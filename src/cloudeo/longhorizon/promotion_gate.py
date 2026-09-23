"""Verified checkpoint and promotion gate.

Consumes the normalized AuditorVerification contract (never the auditor's
prose) and promotes a candidate only if the exact state that was audited is the
state being promoted. It closes this race:

    audit state A -> the workspace changes to B -> promotion accepts B on A's audit

Checks happen twice. evaluate_promotion_gate() compares the audited identity,
HEAD, and content hash with the candidate as it is now. Then, because
checkpoint_candidate() commits whatever the worktree holds at that instant,
checkpoint_and_promote_verified() also verifies the resulting immutable
checkpoint commit (its parent and its content hash) against the audit before
calling promote(). promote() moves accepted state to that immutable commit
through the broker's own compare-and-swap, so later worktree changes cannot
reach accepted state.

Only public broker calls are used. Everything fails closed.
"""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from cloudeo.bridge.audit import current_content_sha256, snapshot_content_sha256
from cloudeo.bridge.bundle import BridgeError
from cloudeo.bridge.models import BridgeFileEntry, BridgeLimits
from cloudeo.longhorizon.audit_result import AuditorVerification
from cloudeo.workspace.broker import (
    NothingToCheckpointError,
    StaleCandidateError,
    WorkspaceBroker,
    WorkspaceBrokerError,
)
from cloudeo.workspace.models import CandidateWorkspace, PromotionResult, WorkspaceCheckpoint

GateStatus = Literal[
    "VERIFIED_AND_CURRENT",
    # Carried over from AuditorVerification.status:
    "NOT_VERIFIED",
    "BLOCKED",
    "AUDITOR_ERROR",
    # The verification exists but cannot be tied to the state now present:
    "EVIDENCE_MISSING",
    "VERIFICATION_STALE",
    "HEAD_CHANGED",
    "WORKSPACE_CHANGED",
    "NOTHING_TO_PROMOTE",
]

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_COMMIT = re.compile(r"^[0-9a-f]{40}([0-9a-f]{24})?$")


class AuditedState(BaseModel):
    """The state the audit applies to, from the auditor's snapshot evidence."""

    model_config = ConfigDict(frozen=True)

    workspace_id: str
    candidate_id: str
    base_commit: str
    head_commit: str
    content_sha256: str


class ObservedState(BaseModel):
    """What the gate read from the candidate at check time."""

    model_config = ConfigDict(frozen=True)

    accepted_commit: str | None = None
    head_commit: str | None = None
    content_sha256: str | None = None


class PromotionGateDecision(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: GateStatus
    reason: str
    detail: str = ""
    audited: AuditedState | None = None
    observed: ObservedState | None = None

    @property
    def allowed(self) -> bool:
        return self.status == "VERIFIED_AND_CURRENT"


GateStage = Literal["refused_before_checkpoint", "refused_after_checkpoint", "promoted"]


class GatedPromotionResult(BaseModel):
    """What the gate did, and how far it got.

    refused_before_checkpoint: no checkpoint was involved.
    refused_after_checkpoint: `checkpoint` is set but was not promoted. It is
    candidate history, never accepted state, and is deliberately kept (with its
    ref) as forensic evidence; cleanup or rejection belongs to a later layer.
    promoted: `checkpoint` and `promotion` are set.
    """

    model_config = ConfigDict(frozen=True)

    decision: PromotionGateDecision
    stage: GateStage
    checkpoint: WorkspaceCheckpoint | None = None
    # True if this call created the checkpoint; False if it reused the
    # already-checkpointed audited state (or no checkpoint is involved).
    checkpoint_created: bool = False
    promotion: PromotionResult | None = None

    @property
    def promoted(self) -> bool:
        return self.promotion is not None


def evaluate_promotion_gate(
    broker: WorkspaceBroker,
    candidate: CandidateWorkspace,
    verification: AuditorVerification,
    *,
    limits: BridgeLimits | None = None,
) -> PromotionGateDecision:
    """Read-only: may this candidate be checkpointed and promoted right now?"""
    limits = limits or BridgeLimits()
    refusal = _verification_refusal(verification)
    if refusal is not None:
        return refusal
    audited = _audited_state(verification)
    if isinstance(audited, PromotionGateDecision):
        return audited

    def decide(status: GateStatus, reason: str, detail: str = "", **observed):
        return PromotionGateDecision(
            status=status,
            reason=reason,
            detail=detail,
            audited=audited,
            observed=ObservedState(**observed),
        )

    identity = (candidate.workspace_id, candidate.candidate_id, candidate.base_commit)
    if identity != (audited.workspace_id, audited.candidate_id, audited.base_commit):
        return decide(
            "VERIFICATION_STALE",
            "audit_identity_mismatch",
            f"the audit applies to {audited.workspace_id}/{audited.candidate_id} "
            f"from {audited.base_commit}, not {'/'.join(identity[:2])} from {identity[2]}",
        )
    # Current values, read now; nothing captured at audit time is trusted.
    try:
        head = broker.inspect_candidate(candidate).head_commit
        accepted = broker.accepted_state().accepted_commit
    except WorkspaceBrokerError as exc:
        return decide("BLOCKED", "candidate_unavailable", str(exc))
    if accepted != candidate.base_commit:
        return decide(
            "VERIFICATION_STALE",
            "candidate_stale",
            f"accepted state moved to {accepted}",
            accepted_commit=accepted,
            head_commit=head,
        )
    if head != audited.head_commit:
        return decide(
            "HEAD_CHANGED",
            "head_changed_since_audit",
            f"candidate HEAD is {head}; the audit inspected {audited.head_commit}",
            accepted_commit=accepted,
            head_commit=head,
        )
    try:
        content = current_content_sha256(candidate, limits)
    except BridgeError as exc:
        return decide(
            "WORKSPACE_CHANGED",
            "workspace_unreadable_as_audited",
            str(exc),
            accepted_commit=accepted,
            head_commit=head,
        )
    if content != audited.content_sha256:
        return decide(
            "WORKSPACE_CHANGED",
            "content_changed_since_audit",
            accepted_commit=accepted,
            head_commit=head,
            content_sha256=content,
        )
    return decide(
        "VERIFIED_AND_CURRENT",
        "audited_state_is_current",
        accepted_commit=accepted,
        head_commit=head,
        content_sha256=content,
    )


def checkpoint_and_promote_verified(
    broker: WorkspaceBroker,
    candidate: CandidateWorkspace,
    verification: AuditorVerification,
    *,
    message: str,
    limits: BridgeLimits | None = None,
) -> GatedPromotionResult:
    """Recheck, checkpoint, prove the checkpoint is the audited state, then promote."""
    decision = evaluate_promotion_gate(broker, candidate, verification, limits=limits)
    if not decision.allowed:
        return GatedPromotionResult(decision=decision, stage="refused_before_checkpoint")
    audited = decision.audited
    if audited is None:  # pragma: no cover - an allowed decision always has it
        raise RuntimeError("an allowed gate decision has no audited state")

    def denied(status: GateStatus, reason: str, detail: str = "", checkpoint=None, created=False):
        final = decision.model_copy(update={"status": status, "reason": reason, "detail": detail})
        return GatedPromotionResult(
            decision=final,
            stage="refused_after_checkpoint" if checkpoint else "refused_before_checkpoint",
            checkpoint=checkpoint,
            checkpoint_created=created,
        )

    created = False
    try:
        checkpoint = broker.checkpoint_candidate(candidate, message)
        created = True
    except NothingToCheckpointError as exc:
        if audited.head_commit == candidate.base_commit:
            return denied("NOTHING_TO_PROMOTE", "no_changes_since_base", str(exc))
        # The audited state is an existing checkpoint: promote exactly that commit.
        checkpoint = WorkspaceCheckpoint(
            workspace_id=candidate.workspace_id,
            candidate_id=candidate.candidate_id,
            base_commit=candidate.base_commit,
            commit=audited.head_commit,
        )
    except WorkspaceBrokerError as exc:
        return denied("BLOCKED", "checkpoint_failed", str(exc))

    # The commit is immutable: if it is exactly the audited state, promoting it
    # promotes the audited state, whatever the worktree does afterwards.
    # A checkpoint that fails from here on is returned and never deleted.
    mismatch = _checkpoint_mismatch(candidate.local_path, checkpoint.commit, audited)
    if mismatch is not None:
        return denied(
            "WORKSPACE_CHANGED", "checkpoint_differs_from_audit", mismatch, checkpoint, created
        )
    try:
        promotion = broker.promote(checkpoint)
    except StaleCandidateError as exc:
        return denied("VERIFICATION_STALE", "candidate_stale", str(exc), checkpoint, created)
    except WorkspaceBrokerError as exc:
        return denied("BLOCKED", "promotion_refused", str(exc), checkpoint, created)
    return GatedPromotionResult(
        decision=decision,
        stage="promoted",
        checkpoint=checkpoint,
        checkpoint_created=created,
        promotion=promotion,
    )


def _verification_refusal(verification: AuditorVerification) -> PromotionGateDecision | None:
    """The normalized contract, taken as-is; the report text is never read."""
    if verification.status != "VERIFIED":
        return PromotionGateDecision(status=verification.status, reason=verification.reason)
    # Defense in depth: AuditorVerification never marks these VERIFIED.
    if (
        verification.reason != "report_complete"
        or verification.format_repair == "accepted"
        or (verification.report_source or "").startswith("repair.")
    ):
        return PromotionGateDecision(
            status="NOT_VERIFIED",
            reason="repaired_report_not_verification_authority",
        )
    if verification.verifier_workspace_mutation_detected is not False:
        return PromotionGateDecision(status="BLOCKED", reason="workspace_mutation_not_excluded")
    if verification.audit_invalid_reasons:
        return PromotionGateDecision(status="BLOCKED", reason="audit_boundary_invalid")
    return None


def _audited_state(verification: AuditorVerification) -> AuditedState | PromotionGateDecision:
    metadata = verification.upstream_metadata

    def missing(detail: str) -> PromotionGateDecision:
        return PromotionGateDecision(
            status="EVIDENCE_MISSING", reason="audit_snapshot_evidence_missing", detail=detail
        )

    fields = {
        "workspace_id": metadata.get("workspace_id"),
        "candidate_id": metadata.get("candidate_id"),
        "base_commit": metadata.get("candidate_base_commit"),
        "head_commit": metadata.get("audit_snapshot_head"),
        "content_sha256": metadata.get("audit_snapshot_content_sha256"),
    }
    for key, value in fields.items():
        if not isinstance(value, str) or not value:
            return missing(f"no {key} in the audit evidence")
    for key in ("base_commit", "head_commit"):
        if not _COMMIT.match(fields[key]):
            return missing(f"{key} is not a commit ID")
    if not _SHA256.match(fields["content_sha256"]):
        return missing("content_sha256 is not a SHA-256")
    # The auditor's own after-audit checks must have been recorded as clean.
    for key in (
        "audit_snapshot_unchanged",
        "accepted_state_unchanged",
        "auditor_remote_workspace_unchanged",
    ):
        if metadata.get(key) is not True:
            return missing(f"{key} is not recorded as true")
    return AuditedState(**fields)


def _checkpoint_mismatch(root: Path, commit: str, audited: AuditedState) -> str | None:
    try:
        if commit != audited.head_commit:
            parent = _git(root, "rev-parse", "--verify", f"{commit}^1").decode().strip()
            if parent != audited.head_commit:
                return f"checkpoint {commit} is not on top of the audited HEAD"
        content = commit_content_sha256(root, commit)
    except _GitReadError as exc:
        return f"the checkpoint could not be read: {exc}"
    if content != audited.content_sha256:
        return f"checkpoint {commit} content differs from the audited snapshot"
    return None


class _GitReadError(Exception):
    pass


def _git(root: Path, *args: str, stdin: bytes | None = None) -> bytes:
    """Read-only object queries only."""
    if args[0] not in ("rev-parse", "ls-tree", "cat-file"):
        raise _GitReadError(f"git {args[0]} is not permitted in the promotion gate")
    process = subprocess.run(
        ["git", "-C", str(root), *args],
        input=stdin,
        capture_output=True,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C"},
        check=False,
    )
    if process.returncode != 0:
        raise _GitReadError(process.stderr.decode(errors="replace").strip())
    return process.stdout


def commit_content_sha256(root: Path, commit: str) -> str:
    """The content identity of a commit's tree, by the audit snapshot's rules.

    Symlinks and submodules cannot be part of an audited snapshot, so their
    presence fails.
    """
    listing = _git(root, "ls-tree", "-r", "-z", "--full-tree", commit)
    items: list[tuple[str, str, bool]] = []
    for record in listing.split(b"\0"):
        if not record:
            continue
        meta, raw_path = record.split(b"\t", 1)
        mode, kind, sha = meta.decode().split(" ")
        path = raw_path.decode("utf-8")
        if kind != "blob" or mode not in ("100644", "100755"):
            raise _GitReadError(f"{path!r} is not a regular file in the checkpoint")
        items.append((path, sha, mode == "100755"))
    blobs = _read_blobs(root, [sha for _, sha, _ in items])
    entries = tuple(
        BridgeFileEntry(
            path=path,
            size=len(blobs[sha]),
            sha256=hashlib.sha256(blobs[sha]).hexdigest(),
            executable=executable,
        )
        for path, sha, executable in sorted(items)
    )
    return snapshot_content_sha256(entries)


def _read_blobs(root: Path, shas: list[str]) -> dict[str, bytes]:
    if not shas:
        return {}
    unique = sorted(set(shas))
    output = _git(root, "cat-file", "--batch", stdin=("\n".join(unique) + "\n").encode())
    blobs: dict[str, bytes] = {}
    offset = 0
    for sha in unique:
        end = output.index(b"\n", offset)
        name, kind, size = output[offset:end].decode().split(" ")
        if name != sha or kind != "blob":
            raise _GitReadError(f"unexpected object {name} ({kind})")
        start = end + 1
        blobs[sha] = output[start : start + int(size)]
        offset = start + int(size) + 1
    return blobs
