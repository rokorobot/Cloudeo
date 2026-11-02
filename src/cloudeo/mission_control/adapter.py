"""WorkOrderViewAdapter: control-layer records -> Mission Control view models.

Pure and deterministic: the same stored WorkOrder and event history always
produce the same view model. No clocks, no I/O, no writes.

Every domain enum the UI depends on is mapped through an explicit, exhaustive
table. A value missing from a table raises UnsupportedDomainState; nothing
falls back to a default such as "pending" or "executing".
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from pydantic import BaseModel

from cloudeo.control.model import (
    AttemptRecord,
    AttentionCode,
    AttentionRequest,
    AuditRecord,
    Block,
    BlockStatus,
    EvidenceRef,
    PlanVersion,
    ProfileRef,
    Role,
    UserAction,
    WorkOrder,
    WorkOrderStatus,
)
from cloudeo.control.store import ControlEvent
from cloudeo.mission_control.views import (
    AgentView,
    AttentionReasonView,
    AttentionView,
    AuditView,
    BindingView,
    BlockCount,
    BlockView,
    BudgetView,
    CheckpointItemView,
    CheckpointView,
    CheckView,
    CriterionView,
    DecisionView,
    ExecutionView,
    Fact,
    FutureStageView,
    HistoryEntry,
    MemoryCurationView,
    PlanApprovalView,
    PlanBlockView,
    PlanView,
    PreconditionView,
    ProfileIdentity,
    ProvenView,
    Stage,
    StageStatus,
    TestView,
    TimestampView,
    UiState,
    WorkOrderDetailView,
    WorkOrderSummaryView,
)


class UnsupportedDomainState(ValueError):
    """The control store holds a state this adapter cannot present faithfully."""


def _lookup[K, V](table: Mapping[K, V], value: object, what: str) -> V:
    try:
        return table[value]  # type: ignore[index]
    except (KeyError, TypeError):
        raise UnsupportedDomainState(f"unsupported {what}: {value!r}") from None


# --- Exhaustive vocabularies (tests assert every domain member is present) ---

UI_STATE: dict[WorkOrderStatus, UiState] = {
    WorkOrderStatus.DRAFT: "draft",
    WorkOrderStatus.CONTEXT_INTAKE: "intake",
    WorkOrderStatus.PLAN_PROPOSED: "plan_proposed",
    WorkOrderStatus.PLAN_APPROVED: "plan_approved",
    WorkOrderStatus.EXECUTING: "executing",
    WorkOrderStatus.FINAL_VERIFICATION: "final_verification",
    WorkOrderStatus.PROMOTED: "promoted",
    WorkOrderStatus.USER_ATTENTION_REQUIRED: "attention",
    WorkOrderStatus.DEFERRED: "deferred",
    WorkOrderStatus.ABORTED: "aborted",
}

# The lifecycle stage a block is in. CODE_APPROVED is between stages: the audit
# is done and the block waits for memory curation or its checkpoint.
_AFTER_AUDIT = "after_audit"
BLOCK_STAGE: dict[BlockStatus, str] = {
    BlockStatus.PENDING: "execute",
    BlockStatus.RUNNING: "execute",
    BlockStatus.TESTING: "execute",
    BlockStatus.BLOCK_RESULT: "audit",
    BlockStatus.CODE_APPROVED: _AFTER_AUDIT,
    BlockStatus.MEMORY_CURATION: "memory",
    BlockStatus.MEMORY_AUDIT: "memory",
    BlockStatus.BLOCK_CHECKPOINT: "checkpoint",
    BlockStatus.BLOCK_DONE: "done",
}

BLOCK_PRESENTATION: dict[BlockStatus, str] = {
    BlockStatus.PENDING: "pending",
    BlockStatus.RUNNING: "active",
    BlockStatus.TESTING: "active",
    BlockStatus.BLOCK_RESULT: "active",
    BlockStatus.CODE_APPROVED: "active",
    BlockStatus.MEMORY_CURATION: "active",
    BlockStatus.MEMORY_AUDIT: "active",
    BlockStatus.BLOCK_CHECKPOINT: "active",
    BlockStatus.BLOCK_DONE: "proven",
}

MEMORY_STATUS: dict[BlockStatus, str] = {
    BlockStatus.PENDING: "not_started",
    BlockStatus.RUNNING: "not_started",
    BlockStatus.TESTING: "not_started",
    BlockStatus.BLOCK_RESULT: "not_started",
    BlockStatus.CODE_APPROVED: "not_started",
    BlockStatus.MEMORY_CURATION: "curating",
    BlockStatus.MEMORY_AUDIT: "auditing",
    BlockStatus.BLOCK_CHECKPOINT: "approved",
    BlockStatus.BLOCK_DONE: "approved",
}

# Attention codes the UI knows how to present. Adding a code to the domain
# without adding it here makes the adapter refuse the WorkOrder.
ATTENTION_CODES: frozenset[AttentionCode] = frozenset(
    {
        AttentionCode.BUDGET_EXHAUSTED,
        AttentionCode.ATTEMPTS_EXHAUSTED,
        AttentionCode.MATERIAL_DEVIATION,
        AttentionCode.AGENT_UNAVAILABLE,
        AttentionCode.INDEPENDENCE_UNAVAILABLE,
        AttentionCode.AUDITOR_ERROR,
        AttentionCode.AUDIT_NOT_VERIFIED,
        AttentionCode.MEMORY_CONFLICT,
        AttentionCode.BLOCK_CHECKPOINT_MISMATCH,
        AttentionCode.BASELINE_DRIFT,
        AttentionCode.PROMOTION_REFUSED,
        AttentionCode.RISK_REQUIRES_HUMAN,
        AttentionCode.PLAN_AMBIGUITY,
    }
)
USER_ACTIONS: tuple[UserAction, ...] = (
    UserAction.RESUME,
    UserAction.REPLAN,
    UserAction.CHANGE_AGENT,
    UserAction.CHANGE_BUDGET,
    UserAction.DEFER,
    UserAction.ABORT,
)

_PLANNING = frozenset(
    {
        WorkOrderStatus.DRAFT,
        WorkOrderStatus.CONTEXT_INTAKE,
        WorkOrderStatus.PLAN_PROPOSED,
        WorkOrderStatus.PLAN_APPROVED,
    }
)
_BLOCK_STAGES: tuple[Stage, ...] = ("execute", "audit", "memory", "checkpoint")
STAGES: tuple[Stage, ...] = ("plan", *_BLOCK_STAGES, "verify", "promote")


def ui_state(status: object) -> UiState:
    return _lookup(UI_STATE, status, "WorkOrder status")


# --- Small formatters ---


def _profile(ref: ProfileRef) -> str:
    return f"{ref.profile_id} v{ref.version}"


def _evidence(value: object) -> set[tuple[str, str]]:
    """Every distinct evidence reference reachable from a record."""
    found: set[tuple[str, str]] = set()

    def walk(node: object) -> None:
        if isinstance(node, EvidenceRef):
            found.add((node.kind, node.ref))
        elif isinstance(node, tuple | list | frozenset | set):
            for item in node:
                walk(item)
        elif isinstance(node, BaseModel):
            for name in type(node).model_fields:
                walk(getattr(node, name))

    walk(value)
    return found


def _plan(wo: WorkOrder) -> PlanVersion | None:
    """The approved plan, else the latest proposal, else none."""
    if wo.approvals:
        return wo.approved_plan
    return wo.plan_versions[-1] if wo.plan_versions else None


def _current_block(wo: WorkOrder) -> Block | None:
    return next((b for b in wo.blocks if b.status != BlockStatus.BLOCK_DONE), None)


def _last_attempt(block: Block | None, role: Role | None = None) -> AttemptRecord | None:
    if block is None:
        return None
    attempts = [a for a in block.attempts if role is None or a.role == role]
    return attempts[-1] if attempts else None


def _last_accepted_checkpoint(wo: WorkOrder) -> str | None:
    done = [b.checkpoint.commit for b in wo.blocks if b.checkpoint is not None]
    return done[-1] if done else None


# --- Lifecycle ---


def _progress(wo: WorkOrder, status: WorkOrderStatus) -> tuple[Stage, dict[Stage, StageStatus]]:
    """Stage statuses for a progress state (not attention/deferred/aborted)."""
    stages: dict[Stage, StageStatus] = {s: "pending" for s in STAGES}
    no_memory = not any(b.spec.memory_impact for b in wo.blocks)

    if status in _PLANNING:
        stages["plan"] = "active"
        return "plan", stages

    if status in (WorkOrderStatus.FINAL_VERIFICATION, WorkOrderStatus.PROMOTED):
        for s in ("plan", *_BLOCK_STAGES):
            stages[s] = "done"
        if no_memory:
            stages["memory"] = "skipped"
        if status == WorkOrderStatus.FINAL_VERIFICATION:
            stages["verify"] = "active"
            return "verify", stages
        stages["verify"] = stages["promote"] = "done"
        return "promote", stages

    if status == WorkOrderStatus.EXECUTING:
        stages["plan"] = "done"
        block = _current_block(wo)
        if block is None:  # every block proven; final verification not entered yet
            for s in _BLOCK_STAGES:
                stages[s] = "done"
            if no_memory:
                stages["memory"] = "skipped"
            return "checkpoint", stages
        where = _lookup(BLOCK_STAGE, block.status, "block status")
        if where == _AFTER_AUDIT:
            where = "memory" if block.spec.memory_impact else "checkpoint"
        current = _BLOCK_STAGES.index(where)  # type: ignore[arg-type]
        for i, s in enumerate(_BLOCK_STAGES):
            stages[s] = "done" if i < current else "active" if i == current else "pending"
        if not block.spec.memory_impact and stages["memory"] != "active":
            stages["memory"] = "skipped"
        return where, stages  # type: ignore[return-value]

    raise UnsupportedDomainState(f"no lifecycle progress mapping for {status!r}")


def lifecycle(wo: WorkOrder) -> tuple[Stage, dict[Stage, StageStatus]]:
    """Current stage and every stage's status, derived only from stored state."""
    status = wo.status
    if status == WorkOrderStatus.USER_ATTENTION_REQUIRED:
        request = wo.open_attention
        if request is None:
            raise UnsupportedDomainState("attention required without an open request")
        stage, stages = _progress(wo, request.raised_from)
        stages[stage] = "attention"
        return stage, stages
    if status == WorkOrderStatus.DEFERRED:
        if wo.deferred_from is None:
            raise UnsupportedDomainState("DEFERRED without deferred_from")
        stage, stages = _progress(wo, wo.deferred_from)
        stages[stage] = "paused"
        return stage, stages
    if status == WorkOrderStatus.ABORTED:
        closed = [a for a in wo.attention if a.closed]
        source = closed[-1].raised_from if closed else WorkOrderStatus.PLAN_PROPOSED
        stage, stages = _progress(wo, source)
        stages[stage] = "aborted"
        return stage, stages
    ui_state(status)  # fail closed before any progress mapping
    return _progress(wo, status)


# --- Sections ---


def _plan_view(wo: WorkOrder) -> PlanView:
    plan = _plan(wo)
    approval = wo.approvals[-1] if wo.approvals else None
    bindings = [
        BindingView(
            role=str(b.role),
            primary=_profile(b.primary),
            fallbacks=[_profile(f) for f in b.fallbacks],
            fallback_conditions=sorted(str(c) for c in b.fallback_conditions),
        )
        for b in wo.execution_profile.bindings
    ]
    if plan is None:
        return PlanView(acceptance_criteria=[], bindings=bindings)
    return PlanView(
        acceptance_criteria=[
            CriterionView(text=c, status="unassessed") for c in plan.acceptance_criteria
        ],
        plan_version=plan.version,
        architecture_summary=plan.architecture_summary,
        approval=PlanApprovalView(
            plan_version=approval.plan_version,
            profile_version=approval.execution_profile_version,
            approved_by=approval.approved_by,
            approved_at=approval.approved_at.isoformat(),
        )
        if approval
        else None,
        blocks=[
            PlanBlockView(
                id=s.block_id,
                order=s.order,
                goal=s.goal,
                scope=list(s.scope),
                acceptance_checks=list(s.acceptance_checks),
                memory_impact=s.memory_impact,
            )
            for s in plan.blocks
        ],
        bindings=bindings,
    )


def _execution_view(wo: WorkOrder) -> ExecutionView | None:
    if not wo.blocks:
        return None
    current = _current_block(wo)
    return ExecutionView(
        current_block_id=current.spec.block_id if current else None,
        blocks=[
            BlockView(
                id=b.spec.block_id,
                title=b.spec.goal,
                status=_lookup(BLOCK_PRESENTATION, b.status, "block status"),
                phase=str(b.status),
                attempts=len(b.attempts),
                failed_attempts=b.failed_attempts,
            )
            for b in wo.blocks
        ],
    )


def _audit_view(wo: WorkOrder) -> AuditView | None:
    audited = [b for b in wo.blocks if b.code_audit is not None]
    if not audited:
        return None
    block = audited[-1]
    audit: AuditRecord = block.code_audit  # type: ignore[assignment]
    done = block.status == BlockStatus.BLOCK_DONE
    rejected = bool(block.rejected_checkpoints)
    verdict = "BLOCK_DONE" if done else "CHECKPOINT_REJECTED" if rejected else "NOT_YET_PROVEN"
    verification = "MATCH" if done else "MISMATCH" if rejected else "PENDING"
    executor = _last_attempt(block, Role.PRIMARY_CODE_EXECUTOR)
    changes = block.code_changes
    proven: list[ProvenView] = []
    if block.tests is not None:
        proven.append(
            ProvenView(
                value=len(block.spec.acceptance_checks),
                label="acceptance checks recorded as passing on the audited state"
                if block.tests.passed
                else "acceptance checks recorded as failing",
                tone="ok" if block.tests.passed else "err",
            )
        )
    if changes is not None:
        proven.append(ProvenView(value=len(changes.changed_paths), label="paths changed"))
        outside = len(changes.outside)
        proven.append(
            ProvenView(
                value=outside,
                label="changed paths outside the block scope"
                + (f" (approved deviation {changes.approved_deviation})" if outside else ""),
                tone="ok" if outside == 0 else "warn",
            )
        )
    proven.append(
        ProvenView(
            value=len(block.rejected_checkpoints),
            label="rejected checkpoints kept as evidence",
            tone="ok" if not rejected else "warn",
        )
    )
    note = None
    if not done:
        note = f"Block {block.spec.block_id} is {block.status}; it is not proven until its checkpoint is."
    return AuditView(
        block_id=block.spec.block_id,
        block_title=block.spec.goal,
        verdict=verdict,
        executor=_profile(executor.profile) if executor else None,
        auditor=f"{_profile(audit.auditor)} · {audit.role}",
        audit_status=audit.status,
        authoritative=audit.authoritative,
        audited_head=audit.audited_state.head_commit,
        content_sha=audit.audited_state.content_sha256,
        checkpoint=block.checkpoint.commit if block.checkpoint else None,
        verification=verification,
        tests=[
            TestView(suite="acceptance checks", result="passed" if block.tests.passed else "failed")
        ]
        if block.tests is not None
        else [],
        artifact_count=len(_evidence(block)),
        proven=proven,
        pending_note=note,
    )


def _memory_views(wo: WorkOrder) -> list[MemoryCurationView]:
    views = []
    for b in wo.blocks:
        if not b.spec.memory_impact:
            continue
        changes, audit = b.memory_changes, b.memory_audit
        views.append(
            MemoryCurationView(
                block_id=b.spec.block_id,
                block_title=b.spec.goal,
                status=_lookup(MEMORY_STATUS, b.status, "block status"),
                changed_paths=list(changes.changed_paths) if changes else [],
                outside_paths=list(changes.outside) if changes else [],
                auditor=_profile(audit.auditor) if audit else None,
                audit_status=audit.status if audit else None,
            )
        )
    return views


def _checkpoint_view(wo: WorkOrder) -> CheckpointView:
    items: list[CheckpointItemView] = []
    if wo.planned_baseline:
        items.append(
            CheckpointItemView(
                id="C0", sha=wo.planned_baseline, label="planned baseline", status="baseline"
            )
        )
    for b in wo.blocks:
        cid = f"C{b.spec.order}"
        for proof in b.rejected_checkpoints:
            items.append(
                CheckpointItemView(id=cid, sha=proof.commit, label=b.spec.goal, status="rejected")
            )
        if b.checkpoint is not None:
            approving = b.memory_audit if b.spec.memory_impact else b.code_audit
            items.append(
                CheckpointItemView(
                    id=cid,
                    sha=b.checkpoint.commit,
                    label=b.spec.goal,
                    status="accepted",
                    audited_by=_profile(approving.auditor) if approving else None,
                )
            )
        elif b.status == BlockStatus.BLOCK_CHECKPOINT:
            items.append(CheckpointItemView(id=cid, label=b.spec.goal, status="candidate"))
    return CheckpointView(
        repo=wo.candidate.workspace_id if wo.candidate else None,
        items=items,
    )


def _verify_view(wo: WorkOrder) -> FutureStageView:
    plan = _plan(wo)
    total = len(wo.blocks)
    done = sum(b.status == BlockStatus.BLOCK_DONE for b in wo.blocks)
    binding = wo.execution_profile.binding(Role.FINAL_VERIFIER)
    facts: list[Fact] = []
    if wo.final_audit is not None:
        fa = wo.final_audit
        facts = [
            Fact(label="Final audit", value=fa.status, tone="ok" if fa.authoritative else "warn"),
            Fact(label="Verifier", value=_profile(fa.auditor)),
            Fact(label="Audited HEAD", value=fa.audited_state.head_commit),
            Fact(label="Authoritative", value="yes" if fa.authoritative else "no"),
        ]
    return FutureStageView(
        summary=(
            "final_verifier audits the frozen candidate against the acceptance criteria, "
            "read-only and independently of the executor."
        ),
        checks=[CheckView(text=c) for c in (plan.acceptance_criteria if plan else ())],
        preconditions=[
            PreconditionView(
                text=f"All {total} blocks BLOCK_DONE" if total else "Blocks approved and proven",
                met=total > 0 and done == total,
            ),
            PreconditionView(
                text=f"final_verifier bound to {_profile(binding.primary)}"
                if binding
                else "final_verifier bound in the execution profile",
                met=binding is not None,
            ),
        ],
        facts=facts,
    )


def _promote_view(wo: WorkOrder) -> FutureStageView:
    facts: list[Fact] = []
    if wo.outcome is not None:
        o = wo.outcome
        facts = [
            Fact(label="Promotion attempted", value="yes" if o.promotion_attempted else "no"),
            Fact(label="Stage", value=o.stage or "none"),
            Fact(label="Reason", value=o.reason),
        ]
        if o.checkpoint_commit:
            facts.append(Fact(label="Promoted checkpoint", value=o.checkpoint_commit, tone="ok"))
    authoritative = wo.final_audit is not None and wo.final_audit.authoritative
    return FutureStageView(
        summary="The trust kernel promotes the audited candidate only if it is still the audited state.",
        checks=[CheckView(text="Trust kernel re-checks the audited state and promotes")],
        preconditions=[
            PreconditionView(text="Original VERIFIED final audit on record", met=authoritative),
        ],
        facts=facts,
    )


def _attention_view(wo: WorkOrder) -> AttentionView | None:
    request: AttentionRequest | None = wo.open_attention
    if request is None:
        return None
    waived = {code for d in request.decisions for code in d.waived}
    reasons = []
    for r in request.reasons:
        if r.code not in ATTENTION_CODES:
            raise UnsupportedDomainState(f"unsupported attention code: {r.code!r}")
        status = (
            "waived"
            if r.code in waived
            else "resolved"
            if r.code in request.resolved_codes
            else "open"
        )
        reasons.append(
            AttentionReasonView(
                code=str(r.code),
                severity=r.severity,
                summary=r.summary,
                evidence_count=len(r.evidence),
                suggestions=list(r.suggested_solutions),
                status=status,
            )
        )
    blocking = request.open_blocking()
    lead = next((r for r in request.reasons if r.code in blocking), request.reasons[0])
    return AttentionView(
        code=str(lead.code),
        headline=lead.summary,
        raised_from=ui_state(request.raised_from),
        paused_at_checkpoint=_last_accepted_checkpoint(wo),
        reasons=reasons,
        decisions=[
            DecisionView(
                action=str(d.action), actor=d.actor, at=d.at.isoformat(), message=d.message or None
            )
            for d in request.decisions
        ],
        available_decisions=[str(a) for a in USER_ACTIONS],
    )


def _agent(wo: WorkOrder) -> AgentView | None:
    block = _current_block(wo) or (wo.blocks[-1] if wo.blocks else None)
    attempt = _last_attempt(block)
    if attempt is None:
        return None
    return AgentView(
        role=str(attempt.role),
        profile=_profile(attempt.profile),
        fallback_condition=str(attempt.fallback_condition) if attempt.fallback_condition else None,
    )


def _timestamps(wo: WorkOrder) -> list[TimestampView]:
    p = wo.execution_profile
    stamps = [
        TimestampView(
            label=f"Execution profile v{p.version} approved",
            at=p.approved_at.isoformat(),
            by=p.approved_by,
        )
    ]
    stamps += [
        TimestampView(
            label=f"Plan v{a.plan_version} approved",
            at=a.approved_at.isoformat(),
            by=a.approved_by,
        )
        for a in wo.approvals
    ]
    stamps += [
        TimestampView(
            label=f"Envelope amendment: {a.action}", at=a.approved_at.isoformat(), by=a.approved_by
        )
        for a in wo.amendments
    ]
    stamps += [
        TimestampView(label=f"Attention decision: {d.action}", at=d.at.isoformat(), by=d.actor)
        for request in wo.attention
        for d in request.decisions
    ]
    return sorted(stamps, key=lambda s: (s.at, s.label))


def _history(events: Iterable[ControlEvent]) -> list[HistoryEntry]:
    return [
        HistoryEntry(version=e.version, event=e.event, state=ui_state(_status(e.status)))
        for e in events
    ]


def _status(raw: str) -> WorkOrderStatus:
    try:
        return WorkOrderStatus(raw)
    except ValueError:
        raise UnsupportedDomainState(f"unsupported WorkOrder status in history: {raw!r}") from None


# --- Public API ---


def to_summary(wo: WorkOrder) -> WorkOrderSummaryView:
    state = ui_state(wo.status)
    attention = _attention_view(wo)
    return WorkOrderSummaryView(
        id=wo.work_order_id,
        title=wo.objective,
        project=wo.project_id,
        state=state,
        reason=attention.code if attention else None,
        blocks=BlockCount(
            done=sum(b.status == BlockStatus.BLOCK_DONE for b in wo.blocks), total=len(wo.blocks)
        )
        if wo.blocks
        else None,
    )


def to_detail(wo: WorkOrder, events: Iterable[ControlEvent] = ()) -> WorkOrderDetailView:
    summary = to_summary(wo)
    stage, stages = lifecycle(wo)
    plan = _plan(wo)
    budget = wo.budget or (plan.budget if plan else None)
    return WorkOrderDetailView(
        **summary.model_dump(),
        objective=wo.objective,
        version=wo.version,
        risk=plan.risk_class if plan else None,
        profile=ProfileIdentity(
            id=wo.execution_profile.project_id, version=f"v{wo.execution_profile.version}"
        ),
        budget=BudgetView(
            usd=budget.max_cost_usd,
            max_attempts_per_block=budget.max_attempts_per_block,
            max_duration_seconds=budget.max_duration_seconds,
        )
        if budget
        else None,
        current_stage=stage,
        stages=stages,
        agent=_agent(wo),
        evidence_count=len(_evidence(wo)),
        plan=_plan_view(wo),
        execution=_execution_view(wo),
        audit=_audit_view(wo),
        memory_curation=_memory_views(wo),
        checkpoints=_checkpoint_view(wo),
        verify=_verify_view(wo),
        promote=_promote_view(wo),
        attention=_attention_view(wo),
        history=_history(events),
        timestamps=_timestamps(wo),
    )
