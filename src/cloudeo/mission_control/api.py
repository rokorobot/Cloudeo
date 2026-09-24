"""Read-only HTTP surface for Mission Control (GET only).

Mounted under /v1/mission-control. The control store path comes from
CLOUDEO_CONTROL_DB_PATH; the store is opened read-only on every request.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from cloudeo.config import settings
from cloudeo.mission_control.query import (
    ControlStoreUnavailable,
    NotFoundError,
    ReadOnlySqliteControlStore,
    UnsupportedDomainState,
    WorkOrderQuerySource,
)

router = APIRouter(prefix="/v1/mission-control", tags=["mission-control"])


def query_source() -> WorkOrderQuerySource:
    try:
        return WorkOrderQuerySource(ReadOnlySqliteControlStore(settings.control_db_path))
    except ControlStoreUnavailable as exc:
        raise HTTPException(
            status_code=503, detail={"error": "control_store_unavailable", "message": str(exc)}
        ) from exc


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
