"""Candidate <-> UHP session workspace bridge.

One bridge run is one fresh UHP session. The bridge may change the candidate's
working tree, and nothing else: it never checkpoints, promotes, or rejects, and
never moves accepted state, a branch, or HEAD. After a successful sync the
candidate is simply dirty; the Workspace Broker remains the only authority for
checkpoint_candidate(), promote(), and reject().
"""

from __future__ import annotations

import shutil
from importlib import resources
from pathlib import Path
from typing import ClassVar

from cloudeo.bridge import remote_helper as helper
from cloudeo.bridge.bundle import (
    BridgeError,
    InputBundle,
    apply_delta,
    build_input_bundle,
    new_run_id,
    validate_output_bundle,
)
from cloudeo.bridge.models import (
    BridgeLimits,
    BridgeSyncError,
    WorkspaceBridgeResult,
    WorkspaceBridgeTask,
)
from cloudeo.execution.contracts import ExecutionOutcome, HarnessTaskExecution
from cloudeo.execution.dispatch import ExecutionDispatcher
from cloudeo.uhp.client import UHPClient, UHPError
from cloudeo.uhp.models import UHPFile, UHPTaskRequest
from cloudeo.workspace.broker import WorkspaceBroker
from cloudeo.workspace.models import CandidateWorkspace

HELPER_SOURCE = resources.files("cloudeo.bridge").joinpath("remote_helper.py").read_bytes()
# Runtime states in which the remote workspace is not read at all.
_UNOBSERVED = {"unknown", "in_progress"}
_NOT_COMPLETED = {"failed", "cancelled"}


def bridge_instructions(run_id: str, task: str) -> str:
    """Transport steps, clearly separated from the user's task."""
    helper_cmd = f"python3 {helper.HELPER_NAME}"
    return (
        "=== CLOUDEO WORKSPACE BRIDGE: transport protocol (not part of the task) ===\n"
        f"Bridge run id: {run_id}\n"
        "Two files are attached: the bridge helper and the project snapshot.\n"
        "BEFORE starting the task:\n"
        f"  1. Run: {helper_cmd} unpack --run-id {run_id}\n"
        "     It extracts the project into the current working directory and checks\n"
        "     the bridge run metadata. Stop and report the error if it fails.\n"
        "  2. Work only on that extracted project, in the current working directory.\n"
        "AFTER finishing the task, before your final answer:\n"
        f"  3. Run: {helper_cmd} pack-delta --run-id {run_id}\n"
        f"     It writes {helper.output_archive_name(run_id)} in the current working\n"
        "     directory. That file is the only bridge output; do not create, rename,\n"
        "     or edit any other cloudeo-bridge-output-* file.\n"
        "Do not modify or delete the bridge helper or the input snapshot.\n"
        "=== END OF BRIDGE PROTOCOL ===\n\n"
        "=== TASK ===\n"
        f"{task}\n"
    )


class UHPWorkspaceBridge:
    """Transports a candidate to one fresh UHP session and its delta back."""

    # This bridge moves files both ways. It does not change the base
    # UHPHarnessAgentAdapter, which still has supports_workspace_sync = False.
    supports_workspace_sync: ClassVar[bool] = True

    def __init__(
        self,
        broker: WorkspaceBroker,
        client: UHPClient,
        dispatcher: ExecutionDispatcher,
        *,
        limits: BridgeLimits | None = None,
        staging_root: Path | None = None,
    ):
        if dispatcher.harness_task is None:
            raise ValueError("The dispatcher has no harness-task backend.")
        self.broker = broker
        self.client = client
        self.dispatcher = dispatcher
        self.limits = limits or BridgeLimits()
        self.staging_root = staging_root

    async def run(
        self, candidate: CandidateWorkspace, task: WorkspaceBridgeTask
    ) -> WorkspaceBridgeResult:
        # Read-only identity check; the broker is never asked to change state.
        inspection = self.broker.inspect_candidate(candidate)
        run_id = new_run_id()
        bundle = build_input_bundle(candidate, inspection.head_commit, run_id, self.limits)
        helper_file = await self.client.upload_file(
            helper.HELPER_NAME, HELPER_SOURCE, media_type="text/x-python"
        )
        input_file = await self.client.upload_file(
            helper.input_archive_name(run_id), bundle.archive, media_type="application/gzip"
        )
        request = HarnessTaskExecution(
            task=UHPTaskRequest(
                input=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "input_text", "text": bridge_instructions(run_id, task.task)},
                            {"type": "input_file", "file_id": helper_file.id},
                            {"type": "input_file", "file_id": input_file.id},
                        ],
                    }
                ],
                harness_id=task.harness_id,
                model=task.model,
                max_step=task.max_step,
                timeout_seconds=task.timeout_seconds,
                # One bridge run is one fresh session: no previous_response_id.
            )
        )
        outcome = await self.dispatcher.execute(request)
        return await self._sync(candidate, bundle, run_id, outcome)

    async def _sync(
        self,
        candidate: CandidateWorkspace,
        bundle: InputBundle,
        run_id: str,
        outcome: ExecutionOutcome,
    ) -> WorkspaceBridgeResult:
        session_id = outcome.runtime.session_id
        base = {
            "outcome": outcome,
            "bridge_run_id": run_id,
            "session_id": session_id,
            "input_file_count": len(bundle.manifest.files),
        }

        def result(status: str, code: str | None = None, message: str = "", **paths):
            error = BridgeSyncError(code=code, message=message) if code else None
            return WorkspaceBridgeResult(workspace_sync_status=status, error=error, **base, **paths)

        if outcome.status in _UNOBSERVED:
            return result(
                "skipped",
                "runtime_state_unobserved",
                f"Runtime state {outcome.status!r}: the remote workspace was not read.",
            )
        if outcome.status in _NOT_COMPLETED:
            return result(
                "skipped",
                "runtime_not_completed",
                f"Runtime status {outcome.status!r}: remote state was not imported.",
            )
        if session_id is None:
            return result("failed", "missing_session_id", "The response has no session_id.")

        name = helper.output_archive_name(run_id)
        try:
            listing = await self.client.list_session_files(session_id)
        except UHPError as exc:
            return result("failed", "artifact_listing_failed", str(exc))
        matches = [item for item in listing.files if _is_output(item, name)]
        if not matches:
            return result("failed", "output_artifact_missing", f"No artifact named {name}.")
        if len(matches) > 1:
            return result(
                "failed", "output_artifact_ambiguous", f"{len(matches)} artifacts named {name}."
            )
        artifact = matches[0]
        if not artifact.container_id:
            return result("failed", "output_artifact_invalid", "The artifact has no container_id.")
        if artifact.size is not None and artifact.size > self.limits.max_bundle_bytes:
            return result("failed", "invalid_bundle", "The output artifact exceeds the size limit.")
        try:
            content = await self.client.download_container_file(
                artifact.container_id, artifact.id, max_bytes=self.limits.max_bundle_bytes
            )
        except UHPError as exc:
            return result("failed", "artifact_download_failed", str(exc))

        try:
            delta = validate_output_bundle(
                content.content, bundle.manifest, self.limits, self.staging_root
            )
        except BridgeError as exc:
            return result("failed", exc.code, str(exc))
        try:
            applied = apply_delta(candidate.local_path, delta, bundle.manifest)
        except BridgeError as exc:
            return result("failed", exc.code, str(exc))
        finally:
            shutil.rmtree(delta.staging, ignore_errors=True)
        return result(
            "synced",
            added_paths=applied.added,
            changed_paths=applied.changed,
            deleted_paths=applied.deleted,
            ignored_paths=applied.ignored,
        )


def _is_output(item: UHPFile, name: str) -> bool:
    """Exactly this run's archive at the workspace root; never another run's."""
    if item.filename != name:
        return False
    path = (item.model_extra or {}).get("path")
    return path is None or path == name
