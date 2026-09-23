"""Normalization of LongHorizon auditor EpisodeResults into AuditorVerification.

Unit cases build EpisodeResults directly; integration cases use the real
UHPWorkspaceAuditorAdapter over the offline fake HarnessRouter.
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
    audit_server,
    broker,
    candidate,
    isolated_git,
    repo,
    run_auditor,
    staging,
)

from cloudeo.longhorizon.audit_result import AuditorVerification, normalize_auditor_result

MALFORMED = "Everything looks finished to me."
INCOMPLETE_REPORT = VALID_REPORT.replace("Status: complete", "Status: incomplete")
NO_MUTATIONS = {"added": [], "changed": [], "deleted": [], "type_changed": []}


def guarded(**metadata):
    """Metadata of a read-only audit whose guard saw no mutation."""
    return {
        "verifier_workspace_guard": True,
        "verifier_workspace_mutation_detected": False,
        "verifier_workspace_mutations": NO_MUTATIONS,
        "assistant_visible_output": VALID_REPORT,
        "actions_log_diagnostics_only": True,
        **metadata,
    }


def episode(status="done", *, actions_log="", error=None, **metadata):
    return EpisodeResult(
        status=status, actions_log=actions_log, error=error, duration_ms=5, metadata=metadata
    )


def done(**metadata):
    return episode(**guarded(**metadata))


# --- Normal reports ---


def test_valid_report_is_verified():
    result = normalize_auditor_result(done())
    assert isinstance(result, AuditorVerification)
    assert (result.status, result.reason, result.verified) == ("VERIFIED", "report_complete", True)
    assert result.report_source == "metadata.assistant_visible_output"
    assert (result.report_status, result.integrity_status, result.contract_audit_status) == (
        "complete",
        "clean",
        "aligned",
    )
    assert result.report_text.startswith("Status: complete")
    assert result.verifier_workspace_mutation_detected is False
    assert result.verifier_workspace_mutations == NO_MUTATIONS
    assert result.failure is None


def test_valid_but_incomplete_report_is_not_verified():
    result = normalize_auditor_result(done(assistant_visible_output=INCOMPLETE_REPORT))
    assert (result.status, result.reason) == ("NOT_VERIFIED", "report_not_complete")
    assert result.report_status == "incomplete"


def test_longhorizon_acceptance_guard_still_applies():
    # LongHorizon, not Cloudeo, downgrades "complete" with blocking constraints.
    text = VALID_REPORT.replace("Blocking constraints: none", "Blocking constraints: tests fail")
    result = normalize_auditor_result(done(assistant_visible_output=text))
    assert result.status == "NOT_VERIFIED"
    assert (result.report_status, result.contract_audit_status) == ("incomplete", "unknown")


# --- Workspace mutation ---

MUTATIONS = {
    "added": ["notes.md"],
    "changed": ["README.md"],
    "deleted": ["docs/old.md"],
    "type_changed": ["link"],
}


def test_mutation_detected_is_blocked_and_list_preserved():
    # Native LongHorizon shape: a done episode whose guard saw writes.
    result = normalize_auditor_result(
        done(verifier_workspace_mutation_detected=True, verifier_workspace_mutations=MUTATIONS)
    )
    assert (result.status, result.reason) == ("BLOCKED", "workspace_mutation_detected")
    assert result.verifier_workspace_mutation_detected is True
    assert result.verifier_workspace_mutations == MUTATIONS
    assert result.report_source is None  # the report was not used


# --- Missing, malformed, ambiguous reports ---


@pytest.mark.parametrize(
    "metadata,actions_log",
    [
        ({"assistant_visible_output": ""}, ""),
        ({"assistant_visible_output": "   \n"}, ""),
        # A valid report only in actions_log is never a report source, even
        # when actions_log is not marked diagnostics-only.
        ({"assistant_visible_output": "", "actions_log_diagnostics_only": False}, VALID_REPORT),
    ],
    ids=["empty", "whitespace", "actions_log_only"],
)
def test_missing_report_is_blocked(metadata, actions_log):
    result = normalize_auditor_result(episode(actions_log=actions_log, **guarded(**metadata)))
    assert (result.status, result.reason) == ("BLOCKED", "report_missing")
    assert result.report_source is None


def test_malformed_report_is_blocked():
    result = normalize_auditor_result(done(assistant_visible_output=MALFORMED))
    assert (result.status, result.reason) == ("BLOCKED", "report_malformed")
    assert result.format_repair == "not_provided"
    assert result.report_text == MALFORMED
    assert result.report_source == "metadata.assistant_visible_output"


def test_conflicting_visible_outputs_are_ambiguous():
    result = normalize_auditor_result(done(executor_agent_visible_output=INCOMPLETE_REPORT))
    assert (result.status, result.reason) == ("BLOCKED", "report_source_ambiguous")


def test_identical_visible_outputs_follow_longhorizon_precedence():
    result = normalize_auditor_result(done(output_text=VALID_REPORT))
    assert result.status == "VERIFIED"
    assert result.report_source == "metadata.assistant_visible_output"


def test_no_read_only_evidence_is_blocked():
    # E.g. a text-only adapter: a perfect report, but no workspace guard.
    result = normalize_auditor_result(
        episode(assistant_visible_output=VALID_REPORT, actions_log_diagnostics_only=True)
    )
    assert (result.status, result.reason) == ("BLOCKED", "read_only_evidence_missing")


# --- Runtime and provider failures ---


@pytest.mark.parametrize(
    "status,error,kind",
    [
        ("error", "HTTP 401 Unauthorized: invalid api key", "authentication"),
        ("error", "rate limit exceeded (429)", "rate_limit"),
        ("error", "harness crashed", "provider_error"),
        ("timeout", "Harness task stopped at a budget: max_steps.", "timeout"),
        ("cancelled", "Execution cancelled by operator", "cancelled"),
    ],
)
def test_runtime_failure_is_auditor_error(status, error, kind):
    # Even with a perfect report in the metadata.
    result = normalize_auditor_result(episode(status, error=error, **guarded()))
    assert (result.status, result.reason) == ("AUDITOR_ERROR", "auditor_runtime_failure")
    assert result.failure.kind == kind
    assert result.upstream_error == error
    assert result.report_source is None


@pytest.mark.parametrize(
    "code,status,reason",
    [
        ("candidate_changed_during_audit", "BLOCKED", "audit_boundary_invalid"),
        ("candidate_stale_during_audit", "BLOCKED", "audit_boundary_invalid"),
        ("audit_evidence_invalid", "BLOCKED", "audit_boundary_invalid"),
        ("candidate_unavailable", "BLOCKED", "audit_boundary_invalid"),
        ("workspace_upload_failed", "AUDITOR_ERROR", "auditor_transport_failure"),
    ],
)
def test_cloudeo_audit_boundary_codes(code, status, reason):
    # Checked before LongHorizon's classifier, which would call these provider errors.
    result = normalize_auditor_result(
        episode("error", error=f"{code}: detail", **guarded(audit_invalid_reasons=[code]))
    )
    assert (result.status, result.reason) == (status, reason)
    assert result.failure.kind == code
    assert result.failure.source == "cloudeo_audit_boundary"


# --- Primary visible output vs repaired actions_log ---


def test_manager_repair_shape_does_not_use_repaired_actions_log():
    """What the pinned manager builds after repair: repaired text in
    actions_log, primary metadata (malformed visible output) kept."""
    corrected = episode(actions_log=VALID_REPORT, **guarded(assistant_visible_output=MALFORMED))
    result = normalize_auditor_result(corrected)
    assert (result.status, result.reason) == ("BLOCKED", "report_malformed")
    assert result.report_source == "metadata.assistant_visible_output"
    assert result.report_text == MALFORMED


def test_repair_is_used_only_when_explicitly_passed():
    primary = done(assistant_visible_output=MALFORMED)
    repair = episode(assistant_visible_output=VALID_REPORT, actions_log_diagnostics_only=True)
    result = normalize_auditor_result(primary, repair=repair)
    assert result.format_repair == "accepted"
    assert result.report_source == "repair.metadata.assistant_visible_output"
    assert result.repair_metadata == repair.metadata
    # The primary's evidence still decides the mutation fields.
    assert result.verifier_workspace_mutation_detected is False


# --- Repair recovers syntax only; it is never verification authority ---


def test_1_malformed_original_with_positive_repair_is_capped_at_not_verified():
    repair = episode(assistant_visible_output=VALID_REPORT)
    result = normalize_auditor_result(done(assistant_visible_output=MALFORMED), repair=repair)
    assert (result.status, result.reason) == (
        "NOT_VERIFIED",
        "report_repaired_not_verification_authority",
    )
    assert result.verified is False
    # The repaired text, its parsed fields, and its provenance are all kept.
    assert result.report_text.startswith("Status: complete")
    assert (result.report_status, result.integrity_status, result.contract_audit_status) == (
        "complete",
        "clean",
        "aligned",
    )
    assert result.format_repair == "accepted"
    assert result.report_source == "repair.metadata.assistant_visible_output"
    assert result.repair_metadata == repair.metadata
    assert result.upstream_metadata["assistant_visible_output"] == MALFORMED


def test_2_repaired_negative_report_is_not_verified():
    repair = episode(assistant_visible_output=INCOMPLETE_REPORT)
    result = normalize_auditor_result(done(assistant_visible_output=MALFORMED), repair=repair)
    assert (result.status, result.reason) == ("NOT_VERIFIED", "report_not_complete")
    assert (result.format_repair, result.report_status) == ("accepted", "incomplete")


def test_structured_evidence_does_not_make_a_repaired_report_verified():
    """Every structured signal Cloudeo has is clean, and it still does not verify.

    The read-only guard, snapshot, and accepted-state evidence prove only that
    the audit was attributable and read-only, not what it concluded; there is
    no structured verification path that bypasses the report text.
    """
    primary = done(
        assistant_visible_output=MALFORMED,
        audit_invalid_reasons=[],
        audit_snapshot_unchanged=True,
        accepted_state_unchanged=True,
        auditor_remote_workspace_unchanged=True,
        independently_verified=False,
    )
    result = normalize_auditor_result(
        primary, repair=episode(assistant_visible_output=VALID_REPORT)
    )
    assert result.status == "NOT_VERIFIED"


POSITIVE_REPAIR = episode(assistant_visible_output=VALID_REPORT)
UNVERIFIABLE_PRIMARIES = {
    "runtime_error": lambda text: episode(
        "error", error="harness crashed", **guarded(assistant_visible_output=text)
    ),
    "provider_auth": lambda text: episode(
        "error", error="HTTP 401 Unauthorized", **guarded(assistant_visible_output=text)
    ),
    "timeout": lambda text: episode(
        "timeout", error="budget", **guarded(assistant_visible_output=text)
    ),
    "cancelled": lambda text: episode("cancelled", **guarded(assistant_visible_output=text)),
    "native_mutation": lambda text: done(
        assistant_visible_output=text,
        verifier_workspace_mutation_detected=True,
        verifier_workspace_mutations=MUTATIONS,
    ),
    "cloudeo_mutation": lambda text: episode(
        "error",
        **guarded(
            assistant_visible_output=text,
            audit_invalid_reasons=["auditor_workspace_mutation_detected"],
        ),
    ),
    "no_read_only_evidence": lambda text: episode(assistant_visible_output=text),
    "guard_without_verdict": lambda text: done(
        assistant_visible_output=text, verifier_workspace_mutation_detected=None
    ),
    "candidate_drift": lambda text: episode(
        "error",
        **guarded(
            assistant_visible_output=text, audit_invalid_reasons=["candidate_changed_during_audit"]
        ),
    ),
    "accepted_state_moved": lambda text: episode(
        "error",
        **guarded(
            assistant_visible_output=text, audit_invalid_reasons=["candidate_stale_during_audit"]
        ),
    ),
    "evidence_invalid": lambda text: episode(
        "error",
        **guarded(assistant_visible_output=text, audit_invalid_reasons=["audit_evidence_invalid"]),
    ),
    "transport_failure": lambda text: episode(
        "error",
        **guarded(assistant_visible_output=text, audit_invalid_reasons=["workspace_upload_failed"]),
    ),
}


@pytest.mark.parametrize(
    "primary_text", [MALFORMED, "", VALID_REPORT], ids=["malformed", "empty", "valid"]
)
@pytest.mark.parametrize("condition", sorted(UNVERIFIABLE_PRIMARIES))
def test_4_no_repair_turns_a_failed_audit_into_verified(condition, primary_text):
    primary = UNVERIFIABLE_PRIMARIES[condition](primary_text)
    result = normalize_auditor_result(primary, repair=POSITIVE_REPAIR)
    assert result.status in ("BLOCKED", "AUDITOR_ERROR")
    assert result.format_repair == "not_needed"  # repair is never even considered
    assert result.report_source is None


def test_repair_is_ignored_when_primary_report_is_valid():
    primary = done(assistant_visible_output=INCOMPLETE_REPORT)
    repair = episode(assistant_visible_output=VALID_REPORT)
    result = normalize_auditor_result(primary, repair=repair)
    assert result.status == "NOT_VERIFIED"
    assert result.format_repair == "not_needed"
    assert result.report_source == "metadata.assistant_visible_output"


@pytest.mark.parametrize(
    "repair",
    [
        episode("error", error="harness crashed", assistant_visible_output=VALID_REPORT),
        episode(assistant_visible_output=MALFORMED),
        episode(actions_log=VALID_REPORT, assistant_visible_output=""),
        episode(assistant_visible_output=VALID_REPORT, verifier_workspace_mutation_detected=True),
        episode(assistant_visible_output=VALID_REPORT, output_text=INCOMPLETE_REPORT),
    ],
    ids=["failed", "still_malformed", "actions_log_only", "mutated", "ambiguous"],
)
def test_3_unacceptable_repair_is_blocked(repair):
    result = normalize_auditor_result(done(assistant_visible_output=MALFORMED), repair=repair)
    assert (result.status, result.reason) == ("BLOCKED", "report_malformed")
    assert result.format_repair == "rejected"


def test_repair_cannot_rescue_a_mutated_or_failed_primary():
    repair = episode(assistant_visible_output=VALID_REPORT)
    mutated = done(assistant_visible_output=MALFORMED, verifier_workspace_mutation_detected=True)
    assert normalize_auditor_result(mutated, repair=repair).status == "BLOCKED"
    failed = episode(
        "error", error="harness crashed", **guarded(assistant_visible_output=MALFORMED)
    )
    assert normalize_auditor_result(failed, repair=repair).status == "AUDITOR_ERROR"


# --- No false VERIFIED ---

FAILURES = {
    "missing": done(assistant_visible_output=""),
    "malformed": done(assistant_visible_output=MALFORMED),
    "ambiguous": done(output_text=INCOMPLETE_REPORT),
    "mutated": done(verifier_workspace_mutation_detected=True),
    "no_guard": episode(assistant_visible_output=VALID_REPORT),
    "guard_without_verdict": done(verifier_workspace_mutation_detected=None),
    "drift": episode("error", **guarded(audit_invalid_reasons=["candidate_changed_during_audit"])),
    "runtime_error": episode("error", error="boom", **guarded()),
    "timeout": episode("timeout", error="budget", **guarded()),
    "cancelled": episode("cancelled", **guarded()),
    "manager_repair_shape": episode(
        actions_log=VALID_REPORT, **guarded(assistant_visible_output=MALFORMED)
    ),
    "not_a_dict": EpisodeResult(status="done", metadata=None),
}


@pytest.mark.parametrize("name", sorted(FAILURES))
def test_extraction_or_execution_failure_is_never_verified(name):
    result = normalize_auditor_result(FAILURES[name])
    assert result.status in ("BLOCKED", "AUDITOR_ERROR")
    assert result.verified is False


def test_upstream_metadata_is_preserved_unmodified():
    primary = done(verifier_workspace_mutations=MUTATIONS, custom_evidence={"k": [1]})
    result = normalize_auditor_result(primary)
    assert result.upstream_metadata == primary.metadata
    primary.metadata["custom_evidence"]["k"].append(2)
    assert result.upstream_metadata["custom_evidence"] == {"k": [1]}


# --- Integration with the real UHPWorkspaceAuditorAdapter ---


async def test_real_read_only_audit_is_verified(broker, candidate, staging, tmp_path):
    result = normalize_auditor_result(
        await run_auditor(broker, candidate, audit_server(tmp_path), staging)
    )
    assert result.status == "VERIFIED"
    assert result.verifier_workspace_mutations == NO_MUTATIONS
    assert result.upstream_metadata["audit_snapshot_content_sha256"]


async def test_real_auditor_mutation_is_blocked_with_paths(broker, candidate, staging, tmp_path):
    def mutate(ws):
        (ws / "audit_notes.md").write_text("notes\n")
        os.chmod(ws / "src/app.py", 0o755)

    episode_result = await run_auditor(
        broker, candidate, audit_server(tmp_path, work=mutate), staging
    )
    result = normalize_auditor_result(episode_result)
    assert (result.status, result.reason) == ("BLOCKED", "workspace_mutation_detected")
    assert result.verifier_workspace_mutations == {
        "added": ["audit_notes.md"],
        "changed": ["src/app.py"],
        "deleted": [],
        "type_changed": [],
    }
    # The auditor's report was withheld as untrusted and is not the result text.
    assert result.report_text == ""
    assert result.upstream_metadata["untrusted_auditor_output"] == VALID_REPORT


async def test_real_local_drift_is_blocked(broker, candidate, staging, tmp_path):
    server = audit_server(
        tmp_path, work=lambda ws: (candidate.local_path / "README.md").write_text("edit\n")
    )
    result = normalize_auditor_result(await run_auditor(broker, candidate, server, staging))
    assert (result.status, result.reason) == ("BLOCKED", "audit_boundary_invalid")
    assert result.failure.kind == "candidate_changed_during_audit"


async def test_real_runtime_failure_is_auditor_error(broker, candidate, staging, tmp_path):
    server = audit_server(tmp_path, status="failed")
    result = normalize_auditor_result(await run_auditor(broker, candidate, server, staging))
    assert (result.status, result.reason) == ("AUDITOR_ERROR", "auditor_runtime_failure")
    assert result.failure.source == "longhorizon_classifier"


async def test_real_malformed_audit_with_positive_repair_is_not_verified(
    broker, candidate, staging, tmp_path
):
    primary = await run_auditor(broker, candidate, audit_server(tmp_path, text=MALFORMED), staging)
    assert primary.status == "done"  # the read-only boundary held
    result = normalize_auditor_result(primary, repair=POSITIVE_REPAIR)
    assert (result.status, result.reason) == (
        "NOT_VERIFIED",
        "report_repaired_not_verification_authority",
    )
    assert result.format_repair == "accepted"
