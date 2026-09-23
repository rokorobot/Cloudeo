"""LongHorizon CLI executor bound to one CandidateWorkspace through the bridge.

Composes the UHP Workspace Bridge (ADR-017) with the LongHorizon AgentAdapter
contract (ADR-016): each episode moves the bound candidate into one fresh UHP
session, the harness works on it, and the validated delta is applied back to
the same candidate. The candidate is then dirty and unverified; this adapter
never checkpoints, promotes, or rejects.

Environment: the executor's filesystem is the bound CandidateWorkspace, not the
LongHorizon Environment passed to run_episode(), which is accepted for protocol
compatibility and never called. That is safe only because this adapter is
eligible for the cli_executor role alone (see roles.py).

Live trajectory: the bridge does not stream a native LongHorizon trajectory, so
live_trajectory_path is accepted and never written; nothing is fabricated.
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

from cloudeo.bridge.bridge import UHPWorkspaceBridge
from cloudeo.bridge.bundle import BridgeInputError
from cloudeo.bridge.models import WorkspaceBridgeResult, WorkspaceBridgeTask
from cloudeo.longhorizon.adapter import HarnessExecutionProfile, episode_result_from_outcome
from cloudeo.uhp.client import UHPError
from cloudeo.workspace.broker import WorkspaceBrokerError
from cloudeo.workspace.models import CandidateWorkspace

WORKSPACE_SYNC_FAILED = "workspace_sync_failed"
CANDIDATE_UNAVAILABLE = "candidate_unavailable"


class UHPWorkspaceExecutorAdapter:
    """AgentAdapter for the LongHorizon cli_executor role, bound to one candidate.

    Multiple episodes may run against the same candidate; each is a fresh UHP
    session (no previous_response_id), created by the bridge.
    """

    # Workspace-capable because it owns both the candidate and the bridge.
    supports_workspace_sync: ClassVar[bool] = True

    def __init__(
        self,
        profile: HarnessExecutionProfile,
        bridge: UHPWorkspaceBridge,
        candidate: CandidateWorkspace,
        *,
        clock: Callable[[], float] = time.monotonic,
    ):
        if not bridge.supports_workspace_sync:
            raise ValueError("The bridge does not synchronize workspaces.")
        self.profile = profile
        self.bridge = bridge
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
        problem = self._candidate_problem()
        if problem is not None:
            return self._not_started(started, problem)
        task = WorkspaceBridgeTask(
            task=prompt,
            harness_id=self.profile.harness_id,
            model=self.profile.model,
            max_step=self.profile.max_step,
            timeout_seconds=budget.max_duration_seconds,
        )
        try:
            result = await self.bridge.run(self.candidate, task)
        except (WorkspaceBrokerError, BridgeInputError) as exc:
            return self._not_started(started, (CANDIDATE_UNAVAILABLE, str(exc)))
        except UHPError as exc:
            return self._not_started(started, ("workspace_upload_failed", str(exc)))
        episode_ms = round((self._clock() - started) * 1000)
        return self._episode_result(result, budget, episode_ms)

    def _candidate_problem(self) -> tuple[str, str] | None:
        """Existing broker semantics only: identity, worktree, and staleness."""
        broker = self.bridge.broker
        try:
            broker.inspect_candidate(self.candidate)
            accepted = broker.accepted_state().accepted_commit
        except WorkspaceBrokerError as exc:
            return CANDIDATE_UNAVAILABLE, str(exc)
        if accepted != self.candidate.base_commit:
            return (
                "candidate_stale",
                (
                    f"accepted state moved to {accepted}; candidate "
                    f"{self.candidate.candidate_id} began from {self.candidate.base_commit}"
                ),
            )
        return None

    def _episode_result(
        self, result: WorkspaceBridgeResult, budget: EpisodeBudget, episode_ms: int
    ) -> EpisodeResult:
        base = episode_result_from_outcome(
            result.outcome, budget=budget, episode_duration_ms=episode_ms
        )
        status, error = base.status, base.error
        synced = result.workspace_sync_status == "synced"
        if result.outcome.status == "completed" and not synced:
            # The runtime finished but its work did not reach the candidate:
            # LongHorizon must not continue as though the candidate changed.
            detail = result.error.code if result.error else result.workspace_sync_status
            message = result.error.message if result.error else "no delta was applied"
            status, error = "error", f"{WORKSPACE_SYNC_FAILED}: {detail}: {message}"
        metadata = {**base.metadata, **self._workspace_metadata(result)}
        return EpisodeResult(
            status=status,
            actions_log=base.actions_log,
            error=error,
            duration_ms=base.duration_ms,
            metadata=metadata,
        )

    def _workspace_metadata(self, result: WorkspaceBridgeResult | None) -> dict[str, Any]:
        candidate = self.candidate
        error = result.error if result is not None else None
        return {
            "supports_workspace_sync": True,
            "workspace_sync_status": result.workspace_sync_status if result else "skipped",
            "workspace_sync_error": (
                {"code": error.code, "message": error.message} if error else None
            ),
            "bridge_run_id": result.bridge_run_id if result else None,
            "workspace_id": candidate.workspace_id,
            "candidate_id": candidate.candidate_id,
            "candidate_base_commit": candidate.base_commit,
            "added_paths": list(result.added_paths) if result else [],
            "changed_paths": list(result.changed_paths) if result else [],
            "deleted_paths": list(result.deleted_paths) if result else [],
            "ignored_paths": list(result.ignored_paths) if result else [],
            # Synced means the candidate changed; it is never independent
            # verification, and a dirty candidate is never accepted state.
            "independently_verified": False,
        }

    def _not_started(self, started: float, problem: tuple[str, str]) -> EpisodeResult:
        code, message = problem
        metadata = self._workspace_metadata(None)
        metadata["workspace_sync_error"] = {"code": code, "message": message}
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
