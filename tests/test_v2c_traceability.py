"""V2C traceability: every contract invariant has exactly one status.

- ENFORCED: a guard exists in this slice, with passing positive tests and at
  least one negative test proving the prohibited state or transition is
  rejected.
- DEFERRED: the contract obligation belongs to a later milestone. It is held by
  a strict xfail test whose reason names the invariant, so an unexpected pass
  (XPASS) fails CI until this record is deliberately updated. Guards this slice
  already provides are listed as supporting evidence; they do not make the
  invariant ENFORCED.
- NOT_APPLICABLE: only if the accepted contract makes the invariant irrelevant
  to this layer, with a written reason. (None today.)
"""

import inspect
import re
from pathlib import Path

import pytest
import test_control_machine
import test_control_store

ROOT = Path(__file__).resolve().parents[1]
STATUSES = ("ENFORCED", "DEFERRED", "NOT_APPLICABLE")
MODULES = {"test_control_machine": test_control_machine, "test_control_store": test_control_store}
MACHINE = "test_control_machine::"
STORE = "test_control_store::"


def enforced(guard, positive, negative):
    return {"status": "ENFORCED", "guard": guard, "positive": positive, "negative": negative}


def deferred(obligation, supporting=()):
    return {"status": "DEFERRED", "obligation": obligation, "supporting": list(supporting)}


TRACE = {
    "V2C-01": enforced(
        "the control package imports no broker mutator, bridge, LongHorizon code, or subprocess; "
        "no promote/checkpoint/reject/cleanup calls; no ref strings",
        [MACHINE + "test_v2c_01_control_layer_cannot_touch_accepted_state"],
        [MACHINE + "test_v2c_01_k1_checker_flags_forbidden_access"],
    ),
    "V2C-02": deferred(
        "no workspace write happens before an approved plan: executor dispatch runs only through "
        "begin_attempt of an approved, executing WorkOrder",
        [MACHINE + "test_v2c_02_no_candidate_or_blocks_before_plan_approval"],
    ),
    "V2C-03": enforced(
        "sequential immutable plan versions; approval only of the latest, newer version; "
        "append-only plan history (check_evolution)",
        [MACHINE + "test_v2c_03_plan_versions_are_immutable_and_reapproval_is_required"],
        [
            MACHINE + "test_v2c_03_plan_versions_are_immutable_and_reapproval_is_required",
            STORE + "test_store_refuses_illegal_successors_even_when_built_directly",
        ],
    ),
    "V2C-04": deferred(
        "PROMOTED only from a real trust-kernel result: KernelOutcome is built from a GatedPromotionResult",
        [
            MACHINE + "test_v2c_04_promoted_only_from_a_promoted_kernel_outcome",
            MACHINE + "test_v2c_04_promotion_needs_an_authoritative_final_audit_on_record",
        ],
    ),
    "V2C-05": enforced(
        "all blocks BLOCK_DONE only permits FINAL_VERIFICATION; validators forbid PROMOTED without "
        "a promoted kernel outcome",
        [MACHINE + "test_happy_path_reaches_promoted_only_through_every_state"],
        [MACHINE + "test_v2c_05_code_approved_and_block_done_never_imply_acceptance"],
    ),
    "V2C-06": deferred(
        "CODE_APPROVED evidence (checks, scope diff) is produced by deterministic runners and diff checks",
        [
            MACHINE + "test_v2c_06_07_code_approval_requires_every_condition",
            MACHINE + "test_v2c_06_block_status_cannot_be_forged_past_code_approval",
            MACHINE + "test_v2c_06_approved_deviation_allows_out_of_scope_changes",
        ],
    ),
    "V2C-07": enforced(
        "AuditRecord.authoritative excludes repaired reports and gates code, memory, and final audits",
        [MACHINE + "test_happy_path_reaches_promoted_only_through_every_state"],
        [
            MACHINE + "test_v2c_06_07_code_approval_requires_every_condition",
            MACHINE + "test_v2c_07_repaired_audits_never_approve_memory_or_final_verification",
        ],
    ),
    "V2C-08": deferred("Project Memory lives in tracked documents and is promoted with code"),
    "V2C-09": deferred(
        "the curator's workspace writes are restricted to memory_paths at execution time",
        [
            MACHINE + "test_v2c_09_curation_only_after_code_approved_and_only_by_the_curator",
            MACHINE + "test_v2c_09_curator_changes_outside_memory_paths_escalate",
            MACHINE + "test_v2c_09_memory_audit_is_required_before_the_checkpoint",
        ],
    ),
    "V2C-10": deferred("Context Intake runs read-only and classifies memory claims with evidence"),
    "V2C-11": enforced(
        "the profile snapshot changes only through an approved change_agent amendment; the snapshot "
        "must be a stored, approved version",
        [MACHINE + "test_v2c_11_profile_snapshot_changes_only_by_an_approved_amendment"],
        [
            MACHINE + "test_v2c_11_profile_snapshot_changes_only_by_an_approved_amendment",
            STORE + "test_v2c_11_store_refuses_a_profile_snapshot_change_without_amendment",
            STORE + "test_v2c_11_snapshot_must_be_a_stored_approved_profile",
        ],
    ),
    "V2C-12": deferred(
        "fallbacks are triggered only by classified runtime/provider failures or discovery",
        [
            MACHINE + "test_v2c_12_primary_is_used_and_fallbacks_need_a_defined_condition",
            MACHINE + "test_v2c_12_auditors_must_be_the_bound_profile",
        ],
    ),
    "V2C-13": deferred("Performance Memory and Jev can only recommend, never select profiles"),
    "V2C-14": deferred("the independence resolver enforces cumulative requirements per risk class"),
    "V2C-15": deferred(
        "material deviations are detected from diffs, audit findings, and accounting",
        [
            MACHINE + "test_v2c_15_material_deviation_always_escalates",
            MACHINE + "test_v2c_09_curator_changes_outside_memory_paths_escalate",
        ],
    ),
    "V2C-16": enforced(
        "one open attention request merges every reason; resume requires each blocking reason "
        "resolved or waived; decisions recorded",
        [MACHINE + "test_v2c_16_all_active_reasons_together_and_resume_needs_them_resolved"],
        [
            MACHINE + "test_v2c_16_all_active_reasons_together_and_resume_needs_them_resolved",
            MACHINE + "test_v2c_16_attention_only_from_the_contract_states",
        ],
    ),
    "V2C-17": deferred(
        "AUDITOR_ERROR beyond the fallback conditions is routed to attention",
        [MACHINE + "test_v2c_17_kernel_refusal_and_drift_always_escalate"],
    ),
    "V2C-18": deferred(
        "an ExecutionProfile registry (AgentProfile, DirectToolProfile, ...) with immutable versions",
        [
            STORE + "test_v2c_18_profile_versions_are_immutable_and_sequential",
            STORE + "test_v2c_18_canonical_profile_hash_is_stable_across_processes",
            MACHINE + "test_v2c_12_primary_is_used_and_fallbacks_need_a_defined_condition",
        ],
    ),
    "V2C-19": deferred(
        "the checkpoint subsystem supplies the CheckpointProof from immutable Git objects",
        [
            MACHINE + "test_v2c_19_block_done_only_via_a_proven_checkpoint",
            MACHINE + "test_v2c_19_candidate_change_after_the_audit_stops_the_block",
            MACHINE + "test_v2c_19_block_done_is_the_only_function_that_sets_it",
            STORE + "test_reload_revalidates_and_rejects_tampered_rows",
        ],
    ),
    "V2C-20": deferred(
        "the final verification runner uses a fresh, read-only auditor",
        [MACHINE + "test_v2c_20_final_verification_runs_no_write_capable_role"],
    ),
    "V2C-21": enforced(
        "abort/defer keep candidate, blocks, and attention; append-only store with no delete; "
        "history cannot be erased; superseded blocks kept",
        [
            MACHINE + "test_v2c_21_abort_and_defer_keep_evidence_and_candidate",
            STORE + "test_v2c_21_aborted_work_order_keeps_its_full_history",
        ],
        [STORE + "test_v2c_21_history_cannot_be_removed"],
    ),
    "V2C-22": deferred(
        "the accepted baseline is observed from the Workspace Broker",
        [MACHINE + "test_v2c_22_baseline_drift_is_never_silently_absorbed"],
    ),
    "V2C-23": enforced(
        "SqliteControlStore.update: BEGIN IMMEDIATE, expected-version check, revalidation, "
        "check_evolution, and a version-conditioned UPDATE; conflicts are never resolved by the store",
        [STORE + "test_reload_is_deterministic_and_replays_every_version"],
        [
            STORE + "test_v2c_23_concurrent_writers_are_serialized_by_version",
            STORE + "test_v2c_23_stale_expected_version_is_refused",
        ],
    ),
}


def _test(entry):
    module, name = entry.split("::")
    return getattr(MODULES[module], name, None)


def _deferred_params():
    return [
        pytest.param(
            key,
            value["obligation"],
            id=key,
            marks=pytest.mark.xfail(strict=True, reason=f"{key} deferred: {value['obligation']}"),
        )
        for key, value in TRACE.items()
        if value["status"] == "DEFERRED"
    ]


DEFERRED_PARAMS = _deferred_params()


@pytest.mark.parametrize("invariant,obligation", DEFERRED_PARAMS)
def test_deferred_obligation(invariant, obligation):
    pytest.fail(f"{invariant} is deferred to a later milestone: {obligation}")


# --- Meta-tests ---


def test_every_contract_invariant_is_traced_once():
    text = (ROOT / "docs/13_V2_CONTROL_ARCHITECTURE.md").read_text(encoding="utf-8")
    ids = re.findall(r"\*\*(V2C-\d\d):\*\*", text)
    assert ids == [f"V2C-{n:02d}" for n in range(1, 24)]
    assert list(TRACE) == ids
    for key, value in TRACE.items():
        assert value["status"] in STATUSES, key


def test_every_invariant_has_named_test_obligations_that_exist():
    for key, value in TRACE.items():
        named = [
            *value.get("positive", []),
            *value.get("negative", []),
            *value.get("supporting", []),
        ]
        if value["status"] == "ENFORCED":
            assert value["positive"] and value["negative"], key
            assert "obligation" not in value, key
        elif value["status"] == "DEFERRED":
            assert value["obligation"], key  # held by test_deferred_obligation[key]
        else:
            assert value.get("reason"), f"{key}: NOT_APPLICABLE needs a written reason"
            assert named, key
        for entry in named:
            assert callable(_test(entry)), f"{key}: {entry} does not exist"


def test_every_deferred_obligation_is_strict_xfail_naming_its_invariant():
    by_id = {param.values[0]: param for param in DEFERRED_PARAMS}
    deferred_ids = [k for k, v in TRACE.items() if v["status"] == "DEFERRED"]
    assert sorted(by_id) == sorted(deferred_ids)
    for key in deferred_ids:
        marks = [m for m in by_id[key].marks if m.name == "xfail"]
        assert len(marks) == 1, key
        assert marks[0].kwargs.get("strict") is True, key
        assert key in marks[0].kwargs.get("reason", ""), key


REJECTION = ("pytest.raises(", "USER_ATTENTION_REQUIRED", "k1_violations(")


def test_every_enforced_invariant_has_a_real_negative_test():
    for key, value in TRACE.items():
        if value["status"] != "ENFORCED":
            continue
        for entry in value["negative"]:
            function = _test(entry)
            marks = {m.name for m in getattr(function, "pytestmark", [])}
            assert "negative" in marks, f"{key}: {entry} is not marked negative"
            source = inspect.getsource(function)
            assert any(r in source for r in REJECTION), f"{key}: {entry} asserts no rejection"


def test_doc_matches_the_matrix():
    text = (ROOT / "docs/14_V2C_TRACEABILITY.md").read_text(encoding="utf-8")
    rows = dict(
        re.findall(r"^\| (V2C-\d\d) \| (ENFORCED|DEFERRED|NOT_APPLICABLE) \|", text, re.MULTILINE)
    )
    assert rows == {key: value["status"] for key, value in TRACE.items()}
    counts = {s: sum(v["status"] == s for v in TRACE.values()) for s in STATUSES}
    expected = (
        f"**Totals:** {counts['ENFORCED']} ENFORCED, {counts['DEFERRED']} DEFERRED, "
        f"{counts['NOT_APPLICABLE']} NOT_APPLICABLE; {len(DEFERRED_PARAMS)} strict"
    )
    assert expected in text
    assert "TODO" not in text


def test_block_done_has_no_generic_setter():
    """ADR-026: no mark_block_done(); only the proven-checkpoint path."""
    from cloudeo.control import machine

    public = [
        name
        for name, _ in inspect.getmembers(machine, inspect.isfunction)
        if not name.startswith("_") and inspect.getmodule(getattr(machine, name)) is machine
    ]
    assert not [n for n in public if "done" in n.lower() or "set_status" in n.lower()]
    setters = [n for n in public if "status=B.BLOCK_DONE" in inspect.getsource(getattr(machine, n))]
    assert setters == ["prove_block_checkpoint"]
