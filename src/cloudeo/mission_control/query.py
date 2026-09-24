"""WorkOrderQuerySource: the read side Mission Control uses in control mode.

Only reads. There is deliberately no command counterpart here: pause, resume,
stop, take-control and policy amendments are not connected in this slice.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Protocol

from pydantic import ValidationError

from cloudeo.control.model import WorkOrder
from cloudeo.control.store import ControlEvent, NotFoundError, SqliteControlStore
from cloudeo.mission_control.adapter import UnsupportedDomainState, to_detail, to_summary
from cloudeo.mission_control.views import (
    UnsupportedWorkOrderView,
    WorkOrderDetailView,
    WorkOrderSummaryView,
)


class WorkOrderReader(Protocol):
    """The narrow read surface the adapter needs from a control store."""

    def work_order_ids(self) -> list[str]: ...

    def get(self, work_order_id: str) -> WorkOrder: ...

    def events(self, work_order_id: str) -> list[ControlEvent]: ...


class ControlStoreUnavailable(RuntimeError):
    pass


class ReadOnlySqliteControlStore(SqliteControlStore):
    """SqliteControlStore opened read-only: it never creates, migrates, or writes.

    SQLite enforces this (mode=ro), so any write path fails at the connection.
    """

    def __init__(self, path: Path | str):
        resolved = Path(path).resolve()
        if not resolved.is_file():
            raise ControlStoreUnavailable(f"no control store at {resolved}")
        self._path = str(resolved)

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(f"{Path(self._path).as_uri()}?mode=ro", uri=True, timeout=5)


class WorkOrderQuerySource:
    def __init__(self, reader: WorkOrderReader):
        self._reader = reader

    def get_work_order(self, work_order_id: str) -> WorkOrderDetailView:
        """Raises NotFoundError, or UnsupportedDomainState for records the UI cannot present."""
        try:
            work_order = self._reader.get(work_order_id)
        except ValidationError as exc:
            raise UnsupportedDomainState(
                f"{work_order_id} does not load under the current control model: "
                f"{exc.error_count()} validation error(s)"
            ) from exc
        return to_detail(work_order, self._reader.events(work_order_id))

    def list_work_orders(self) -> list[WorkOrderSummaryView | UnsupportedWorkOrderView]:
        """Every stored WorkOrder; ones that cannot be presented are listed as unsupported."""
        views: list[WorkOrderSummaryView | UnsupportedWorkOrderView] = []
        for work_order_id in self._reader.work_order_ids():
            try:
                views.append(to_summary(self._reader.get(work_order_id)))
            except (ValidationError, UnsupportedDomainState) as exc:
                reason = (
                    f"does not load under the current control model ({exc.error_count()} errors)"
                    if isinstance(exc, ValidationError)
                    else str(exc)
                )
                views.append(UnsupportedWorkOrderView(id=work_order_id, unsupported=reason))
        return views


__all__ = [
    "ControlStoreUnavailable",
    "NotFoundError",
    "ReadOnlySqliteControlStore",
    "UnsupportedDomainState",
    "WorkOrderQuerySource",
    "WorkOrderReader",
]
