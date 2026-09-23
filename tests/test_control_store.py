"""Control store: persistence, CAS concurrency, evolution rules, reload (V2C-11/18/21/23)."""

import json
import sqlite3

import pytest
from control_helpers import (
    BASE,
    NOW,
    OPUS_FALLBACK,
    block_done,
    final_verification,
    new_work_order,
    outcome,
    plan,
    project_profile,
    ref,
)
from pydantic import ValidationError

from cloudeo.control import machine as m
from cloudeo.control.model import (
    AttentionCode,
    AttentionReason,
    BlockStatus,
    Candidate,
    EnvelopeAmendment,
    EvolutionError,
    UserAction,
    UserDecision,
    WorkOrderStatus,
)
from cloudeo.control.store import (
    ControlStore,
    ControlStoreError,
    ImmutableRecordError,
    NotFoundError,
    SqliteControlStore,
    StaleWriteError,
)

S = WorkOrderStatus


@pytest.fixture
def store(tmp_path):
    s = SqliteControlStore(tmp_path / "control.db")
    s.save_profile(project_profile())
    return s


def persist_steps(store, steps):
    """Apply each machine step through the store, as a real caller would."""
    wo = store.create(new_work_order(), event="created")
    for event, step in steps:
        wo = store.update(step(wo), expected_version=wo.version, event=event)
    return wo


HAPPY = [
    ("intake", lambda wo: m.start_intake(wo, accepted_baseline=BASE)),
    ("plan_proposed", lambda wo: m.propose_plan(wo, plan())),
    (
        "plan_approved",
        lambda wo: m.approve_plan(wo, plan_version=1, approved_by="robert", approved_at=NOW),
    ),
    (
        "candidate",
        lambda wo: m.attach_candidate(
            wo,
            Candidate(workspace_id="demo", candidate_id="c1", base_commit=BASE),
            accepted_baseline=BASE,
        ),
    ),
    ("executing", lambda wo: m.start_execution(wo, accepted_baseline=BASE)),
    ("block_done", block_done),
    ("final", lambda wo: m.enter_final_verification(wo, accepted_baseline=BASE)),
]


def test_store_implements_the_interface_and_has_no_delete(store):
    assert isinstance(store, SqliteControlStore)
    for name in (
        "save_profile",
        "get_profile",
        "current_profile",
        "create",
        "get",
        "update",
        "events",
    ):
        assert callable(getattr(store, name))
    assert not any("delete" in name or "remove" in name for name in dir(ControlStore))
    assert not any("delete" in name or "remove" in name for name in dir(SqliteControlStore))


# --- Deterministic reload and reconstruction ---


def test_reload_is_deterministic_and_replays_every_version(store, tmp_path):
    wo = persist_steps(store, HAPPY)
    assert wo.version == len(HAPPY) + 1
    reopened = SqliteControlStore(tmp_path / "control.db")
    assert reopened.get("wo-1") == wo
    assert reopened.get("wo-1").model_dump_json() == wo.model_dump_json()
    history = reopened.replay("wo-1")
    assert [v.version for v in history] == list(range(1, len(HAPPY) + 2))
    assert history[-1] == wo
    assert [e.event for e in reopened.events("wo-1")] == ["created", *(e for e, _ in HAPPY)]
    assert reopened.events("wo-1")[-1].status == str(S.FINAL_VERIFICATION)


def test_reload_revalidates_and_rejects_tampered_rows(store, tmp_path):
    wo = persist_steps(store, HAPPY[:5])
    db = sqlite3.connect(tmp_path / "control.db")
    data = wo.model_dump(mode="json")
    data["blocks"][0]["status"] = "BLOCK_DONE"  # forged, without a proven checkpoint
    db.execute("UPDATE work_orders SET data=? WHERE work_order_id='wo-1'", (json.dumps(data),))
    db.commit()
    db.close()
    with pytest.raises(ValidationError, match="BLOCK_DONE"):
        store.get("wo-1")


# --- V2C-23: compare-and-swap ---


def test_v2c_23_concurrent_writers_are_serialized_by_version(store):
    wo = persist_steps(store, HAPPY[:5])
    actor_a = store.get("wo-1")
    actor_b = store.get("wo-1")
    store.update(
        m.begin_attempt(actor_a, "b1", profile=project_profile().bindings[0].primary),
        expected_version=actor_a.version,
        event="a",
    )
    reason = AttentionReason(code=AttentionCode.RISK_REQUIRES_HUMAN, summary="b", evidence=(ref(),))
    with pytest.raises(StaleWriteError):
        store.update(
            m.raise_attention(actor_b, reason), expected_version=actor_b.version, event="b"
        )
    current = store.get("wo-1")
    assert current.version == wo.version + 1
    assert current.block("b1").status == BlockStatus.RUNNING
    assert [e.event for e in store.events("wo-1")][-1] == "a"


def test_v2c_23_stale_expected_version_is_refused(store):
    wo = persist_steps(store, HAPPY[:1])
    with pytest.raises(StaleWriteError):
        store.update(m.propose_plan(wo, plan()), expected_version=wo.version - 1, event="late")
    with pytest.raises(NotFoundError):
        store.get("missing")


# --- Evolution rules are enforced at the storage boundary ---


def test_store_refuses_illegal_successors_even_when_built_directly(store):
    wo = persist_steps(store, HAPPY[:5])
    illegal = [
        wo.evolve(status=S.PLAN_PROPOSED),  # EXECUTING -> PLAN_PROPOSED is not in the table
        wo.evolve(objective="something else"),
        wo.evolve(plan_versions=(plan().evolve(architecture_summary="rewritten"),)),
        wo.evolve(candidate=wo.candidate.evolve(candidate_id="other")),
        wo.evolve(planned_baseline="b" * 40),  # V2C-22: never rebased
    ]
    for candidate in illegal:
        with pytest.raises(EvolutionError):
            store.update(candidate, expected_version=wo.version, event="forged")
    assert store.get("wo-1") == wo


def test_v2c_11_store_refuses_a_profile_snapshot_change_without_amendment(store):
    wo = persist_steps(store, HAPPY[:5])
    newer = project_profile(version=2, executor=OPUS_FALLBACK, fallbacks=())
    store.save_profile(newer)
    with pytest.raises(EvolutionError, match="amendment"):
        store.update(
            wo.evolve(execution_profile=newer), expected_version=wo.version, event="forged"
        )
    # The legitimate path: attention, change_agent with an approved amendment.
    reason = AttentionReason(
        code=AttentionCode.AGENT_UNAVAILABLE, summary="down", evidence=(ref(),)
    )
    wo = store.update(m.raise_attention(wo, reason), expected_version=wo.version, event="attention")
    amendment = EnvelopeAmendment(
        attention_id="att-1",
        action=UserAction.CHANGE_AGENT,
        execution_profile=newer,
        approved_by="robert",
        approved_at=NOW,
    )
    amended = m.decide(
        wo,
        UserDecision(action=UserAction.CHANGE_AGENT, actor="robert", at=NOW),
        amendment=amendment,
    )
    wo = store.update(amended, expected_version=wo.version, event="change_agent")
    assert store.get("wo-1").execution_profile.version == 2


def test_v2c_11_snapshot_must_be_a_stored_approved_profile(store):
    with pytest.raises(ControlStoreError, match="stored profile"):
        store.create(new_work_order(profile=project_profile(version=5)), event="created")
    unsaved = project_profile(version=2, executor=OPUS_FALLBACK, fallbacks=())
    wo = persist_steps(store, HAPPY[:5])
    wo = store.update(
        m.raise_attention(
            wo,
            AttentionReason(code=AttentionCode.AGENT_UNAVAILABLE, summary="x", evidence=(ref(),)),
        ),
        expected_version=wo.version,
        event="attention",
    )
    amended = m.decide(
        wo,
        UserDecision(action=UserAction.CHANGE_AGENT, actor="robert", at=NOW),
        amendment=EnvelopeAmendment(
            attention_id="att-1",
            action=UserAction.CHANGE_AGENT,
            execution_profile=unsaved,
            approved_by="robert",
            approved_at=NOW,
        ),
    )
    with pytest.raises(ControlStoreError, match="stored profile"):
        store.update(amended, expected_version=wo.version, event="change_agent")


def test_terminal_work_orders_are_immutable(store):
    wo = persist_steps(store, HAPPY)
    wo = store.update(
        m.record_final_audit(wo, final_verification().final_audit),
        expected_version=wo.version,
        event="final_audit",
    )
    wo = store.update(
        m.record_kernel_outcome(wo, outcome(True)), expected_version=wo.version, event="promoted"
    )
    assert wo.status == S.PROMOTED
    with pytest.raises(EvolutionError, match="immutable"):
        store.update(
            wo.evolve(evidence=(*wo.evidence, ref())), expected_version=wo.version, event="late"
        )


def test_block_done_blocks_and_closed_attention_are_immutable(store):
    wo = persist_steps(store, HAPPY[:6])
    done = wo.block("b1")
    assert done.status == BlockStatus.BLOCK_DONE
    with pytest.raises(EvolutionError, match="BLOCK_DONE"):
        store.update(
            wo.evolve(blocks=(done.evolve(attempts=()),)),
            expected_version=wo.version,
            event="forged",
        )
    reason = AttentionReason(code=AttentionCode.RISK_REQUIRES_HUMAN, summary="r", evidence=(ref(),))
    wo = store.update(m.raise_attention(wo, reason), expected_version=wo.version, event="attention")
    resumed = m.decide(
        wo,
        UserDecision(
            action=UserAction.RESUME,
            actor="robert",
            at=NOW,
            waived=(AttentionCode.RISK_REQUIRES_HUMAN,),
        ),
        accepted_baseline=BASE,
    )
    wo = store.update(resumed, expected_version=wo.version, event="resume")
    closed = wo.attention[0]
    with pytest.raises(EvolutionError, match="closed attention"):
        store.update(
            wo.evolve(attention=(closed.evolve(decisions=()),)),
            expected_version=wo.version,
            event="forged",
        )


# --- V2C-18: profile versions are immutable ---


def test_v2c_18_profile_versions_are_immutable_and_sequential(store):
    store.save_profile(project_profile())  # identical re-save is a no-op
    with pytest.raises(ImmutableRecordError):
        store.save_profile(project_profile().evolve(approved_by="someone else"))
    with pytest.raises(ControlStoreError, match="next profile version"):
        store.save_profile(project_profile(version=3))
    store.save_profile(project_profile(version=2, executor=OPUS_FALLBACK, fallbacks=()))
    assert store.current_profile("demo").version == 2
    assert store.get_profile("demo", 1) == project_profile()


# --- V2C-21: nothing is deleted ---


def test_v2c_21_aborted_work_order_keeps_its_full_history(store):
    wo = persist_steps(store, HAPPY[:5])
    reason = AttentionReason(code=AttentionCode.RISK_REQUIRES_HUMAN, summary="r", evidence=(ref(),))
    wo = store.update(m.raise_attention(wo, reason), expected_version=wo.version, event="attention")
    wo = store.update(
        m.decide(wo, UserDecision(action=UserAction.ABORT, actor="robert", at=NOW)),
        expected_version=wo.version,
        event="abort",
    )
    assert wo.status == S.ABORTED and wo.candidate is not None
    assert len(store.replay("wo-1")) == wo.version
    assert store.replay("wo-1")[5].status == S.EXECUTING  # version 6
