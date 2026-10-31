"""Control-owned executor dispatch (V2C-02 slice 1, ADR-037)."""

import pytest
from control_helpers import (
    GPT_CODER,
    OPUS,
    OPUS_FALLBACK,
    approved,
    executing,
    new_work_order,
    project_profile,
    ref,
)

from cloudeo.control import machine as m
from cloudeo.control.model import AttentionCode, BlockStatus, FallbackCondition, WorkOrderStatus
from cloudeo.execution.contracts import ExecutionOutcome, RuntimeIdentity
from cloudeo.orchestration.dispatch import DispatchRefused, dispatch_attempt
from cloudeo.uhp.models import UHPTaskRequest

TASK = UHPTaskRequest(input="Implement block b1.")


class RecordingBackend:
    def __init__(self):
        self.requests = []

    async def execute(self, request):
        self.requests.append(request)
        return ExecutionOutcome(
            kind="harness_task",
            status="completed",
            runtime=RuntimeIdentity(backend="uhp", requested_harness=request.task.harness_id),
        )


async def test_an_approved_attempt_dispatches_exactly_the_bound_profile():
    backend = RecordingBackend()
    result = await dispatch_attempt(executing(), "b1", profile=OPUS, task=TASK, backend=backend)
    assert result.dispatched and result.outcome.status == "completed"
    (request,) = backend.requests
    # Harness and model come from the approved profile, not from the caller.
    assert (request.task.harness_id, request.task.model) == ("uhp", "opus-coder")
    block = result.work_order.block("b1")
    assert block.status == BlockStatus.RUNNING
    assert [a.profile for a in block.attempts] == [OPUS]


async def test_an_approved_fallback_with_its_condition_and_evidence_dispatches():
    backend = RecordingBackend()
    result = await dispatch_attempt(
        executing(), "b1", profile=OPUS_FALLBACK, task=TASK, backend=backend,
        fallback_condition=FallbackCondition.MODEL_UNAVAILABLE, evidence=ref("discovery", "d-1"),
    )  # fmt: skip
    assert result.dispatched
    assert backend.requests[0].task.model == "sonnet-coder"


@pytest.mark.negative
@pytest.mark.parametrize(
    "work_order",
    [new_work_order(), approved()],
    ids=["no_plan", "plan_approved_not_executing"],
)
async def test_v2c_02_no_dispatch_before_an_approved_executing_work_order(work_order):
    backend = RecordingBackend()
    with pytest.raises(m.TransitionRejected):
        await dispatch_attempt(work_order, "b1", profile=OPUS, task=TASK, backend=backend)
    assert backend.requests == []


@pytest.mark.negative
async def test_a_fallback_without_its_condition_is_not_dispatched():
    backend = RecordingBackend()
    with pytest.raises(m.TransitionRejected):
        await dispatch_attempt(executing(), "b1", profile=OPUS_FALLBACK, task=TASK, backend=backend)
    assert backend.requests == []


@pytest.mark.negative
async def test_a_profile_outside_the_envelope_is_refused():
    backend = RecordingBackend()
    with pytest.raises(DispatchRefused, match="not in the envelope"):
        await dispatch_attempt(executing(), "b1", profile=GPT_CODER, task=TASK, backend=backend)
    assert backend.requests == []


@pytest.mark.negative
@pytest.mark.parametrize(
    "task",
    [
        UHPTaskRequest(input="x", model="claude-haiku-4"),
        UHPTaskRequest(input="x", harness_id="chrn_codex"),
    ],
    ids=["other_model", "other_harness"],
)
async def test_a_task_naming_another_harness_or_model_is_refused_before_any_attempt(task):
    backend = RecordingBackend()
    wo = executing()
    with pytest.raises(DispatchRefused, match="is not the approved"):
        await dispatch_attempt(wo, "b1", profile=OPUS, task=task, backend=backend)
    assert backend.requests == []
    assert wo.block("b1").attempts == ()


@pytest.mark.negative
async def test_after_exhausted_attempts_nothing_more_is_dispatched():
    backend = RecordingBackend()
    first = await dispatch_attempt(
        executing(attempts=1), "b1", profile=OPUS, task=TASK, backend=backend
    )
    failed = m.fail_attempt(first.work_order, "b1", ref("tests", "t-fail"))
    assert failed.status == WorkOrderStatus.USER_ATTENTION_REQUIRED
    with pytest.raises(m.TransitionRejected, match="illegal_state"):
        await dispatch_attempt(failed, "b1", profile=OPUS, task=TASK, backend=backend)
    assert len(backend.requests) == 1


@pytest.mark.negative
async def test_attention_from_begin_attempt_dispatches_nothing():
    # A fallback that would break auditor independence: control raises attention.
    backend = RecordingBackend()
    wo = executing(profile=project_profile(fallbacks=(GPT_CODER,)), risk="medium")
    result = await dispatch_attempt(
        wo, "b1", profile=GPT_CODER, task=TASK, backend=backend,
        fallback_condition=FallbackCondition.MODEL_UNAVAILABLE, evidence=ref("discovery", "d-1"),
    )  # fmt: skip
    assert not result.dispatched and backend.requests == []
    assert result.work_order.status == WorkOrderStatus.USER_ATTENTION_REQUIRED
    codes = {r.code for r in result.work_order.open_attention.reasons}
    assert codes == {AttentionCode.INDEPENDENCE_UNAVAILABLE}
