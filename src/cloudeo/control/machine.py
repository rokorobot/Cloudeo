"""Pure WorkOrder and ImplementationBlock state machines (§6.1, §8.5, §10).

Each function takes a WorkOrder (plus observations and evidence the caller
obtained elsewhere) and returns a new, validated WorkOrder, or raises
TransitionRejected with an explicit code. There are no side effects: nothing
here runs an agent, touches a workspace, creates a checkpoint, or promotes.
Situations the contract routes to the user return a WorkOrder in
USER_ATTENTION_REQUIRED instead of raising.

The WorkOrder version is not changed here; the control store assigns it (CAS).
"""

from __future__ import annotations

from datetime import datetime

from cloudeo.control.model import (
    ATTENTION_SOURCES,
    TERMINAL,
    AttemptRecord,
    AttentionCode,
    AttentionReason,
    AttentionRequest,
    AuditRecord,
    Block,
    BlockStatus,
    Candidate,
    ChangeRecord,
    CheckpointProof,
    Deviation,
    EnvelopeAmendment,
    EvidenceRef,
    KernelOutcome,
    PlanApproval,
    PlanVersion,
    ProfileRef,
    ProjectExecutionProfile,
    Role,
    StateIdentity,
    TestRecord,
    UserAction,
    UserDecision,
    WorkOrder,
    WorkOrderStatus,
    code_approval_problem,
    memory_approval_problem,
)

S = WorkOrderStatus
B = BlockStatus


class TransitionRejected(Exception):
    """The requested transition is not allowed; nothing changed."""

    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code


def _require(condition: bool, code: str, message: str) -> None:
    if not condition:
        raise TransitionRejected(code, message)


def _require_status(work_order: WorkOrder, *allowed: WorkOrderStatus) -> None:
    _require(
        work_order.status in allowed,
        "illegal_state",
        f"{work_order.status} is not one of {', '.join(allowed)}",
    )


# --- WorkOrder lifecycle ---


def create_work_order(
    *,
    work_order_id: str,
    project_id: str,
    objective: str,
    memory_paths: tuple[str, ...],
    execution_profile: ProjectExecutionProfile,
) -> WorkOrder:
    """A new WorkOrder snapshots the project's currently approved profile (V2C-11)."""
    return WorkOrder(
        work_order_id=work_order_id,
        project_id=project_id,
        objective=objective,
        memory_paths=memory_paths,
        execution_profile=execution_profile,
    )


def start_intake(work_order: WorkOrder, *, accepted_baseline: str) -> WorkOrder:
    """Read-only Context Intake against the broker's current accepted commit."""
    _require_status(work_order, S.DRAFT)
    return work_order.evolve(status=S.CONTEXT_INTAKE, planned_baseline=accepted_baseline)


def propose_plan(work_order: WorkOrder, plan: PlanVersion) -> WorkOrder:
    """Every proposal, including a replan, is a new immutable version (V2C-03)."""
    _require_status(work_order, S.CONTEXT_INTAKE, S.PLAN_PROPOSED)
    _require(
        plan.version == len(work_order.plan_versions) + 1,
        "plan_version",
        f"the next plan version is {len(work_order.plan_versions) + 1}",
    )
    return work_order.evolve(
        status=S.PLAN_PROPOSED, plan_versions=(*work_order.plan_versions, plan)
    )


def approve_plan(
    work_order: WorkOrder, *, plan_version: int, approved_by: str, approved_at: datetime
) -> WorkOrder:
    """The user approves one specific, latest plan version; it becomes the envelope."""
    _require_status(work_order, S.PLAN_PROPOSED)
    _require(
        plan_version == len(work_order.plan_versions),
        "plan_version",
        "only the latest proposed plan version can be approved",
    )
    _require(
        not work_order.approvals or plan_version > work_order.approvals[-1].plan_version,
        "plan_version",
        "a plan change after approval needs a new plan version",
    )
    plan = work_order.plan_versions[plan_version - 1]
    done = {b.spec.block_id: b for b in work_order.blocks if b.status == B.BLOCK_DONE}
    for block_id, block in done.items():
        _require(
            block.spec in plan.blocks,
            "replan_changes_done_block",
            f"block {block_id} is BLOCK_DONE and must remain unchanged in the new plan",
        )
    done_specs = {b.spec for b in done.values()}
    blocks = tuple(
        done[spec.block_id] if spec in done_specs else Block(spec=spec) for spec in plan.blocks
    )
    superseded = tuple(
        b for b in work_order.blocks if b.status != B.BLOCK_DONE and (b.attempts or b.tests)
    )
    approval = PlanApproval(
        plan_version=plan_version,
        execution_profile_version=work_order.execution_profile.version,
        approved_by=approved_by,
        approved_at=approved_at,
    )
    return work_order.evolve(
        status=S.PLAN_APPROVED,
        approvals=(*work_order.approvals, approval),
        budget=work_order.budget or plan.budget,
        blocks=blocks,
        superseded_blocks=(*work_order.superseded_blocks, *superseded),
    )


def reject_plan(work_order: WorkOrder) -> WorkOrder:
    _require_status(work_order, S.PLAN_PROPOSED)
    return work_order.evolve(status=S.ABORTED)


def _drift(work_order: WorkOrder, accepted_baseline: str) -> AttentionReason | None:
    if accepted_baseline == work_order.planned_baseline:
        return None
    return AttentionReason(
        code=AttentionCode.BASELINE_DRIFT,
        summary=(
            f"accepted state is {accepted_baseline}; the plan was made against "
            f"{work_order.planned_baseline}"
        ),
        evidence=(EvidenceRef(kind="broker_accepted_state", ref=accepted_baseline),),
    )


def attach_candidate(
    work_order: WorkOrder, candidate: Candidate, *, accepted_baseline: str
) -> WorkOrder:
    """The candidate is created only after plan approval, from the planned baseline."""
    _require_status(work_order, S.PLAN_APPROVED)
    _require(work_order.candidate is None, "candidate", "the candidate is already attached")
    drift = _drift(work_order, accepted_baseline)
    if drift:
        return raise_attention(work_order, drift)
    _require(
        candidate.base_commit == work_order.planned_baseline,
        "candidate_base",
        "the candidate must start from the planned baseline",
    )
    return work_order.evolve(candidate=candidate)


def start_execution(work_order: WorkOrder, *, accepted_baseline: str) -> WorkOrder:
    _require_status(work_order, S.PLAN_APPROVED)
    _require(work_order.candidate is not None, "candidate", "no candidate is attached")
    drift = _drift(work_order, accepted_baseline)
    if drift:
        return raise_attention(work_order, drift)
    return work_order.evolve(status=S.EXECUTING)


def enter_final_verification(work_order: WorkOrder, *, accepted_baseline: str) -> WorkOrder:
    """Only when every block is BLOCK_DONE; the candidate is then frozen (V2C-20)."""
    _require_status(work_order, S.EXECUTING)
    _require(
        all(b.status == B.BLOCK_DONE for b in work_order.blocks),
        "blocks_not_done",
        "final verification requires every block BLOCK_DONE",
    )
    drift = _drift(work_order, accepted_baseline)
    if drift:
        return raise_attention(work_order, drift)
    return work_order.evolve(status=S.FINAL_VERIFICATION)


def record_final_audit(work_order: WorkOrder, audit: AuditRecord) -> WorkOrder:
    """The fresh read-only final audit; the gate, not this record, decides (§12)."""
    _require_status(work_order, S.FINAL_VERIFICATION)
    _require(audit.role == Role.FINAL_VERIFIER, "role", "the final audit is by final_verifier")
    _check_profile(work_order, audit.role, audit.auditor, None, None)
    return work_order.evolve(final_audit=audit)


def record_kernel_outcome(work_order: WorkOrder, outcome: KernelOutcome) -> WorkOrder:
    """PROMOTED only from a kernel result that promoted (V2C-04); anything else escalates."""
    _require_status(work_order, S.FINAL_VERIFICATION)
    if outcome.promoted:
        _require(
            work_order.final_audit is not None and work_order.final_audit.authoritative,
            "final_audit",
            "promotion requires an original VERIFIED final audit on record",
        )
        return work_order.evolve(
            status=S.PROMOTED, outcome=outcome, evidence=(*work_order.evidence, outcome.evidence)
        )
    reason = AttentionReason(
        code=AttentionCode.PROMOTION_REFUSED,
        summary=(
            f"trust kernel: {outcome.stage or 'not attempted'} ({outcome.reason})"
            if outcome.promotion_attempted
            else f"trust kernel: promotion not attempted ({outcome.reason})"
        ),
        evidence=(outcome.evidence,),
    )
    escalated = raise_attention(work_order, reason)
    return escalated.evolve(outcome=outcome, evidence=(*escalated.evidence, outcome.evidence))


# --- Attention and user decisions (§10) ---


def raise_attention(
    work_order: WorkOrder, *reasons: AttentionReason, attention_id: str | None = None
) -> WorkOrder:
    """Enter USER_ATTENTION_REQUIRED, or add reasons to the one open request."""
    _require(bool(reasons), "reasons", "attention needs at least one reason")
    current = work_order.open_attention
    if current is not None:
        merged = {r.code: r for r in current.reasons}
        for reason in reasons:
            if reason.code in merged:
                old = merged[reason.code]
                merged[reason.code] = old.evolve(
                    evidence=(*old.evidence, *reason.evidence),
                    suggested_solutions=(*old.suggested_solutions, *reason.suggested_solutions),
                )
            else:
                merged[reason.code] = reason
        updated = current.evolve(
            reasons=tuple(merged.values()),
            resolved_codes=tuple(
                c for c in current.resolved_codes if c not in {r.code for r in reasons}
            ),
        )
        return _replace_attention(work_order, updated)
    _require(
        work_order.status in ATTENTION_SOURCES,
        "illegal_state",
        f"attention cannot be raised from {work_order.status}",
    )
    request = AttentionRequest(
        attention_id=attention_id or f"att-{len(work_order.attention) + 1}",
        raised_from=work_order.status,
        reasons=tuple({r.code: r for r in reasons}.values()),
    )
    return work_order.evolve(
        status=S.USER_ATTENTION_REQUIRED, attention=(*work_order.attention, request)
    )


def _replace_attention(work_order: WorkOrder, request: AttentionRequest) -> WorkOrder:
    return work_order.evolve(
        attention=tuple(
            request if a.attention_id == request.attention_id else a for a in work_order.attention
        )
    )


def decide(
    work_order: WorkOrder,
    decision: UserDecision,
    *,
    amendment: EnvelopeAmendment | None = None,
    accepted_baseline: str | None = None,
) -> WorkOrder:
    """Record the user's decision on the open attention request."""
    _require_status(work_order, S.USER_ATTENTION_REQUIRED)
    request = work_order.open_attention
    assert request is not None  # guaranteed by the model while in attention
    known = {r.code for r in request.reasons}
    _require(set(decision.waived) <= known, "waiver", "only active reasons can be waived")
    request = request.evolve(decisions=(*request.decisions, decision))
    work_order = _approve_deviations(work_order, decision)
    action = decision.action

    if action in (UserAction.CHANGE_AGENT, UserAction.CHANGE_BUDGET):
        return _amend(work_order, request, decision, amendment)
    _require(amendment is None, "amendment", f"{action} does not take an envelope amendment")

    if action == UserAction.RESUME:
        blocking = request.open_blocking()
        _require(
            not blocking,
            "unresolved_reasons",
            f"resolve or explicitly waive every blocking reason first: {', '.join(blocking)}",
        )
        target = request.raised_from
        if target in (S.PLAN_APPROVED, S.EXECUTING, S.FINAL_VERIFICATION):
            _require(accepted_baseline is not None, "baseline", "resume rechecks the baseline")
            drift = _drift(work_order, accepted_baseline)
            if drift:
                return raise_attention(_replace_attention(work_order, request), drift)
        return _close(work_order, request, target)
    if action == UserAction.REPLAN:
        return _close(work_order, request, S.PLAN_PROPOSED)
    if action == UserAction.DEFER:
        return _close(work_order, request, S.DEFERRED, deferred_from=request.raised_from)
    if action == UserAction.ABORT:
        return _close(work_order, request, S.ABORTED)
    raise TransitionRejected("action", f"unknown action {action}")  # pragma: no cover


def _close(
    work_order: WorkOrder, request: AttentionRequest, target: WorkOrderStatus, **changes
) -> WorkOrder:
    """Close the request and leave attention in one atomic change."""
    closed = request.evolve(closed=True)
    return work_order.evolve(
        status=target,
        attention=tuple(
            closed if a.attention_id == closed.attention_id else a for a in work_order.attention
        ),
        **changes,
    )


def _amend(
    work_order: WorkOrder,
    request: AttentionRequest,
    decision: UserDecision,
    amendment: EnvelopeAmendment | None,
) -> WorkOrder:
    """change_agent / change_budget: an explicit, approved envelope amendment (§8.4)."""
    _require(
        amendment is not None and amendment.action == decision.action,
        "amendment",
        f"{decision.action} requires an approved envelope amendment",
    )
    _require(
        amendment.attention_id == request.attention_id,
        "amendment",
        "the amendment must answer this attention request",
    )
    changes: dict = {"amendments": (*work_order.amendments, amendment)}
    if amendment.action == UserAction.CHANGE_AGENT:
        profile = amendment.execution_profile
        _require(
            profile.project_id == work_order.project_id
            and profile.version > work_order.execution_profile.version,
            "profile_version",
            "change_agent needs a newer project-level profile version",
        )
        changes["execution_profile"] = profile
        resolved = (AttentionCode.AGENT_UNAVAILABLE, AttentionCode.INDEPENDENCE_UNAVAILABLE)
    else:
        changes["budget"] = amendment.budget
        resolved = (AttentionCode.BUDGET_EXHAUSTED, AttentionCode.ATTEMPTS_EXHAUSTED)
        # A new budget restarts the attempt counters of blocks that are not done.
        changes["blocks"] = tuple(
            b if b.status == B.BLOCK_DONE else b.evolve(failed_attempts=0, curation_attempts=0)
            for b in work_order.blocks
        )
    request = request.evolve(
        resolved_codes=tuple(
            dict.fromkeys(
                (
                    *request.resolved_codes,
                    *(c for c in resolved if c in {r.code for r in request.reasons}),
                )
            )
        )
    )
    return _replace_attention(work_order.evolve(**changes), request)


def _approve_deviations(work_order: WorkOrder, decision: UserDecision) -> WorkOrder:
    if not decision.approved_deviations:
        return work_order
    ids = {d.deviation_id for d in work_order.deviations}
    missing = set(decision.approved_deviations) - ids
    _require(not missing, "deviation", f"unknown deviations: {', '.join(sorted(missing))}")
    deviations = tuple(
        d.evolve(approved_by=decision.actor)
        if d.deviation_id in decision.approved_deviations and d.approved_by is None
        else d
        for d in work_order.deviations
    )
    return work_order.evolve(deviations=deviations)


def resume_deferred(work_order: WorkOrder, *, accepted_baseline: str) -> WorkOrder:
    """Return to the deferred state after rechecking the baseline."""
    _require_status(work_order, S.DEFERRED)
    target = work_order.deferred_from
    resumed = work_order.evolve(status=target, deferred_from=None)
    if target in (S.PLAN_APPROVED, S.EXECUTING, S.FINAL_VERIFICATION):
        drift = _drift(work_order, accepted_baseline)
        if drift:
            return raise_attention(resumed, drift)
    return resumed


def record_deviation(work_order: WorkOrder, deviation: Deviation) -> WorkOrder:
    """Every material deviation escalates (V2C-15); none is silently absorbed."""
    _require(work_order.status not in TERMINAL, "illegal_state", "the WorkOrder is finished")
    _require(
        deviation.approved_by is None,
        "deviation",
        "only the user approves deviations, through an attention decision",
    )
    recorded = work_order.evolve(deviations=(*work_order.deviations, deviation))
    if not deviation.material:
        return recorded
    return raise_attention(
        recorded,
        AttentionReason(
            code=AttentionCode.MATERIAL_DEVIATION,
            summary=deviation.summary,
            evidence=(deviation.evidence,),
        ),
    )


# --- Profiles (V2C-12, V2C-18) ---


def _check_profile(
    work_order: WorkOrder,
    role: Role,
    profile: ProfileRef,
    fallback_condition,
    evidence: EvidenceRef | None,
) -> None:
    binding = work_order.execution_profile.binding(role)
    _require(binding is not None, "role_unbound", f"{role} has no binding in the profile snapshot")
    if profile == binding.primary:
        _require(
            fallback_condition is None, "fallback", "the bound primary needs no fallback condition"
        )
        return
    _require(
        profile in binding.fallbacks,
        "profile_not_bound",
        f"{profile.profile_id} v{profile.version} is not bound to {role}",
    )
    _require(
        fallback_condition is not None
        and fallback_condition in binding.fallback_conditions
        and evidence is not None,
        "fallback_condition",
        "a fallback is used only under a defined condition, with evidence",
    )


# --- Blocks (§8.5) ---


def _update_block(work_order: WorkOrder, block: Block) -> WorkOrder:
    return work_order.evolve(
        blocks=tuple(
            block if b.spec.block_id == block.spec.block_id else b for b in work_order.blocks
        )
    )


def _block_in(work_order: WorkOrder, block_id: str, *allowed: BlockStatus) -> Block:
    _require_status(work_order, S.EXECUTING)
    try:
        block = work_order.block(block_id)
    except KeyError:
        raise TransitionRejected("unknown_block", block_id) from None
    _require(
        block.status in allowed,
        "illegal_block_state",
        f"block {block_id} is {block.status}, not one of {', '.join(allowed)}",
    )
    return block


def _attempts_left(work_order: WorkOrder, used: int) -> bool:
    return work_order.budget is not None and used < work_order.budget.max_attempts_per_block


def begin_attempt(
    work_order: WorkOrder,
    block_id: str,
    *,
    profile: ProfileRef,
    fallback_condition=None,
    evidence: EvidenceRef | None = None,
) -> WorkOrder:
    """Start a bounded run for the next block, in order, by primary_code_executor."""
    block = _block_in(work_order, block_id, B.PENDING)
    earlier = [b for b in work_order.blocks if b.spec.order < block.spec.order]
    _require(
        all(b.status == B.BLOCK_DONE for b in earlier),
        "block_order",
        "earlier blocks must be BLOCK_DONE first",
    )
    if not _attempts_left(work_order, block.failed_attempts):
        return raise_attention(
            work_order,
            AttentionReason(
                code=AttentionCode.ATTEMPTS_EXHAUSTED,
                summary=f"block {block_id} used all {block.failed_attempts} attempts",
                evidence=(EvidenceRef(kind="block", ref=block_id),),
            ),
        )
    _check_profile(work_order, Role.PRIMARY_CODE_EXECUTOR, profile, fallback_condition, evidence)
    attempt = AttemptRecord(
        role=Role.PRIMARY_CODE_EXECUTOR,
        profile=profile,
        fallback_condition=fallback_condition,
        evidence=evidence,
    )
    started = block.evolve(
        status=B.RUNNING,
        attempts=(*block.attempts, attempt),
        tests=None,
        code_audit=None,
        code_changes=None,
    )
    return _update_block(work_order, started)


def finish_run(work_order: WorkOrder, block_id: str) -> WorkOrder:
    block = _block_in(work_order, block_id, B.RUNNING)
    return _update_block(work_order, block.evolve(status=B.TESTING))


def record_tests(work_order: WorkOrder, block_id: str, tests: TestRecord) -> WorkOrder:
    block = _block_in(work_order, block_id, B.TESTING)
    return _update_block(work_order, block.evolve(status=B.BLOCK_RESULT, tests=tests))


def approve_code(
    work_order: WorkOrder,
    block_id: str,
    *,
    audit: AuditRecord,
    changes: ChangeRecord,
    current_state: StateIdentity,
) -> WorkOrder:
    """CODE_APPROVED only with every V2C-06 condition, on the exact current state."""
    block = _block_in(work_order, block_id, B.BLOCK_RESULT)
    _check_profile(work_order, audit.role, audit.auditor, None, None)
    _require(
        audit.audited_state == current_state,
        "state_changed_since_audit",
        "the audited state is no longer the current candidate state",
    )
    _require_approved_deviation(work_order, block_id, changes)
    candidate = block.evolve(code_audit=audit, code_changes=changes)
    problem = code_approval_problem(candidate)
    _require(problem is None, "code_not_approved", problem or "")
    return _update_block(work_order, candidate.evolve(status=B.CODE_APPROVED))


def _require_approved_deviation(
    work_order: WorkOrder, block_id: str, changes: ChangeRecord
) -> None:
    if changes.approved_deviation is None:
        return
    _require(
        any(
            d.deviation_id == changes.approved_deviation
            and d.block_id == block_id
            and d.approved_by is not None
            for d in work_order.deviations
        ),
        "deviation",
        "the out-of-scope change is not covered by a user-approved deviation",
    )


def fail_attempt(work_order: WorkOrder, block_id: str, evidence: EvidenceRef) -> WorkOrder:
    """A failed bounded run (tests or audit); retry within budget, else escalate."""
    block = _block_in(work_order, block_id, B.RUNNING, B.TESTING, B.BLOCK_RESULT)
    failed = block.evolve(
        status=B.PENDING,
        failed_attempts=block.failed_attempts + 1,
        tests=None,
        code_audit=None,
        code_changes=None,
    )
    updated = _update_block(work_order.evolve(evidence=(*work_order.evidence, evidence)), failed)
    if _attempts_left(updated, failed.failed_attempts):
        return updated
    return raise_attention(
        updated,
        AttentionReason(
            code=AttentionCode.ATTEMPTS_EXHAUSTED,
            summary=f"block {block_id} used all {failed.failed_attempts} attempts",
            evidence=(evidence,),
        ),
    )


def begin_memory_curation(
    work_order: WorkOrder,
    block_id: str,
    *,
    profile: ProfileRef,
    fallback_condition=None,
    evidence: EvidenceRef | None = None,
) -> WorkOrder:
    """After CODE_APPROVED only, by memory_curator only (V2C-09)."""
    block = _block_in(work_order, block_id, B.CODE_APPROVED, B.MEMORY_AUDIT)
    _require(block.spec.memory_impact, "no_memory_impact", "this block has no memory impact")
    if not _attempts_left(work_order, block.curation_attempts):
        return raise_attention(
            work_order,
            AttentionReason(
                code=AttentionCode.ATTEMPTS_EXHAUSTED,
                summary=f"memory curation for block {block_id} used all attempts",
                evidence=(EvidenceRef(kind="block", ref=block_id),),
            ),
        )
    _check_profile(work_order, Role.MEMORY_CURATOR, profile, fallback_condition, evidence)
    attempt = AttemptRecord(
        role=Role.MEMORY_CURATOR,
        profile=profile,
        fallback_condition=fallback_condition,
        evidence=evidence,
    )
    curating = block.evolve(
        status=B.MEMORY_CURATION,
        attempts=(*block.attempts, attempt),
        curation_attempts=block.curation_attempts + (1 if block.status == B.MEMORY_AUDIT else 0),
        memory_changes=None,
        memory_audit=None,
    )
    return _update_block(work_order, curating)


def finish_memory_curation(
    work_order: WorkOrder, block_id: str, changes: ChangeRecord
) -> WorkOrder:
    """The curator may change only memory_paths; anything else is a material deviation."""
    block = _block_in(work_order, block_id, B.MEMORY_CURATION)
    _require(
        changes.allowed == work_order.memory_paths,
        "memory_paths",
        "curation changes must be checked against the WorkOrder's memory_paths",
    )
    _require_approved_deviation(work_order, block_id, changes)
    audited = _update_block(work_order, block.evolve(status=B.MEMORY_AUDIT, memory_changes=changes))
    if changes.outside and changes.approved_deviation is None:
        return record_deviation(
            audited,
            Deviation(
                deviation_id=f"dev-{len(work_order.deviations) + 1}",
                block_id=block_id,
                material=True,
                summary=f"memory curation changed paths outside memory_paths: {', '.join(changes.outside)}",
                evidence=changes.evidence,
            ),
        )
    return audited


def approve_memory(
    work_order: WorkOrder, block_id: str, *, audit: AuditRecord, current_state: StateIdentity
) -> WorkOrder:
    """An independent, original VERIFIED Memory Audit of the exact current state."""
    block = _block_in(work_order, block_id, B.MEMORY_AUDIT)
    _check_profile(work_order, audit.role, audit.auditor, None, None)
    _require(
        audit.audited_state == current_state,
        "state_changed_since_audit",
        "the Memory Audit no longer covers the current candidate state",
    )
    candidate = block.evolve(memory_audit=audit)
    problem = memory_approval_problem(candidate)
    _require(problem is None, "memory_not_approved", problem or "")
    return _update_block(work_order, candidate.evolve(status=B.BLOCK_CHECKPOINT))


def enter_block_checkpoint(
    work_order: WorkOrder, block_id: str, *, current_state: StateIdentity
) -> WorkOrder:
    """No memory impact: CODE_APPROVED goes straight to the checkpoint step."""
    block = _block_in(work_order, block_id, B.CODE_APPROVED)
    _require(
        not block.spec.memory_impact,
        "memory_impact",
        "a block with memory impact needs curation and a Memory Audit first",
    )
    _require(
        block.authoritative_state == current_state,
        "state_changed_since_audit",
        "the candidate changed after the approving audit; the block does not proceed",
    )
    return _update_block(work_order, block.evolve(status=B.BLOCK_CHECKPOINT))


def prove_block_checkpoint(
    work_order: WorkOrder, block_id: str, *, proof: CheckpointProof
) -> WorkOrder:
    """The only path to BLOCK_DONE (ADR-026, V2C-19).

    The proof comes from immutable Git objects (created elsewhere). If it is
    not exactly the authoritative block state, the checkpoint is kept as
    evidence, the block is not BLOCK_DONE, and the WorkOrder escalates.
    """
    block = _block_in(work_order, block_id, B.BLOCK_CHECKPOINT)
    if proof.proves(block.authoritative_state):
        return _update_block(work_order, block.evolve(status=B.BLOCK_DONE, checkpoint=proof))
    kept = _update_block(
        work_order, block.evolve(rejected_checkpoints=(*block.rejected_checkpoints, proof))
    )
    return raise_attention(
        kept,
        AttentionReason(
            code=AttentionCode.BLOCK_CHECKPOINT_MISMATCH,
            summary=(
                f"checkpoint {proof.commit} for block {block_id} is not the audited block state"
            ),
            evidence=(proof.evidence,),
        ),
    )
