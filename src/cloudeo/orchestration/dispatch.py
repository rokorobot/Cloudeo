"""Control-owned executor dispatch (V2C-02, ADR-037).

The only producer of `ExecutorAuthorization`, which every write-capable
executor path requires (the workspace bridge and the LongHorizon executor
adapter). An authorization exists only after `machine.begin_attempt` has
accepted the attempt on an approved, executing WorkOrder, and it names the
exact harness and model of the bound profile it approved:

- `begin_attempt` refuses (TransitionRejected) outside EXECUTING, for a
  block out of order, or for a profile that is not the bound primary or an
  approved fallback with its condition and evidence; nothing is dispatched.
- If `begin_attempt` raises attention instead (attempts exhausted, an
  independence gap), nothing is dispatched.
- A task naming a different harness or model than the approved profile is
  refused before `begin_attempt`, so no attempt is recorded for it.

`authorize_executor_attempt` returns the authorization (for a LongHorizon run:
one run is one attempt); `dispatch_attempt` authorizes and sends one task.
Policy stays in cloudeo.control; this module only refuses to dispatch what
control did not approve.
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
from cloudeo.execution.contracts import (
    ExecutionOutcome,
    ExecutorAuthorization,
    HarnessTaskExecution,
)
from cloudeo.execution.dispatch import HarnessTaskExecutionBackend
from cloudeo.uhp.models import UHPTaskRequest


class DispatchRefused(ValueError):
    """The task does not match what control approved; nothing was dispatched."""


class ExecutorAttempt(BaseModel):
    """The WorkOrder after begin_attempt, and the authorization if it recorded one."""

    model_config = ConfigDict(frozen=True)

    work_order: WorkOrder
    authorization: ExecutorAuthorization | None = None


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


def authorize_executor_attempt(
    work_order: WorkOrder,
    block_id: str,
    *,
    profile: ProfileRef,
    fallback_condition: FallbackCondition | None = None,
    evidence: EvidenceRef | None = None,
) -> ExecutorAttempt:
    """Begin the attempt through control; authorize it only if control recorded it."""
    if not any(p.ref == profile for p in work_order.execution_profile.profiles):
        raise DispatchRefused(f"{profile.profile_id} v{profile.version} is not in the envelope")
    definition = work_order.execution_profile.profile(profile)
    if not isinstance(definition, AgentProfile):
        raise DispatchRefused(f"{profile.profile_id} is not an agent profile")
    started = machine.begin_attempt(
        work_order, block_id, profile=profile,
        fallback_condition=fallback_condition, evidence=evidence,
    )  # fmt: skip
    # begin_attempt validated the block; authorize only if it recorded this attempt.
    attempts = len(work_order.block(block_id).attempts)
    block = started.block(block_id)
    if block.status != BlockStatus.RUNNING or len(block.attempts) != attempts + 1:
        return ExecutorAttempt(work_order=started)
    candidate = started.candidate
    if candidate is None:  # pragma: no cover - EXECUTING always has a candidate
        raise DispatchRefused("the WorkOrder has no candidate")
    return ExecutorAttempt(
        work_order=started,
        authorization=ExecutorAuthorization(
            work_order_id=started.work_order_id, block_id=block_id, attempt=len(block.attempts),
            profile_id=profile.profile_id, profile_version=profile.version,
            profile_fingerprint=profile.fingerprint,
            harness_id=definition.runtime.harness_id, model=definition.model.model_id,
            workspace_id=candidate.workspace_id, candidate_id=candidate.candidate_id,
        ),
    )  # fmt: skip


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
    """Authorize the attempt through control, then dispatch exactly the approved task."""
    if not any(p.ref == profile for p in work_order.execution_profile.profiles):
        raise DispatchRefused(f"{profile.profile_id} v{profile.version} is not in the envelope")
    request = _approved_task(work_order, profile, task)
    attempt = authorize_executor_attempt(
        work_order, block_id, profile=profile,
        fallback_condition=fallback_condition, evidence=evidence,
    )  # fmt: skip
    if attempt.authorization is None:
        return AttemptDispatch(work_order=attempt.work_order, dispatched=False)
    return AttemptDispatch(
        work_order=attempt.work_order, dispatched=True, outcome=await backend.execute(request)
    )
