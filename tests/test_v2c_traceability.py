"""V2C traceability: every contract invariant maps to a guard and tests, or to an
explicit, strictly-expected-to-fail test for what the foundation slice does not
implement yet. No invariant may disappear between architecture and code.

Statuses:
- PASS: enforced by this slice and proven by the listed tests.
- PARTIAL: the state/persistence-layer guard is enforced and tested; the
  remaining obligation (usually an integration) has a strict xfail test.
- UNIMPLEMENTED: nothing in this slice; a strict xfail test holds the place.
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

TRACE = {
    "V2C-01": (
        "PASS",
        "control package imports no broker mutator, bridge, or LongHorizon code; no promote/checkpoint calls; no ref strings",
        ["test_control_machine::test_v2c_01_control_layer_cannot_touch_accepted_state"],
        None,
    ),
    "V2C-02": (
        "PARTIAL",
        "WorkOrder validator: no candidate or blocks before an approved plan; attach_candidate/begin_attempt state guards",
        ["test_control_machine::test_v2c_02_no_candidate_or_blocks_before_plan_approval"],
        "executor dispatch runs only through begin_attempt of an approved, executing WorkOrder",
    ),
    "V2C-03": (
        "PASS",
        "propose_plan versioning; approve_plan requires the latest, newer version; plan history append-only (check_evolution)",
        [
            "test_control_machine::test_v2c_03_plan_versions_are_immutable_and_reapproval_is_required",
            "test_control_machine::test_v2c_03_replan_cannot_change_a_done_block_and_keeps_superseded_evidence",
            "test_control_store::test_store_refuses_illegal_successors_even_when_built_directly",
        ],
        None,
    ),
    "V2C-04": (
        "PARTIAL",
        "WorkOrder validator: PROMOTED iff a promoted KernelOutcome; record_kernel_outcome requires an authoritative final audit",
        [
            "test_control_machine::test_v2c_04_promoted_only_from_a_promoted_kernel_outcome",
            "test_control_machine::test_v2c_04_promotion_needs_an_authoritative_final_audit_on_record",
        ],
        "KernelOutcome is built only from a real GatedPromotionResult",
    ),
    "V2C-05": (
        "PASS",
        "all blocks BLOCK_DONE only permits FINAL_VERIFICATION; validators forbid PROMOTED without the kernel",
        ["test_control_machine::test_v2c_05_code_approved_and_block_done_never_imply_acceptance"],
        None,
    ),
    "V2C-06": (
        "PARTIAL",
        "code_approval_problem(): passing checks, original VERIFIED code audit of the exact current state, in-scope diff or approved deviation; enforced by validator and approve_code",
        [
            "test_control_machine::test_v2c_06_07_code_approval_requires_every_condition",
            "test_control_machine::test_v2c_06_block_status_cannot_be_forged_past_code_approval",
            "test_control_machine::test_v2c_06_approved_deviation_allows_out_of_scope_changes",
        ],
        "test and change records are produced by deterministic runners and diff checks",
    ),
    "V2C-07": (
        "PASS",
        "AuditRecord.authoritative excludes repaired reports; used for code, memory, and final-audit gates",
        [
            "test_control_machine::test_v2c_06_07_code_approval_requires_every_condition",
            "test_control_machine::test_v2c_07_repaired_audits_never_approve_memory_or_final_verification",
        ],
        None,
    ),
    "V2C-08": (
        "UNIMPLEMENTED",
        "none in this slice (memory_paths are recorded per WorkOrder)",
        [],
        "Project Memory lives in tracked documents and is promoted with code",
    ),
    "V2C-09": (
        "PARTIAL",
        "curation only after CODE_APPROVED, only memory_curator, changes checked against memory_paths, Memory Audit required before the checkpoint",
        [
            "test_control_machine::test_v2c_09_curation_only_after_code_approved_and_only_by_the_curator",
            "test_control_machine::test_v2c_09_curator_changes_outside_memory_paths_escalate",
            "test_control_machine::test_v2c_09_memory_audit_is_required_before_the_checkpoint",
        ],
        "the curator's workspace writes are restricted to memory_paths at execution time",
    ),
    "V2C-10": (
        "UNIMPLEMENTED",
        "none in this slice",
        [],
        "Context Intake runs read-only and classifies memory claims with evidence",
    ),
    "V2C-11": (
        "PASS",
        "profile snapshot changes only via an approved change_agent amendment (decide, check_evolution); snapshot must be a stored approved version",
        [
            "test_control_machine::test_v2c_11_profile_snapshot_changes_only_by_an_approved_amendment",
            "test_control_store::test_v2c_11_store_refuses_a_profile_snapshot_change_without_amendment",
            "test_control_store::test_v2c_11_snapshot_must_be_a_stored_approved_profile",
        ],
        None,
    ),
    "V2C-12": (
        "PARTIAL",
        "_check_profile(): bound primary, or an approved fallback with a defined condition and evidence; every attempt recorded",
        [
            "test_control_machine::test_v2c_12_primary_is_used_and_fallbacks_need_a_defined_condition",
            "test_control_machine::test_v2c_12_auditors_must_be_the_bound_profile",
        ],
        "fallbacks are triggered only by classified runtime/provider failures or discovery",
    ),
    "V2C-13": (
        "UNIMPLEMENTED",
        "none in this slice (no Performance Memory or Jev integration)",
        [],
        "Performance Memory and Jev can only recommend, never select profiles",
    ),
    "V2C-14": (
        "UNIMPLEMENTED",
        "none in this slice",
        [],
        "the independence resolver enforces cumulative requirements per risk class",
    ),
    "V2C-15": (
        "PARTIAL",
        "record_deviation(): a material deviation always raises attention; curator out-of-path changes become material deviations",
        [
            "test_control_machine::test_v2c_15_material_deviation_always_escalates",
            "test_control_machine::test_v2c_09_curator_changes_outside_memory_paths_escalate",
        ],
        "deviations are detected from diffs, audit findings, and accounting",
    ),
    "V2C-16": (
        "PASS",
        "one open AttentionRequest merges all reasons; resume requires every blocking reason resolved or waived; decisions recorded",
        [
            "test_control_machine::test_v2c_16_all_active_reasons_together_and_resume_needs_them_resolved",
            "test_control_machine::test_v2c_16_attention_only_from_the_contract_states",
        ],
        None,
    ),
    "V2C-17": (
        "PARTIAL",
        "a non-promoted kernel outcome and baseline drift always raise attention",
        ["test_control_machine::test_v2c_17_kernel_refusal_and_drift_always_escalate"],
        "AUDITOR_ERROR beyond the fallback conditions is routed to attention",
    ),
    "V2C-18": (
        "PARTIAL",
        "Project Execution Profile versions immutable and sequential in the store; every attempt records the exact ProfileRef fingerprint",
        [
            "test_control_store::test_v2c_18_profile_versions_are_immutable_and_sequential",
            "test_control_machine::test_v2c_12_primary_is_used_and_fallbacks_need_a_defined_condition",
        ],
        "an ExecutionProfile registry (AgentProfile, DirectToolProfile, ...) with immutable versions",
    ),
    "V2C-19": (
        "PARTIAL",
        "BLOCK_DONE constructible only with a checkpoint proving the authoritative block state; prove_block_checkpoint is the only setter; mismatch escalates",
        [
            "test_control_machine::test_v2c_19_block_done_only_via_a_proven_checkpoint",
            "test_control_machine::test_v2c_19_candidate_change_after_the_audit_stops_the_block",
            "test_control_machine::test_v2c_19_block_done_is_the_only_function_that_sets_it",
            "test_control_store::test_reload_revalidates_and_rejects_tampered_rows",
        ],
        "the CheckpointProof is computed from immutable Git objects when the checkpoint is created",
    ),
    "V2C-20": (
        "PARTIAL",
        "no write-capable step outside EXECUTING; the final audit must be final_verifier",
        ["test_control_machine::test_v2c_20_final_verification_runs_no_write_capable_role"],
        "the final verification runner uses a fresh, read-only auditor",
    ),
    "V2C-21": (
        "PASS",
        "abort/defer keep candidate, blocks, attention; store is append-only with no delete; superseded blocks kept",
        [
            "test_control_machine::test_v2c_21_abort_and_defer_keep_evidence_and_candidate",
            "test_control_store::test_v2c_21_aborted_work_order_keeps_its_full_history",
            "test_control_store::test_store_implements_the_interface_and_has_no_delete",
        ],
        None,
    ),
    "V2C-22": (
        "PARTIAL",
        "drift checks at candidate attach, execution start, final verification, resume, and resume from deferral; planned baseline never rebased",
        ["test_control_machine::test_v2c_22_baseline_drift_is_never_silently_absorbed"],
        "the accepted baseline is observed from the Workspace Broker",
    ),
    "V2C-23": (
        "PASS",
        "SqliteControlStore.update: BEGIN IMMEDIATE + compare-and-swap on (id, version)",
        [
            "test_control_store::test_v2c_23_concurrent_writers_are_serialized_by_version",
            "test_control_store::test_v2c_23_stale_expected_version_is_refused",
        ],
        None,
    ),
}


def _contract_ids():
    text = (ROOT / "docs/13_V2_CONTROL_ARCHITECTURE.md").read_text(encoding="utf-8")
    return re.findall(r"\*\*(V2C-\d\d):\*\*", text)


def _doc_rows():
    text = (ROOT / "docs/14_V2C_TRACEABILITY.md").read_text(encoding="utf-8")
    return dict(
        re.findall(r"^\| (V2C-\d\d) \| (PASS|PARTIAL|UNIMPLEMENTED) \|", text, flags=re.MULTILINE)
    )


def test_every_contract_invariant_is_traced():
    ids = _contract_ids()
    assert ids == [f"V2C-{n:02d}" for n in range(1, 24)]
    assert list(TRACE) == ids
    assert _doc_rows() == {key: value[0] for key, value in TRACE.items()}


def test_doc_totals_match_the_matrix():
    text = (ROOT / "docs/14_V2C_TRACEABILITY.md").read_text(encoding="utf-8")
    counts = {
        status: sum(v[0] == status for v in TRACE.values())
        for status in ("PASS", "PARTIAL", "UNIMPLEMENTED")
    }
    remaining = sum(v[3] is not None for v in TRACE.values())
    expected = (
        f"**Totals:** {counts['PASS']} PASS, {counts['PARTIAL']} PARTIAL, "
        f"{counts['UNIMPLEMENTED']} UNIMPLEMENTED. There are {remaining} strict"
    )
    assert expected in text


def test_listed_tests_exist():
    import test_control_machine
    import test_control_store

    modules = {
        "test_control_machine": test_control_machine,
        "test_control_store": test_control_store,
    }
    for invariant, (status, _, tests, remaining) in TRACE.items():
        if status in ("PASS", "PARTIAL"):
            assert tests, invariant
        for entry in tests:
            module, name = entry.split("::")
            assert callable(getattr(modules[module], name, None)), f"{invariant}: {entry}"
        assert (remaining is None) == (status == "PASS"), invariant


REMAINING = [(key, value[3]) for key, value in TRACE.items() if value[3] is not None]


@pytest.mark.xfail(strict=True, reason="not implemented in the foundation slice")
@pytest.mark.parametrize("invariant,obligation", REMAINING, ids=[key for key, _ in REMAINING])
def test_remaining_obligation(invariant, obligation):
    pytest.fail(f"{invariant} remaining obligation not implemented: {obligation}")
