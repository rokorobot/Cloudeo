"""UI-facing view models served to Mission Control (control mode).

These mirror mission-control/src/lib/types.ts. Fields the control store does
not hold are absent (serialized with exclude_none), never defaulted to a
plausible-looking value. Serialized field names are camelCase for the UI.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

UiState = Literal[
    "draft",
    "intake",
    "plan_proposed",
    "plan_approved",
    "executing",
    "final_verification",
    "promoted",
    "attention",
    "deferred",
    "aborted",
]
Stage = Literal["plan", "execute", "audit", "memory", "checkpoint", "verify", "promote"]
StageStatus = Literal["done", "active", "paused", "attention", "pending", "skipped", "aborted"]
Tone = Literal["brand", "ok", "warn", "err", "neutral"]


class View(BaseModel):
    model_config = ConfigDict(
        frozen=True, extra="forbid", alias_generator=to_camel, populate_by_name=True
    )

    def to_json(self) -> dict:
        return self.model_dump(mode="json", by_alias=True, exclude_none=True)


class BlockCount(View):
    done: int
    total: int


class ProfileIdentity(View):
    id: str
    version: str


class AgentView(View):
    role: str
    profile: str
    fallback_condition: str | None = None


class BudgetView(View):
    usd: float | None = None
    max_attempts_per_block: int
    max_duration_seconds: int | None = None


class Fact(View):
    label: str
    value: str
    tone: Tone | None = None


# --- PLAN ---


class CriterionView(View):
    text: str
    status: Literal["unassessed"]


class PlanBlockView(View):
    id: str
    order: int
    goal: str
    scope: list[str]
    acceptance_checks: list[str]
    memory_impact: bool


class PlanApprovalView(View):
    plan_version: int
    profile_version: int
    approved_by: str
    approved_at: str


class BindingView(View):
    role: str
    primary: str
    fallbacks: list[str]
    fallback_conditions: list[str]


class PlanView(View):
    acceptance_criteria: list[CriterionView]
    plan_version: int | None = None
    architecture_summary: str | None = None
    approval: PlanApprovalView | None = None
    blocks: list[PlanBlockView] = []
    bindings: list[BindingView] = []


# --- EXECUTE ---


class BlockView(View):
    id: str
    title: str
    status: Literal["proven", "active", "pending"]
    phase: str
    attempts: int
    failed_attempts: int


class ExecutionView(View):
    current_block_id: str | None = None
    blocks: list[BlockView]
    runtime: Literal["unavailable"] = "unavailable"


# --- AUDIT ---


class TestView(View):
    __test__ = False  # not a pytest class

    suite: str
    result: Literal["passed", "failed"]


class ProvenView(View):
    value: int
    label: str
    tone: Tone | None = None


class AuditView(View):
    block_id: str
    block_title: str
    verdict: Literal["BLOCK_DONE", "NOT_YET_PROVEN", "CHECKPOINT_REJECTED"]
    executor: str | None = None
    auditor: str
    audit_status: str
    authoritative: bool
    audited_head: str
    content_sha: str
    checkpoint: str | None = None
    verification: Literal["MATCH", "MISMATCH", "PENDING"]
    tests: list[TestView]
    artifact_count: int
    proven: list[ProvenView]
    pending_note: str | None = None


# --- MEMORY (V2: per-block memory curation) ---


class MemoryCurationView(View):
    block_id: str
    block_title: str
    status: Literal["not_started", "curating", "auditing", "approved"]
    changed_paths: list[str]
    outside_paths: list[str]
    auditor: str | None = None
    audit_status: str | None = None


# --- CHECKPOINT ---


class CheckpointItemView(View):
    id: str
    sha: str | None = None
    label: str
    status: Literal["baseline", "accepted", "candidate", "rejected"]
    audited_by: str | None = None


class CheckpointView(View):
    repo: str | None = None
    items: list[CheckpointItemView]


# --- VERIFY / PROMOTE ---


class CheckView(View):
    text: str
    detail: str | None = None


class PreconditionView(View):
    text: str
    met: bool


class FutureStageView(View):
    summary: str
    checks: list[CheckView]
    preconditions: list[PreconditionView]
    facts: list[Fact] = []


# --- ATTENTION ---


class AttentionReasonView(View):
    code: str
    severity: Literal["blocking", "warning"]
    summary: str
    evidence_count: int
    suggestions: list[str]
    status: Literal["open", "resolved", "waived"]


class DecisionView(View):
    action: str
    actor: str
    at: str
    message: str | None = None


class AttentionView(View):
    code: str
    headline: str
    raised_from: UiState
    paused_at_checkpoint: str | None = None
    reasons: list[AttentionReasonView]
    decisions: list[DecisionView]
    available_decisions: list[str]


# --- History ---


class HistoryEntry(View):
    version: int
    event: str
    state: UiState


class TimestampView(View):
    label: str
    at: str
    by: str | None = None


# --- WorkOrder ---


class WorkOrderSummaryView(View):
    id: str
    title: str
    project: str
    state: UiState
    reason: str | None = None
    blocks: BlockCount | None = None
    has_detail: bool = True
    source: Literal["control"] = "control"


class UnsupportedWorkOrderView(View):
    """A stored WorkOrder the UI cannot present faithfully. Shown, never hidden."""

    id: str
    unsupported: str
    source: Literal["control"] = "control"


class WorkOrderDetailView(WorkOrderSummaryView):
    objective: str
    version: int
    risk: Literal["low", "medium", "high"] | None = None
    profile: ProfileIdentity
    budget: BudgetView | None = None
    current_stage: Stage
    stages: dict[Stage, StageStatus]
    agent: AgentView | None = None
    evidence_count: int
    plan: PlanView
    execution: ExecutionView | None = None
    audit: AuditView | None = None
    memory_curation: list[MemoryCurationView]
    checkpoints: CheckpointView
    verify: FutureStageView
    promote: FutureStageView
    attention: AttentionView | None = None
    history: list[HistoryEntry]
    timestamps: list[TimestampView]
