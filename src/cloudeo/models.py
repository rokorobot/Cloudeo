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

    # Discovery metadata, optional for manually supplied candidates.
    provider: str | None = None
    capability: str | None = None
    quoted_cost_usd: float | None = Field(default=None, ge=0)


class RunRequest(BaseModel):
    objective: str = Field(min_length=3)
    state: dict[str, Any] = Field(default_factory=dict)
    success_criteria: str = (
        "The tool result directly and sufficiently satisfies the objective."
    )
    candidates: list[ToolCandidate] = Field(default_factory=list)
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


class DiscoveryQueryEvidence(BaseModel):
    query: str
    count: int = 0
    total: int = 0
    outcome: Literal["matched", "empty"]


class DiscoveryEndpointEvidence(BaseModel):
    endpoint_id: str
    capability: str | None = None
    provider: str | None = None
    decision: Literal["accepted", "rejected"]
    reason: str
    quoted_cost_usd: float | None = None


class DiscoveryEvidence(BaseModel):
    selected_query: str | None = None
    capability_anchor: str | None = None
    queries: list[DiscoveryQueryEvidence] = Field(default_factory=list)
    endpoints: list[DiscoveryEndpointEvidence] = Field(default_factory=list)


class ExecutionEconomics(BaseModel):
    quoted_cost_usd: float | None = None
    reserved_cost_usd: float | None = None
    settled_cost_usd: float | None = None
    latency_ms: int | None = None
    call_id: str | None = None
    provider_requested: str | None = None
    provider_served: str | None = None
    idempotent_replay: bool = False


class AttemptResult(BaseModel):
    tool_id: str
    route_probability: float
    output: str
    deterministic_status: Literal["pass", "fail", "inconclusive"] = (
        "inconclusive"
    )
    deterministic_evidence: list[str] = Field(default_factory=list)
    verification_source: Literal["deterministic", "jev", "dry_run"] = "jev"
    verification_probability: float
    passed: bool
    economics: ExecutionEconomics | None = None


class RunResponse(BaseModel):
    run_id: str
    status: Literal["passed", "escalate", "failed", "dry_run"]
    selected_tool: str | None
    route_confidence: float
    routing_probabilities: dict[str, float]
    attempts: list[AttemptResult]
    reason: str

    discovery_used: bool = False
    discovery_query: str | None = None
    discovered_candidates: list[str] = Field(default_factory=list)
    discovery_evidence: DiscoveryEvidence | None = None
