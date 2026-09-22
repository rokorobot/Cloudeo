"""LongHorizon-Harness AgentAdapter backed by Cloudeo's UHP execution path.

The adapter runs one bounded harness task per episode through the existing
ExecutionDispatcher and maps the ExecutionOutcome onto LongHorizon's
EpisodeResult. It makes no routing decision: the harness and model come from an
explicit profile.

Workspace limitation: the harness works in its HarnessRouter session
workspace, not in the LongHorizon Environment passed to run_episode(). Until a
candidate<->UHP file bridge exists, file changes made by the harness are not
visible to roles that inspect that Environment. supports_workspace_sync is
therefore False, and the adapter must not be bound to file-mutating executor
or workspace-inspecting auditor roles.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field

try:
    from lh_harness.environment.base import Environment
    from lh_harness.types import EpisodeBudget, EpisodeResult
except ModuleNotFoundError as exc:  # pragma: no cover - depends on the install
    raise ImportError(
        "cloudeo.longhorizon requires the optional 'longhorizon' extra "
        "(LongHorizon-Harness pinned at v0.1.7)."
    ) from exc

from cloudeo.execution.contracts import ExecutionOutcome, HarnessTaskExecution
from cloudeo.execution.dispatch import ExecutionDispatcher
from cloudeo.uhp.models import UHPTaskRequest, UHPTaskResult

# incomplete_details.reason values that explicitly name a budget: HarnessRouter
# CE reports max_steps/timeout; the others are the UHP budget field names.
BUDGET_INCOMPLETE_REASONS = frozenset(
    {"max_steps", "max_step", "timeout", "timeout_seconds", "max_output_tokens"}
)
RUNTIME_STATE_UNOBSERVED = "runtime_state_unobserved"


class HarnessExecutionProfile(BaseModel):
    """An explicitly chosen harness and model. Selection happens elsewhere."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    harness_id: str = Field(min_length=1)
    model: str = Field(min_length=1)
    max_step: int | None = Field(default=None, gt=0)


class UHPHarnessAgentAdapter:
    """LongHorizon AgentAdapter that executes each episode as a fresh UHP task."""

    # No candidate<->HarnessRouter workspace bridge exists yet. Any role binding
    # that needs shared workspace visibility must reject this adapter.
    supports_workspace_sync: ClassVar[bool] = False

    def __init__(
        self,
        profile: HarnessExecutionProfile,
        dispatcher: ExecutionDispatcher,
        *,
        clock: Callable[[], float] = time.monotonic,
    ):
        if dispatcher.harness_task is None:
            raise ValueError("The dispatcher has no harness-task backend.")
        self.profile = profile
        self.dispatcher = dispatcher
        self._clock = clock

    async def run_episode(
        self,
        prompt: str,
        env: Environment,
        budget: EpisodeBudget,
        live_trajectory_path: str | None = None,
    ) -> EpisodeResult:
        # `env` is accepted to satisfy AgentAdapter, and no method is called on
        # it: the harness does not run in this Environment. The live trajectory
        # path is not written; UHP output is returned in actions_log instead.
        started = self._clock()
        request = HarnessTaskExecution(
            task=UHPTaskRequest(
                input=prompt,
                harness_id=self.profile.harness_id,
                model=self.profile.model,
                max_step=self.profile.max_step,
                timeout_seconds=budget.max_duration_seconds,
                # Every episode starts a new session: no previous_response_id.
            )
        )
        outcome = await self.dispatcher.execute(request)
        episode_ms = round((self._clock() - started) * 1000)
        return episode_result_from_outcome(outcome, budget=budget, episode_duration_ms=episode_ms)


def episode_result_from_outcome(
    outcome: ExecutionOutcome,
    *,
    budget: EpisodeBudget,
    episode_duration_ms: int,
) -> EpisodeResult:
    """Map a harness-task outcome to EpisodeResult, preserving the native state.

    EpisodeResult.status "done" means the harness task completed. It is never
    a verification result.
    """
    if outcome.kind != "harness_task":
        raise TypeError("Only harness-task outcomes map to LongHorizon episodes.")
    native = outcome.native_result if isinstance(outcome.native_result, UHPTaskResult) else None
    incomplete_details = native.incomplete_details if native is not None else None
    status, error = _map_status(outcome, incomplete_details, budget, episode_duration_ms)
    runtime = outcome.runtime
    visible = outcome.output_text
    metadata: dict[str, Any] = {
        "cloudeo_runtime_status": outcome.status,
        "requested_harness": runtime.requested_harness,
        "actual_harness": runtime.actual_harness,
        "requested_model": runtime.requested_model,
        "actual_model": runtime.actual_model,
        "model_fallback": runtime.model_fallback,
        "response_id": runtime.response_id,
        "session_id": runtime.session_id,
        "protocol_version": runtime.protocol_version,
        "usage": outcome.cost.harness_usage,
        "execution_duration_ms": outcome.duration_ms,
        "execution_error": outcome.error.model_dump(mode="json") if outcome.error else None,
        "incomplete_details": incomplete_details,
        "supports_workspace_sync": UHPHarnessAgentAdapter.supports_workspace_sync,
        # LongHorizon reads role text from this key; actions_log is diagnostic.
        "assistant_visible_output": visible or "",
        "actions_log_diagnostics_only": visible is None,
    }
    raw = outcome.raw_output
    return EpisodeResult(
        status=status,
        actions_log=json.dumps(raw) if isinstance(raw, list) else (raw or ""),
        error=error,
        duration_ms=episode_duration_ms,
        metadata=metadata,
    )


def _map_status(
    outcome: ExecutionOutcome,
    incomplete_details: dict[str, Any] | None,
    budget: EpisodeBudget,
    episode_duration_ms: int,
) -> tuple[str, str | None]:
    detail = _error_text(outcome)
    match outcome.status:
        case "completed":
            return "done", None
        case "failed":
            return "error", detail or "The harness task failed."
        case "cancelled":
            return "cancelled", detail
        case "incomplete":
            reason = (incomplete_details or {}).get("reason")
            if isinstance(reason, str) and reason in BUDGET_INCOMPLETE_REASONS:
                return "timeout", f"Harness task stopped at a budget: {reason}."
            return "error", f"Harness task incomplete without a budget reason: {reason!r}."
        case "unknown":
            return "error", (
                f"{RUNTIME_STATE_UNOBSERVED}: the final harness task state was not "
                f"observed ({detail or 'no detail'})."
            )
        case "in_progress":
            prefix = f"{RUNTIME_STATE_UNOBSERVED}: the harness task was still in progress"
            if episode_duration_ms >= budget.max_duration_seconds * 1000:
                return "timeout", f"{prefix} when the episode budget was exhausted."
            return "error", f"{prefix}; its final state was not observed."
        case _:
            raise TypeError(f"Unexpected harness-task status {outcome.status!r}.")


def _error_text(outcome: ExecutionOutcome) -> str | None:
    if outcome.error is None:
        return None
    code = f"{outcome.error.code}: " if outcome.error.code else ""
    return f"{outcome.error.source} {code}{outcome.error.message}"
