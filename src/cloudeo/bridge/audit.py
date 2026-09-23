"""Read-only audit transport: a frozen candidate snapshot to one fresh UHP session.

Unlike UHPWorkspaceBridge.run(), nothing returned by the remote session is ever
applied to the candidate. The helper's delta is downloaded and validated only as
evidence of whether the auditor changed its remote copy of the snapshot. After
the audit the candidate and accepted state are checked again, because a report
is only meaningful for the exact state it inspected.

The transport never checkpoints, promotes, or rejects, and calls only the
broker's read-only inspect_candidate() and accepted_state().
"""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from cloudeo.bridge import remote_helper as helper
from cloudeo.bridge.bridge import (
    HELPER_SOURCE,
    fetch_output_artifact,
    require_single_deployment,
)
from cloudeo.bridge.bundle import (
    BridgeError,
    BridgeInputError,
    InputBundle,
    _entries,
    build_input_bundle,
    check_candidate_unchanged,
    new_run_id,
    select_files,
    validate_output_bundle,
)
from cloudeo.bridge.models import (
    BridgeFileEntry,
    BridgeLimits,
    BridgeSyncError,
    InputManifest,
    WorkspaceBridgeTask,
)
from cloudeo.execution.contracts import ExecutionOutcome, HarnessTaskExecution
from cloudeo.execution.dispatch import ExecutionDispatcher
from cloudeo.uhp.client import UHPClient
from cloudeo.uhp.models import UHPTaskRequest
from cloudeo.workspace.broker import WorkspaceBroker, WorkspaceBrokerError
from cloudeo.workspace.models import CandidateWorkspace

_UNOBSERVED = {"unknown", "in_progress"}
_NOT_COMPLETED = {"failed", "cancelled"}

RemoteEvidence = Literal["unchanged", "mutated", "failed", "skipped"]


def snapshot_content_sha256(files: tuple[BridgeFileEntry, ...]) -> str:
    """Identity of the file state alone: every path, size, SHA-256, and executable bit.

    Unlike the input manifest hash, it excludes the run ID and limits, so it can
    be recomputed from the candidate later (with the same selection rules) to
    prove that a state is exactly the audited one.
    """
    entries = [entry.model_dump(mode="json") for entry in files]
    return hashlib.sha256(helper._json_bytes({"files": entries})).hexdigest()


def current_content_sha256(candidate: CandidateWorkspace, limits: BridgeLimits) -> str:
    """The candidate's file state now, by exactly the audit snapshot's rules.

    Raises BridgeError (usually BridgeInputError) when the candidate cannot be
    read as a snapshot.
    """
    return snapshot_content_sha256(_entries(select_files(candidate.local_path, limits)))


class WorkspaceAuditSnapshot(BaseModel):
    """The exact candidate state under audit: the bridge's deterministic input bundle.

    manifest_sha256 identifies the exact bundle sent for this run (it includes
    the run ID); content_sha256 identifies the audited file state.
    """

    model_config = ConfigDict(frozen=True)

    workspace_id: str
    candidate_id: str
    base_commit: str
    # Candidate HEAD when the snapshot was taken (uncheckpointed edits are in the files).
    head_commit: str
    manifest: InputManifest
    manifest_sha256: str
    archive: bytes

    @property
    def file_count(self) -> int:
        return len(self.manifest.files)

    @property
    def content_sha256(self) -> str:
        return snapshot_content_sha256(self.manifest.files)


def build_audit_snapshot(
    candidate: CandidateWorkspace, head_commit: str, run_id: str, limits: BridgeLimits
) -> WorkspaceAuditSnapshot:
    """Same selection, archive, and hashing rules as the bridge; no .git, no ignored files."""
    bundle = build_input_bundle(candidate, head_commit, run_id, limits)
    return WorkspaceAuditSnapshot(
        workspace_id=candidate.workspace_id,
        candidate_id=candidate.candidate_id,
        base_commit=candidate.base_commit,
        head_commit=head_commit,
        manifest=bundle.manifest,
        manifest_sha256=bundle.manifest_sha256,
        archive=bundle.archive,
    )


class AuditPreconditionError(Exception):
    """The candidate cannot be audited; raised before anything is uploaded."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class WorkspaceAuditResult(BaseModel):
    """Runtime truth plus the evidence that makes an audit report attributable.

    remote_evidence "unchanged" proves only that the auditor's remote copy of the
    snapshot was unchanged; it says nothing about whether the report is right.
    """

    model_config = ConfigDict(frozen=True)

    outcome: ExecutionOutcome
    audit_run_id: str
    session_id: str | None = None
    snapshot: WorkspaceAuditSnapshot
    remote_evidence: RemoteEvidence
    remote_added: tuple[str, ...] = ()
    remote_changed: tuple[str, ...] = ()
    remote_deleted: tuple[str, ...] = ()
    # Subset of remote_changed whose content is unchanged: only the executable bit.
    remote_mode_changed: tuple[str, ...] = ()
    evidence_error: BridgeSyncError | None = None
    candidate_unchanged: bool
    candidate_change: str | None = None
    accepted_state_unchanged: bool
    accepted_state_change: str | None = None

    @property
    def remote_mutated(self) -> bool:
        return bool(self.remote_added or self.remote_changed or self.remote_deleted)


def audit_instructions(run_id: str, prompt: str) -> str:
    """Transport steps for a read-only audit, clearly separated from the audit prompt."""
    helper_cmd = f"python3 {helper.HELPER_NAME}"
    return (
        "=== CLOUDEO WORKSPACE AUDIT: transport protocol (not part of the audit) ===\n"
        f"Bridge run id: {run_id}\n"
        "Two files are attached: the bridge helper and a frozen snapshot of the project\n"
        "to audit.\n"
        "BEFORE auditing:\n"
        f"  1. Run: {helper_cmd} unpack --run-id {run_id}\n"
        "     It extracts the project snapshot into the current working directory and\n"
        "     checks the run metadata. Stop and report the error if it fails.\n"
        "  2. The extracted snapshot is authoritative: it is exactly the state under\n"
        "     audit. If it contains AGENTS.md, CLAUDE.md, QWEN.md or GEMINI.md, read it\n"
        "     now and follow its project instructions where they apply to auditing.\n"
        "  3. Wherever the audit prompt names a local workspace path or the task\n"
        "     workspace, it means the current working directory with the extracted\n"
        "     project.\n"
        "AUDIT RULE (read-only):\n"
        "  - Inspect only. Do not repair anything. Do not create, modify, move, or\n"
        "    delete project files, and do not create deliverables.\n"
        "  - Commands you run (tests, builds, linters) must not leave new or changed\n"
        "    files in the project: send caches and outputs to a temporary directory\n"
        "    outside it (for example PYTHONDONTWRITEBYTECODE=1, pytest -p no:cacheprovider).\n"
        "  - Your final answer is the audit report required by the audit prompt below.\n"
        "BEFORE your final answer:\n"
        f"  4. Run: {helper_cmd} pack-delta --run-id {run_id}\n"
        "     It records whether the project snapshot changed during the audit. It is\n"
        "     evidence only and is never imported. Do not create, rename, or edit any\n"
        "     cloudeo-bridge-output-* file.\n"
        "Do not modify or delete the bridge helper or the input snapshot.\n"
        "=== END OF AUDIT PROTOCOL ===\n\n"
        "=== AUDIT PROMPT ===\n"
        f"{prompt}\n"
    )


class UHPWorkspaceAuditTransport:
    """Sends a frozen candidate snapshot to one fresh UHP session for a read-only audit."""

    def __init__(
        self,
        broker: WorkspaceBroker,
        client: UHPClient,
        dispatcher: ExecutionDispatcher,
        *,
        limits: BridgeLimits | None = None,
        staging_root: Path | None = None,
    ):
        require_single_deployment(client, dispatcher)
        self.broker = broker
        self.client = client
        self.dispatcher = dispatcher
        self.limits = limits or BridgeLimits()
        self.staging_root = staging_root

    async def run(
        self, candidate: CandidateWorkspace, task: WorkspaceBridgeTask
    ) -> WorkspaceAuditResult:
        run_id = new_run_id()
        snapshot = self._freeze(candidate, run_id)
        helper_file = await self.client.upload_file(
            helper.HELPER_NAME, HELPER_SOURCE, media_type="text/x-python"
        )
        input_file = await self.client.upload_file(
            helper.input_archive_name(run_id), snapshot.archive, media_type="application/gzip"
        )
        request = HarnessTaskExecution(
            task=UHPTaskRequest(
                input=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "input_text", "text": audit_instructions(run_id, task.task)},
                            {"type": "input_file", "file_id": helper_file.id},
                            {"type": "input_file", "file_id": input_file.id},
                        ],
                    }
                ],
                harness_id=task.harness_id,
                model=task.model,
                max_step=task.max_step,
                timeout_seconds=task.timeout_seconds,
                # One audit is one fresh session: no previous_response_id, so no
                # executor session, response, or remote workspace is reused.
            )
        )
        outcome = await self.dispatcher.execute(request)
        evidence = await self._remote_evidence(outcome, snapshot, run_id)
        # The report is only valid for the state it inspected: check both again.
        candidate_change = self._candidate_change(candidate, snapshot)
        accepted_change = self._accepted_change(candidate)
        return WorkspaceAuditResult(
            outcome=outcome,
            audit_run_id=run_id,
            session_id=outcome.runtime.session_id,
            snapshot=snapshot,
            candidate_unchanged=candidate_change is None,
            candidate_change=candidate_change,
            accepted_state_unchanged=accepted_change is None,
            accepted_state_change=accepted_change,
            **evidence,
        )

    def _freeze(self, candidate: CandidateWorkspace, run_id: str) -> WorkspaceAuditSnapshot:
        """Public broker checks, then the snapshot; nothing is uploaded on failure."""
        try:
            inspection = self.broker.inspect_candidate(candidate)
            accepted = self.broker.accepted_state().accepted_commit
        except WorkspaceBrokerError as exc:
            raise AuditPreconditionError("candidate_unavailable", str(exc)) from exc
        if accepted != candidate.base_commit:
            raise AuditPreconditionError(
                "candidate_stale",
                f"accepted state moved to {accepted}; candidate "
                f"{candidate.candidate_id} began from {candidate.base_commit}",
            )
        try:
            return build_audit_snapshot(candidate, inspection.head_commit, run_id, self.limits)
        except BridgeInputError as exc:
            raise AuditPreconditionError("candidate_unavailable", str(exc)) from exc

    async def _remote_evidence(
        self, outcome: ExecutionOutcome, snapshot: WorkspaceAuditSnapshot, run_id: str
    ) -> dict:
        def failed(code: str, message: str) -> dict:
            return {
                "remote_evidence": "failed",
                "evidence_error": BridgeSyncError(code=code, message=message),
            }

        if outcome.status in _UNOBSERVED:
            return {
                "remote_evidence": "skipped",
                "evidence_error": BridgeSyncError(
                    code="runtime_state_unobserved",
                    message=f"Runtime state {outcome.status!r}: the remote workspace was not read.",
                ),
            }
        if outcome.status in _NOT_COMPLETED:
            return {
                "remote_evidence": "skipped",
                "evidence_error": BridgeSyncError(
                    code="runtime_not_completed",
                    message=f"Runtime status {outcome.status!r}: no audit evidence was read.",
                ),
            }
        session_id = outcome.runtime.session_id
        if session_id is None:
            return failed("missing_session_id", "The response has no session_id.")
        # The delta must echo this snapshot's identity and input_manifest_sha256.
        sent = InputBundle(
            manifest=snapshot.manifest,
            archive=snapshot.archive,
            manifest_sha256=snapshot.manifest_sha256,
        )
        try:
            data = await fetch_output_artifact(self.client, session_id, run_id, self.limits)
            delta = validate_output_bundle(data, sent, self.limits, self.staging_root)
        except BridgeError as exc:
            return failed(exc.code, str(exc))
        # Evidence only: the validated delta is inspected and discarded, never applied.
        shutil.rmtree(delta.staging, ignore_errors=True)
        manifest = delta.manifest
        sent_by_path = {entry.path: entry for entry in snapshot.manifest.files}
        changed = tuple(entry.path for entry in manifest.changed)
        return {
            "remote_evidence": "mutated"
            if (manifest.added or manifest.changed or manifest.deleted)
            else "unchanged",
            "remote_added": tuple(entry.path for entry in manifest.added),
            "remote_changed": changed,
            "remote_deleted": tuple(manifest.deleted),
            "remote_mode_changed": tuple(
                entry.path
                for entry in manifest.changed
                if entry.sha256 == sent_by_path[entry.path].sha256
            ),
        }

    def _candidate_change(
        self, candidate: CandidateWorkspace, snapshot: WorkspaceAuditSnapshot
    ) -> str | None:
        try:
            head = self.broker.inspect_candidate(candidate).head_commit
        except WorkspaceBrokerError as exc:
            return f"the candidate can no longer be inspected: {exc}"
        if head != snapshot.head_commit:
            return f"candidate HEAD moved from {snapshot.head_commit} to {head}"
        try:
            check_candidate_unchanged(candidate.local_path, snapshot.manifest, self.limits)
        except BridgeError as exc:
            # Includes CandidateDriftError; its wording refers to execution.
            return str(exc).replace("during execution", "during the audit")
        return None

    def _accepted_change(self, candidate: CandidateWorkspace) -> str | None:
        try:
            accepted = self.broker.accepted_state().accepted_commit
        except WorkspaceBrokerError as exc:
            return f"accepted state could not be read: {exc}"
        if accepted != candidate.base_commit:
            return (
                f"accepted state moved to {accepted} during the audit; candidate "
                f"{candidate.candidate_id} began from {candidate.base_commit}"
            )
        return None
