"""HTTP surface for Mission Control.

`router` is read-only (GET only): the store is opened read-only on every
request. `commands_router` is the single owner-command endpoint (ADR-038),
mounted separately so the read surface stays GET-only. Both are under
/v1/mission-control; the store path comes from CLOUDEO_CONTROL_DB_PATH.
"""

from __future__ import annotations

import hmac
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from cloudeo.config import settings
from cloudeo.control.store import SqliteControlStore, StaleWriteError
from cloudeo.mission_control.commands import CommandName, CommandRefused, CommandService
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


# --- Owner commands (ADR-038) ---

commands_router = APIRouter(prefix="/v1/mission-control", tags=["mission-control-commands"])

MIN_TOKEN_LENGTH = 32


def _refuse(status: int, error: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"error": error, "message": message})


def owner(
    authorization: Annotated[str | None, Header()] = None,
    origin: Annotated[str | None, Header()] = None,
) -> str:
    """The configured owner, if the caller holds the owner token.

    Only the Mission Control server calls this, server to server. A browser
    always sends Origin on a POST, so any request carrying one is refused:
    no web page can reach this endpoint, even from localhost.
    """
    actor, token = settings.mission_control_owner, settings.mission_control_owner_token
    if not actor or not token or len(token) < MIN_TOKEN_LENGTH:
        raise _refuse(
            503,
            "commands_not_configured",
            "set CLOUDEO_MISSION_CONTROL_OWNER and CLOUDEO_MISSION_CONTROL_OWNER_TOKEN "
            f"(at least {MIN_TOKEN_LENGTH} characters)",
        )
    if origin is not None:
        raise _refuse(403, "browser_origin", "owner commands are accepted server to server only")
    scheme, _, presented = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not hmac.compare_digest(presented.encode(), token.encode()):
        raise _refuse(401, "unauthorized", "owner token required")
    return actor


def writable_store() -> SqliteControlStore:
    """The control store opened for writing; a missing store is never created."""
    path = Path(settings.control_db_path).resolve()
    if not path.is_file():
        raise _refuse(503, "control_store_unavailable", f"no control store at {path}")
    return SqliteControlStore(path)


class CommandRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    command: CommandName
    expected_version: int = Field(ge=1, alias="expectedVersion")
    message: str = Field(default="", max_length=2000)


@commands_router.post("/work-orders/{work_order_id}/commands")
def run_command(
    work_order_id: str,
    request: CommandRequest,
    actor: Annotated[str, Depends(owner)],
) -> dict:
    service = CommandService(writable_store(), actor=actor)
    try:
        updated = service.run(
            work_order_id,
            request.command,
            expected_version=request.expected_version,
            message=request.message,
        )
    except NotFoundError as exc:
        raise _refuse(404, "not_found", work_order_id) from exc
    except StaleWriteError as exc:
        raise _refuse(
            409, "stale_version", "the WorkOrder changed since it was shown; nothing was recorded"
        ) from exc
    except CommandRefused as exc:
        raise _refuse(409, exc.code, exc.message) from exc
    return {"workOrderId": work_order_id, "version": updated.version, "command": request.command}
