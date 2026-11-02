"""Operator halt and stop (ADR-039): the owner stops progress through attention."""

import pytest
from control_helpers import (
    BASE,
    MOVED,
    NOW,
    OPUS,
    approved,
    block_done,
    executing,
    final_verification,
    new_work_order,
    persist_attention_work_order,
    project_profile,
    ref,
    register_all,
    spec,
)

from cloudeo.control import machine as m
from cloudeo.control.model import (
    AttentionCode,
    AttentionReason,
    UserAction,
    UserDecision,
    WorkOrderStatus,
    check_evolution,
)
from cloudeo.control.store import SqliteControlStore

S = WorkOrderStatus
Rejected = m.TransitionRejected
HALT = AttentionCode.OPERATOR_HALT


def intake():
    return m.start_intake(new_work_order(), accepted_baseline=BASE)


def proposed():
    return m.propose_plan(intake(), __import__("control_helpers").plan())


def resume(wo, **kw):
    return m.decide(wo, UserDecision(action=UserAction.RESUME, actor="robert", at=NOW), **kw)


HALTABLE = {
    "CONTEXT_INTAKE": intake,
    "PLAN_APPROVED": approved,
    "EXECUTING": executing,
    "FINAL_VERIFICATION": final_verification,
}


@pytest.mark.parametrize("name", HALTABLE)
def test_halt_from_every_active_state(name):
    wo = HALTABLE[name]()
    halted = m.halt(wo, actor="robert", at=NOW, message="hold on")
    check_evolution(wo, halted)
    assert halted.status == S.USER_ATTENTION_REQUIRED
    request = halted.open_attention
    assert request.raised_from == wo.status
    [reason] = request.reasons
    assert (reason.code, reason.severity, reason.summary) == (HALT, "blocking", "hold on")
    assert reason.evidence[0].kind == "owner_command"


def test_halt_without_a_message_names_the_owner():
    assert m.halt(intake(), actor="robert", at=NOW).open_attention.reasons[0].summary == (
        "halted by robert"
    )


@pytest.mark.parametrize(
    "make",
    [
        new_work_order,
        proposed,
        lambda: m.halt(intake(), actor="robert", at=NOW),
        lambda: m.decide(
            m.halt(intake(), actor="r", at=NOW),
            UserDecision(action=UserAction.DEFER, actor="r", at=NOW),
        ),
        lambda: m.reject_plan(proposed()),
    ],
    ids=["draft", "plan_proposed", "already_in_attention", "deferred", "aborted"],
)
def test_halt_refused_outside_active_states(make):
    with pytest.raises(Rejected):
        m.halt(make(), actor="robert", at=NOW)


def test_halted_work_order_accepts_no_block_transition():
    wo = m.begin_attempt(executing(), "b1", profile=OPUS)
    halted = m.halt(wo, actor="robert", at=NOW)
    with pytest.raises(Rejected):
        m.finish_run(halted, "b1")
    fresh = m.halt(executing(blocks=(spec("b1"), spec("b2", 2))), actor="robert", at=NOW)
    with pytest.raises(Rejected):
        m.begin_attempt(fresh, "b1", profile=OPUS)


def test_resume_lifts_the_halt_and_records_it():
    halted = m.halt(intake(), actor="robert", at=NOW)
    resumed = resume(halted)
    check_evolution(halted, resumed)
    assert resumed.status == S.CONTEXT_INTAKE
    closed = resumed.attention[-1]
    assert closed.closed and HALT in closed.resolved_codes
    assert closed.decisions[-1].waived == ()


def test_resume_into_execution_still_rechecks_the_baseline():
    halted = m.halt(executing(), actor="robert", at=NOW)
    with pytest.raises(Rejected):
        resume(halted)  # no baseline given
    drifted = resume(halted, accepted_baseline=MOVED)
    assert drifted.status == S.USER_ATTENTION_REQUIRED
    assert AttentionCode.BASELINE_DRIFT in {r.code for r in drifted.open_attention.reasons}
    assert resume(halted, accepted_baseline=BASE).status == S.EXECUTING


def test_resume_does_not_lift_other_blocking_reasons():
    halted = m.halt(executing(), actor="robert", at=NOW)
    other = AttentionReason(
        code=AttentionCode.AUDITOR_ERROR, summary="auditor down", evidence=(ref(),)
    )
    both = m.raise_attention(halted, other)
    assert both.open_attention.blocking_resume() == (AttentionCode.AUDITOR_ERROR,)
    with pytest.raises(Rejected, match="AUDITOR_ERROR"):
        resume(both, accepted_baseline=BASE)


def test_halt_after_done_blocks_keeps_them_done():
    wo = block_done(executing(blocks=(spec("b1"), spec("b2", 2))))
    resumed = resume(m.halt(wo, actor="robert", at=NOW), accepted_baseline=BASE)
    assert resumed.block("b1").status == wo.block("b1").status


def abort(wo, message=""):
    return m.decide(
        wo, UserDecision(action=UserAction.ABORT, actor="robert", at=NOW, message=message)
    )


@pytest.mark.parametrize("name", HALTABLE)
def test_stop_is_halt_then_abort_both_legal(name):
    wo = HALTABLE[name]()
    halted = m.halt(wo, actor="robert", at=NOW, message="wrong ticket")
    stopped = abort(halted, "wrong ticket")
    check_evolution(wo, halted)
    check_evolution(halted, stopped)
    assert stopped.status == S.ABORTED
    request = stopped.attention[-1]
    assert request.closed and [r.code for r in request.reasons] == [HALT]


@pytest.mark.parametrize("name", HALTABLE)
def test_no_direct_abort_from_an_active_state(name):
    from cloudeo.control.model import EvolutionError

    wo = HALTABLE[name]()
    with pytest.raises(EvolutionError):
        check_evolution(
            wo, abort(m.halt(wo, actor="robert", at=NOW)).evolve(attention=wo.attention)
        )


def test_stop_and_halt_are_stored_like_any_transition(tmp_path):
    store = SqliteControlStore(tmp_path / "control.db")
    register_all(store)
    store.save_profile(project_profile())
    wo = store.create(new_work_order(), event="created")
    wo = store.update(
        m.start_intake(wo, accepted_baseline=BASE), expected_version=wo.version, event="intake"
    )
    wo = store.update(
        m.halt(wo, actor="robert", at=NOW), expected_version=wo.version, event="owner_halt"
    )
    wo = store.update(resume(wo), expected_version=wo.version, event="owner_resume")
    wo = store.update(
        m.halt(wo, actor="robert", at=NOW), expected_version=wo.version, event="owner_stop_halt"
    )
    wo = store.update(abort(wo), expected_version=wo.version, event="owner_stop")
    assert [r.status for r in store.replay(wo.work_order_id)][-4:] == [
        S.USER_ATTENTION_REQUIRED,
        S.CONTEXT_INTAKE,
        S.USER_ATTENTION_REQUIRED,
        S.ABORTED,
    ]


def test_existing_attention_work_orders_are_unaffected(tmp_path):
    store = SqliteControlStore(tmp_path / "control.db")
    register_all(store)
    store.save_profile(project_profile())
    wo = persist_attention_work_order(store)
    assert wo.open_attention.blocking_resume() == wo.open_attention.open_blocking()
