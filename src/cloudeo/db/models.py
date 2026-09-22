from __future__ import annotations

from datetime import datetime, timezone

from sqlmodel import Field, SQLModel


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class RunRecord(SQLModel, table=True):
    id: str = Field(primary_key=True)
    created_at: datetime = Field(default_factory=utc_now)
    objective: str
    status: str
    selected_tool: str | None = None
    route_confidence: float = 0.0
    payload_json: str
    result_json: str
