from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ToolCandidate(BaseModel):
    id: str = Field(min_length=1)
    description: str = Field(min_length=1)
    treg_tool_id: str = Field(min_length=1)
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"] = "GET"
    query: dict[str, str | int | float | bool] = Field(default_factory=dict)
    body: dict[str, Any] = Field(default_factory=dict)


class RunRequest(BaseModel):
    objective: str = Field(min_length=3)
    state: dict[str, Any] = Field(default_factory=dict)
    success_criteria: str = "The tool result directly and sufficiently satisfies the objective."
    candidates: list[ToolCandidate] = Field(min_length=1)
    route_confidence: float | None = Field(default=None, ge=0, le=1)
    verify_probability: float | None = Field(default=None, ge=0, le=1)
    max_attempts: int | None = Field(default=None, ge=1, le=5)
    dry_run: bool = False


class DecisionQuestion(BaseModel):
    type: Literal["choice", "score", "noul"]
    instructions: str
    criteria: dict[str, Any] | list[Any] | None = None


class DecisionRequest(BaseModel):
    state: Any
    questions: dict[str, DecisionQuestion]


class AttemptResult(BaseModel):
    tool_id: str
    route_probability: float
    output: str
    deterministic_status: Literal["pass", "fail", "inconclusive"] = "inconclusive"
    deterministic_evidence: list[str] = Field(default_factory=list)
    verification_source: Literal["deterministic", "jev"] = "jev"
    verification_probability: float
    passed: bool


class RunResponse(BaseModel):
    run_id: str
    status: Literal["passed", "escalate", "failed"]
    selected_tool: str | None
    route_confidence: float
    routing_probabilities: dict[str, float]
    attempts: list[AttemptResult]
    reason: str
