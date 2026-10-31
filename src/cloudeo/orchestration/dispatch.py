"""Control-owned executor dispatch (V2C-02 slice 1, ADR-037).

The only orchestration entry point that sends a primary_code_executor task to
a harness. It dispatches only after `machine.begin_attempt` has accepted the
attempt on an approved, executing WorkOrder, and only the exact harness and
model of the bound profile it approved:

- `begin_attempt` refuses (TransitionRejected) outside EXECUTING, for a
  block out of order, or for a profile that is not the bound primary or an
  approved fallback with its condition and evidence; nothing is dispatched.
- If `begin_attempt` raises attention instead (attempts exhausted, an
  independence gap), nothing is dispatched.
- A task naming a different harness or model than the approved profile is
  refused before `begin_attempt`, so no attempt is recorded for it.

Policy stays in cloudeo.control; this module only refuses to dispatch what
control did not approve. Existing executor paths (the workspace bridge and the
LongHorizon adapters) do not go through it yet, so V2C-02 remains DEFERRED.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from cloudeo.control import machine
from cloudeo.control.model import (
    AgentProfile,
    BlockStatus,
    EvidenceRef,
    FallbackCondition,
    ProfileRef,
    WorkOrder,
)
from cloudeo.execution.contracts import ExecutionOutcome, HarnessTaskExecution
from cloudeo.execution.dispatch import HarnessTaskExecutionBackend
from cloudeo.uhp.models import UHPTaskRequest


class DispatchRefused(ValueError):
    """The task does not match what control approved; nothing was dispatched."""


class AttemptDispatch(BaseModel):
    """The WorkOrder after begin_attempt, and the outcome if a task was sent."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    work_order: WorkOrder
    dispatched: bool
    outcome: ExecutionOutcome | None = None


def _approved_task(work_order: WorkOrder, profile: ProfileRef, task: UHPTaskRequest):
    definition = work_order.execution_profile.profile(profile)
    if not isinstance(definition, AgentProfile):
        raise DispatchRefused(f"{profile.profile_id} is not an agent profile")
    harness, model = definition.runtime.harness_id, definition.model.model_id
    for field, approved in (("harness_id", harness), ("model", model)):
        requested = getattr(task, field)
        if requested is not None and requested != approved:
            raise DispatchRefused(
                f"task {field} {requested!r} is not the approved {approved!r} of "
                f"{profile.profile_id} v{profile.version}"
            )
    return HarnessTaskExecution(
        task=task.model_copy(update={"harness_id": harness, "model": model})
    )


async def dispatch_attempt(
    work_order: WorkOrder,
    block_id: str,
    *,
    profile: ProfileRef,
    task: UHPTaskRequest,
    backend: HarnessTaskExecutionBackend,
    fallback_condition: FallbackCondition | None = None,
    evidence: EvidenceRef | None = None,
) -> AttemptDispatch:
    """Begin the attempt through control, then dispatch exactly the approved task."""
    if not any(p.ref == profile for p in work_order.execution_profile.profiles):
        raise DispatchRefused(f"{profile.profile_id} v{profile.version} is not in the envelope")
    request = _approved_task(work_order, profile, task)
    started = machine.begin_attempt(
        work_order, block_id, profile=profile,
        fallback_condition=fallback_condition, evidence=evidence,
    )  # fmt: skip
    # begin_attempt validated the block; dispatch only if it recorded this attempt.
    attempts = len(work_order.block(block_id).attempts)
    block = started.block(block_id)
    if block.status != BlockStatus.RUNNING or len(block.attempts) != attempts + 1:
        return AttemptDispatch(work_order=started, dispatched=False)
    return AttemptDispatch(
        work_order=started, dispatched=True, outcome=await backend.execute(request)
    )
