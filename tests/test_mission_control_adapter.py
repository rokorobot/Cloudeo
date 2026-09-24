"""Mission Control read adapter: domain WorkOrder -> UI view model mapping."""

import pytest
from control_helpers import (
    BASE,
    NOW,
    OPUS,
    audit,
    block_done,
    changes,
    code_approved,
    executing,
    final_verification,
    new_work_order,
    outcome,
    passing_checks,
    proof_for,
    ref,
    spec,
    state,
)
from control_helpers import (
    approved as approved_wo,
)

from cloudeo.control import machine as m
from cloudeo.control.model import (
    AttentionCode,
    AttentionReason,
    BlockStatus,
    UserAction,
    UserDecision,
    WorkOrder,
    WorkOrderStatus,
)
from cloudeo.control.store import ControlEvent
from cloudeo.mission_control import adapter
from cloudeo.mission_control.adapter import (
    UnsupportedDomainState,
    lifecycle,
    to_detail,
    to_summary,
    ui_state,
)

TWO_BLOCKS = (spec("b1", 1), spec("b2", 2))


def independence(wo):
    return m.raise_attention(
        wo,
        AttentionReason(
            code=AttentionCode.INDEPENDENCE_UNAVAILABLE,
            summary="no final_verifier independent of the executor provider",
            evidence=(ref("health", "h-1"),),
            suggested_solutions=("add an independent verifier profile",),
        ),
    )


# --- Vocabulary is exhaustive: a new domain value must be mapped deliberately ---


def test_every_domain_vocabulary_is_mapped():
    assert set(adapter.UI_STATE) == set(WorkOrderStatus)
    for table in (adapter.BLOCK_STAGE, adapter.BLOCK_PRESENTATION, adapter.MEMORY_STATUS):
        assert set(table) == set(BlockStatus)
    assert adapter.ATTENTION_CODES == set(AttentionCode)
    assert set(adapter.USER_ACTIONS) == set(UserAction)


# --- domain WorkOrder -> expected lifecycle stage ---


@pytest.mark.parametrize(
    ("build", "state", "stage", "expected"),
    [
        (new_work_order, "draft", "plan", {"plan": "active", "execute": "pending"}),
        (approved_wo, "plan_approved", "plan", {"plan": "active"}),
        (
            executing,
            "executing",
            "execute",
            {"plan": "done", "execute": "active", "audit": "pending", "memory": "skipped"},
        ),
        (
            lambda: m.finish_run(m.begin_attempt(executing(), "b1", profile=OPUS), "b1"),
            "executing",
            "execute",
            {"execute": "active"},
        ),
        (
            lambda: m.record_tests(
                m.finish_run(m.begin_attempt(executing(), "b1", profile=OPUS), "b1"),
                "b1",
                passing_checks(state()),
            ),
            "executing",
            "audit",
            {"execute": "done", "audit": "active", "checkpoint": "pending"},
        ),
        (
            lambda: code_approved(executing()),
            "executing",
            "checkpoint",
            {"audit": "done", "memory": "skipped", "checkpoint": "active"},
        ),
        (
            lambda: code_approved(executing(blocks=(spec(memory_impact=True),))),
            "executing",
            "memory",
            {"audit": "done", "memory": "active", "checkpoint": "pending"},
        ),
        (
            lambda: block_done(executing()),
            "executing",
            "checkpoint",
            {"execute": "done", "checkpoint": "done", "verify": "pending"},
        ),
        (
            final_verification,
            "final_verification",
            "verify",
            {"checkpoint": "done", "verify": "active", "promote": "pending"},
        ),
        (
            lambda: m.record_kernel_outcome(final_verification(), outcome()),
            "promoted",
            "promote",
            {"verify": "done", "promote": "done"},
        ),
    ],
)
def test_domain_state_maps_to_lifecycle(build, state, stage, expected):
    view = to_detail(build())
    assert view.state == state
    assert view.current_stage == stage
    for name, status in expected.items():
        assert view.stages[name] == status, name


def test_second_block_restarts_block_stages():
    wo = block_done(executing(blocks=TWO_BLOCKS), "b1")
    view = to_detail(wo)
    assert view.current_stage == "execute"
    assert view.execution.current_block_id == "b2"
    assert [b.status for b in view.execution.blocks] == ["proven", "pending"]
    assert view.blocks.done == 1 and view.blocks.total == 2


# --- domain attention -> attention presentation ---


def test_attention_presentation():
    wo = independence(block_done(executing(blocks=TWO_BLOCKS), "b1"))
    view = to_detail(wo)

    assert view.state == "attention"
    assert view.reason == "INDEPENDENCE_UNAVAILABLE"
    assert view.current_stage == "execute"
    assert view.stages["execute"] == "attention"
    a = view.attention
    assert a.code == "INDEPENDENCE_UNAVAILABLE"
    assert a.raised_from == "executing"
    assert a.headline == "no final_verifier independent of the executor provider"
    assert a.paused_at_checkpoint == "c" * 40
    assert [(r.code, r.status, r.evidence_count) for r in a.reasons] == [
        ("INDEPENDENCE_UNAVAILABLE", "open", 1)
    ]
    assert a.available_decisions == [
        "resume",
        "replan",
        "change_agent",
        "change_budget",
        "defer",
        "abort",
    ]
    assert to_summary(wo).reason == "INDEPENDENCE_UNAVAILABLE"


def test_deferred_and_aborted_keep_the_stage_they_left():
    held = independence(executing())
    deferred = m.decide(held, _decision(UserAction.DEFER))
    assert to_detail(deferred).state == "deferred"
    assert to_detail(deferred).stages["execute"] == "paused"

    aborted = m.decide(held, _decision(UserAction.ABORT))
    assert to_detail(aborted).state == "aborted"
    assert to_detail(aborted).stages["execute"] == "aborted"
    assert to_detail(aborted).attention is None


def _decision(action):
    return UserDecision(action=action, actor="robert", at=NOW)


# --- BLOCK_DONE proof -> proven UI state ---


def test_block_done_is_presented_as_proven():
    wo = block_done(executing())
    view = to_detail(wo)
    audit_view = view.audit
    assert audit_view.verdict == "BLOCK_DONE"
    assert audit_view.verification == "MATCH"
    assert audit_view.authoritative is True
    assert audit_view.checkpoint == "c" * 40
    assert audit_view.audited_head == state().head_commit
    assert audit_view.content_sha == state().content_sha256
    assert audit_view.tests[0].result == "passed"
    assert audit_view.pending_note is None
    accepted = [i for i in view.checkpoints.items if i.status == "accepted"]
    assert [(i.id, i.sha, i.audited_by) for i in accepted] == [("C1", "c" * 40, "sol-auditor v1")]


# --- candidate checkpoint -> never rendered as accepted ---


def test_candidate_checkpoint_is_never_accepted():
    wo = m.enter_block_checkpoint(code_approved(executing()), "b1", current_state=state())
    view = to_detail(wo)
    assert view.audit.verdict == "NOT_YET_PROVEN"
    assert view.audit.verification == "PENDING"
    assert view.audit.checkpoint is None
    statuses = [(i.id, i.status, i.sha) for i in view.checkpoints.items]
    assert statuses == [("C0", "baseline", BASE), ("C1", "candidate", None)]


def test_rejected_checkpoint_stays_evidence_not_acceptance():
    wo = m.enter_block_checkpoint(code_approved(executing()), "b1", current_state=state())
    wo = m.prove_block_checkpoint(wo, "b1", proof=proof_for(state(7), commit="e" * 40))
    view = to_detail(wo)
    assert view.reason == "BLOCK_CHECKPOINT_MISMATCH"
    assert view.audit.verdict == "CHECKPOINT_REJECTED"
    assert view.audit.verification == "MISMATCH"
    assert not [i for i in view.checkpoints.items if i.status == "accepted"]
    assert ("C1", "rejected", "e" * 40) in [(i.id, i.status, i.sha) for i in view.checkpoints.items]


# --- unknown domain enum/state -> explicit mapping failure ---


def test_unknown_status_value_fails_closed():
    with pytest.raises(UnsupportedDomainState):
        ui_state("SOMETHING_NEW")


def test_unmapped_block_status_fails_closed(monkeypatch):
    wo = m.begin_attempt(executing(), "b1", profile=OPUS)
    table = {k: v for k, v in adapter.BLOCK_STAGE.items() if k != BlockStatus.RUNNING}
    monkeypatch.setattr(adapter, "BLOCK_STAGE", table)
    with pytest.raises(UnsupportedDomainState, match="block status"):
        lifecycle(wo)


def test_unmapped_attention_code_fails_closed(monkeypatch):
    wo = independence(executing())
    monkeypatch.setattr(adapter, "ATTENTION_CODES", frozenset())
    with pytest.raises(UnsupportedDomainState, match="attention code"):
        to_detail(wo)


def test_unknown_status_in_history_fails_closed():
    events = [ControlEvent("wo-1", 1, "created", "SOMETHING_NEW")]
    with pytest.raises(UnsupportedDomainState, match="history"):
        to_detail(new_work_order(), events)


# --- reload of same domain state -> identical view model ---


def test_reload_produces_identical_view_model():
    wo = independence(block_done(executing(blocks=TWO_BLOCKS), "b1"))
    reloaded = WorkOrder.model_validate_json(wo.model_dump_json())
    assert to_detail(reloaded) == to_detail(wo)
    assert to_detail(reloaded).to_json() == to_detail(wo).to_json()


# --- nothing the control store does not hold is invented ---


def test_no_invented_runtime_or_cost_values():
    data = to_detail(code_approved(executing())).to_json()
    for absent in ("elapsedSec", "cost", "steps", "memory", "createdAt", "when"):
        assert absent not in data
    assert data["execution"]["runtime"] == "unavailable"
    assert "browser" not in data["execution"]
    assert {c["status"] for c in data["plan"]["acceptanceCriteria"]} == {"unassessed"}
    assert "routing" not in data["plan"]
    assert data["budget"] == {"maxAttemptsPerBlock": 2}


def test_evidence_count_counts_distinct_references():
    wo = code_approved(executing())
    # context report, tests, audit, diff: each distinct (kind, ref) once.
    assert to_detail(wo).evidence_count == 4


def test_memory_curation_reflects_memory_audit():
    wo = block_done(executing(blocks=(spec(memory_impact=True),)))
    [curation] = to_detail(wo).memory_curation
    assert curation.status == "approved"
    assert curation.changed_paths == ["docs/components/app.md"]
    assert curation.outside_paths == []
    assert curation.auditor == "memory-auditor v1"
    assert curation.audit_status == "VERIFIED"


def test_failed_tests_are_not_presented_as_passing():
    wo = m.begin_attempt(executing(), "b1", profile=OPUS)
    wo = m.record_tests(m.finish_run(wo, "b1"), "b1", passing_checks(state(), passed=False))
    view = to_detail(wo)
    assert view.audit is None  # no code audit recorded yet
    assert view.execution.blocks[0].phase == "BLOCK_RESULT"
    # A code audit on failing tests cannot approve; the adapter does not guess an outcome.
    with pytest.raises(m.TransitionRejected):
        m.approve_code(wo, "b1", audit=audit(state()), changes=changes(), current_state=state())
