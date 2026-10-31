"""Execution failure -> control attention (ADR-035 slice 2; V2C-12, V2C-17 producers)."""

import typing

import pytest
from control_helpers import CLAUDE_AUDITOR, OPUS, OPUS_FALLBACK, executing, new_work_order

from cloudeo.control import machine as m
from cloudeo.control.model import AttentionCode, FallbackCondition, Role, WorkOrderStatus
from cloudeo.execution.contracts import (
    ErrorClass,
    ExecutionError,
    ExecutionOutcome,
    RuntimeIdentity,
)
from cloudeo.orchestration.execution_failure import (
    CONDITION_IF_ESTABLISHED,
    ExecutionFailureAssessment,
    UnmappableExecutionOutcome,
    assess_execution_failure,
    route_execution_failure,
)

ALL_CLASSES = typing.get_args(ErrorClass)
RUNTIME = RuntimeIdentity(
    backend="uhp", execution_plane="uhp_harness", adapter_id="uhp", requested_harness="h1"
)


def failed(error_class="tool_failure", status="failed", **error):
    return ExecutionOutcome(
        kind="harness_task",
        status=status,
        error=ExecutionError(
            error_class=error_class, source="uhp_http", message="native message", **error
        ),
        runtime=RUNTIME,
    )


def executor(outcome):
    return assess_execution_failure(outcome, role=Role.PRIMARY_CODE_EXECUTOR, profile=OPUS)


def test_matrix_covers_every_error_class_exactly():
    assert set(CONDITION_IF_ESTABLISHED) == set(ALL_CLASSES)


def test_the_assessment_carries_no_fallback_authorization():
    assert "fallback_condition" not in ExecutionFailureAssessment.model_fields


@pytest.mark.parametrize("error_class", ALL_CLASSES)
def test_every_class_routes_to_attention(error_class):
    a = executor(failed(error_class))
    assert a.attention.code == AttentionCode.AGENT_UNAVAILABLE
    assert a.attention.severity == "blocking"
    assert a.error_class == error_class


@pytest.mark.parametrize(
    "error_class,condition",
    [
        ("runtime_unavailable", FallbackCondition.RUNTIME_UNAVAILABLE),
        ("model_unavailable", FallbackCondition.MODEL_UNAVAILABLE),
        ("authentication", FallbackCondition.PROVIDER_FAILURE_PERSISTENT),
        ("quota_exhausted", FallbackCondition.PROVIDER_FAILURE_PERSISTENT),
        ("rate_limited", FallbackCondition.PROVIDER_FAILURE_PERSISTENT),
        ("transport", FallbackCondition.PROVIDER_FAILURE_PERSISTENT),
        ("authorization", None),
        ("protocol", None),
        ("unknown", None),
        ("timeout", None),
        ("invalid_request", None),
        ("workspace_violation", None),
        ("tool_failure", None),
        ("cancelled", None),
    ],
)
def test_condition_if_established_follows_contract_8_4(error_class, condition):
    a = executor(failed(error_class))
    assert a.condition_if_established == condition
    assert (a.established_by is None) == (condition is None)


def test_rate_limit_and_quota_exhaustion_stay_distinct():
    rate, quota = executor(failed("rate_limited")), executor(failed("quota_exhausted"))
    assert (rate.error_class, quota.error_class) == ("rate_limited", "quota_exhausted")
    assert "not quota exhaustion" in rate.attention.summary
    assert "not a rate limit" in quota.attention.summary
    assert rate.attention.evidence != quota.attention.evidence


def test_auditor_failure_is_an_auditor_error_and_other_roles_are_not():
    outcome = failed("transport")
    for role in (Role.CODE_AUDITOR, Role.MEMORY_AUDITOR, Role.FINAL_VERIFIER):
        auditing = assess_execution_failure(outcome, role=role, profile=CLAUDE_AUDITOR)
        assert auditing.attention.code == AttentionCode.AUDITOR_ERROR
    for role in (Role.PRIMARY_CODE_EXECUTOR, Role.MEMORY_CURATOR, Role.ARCHITECTURE_PLANNER):
        other = assess_execution_failure(outcome, role=role, profile=OPUS)
        assert other.attention.code == AttentionCode.AGENT_UNAVAILABLE


@pytest.mark.parametrize(
    "status,safe",
    [("failed", True), ("cancelled", True), ("incomplete", False), ("unknown", False)],
)
def test_unobserved_runtime_state_is_never_safe_to_execute_again(status, safe):
    a = executor(failed("runtime_unavailable", status=status))
    assert a.second_execution_safe is safe
    assert ("not re-executed" in a.attention.summary) is not safe


def test_original_error_identity_and_profile_version_are_preserved():
    outcome = failed("authentication", code="missing_credential", http_status=401, body={"v": 1})
    a = executor(outcome)
    assert a.error == outcome.error
    assert a.runtime == RUNTIME
    assert a.profile == OPUS
    assert f"v{OPUS.version}" in a.attention.summary
    assert a.attention.evidence[0].kind == "execution_failure"


def test_evidence_digest_is_deterministic_and_distinguishes_inputs():
    one, two = executor(failed("transport")), executor(failed("transport"))
    assert one.attention.evidence == two.attention.evidence
    other_profile = assess_execution_failure(
        failed("transport"), role=Role.PRIMARY_CODE_EXECUTOR, profile=OPUS_FALLBACK
    )
    assert other_profile.attention.evidence != one.attention.evidence


def test_failure_without_an_error_record_fails_closed():
    a = executor(ExecutionOutcome(kind="harness_task", status="incomplete", runtime=RUNTIME))
    assert (a.error_class, a.error, a.condition_if_established) == ("unknown", None, None)
    assert a.second_execution_safe is False
    cancelled = executor(ExecutionOutcome(kind="harness_task", status="cancelled", runtime=RUNTIME))
    assert cancelled.error_class == "cancelled"


@pytest.mark.negative
@pytest.mark.parametrize("status", ["completed", "dry_run", "in_progress"])
def test_non_failures_are_not_mapped_even_with_an_error(status):
    outcome = ExecutionOutcome(
        kind="harness_task",
        status=status,
        error=ExecutionError(source="uhp_task", message="reported anyway"),
        runtime=RUNTIME,
    )
    with pytest.raises(UnmappableExecutionOutcome):
        executor(outcome)


@pytest.mark.negative
def test_unlisted_error_class_is_not_mapped():
    outcome = failed("transport")
    forged = outcome.model_copy(
        update={"error": outcome.error.model_copy(update={"error_class": "vendor_x"})}
    )
    with pytest.raises(UnmappableExecutionOutcome):
        executor(forged)


@pytest.mark.negative
def test_repeated_failures_are_never_escalated_to_a_fallback():
    for error_class in ("rate_limited", "transport", "authentication", "quota_exhausted"):
        assessments = [executor(failed(error_class)) for _ in range(10)]
        assert {a.attention.code for a in assessments} == {AttentionCode.AGENT_UNAVAILABLE}


# --- Through the public state machine ---


def test_route_raises_attention_through_the_machine_without_a_new_attempt():
    wo = m.begin_attempt(executing(), "b1", profile=OPUS)
    a = executor(failed("unknown", status="unknown"))
    routed = route_execution_failure(wo, a)
    assert routed.status == WorkOrderStatus.USER_ATTENTION_REQUIRED
    reason = routed.open_attention.reasons[0]
    assert (reason.code, reason.evidence) == (AttentionCode.AGENT_UNAVAILABLE, a.attention.evidence)
    assert routed.block("b1").attempts == wo.block("b1").attempts


def test_auditor_error_and_executor_failure_are_listed_together():
    wo = m.begin_attempt(executing(), "b1", profile=OPUS)
    wo = route_execution_failure(wo, executor(failed("transport")))
    audit = assess_execution_failure(
        failed("protocol", status="unknown"), role=Role.CODE_AUDITOR, profile=CLAUDE_AUDITOR
    )
    wo = route_execution_failure(wo, audit)
    codes = {r.code for r in wo.open_attention.reasons}
    assert codes == {AttentionCode.AGENT_UNAVAILABLE, AttentionCode.AUDITOR_ERROR}


@pytest.mark.negative
def test_control_refuses_a_fallback_condition_the_binding_does_not_define():
    # The executor binding allows MODEL/RUNTIME_UNAVAILABLE only. Even if a caller
    # passed the persistent-failure condition, control is the gate and refuses it.
    a = executor(failed("authentication"))
    assert a.condition_if_established == FallbackCondition.PROVIDER_FAILURE_PERSISTENT
    with pytest.raises(m.TransitionRejected, match="fallback_condition"):
        m.begin_attempt(
            executing(),
            "b1",
            profile=OPUS_FALLBACK,
            fallback_condition=a.condition_if_established,
            evidence=a.attention.evidence[0],
        )


@pytest.mark.negative
def test_routing_is_refused_by_control_outside_attention_source_states():
    wo = new_work_order()
    assert wo.status not in (WorkOrderStatus.EXECUTING, WorkOrderStatus.USER_ATTENTION_REQUIRED)
    with pytest.raises(m.TransitionRejected, match="illegal_state"):
        route_execution_failure(wo, executor(failed()))
