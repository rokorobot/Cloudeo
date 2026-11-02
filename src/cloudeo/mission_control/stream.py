"""Server-Sent Events over the control store's append-only event log.

The stream carries only *that* something changed (cursor, WorkOrder id,
version, event name). Clients re-read the affected views through the GET
endpoints, so the adapter stays the single place that maps domain records to
view models, and the stream cannot show anything the store does not hold.

Frames:
- ``ready``: sent first on a fresh subscription, and whenever the client's
  cursor is ahead of the store (store replaced). Clients refetch everything.
- ``work-order``: one appended control event. ``id:`` is its cursor, so a
  reconnecting EventSource resumes with Last-Event-ID and misses nothing.
- ``unavailable``: the store could not be read; the stream ends.
- ``: ping`` comments keep idle connections open through proxies.

SQLite has no change notification, so the stream polls the event table. The
query is a rowid range scan and the store is opened read-only.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import time
from collections.abc import AsyncIterator, Awaitable, Callable

from cloudeo.mission_control.query import ControlStoreUnavailable, ReadOnlySqliteControlStore

POLL_SECONDS = 0.5
HEARTBEAT_SECONDS = 15.0
RETRY_MS = 3000


def frame(event: str, data: dict, cursor: int | None = None) -> str:
    head = f"id: {cursor}\n" if cursor is not None else ""
    return f"{head}event: {event}\ndata: {json.dumps(data, separators=(',', ':'))}\n\n"


async def control_events(
    store: ReadOnlySqliteControlStore,
    after: int | None,
    *,
    disconnected: Callable[[], Awaitable[bool]],
    poll_seconds: float = POLL_SECONDS,
    heartbeat_seconds: float = HEARTBEAT_SECONDS,
) -> AsyncIterator[str]:
    yield f"retry: {RETRY_MS}\n\n"
    try:
        head = await asyncio.to_thread(store.head_cursor)
        if after is None or after > head:
            cursor = head
            yield frame("ready", {"cursor": cursor}, cursor)
        else:
            cursor = after
        idle_since = time.monotonic()
        while not await disconnected():
            events = await asyncio.to_thread(store.events_after, cursor)
            for event in events:
                cursor = event.cursor
                yield frame("work-order", event.to_json(), cursor)
            if events:
                idle_since = time.monotonic()
                continue
            if time.monotonic() - idle_since >= heartbeat_seconds:
                idle_since = time.monotonic()
                yield ": ping\n\n"
            await asyncio.sleep(poll_seconds)
    except (sqlite3.Error, ControlStoreUnavailable) as exc:
        yield frame("unavailable", {"error": "control_store_unavailable", "message": str(exc)})
