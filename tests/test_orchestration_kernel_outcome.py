"""V2C-04: KernelOutcome from real GatedPromotionResults (ADR-030).

Gate results come from the real checkpoint_and_promote_verified() on a real
GitWorkspaceBroker, with verifications from the real auditor adapter (offline
fake HarnessRouter) and normalize_auditor_result().
"""

# Pytest fixtures imported from the auditor tests are requested by parameter
# name, which ruff reports as redefinitions.
# ruff: noqa: F811

import hashlib
import json
import typing

import pytest

pytest.importorskip("lh_harness", reason="requires the optional 'longhorizon' extra")

from control_helpers import final_verification
from test_longhorizon_promotion_gate import (
    RacingBroker,
    add_untracked,
    execute,
    gate,
    modify_tracked,
    verify,
)
from test_longhorizon_workspace_auditor import (  # noqa: F401 - fixtures are used by name
    accepted,
    broker,
    candidate,
    git,
    isolated_git,
    repo,
    staging,
)

from cloudeo.control import machine as m
from cloudeo.control.model import AttentionCode, WorkOrderStatus
from cloudeo.longhorizon.promotion_gate import GateStage, GateStatus
from cloudeo.orchestration.kernel_outcome import (
    ALLOWED_STATUS,
    DIGEST_SEPARATOR,
    DIGEST_TAG,
    REFUSAL_STATUSES,
    STAGES,
    UnmappableGateResult,
    gated_promotion_result_digest,
    kernel_outcome_from_gate,
)


@pytest.fixture
async def results(repo, broker, candidate, staging, tmp_path):
    """One real gate result for each stage, and NOTHING_TO_PROMOTE."""
    execute(candidate)
    verification = await verify(broker, candidate, staging, tmp_path)
    modify_tracked(candidate.local_path)
    before = gate(broker, candidate, verification)
    execute(candidate)  # back to the audited state
    racing = RacingBroker(
        broker, {"checkpoint_candidate": lambda: add_untracked(candidate.local_path)}
    )
    after = gate(racing, candidate, verification)
    fresh = broker.create_candidate(broker.accepted_state())
    execute(fresh)
    promoted = gate(broker, fresh, await verify(broker, fresh, staging, tmp_path, "fresh"))
    clean = broker.create_candidate(broker.accepted_state())
    nothing = gate(broker, clean, await verify(broker, clean, staging, tmp_path, "clean"))
    stages = [r.stage for r in (before, after, promoted, nothing)]
    assert stages == [
        "refused_before_checkpoint",
        "refused_after_checkpoint",
        "promoted",
        "refused_before_checkpoint",
    ]
    assert nothing.decision.status == "NOTHING_TO_PROMOTE"
    return {"before": before, "after": after, "promoted": promoted, "nothing": nothing}


def test_v2c_04_real_gate_results_map_to_kernel_outcomes(results, repo):
    for result in results.values():
        outcome = kernel_outcome_from_gate(result)
        assert outcome.promotion_attempted is True
        assert outcome.stage == result.stage
        assert outcome.reason == result.decision.reason
        assert outcome.promoted == result.promoted
        expected_commit = result.checkpoint.commit if result.checkpoint else None
        assert outcome.checkpoint_commit == expected_commit
    promoted = kernel_outcome_from_gate(results["promoted"])
    assert promoted.promoted and promoted.checkpoint_commit == accepted(repo)
    assert not kernel_outcome_from_gate(results["after"]).promoted


def test_v2c_04_the_control_layer_decides_from_the_mapped_outcome(results):
    wo = m.record_kernel_outcome(
        final_verification(), kernel_outcome_from_gate(results["promoted"])
    )
    assert wo.status == WorkOrderStatus.PROMOTED
    for key in ("before", "after", "nothing"):
        wo = m.record_kernel_outcome(final_verification(), kernel_outcome_from_gate(results[key]))
        assert wo.status == WorkOrderStatus.USER_ATTENTION_REQUIRED
        assert wo.open_attention.reasons[0].code == AttentionCode.PROMOTION_REFUSED


def test_v2c_04_the_evidence_digest_is_framed_versioned_and_deterministic(results):
    result = results["promoted"]
    payload = json.dumps(
        result.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")
    assert DIGEST_TAG == b"gated-promotion-result:v1" and DIGEST_SEPARATOR == b"\x00"
    digest = gated_promotion_result_digest(result)
    assert digest == hashlib.sha256(DIGEST_TAG + DIGEST_SEPARATOR + payload).hexdigest()
    assert digest != hashlib.sha256(payload).hexdigest()  # domain-separated
    outcome = kernel_outcome_from_gate(result)
    assert outcome.evidence.kind == "gated_promotion_result" and outcome.evidence.ref == digest
    assert kernel_outcome_from_gate(result) == outcome  # deterministic
    changed = result.model_copy(update={"checkpoint_created": not result.checkpoint_created})
    assert gated_promotion_result_digest(changed) != digest


def test_v2c_04_known_values_are_exactly_the_gates():
    # A new gate stage or status must fail here and be mapped deliberately.
    assert set(typing.get_args(GateStage)) == STAGES
    assert set(typing.get_args(GateStatus)) == REFUSAL_STATUSES | {ALLOWED_STATUS}


def forge(result, *, decision=None, **fields):
    """A result the gate never produces (validation bypassed on purpose)."""
    if decision:
        fields["decision"] = result.decision.model_copy(update=decision)
    return result.model_copy(update=fields)


@pytest.mark.negative
def test_v2c_04_unknown_or_inconsistent_results_fail_closed(results):
    promoted, after, before = results["promoted"], results["after"], results["before"]
    other = promoted.checkpoint.model_copy(update={"commit": "e" * 40})
    # Each case names the guard that must refuse it, so every guard is observable.
    forged = [
        (forge(before, stage="refused_somewhere_new"), "unknown gate stage"),
        (forge(before, decision={"status": "SOMETHING_NEW"}), "unknown gate status"),
        (forge(promoted, promotion=None), "promoted without both records"),
        (forge(promoted, decision={"status": "BLOCKED"}), "promoted with status BLOCKED"),
        (
            forge(promoted, promotion=promoted.promotion.model_copy(update={"checkpoint": other})),
            "does not match the checkpoint",
        ),
        (forge(after, checkpoint=None), "refused_after_checkpoint without a checkpoint"),
        (forge(after, promotion=promoted.promotion), "with a promotion"),
        (forge(after, decision={"status": ALLOWED_STATUS}), "with status VERIFIED_AND_CURRENT"),
        (forge(before, checkpoint=after.checkpoint), "refused_before_checkpoint with a checkpoint"),
        (forge(before, checkpoint_created=True), "refused_before_checkpoint with a checkpoint"),
    ]
    for result, guard in forged:
        with pytest.raises(UnmappableGateResult, match=guard):
            kernel_outcome_from_gate(result)
