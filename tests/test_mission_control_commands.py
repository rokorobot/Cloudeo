"""Mission Control owner commands (ADR-038): availability, the command service
over a real SQLite control store, and the authenticated HTTP endpoint."""

from datetime import UTC, datetime

import pytest
from control_helpers import (
    BASE,
    new_work_order,
    persist_attention_work_order,
    plan,
    project_profile,
    ref,
    register_all,
)
from fastapi import FastAPI
from fastapi.testclient import TestClient

from cloudeo.control import machine as m
from cloudeo.control.model import AttentionCode, AttentionReason, WorkOrderStatus
from cloudeo.control.store import SqliteControlStore, StaleWriteError
from cloudeo.mission_control import api
from cloudeo.mission_control.commands import (
    NO_BROKER,
    CommandRefused,
    CommandService,
    available_commands,
)

S = WorkOrderStatus
WHEN = datetime(2026, 11, 2, 9, 30, tzinfo=UTC)
TOKEN = "t" * 40


def proposed():
    wo = m.start_intake(new_work_order(), accepted_baseline=BASE)
    return m.propose_plan(wo, plan())


def intake_attention(severity="blocking"):
    wo = m.start_intake(new_work_order(), accepted_baseline=BASE)
    reason = AttentionReason(
        code=AttentionCode.PLAN_AMBIGUITY,
        severity=severity,
        summary="two readings of the objective",
        evidence=(ref("context_report", "ctx-1"),),
    )
    return m.raise_attention(wo, reason)


def offered(wo):
    return {a.command: (a.enabled, a.reason) for a in available_commands(wo)}


# --- availability (pure) ---


def test_plan_proposed_offers_approve_and_reject():
    assert offered(proposed()) == {"approve_plan": (True, None), "reject_plan": (True, None)}


def test_attention_from_execution_disables_resume_for_the_baseline(store):
    wo = persist_attention_work_order(store)
    assert offered(wo) == {
        "resume": (False, NO_BROKER),
        "replan": (True, None),
        "defer": (True, None),
        "abort": (True, None),
    }


def test_resume_needs_blocking_reasons_closed():
    enabled, reason = offered(intake_attention("blocking"))["resume"]
    assert not enabled and "PLAN_AMBIGUITY" in reason
    assert offered(intake_attention("warning"))["resume"] == (True, None)


@pytest.mark.parametrize(
    "status_wo", [new_work_order, lambda: m.start_intake(new_work_order(), accepted_baseline=BASE)]
)
def test_states_without_owner_commands_offer_none(status_wo):
    assert available_commands(status_wo()) == []


# --- service over a real store ---


@pytest.fixture
def store(tmp_path):
    s = SqliteControlStore(tmp_path / "control.db")
    register_all(s)
    s.save_profile(project_profile())
    return s


def service(store):
    return CommandService(store, actor="robert", clock=lambda: WHEN)


def persist(store, wo):
    return store.create(wo, event="created")


def test_approve_plan_records_the_configured_owner(store):
    wo = persist(store, proposed())
    done = service(store).run("wo-1", "approve_plan", expected_version=wo.version)
    assert done.status == S.PLAN_APPROVED
    assert done.approvals[-1].approved_by == "robert"
    assert done.approvals[-1].approved_at == WHEN
    assert store.events("wo-1")[-1].event == "owner_approve_plan"


def test_reject_plan_aborts(store):
    wo = persist(store, proposed())
    assert (
        service(store).run("wo-1", "reject_plan", expected_version=wo.version).status == S.ABORTED
    )


@pytest.mark.parametrize(
    ("command", "status"),
    [("abort", S.ABORTED), ("defer", S.DEFERRED), ("replan", S.PLAN_PROPOSED)],
)
def test_attention_decisions(store, command, status):
    wo = persist_attention_work_order(store)
    done = service(store).run("wo-1", command, expected_version=wo.version, message="owner note")
    assert done.status == status
    decision = done.attention[-1].decisions[-1]
    assert (decision.action, decision.actor, decision.at, decision.message) == (
        command,
        "robert",
        WHEN,
        "owner note",
    )
    assert decision.waived == ()


def test_resume_where_no_baseline_is_needed(store):
    wo = persist(store, intake_attention("warning"))
    assert (
        service(store).run("wo-1", "resume", expected_version=wo.version).status == S.CONTEXT_INTAKE
    )


def test_stale_version_writes_nothing(store):
    wo = persist_attention_work_order(store)
    before = store.events("wo-1")
    with pytest.raises(StaleWriteError):
        service(store).run("wo-1", "abort", expected_version=wo.version - 1)
    assert store.events("wo-1") == before


@pytest.mark.parametrize(
    ("command", "code"),
    [
        ("resume", "not_available"),
        ("approve_plan", "not_applicable"),
        ("reject_plan", "not_applicable"),
    ],
)
def test_refused_commands_write_nothing(store, command, code):
    wo = persist_attention_work_order(store)
    before = store.events("wo-1")
    with pytest.raises(CommandRefused) as refused:
        service(store).run("wo-1", command, expected_version=wo.version)
    assert refused.value.code == code
    assert store.events("wo-1") == before


def test_state_machine_rejections_surface_as_refusals(store, monkeypatch):
    wo = persist(store, proposed())

    def reject(*_a, **_k):
        raise m.TransitionRejected("replan_changes_done_block", "nope")

    monkeypatch.setattr(m, "approve_plan", reject)
    with pytest.raises(CommandRefused) as refused:
        service(store).run("wo-1", "approve_plan", expected_version=wo.version)
    assert refused.value.code == "replan_changes_done_block"
    assert store.get("wo-1").version == wo.version


# --- HTTP ---


@pytest.fixture
def db_path(store, tmp_path):
    persist_attention_work_order(store)
    return tmp_path / "control.db"


@pytest.fixture
def configured(db_path, monkeypatch):
    monkeypatch.setattr(api.settings, "control_db_path", str(db_path))
    monkeypatch.setattr(api.settings, "mission_control_owner", "robert")
    monkeypatch.setattr(api.settings, "mission_control_owner_token", TOKEN)
    app = FastAPI()
    app.include_router(api.router)
    app.include_router(api.commands_router)
    return TestClient(app)


URL = "/v1/mission-control/work-orders/wo-1/commands"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


def version(client):
    return client.get("/v1/mission-control/work-orders/wo-1").json()["version"]


def test_http_command_records_and_reports(configured, store):
    v = version(configured)
    r = configured.post(URL, json={"command": "defer", "expectedVersion": v}, headers=AUTH)
    assert r.status_code == 200, r.text
    assert r.json() == {"workOrderId": "wo-1", "version": v + 1, "command": "defer"}
    stored = store.get("wo-1")
    assert stored.status == S.DEFERRED
    assert stored.attention[-1].decisions[-1].actor == "robert"
    detail = configured.get("/v1/mission-control/work-orders/wo-1").json()
    assert detail["commands"] == []


def test_http_stale_version_is_a_conflict(configured):
    v = version(configured)
    r = configured.post(URL, json={"command": "abort", "expectedVersion": v - 1}, headers=AUTH)
    assert r.status_code == 409
    assert r.json()["detail"]["error"] == "stale_version"


def test_http_unavailable_command_is_a_conflict_with_reason(configured):
    r = configured.post(
        URL, json={"command": "resume", "expectedVersion": version(configured)}, headers=AUTH
    )
    assert r.status_code == 409
    assert r.json()["detail"] == {"error": "not_available", "message": NO_BROKER}


@pytest.mark.parametrize(
    ("headers", "status", "error"),
    [
        ({}, 401, "unauthorized"),
        ({"Authorization": "Bearer wrong"}, 401, "unauthorized"),
        ({"Authorization": TOKEN}, 401, "unauthorized"),
        ({**AUTH, "Origin": "http://127.0.0.1:3000"}, 403, "browser_origin"),
        ({**AUTH, "Origin": "https://evil.example"}, 403, "browser_origin"),
    ],
)
def test_http_requires_owner_token_server_to_server(configured, store, headers, status, error):
    before = store.events("wo-1")
    r = configured.post(
        URL, json={"command": "abort", "expectedVersion": version(configured)}, headers=headers
    )
    assert r.status_code == status
    assert r.json()["detail"]["error"] == error
    assert store.events("wo-1") == before


@pytest.mark.parametrize(
    "body",
    [
        {"command": "abort", "expectedVersion": 1, "actor": "someone-else"},
        {"command": "change_budget", "expectedVersion": 1},
        {"command": "abort"},
        {"command": "abort", "expectedVersion": 1, "waived": ["INDEPENDENCE_UNAVAILABLE"]},
    ],
)
def test_http_rejects_anything_beyond_the_command(configured, store, body):
    before = store.events("wo-1")
    assert configured.post(URL, json=body, headers=AUTH).status_code == 422
    assert store.events("wo-1") == before


@pytest.mark.parametrize(("owner", "token"), [(None, TOKEN), ("robert", None), ("robert", "short")])
def test_http_refuses_when_not_configured(configured, monkeypatch, owner, token):
    monkeypatch.setattr(api.settings, "mission_control_owner", owner)
    monkeypatch.setattr(api.settings, "mission_control_owner_token", token)
    r = configured.post(
        URL,
        json={"command": "abort", "expectedVersion": 1},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 503
    assert r.json()["detail"]["error"] == "commands_not_configured"


def test_http_missing_store_is_not_created(configured, monkeypatch, tmp_path):
    absent = tmp_path / "absent.db"
    monkeypatch.setattr(api.settings, "control_db_path", str(absent))
    r = configured.post(URL, json={"command": "abort", "expectedVersion": 1}, headers=AUTH)
    assert r.status_code == 503
    assert not absent.exists()


def test_http_unknown_work_order(configured):
    r = configured.post(
        "/v1/mission-control/work-orders/wo-404/commands",
        json={"command": "abort", "expectedVersion": 1},
        headers=AUTH,
    )
    assert r.status_code == 404


def test_read_router_stays_get_only():
    methods = {method for route in api.router.routes for method in route.methods}
    assert methods <= {"GET", "HEAD"}
