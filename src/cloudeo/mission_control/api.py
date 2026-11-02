"""Read-only HTTP surface for Mission Control (GET only).

Mounted under /v1/mission-control. The control store path comes from
CLOUDEO_CONTROL_DB_PATH; the store is opened read-only on every request.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from cloudeo.config import settings
from cloudeo.mission_control.query import (
    ControlStoreUnavailable,
    NotFoundError,
    ReadOnlySqliteControlStore,
    UnsupportedDomainState,
    WorkOrderQuerySource,
)
from cloudeo.mission_control.stream import control_events

router = APIRouter(prefix="/v1/mission-control", tags=["mission-control"])


def read_only_store() -> ReadOnlySqliteControlStore:
    try:
        return ReadOnlySqliteControlStore(settings.control_db_path)
    except ControlStoreUnavailable as exc:
        raise HTTPException(
            status_code=503, detail={"error": "control_store_unavailable", "message": str(exc)}
        ) from exc


def query_source() -> WorkOrderQuerySource:
    return WorkOrderQuerySource(read_only_store())


Source = Annotated[WorkOrderQuerySource, Depends(query_source)]


@router.get("/work-orders")
def list_work_orders(source: Source) -> dict:
    return {"workOrders": [view.to_json() for view in source.list_work_orders()]}


@router.get("/work-orders/{work_order_id}")
def get_work_order(work_order_id: str, source: Source) -> dict:
    try:
        return source.get_work_order(work_order_id).to_json()
    except NotFoundError as exc:
        raise HTTPException(
            status_code=404, detail={"error": "not_found", "message": work_order_id}
        ) from exc
    except UnsupportedDomainState as exc:
        raise HTTPException(
            status_code=422, detail={"error": "unsupported_domain_state", "message": str(exc)}
        ) from exc


@router.get("/stream")
async def stream(
    request: Request,
    after: Annotated[int | None, Query(ge=0)] = None,
    last_event_id: Annotated[str | None, Header()] = None,
) -> StreamingResponse:
    """SSE of appended control events. A reconnect's Last-Event-ID wins over ?after."""
    cursor = after
    if last_event_id is not None:
        if not last_event_id.isdigit():
            raise HTTPException(
                status_code=400,
                detail={"error": "bad_cursor", "message": "Last-Event-ID must be a cursor"},
            )
        cursor = int(last_event_id)
    return StreamingResponse(
        control_events(read_only_store(), cursor, disconnected=request.is_disconnected),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )
