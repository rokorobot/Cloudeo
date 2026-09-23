"""V2 control-layer domain model (13_V2_CONTROL_ARCHITECTURE.md; ADR-022 to ADR-029).

Pure data. Every record is frozen, and the invariants that must hold for any
stored WorkOrder or block are model validators, so they are enforced on every
construction and on every reload, not only by the transition functions in
machine.py. Evolution rules between two versions of a WorkOrder (append-only
history, immutable snapshots, legal transitions) are in check_evolution().

No execution, no Git, no Workspace Broker: this module never touches a
workspace or accepted state (K1).
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer, model_validator

from cloudeo.workspace.models import CommitSha, Identifier

Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Text = Annotated[str, Field(min_length=1)]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    def evolve(self, **changes):
        """A validated copy; model_copy(update=...) would skip the validators."""
        return type(self).model_validate({**dict(self), **changes})

    def canonical_sha256(self) -> str:
        data = json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(data.encode()).hexdigest()


# --- Vocabulary ---


class WorkOrderStatus(StrEnum):
    DRAFT = "DRAFT"
    CONTEXT_INTAKE = "CONTEXT_INTAKE"
    PLAN_PROPOSED = "PLAN_PROPOSED"
    PLAN_APPROVED = "PLAN_APPROVED"
    EXECUTING = "EXECUTING"
    FINAL_VERIFICATION = "FINAL_VERIFICATION"
    PROMOTED = "PROMOTED"
    USER_ATTENTION_REQUIRED = "USER_ATTENTION_REQUIRED"
    DEFERRED = "DEFERRED"
    ABORTED = "ABORTED"


TERMINAL = frozenset({WorkOrderStatus.PROMOTED, WorkOrderStatus.ABORTED})
# States from which the contract allows USER_ATTENTION_REQUIRED (§6.1).
ATTENTION_SOURCES = frozenset(
    {
        WorkOrderStatus.CONTEXT_INTAKE,
        WorkOrderStatus.PLAN_APPROVED,
        WorkOrderStatus.EXECUTING,
        WorkOrderStatus.FINAL_VERIFICATION,
    }
)
# Legal WorkOrder status changes (§6.1). check_evolution() enforces this table.
WORK_ORDER_TRANSITIONS: dict[WorkOrderStatus, frozenset[WorkOrderStatus]] = {
    WorkOrderStatus.DRAFT: frozenset({WorkOrderStatus.CONTEXT_INTAKE}),
    WorkOrderStatus.CONTEXT_INTAKE: frozenset(
        {WorkOrderStatus.PLAN_PROPOSED, WorkOrderStatus.USER_ATTENTION_REQUIRED}
    ),
    WorkOrderStatus.PLAN_PROPOSED: frozenset(
        {WorkOrderStatus.PLAN_APPROVED, WorkOrderStatus.ABORTED}
    ),
    WorkOrderStatus.PLAN_APPROVED: frozenset(
        {WorkOrderStatus.EXECUTING, WorkOrderStatus.USER_ATTENTION_REQUIRED}
    ),
    WorkOrderStatus.EXECUTING: frozenset(
        {WorkOrderStatus.FINAL_VERIFICATION, WorkOrderStatus.USER_ATTENTION_REQUIRED}
    ),
    WorkOrderStatus.FINAL_VERIFICATION: frozenset(
        {WorkOrderStatus.PROMOTED, WorkOrderStatus.USER_ATTENTION_REQUIRED}
    ),
    WorkOrderStatus.USER_ATTENTION_REQUIRED: frozenset(
        {
            *ATTENTION_SOURCES,
            WorkOrderStatus.PLAN_PROPOSED,
            WorkOrderStatus.DEFERRED,
            WorkOrderStatus.ABORTED,
        }
    ),
    WorkOrderStatus.DEFERRED: frozenset(
        {*ATTENTION_SOURCES, WorkOrderStatus.USER_ATTENTION_REQUIRED}
    ),
    WorkOrderStatus.PROMOTED: frozenset(),
    WorkOrderStatus.ABORTED: frozenset(),
}


class BlockStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    TESTING = "TESTING"
    BLOCK_RESULT = "BLOCK_RESULT"
    CODE_APPROVED = "CODE_APPROVED"
    MEMORY_CURATION = "MEMORY_CURATION"
    MEMORY_AUDIT = "MEMORY_AUDIT"
    BLOCK_CHECKPOINT = "BLOCK_CHECKPOINT"
    BLOCK_DONE = "BLOCK_DONE"


# Statuses at or after CODE_APPROVED: the code approval must stay provable.
CODE_APPROVED_OR_LATER = frozenset(
    {
        BlockStatus.CODE_APPROVED,
        BlockStatus.MEMORY_CURATION,
        BlockStatus.MEMORY_AUDIT,
        BlockStatus.BLOCK_CHECKPOINT,
        BlockStatus.BLOCK_DONE,
    }
)


class Role(StrEnum):
    CONTEXT_ANALYST = "context_analyst"
    ARCHITECTURE_PLANNER = "architecture_planner"
    IMPLEMENTATION_PLANNER = "implementation_planner"
    RECOVERY_PLANNER = "recovery_planner"
    EPISODE_MANAGER = "episode_manager"
    PRIMARY_CODE_EXECUTOR = "primary_code_executor"
    CODE_AUDITOR = "code_auditor"
    FORMAT_REPAIR = "format_repair"
    MEMORY_CURATOR = "memory_curator"
    MEMORY_AUDITOR = "memory_auditor"
    FINAL_VERIFIER = "final_verifier"
    USER_REPORTER = "user_reporter"


WRITE_CAPABLE_ROLES = frozenset({Role.PRIMARY_CODE_EXECUTOR, Role.MEMORY_CURATOR})


class FallbackCondition(StrEnum):
    """The only conditions under which a fallback profile may be used (§8.4)."""

    RUNTIME_UNAVAILABLE = "runtime_unavailable"
    MODEL_UNAVAILABLE = "model_unavailable"
    PROVIDER_FAILURE_PERSISTENT = "provider_failure_persistent"
    POLICY_FORBIDS_PRIMARY = "policy_forbids_primary"


class AttentionCode(StrEnum):
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
    ATTEMPTS_EXHAUSTED = "ATTEMPTS_EXHAUSTED"
    MATERIAL_DEVIATION = "MATERIAL_DEVIATION"
    AGENT_UNAVAILABLE = "AGENT_UNAVAILABLE"
    INDEPENDENCE_UNAVAILABLE = "INDEPENDENCE_UNAVAILABLE"
    AUDITOR_ERROR = "AUDITOR_ERROR"
    AUDIT_NOT_VERIFIED = "AUDIT_NOT_VERIFIED"
    MEMORY_CONFLICT = "MEMORY_CONFLICT"
    BLOCK_CHECKPOINT_MISMATCH = "BLOCK_CHECKPOINT_MISMATCH"
    BASELINE_DRIFT = "BASELINE_DRIFT"
    PROMOTION_REFUSED = "PROMOTION_REFUSED"
    RISK_REQUIRES_HUMAN = "RISK_REQUIRES_HUMAN"
    PLAN_AMBIGUITY = "PLAN_AMBIGUITY"


class UserAction(StrEnum):
    RESUME = "resume"
    REPLAN = "replan"
    CHANGE_AGENT = "change_agent"
    CHANGE_BUDGET = "change_budget"
    DEFER = "defer"
    ABORT = "abort"


# --- Profiles (§8.3, §8.4) ---


class ProfileRef(_Frozen):
    """An exact, immutable ExecutionProfile version (V2C-18)."""

    profile_id: Identifier
    version: int = Field(ge=1)
    fingerprint: Text


class RoleBinding(_Frozen):
    role: Role
    primary: ProfileRef
    fallbacks: tuple[ProfileRef, ...] = ()
    fallback_conditions: frozenset[FallbackCondition] = frozenset()

    @field_serializer("fallback_conditions")
    def _sorted_conditions(self, conditions: frozenset[FallbackCondition]) -> list[str]:
        # Set iteration order depends on the process hash seed; serialized
        # records and their canonical hashes must not (V2C-18, store checks).
        return sorted(str(condition) for condition in conditions)

    @model_validator(mode="after")
    def _distinct(self):
        if self.primary in self.fallbacks or len(set(self.fallbacks)) != len(self.fallbacks):
            raise ValueError("fallbacks must be distinct from each other and from the primary")
        if self.fallbacks and not self.fallback_conditions:
            raise ValueError("fallbacks need at least one defined fallback condition")
        return self


class ProjectExecutionProfile(_Frozen):
    """Project-level role bindings, approved at onboarding; immutable per version."""

    project_id: Identifier
    version: int = Field(ge=1)
    bindings: tuple[RoleBinding, ...]
    approved_by: Text
    approved_at: datetime

    @model_validator(mode="after")
    def _one_binding_per_role(self):
        roles = [binding.role for binding in self.bindings]
        if len(roles) != len(set(roles)):
            raise ValueError("each role has exactly one binding")
        return self

    def binding(self, role: Role) -> RoleBinding | None:
        return next((b for b in self.bindings if b.role == role), None)


# --- Evidence ---


class EvidenceRef(_Frozen):
    """A reference to evidence stored elsewhere; never prose as proof."""

    kind: Text
    ref: Text


class StateIdentity(_Frozen):
    """An exact candidate state: HEAD plus content hash (audit snapshot rules)."""

    head_commit: CommitSha
    content_sha256: Sha256


class AuditRecord(_Frozen):
    """A normalized audit result (AuditorVerification) and the state it covers."""

    role: Role
    auditor: ProfileRef
    status: Literal["VERIFIED", "NOT_VERIFIED", "BLOCKED", "AUDITOR_ERROR"]
    reason: Text
    format_repair: Literal["not_needed", "not_provided", "accepted", "rejected"]
    audited_state: StateIdentity
    evidence: EvidenceRef

    @property
    def authoritative(self) -> bool:
        """Original VERIFIED only: a repaired report is never authority (V2C-07)."""
        return (
            self.status == "VERIFIED"
            and self.reason == "report_complete"
            and self.format_repair != "accepted"
        )


class TestRecord(_Frozen):
    """Deterministic acceptance checks on one exact candidate state."""

    __test__ = False  # not a pytest class

    passed: bool
    state: StateIdentity
    evidence: EvidenceRef


def _within(path: str, prefixes: tuple[str, ...]) -> bool:
    return any(path == p.rstrip("/") or path.startswith(p.rstrip("/") + "/") for p in prefixes)


class ChangeRecord(_Frozen):
    """Paths changed by one write-capable step, from a deterministic diff."""

    changed_paths: tuple[str, ...]
    allowed: tuple[str, ...]
    evidence: EvidenceRef
    # A user-approved deviation that covers out-of-scope paths (§9).
    approved_deviation: str | None = None

    @property
    def outside(self) -> tuple[str, ...]:
        return tuple(p for p in self.changed_paths if not _within(p, self.allowed))


class CheckpointProof(_Frozen):
    """What immutable Git objects say about a checkpoint commit (§8.5)."""

    commit: CommitSha
    parent: CommitSha | None
    content_sha256: Sha256
    evidence: EvidenceRef

    def proves(self, state: StateIdentity) -> bool:
        on_top = self.commit == state.head_commit or self.parent == state.head_commit
        return on_top and self.content_sha256 == state.content_sha256


class AttemptRecord(_Frozen):
    """One use of a profile for a role; fallbacks record their condition (V2C-12)."""

    role: Role
    profile: ProfileRef
    fallback_condition: FallbackCondition | None = None
    evidence: EvidenceRef | None = None


class KernelOutcome(_Frozen):
    """The structured final result of the trust kernel (ADR-020/021)."""

    promotion_attempted: bool
    stage: Literal["refused_before_checkpoint", "refused_after_checkpoint", "promoted"] | None
    checkpoint_commit: CommitSha | None = None
    reason: Text
    evidence: EvidenceRef

    @property
    def promoted(self) -> bool:
        return (
            self.promotion_attempted
            and self.stage == "promoted"
            and self.checkpoint_commit is not None
        )


# --- Plan and envelope (§8.1, §9) ---


class Budget(_Frozen):
    max_attempts_per_block: int = Field(ge=1)
    max_cost_usd: float | None = Field(default=None, ge=0)
    max_duration_seconds: int | None = Field(default=None, ge=1)


class BlockSpec(_Frozen):
    block_id: Identifier
    order: int = Field(ge=1)
    goal: Text
    scope: tuple[Text, ...] = Field(min_length=1)
    acceptance_checks: tuple[Text, ...] = Field(min_length=1)
    memory_impact: bool = False


class PlanVersion(_Frozen):
    """An immutable plan proposal (§8.1)."""

    version: int = Field(ge=1)
    architecture_summary: Text
    blocks: tuple[BlockSpec, ...] = Field(min_length=1)
    acceptance_criteria: tuple[Text, ...] = Field(min_length=1)
    risk_class: Literal["low", "medium", "high"]
    budget: Budget
    context_report: EvidenceRef

    @model_validator(mode="after")
    def _ordered_unique_blocks(self):
        ids = [b.block_id for b in self.blocks]
        orders = [b.order for b in self.blocks]
        if len(set(ids)) != len(ids) or orders != list(range(1, len(orders) + 1)):
            raise ValueError("blocks need unique ids and consecutive order 1..n")
        return self


class PlanApproval(_Frozen):
    plan_version: int = Field(ge=1)
    execution_profile_version: int = Field(ge=1)
    approved_by: Text
    approved_at: datetime


class EnvelopeAmendment(_Frozen):
    """A user-approved change to an active WorkOrder's envelope (§8.4, §10)."""

    attention_id: Identifier
    action: Literal[UserAction.CHANGE_AGENT, UserAction.CHANGE_BUDGET]
    execution_profile: ProjectExecutionProfile | None = None
    budget: Budget | None = None
    approved_by: Text
    approved_at: datetime

    @model_validator(mode="after")
    def _matches_action(self):
        if self.action == UserAction.CHANGE_AGENT and (
            self.execution_profile is None or self.budget is not None
        ):
            raise ValueError("change_agent amends exactly the execution profile")
        if self.action == UserAction.CHANGE_BUDGET and (
            self.budget is None or self.execution_profile is not None
        ):
            raise ValueError("change_budget amends exactly the budget")
        return self


class Candidate(_Frozen):
    workspace_id: Identifier
    candidate_id: Identifier
    base_commit: CommitSha


# --- Human decisions (§10) ---


class AttentionReason(_Frozen):
    code: AttentionCode
    severity: Literal["blocking", "warning"] = "blocking"
    summary: Text
    evidence: tuple[EvidenceRef, ...] = Field(min_length=1)
    suggested_solutions: tuple[Text, ...] = ()


class UserDecision(_Frozen):
    action: UserAction
    actor: Text
    at: datetime
    message: str = ""
    waived: tuple[AttentionCode, ...] = ()
    approved_deviations: tuple[Identifier, ...] = ()


class AttentionRequest(_Frozen):
    attention_id: Identifier
    raised_from: WorkOrderStatus
    reasons: tuple[AttentionReason, ...] = Field(min_length=1)
    resolved_codes: tuple[AttentionCode, ...] = ()
    decisions: tuple[UserDecision, ...] = ()
    closed: bool = False

    @model_validator(mode="after")
    def _consistent(self):
        if self.raised_from not in ATTENTION_SOURCES:
            raise ValueError(f"attention cannot be raised from {self.raised_from}")
        codes = [r.code for r in self.reasons]
        if len(set(codes)) != len(codes):
            raise ValueError("one reason per code; later evidence extends the same reason")
        return self

    def open_blocking(self) -> tuple[AttentionCode, ...]:
        waived = {code for d in self.decisions for code in d.waived}
        return tuple(
            r.code
            for r in self.reasons
            if r.severity == "blocking"
            and r.code not in self.resolved_codes
            and r.code not in waived
        )


class Deviation(_Frozen):
    deviation_id: Identifier
    block_id: Identifier | None
    material: bool
    summary: Text
    evidence: EvidenceRef
    approved_by: str | None = None


# --- Blocks (§8.5) ---


class Block(_Frozen):
    spec: BlockSpec
    status: BlockStatus = BlockStatus.PENDING
    attempts: tuple[AttemptRecord, ...] = ()
    failed_attempts: int = 0
    tests: TestRecord | None = None
    code_audit: AuditRecord | None = None
    code_changes: ChangeRecord | None = None
    curation_attempts: int = 0
    memory_changes: ChangeRecord | None = None
    memory_audit: AuditRecord | None = None
    checkpoint: CheckpointProof | None = None
    # Checkpoints that failed the proof: kept as evidence, never BLOCK_DONE.
    rejected_checkpoints: tuple[CheckpointProof, ...] = ()

    @model_validator(mode="after")
    def _status_requirements(self):
        if self.status in CODE_APPROVED_OR_LATER:
            problem = code_approval_problem(self)
            if problem:
                raise ValueError(f"{self.status} without a valid code approval: {problem}")
        memory_states = {BlockStatus.MEMORY_CURATION, BlockStatus.MEMORY_AUDIT}
        if self.status in memory_states and not self.spec.memory_impact:
            raise ValueError("memory curation only for blocks with memory impact")
        if self.status in {BlockStatus.BLOCK_CHECKPOINT, BlockStatus.BLOCK_DONE}:
            problem = memory_approval_problem(self)
            if problem:
                raise ValueError(f"{self.status} without a valid memory approval: {problem}")
        # BLOCK_DONE exists only with a checkpoint proven to be the authoritative
        # block state (ADR-026, V2C-19); there is no other way to construct it.
        if self.status == BlockStatus.BLOCK_DONE:
            if self.checkpoint is None or not self.checkpoint.proves(self.authoritative_state):
                raise ValueError("BLOCK_DONE requires a checkpoint proven to be the audited state")
        elif self.checkpoint is not None:
            raise ValueError("only a BLOCK_DONE block has a block checkpoint")
        return self

    @property
    def authoritative_state(self) -> StateIdentity:
        """The last approving audit's state: Memory Audit if memory changed (§8.5)."""
        audit = self.memory_audit if self.spec.memory_impact else self.code_audit
        if audit is None:
            raise ValueError("the block has no approving audit yet")
        return audit.audited_state


def code_approval_problem(block: Block) -> str | None:
    """Why CODE_APPROVED cannot hold (V2C-06, V2C-07), or None."""
    audit, tests, changes = block.code_audit, block.tests, block.code_changes
    if audit is None or tests is None or changes is None:
        return "tests, code audit, and change record are all required"
    if audit.role != Role.CODE_AUDITOR:
        return "the code audit must come from code_auditor"
    if not audit.authoritative:
        return "the code audit is not an original VERIFIED result"
    if not tests.passed:
        return "deterministic acceptance checks did not pass"
    if tests.state != audit.audited_state:
        return "tests and audit cover different candidate states"
    if changes.allowed != block.spec.scope:
        return "the change record is not checked against the block scope"
    if changes.outside and changes.approved_deviation is None:
        return f"changes outside the block scope: {', '.join(changes.outside)}"
    return None


def memory_approval_problem(block: Block) -> str | None:
    """Why a block with memory impact cannot leave memory curation (V2C-09), or None."""
    if not block.spec.memory_impact:
        return (
            None
            if block.memory_audit is None and block.memory_changes is None
            else ("a block without memory impact has no memory records")
        )
    audit, changes = block.memory_audit, block.memory_changes
    if audit is None or changes is None:
        return "memory changes and a Memory Audit are required"
    if audit.role != Role.MEMORY_AUDITOR:
        return "the Memory Audit must come from memory_auditor"
    if not audit.authoritative:
        return "the Memory Audit is not an original VERIFIED result"
    if changes.outside and changes.approved_deviation is None:
        return f"memory curation changed paths outside memory_paths: {', '.join(changes.outside)}"
    return None


# --- WorkOrder (§6) ---


class WorkOrder(_Frozen):
    work_order_id: Identifier
    version: int = Field(default=0, ge=0)  # set by the store (CAS, §14.1)
    project_id: Identifier
    objective: Text
    memory_paths: tuple[Text, ...] = Field(min_length=1)
    execution_profile: ProjectExecutionProfile  # the immutable snapshot (V2C-11)
    status: WorkOrderStatus = WorkOrderStatus.DRAFT
    planned_baseline: CommitSha | None = None
    candidate: Candidate | None = None
    plan_versions: tuple[PlanVersion, ...] = ()
    approvals: tuple[PlanApproval, ...] = ()
    budget: Budget | None = None
    amendments: tuple[EnvelopeAmendment, ...] = ()
    blocks: tuple[Block, ...] = ()
    # Blocks replaced by a replan before they were done: kept as evidence (V2C-21).
    superseded_blocks: tuple[Block, ...] = ()
    attention: tuple[AttentionRequest, ...] = ()
    deferred_from: WorkOrderStatus | None = None
    deviations: tuple[Deviation, ...] = ()
    final_audit: AuditRecord | None = None
    outcome: KernelOutcome | None = None
    evidence: tuple[EvidenceRef, ...] = ()

    @model_validator(mode="after")
    def _invariants(self):
        if self.execution_profile.project_id != self.project_id:
            raise ValueError("the execution profile belongs to another project")
        versions = [p.version for p in self.plan_versions]
        if versions != list(range(1, len(versions) + 1)):
            raise ValueError("plan versions are consecutive from 1")
        for approval in self.approvals:
            if approval.plan_version > len(self.plan_versions):
                raise ValueError("an approval refers to a plan version that does not exist")
        approved = [a.plan_version for a in self.approvals]
        if approved != sorted(set(approved)):
            raise ValueError("each approval is of a newer plan version")
        # V2C-02: nothing that implies a workspace write before an approved plan.
        if (self.candidate or self.blocks) and not self.approvals:
            raise ValueError("no candidate or blocks before an approved plan")
        if self.blocks and tuple(b.spec for b in self.blocks) != self.approved_plan.blocks:
            raise ValueError("blocks must match the approved plan")
        running = {WorkOrderStatus.EXECUTING, WorkOrderStatus.FINAL_VERIFICATION}
        if self.status in running and (self.candidate is None or not self.blocks):
            raise ValueError(f"{self.status} requires a candidate and approved blocks")
        # V2C-05: only fully proven blocks may reach final verification.
        finishing = {WorkOrderStatus.FINAL_VERIFICATION, WorkOrderStatus.PROMOTED}
        if self.status in finishing and any(
            b.status != BlockStatus.BLOCK_DONE for b in self.blocks
        ):
            raise ValueError("final verification requires every block BLOCK_DONE")
        # V2C-04: PROMOTED only from a kernel result that promoted.
        if self.status == WorkOrderStatus.PROMOTED and not (self.outcome and self.outcome.promoted):
            raise ValueError("PROMOTED requires a kernel outcome with promoted == true")
        promoted = self.outcome is not None and self.outcome.promoted
        if promoted and self.status != WorkOrderStatus.PROMOTED:
            raise ValueError("a promoted kernel outcome means the WorkOrder is PROMOTED")
        ids = [d.deviation_id for d in self.deviations]
        if len(set(ids)) != len(ids):
            raise ValueError("deviation ids are unique")
        open_requests = [a for a in self.attention if not a.closed]
        in_attention = self.status == WorkOrderStatus.USER_ATTENTION_REQUIRED
        if len(open_requests) != (1 if in_attention else 0):
            raise ValueError("exactly one open attention request while attention is required")
        if (self.status == WorkOrderStatus.DEFERRED) != (self.deferred_from is not None):
            raise ValueError("deferred_from is set exactly while DEFERRED")
        return self

    @property
    def approved_plan(self) -> PlanVersion:
        if not self.approvals:
            raise ValueError("no approved plan")
        return self.plan_versions[self.approvals[-1].plan_version - 1]

    @property
    def open_attention(self) -> AttentionRequest | None:
        return next((a for a in self.attention if not a.closed), None)

    def block(self, block_id: str) -> Block:
        for block in self.blocks:
            if block.spec.block_id == block_id:
                return block
        raise KeyError(block_id)


class EvolutionError(ValueError):
    """A new WorkOrder version is not a legal successor of the stored one."""


def check_evolution(old: WorkOrder, new: WorkOrder) -> None:
    """Rules between consecutive versions, enforced by the store on every write."""
    if new.work_order_id != old.work_order_id or new.project_id != old.project_id:
        raise EvolutionError("identity is immutable")
    if old.status in TERMINAL and new != old.evolve(version=new.version):
        raise EvolutionError(f"a {old.status} WorkOrder is immutable")
    if new.status != old.status and new.status not in WORK_ORDER_TRANSITIONS[old.status]:
        raise EvolutionError(f"illegal transition {old.status} -> {new.status}")
    for name in ("objective", "memory_paths"):
        if getattr(new, name) != getattr(old, name):
            raise EvolutionError(f"{name} is immutable")
    # V2C-22: the planned baseline is never rebased. (The contract defines no
    # re-intake transition; drift is resolved by the user, see ADR-026.)
    if old.planned_baseline is not None and new.planned_baseline != old.planned_baseline:
        raise EvolutionError("the planned baseline is immutable once intake started")
    if old.candidate is not None and new.candidate != old.candidate:
        raise EvolutionError("the candidate is immutable once attached")
    for name in (
        "plan_versions",
        "approvals",
        "amendments",
        "deviations",
        "evidence",
        "superseded_blocks",
    ):
        _append_only(
            name, getattr(old, name), getattr(new, name), allow_update=name == "deviations"
        )
    # V2C-11: the profile snapshot changes only through an approved amendment.
    if new.execution_profile != old.execution_profile:
        added = new.amendments[len(old.amendments) :]
        if not any(a.execution_profile == new.execution_profile for a in added):
            raise EvolutionError("the execution profile snapshot changes only by an amendment")
    if new.budget != old.budget and old.budget is not None:
        added = new.amendments[len(old.amendments) :]
        if not any(a.budget == new.budget for a in added):
            raise EvolutionError("the budget changes only by an approved amendment")
    old_attention = {a.attention_id: a for a in old.attention}
    for request in new.attention:
        before = old_attention.get(request.attention_id)
        if before is not None and before.closed and request != before:
            raise EvolutionError("a closed attention request is immutable")
    if [a.attention_id for a in new.attention][: len(old.attention)] != list(old_attention):
        raise EvolutionError("attention history is append-only")
    new_blocks = {b.spec.block_id: b for b in new.blocks}
    for before in old.blocks:
        if (
            before.status == BlockStatus.BLOCK_DONE
            and new_blocks.get(before.spec.block_id) != before
        ):
            raise EvolutionError("a BLOCK_DONE block is immutable and cannot be removed")


def _append_only(name: str, old: tuple, new: tuple, *, allow_update: bool = False) -> None:
    if len(new) < len(old):
        raise EvolutionError(f"{name} is append-only")
    for before, after in zip(old, new, strict=False):
        if before == after:
            continue
        # Deviations may only gain an approval.
        if (
            allow_update
            and before.approved_by is None
            and after == before.evolve(approved_by=after.approved_by)
        ):
            continue
        raise EvolutionError(f"{name} entries are immutable")
