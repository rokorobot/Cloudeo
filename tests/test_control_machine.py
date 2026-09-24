"""Pure WorkOrder / block state machines and their invariant guards (V2C)."""

import ast
import inspect
from pathlib import Path

import pytest
from control_helpers import (
    BASE,
    CLAUDE_AUDITOR,
    CURATOR,
    FINAL,
    GPT_CODER,
    GPT_ON_ANTHROPIC,
    MEM_AUDITOR,
    MEMORY_PATHS,
    MOVED,
    NOW,
    OPUS,
    OPUS_FALLBACK,
    PROFILES,
    READ_ONLY_CODER,
    SOL,
    approved,
    audit,
    block_done,
    changes,
    code_approved,
    executing,
    final_verification,
    new_work_order,
    outcome,
    passing_checks,
    plan,
    profile_ref,
    project_profile,
    proof_for,
    ref,
    spec,
    state,
)
from pydantic import ValidationError

import cloudeo.control
from cloudeo.control import machine as m
from cloudeo.control.model import (
    CONTRACT_INDEPENDENCE,
    AttentionCode,
    AttentionReason,
    Block,
    BlockStatus,
    Budget,
    Candidate,
    Deviation,
    DirectToolProfile,
    EnvelopeAmendment,
    EvolutionError,
    FallbackCondition,
    IndependencePolicy,
    IndependenceRequirement,
    Permissions,
    Role,
    UserAction,
    UserDecision,
    WorkOrderStatus,
    check_evolution,
    independence_gaps,
)

S = WorkOrderStatus
B = BlockStatus
I = IndependenceRequirement
Rejected = m.TransitionRejected


def decision(action, **kwargs):
    return UserDecision(action=action, actor="robert", at=NOW, **kwargs)


# --- Happy path ---


def test_happy_path_reaches_promoted_only_through_every_state():
    wo = new_work_order()
    assert wo.status == S.DRAFT
    wo = m.start_intake(wo, accepted_baseline=BASE)
    wo = m.propose_plan(wo, plan())
    wo = m.approve_plan(wo, plan_version=1, approved_by="robert", approved_at=NOW)
    assert wo.status == S.PLAN_APPROVED and wo.blocks[0].status == B.PENDING
    wo = m.attach_candidate(
        wo,
        Candidate(workspace_id="demo", candidate_id="c1", base_commit=BASE),
        accepted_baseline=BASE,
    )
    wo = m.start_execution(wo, accepted_baseline=BASE)
    wo = block_done(wo)
    assert wo.blocks[0].status == B.BLOCK_DONE
    wo = m.enter_final_verification(wo, accepted_baseline=BASE)
    wo = m.record_final_audit(wo, audit(state(), Role.FINAL_VERIFIER, FINAL))
    wo = m.record_kernel_outcome(wo, outcome(promoted=True))
    assert wo.status == S.PROMOTED


def test_memory_impact_block_goes_through_curation_and_memory_audit():
    wo = block_done(executing(blocks=(spec(memory_impact=True),)))
    block = wo.blocks[0]
    assert block.status == B.BLOCK_DONE
    assert [a.role for a in block.attempts] == [Role.PRIMARY_CODE_EXECUTOR, Role.MEMORY_CURATOR]
    # The authoritative state is the Memory Audit's, and the checkpoint proves it.
    assert block.authoritative_state == block.memory_audit.audited_state
    assert block.checkpoint.proves(block.memory_audit.audited_state)


@pytest.mark.negative
@pytest.mark.parametrize(
    "call",
    [
        lambda wo: m.propose_plan(wo, plan()),
        lambda wo: m.start_execution(wo, accepted_baseline=BASE),
        lambda wo: m.enter_final_verification(wo, accepted_baseline=BASE),
    ],
)
def test_illegal_transitions_are_rejected_with_a_reason(call):
    with pytest.raises(Rejected) as exc:
        call(new_work_order())
    assert exc.value.code == "illegal_state"


# --- V2C-01: no promotion or accepted-state access from the control layer ---


FORBIDDEN_MODULES = (
    "cloudeo.workspace.broker",
    "cloudeo.workspace.git",
    "cloudeo.bridge",
    "cloudeo.longhorizon",
    "subprocess",
)
FORBIDDEN_CALLS = {"promote", "checkpoint_candidate", "reject", "cleanup"}


def k1_violations(source: str) -> list[str]:
    """Accepted-state access that K1 forbids in the control layer."""
    tree = ast.parse(source)
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import | ast.ImportFrom):
            names = (
                [node.module] if isinstance(node, ast.ImportFrom) else [a.name for a in node.names]
            )
            found += [f"import {n}" for n in names if n and n.startswith(FORBIDDEN_MODULES)]
        is_call = isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        if is_call and node.func.attr in FORBIDDEN_CALLS:
            found.append(f"call {node.func.attr}")
    found += [f"string {s}" for s in ("refs/cloudeo", "update-ref") if s in source]
    return found


def test_v2c_01_control_layer_cannot_touch_accepted_state():
    package = Path(cloudeo.control.__file__).parent
    for path in package.glob("*.py"):
        assert k1_violations(path.read_text()) == [], path.name


@pytest.mark.negative
@pytest.mark.parametrize(
    "source,violation",
    [
        ("from cloudeo.workspace.broker import WorkspaceBroker", "import cloudeo.workspace.broker"),
        ("import cloudeo.longhorizon.promotion_gate", "import cloudeo.longhorizon.promotion_gate"),
        ("import subprocess", "import subprocess"),
        ("broker.promote(checkpoint)", "call promote"),
        ("broker.checkpoint_candidate(candidate, 'm')", "call checkpoint_candidate"),
        ("REF = 'refs/cloudeo/workspaces/demo/accepted'", "string refs/cloudeo"),
    ],
)
def test_v2c_01_k1_checker_flags_forbidden_access(source, violation):
    assert violation in k1_violations(source)


# --- V2C-02: no workspace write before an approved plan ---


def test_v2c_02_no_candidate_or_blocks_before_plan_approval():
    wo = m.propose_plan(m.start_intake(new_work_order(), accepted_baseline=BASE), plan())
    with pytest.raises(Rejected):
        m.attach_candidate(
            wo,
            Candidate(workspace_id="demo", candidate_id="c1", base_commit=BASE),
            accepted_baseline=BASE,
        )
    with pytest.raises(ValidationError, match="before an approved plan"):
        wo.evolve(candidate=Candidate(workspace_id="demo", candidate_id="c1", base_commit=BASE))
    with pytest.raises(ValidationError, match="before an approved plan"):
        wo.evolve(blocks=(Block(spec=spec()),))
    with pytest.raises(Rejected):
        m.begin_attempt(approved(), "b1", profile=OPUS)  # not EXECUTING yet


# --- V2C-03: plan changes need a new version and a new approval ---


@pytest.mark.negative
def test_v2c_03_plan_versions_are_immutable_and_reapproval_is_required():
    wo = m.start_intake(new_work_order(), accepted_baseline=BASE)
    with pytest.raises(Rejected, match="plan_version"):
        m.propose_plan(wo, plan(version=2))
    wo = m.propose_plan(wo, plan())
    wo = m.approve_plan(wo, plan_version=1, approved_by="robert", approved_at=NOW)
    wo = m.start_execution(
        m.attach_candidate(
            wo,
            Candidate(workspace_id="demo", candidate_id="c1", base_commit=BASE),
            accepted_baseline=BASE,
        ),
        accepted_baseline=BASE,
    )
    wo = m.raise_attention(
        wo, AttentionReason(code=AttentionCode.PLAN_AMBIGUITY, summary="unclear", evidence=(ref(),))
    )
    wo = m.decide(wo, decision(UserAction.REPLAN))
    assert wo.status == S.PLAN_PROPOSED
    with pytest.raises(Rejected, match="plan_version"):
        m.approve_plan(wo, plan_version=1, approved_by="robert", approved_at=NOW)
    wo = m.propose_plan(wo, plan(version=2))
    wo = m.approve_plan(wo, plan_version=2, approved_by="robert", approved_at=NOW)
    assert [a.plan_version for a in wo.approvals] == [1, 2]
    with pytest.raises(ValidationError, match="newer plan version"):
        wo.evolve(approvals=(wo.approvals[1], wo.approvals[0]))
    with pytest.raises(ValidationError, match="consecutive"):
        wo.evolve(plan_versions=wo.plan_versions[1:])


def test_v2c_03_replan_cannot_change_a_done_block_and_keeps_superseded_evidence():
    wo = block_done(executing(blocks=(spec("b1"), spec("b2", 2))))
    wo = m.begin_attempt(wo, "b2", profile=OPUS)
    wo = m.raise_attention(
        wo, AttentionReason(code=AttentionCode.PLAN_AMBIGUITY, summary="unclear", evidence=(ref(),))
    )
    wo = m.propose_plan(
        m.decide(wo, decision(UserAction.REPLAN)), plan(2, blocks=(spec("b1", scope=("other",)),))
    )
    with pytest.raises(Rejected, match="replan_changes_done_block"):
        m.approve_plan(wo, plan_version=2, approved_by="robert", approved_at=NOW)
    wo = m.propose_plan(wo, plan(3, blocks=(spec("b1"), spec("b3", 2))))
    wo = m.approve_plan(wo, plan_version=3, approved_by="robert", approved_at=NOW)
    assert wo.block("b1").status == B.BLOCK_DONE
    assert [b.spec.block_id for b in wo.superseded_blocks] == ["b2"]


# --- V2C-04 / V2C-05: acceptance only from the kernel ---


def test_v2c_04_promoted_only_from_a_promoted_kernel_outcome():
    wo = final_verification()
    refused = m.record_kernel_outcome(wo, outcome(promoted=False))
    assert refused.status == S.USER_ATTENTION_REQUIRED
    assert refused.open_attention.reasons[0].code == AttentionCode.PROMOTION_REFUSED
    with pytest.raises(ValidationError, match="PROMOTED requires"):
        wo.evolve(status=S.PROMOTED)
    with pytest.raises(ValidationError, match="promoted kernel outcome"):
        wo.evolve(outcome=outcome(promoted=True))


def test_v2c_04_promotion_needs_an_authoritative_final_audit_on_record():
    wo = m.enter_final_verification(block_done(executing()), accepted_baseline=BASE)
    with pytest.raises(Rejected, match="final_audit"):
        m.record_kernel_outcome(wo, outcome(promoted=True))


@pytest.mark.negative
def test_v2c_05_code_approved_and_block_done_never_imply_acceptance():
    wo = block_done(executing())
    assert wo.status == S.EXECUTING  # all blocks done is not promotion
    with pytest.raises(ValidationError):
        wo.evolve(status=S.PROMOTED)
    with pytest.raises(ValidationError, match="every block BLOCK_DONE"):
        code_approved(executing()).evolve(status=S.FINAL_VERIFICATION)


# --- V2C-06 / V2C-07: CODE_APPROVED requirements ---


@pytest.mark.negative
@pytest.mark.parametrize(
    "tests_passed,audit_kwargs,change_kwargs,current,error",
    [
        (False, {}, {}, 1, "acceptance checks did not pass"),
        (True, {"status": "NOT_VERIFIED"}, {}, 1, "not an original VERIFIED"),
        (True, {"status": "BLOCKED"}, {}, 1, "not an original VERIFIED"),
        (True, {"repair": "accepted"}, {}, 1, "not an original VERIFIED"),
        (True, {"role": Role.MEMORY_AUDITOR, "auditor": MEM_AUDITOR}, {}, 1, "code_auditor"),
        (True, {}, {"paths": ("src/other/y.py",)}, 1, "outside the block scope"),
        (True, {}, {}, 2, "state_changed_since_audit"),
    ],
    ids=[
        "tests_failed",
        "not_verified",
        "blocked",
        "repaired",
        "wrong_role",
        "out_of_scope",
        "stale",
    ],
)
def test_v2c_06_07_code_approval_requires_every_condition(
    tests_passed, audit_kwargs, change_kwargs, current, error
):
    wo = executing()
    wo = m.record_tests(
        m.finish_run(m.begin_attempt(wo, "b1", profile=OPUS), "b1"),
        "b1",
        passing_checks(state(), tests_passed),
    )
    with pytest.raises(Rejected, match=error):
        m.approve_code(
            wo,
            "b1",
            audit=audit(state(), **audit_kwargs),
            changes=changes(**change_kwargs),
            current_state=state(current),
        )
    assert wo.block("b1").status == B.BLOCK_RESULT


def test_v2c_06_block_status_cannot_be_forged_past_code_approval():
    for status in (B.CODE_APPROVED, B.BLOCK_CHECKPOINT, B.BLOCK_DONE):
        with pytest.raises(ValidationError):
            Block(spec=spec(), status=status)


def test_v2c_06_approved_deviation_allows_out_of_scope_changes():
    wo = executing()
    wo = m.record_tests(
        m.finish_run(m.begin_attempt(wo, "b1", profile=OPUS), "b1"), "b1", passing_checks(state())
    )
    # An unapproved deviation id does not cover the out-of-scope change.
    with pytest.raises(Rejected, match="deviation"):
        m.approve_code(
            wo,
            "b1",
            audit=audit(state()),
            changes=changes(paths=("src/other/y.py",), deviation="dev-1"),
            current_state=state(),
        )
    dev = Deviation(
        deviation_id="dev-1",
        block_id="b1",
        material=True,
        summary="touches src/other",
        evidence=ref(),
    )
    wo = m.record_deviation(wo, dev)
    assert wo.status == S.USER_ATTENTION_REQUIRED  # nothing is approved while escalated
    wo = m.decide(
        wo,
        decision(
            UserAction.RESUME,
            approved_deviations=("dev-1",),
            waived=(AttentionCode.MATERIAL_DEVIATION,),
        ),
        accepted_baseline=BASE,
    )
    wo = m.approve_code(
        wo,
        "b1",
        audit=audit(state()),
        changes=changes(paths=("src/other/y.py",), deviation="dev-1"),
        current_state=state(),
    )
    assert wo.block("b1").status == B.CODE_APPROVED


@pytest.mark.negative
def test_v2c_07_repaired_audits_never_approve_memory_or_final_verification():
    wo = code_approved(executing(blocks=(spec(memory_impact=True),)))
    wo = m.begin_memory_curation(wo, "b1", profile=CURATOR)
    wo = m.finish_memory_curation(
        wo, "b1", changes(paths=("docs/components/a.md",), allowed=MEMORY_PATHS)
    )
    s = state(5)
    with pytest.raises(Rejected, match="not an original VERIFIED"):
        m.approve_memory(
            wo,
            "b1",
            audit=audit(s, Role.MEMORY_AUDITOR, MEM_AUDITOR, repair="accepted"),
            current_state=s,
        )
    fv = m.enter_final_verification(block_done(executing()), accepted_baseline=BASE)
    fv = m.record_final_audit(fv, audit(state(), Role.FINAL_VERIFIER, FINAL, repair="accepted"))
    with pytest.raises(Rejected, match="final_audit"):
        m.record_kernel_outcome(fv, outcome(promoted=True))


# --- V2C-09: memory curation ---


def test_v2c_09_curation_only_after_code_approved_and_only_by_the_curator():
    wo = executing(blocks=(spec(memory_impact=True),))
    with pytest.raises(Rejected, match="illegal_block_state"):
        m.begin_memory_curation(wo, "b1", profile=CURATOR)
    wo = code_approved(wo)
    with pytest.raises(Rejected, match="profile_not_bound"):
        m.begin_memory_curation(wo, "b1", profile=OPUS)
    no_memory = code_approved(executing())
    with pytest.raises(Rejected, match="no_memory_impact"):
        m.begin_memory_curation(no_memory, "b1", profile=CURATOR)


def test_v2c_09_curator_changes_outside_memory_paths_escalate():
    wo = m.begin_memory_curation(
        code_approved(executing(blocks=(spec(memory_impact=True),))), "b1", profile=CURATOR
    )
    wo = m.finish_memory_curation(wo, "b1", changes(paths=("src/app/x.py",), allowed=MEMORY_PATHS))
    assert wo.status == S.USER_ATTENTION_REQUIRED
    assert wo.open_attention.reasons[0].code == AttentionCode.MATERIAL_DEVIATION
    assert wo.deviations[0].material


def test_v2c_09_memory_audit_is_required_before_the_checkpoint():
    wo = code_approved(executing(blocks=(spec(memory_impact=True),)))
    with pytest.raises(Rejected, match="memory_impact"):
        m.enter_block_checkpoint(wo, "b1", current_state=state())


# --- V2C-11: profile snapshot ---


@pytest.mark.negative
def test_v2c_11_profile_snapshot_changes_only_by_an_approved_amendment():
    wo = executing()
    with pytest.raises(Rejected):
        m.decide(wo, decision(UserAction.CHANGE_AGENT))  # not in attention
    wo = m.raise_attention(
        wo,
        AttentionReason(
            code=AttentionCode.AGENT_UNAVAILABLE, summary="opus down", evidence=(ref(),)
        ),
    )
    with pytest.raises(Rejected, match="amendment"):
        m.decide(wo, decision(UserAction.CHANGE_AGENT))
    new_profile = project_profile(version=2, executor=OPUS_FALLBACK, fallbacks=())
    stale = project_profile(version=1)
    with pytest.raises(Rejected, match="profile_version"):
        m.decide(
            wo,
            decision(UserAction.CHANGE_AGENT),
            amendment=EnvelopeAmendment(
                attention_id="att-1",
                action=UserAction.CHANGE_AGENT,
                execution_profile=stale,
                approved_by="robert",
                approved_at=NOW,
            ),
        )
    amendment = EnvelopeAmendment(
        attention_id="att-1",
        action=UserAction.CHANGE_AGENT,
        execution_profile=new_profile,
        approved_by="robert",
        approved_at=NOW,
    )
    wo = m.decide(wo, decision(UserAction.CHANGE_AGENT), amendment=amendment)
    assert wo.execution_profile.version == 2 and wo.status == S.USER_ATTENTION_REQUIRED
    wo = m.decide(wo, decision(UserAction.RESUME), accepted_baseline=BASE)
    assert wo.status == S.EXECUTING
    wo = m.begin_attempt(wo, "b1", profile=OPUS_FALLBACK)  # now the bound primary
    assert wo.block("b1").attempts[-1].fallback_condition is None


# --- V2C-12: bound primary and defined fallback conditions ---


def test_v2c_12_primary_is_used_and_fallbacks_need_a_defined_condition():
    wo = executing()
    with pytest.raises(Rejected, match="profile_not_bound"):
        m.begin_attempt(wo, "b1", profile=profile_ref("unbound"))
    with pytest.raises(Rejected, match="fallback_condition"):
        m.begin_attempt(wo, "b1", profile=OPUS_FALLBACK)  # no condition
    with pytest.raises(Rejected, match="fallback_condition"):
        m.begin_attempt(
            wo,
            "b1",
            profile=OPUS_FALLBACK,
            fallback_condition=FallbackCondition.POLICY_FORBIDS_PRIMARY,
            evidence=ref(),
        )  # not a condition defined for this binding
    with pytest.raises(Rejected, match="fallback_condition"):
        m.begin_attempt(
            wo, "b1", profile=OPUS_FALLBACK, fallback_condition=FallbackCondition.MODEL_UNAVAILABLE
        )  # no evidence
    with pytest.raises(Rejected, match="fallback"):
        m.begin_attempt(
            wo, "b1", profile=OPUS, fallback_condition=FallbackCondition.MODEL_UNAVAILABLE
        )
    wo = m.begin_attempt(
        wo,
        "b1",
        profile=OPUS_FALLBACK,
        fallback_condition=FallbackCondition.MODEL_UNAVAILABLE,
        evidence=ref("uhp_discovery", "models"),
    )
    attempt = wo.block("b1").attempts[-1]
    assert (attempt.profile, attempt.fallback_condition) == (
        OPUS_FALLBACK,
        FallbackCondition.MODEL_UNAVAILABLE,
    )


def test_v2c_12_auditors_must_be_the_bound_profile():
    wo = m.record_tests(
        m.finish_run(m.begin_attempt(executing(), "b1", profile=OPUS), "b1"),
        "b1",
        passing_checks(state()),
    )
    with pytest.raises(Rejected, match="profile_not_bound"):
        m.approve_code(
            wo, "b1", audit=audit(state(), auditor=OPUS), changes=changes(), current_state=state()
        )


# --- V2C-14: auditor independence ---


def gap_refs(wo):
    reason = next(
        r for r in wo.open_attention.reasons if r.code == AttentionCode.INDEPENDENCE_UNAVAILABLE
    )
    return {e.ref for e in reason.evidence}


FALLBACK_TO_GPT = {
    "profile": GPT_CODER,
    "fallback_condition": FallbackCondition.MODEL_UNAVAILABLE,
    "evidence": ref("uhp_discovery", "opus-unavailable"),
}


def change_agent(wo, profile):
    amendment = EnvelopeAmendment(
        attention_id=wo.open_attention.attention_id,
        action=UserAction.CHANGE_AGENT,
        execution_profile=profile,
        approved_by="robert",
        approved_at=NOW,
    )
    return m.decide(wo, decision(UserAction.CHANGE_AGENT), amendment=amendment)


def agent_down(wo):
    reason = AttentionReason(
        code=AttentionCode.AGENT_UNAVAILABLE, summary="agent down", evidence=(ref(),)
    )
    return m.raise_attention(wo, reason)


@pytest.mark.negative
def test_v2c_14_policy_is_the_contract_table_and_can_only_be_stricter():
    policy = IndependencePolicy()
    assert policy.required("low") == (I.FRESH_SESSION, I.READ_ONLY_WORKSPACE)
    for risk in ("low", "medium", "high"):
        assert policy.required(risk) == CONTRACT_INDEPENDENCE[risk]
    stricter = IndependencePolicy(low=(*CONTRACT_INDEPENDENCE["low"], I.DIFFERENT_MODEL_FAMILY))
    assert I.DIFFERENT_MODEL_FAMILY in stricter.required("low")
    with pytest.raises(ValidationError, match="only add to the contract"):
        IndependencePolicy(high=CONTRACT_INDEPENDENCE["medium"])
    with pytest.raises(ValidationError, match="listed once"):
        IndependencePolicy(low=(I.FRESH_SESSION, I.FRESH_SESSION, I.READ_ONLY_WORKSPACE))


def test_v2c_14_requirements_accumulate_by_risk_class():
    def gaps(auditor, risk):
        required = CONTRACT_INDEPENDENCE[risk]
        return independence_gaps(required, Role.CODE_AUDITOR, auditor, (PROFILES[OPUS],))

    claude = PROFILES[CLAUDE_AUDITOR]
    assert gaps(claude, "low") == ()
    assert gaps(claude, "medium") == ("code_auditor:different_model_family",)
    assert gaps(claude, "high") == (
        "code_auditor:different_model_family",
        "code_auditor:different_inference_provider",
    )
    assert gaps(PROFILES[GPT_ON_ANTHROPIC], "high") == (
        "code_auditor:different_inference_provider",
    )
    assert gaps(PROFILES[SOL], "high") == ()
    persistent = PROFILES[SOL].evolve(session="persistent")
    assert gaps(persistent, "low") == ("code_auditor:fresh_session",)
    writable = PROFILES[SOL].evolve(permissions=Permissions(workspace="read_write"))
    assert gaps(writable, "low") == ("code_auditor:read_only_workspace",)
    tool = DirectToolProfile(
        profile_id="lint-tool",
        version=1,
        permissions=Permissions(workspace="read_only"),
        eligible_roles=(Role.CODE_AUDITOR,),
        capability="lint",
        provider="treg",
    )
    # Only an agent can show a fresh session or a model family.
    assert gaps(tool, "medium") == (
        "code_auditor:fresh_session",
        "code_auditor:different_model_family",
    )


@pytest.mark.negative
def test_v2c_14_plan_approval_escalates_when_bound_auditors_cannot_be_independent():
    profile = project_profile(code_auditor=CLAUDE_AUDITOR)
    assert approved(profile=profile, risk="low").status == S.PLAN_APPROVED
    wo = approved(profile=profile, risk="high")
    assert wo.status == S.USER_ATTENTION_REQUIRED
    assert wo.open_attention.raised_from == S.PLAN_APPROVED
    assert gap_refs(wo) == {
        "code_auditor:different_model_family",
        "code_auditor:different_inference_provider",
    }
    # Never weakened automatically: resuming without a decision is refused.
    with pytest.raises(Rejected, match="unresolved_reasons"):
        m.decide(wo, decision(UserAction.RESUME), accepted_baseline=BASE)


@pytest.mark.negative
def test_v2c_14_a_fallback_that_breaks_independence_escalates_before_it_runs():
    wo = executing(profile=project_profile(fallbacks=(GPT_CODER,)), risk="medium")
    assert wo.status == S.EXECUTING  # the bound primaries are independent
    wo = m.begin_attempt(wo, "b1", **FALLBACK_TO_GPT)
    assert wo.status == S.USER_ATTENTION_REQUIRED
    assert gap_refs(wo) == {
        "code_auditor:different_model_family",
        "final_verifier:different_model_family",
    }
    assert wo.block("b1").attempts == ()
    assert GPT_CODER not in {p.ref for p in wo.used_profiles}


@pytest.mark.negative
def test_v2c_14_only_an_explicit_recorded_waiver_accepts_a_gap():
    wo = executing(profile=project_profile(fallbacks=(GPT_CODER,)), risk="medium")
    wo = m.begin_attempt(wo, "b1", **FALLBACK_TO_GPT)
    with pytest.raises(Rejected, match="unresolved_reasons"):
        m.decide(wo, decision(UserAction.RESUME), accepted_baseline=BASE)
    wo = m.decide(
        wo,
        decision(UserAction.RESUME, waived=(AttentionCode.INDEPENDENCE_UNAVAILABLE,)),
        accepted_baseline=BASE,
    )
    assert wo.waived_independence == {
        "code_auditor:different_model_family",
        "final_verifier:different_model_family",
    }
    assert wo.attention[-1].decisions[-1].actor == "robert"
    wo = m.begin_attempt(wo, "b1", **FALLBACK_TO_GPT)
    wo = m.record_tests(m.finish_run(wo, "b1"), "b1", passing_checks(state()))
    wo = m.approve_code(wo, "b1", audit=audit(state()), changes=changes(), current_state=state())
    assert wo.block("b1").status == B.CODE_APPROVED


@pytest.mark.negative
def test_v2c_14_final_verifier_is_judged_against_every_writer_used():
    wo = agent_down(block_done(executing(risk="medium")))
    # The user redirects final verification to a Claude auditor. Opus is no
    # longer bound, but the changes it wrote remain in the candidate.
    v2 = project_profile(
        version=2, executor=OPUS_FALLBACK, fallbacks=(), final_verifier=CLAUDE_AUDITOR
    )
    wo = m.decide(change_agent(wo, v2), decision(UserAction.RESUME), accepted_baseline=BASE)
    wo = m.enter_final_verification(wo, accepted_baseline=BASE)
    wo = m.record_final_audit(wo, audit(state(), Role.FINAL_VERIFIER, CLAUDE_AUDITOR))
    assert wo.status == S.USER_ATTENTION_REQUIRED and wo.final_audit is None
    assert gap_refs(wo) == {"final_verifier:different_model_family"}


@pytest.mark.negative
def test_v2c_14_a_stored_approval_without_independence_is_rejected():
    wo = executing(profile=project_profile(code_auditor=CLAUDE_AUDITOR))
    wo = m.begin_attempt(wo, "b1", profile=OPUS)
    wo = m.record_tests(m.finish_run(wo, "b1"), "b1", passing_checks(state()))
    wo = m.approve_code(
        wo,
        "b1",
        audit=audit(state(), auditor=CLAUDE_AUDITOR),
        changes=changes(),
        current_state=state(),
    )
    block = wo.block("b1")
    assert block.status == B.CODE_APPROVED and block.risk_class == "low"
    # Judged by the risk class in force; a forged stricter class exposes the gap.
    with pytest.raises(ValidationError, match="lacks independence"):
        wo.evolve(blocks=(block.evolve(risk_class="medium"),))
    with pytest.raises(ValidationError, match="risk class"):
        wo.evolve(blocks=(block.evolve(risk_class=None),))


# --- V2C-18: exact, recorded profile versions ---


@pytest.mark.negative
def test_v2c_18_every_step_records_the_exact_profile_version():
    wo = final_verification()
    assert {p.ref for p in wo.used_profiles} == {OPUS, SOL, FINAL}
    attempt = wo.block("b1").attempts[0]
    assert attempt.profile.fingerprint == PROFILES[OPUS].canonical_sha256()
    with pytest.raises(ValidationError, match="unrecorded profile versions"):
        wo.evolve(used_profiles=tuple(p for p in wo.used_profiles if p.ref != OPUS))
    # A different fingerprint is a different, unknown version.
    forged = attempt.evolve(profile=attempt.profile.evolve(fingerprint="0" * 64))
    with pytest.raises(ValidationError, match="unrecorded profile versions"):
        wo.evolve(blocks=(wo.block("b1").evolve(attempts=(forged,)),))
    # The record is append-only, even for an entry no step names.
    extra = wo.evolve(used_profiles=(*wo.used_profiles, PROFILES[OPUS_FALLBACK]))
    with pytest.raises(EvolutionError, match="used_profiles"):
        check_evolution(extra, wo)


def test_v2c_18_used_versions_outlive_a_snapshot_change():
    wo = agent_down(code_approved(executing()))
    wo = change_agent(wo, project_profile(version=2, executor=OPUS_FALLBACK, fallbacks=()))
    assert OPUS not in {p.ref for p in wo.execution_profile.profiles}
    assert wo.used_profile(OPUS) == PROFILES[OPUS]


@pytest.mark.negative
def test_v2c_18_bindings_must_match_their_exact_definitions():
    profile = project_profile()
    sol = PROFILES[SOL]
    others = tuple(p for p in profile.profiles if p.ref != SOL)
    with pytest.raises(ValidationError, match="exactly the definitions"):
        profile.evolve(profiles=others)  # a missing definition
    with pytest.raises(ValidationError, match="exactly the definitions"):
        profile.evolve(profiles=(*others, sol.evolve(reasoning="high")))  # another fingerprint
    with pytest.raises(ValidationError, match="exactly the definitions"):
        profile.evolve(profiles=(*profile.profiles, PROFILES[CLAUDE_AUDITOR]))  # unbound
    with pytest.raises(ValidationError, match="defined once"):
        profile.evolve(profiles=(*profile.profiles, sol))
    with pytest.raises(ValidationError, match="not eligible"):
        project_profile(code_auditor=MEM_AUDITOR)
    with pytest.raises(ValidationError, match="read_write"):
        project_profile(executor=READ_ONLY_CODER, fallbacks=())


# --- V2C-15 / V2C-16 / V2C-17: attention ---


def test_v2c_15_material_deviation_always_escalates():
    wo = m.record_deviation(
        executing(),
        Deviation(
            deviation_id="dev-1", block_id="b1", material=True, summary="new dep", evidence=ref()
        ),
    )
    assert wo.status == S.USER_ATTENTION_REQUIRED
    minor = m.record_deviation(
        executing(),
        Deviation(
            deviation_id="dev-1", block_id="b1", material=False, summary="naming", evidence=ref()
        ),
    )
    assert minor.status == S.EXECUTING and minor.deviations
    with pytest.raises(Rejected, match="only the user approves"):
        m.record_deviation(
            executing(),
            Deviation(
                deviation_id="dev-1",
                block_id="b1",
                material=True,
                summary="x",
                evidence=ref(),
                approved_by="agent",
            ),
        )


@pytest.mark.negative
def test_v2c_16_all_active_reasons_together_and_resume_needs_them_resolved():
    wo = m.raise_attention(
        executing(),
        AttentionReason(code=AttentionCode.BUDGET_EXHAUSTED, summary="budget", evidence=(ref(),)),
        AttentionReason(code=AttentionCode.AUDITOR_ERROR, summary="auditor", evidence=(ref(),)),
    )
    wo = m.raise_attention(
        wo,
        AttentionReason(
            code=AttentionCode.MEMORY_CONFLICT,
            summary="memory",
            evidence=(ref(),),
            severity="warning",
        ),
        AttentionReason(
            code=AttentionCode.AUDITOR_ERROR, summary="again", evidence=(ref("audit", "a-2"),)
        ),
    )
    request = wo.open_attention
    assert len(wo.attention) == 1  # one request, every reason together
    assert {r.code for r in request.reasons} == {
        AttentionCode.BUDGET_EXHAUSTED,
        AttentionCode.AUDITOR_ERROR,
        AttentionCode.MEMORY_CONFLICT,
    }
    assert (
        len(next(r for r in request.reasons if r.code == AttentionCode.AUDITOR_ERROR).evidence) == 2
    )
    with pytest.raises(Rejected, match="unresolved_reasons"):
        m.decide(wo, decision(UserAction.RESUME), accepted_baseline=BASE)
    amendment = EnvelopeAmendment(
        attention_id="att-1",
        action=UserAction.CHANGE_BUDGET,
        budget=Budget(max_attempts_per_block=5),
        approved_by="robert",
        approved_at=NOW,
    )
    wo = m.decide(wo, decision(UserAction.CHANGE_BUDGET), amendment=amendment)
    with pytest.raises(Rejected, match="AUDITOR_ERROR"):
        m.decide(wo, decision(UserAction.RESUME), accepted_baseline=BASE)
    wo = m.decide(
        wo,
        decision(UserAction.RESUME, waived=(AttentionCode.AUDITOR_ERROR,)),
        accepted_baseline=BASE,
    )
    assert wo.status == S.EXECUTING and wo.budget.max_attempts_per_block == 5
    closed = wo.attention[0]
    assert closed.closed
    # Rejected decisions are not recorded; accepted ones are, in order.
    assert [d.action for d in closed.decisions] == [UserAction.CHANGE_BUDGET, UserAction.RESUME]
    assert closed.resolved_codes == (AttentionCode.BUDGET_EXHAUSTED,)


@pytest.mark.negative
def test_v2c_16_attention_only_from_the_contract_states():
    with pytest.raises(Rejected):
        m.raise_attention(
            new_work_order(),
            AttentionReason(code=AttentionCode.PLAN_AMBIGUITY, summary="x", evidence=(ref(),)),
        )


def test_v2c_17_kernel_refusal_and_drift_always_escalate():
    refused = m.record_kernel_outcome(final_verification(), outcome(promoted=False))
    assert refused.status == S.USER_ATTENTION_REQUIRED and refused.outcome is not None
    drift = m.start_execution(
        m.attach_candidate(
            approved(),
            Candidate(workspace_id="demo", candidate_id="c1", base_commit=BASE),
            accepted_baseline=BASE,
        ),
        accepted_baseline=MOVED,
    )
    assert drift.open_attention.reasons[0].code == AttentionCode.BASELINE_DRIFT


# --- V2C-19: BLOCK_DONE only through the proven checkpoint ---


def test_v2c_19_block_done_only_via_a_proven_checkpoint():
    wo = m.enter_block_checkpoint(code_approved(executing()), "b1", current_state=state())
    block = wo.block("b1")
    with pytest.raises(ValidationError, match="proven"):
        block.evolve(status=B.BLOCK_DONE)
    wrong_content = proof_for(state(7))
    raced = m.prove_block_checkpoint(wo, "b1", proof=wrong_content)
    assert raced.block("b1").status == B.BLOCK_CHECKPOINT  # never labelled BLOCK_DONE
    assert raced.block("b1").rejected_checkpoints == (wrong_content,)
    assert raced.open_attention.reasons[0].code == AttentionCode.BLOCK_CHECKPOINT_MISMATCH
    wrong_parent = proof_for(state()).evolve(parent="e" * 40)
    assert (
        m.prove_block_checkpoint(wo, "b1", proof=wrong_parent).status == S.USER_ATTENTION_REQUIRED
    )
    done = m.prove_block_checkpoint(wo, "b1", proof=proof_for(state()))
    assert done.block("b1").status == B.BLOCK_DONE
    same_commit = proof_for(state()).evolve(commit=BASE, parent=None)  # the audited HEAD itself
    assert m.prove_block_checkpoint(wo, "b1", proof=same_commit).block("b1").status == B.BLOCK_DONE


def test_v2c_19_candidate_change_after_the_audit_stops_the_block():
    wo = code_approved(executing())
    with pytest.raises(Rejected, match="state_changed_since_audit"):
        m.enter_block_checkpoint(wo, "b1", current_state=state(2))


def test_v2c_19_block_done_is_the_only_function_that_sets_it():
    source = inspect.getsource(m)
    setters = [
        line
        for line in source.splitlines()
        if "status=B.BLOCK_DONE" in line or "status=BlockStatus.BLOCK_DONE" in line
    ]
    assert len(setters) == 1 and "prove_block_checkpoint" in inspect.getsource(
        m.prove_block_checkpoint
    )
    assert "status=B.BLOCK_DONE" in inspect.getsource(m.prove_block_checkpoint)


# --- V2C-20: no write-capable role in final verification ---


def test_v2c_20_final_verification_runs_no_write_capable_role():
    wo = final_verification()
    with pytest.raises(Rejected, match="illegal_state"):
        m.begin_attempt(wo, "b1", profile=OPUS)
    with pytest.raises(Rejected, match="illegal_state"):
        m.begin_memory_curation(wo, "b1", profile=CURATOR)
    with pytest.raises(Rejected, match="role"):
        m.record_final_audit(wo, audit(state(), Role.CODE_AUDITOR, SOL))


# --- V2C-21 / V2C-22 ---


def test_v2c_21_abort_and_defer_keep_evidence_and_candidate():
    wo = m.raise_attention(
        code_approved(executing()),
        AttentionReason(code=AttentionCode.RISK_REQUIRES_HUMAN, summary="risk", evidence=(ref(),)),
    )
    deferred = m.decide(wo, decision(UserAction.DEFER))
    assert deferred.status == S.DEFERRED and deferred.deferred_from == S.EXECUTING
    assert deferred.candidate == wo.candidate and deferred.blocks == wo.blocks
    resumed = m.resume_deferred(deferred, accepted_baseline=BASE)
    assert resumed.status == S.EXECUTING
    aborted = m.decide(
        m.raise_attention(
            resumed,
            AttentionReason(
                code=AttentionCode.RISK_REQUIRES_HUMAN, summary="risk", evidence=(ref(),)
            ),
        ),
        decision(UserAction.ABORT),
    )
    assert aborted.status == S.ABORTED
    assert aborted.candidate == wo.candidate and aborted.blocks == wo.blocks
    assert len(aborted.attention) == 2


@pytest.mark.parametrize("step", ["attach", "execute", "final", "resume", "deferred"])
def test_v2c_22_baseline_drift_is_never_silently_absorbed(step):
    candidate = Candidate(workspace_id="demo", candidate_id="c1", base_commit=BASE)
    if step == "attach":
        wo = m.attach_candidate(approved(), candidate, accepted_baseline=MOVED)
    elif step == "execute":
        wo = m.start_execution(
            m.attach_candidate(approved(), candidate, accepted_baseline=BASE),
            accepted_baseline=MOVED,
        )
    elif step == "final":
        wo = m.enter_final_verification(block_done(executing()), accepted_baseline=MOVED)
    elif step == "resume":
        wo = m.raise_attention(
            executing(),
            AttentionReason(code=AttentionCode.RISK_REQUIRES_HUMAN, summary="r", evidence=(ref(),)),
        )
        wo = m.decide(
            wo,
            decision(UserAction.RESUME, waived=(AttentionCode.RISK_REQUIRES_HUMAN,)),
            accepted_baseline=MOVED,
        )
    else:
        wo = m.raise_attention(
            executing(),
            AttentionReason(code=AttentionCode.RISK_REQUIRES_HUMAN, summary="r", evidence=(ref(),)),
        )
        wo = m.resume_deferred(m.decide(wo, decision(UserAction.DEFER)), accepted_baseline=MOVED)
    assert wo.status == S.USER_ATTENTION_REQUIRED
    assert AttentionCode.BASELINE_DRIFT in {r.code for r in wo.open_attention.reasons}
    assert wo.planned_baseline == BASE  # never rebased


# --- Attempts and budget ---


def test_failed_attempts_are_bounded_then_escalate():
    wo = executing(attempts=2)
    for n in range(2):
        wo = m.begin_attempt(wo, "b1", profile=OPUS)
        wo = m.fail_attempt(wo, "b1", ref("tests", f"fail-{n}"))
    assert wo.status == S.USER_ATTENTION_REQUIRED
    assert wo.open_attention.reasons[0].code == AttentionCode.ATTEMPTS_EXHAUSTED
    assert len(wo.block("b1").attempts) == 2


def test_blocks_run_in_order():
    wo = executing(blocks=(spec("b1"), spec("b2", 2)))
    with pytest.raises(Rejected, match="block_order"):
        m.begin_attempt(wo, "b2", profile=OPUS)
