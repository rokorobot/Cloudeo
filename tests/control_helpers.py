"""Builders for the V2 control-layer tests: profiles, plans, evidence, and a
WorkOrder driven along the happy path to any point."""

from datetime import UTC, datetime

from cloudeo.control import machine as m
from cloudeo.control.model import (
    AuditRecord,
    BlockSpec,
    Budget,
    Candidate,
    ChangeRecord,
    CheckpointProof,
    EvidenceRef,
    FallbackCondition,
    KernelOutcome,
    PlanVersion,
    ProfileRef,
    ProjectExecutionProfile,
    Role,
    RoleBinding,
    StateIdentity,
    TestRecord,
)

NOW = datetime(2026, 9, 23, 12, 0, tzinfo=UTC)
BASE = "a" * 40
MOVED = "b" * 40
MEMORY_PATHS = ("docs/architecture", "docs/components", "docs/decisions")


def ref(kind="evidence", value="ev-1"):
    return EvidenceRef(kind=kind, ref=value)


def profile_ref(name, version=1):
    return ProfileRef(profile_id=name, version=version, fingerprint=f"{name}@v{version}")


OPUS = profile_ref("opus-coder")
OPUS_FALLBACK = profile_ref("sonnet-coder")
SOL = profile_ref("sol-auditor")
CURATOR = profile_ref("memory-curator")
MEM_AUDITOR = profile_ref("memory-auditor")
FINAL = profile_ref("final-verifier")


def project_profile(version=1, executor=OPUS, fallbacks=(OPUS_FALLBACK,)):
    return ProjectExecutionProfile(
        project_id="demo",
        version=version,
        bindings=(
            RoleBinding(
                role=Role.PRIMARY_CODE_EXECUTOR,
                primary=executor,
                fallbacks=fallbacks,
                fallback_conditions=frozenset(
                    {FallbackCondition.MODEL_UNAVAILABLE, FallbackCondition.RUNTIME_UNAVAILABLE}
                )
                if fallbacks
                else frozenset(),
            ),
            RoleBinding(role=Role.CODE_AUDITOR, primary=SOL),
            RoleBinding(role=Role.MEMORY_CURATOR, primary=CURATOR),
            RoleBinding(role=Role.MEMORY_AUDITOR, primary=MEM_AUDITOR),
            RoleBinding(role=Role.FINAL_VERIFIER, primary=FINAL),
        ),
        approved_by="robert",
        approved_at=NOW,
    )


def spec(block_id="b1", order=1, memory_impact=False, scope=("src/app",)):
    return BlockSpec(
        block_id=block_id,
        order=order,
        goal=f"implement {block_id}",
        scope=scope,
        acceptance_checks=("uv run pytest -q",),
        memory_impact=memory_impact,
    )


def plan(version=1, blocks=None, attempts=2):
    return PlanVersion(
        version=version,
        architecture_summary="add the feature",
        blocks=blocks or (spec(),),
        acceptance_criteria=("feature works",),
        risk_class="low",
        budget=Budget(max_attempts_per_block=attempts),
        context_report=ref("context_report", "ctx-1"),
    )


def state(n=1):
    return StateIdentity(head_commit=BASE, content_sha256=f"{n:064x}")


def passing_checks(s, passed=True):
    return TestRecord(passed=passed, state=s, evidence=ref("tests", "t-1"))


def audit(s, role=Role.CODE_AUDITOR, auditor=SOL, status="VERIFIED", repair="not_needed"):
    return AuditRecord(
        role=role,
        auditor=auditor,
        status=status,
        reason="report_complete" if status == "VERIFIED" else "report_not_complete",
        format_repair=repair,
        audited_state=s,
        evidence=ref("audit", "a-1"),
    )


def changes(paths=("src/app/x.py",), allowed=("src/app",), deviation=None):
    return ChangeRecord(
        changed_paths=paths,
        allowed=allowed,
        evidence=ref("diff", "d-1"),
        approved_deviation=deviation,
    )


def proof_for(s, commit="c" * 40):
    return CheckpointProof(
        commit=commit,
        parent=s.head_commit,
        content_sha256=s.content_sha256,
        evidence=ref("git", commit),
    )


def outcome(promoted=True):
    return KernelOutcome(
        promotion_attempted=True,
        stage="promoted" if promoted else "refused_before_checkpoint",
        checkpoint_commit="d" * 40 if promoted else None,
        reason="audited_state_is_current" if promoted else "content_changed_since_audit",
        evidence=ref("kernel", "k-1"),
    )


def new_work_order(profile=None):
    return m.create_work_order(
        work_order_id="wo-1",
        project_id="demo",
        objective="Add the feature.",
        memory_paths=MEMORY_PATHS,
        execution_profile=profile or project_profile(),
    )


def approved(blocks=None, attempts=2):
    wo = m.start_intake(new_work_order(), accepted_baseline=BASE)
    wo = m.propose_plan(wo, plan(blocks=blocks, attempts=attempts))
    return m.approve_plan(wo, plan_version=1, approved_by="robert", approved_at=NOW)


def executing(blocks=None, attempts=2):
    wo = approved(blocks, attempts)
    wo = m.attach_candidate(
        wo,
        Candidate(workspace_id="demo", candidate_id="cand1", base_commit=BASE),
        accepted_baseline=BASE,
    )
    return m.start_execution(wo, accepted_baseline=BASE)


def code_approved(wo, block_id="b1", s=None):
    s = s or state()
    wo = m.begin_attempt(wo, block_id, profile=OPUS)
    wo = m.finish_run(wo, block_id)
    wo = m.record_tests(wo, block_id, passing_checks(s))
    scope = wo.block(block_id).spec.scope
    return m.approve_code(
        wo,
        block_id,
        audit=audit(s),
        changes=changes(paths=(f"{scope[0]}/x.py",), allowed=scope),
        current_state=s,
    )


def block_done(wo, block_id="b1", s=None):
    s = s or state()
    wo = code_approved(wo, block_id, s)
    if wo.block(block_id).spec.memory_impact:
        wo = m.begin_memory_curation(wo, block_id, profile=CURATOR)
        wo = m.finish_memory_curation(
            wo, block_id, changes(paths=("docs/components/app.md",), allowed=MEMORY_PATHS)
        )
        s = state(99)
        wo = m.approve_memory(
            wo, block_id, audit=audit(s, Role.MEMORY_AUDITOR, MEM_AUDITOR), current_state=s
        )
    else:
        wo = m.enter_block_checkpoint(wo, block_id, current_state=s)
    return m.prove_block_checkpoint(wo, block_id, proof=proof_for(s))


def final_verification(wo=None):
    wo = block_done(wo or executing())
    wo = m.enter_final_verification(wo, accepted_baseline=BASE)
    return m.record_final_audit(wo, audit(state(), Role.FINAL_VERIFIER, FINAL))
