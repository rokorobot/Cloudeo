"""Mission Control read path end to end: real temporary SQLite control store ->
read-only query source -> UI view model, and the GET-only HTTP surface."""

import sqlite3

import pytest
from control_helpers import persist_attention_work_order, project_profile
from fastapi import FastAPI
from fastapi.testclient import TestClient

from cloudeo.control.store import NotFoundError, SqliteControlStore
from cloudeo.mission_control import api
from cloudeo.mission_control.query import (
    ControlStoreUnavailable,
    ReadOnlySqliteControlStore,
    UnsupportedDomainState,
    WorkOrderQuerySource,
)
from cloudeo.mission_control.views import UnsupportedWorkOrderView


@pytest.fixture
def db_path(tmp_path):
    """A control store with one WorkOrder driven to attention, as a real caller would."""
    path = tmp_path / "control.db"
    store = SqliteControlStore(path)
    store.save_profile(project_profile())
    persist_attention_work_order(store)
    return path


def test_real_store_to_view_model(db_path):
    source = WorkOrderQuerySource(ReadOnlySqliteControlStore(db_path))
    view = source.get_work_order("wo-1")

    assert view.id == "wo-1"
    assert view.version == 8
    assert view.state == "attention"
    assert view.reason == "INDEPENDENCE_UNAVAILABLE"
    assert view.current_stage == "execute"
    assert view.stages["execute"] == "attention"
    assert view.blocks.done == 1 and view.blocks.total == 2
    assert view.checkpoints.repo == "demo"
    assert [i.status for i in view.checkpoints.items] == ["baseline", "accepted"]
    assert [(h.version, h.event, h.state) for h in view.history] == [
        (1, "created", "draft"),
        (2, "intake_started", "intake"),
        (3, "plan_proposed", "plan_proposed"),
        (4, "plan_approved", "plan_approved"),
        (5, "candidate_attached", "plan_approved"),
        (6, "execution_started", "executing"),
        (7, "block_b1_done", "executing"),
        (8, "attention_raised", "attention"),
    ]
    assert [t.label for t in view.timestamps] == [
        "Execution profile v1 approved",
        "Plan v1 approved",
    ]
    # Reading twice gives the identical view model.
    assert source.get_work_order("wo-1") == view

    [summary] = source.list_work_orders()
    assert (summary.id, summary.state, summary.reason) == (
        "wo-1",
        "attention",
        "INDEPENDENCE_UNAVAILABLE",
    )


def test_read_only_store_cannot_write(db_path):
    before = db_path.read_bytes()
    ro = ReadOnlySqliteControlStore(db_path)
    wo = ro.get("wo-1")
    with pytest.raises(sqlite3.OperationalError, match="readonly"):
        ro.update(wo, expected_version=wo.version, event="should_fail")
    assert db_path.read_bytes() == before


def test_missing_store_is_not_created(tmp_path):
    missing = tmp_path / "absent.db"
    with pytest.raises(ControlStoreUnavailable):
        ReadOnlySqliteControlStore(missing)
    assert not missing.exists()


def test_unloadable_record_is_listed_as_unsupported(db_path):
    db = sqlite3.connect(db_path)
    data = db.execute("SELECT data FROM work_orders WHERE work_order_id='wo-1'").fetchone()[0]
    db.execute(
        "INSERT INTO work_orders VALUES (?, ?, ?)",
        (
            "wo-2",
            1,
            data.replace('"USER_ATTENTION_REQUIRED"', '"SOMETHING_NEW"').replace("wo-1", "wo-2"),
        ),
    )
    db.commit()
    db.close()

    source = WorkOrderQuerySource(ReadOnlySqliteControlStore(db_path))
    listed = {v.id: v for v in source.list_work_orders()}
    assert listed["wo-1"].state == "attention"
    assert isinstance(listed["wo-2"], UnsupportedWorkOrderView)
    with pytest.raises(UnsupportedDomainState):
        source.get_work_order("wo-2")
    with pytest.raises(NotFoundError):
        source.get_work_order("wo-404")


# --- HTTP surface: GET only ---


@pytest.fixture
def client(db_path, monkeypatch):
    monkeypatch.setattr(api.settings, "control_db_path", str(db_path))
    app = FastAPI()
    app.include_router(api.router)
    return TestClient(app)


def test_http_read_endpoints(client):
    listed = client.get("/v1/mission-control/work-orders")
    assert listed.status_code == 200
    assert listed.json()["workOrders"][0]["reason"] == "INDEPENDENCE_UNAVAILABLE"

    detail = client.get("/v1/mission-control/work-orders/wo-1")
    assert detail.status_code == 200
    body = detail.json()
    assert body["currentStage"] == "execute"
    assert body["source"] == "control"
    assert body["execution"]["runtime"] == "unavailable"

    missing = client.get("/v1/mission-control/work-orders/wo-404")
    assert missing.status_code == 404


def test_http_surface_has_no_write_methods(client):
    for method in ("post", "put", "patch", "delete"):
        response = getattr(client, method)("/v1/mission-control/work-orders/wo-1")
        assert response.status_code == 405, method


def test_http_reports_missing_store(tmp_path, monkeypatch):
    monkeypatch.setattr(api.settings, "control_db_path", str(tmp_path / "absent.db"))
    app = FastAPI()
    app.include_router(api.router)
    response = TestClient(app).get("/v1/mission-control/work-orders")
    assert response.status_code == 503
    assert response.json()["detail"]["error"] == "control_store_unavailable"
