"""Independent LongHorizon CLI auditor over a frozen CandidateWorkspace snapshot.

Each episode freezes the bound candidate into the bridge's deterministic
snapshot, sends it to one fresh UHP session through UHPWorkspaceAuditTransport,
and returns the auditor's natural-language report for LongHorizon's own audit
machinery (control header, format repair, parse, acceptance guard). Nothing the
auditor does remotely reaches the candidate.

"done" means only: the auditor runtime completed, it inspected exactly the bound
snapshot, its remote copy of the snapshot was unchanged, and the candidate and
accepted state were unchanged throughout. It is never audit "complete", and never
verification: independently_verified stays False; a later gate decides.

"Independent" means a separate execution boundary (a fresh session and remote
workspace, sharing only the Cloudeo-built snapshot with the executor), not a
different model or provider.

Environment and trajectory: as for the workspace executor, the LongHorizon
Environment is accepted for protocol compatibility and never called, and
live_trajectory_path is never written.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any, ClassVar

try:
    from lh_harness.environment.base import Environment
    from lh_harness.types import EpisodeBudget, EpisodeResult
except ModuleNotFoundError as exc:  # pragma: no cover - depends on the install
    raise ImportError(
        "cloudeo.longhorizon requires the optional 'longhorizon' extra "
        "(LongHorizon-Harness pinned at v0.1.7)."
    ) from exc

from cloudeo.bridge.audit import (
    AuditPreconditionError,
    UHPWorkspaceAuditTransport,
    WorkspaceAuditResult,
)
from cloudeo.bridge.models import WorkspaceBridgeTask
from cloudeo.longhorizon.adapter import HarnessExecutionProfile, episode_result_from_outcome
from cloudeo.uhp.client import UHPError
from cloudeo.workspace.models import CandidateWorkspace

AUDITOR_WORKSPACE_MUTATION_DETECTED = "auditor_workspace_mutation_detected"
CANDIDATE_CHANGED_DURING_AUDIT = "candidate_changed_during_audit"
CANDIDATE_STALE_DURING_AUDIT = "candidate_stale_during_audit"
AUDIT_EVIDENCE_INVALID = "audit_evidence_invalid"
READ_ONLY_SNAPSHOT = "read_only_snapshot"


class UHPWorkspaceAuditorAdapter:
    """AgentAdapter for the LongHorizon cli_auditor role, bound to one candidate."""

    # It can inspect a synchronized candidate snapshot. It can NOT change the
    # candidate: workspace_access says which kind of sync this is.
    supports_workspace_sync: ClassVar[bool] = True
    workspace_access: ClassVar[str] = READ_ONLY_SNAPSHOT

    def __init__(
        self,
        profile: HarnessExecutionProfile,
        transport: UHPWorkspaceAuditTransport,
        candidate: CandidateWorkspace,
        *,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.profile = profile
        self.transport = transport
        self.candidate = candidate
        self._clock = clock

    async def run_episode(
        self,
        prompt: str,
        env: Environment,
        budget: EpisodeBudget,
        live_trajectory_path: str | None = None,
    ) -> EpisodeResult:
        # `env` and `live_trajectory_path` are accepted for AgentAdapter
        # compatibility only; see the module docstring.
        started = self._clock()
        task = WorkspaceBridgeTask(
            task=prompt,
            harness_id=self.profile.harness_id,
            model=self.profile.model,
            max_step=self.profile.max_step,
            timeout_seconds=budget.max_duration_seconds,
        )
        try:
            result = await self.transport.run(self.candidate, task)
        except AuditPreconditionError as exc:
            return self._not_started(started, exc.code, str(exc))
        except UHPError as exc:
            return self._not_started(started, "workspace_upload_failed", str(exc))
        episode_ms = round((self._clock() - started) * 1000)
        return self._episode_result(result, budget, episode_ms)

    def _episode_result(
        self, result: WorkspaceAuditResult, budget: EpisodeBudget, episode_ms: int
    ) -> EpisodeResult:
        base = episode_result_from_outcome(
            result.outcome, budget=budget, episode_duration_ms=episode_ms
        )
        problems = _problems(result)
        status, error = base.status, base.error
        metadata = {**base.metadata, **self._audit_metadata(result, problems)}
        if problems and result.outcome.status == "completed":
            # The report cannot be attributed to the audited state, or the
            # auditor was not read-only: never "done", and the text is kept
            # only as untrusted diagnostics, never as the role's output.
            code, message = problems[0]
            status, error = "error", f"{code}: {message}"
            metadata["untrusted_auditor_output"] = metadata["assistant_visible_output"]
            metadata["assistant_visible_output"] = ""
            metadata["actions_log_diagnostics_only"] = True
        return EpisodeResult(
            status=status,
            actions_log=base.actions_log,
            error=error,
            duration_ms=base.duration_ms,
            metadata=metadata,
        )

    def _audit_metadata(
        self, result: WorkspaceAuditResult | None, problems: list[tuple[str, str]]
    ) -> dict[str, Any]:
        candidate = self.candidate
        snapshot = result.snapshot if result is not None else None
        metadata: dict[str, Any] = {
            "supports_workspace_sync": True,
            "workspace_access": READ_ONLY_SNAPSHOT,
            "workspace_id": candidate.workspace_id,
            "candidate_id": candidate.candidate_id,
            "candidate_base_commit": candidate.base_commit,
            "audit_transport_run_id": result.audit_run_id if result else None,
            "audit_snapshot_head": snapshot.head_commit if snapshot else None,
            "audit_snapshot_manifest_sha256": snapshot.manifest_sha256 if snapshot else None,
            "audit_snapshot_content_sha256": snapshot.content_sha256 if snapshot else None,
            "audit_snapshot_file_count": snapshot.file_count if snapshot else None,
            "audit_snapshot_unchanged": result.candidate_unchanged if result else None,
            "accepted_state_unchanged": result.accepted_state_unchanged if result else None,
            "auditor_remote_evidence": result.remote_evidence if result else "skipped",
            "auditor_remote_workspace_unchanged": (
                result.remote_evidence == "unchanged" if result else None
            ),
            "auditor_workspace_mutations": {
                "added": list(result.remote_added) if result else [],
                "changed": list(result.remote_changed) if result else [],
                "deleted": list(result.remote_deleted) if result else [],
                "mode_changed": list(result.remote_mode_changed) if result else [],
            },
            "audit_evidence_error": (
                result.evidence_error.model_dump() if result and result.evidence_error else None
            ),
            "audit_invalid_reasons": [code for code, _ in problems],
            # An independent audit EXECUTION boundary, not verification: the
            # later gate decides whether the parsed report is sufficient.
            "independently_verified": False,
        }
        if result is not None and result.remote_evidence in ("unchanged", "mutated"):
            metadata.update(_native_guard_metadata(result))
        return metadata

    def _not_started(self, started: float, code: str, message: str) -> EpisodeResult:
        metadata = self._audit_metadata(None, [(code, message)])
        metadata["cloudeo_runtime_status"] = None  # no harness task was started
        return EpisodeResult(
            status="error",
            actions_log="",
            error=f"{code}: {message}",
            duration_ms=round((self._clock() - started) * 1000),
            metadata={
                **metadata,
                "assistant_visible_output": "",
                "actions_log_diagnostics_only": True,
            },
        )


def _problems(result: WorkspaceAuditResult) -> list[tuple[str, str]]:
    """Every reason the report is not attributable to a read-only audit of the snapshot."""
    problems = []
    if not result.accepted_state_unchanged:
        problems.append((CANDIDATE_STALE_DURING_AUDIT, result.accepted_state_change or ""))
    if not result.candidate_unchanged:
        problems.append((CANDIDATE_CHANGED_DURING_AUDIT, result.candidate_change or ""))
    if result.remote_evidence == "mutated":
        paths = [*result.remote_added, *result.remote_changed, *result.remote_deleted]
        shown = ", ".join(paths[:20]) + (", ..." if len(paths) > 20 else "")
        problems.append(
            (AUDITOR_WORKSPACE_MUTATION_DETECTED, f"the auditor changed project files: {shown}")
        )
    if result.remote_evidence == "failed" and result.evidence_error is not None:
        error = result.evidence_error
        problems.append((AUDIT_EVIDENCE_INVALID, f"{error.code}: {error.message}"))
    return problems


def _native_guard_metadata(result: WorkspaceAuditResult) -> dict[str, Any]:
    """LongHorizon's own read-only guard keys (pinned adapters/claude_permissions.py).

    The task workspace here is the CandidateWorkspace, which never receives
    auditor writes, so it always still holds the pre-audit snapshot: "restored"
    is true, and LongHorizon therefore never treats a remote deletion as a
    confirmed artifact deletion.
    """
    mutations = {
        "added": list(result.remote_added),
        "changed": list(result.remote_changed),
        "deleted": list(result.remote_deleted),
        "type_changed": [],
    }
    return {
        "verifier_workspace_guard": True,
        "verifier_workspace_restore_on_mutation": True,
        "verifier_workspace_restored": True,
        "verifier_workspace_mutation_detected": result.remote_mutated,
        "verifier_workspace_mutations": mutations,
        "verifier_workspace_mutation_counts": {k: len(v) for k, v in mutations.items()},
    }
