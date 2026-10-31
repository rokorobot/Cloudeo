"""Failed ExecutionOutcome -> control attention input (ADR-035; V2C-12, V2C-17 producers).

A pure, deterministic mapping from a normalized execution failure to what the
control layer can evaluate. Orchestration interprets the evidence; control
decides. In particular:

- This module never selects or authorizes a fallback. A FallbackCondition is
  usable only through the public state machine (`begin_attempt`), which checks
  it against the approved binding. Here a condition is only reported as the
  one an error class could support once its establishing evidence exists
  (`condition_if_established`); a single execution failure never establishes
  one, and `provider_failure_persistent` is never produced.
- Every assessed failure therefore routes to attention: `AUDITOR_ERROR` for an
  auditing role, `AGENT_UNAVAILABLE` for any other role (13 §10, V2C-17).
- A failure whose final runtime state was not observed is never marked safe
  for a second execution.

Anything this module does not recognize raises UnmappableExecutionOutcome
instead of being guessed at.
"""

from __future__ import annotations

import hashlib
import json

from pydantic import BaseModel, ConfigDict

from cloudeo.control import machine
from cloudeo.control.model import (
    AUDITED_PRODUCERS,
    AttentionCode,
    AttentionReason,
    EvidenceRef,
    FallbackCondition,
    ProfileRef,
    Role,
    WorkOrder,
)
from cloudeo.execution.contracts import (
    ErrorClass,
    ExecutionError,
    ExecutionOutcome,
    ExecutionStatus,
    RuntimeIdentity,
)

EVIDENCE_KIND = "execution_failure"
# Digest framing as in kernel_outcome: SHA-256 over the tag, one NUL byte, then
# canonical JSON. A new serialization or meaning needs a new tag.
DIGEST_TAG = b"execution-failure:v1"
DIGEST_SEPARATOR = b"\x00"

FAILURE_STATUSES: frozenset[ExecutionStatus] = frozenset(
    {"failed", "cancelled", "incomplete", "unknown"}
)
# The runtime reported a final state in which the task is not running. Any
# other failure status leaves a second execution unsafe (it may duplicate or
# race the first).
TERMINAL_OBSERVED: frozenset[ExecutionStatus] = frozenset({"failed", "cancelled"})

# 13 §8.4: the condition an error class could support, and what must
# establish it. Neither is established by one execution failure.
ESTABLISHED_BY_DISCOVERY = "UHP discovery or health evidence"
ESTABLISHED_BY_PERSISTENCE = (
    "persistence after the primary's allowed retries (not defined in control)"
)
CONDITION_IF_ESTABLISHED: dict[str, tuple[FallbackCondition, str] | None] = {
    "runtime_unavailable": (FallbackCondition.RUNTIME_UNAVAILABLE, ESTABLISHED_BY_DISCOVERY),
    "model_unavailable": (FallbackCondition.MODEL_UNAVAILABLE, ESTABLISHED_BY_DISCOVERY),
    "authentication": (FallbackCondition.PROVIDER_FAILURE_PERSISTENT, ESTABLISHED_BY_PERSISTENCE),
    "quota_exhausted": (FallbackCondition.PROVIDER_FAILURE_PERSISTENT, ESTABLISHED_BY_PERSISTENCE),
    "rate_limited": (FallbackCondition.PROVIDER_FAILURE_PERSISTENT, ESTABLISHED_BY_PERSISTENCE),
    "transport": (FallbackCondition.PROVIDER_FAILURE_PERSISTENT, ESTABLISHED_BY_PERSISTENCE),
    # Not listed in 13 §8.4: fail closed, no condition.
    "authorization": None,
    "timeout": None,
    "protocol": None,
    "invalid_request": None,
    "workspace_violation": None,
    "tool_failure": None,
    "cancelled": None,
    "unknown": None,
}

_DESCRIPTION = {
    "rate_limited": "rate limited (transient; not quota exhaustion)",
    "quota_exhausted": "quota exhausted (confirmed by the runtime; not a rate limit)",
}


class UnmappableExecutionOutcome(ValueError):
    """The outcome is not a failure this module knows; nothing is mapped."""


class ExecutionFailureAssessment(BaseModel):
    """Orchestration's reading of one failed execution; evidence, not authority."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    role: Role
    profile: ProfileRef  # exact version and fingerprint that ran
    status: ExecutionStatus
    error_class: ErrorClass
    error: ExecutionError | None  # original details, unchanged
    runtime: RuntimeIdentity
    condition_if_established: FallbackCondition | None
    established_by: str | None
    second_execution_safe: bool
    attention: AttentionReason


def _digest(outcome: ExecutionOutcome, role: Role, profile: ProfileRef) -> str:
    payload = {
        "role": str(role),
        "profile": profile.model_dump(mode="json"),
        "kind": outcome.kind,
        "status": outcome.status,
        "error": None if outcome.error is None else outcome.error.model_dump(mode="json"),
        "runtime": outcome.runtime.model_dump(mode="json"),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(DIGEST_TAG + DIGEST_SEPARATOR + encoded.encode("ascii")).hexdigest()


def assess_execution_failure(
    outcome: ExecutionOutcome, *, role: Role, profile: ProfileRef
) -> ExecutionFailureAssessment:
    """Classify one failed outcome for `role` run by `profile`."""
    if outcome.status not in FAILURE_STATUSES:
        raise UnmappableExecutionOutcome(f"status {outcome.status!r} is not a failure")
    if outcome.error is not None:
        error_class = outcome.error.error_class
    else:
        error_class = "cancelled" if outcome.status == "cancelled" else "unknown"
    if error_class not in CONDITION_IF_ESTABLISHED:
        raise UnmappableExecutionOutcome(f"unknown error class {error_class!r}")

    mapped = CONDITION_IF_ESTABLISHED[error_class]
    condition, established_by = mapped if mapped is not None else (None, None)
    safe = outcome.status in TERMINAL_OBSERVED
    auditing = role in AUDITED_PRODUCERS
    code = AttentionCode.AUDITOR_ERROR if auditing else AttentionCode.AGENT_UNAVAILABLE

    runtime = outcome.runtime
    summary = (
        f"{role} execution {outcome.status}: {_DESCRIPTION.get(error_class, error_class)}; "
        f"profile {profile.profile_id} v{profile.version}, "
        f"adapter {runtime.adapter_id or runtime.backend}"
    )
    if not safe:
        summary += "; final runtime state not observed, so it is not re-executed"
    evidence = EvidenceRef(kind=EVIDENCE_KIND, ref=_digest(outcome, role, profile))
    return ExecutionFailureAssessment(
        role=role,
        profile=profile,
        status=outcome.status,
        error_class=error_class,
        error=outcome.error,
        runtime=runtime,
        condition_if_established=condition,
        established_by=established_by,
        second_execution_safe=safe,
        attention=AttentionReason(code=code, summary=summary, evidence=(evidence,)),
    )


def route_execution_failure(
    work_order: WorkOrder, assessment: ExecutionFailureAssessment
) -> WorkOrder:
    """Raise the assessment's attention reason through the public state machine.

    No fallback is attempted here: whether a fallback may run is decided only
    by control, through `begin_attempt` and the approved binding.
    """
    return machine.raise_attention(work_order, assessment.attention)
