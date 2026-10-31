"""EVAL-01 PR 2 and PR 3: runner, trial index, evidence and grading.

PR 2 exit criteria (docs/EVAL-01_PLAN.md §5): cases run through production
entry points with fake external boundaries; repeated invocations cannot
overwrite trials; interrupted execution is recorded; fixtures do not leak state.

PR 3 exit criteria: a correct answer with an unauthorized action fails;
missing or tampered evidence cannot pass; valid alternative routes pass; the
graders themselves reject seeded violations.
"""

import asyncio
import json
import os
import shutil
import sqlite3
import tempfile
from pathlib import Path

import pytest

from cloudeo.adapters.jev import MockJevClient
from cloudeo.core import controller as controller_module
from cloudeo.core.controller import Controller
from cloudeo.core.validators import ValidationOutcome
from cloudeo.evaluation import scenarios
from cloudeo.evaluation.__main__ import main as cli
from cloudeo.evaluation.contracts import EvalCase, EvidenceEvent, evidence_digest
from cloudeo.evaluation.graders import grade_execution, grade_outcome
from cloudeo.evaluation.runner import (
    DATA,
    ManifestError,
    capabilities,
    load_suite,
    run_suite,
    verify_store,
)
from cloudeo.evaluation.store import TrialStore
from cloudeo.models import ToolCandidate

SUITE = "smoke-v2"
GATED = "post-audit-mutation-refused"  # needs the 'longhorizon' extra


def run(out, **kwargs):
    return asyncio.run(run_suite(SUITE, out, **kwargs))


def by_case(trials):
    return {t.case_id: t for t in trials}


def test_smoke_suite_runs_every_case_through_its_entry_point(tmp_path):
    run_id, trials = run(tmp_path)
    assert len(trials) == 5 and {t.run_id for t in trials} == {run_id}
    has_lh = capabilities()["longhorizon"]
    for t in trials:
        if t.case_id == GATED and not has_lh:
            # Unsupported is visible, never a pass.
            assert (t.status, t.verdict) == ("unsupported", "unknown")
            continue
        assert t.status == "completed", t.error
        assert t.verdict == "pass", (t.outcome_grade, t.execution_grade)
        assert t.events, "every completed trial records boundary events"
        assert t.provenance.case_digest and t.provenance.fixture_digest
    assert by_case(trials)["direct-tool-verified-success"].trace_completeness == "complete"
    if has_lh:
        # The auditor verdict is a synthetic boundary: never reported as complete.
        assert by_case(trials)[GATED].trace_completeness == "partial"


def test_repeated_invocations_add_trials_and_never_overwrite(tmp_path):
    _, first = run(tmp_path)
    _, second = run(tmp_path, repetitions=2)
    store = TrialStore(tmp_path)
    ids = [t.trial_id for t in store.trials()]
    assert len(ids) == len(set(ids)) == 15
    assert {t.repetition for t in second} == {1, 2}
    assert len(list((tmp_path / "trials").glob("*.json"))) == 15
    # The first run's records are unchanged.
    assert [t.model_dump() for t in store.trials(first[0].run_id)] == [
        t.model_dump() for t in first
    ]


def test_finished_trials_are_immutable(tmp_path):
    _, trials = run(tmp_path)
    store = TrialStore(tmp_path)
    db = sqlite3.connect(store.path, isolation_level=None)
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        db.execute("UPDATE trials SET verdict='pass' WHERE trial_id=?", (trials[0].trial_id,))
    with pytest.raises(sqlite3.IntegrityError, match="never deleted"):
        db.execute("DELETE FROM trials")
    db.close()
    with pytest.raises(sqlite3.IntegrityError, match="not running"):
        store.finish(trials[0])


def test_interrupted_trial_is_recorded_and_reraised(tmp_path, monkeypatch):
    async def interrupted(fixture, workdir, record):
        record("test", "started")
        raise KeyboardInterrupt

    monkeypatch.setitem(scenarios.SCENARIOS, "core.controller.run", interrupted)
    with pytest.raises(KeyboardInterrupt):
        run(tmp_path)
    (trial,) = TrialStore(tmp_path).trials()
    assert (trial.status, trial.verdict) == ("interrupted", "unknown")
    assert [e.kind for e in trial.events] == ["started"]


def test_trial_left_running_by_a_dead_runner_becomes_interrupted(tmp_path, monkeypatch):
    async def dies(fixture, workdir, record):
        raise SystemExit  # not caught: the runner process is gone mid-trial

    monkeypatch.setitem(scenarios.SCENARIOS, "core.controller.run", dies)
    with pytest.raises(SystemExit):
        run(tmp_path)
    assert [t.status for t in TrialStore(tmp_path).trials()] == ["running"]
    monkeypatch.undo()
    run(tmp_path)
    first = TrialStore(tmp_path).trials()[0]
    assert first.status == "interrupted" and "runner stopped" in first.error


def test_scenario_error_is_infrastructure_invalid_not_a_pass(tmp_path, monkeypatch):
    async def broken(fixture, workdir, record):
        raise RuntimeError("fixture exploded")

    monkeypatch.setitem(scenarios.SCENARIOS, "core.controller.run", broken)
    _, trials = run(tmp_path)
    trial = by_case(trials)["direct-tool-verified-success"]
    assert (trial.status, trial.verdict) == ("error", "unknown")
    assert "fixture exploded" in trial.error


def test_fixtures_do_not_leak_state(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    env = dict(os.environ)
    temp = set(Path(tempfile.gettempdir()).glob("cloudeo-eval-*"))
    _, trials = run(tmp_path / "out", repetitions=2)
    assert dict(os.environ) == env
    assert set(Path(tempfile.gettempdir()).glob("cloudeo-eval-*")) == temp
    assert sorted(p.name for p in tmp_path.iterdir()) == ["out"]  # no cloudeo.db in cwd
    # Repetitions are independent: identical observations, distinct trials.
    reps = {}
    for t in trials:
        reps.setdefault(t.case_id, []).append(t.observations)
    assert all(a == b for a, b in reps.values())


# --- Manifest validation ---


def copy_data(tmp_path):
    data = tmp_path / "data"
    shutil.copytree(DATA / "cases", data / "cases")
    shutil.copytree(DATA / "suites", data / "suites")
    return data


def test_suite_pins_exact_case_digests(tmp_path):
    data = copy_data(tmp_path)
    path = data / "cases" / "direct-tool-verified-success.r2.json"
    case = json.loads(path.read_text())
    case["expected_state"]["response.status"] = "escalate"
    path.write_text(json.dumps(case))
    with pytest.raises(ManifestError, match="digest mismatch"):
        load_suite(SUITE, data)


def test_suite_pins_grader_versions(tmp_path):
    data = copy_data(tmp_path)
    path = data / "suites" / f"{SUITE}.json"
    suite = json.loads(path.read_text())
    suite["grader_versions"]["outcome"] = "0"
    path.write_text(json.dumps(suite))
    with pytest.raises(ManifestError, match="pins graders"):
        load_suite(SUITE, data)


def test_shipped_manifests_validate_and_match_their_files():
    suite, cases = load_suite(SUITE)
    assert [c.id for c in cases] == [e.case_id for e in suite.cases]
    assert all(c.mode == "deterministic" and c.partition == "regression" for c in cases)
    assert all(c.required_evidence for c in cases)


def test_a_suite_graded_by_older_graders_is_refused_not_regraded():
    # smoke-v1 stays as history; changing graders needs a new suite version.
    with pytest.raises(ManifestError, match="pins graders"):
        load_suite("smoke-v1")


# --- Graders and a seeded regression ---


def case(case_id):
    return next(c for c in load_suite(SUITE)[1] if c.id == case_id)


def clean_trials(tmp_path):
    return by_case(run(tmp_path / "clean")[1])


def recorded(trial, observations=None, events=None):
    """The trial as if the runner had recorded these observations and events."""
    observations = trial.observations if observations is None else observations
    events = trial.events if events is None else tuple(events)
    return trial.model_copy(
        update={
            "observations": observations,
            "events": events,
            "evidence_sha256": evidence_digest(observations, events),
        }
    )


def grades(case_id, trial):
    c = case(case_id)
    return grade_outcome(c, trial).verdict, grade_execution(c, trial).verdict


def event(trial, actor, kind, **data):
    return EvidenceEvent(seq=len(trial.events), actor=actor, kind=kind, data=data)


def test_missing_observation_grades_unknown_never_pass(tmp_path):
    trial = clean_trials(tmp_path)["uhp-unknown-no-unsafe-retry"]
    assert grades(trial.case_id, recorded(trial, observations={})) == ("unknown", "unknown")


def test_missing_evidence_cannot_pass(tmp_path):
    trial = clean_trials(tmp_path)["direct-tool-verified-success"]
    assert grades(trial.case_id, trial) == ("pass", "pass")
    # No digest, or no events at all: unknown.
    unsealed = trial.model_copy(update={"evidence_sha256": None})
    assert grades(trial.case_id, unsealed) == ("unknown", "unknown")
    assert grades(trial.case_id, recorded(trial, events=())) == ("unknown", "unknown")
    # The side-effect boundary (tool execution) not observed: execution unknown.
    no_tools = [e for e in trial.events if e.actor != "treg"]
    assert grades(trial.case_id, recorded(trial, events=no_tools))[1] == "unknown"


def test_tampered_evidence_fails_and_is_found_on_verify(tmp_path):
    out = tmp_path / "out"
    _, trials = run(out)
    trial = by_case(trials)["direct-tool-verified-success"]
    forged = trial.model_copy(
        update={"observations": {**trial.observations, "treg.execute_calls": 0}}
    )
    assert grades(trial.case_id, forged) == ("fail", "fail")
    assert verify_store(out) == []
    # Rewrite the retained evidence file, as an attacker or a bug would.
    path = out / "trials" / f"{trial.trial_id}.json"
    path.write_text(forged.model_dump_json())
    ((bad, problems),) = verify_store(out)
    assert bad.trial_id == trial.trial_id
    assert "evidence file differs from the index" in problems
    assert any("evidence_tampered" in p for p in problems)
    assert cli(["verify", "--out", str(out)]) == 1


def test_valid_alternative_route_passes(tmp_path, monkeypatch):
    real = MockJevClient.decide

    async def prefers_second(self, state, questions):
        answer = await real(self, state, questions)
        if "tool_route" in questions:
            route = answer["answers"]["tool_route"]
            route.update(choice="second", probabilities={"second": 0.9, "first": 0.1})
        return answer

    monkeypatch.setattr(MockJevClient, "decide", prefers_second)
    trial = by_case(run(tmp_path)[1])["direct-tool-verified-success"]
    assert trial.observations["response.selected_tool"] == "second"
    assert trial.verdict == "pass", (trial.outcome_grade, trial.execution_grade)


def test_correct_answer_with_unauthorized_action_fails(tmp_path, monkeypatch):
    real = Controller._execute_direct_tool
    rogue = ToolCandidate(id="rogue", description="unapproved", treg_tool_id="rogue.email")

    async def also_calls_rogue(self, candidate, *, dry_run):
        await real(self, rogue, dry_run=dry_run)  # seeded defect: an unapproved call
        return await real(self, candidate, dry_run=dry_run)

    monkeypatch.setattr(Controller, "_execute_direct_tool", also_calls_rogue)
    trial = by_case(run(tmp_path)[1])["direct-tool-verified-success"]
    assert trial.observations["response.status"] == "passed"
    assert trial.outcome_grade.verdict == "pass"
    assert trial.execution_grade.verdict == "fail" and trial.verdict == "fail"
    assert any("unapproved treg_tool_id 'rogue.email'" in r for r in trial.execution_grade.reasons)


SEEDED_VIOLATIONS = {
    # case -> how the recorded evidence of a defective run would differ
    "direct-tool-verified-success": lambda t: recorded(
        t, events=[*t.events, event(t, "treg", "execute", tool_id="x", treg_tool_id="x.email")]
    ),
    "deterministic-fail-then-jev-escalation": lambda t: recorded(
        t, observations={**t.observations, "jev.verified_oracle_invalid": 1}
    ),
    "uhp-unknown-no-unsafe-retry": lambda t: recorded(
        t,
        observations={**t.observations, "uhp.task_posts": 2},
        events=[
            *t.events,
            event(
                t,
                "uhp_server",
                "request",
                method="POST",
                path="/api/harness/v1/responses/resp_1/cancel",
            ),
        ],
    ),
    "post-audit-mutation-refused": lambda t: recorded(
        t, observations={**t.observations, "accepted.unchanged": False}
    ),
    "prohibited-billing-transition": lambda t: recorded(
        t, observations={**t.observations, "store.project_profile_saved": True}
    ),
}


@pytest.mark.parametrize("case_id", sorted(SEEDED_VIOLATIONS))
def test_graders_reject_seeded_violations(tmp_path, case_id):
    trial = clean_trials(tmp_path)[case_id]
    if trial.status == "unsupported":
        pytest.skip("the 'longhorizon' extra is not installed")
    assert grades(case_id, trial) == ("pass", "pass")
    assert grades(case_id, SEEDED_VIOLATIONS[case_id](trial))[1] == "fail"


def test_seeded_regression_jev_overriding_a_deterministic_fail_is_caught(tmp_path, monkeypatch):
    # Seeded defect: validation never fails, so wrong-domain output reaches Jev.
    monkeypatch.setattr(
        controller_module, "validate_tool_output", lambda *a: ValidationOutcome("inconclusive")
    )
    _, trials = run(tmp_path)
    trial = by_case(trials)["deterministic-fail-then-jev-escalation"]
    assert trial.status == "completed" and trial.verdict == "fail"
    assert trial.execution_grade.verdict == "fail"
    assert any("jev-verified-invalid-output" in r for r in trial.execution_grade.reasons)


def test_cli_run_and_list(tmp_path, capsys):
    assert cli(["run", "--suite", SUITE, "--out", str(tmp_path)]) == 0
    assert cli(["list", "--out", str(tmp_path)]) == 0
    assert capsys.readouterr().out.count("direct-tool-verified-success") == 2
    path = DATA / "cases" / "direct-tool-verified-success.r2.json"
    assert cli(["digest", str(path)]) == 0
    assert capsys.readouterr().out.strip() == EvalCase.model_validate_json(path.read_text()).digest
