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

SUITE = "smoke-v3"
GATED = "post-audit-mutation-refused"  # needs the 'longhorizon' extra


def run(out, suite=None, **kwargs):
    """(run_id, trials); holdout counts are tested separately."""
    return asyncio.run(run_suite(suite or SUITE, out, **kwargs))[:2]


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
        # The real auditor episode runs; only the model behind HarnessRouter is faked.
        gated = by_case(trials)[GATED]
        assert gated.trace_completeness == "complete"
        assert gated.observations["audit.status"] == "VERIFIED"


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


def test_earlier_suite_versions_stay_loadable_and_unchanged():
    # smoke-v2 keeps the synthetic-auditor revision; smoke-v3 replaces only that case.
    v2, v3 = load_suite("smoke-v2"), load_suite("smoke-v3")
    revisions = {c.id: (a.revision, c.revision) for a, c in zip(v2[1], v3[1], strict=True)}
    assert revisions[GATED] == (2, 3)
    assert all(old == new for case_id, (old, new) in revisions.items() if case_id != GATED)


def test_the_real_auditor_decides_not_the_fixture(tmp_path):
    if not capabilities()["longhorizon"]:
        pytest.skip("the 'longhorizon' extra is not installed")
    fixture = case(GATED).fixture
    report = fixture["audit"]["report"].replace("Status: complete", "Status: incomplete")
    fixture = {**fixture, "audit": {**fixture["audit"], "report": report}}
    observations, _ = asyncio.run(
        scenarios.SCENARIOS[case(GATED).entry_point](fixture, tmp_path, scenarios.Recorder())
    )
    assert observations["audit.status"] == "NOT_VERIFIED"
    assert observations["gate.status"] == "NOT_VERIFIED"
    assert observations["accepted.unchanged"] and observations["checkpoint.refs_created"] == 0


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
        t, observations={**t.observations, "environment.exec_calls": 1}
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


# --- PR 4: corpus v1 and holdout plumbing ---

CORPUS = "corpus-v1"
UNOBSERVABLE = {"identity-actual-model-mismatch", "identity-reported-model-fallback"}
NEEDS_LH = {c.id for c in load_suite(CORPUS)[1] if "longhorizon" in c.required_capabilities}


def test_corpus_composition():
    suite, cases = load_suite(CORPUS)
    partitions = [c.partition for c in cases]
    assert len(cases) == 26 and len({c.id for c in cases}) == 26
    assert (partitions.count("regression"), partitions.count("capability")) == (18, 8)
    assert not any(e.holdout for e in suite.cases)  # added later by an independent author
    # Every case has an oracle of its own; critical cases are in the regression gate.
    assert all(c.expected_state for c in cases)
    assert any(c.severity == "critical" and c.partition == "regression" for c in cases)


def test_corpus_regression_passes_and_capability_gaps_stay_visible(tmp_path):
    _, trials = run(tmp_path, suite=CORPUS)
    has_lh = capabilities()["longhorizon"]
    for t in trials:
        if t.case_id in NEEDS_LH and not has_lh:
            assert t.status == "unsupported"
        elif t.provenance.partition == "regression":
            assert t.verdict == "pass", (t.case_id, t.outcome_grade, t.execution_grade)
        else:
            # A capability case that starts passing should be promoted to regression
            # in a new corpus version, like a strict xfail. Cases whose decision has
            # no Cloudeo consumer yet stay unknown, never pass.
            expected = "unknown" if t.case_id in UNOBSERVABLE else "fail"
            assert t.status == "completed" and t.verdict == expected, t.case_id


def test_capability_failures_do_not_fail_the_run_but_regressions_do(tmp_path, monkeypatch, capsys):
    assert cli(["run", "--suite", CORPUS, "--out", str(tmp_path / "a")]) == 0
    out = capsys.readouterr().out
    assert "regression: pass" in out and "capability: pass 0, fail 6, unknown 2" in out
    # An intentional policy defect: unknown runtime state treated as safe to re-run.
    monkeypatch.setattr(
        "cloudeo.orchestration.execution_failure.TERMINAL_OBSERVED",
        frozenset({"failed", "cancelled", "unknown"}),
    )
    assert cli(["run", "--suite", CORPUS, "--out", str(tmp_path / "b")]) == 1
    trial = by_case(TrialStore(tmp_path / "b").trials())["uhp-unknown-no-unsafe-retry"]
    assert trial.verdict == "fail"
    assert any("marked-safe-to-replay" in r for r in trial.execution_grade.reasons)


def holdout_setup(tmp_path, *, store_case=True):
    """A copy of the shipped data whose suite lists one holdout case by ID and digest."""
    data = copy_data(tmp_path)
    holdout = tmp_path / "restricted"
    source = case("direct-tool-verified-success").model_dump(mode="json")
    secret_case = EvalCase.model_validate(
        {**source, "id": "holdout-sample", "revision": 1, "partition": "holdout"}
    )
    if store_case:
        (holdout / "cases").mkdir(parents=True)
        (holdout / "cases" / "holdout-sample.r1.json").write_text(secret_case.model_dump_json())
    suite = json.loads((data / "suites" / f"{SUITE}.json").read_text())
    suite["id"] = "with-holdout"
    suite["cases"].append(
        {"case_id": "holdout-sample", "revision": 1, "case_digest": secret_case.digest,
         "holdout": True}
    )  # fmt: skip
    (data / "suites" / "with-holdout.json").write_text(json.dumps(suite))
    return data, holdout


def test_holdout_runs_only_from_restricted_storage_and_reports_counts(tmp_path):
    data, holdout = holdout_setup(tmp_path)
    run_id, trials, summary = asyncio.run(
        run_suite("with-holdout", tmp_path / "out", data=data, holdout=holdout)
    )
    assert "holdout-sample" not in {t.case_id for t in trials}
    assert not any("holdout-sample" in p.read_text() for p in (tmp_path / "out").rglob("*.json"))
    assert summary == {"cases": 1, "pass": 1, "fail": 0, "unknown": 0, "unavailable": 0}
    (held,) = TrialStore(holdout / "results").trials(run_id)
    assert held.case_id == "holdout-sample" and held.verdict == "pass"


def test_holdout_without_storage_is_unavailable_not_silently_dropped(tmp_path):
    data, _ = holdout_setup(tmp_path, store_case=False)
    _, trials, summary = asyncio.run(run_suite("with-holdout", tmp_path / "out", data=data))
    assert len(trials) == 5
    assert summary == {"cases": 1, "pass": 0, "fail": 0, "unknown": 0, "unavailable": 1}


def test_holdout_content_in_the_repository_is_refused(tmp_path):
    data, holdout = holdout_setup(tmp_path)
    shutil.copy(holdout / "cases" / "holdout-sample.r1.json", data / "cases")
    with pytest.raises(ManifestError, match="holdout content is in the repository"):
        load_suite("with-holdout", data, holdout)


def test_holdout_flag_and_case_partition_must_agree(tmp_path):
    data, holdout = holdout_setup(tmp_path)
    path = data / "suites" / f"{SUITE}.json"
    suite = json.loads(path.read_text())
    suite["cases"][0]["holdout"] = True
    path.write_text(json.dumps(suite))
    shutil.move(data / "cases" / "direct-tool-verified-success.r2.json", holdout / "cases")
    with pytest.raises(ManifestError, match="partition and manifest holdout flag disagree"):
        load_suite(SUITE, data, holdout)


def test_cli_prints_only_holdout_counts(tmp_path, monkeypatch, capsys):
    data, holdout = holdout_setup(tmp_path)
    monkeypatch.setattr("cloudeo.evaluation.runner.DATA", data)
    monkeypatch.setenv("CLOUDEO_EVAL_HOLDOUT_DIR", str(holdout))
    real = run_suite

    async def with_data(*args, **kwargs):
        return await real(*args, data=data, **kwargs)

    monkeypatch.setattr("cloudeo.evaluation.__main__.run_suite", with_data)
    assert cli(["run", "--suite", "with-holdout", "--out", str(tmp_path / "out")]) == 0
    out = capsys.readouterr().out
    assert "holdout: cases 1, pass 1" in out and "holdout-sample" not in out


def test_capability_cases_cannot_pass_without_their_control_entry_point(tmp_path):
    # Even with the desired behavior, a raw-dispatch run lacks the control decision
    # the case requires, so it grades unknown until the case is revised.
    trial = by_case(run(tmp_path, suite=CORPUS)[1])["rate-limited-retry-within-policy"]
    desired = {**trial.observations, "outcome.status": "completed", "uhp.task_posts": 2}
    c = next(c for c in load_suite(CORPUS)[1] if c.id == trial.case_id)
    assert grade_outcome(c, recorded(trial, observations=desired)).verdict == "unknown"
