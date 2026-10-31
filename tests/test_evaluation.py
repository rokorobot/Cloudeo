"""EVAL-01 PR 2: contracts, runner, trial index and the five-case smoke suite.

Exit criteria (docs/EVAL-01_PLAN.md §5): cases run through production entry
points with fake external boundaries; repeated invocations cannot overwrite
trials; interrupted execution is recorded; fixtures do not leak state.
"""

import asyncio
import json
import os
import shutil
import sqlite3
import tempfile
from pathlib import Path

import pytest

from cloudeo.core import controller as controller_module
from cloudeo.core.validators import ValidationOutcome
from cloudeo.evaluation import scenarios
from cloudeo.evaluation.__main__ import main as cli
from cloudeo.evaluation.contracts import EvalCase
from cloudeo.evaluation.graders import grade_execution, grade_outcome
from cloudeo.evaluation.runner import DATA, ManifestError, capabilities, load_suite, run_suite
from cloudeo.evaluation.store import TrialStore

SUITE = "smoke-v1"
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
    path = data / "cases" / "direct-tool-verified-success.r1.json"
    case = json.loads(path.read_text())
    case["expected_state"]["response.status"] = "escalate"
    path.write_text(json.dumps(case))
    with pytest.raises(ManifestError, match="digest mismatch"):
        load_suite(SUITE, data)


def test_suite_pins_grader_versions(tmp_path):
    data = copy_data(tmp_path)
    path = data / "suites" / f"{SUITE}.json"
    suite = json.loads(path.read_text())
    suite["grader_versions"]["outcome-v1"] = "0"
    path.write_text(json.dumps(suite))
    with pytest.raises(ManifestError, match="pins graders"):
        load_suite(SUITE, data)


def test_shipped_manifests_validate_and_match_their_files():
    suite, cases = load_suite(SUITE)
    assert [c.id for c in cases] == [e.case_id for e in suite.cases]
    assert all(c.mode == "deterministic" and c.partition == "regression" for c in cases)


# --- Graders and a seeded regression ---


def case(case_id):
    return next(c for c in load_suite(SUITE)[1] if c.id == case_id)


def test_missing_observation_grades_unknown_never_pass():
    c = case("uhp-unknown-no-unsafe-retry")
    assert grade_outcome(c, {}).verdict == "unknown"
    assert grade_execution(c, {}).verdict == "unknown"


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
    path = DATA / "cases" / "direct-tool-verified-success.r1.json"
    assert cli(["digest", str(path)]) == 0
    assert capsys.readouterr().out.strip() == EvalCase.model_validate_json(path.read_text()).digest
