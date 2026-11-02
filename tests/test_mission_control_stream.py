"""Mission Control realtime stream: SSE over the append-only control event log."""

import asyncio
import json

import pytest
from control_helpers import (
    persist_attention_work_order,
    persist_candidate_work_order,
    project_profile,
    register_all,
)
from fastapi import FastAPI
from fastapi.testclient import TestClient

from cloudeo.control.store import SqliteControlStore
from cloudeo.mission_control import api
from cloudeo.mission_control.query import ReadOnlySqliteControlStore
from cloudeo.mission_control.stream import control_events


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "control.db"
    store = SqliteControlStore(path)
    register_all(store)
    store.save_profile(project_profile())
    persist_attention_work_order(store)
    return path


def parse(raw: str) -> dict:
    fields = dict(line.split(": ", 1) for line in raw.strip().splitlines() if ": " in line)
    return {
        "id": int(fields["id"]) if "id" in fields else None,
        "event": fields.get("event"),
        "data": json.loads(fields["data"]) if "data" in fields else None,
        "comment": raw.startswith(":"),
    }


async def never() -> bool:
    return False


async def take(stream, count: int, timeout: float = 5.0) -> list[dict]:
    """The next `count` frames, skipping the retry hint."""
    out: list[dict] = []

    async def run():
        async for raw in stream:
            if raw.startswith("retry:"):
                continue
            out.append(parse(raw))
            if len(out) == count:
                return

    await asyncio.wait_for(run(), timeout)
    return out


def store(path) -> ReadOnlySqliteControlStore:
    return ReadOnlySqliteControlStore(path)


async def test_fresh_subscription_starts_with_ready_at_head(db_path):
    head = store(db_path).head_cursor()
    assert head > 0
    [ready] = await take(control_events(store(db_path), None, disconnected=never), 1)
    assert ready["event"] == "ready"
    assert ready["data"] == {"cursor": head}
    assert ready["id"] == head


async def test_new_events_are_pushed_in_order(db_path):
    stream = control_events(store(db_path), None, disconnected=never, poll_seconds=0.01)
    [ready] = await take(stream, 1)
    persist_candidate_work_order(SqliteControlStore(db_path))
    stored = SqliteControlStore(db_path).events("wo-2")
    frames = await take(stream, len(stored))
    assert {f["event"] for f in frames} == {"work-order"}
    assert {f["data"]["workOrderId"] for f in frames} == {"wo-2"}
    cursors = [f["id"] for f in frames]
    assert cursors == sorted(cursors) and cursors[0] > ready["id"]
    assert [(f["data"]["version"], f["data"]["event"]) for f in frames] == [
        (e.version, e.event) for e in stored
    ]
    assert all(f["data"]["cursor"] == f["id"] for f in frames)
    await stream.aclose()


async def test_resume_replays_only_what_was_missed(db_path):
    read = store(db_path)
    first_wo1 = read.events_after(0)[0].cursor
    remaining = len(read.events_after(first_wo1))
    frames = await take(control_events(read, first_wo1, disconnected=never), remaining)
    assert all(f["event"] == "work-order" for f in frames)
    assert frames[0]["id"] == first_wo1 + 1
    assert frames[-1]["id"] == read.head_cursor()


async def test_cursor_ahead_of_store_resets_with_ready(db_path):
    head = store(db_path).head_cursor()
    [ready] = await take(control_events(store(db_path), head + 100, disconnected=never), 1)
    assert ready["event"] == "ready"
    assert ready["data"] == {"cursor": head}


async def test_idle_stream_sends_heartbeats(db_path):
    stream = control_events(
        store(db_path), None, disconnected=never, poll_seconds=0.01, heartbeat_seconds=0.02
    )
    frames = await take(stream, 2)
    assert frames[1]["comment"]
    await stream.aclose()


async def test_stream_ends_when_client_disconnects(db_path):
    async def gone() -> bool:
        return True

    frames = [f async for f in control_events(store(db_path), None, disconnected=gone)]
    assert [parse(f)["event"] for f in frames[1:]] == ["ready"]


async def test_store_that_disappears_ends_with_unavailable(db_path):
    stream = control_events(store(db_path), None, disconnected=never, poll_seconds=0.01)
    await take(stream, 1)
    db_path.unlink()
    [gone] = await take(stream, 1)
    assert gone["event"] == "unavailable"
    assert gone["data"]["error"] == "control_store_unavailable"


async def test_stream_never_writes(db_path):
    before = db_path.read_bytes()
    stream = control_events(store(db_path), 0, disconnected=never)
    await take(stream, 3)
    await stream.aclose()
    assert db_path.read_bytes() == before


# --- HTTP surface ---


@pytest.fixture
def client(db_path, monkeypatch):
    monkeypatch.setattr(api.settings, "control_db_path", str(db_path))
    app = FastAPI()
    app.include_router(api.router)
    return TestClient(app)


def test_http_stream_is_get_only(client):
    for method in ("post", "put", "patch", "delete"):
        assert getattr(client, method)("/v1/mission-control/stream").status_code == 405


def test_http_stream_rejects_bad_cursors(client):
    bad_header = client.get("/v1/mission-control/stream", headers={"Last-Event-ID": "x"})
    assert bad_header.status_code == 400
    assert bad_header.json()["detail"]["error"] == "bad_cursor"
    assert client.get("/v1/mission-control/stream?after=-1").status_code == 422


def test_http_stream_reports_missing_store(tmp_path, monkeypatch):
    monkeypatch.setattr(api.settings, "control_db_path", str(tmp_path / "absent.db"))
    app = FastAPI()
    app.include_router(api.router)
    response = TestClient(app).get("/v1/mission-control/stream")
    assert response.status_code == 503
    assert response.json()["detail"]["error"] == "control_store_unavailable"
