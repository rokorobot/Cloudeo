"""Verified checkpoint and promotion gate.

Real GitWorkspaceBroker and CandidateWorkspace, verifications produced by the
real UHPWorkspaceAuditorAdapter (offline fake HarnessRouter) and
normalize_auditor_result().
"""

# Pytest fixtures imported from the auditor tests are requested by parameter
# name, which ruff reports as redefinitions.
# ruff: noqa: F811

import os

import pytest

pytest.importorskip("lh_harness", reason="requires the optional 'longhorizon' extra")

from lh_harness.types import EpisodeResult
from test_longhorizon_workspace_auditor import (  # noqa: F401 - fixtures are used by name
    VALID_REPORT,
    accepted,
    audit_server,
    broker,
    candidate,
    git,
    isolated_git,
    repo,
    run_auditor,
    staging,
)

from cloudeo.bridge.audit import current_content_sha256
from cloudeo.bridge.models import BridgeLimits
from cloudeo.longhorizon.audit_result import normalize_auditor_result
from cloudeo.longhorizon.promotion_gate import (
    checkpoint_and_promote_verified,
    commit_content_sha256,
    evaluate_promotion_gate,
)

INCOMPLETE_REPORT = VALID_REPORT.replace("Status: complete", "Status: incomplete")


def execute(candidate):
    """Stand-in for executor output: the candidate becomes A'."""
    (candidate.local_path / "README.md").write_text("executor change\n")
    (candidate.local_path / "src/feature.py").write_text("FEATURE = True\n")


async def verify(broker, candidate, staging, tmp_path, name="audit", **server):
    episode = await run_auditor(broker, candidate, audit_server(tmp_path / name, **server), staging)
    return normalize_auditor_result(episode)


def checkpoint_refs(repo):
    refs = git(repo, "for-each-ref", "--format=%(refname)", "refs/cloudeo").splitlines()
    return [r for r in refs if "/checkpoints/" in r]


def gate(broker, candidate, verification):
    return checkpoint_and_promote_verified(broker, candidate, verification, message="verified")


def without(verification, *keys, **overrides):
    metadata = {k: v for k, v in verification.upstream_metadata.items() if k not in keys}
    return verification.model_copy(update={"upstream_metadata": {**metadata, **overrides}})


# --- Allowed ---


async def test_verified_and_current_is_promoted_exactly(repo, broker, candidate, staging, tmp_path):
    execute(candidate)
    verification = await verify(broker, candidate, staging, tmp_path)
    assert verification.status == "VERIFIED"
    a = accepted(repo)

    decision = evaluate_promotion_gate(broker, candidate, verification)
    assert (decision.status, decision.allowed) == ("VERIFIED_AND_CURRENT", True)
    assert decision.observed.content_sha256 == decision.audited.content_sha256
    assert accepted(repo) == a  # evaluation is read-only
    assert checkpoint_refs(repo) == []

    result = gate(broker, candidate, verification)
    assert result.promoted
    assert result.decision.status == "VERIFIED_AND_CURRENT"
    commit = result.checkpoint.commit
    assert accepted(repo) == commit
    # The promoted commit is exactly the audited state, on top of the audited HEAD.
    audited = decision.audited
    assert git(repo, "rev-parse", f"{commit}^1") == audited.head_commit
    assert commit_content_sha256(candidate.local_path, commit) == audited.content_sha256


async def test_already_checkpointed_audited_state_is_promoted(
    repo, broker, candidate, staging, tmp_path
):
    execute(candidate)
    checkpoint = broker.checkpoint_candidate(candidate, "before audit")
    verification = await verify(broker, candidate, staging, tmp_path)
    result = gate(broker, candidate, verification)
    assert result.promoted
    assert (result.stage, result.checkpoint_created) == ("promoted", False)  # reused
    assert result.checkpoint.commit == checkpoint.commit
    assert accepted(repo) == checkpoint.commit


async def test_ignored_local_files_are_not_workspace_state(broker, candidate, staging, tmp_path):
    execute(candidate)
    verification = await verify(broker, candidate, staging, tmp_path)
    (candidate.local_path / ".env").write_text("SECRET=rotated\n")  # ignored
    assert evaluate_promotion_gate(broker, candidate, verification).allowed


def test_commit_content_matches_worktree_content_rules(broker, candidate):
    execute(candidate)
    os.chmod(candidate.local_path / "src/feature.py", 0o755)
    checkpoint = broker.checkpoint_candidate(candidate, "clean state")
    assert commit_content_sha256(candidate.local_path, checkpoint.commit) == (
        current_content_sha256(candidate, BridgeLimits())
    )


# --- The workspace moved on after the audit ---


def modify_tracked(root):
    (root / "README.md").write_text("changed after the audit\n")


def add_untracked(root):
    (root / "late.txt").write_text("new after the audit\n")


def delete_file(root):
    (root / "src/app.py").unlink()


def chmod_file(root):
    os.chmod(root / "src/app.py", 0o755)


@pytest.mark.parametrize(
    "change",
    [modify_tracked, add_untracked, delete_file, chmod_file],
    ids=["content_hash_changed", "new_dirty_file", "deleted", "executable_bit"],
)
async def test_workspace_changed_after_audit_is_denied(
    repo, broker, candidate, staging, tmp_path, change
):
    execute(candidate)
    verification = await verify(broker, candidate, staging, tmp_path)
    change(candidate.local_path)
    a = accepted(repo)
    decision = evaluate_promotion_gate(broker, candidate, verification)
    assert (decision.status, decision.reason) == (
        "WORKSPACE_CHANGED",
        "content_changed_since_audit",
    )
    result = gate(broker, candidate, verification)
    assert not result.promoted and result.checkpoint is None
    assert result.stage == "refused_before_checkpoint"
    assert accepted(repo) == a
    assert checkpoint_refs(repo) == []


async def test_head_changed_with_identical_files_is_denied(
    repo, broker, candidate, staging, tmp_path
):
    # Same final file contents, different version identity (HEAD).
    execute(candidate)
    verification = await verify(broker, candidate, staging, tmp_path)
    broker.checkpoint_candidate(candidate, "after audit")
    decision = evaluate_promotion_gate(broker, candidate, verification)
    assert decision.observed.content_sha256 is None  # never reached: HEAD decides
    assert (decision.status, decision.reason) == ("HEAD_CHANGED", "head_changed_since_audit")
    assert not gate(broker, candidate, verification).promoted


async def test_same_content_on_another_candidate_is_stale(
    repo, broker, candidate, staging, tmp_path
):
    execute(candidate)
    verification = await verify(broker, candidate, staging, tmp_path)
    twin = broker.create_candidate(broker.accepted_state())
    for name in ("notes/new.txt", ".env", "debug.log"):
        (twin.local_path / name).parent.mkdir(parents=True, exist_ok=True)
        (twin.local_path / name).write_bytes((candidate.local_path / name).read_bytes())
    execute(twin)
    assert current_content_sha256(twin, BridgeLimits()) == current_content_sha256(
        candidate, BridgeLimits()
    )
    decision = evaluate_promotion_gate(broker, twin, verification)
    assert (decision.status, decision.reason) == ("VERIFICATION_STALE", "audit_identity_mismatch")


async def test_accepted_state_moved_after_audit_is_stale(
    repo, broker, candidate, staging, tmp_path
):
    execute(candidate)
    verification = await verify(broker, candidate, staging, tmp_path)
    other = broker.create_candidate(broker.accepted_state())
    (other.local_path / "other.txt").write_text("x\n")
    broker.promote(broker.checkpoint_candidate(other, "other"))
    decision = evaluate_promotion_gate(broker, candidate, verification)
    assert (decision.status, decision.reason) == ("VERIFICATION_STALE", "candidate_stale")


# --- Races between the recheck and the broker operations ---


class RacingBroker:
    """Delegates to the real broker, changing state just before one call."""

    def __init__(self, broker, before):
        self._broker = broker
        self._before = before

    def __getattr__(self, name):
        target = getattr(self._broker, name)
        if name not in self._before:
            return target

        def call(*args, **kwargs):
            self._before[name]()
            return target(*args, **kwargs)

        return call


async def test_race_between_recheck_and_checkpoint_is_denied(
    repo, broker, candidate, staging, tmp_path
):
    execute(candidate)
    verification = await verify(broker, candidate, staging, tmp_path)
    a = accepted(repo)
    racing = RacingBroker(
        broker, {"checkpoint_candidate": lambda: modify_tracked(candidate.local_path)}
    )
    result = gate(racing, candidate, verification)
    # 1. A checkpoint was created but not promoted.
    assert not result.promoted and result.promotion is None
    assert (result.decision.status, result.decision.reason) == (
        "WORKSPACE_CHANGED",
        "checkpoint_differs_from_audit",
    )
    # 2. The result exposes that checkpoint, which is kept with its ref.
    assert result.stage == "refused_after_checkpoint"
    assert result.checkpoint_created is True
    commit = result.checkpoint.commit
    assert git(candidate.local_path, "rev-parse", "HEAD") == commit
    assert any(r.endswith(f"/checkpoints/{commit}") for r in checkpoint_refs(repo))
    assert git(repo, "show", f"{commit}:README.md") == "changed after the audit"
    # 3. Accepted state is unchanged.
    assert accepted(repo) == a


async def test_race_on_accepted_state_before_promote_is_denied(
    repo, broker, candidate, staging, tmp_path
):
    execute(candidate)
    verification = await verify(broker, candidate, staging, tmp_path)

    def promote_other():
        other = broker.create_candidate(broker.accepted_state())
        (other.local_path / "other.txt").write_text("x\n")
        broker.promote(broker.checkpoint_candidate(other, "other"))

    result = gate(RacingBroker(broker, {"promote": promote_other}), candidate, verification)
    assert not result.promoted
    assert (result.stage, result.checkpoint_created) == ("refused_after_checkpoint", True)
    assert (result.decision.status, result.decision.reason) == (
        "VERIFICATION_STALE",
        "candidate_stale",
    )
    assert accepted(repo) != result.checkpoint.commit


async def test_audit_then_change_then_gate(repo, broker, candidate, staging, tmp_path):
    """The race from the milestone: audit A, the workspace becomes B, promotion."""
    execute(candidate)
    verification = await verify(broker, candidate, staging, tmp_path)  # state A
    (candidate.local_path / "src/feature.py").write_text("FEATURE = False\n")  # state B
    a = accepted(repo)
    result = gate(broker, candidate, verification)
    assert not result.promoted
    assert result.decision.status == "WORKSPACE_CHANGED"
    assert accepted(repo) == a


async def test_caller_can_distinguish_how_far_the_gate_got(
    repo, broker, candidate, staging, tmp_path
):
    """4. Before a checkpoint, after a checkpoint, or promoted."""
    execute(candidate)
    verification = await verify(broker, candidate, staging, tmp_path)
    a = accepted(repo)

    # Refused before any checkpoint: the workspace changed after the audit.
    modify_tracked(candidate.local_path)
    before = gate(broker, candidate, verification)
    assert (before.stage, before.checkpoint, before.checkpoint_created) == (
        "refused_before_checkpoint",
        None,
        False,
    )
    assert before.promotion is None and checkpoint_refs(repo) == []

    # Refused after a checkpoint: the change lands at checkpoint time.
    execute(candidate)  # back to A'
    racing = RacingBroker(
        broker, {"checkpoint_candidate": lambda: add_untracked(candidate.local_path)}
    )
    after = gate(racing, candidate, verification)
    assert (after.stage, after.checkpoint_created) == ("refused_after_checkpoint", True)
    assert after.checkpoint is not None and after.promotion is None
    assert accepted(repo) == a

    # Promoted: a fresh candidate, audited and unchanged.
    fresh = broker.create_candidate(broker.accepted_state())
    execute(fresh)
    promoted = gate(broker, fresh, await verify(broker, fresh, staging, tmp_path, "fresh"))
    assert (promoted.stage, promoted.checkpoint_created) == ("promoted", True)
    assert promoted.promotion is not None
    assert accepted(repo) == promoted.checkpoint.commit


# --- Unverified results are refused as-is ---


async def test_not_verified_blocked_and_auditor_error_are_denied(
    repo, broker, candidate, staging, tmp_path
):
    execute(candidate)
    a = accepted(repo)
    not_verified = await verify(broker, candidate, staging, tmp_path, "n", text=INCOMPLETE_REPORT)
    blocked = await verify(
        broker, candidate, staging, tmp_path, "b", work=lambda ws: (ws / "x.txt").write_text("x")
    )
    auditor_error = await verify(broker, candidate, staging, tmp_path, "e", status="failed")
    for verification, status in (
        (not_verified, "NOT_VERIFIED"),
        (blocked, "BLOCKED"),
        (auditor_error, "AUDITOR_ERROR"),
    ):
        assert verification.status == status
        decision = evaluate_promotion_gate(broker, candidate, verification)
        assert (decision.status, decision.reason) == (status, verification.reason)
        assert not gate(broker, candidate, verification).promoted
    assert accepted(repo) == a
    assert checkpoint_refs(repo) == []


async def test_repaired_prose_can_never_promote(repo, broker, candidate, staging, tmp_path):
    execute(candidate)
    primary = await run_auditor(
        broker, candidate, audit_server(tmp_path / "m", text="Looks done."), staging
    )
    repair = EpisodeResult(status="done", metadata={"assistant_visible_output": VALID_REPORT})
    repaired = normalize_auditor_result(primary, repair=repair)
    assert repaired.status == "NOT_VERIFIED"
    assert not gate(broker, candidate, repaired).promoted
    # Even a forged VERIFIED that carries repair provenance is refused.
    genuine = await verify(broker, candidate, staging, tmp_path)
    for forged in (
        genuine.model_copy(update={"format_repair": "accepted"}),
        genuine.model_copy(update={"report_source": "repair.metadata.assistant_visible_output"}),
        genuine.model_copy(update={"reason": "report_repaired_not_verification_authority"}),
    ):
        decision = evaluate_promotion_gate(broker, candidate, forged)
        assert (decision.status, decision.reason) == (
            "NOT_VERIFIED",
            "repaired_report_not_verification_authority",
        )
    assert checkpoint_refs(repo) == []


async def test_gate_consumes_the_contract_not_the_prose(broker, candidate, staging, tmp_path):
    execute(candidate)
    genuine = await verify(broker, candidate, staging, tmp_path)
    negative_text = genuine.model_copy(update={"report_text": INCOMPLETE_REPORT})
    assert evaluate_promotion_gate(broker, candidate, negative_text).allowed
    positive_text = genuine.model_copy(update={"status": "NOT_VERIFIED"})
    assert not evaluate_promotion_gate(broker, candidate, positive_text).allowed


# --- Missing or inconsistent evidence ---


@pytest.mark.parametrize(
    "keys,overrides",
    [
        (("audit_snapshot_content_sha256",), {}),
        (("audit_snapshot_head",), {}),
        (("candidate_id",), {}),
        ((), {"audit_snapshot_content_sha256": "not-a-hash"}),
        ((), {"audit_snapshot_head": "HEAD"}),
        ((), {"audit_snapshot_unchanged": False}),
        (("accepted_state_unchanged",), {}),
        ((), {"auditor_remote_workspace_unchanged": None}),
    ],
    ids=[
        "no_content_hash",
        "no_head",
        "no_candidate_id",
        "bad_content_hash",
        "symbolic_head",
        "snapshot_changed",
        "no_accepted_check",
        "no_remote_check",
    ],
)
async def test_missing_or_malformed_evidence_is_denied(
    repo, broker, candidate, staging, tmp_path, keys, overrides
):
    execute(candidate)
    verification = without(await verify(broker, candidate, staging, tmp_path), *keys, **overrides)
    decision = evaluate_promotion_gate(broker, candidate, verification)
    assert (decision.status, decision.reason) == (
        "EVIDENCE_MISSING",
        "audit_snapshot_evidence_missing",
    )
    assert not gate(broker, candidate, verification).promoted
    assert checkpoint_refs(repo) == []


async def test_forged_verified_without_mutation_verdict_is_denied(
    broker, candidate, staging, tmp_path
):
    execute(candidate)
    genuine = await verify(broker, candidate, staging, tmp_path)
    for forged, reason in (
        (
            genuine.model_copy(update={"verifier_workspace_mutation_detected": None}),
            "workspace_mutation_not_excluded",
        ),
        (
            genuine.model_copy(update={"verifier_workspace_mutation_detected": True}),
            "workspace_mutation_not_excluded",
        ),
        (
            genuine.model_copy(update={"audit_invalid_reasons": ("candidate_stale",)}),
            "audit_boundary_invalid",
        ),
    ):
        decision = evaluate_promotion_gate(broker, candidate, forged)
        assert (decision.status, decision.reason) == ("BLOCKED", reason)


async def test_nothing_to_promote(repo, broker, staging, tmp_path):
    clean = broker.create_candidate(broker.accepted_state())
    verification = await verify(broker, clean, staging, tmp_path)
    assert evaluate_promotion_gate(broker, clean, verification).allowed
    result = gate(broker, clean, verification)
    assert (result.decision.status, result.promoted) == ("NOTHING_TO_PROMOTE", False)
    assert (result.stage, result.checkpoint) == ("refused_before_checkpoint", None)


async def test_gate_uses_only_public_broker_calls(broker, candidate, staging, tmp_path):
    execute(candidate)
    verification = await verify(broker, candidate, staging, tmp_path)
    calls = []

    class Spy:
        def __getattr__(self, name):
            calls.append(name)
            return getattr(broker, name)

    assert gate(Spy(), candidate, verification).promoted
    assert set(calls) == {"inspect_candidate", "accepted_state", "checkpoint_candidate", "promote"}
