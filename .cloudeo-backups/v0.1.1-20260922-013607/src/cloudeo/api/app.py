from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from sqlmodel import select

from cloudeo.adapters.jev import JevError, build_jev_client
from cloudeo.adapters.treg import TregError, build_treg_client
from cloudeo.config import settings
from cloudeo.core.controller import Controller
from cloudeo.db.models import RunRecord
from cloudeo.db.session import Database
from cloudeo.models import DecisionRequest, RunRequest, RunResponse


database = Database(settings)
jev = build_jev_client(settings)
treg = build_treg_client(settings)
controller = Controller(settings, jev, treg, database)


@asynccontextmanager
async def lifespan(_: FastAPI):
    await database.init()
    yield


app = FastAPI(
    title="Cloudeo",
    version="0.1.0",
    description="Local-first decision, tool-routing, and verification control plane.",
    lifespan=lifespan,
)


@app.get("/health")
async def health() -> dict[str, str]:
    return {
        "status": "ok",
        "version": "0.1.0",
        "jev_backend": settings.jev_backend,
        "treg_backend": settings.treg_backend,
    }


@app.post("/v1/decide")
async def decide(request: DecisionRequest):
    try:
        questions = {key: value.model_dump(exclude_none=True) for key, value in request.questions.items()}
        return await jev.decide(request.state, questions)
    except JevError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/v1/runs", response_model=RunResponse)
async def run(request: RunRequest) -> RunResponse:
    try:
        return await controller.run(request)
    except (JevError, TregError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/v1/runs")
async def list_runs(limit: int = 20):
    limit = max(1, min(limit, 100))
    async with database.session() as session:
        rows = (await session.exec(select(RunRecord).order_by(RunRecord.created_at.desc()).limit(limit))).all()
    return [
        {
            "id": row.id,
            "created_at": row.created_at,
            "objective": row.objective,
            "status": row.status,
            "selected_tool": row.selected_tool,
            "route_confidence": row.route_confidence,
        }
        for row in rows
    ]
