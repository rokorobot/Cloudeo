"""GatedPromotionResult -> KernelOutcome (ADR-030, V2C-04).

A pure, deterministic mapping from what the promotion gate returned to the
control layer's KernelOutcome. It fails closed: a stage or status this module
does not know, or a combination the gate never produces, raises
UnmappableGateResult instead of being guessed at.

Requires the 'longhorizon' extra, as the gate itself does.
"""

from __future__ import annotations

import hashlib
import json

from cloudeo.control.model import EvidenceRef, KernelOutcome
from cloudeo.longhorizon.promotion_gate import GatedPromotionResult

EVIDENCE_KIND = "gated_promotion_result"
# Digest framing: SHA-256 over DIGEST_TAG, one NUL byte, then the canonical
# JSON of the result (sorted keys, no whitespace, ASCII). The tag is fixed
# ASCII without NUL, so the boundary is unambiguous. A new serialization or
# meaning needs a new tag (v2), never a silent change.
DIGEST_TAG = b"gated-promotion-result:v1"
DIGEST_SEPARATOR = b"\x00"

ALLOWED_STATUS = "VERIFIED_AND_CURRENT"
REFUSAL_STATUSES = frozenset(
    {
        "NOT_VERIFIED",
        "BLOCKED",
        "AUDITOR_ERROR",
        "EVIDENCE_MISSING",
        "VERIFICATION_STALE",
        "HEAD_CHANGED",
        "WORKSPACE_CHANGED",
        "NOTHING_TO_PROMOTE",
    }
)
STAGES = frozenset({"refused_before_checkpoint", "refused_after_checkpoint", "promoted"})


class UnmappableGateResult(ValueError):
    """The gate result is unknown or internally inconsistent; nothing is mapped."""


def gated_promotion_result_digest(result: GatedPromotionResult) -> str:
    """A content reference to the observed result.

    It identifies the canonical contents of this GatedPromotionResult. It is
    an integrity/content reference, not proof that the result came from an
    authorized gate.
    """
    payload = json.dumps(
        result.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")
    return hashlib.sha256(DIGEST_TAG + DIGEST_SEPARATOR + payload).hexdigest()


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise UnmappableGateResult(message)


def kernel_outcome_from_gate(result: GatedPromotionResult) -> KernelOutcome:
    """The KernelOutcome for a gate call; the gate ran, so the promotion was attempted."""
    stage, status = result.stage, result.decision.status
    checkpoint, promotion = result.checkpoint, result.promotion
    _require(stage in STAGES, f"unknown gate stage {stage!r}")
    _require(
        status == ALLOWED_STATUS or status in REFUSAL_STATUSES, f"unknown gate status {status!r}"
    )
    if stage == "promoted":
        _require(status == ALLOWED_STATUS, f"promoted with status {status}")
        _require(checkpoint is not None and promotion is not None, "promoted without both records")
        _require(
            promotion.checkpoint == checkpoint
            and promotion.accepted_commit == checkpoint.commit
            and promotion.workspace_id == checkpoint.workspace_id,
            "the promotion does not match the checkpoint",
        )
    else:
        _require(status in REFUSAL_STATUSES, f"{stage} with status {status}")
        _require(promotion is None, f"{stage} with a promotion")
        if stage == "refused_after_checkpoint":
            _require(checkpoint is not None, "refused_after_checkpoint without a checkpoint")
        else:
            _require(
                checkpoint is None and not result.checkpoint_created,
                "refused_before_checkpoint with a checkpoint",
            )
    outcome = KernelOutcome(
        promotion_attempted=True,
        stage=stage,
        checkpoint_commit=checkpoint.commit if checkpoint is not None else None,
        reason=result.decision.reason,
        evidence=EvidenceRef(kind=EVIDENCE_KIND, ref=gated_promotion_result_digest(result)),
    )
    _require(outcome.promoted == result.promoted, "promotion flags disagree")
    return outcome
