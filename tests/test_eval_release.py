"""EVAL-01 PR 6c: baseline pointer and release gate.

Exit criteria (docs/EVAL-01_PLAN.md §5, PR 6): a seeded critical regression
blocks; missing required evidence blocks; a failed evaluation leaves the prior
release baseline active; rollback is moving the pointer back.
"""

import asyncio
import json
import shutil

import pytest

from cloudeo.evaluation import compare as cmp
from cloudeo.evaluation import release
from cloudeo.evaluation.__main__ import main as cli
from cloudeo.evaluation.contracts import EvalConfiguration

COMMIT = "a" * 40
CONFIGS = cmp.DATA / "configurations"


def config(name):
    return EvalConfiguration.model_validate_json((CONFIGS / f"{name}.json").read_text())


@pytest.fixture(scope="module")
def judged(tmp_path_factory):
    """A real offline comparison judged by thresholds-v1, forced to a pass verdict."""
    out = tmp_path_factory.mktemp("cmp")
    mp = pytest.MonkeyPatch()
    mp.setattr(cmp, "_code_state", lambda: (COMMIT, False, None))
    try:
        c = asyncio.run(
            cmp.run_comparison(
                "smoke-v3", config("opus-5-5"), config("gpt-5-6"), out, repetitions=1,
                run_cap_usd=7.0, week_cap_usd=20.0, ledger=cmp.Ledger(out / "l.jsonl"), seed=1,
                thresholds=cmp.load_thresholds(cmp.THRESHOLDS / "thresholds-v1.json"),
            )
        )  # fmt: skip
    finally:
        mp.undo()
    assert c.gate_verdict == "inconclusive"  # five offline cases cannot pass for real
    return c.model_copy(update={"gate_verdict": "pass", "gate_reasons": ("forced",)})


THRESHOLDS = cmp.load_thresholds(cmp.THRESHOLDS / "thresholds-v1.json")
GATE = {"verdict": "pass", "code_commit": COMMIT, "code_dirty": False, "fail_reasons": []}
HOLDOUT = {"code_commit": COMMIT, "code_dirty": False,
           "holdout": {"cases": 4, "pass": 4, "fail": 0, "unknown": 0, "unavailable": 0,
                       "critical_violations": 0}}  # fmt: skip


def decide(comparison, *, gate=None, holdout=HOLDOUT, reason=None, thresholds=THRESHOLDS):
    return release.decide(comparison, thresholds, gate or GATE, holdout, reason, release.current())


def test_the_shipped_pointer_names_an_intact_initial_record():
    record = release.current()
    assert (record.id, record.basis, record.configuration_id) == ("b0001", "initial", "opus-5-5")
    assert release.configuration(record).id == "opus-5-5"
    # Every record's predecessor exists, so rollback always has somewhere to go.
    for path in sorted(release.BASELINES.glob("b*.json")):
        r = release.load_record(path.stem)
        assert r.id == path.stem and (r.previous is None or release.load_record(r.previous))


def test_everything_in_order_passes(judged):
    assert decide(judged) == ("pass", [], [])
    assert decide(judged, holdout=None, reason="holdout org not set up yet")[0] == "pass"


@pytest.mark.parametrize(
    "change, verdict, reason",
    [
        ({"gate_verdict": "fail", "gate_reasons": ("drop",)}, "fail", "comparison failed: drop"),
        ({"gate_verdict": "inconclusive"}, "blocked", "comparison is inconclusive"),
        ({"gate_verdict": "observational", "thresholds_digest": None}, "blocked", "observational"),
        ({"thresholds_digest": "0" * 64}, "blocked", "was judged against"),
        ({"code_dirty": True}, "blocked", "unknown or dirty"),
        ({"code_commit": None}, "blocked", "unknown or dirty"),
    ],
)
def test_comparison_problems(judged, change, verdict, reason):
    v, failed, blocked = decide(judged.model_copy(update=change))
    assert v == verdict and any(reason in r for r in failed + blocked), failed + blocked


def test_the_comparison_must_be_against_the_current_baseline(judged):
    swapped = judged.model_copy(update={"baseline": config("gpt-5-6")})
    v, _, blocked = decide(swapped)
    assert v == "blocked" and any("current baseline b0001 is opus-5-5" in r for r in blocked)


@pytest.mark.parametrize(
    "gate, verdict, reason",
    [
        ({**GATE, "verdict": "fail", "fail_reasons": ["x#1"]}, "fail", "regression gate failed"),
        ({**GATE, "verdict": "blocked"}, "blocked", "regression gate is blocked"),
        ({**GATE, "code_commit": "b" * 40}, "blocked", "regression gate ran on bbbb"),
    ],
)
def test_regression_gate_problems(judged, gate, verdict, reason):
    v, failed, blocked = decide(judged, gate=gate)
    assert v == verdict and any(reason in r for r in failed + blocked), failed + blocked


@pytest.mark.parametrize(
    "holdout, reason, verdict, why",
    [
        (None, None, "blocked", "no owner-recorded reason"),
        ({**HOLDOUT, "holdout": {**HOLDOUT["holdout"], "critical_violations": 1}}, None, "fail",
         "holdout: 1 critical violation"),
        ({**HOLDOUT, "holdout": {**HOLDOUT["holdout"], "unknown": 1}}, None, "blocked",
         "holdout: 1 unknown"),
        ({**HOLDOUT, "holdout": {**HOLDOUT["holdout"], "unavailable": 4}}, None, "blocked",
         "holdout: 4 unavailable"),
        ({**HOLDOUT, "holdout": {"cases": 0}}, None, "blocked", "no holdout cases"),
        ({**HOLDOUT, "code_commit": "c" * 40}, None, "blocked", "holdout report ran on cccc"),
    ],
)  # fmt: skip
def test_holdout_problems(judged, holdout, reason, verdict, why):
    v, failed, blocked = decide(judged, holdout=holdout, reason=reason)
    assert v == verdict and any(why in r for r in failed + blocked), failed + blocked


def cli_files(tmp_path, comparison, gate=GATE):
    (tmp_path / "c.json").write_text(comparison.model_dump_json())
    (tmp_path / "g.json").write_text(json.dumps(gate))
    (tmp_path / "h.json").write_text(json.dumps(HOLDOUT))
    return ["release-gate", "--comparison", str(tmp_path / "c.json"),
            "--gate-report", str(tmp_path / "g.json"), "--holdout-report", str(tmp_path / "h.json"),
            "--candidate-file", "configurations/gpt-5-6.json", "--out", str(tmp_path / "out")]  # fmt: skip


@pytest.fixture
def baselines(tmp_path, monkeypatch):
    copy = tmp_path / "baselines"
    shutil.copytree(release.BASELINES, copy)
    monkeypatch.setattr(release, "BASELINES", copy)
    return copy


def test_apply_promotes_and_rollback_is_moving_the_pointer_back(tmp_path, judged, baselines):
    before = (baselines / "current.json").read_text()
    assert cli([*cli_files(tmp_path, judged), "--apply"]) == 0
    new = release.current()
    assert (new.id, new.previous, new.configuration_id) == ("b0002", "b0001", "gpt-5-6")
    assert (new.thresholds_digest, new.code_commit) == (THRESHOLDS.digest, COMMIT)
    assert new.holdout["cases"] == 4 and new.holdout_exception is None
    assert release.configuration(new).id == "gpt-5-6"
    assert release.load_record("b0001") == release.load_record("b0001", cmp.DATA / "baselines")
    decision = json.loads((tmp_path / "out" / f"release-{judged.comparison_id}.json").read_text())
    assert decision["verdict"] == "pass" and decision["proposed_record"]["id"] == "b0002"
    # Rollback: restore the previous pointer; the old record is intact and active again.
    (baselines / "current.json").write_text(before)
    assert release.current().id == "b0001"
    # Records are never overwritten.
    with pytest.raises(FileExistsError):
        release.apply(new)


def test_a_failed_release_leaves_the_current_baseline_active(tmp_path, judged, baselines):
    before = sorted(p.read_text() for p in baselines.iterdir())
    bad = {**GATE, "verdict": "fail", "fail_reasons": ["prohibited-billing-transition#1"]}
    assert cli([*cli_files(tmp_path, judged, gate=bad), "--apply"]) == 1
    assert sorted(p.read_text() for p in baselines.iterdir()) == before
    assert release.current().id == "b0001"


def test_the_candidate_file_must_be_the_compared_configuration(tmp_path, judged, baselines):
    args = cli_files(tmp_path, judged)
    args[args.index("configurations/gpt-5-6.json")] = "configurations/opus-5-5.json"
    assert cli([*args, "--apply"]) == 2
    assert release.current().id == "b0001"


def test_a_changed_pointer_or_configuration_is_refused(baselines, monkeypatch):
    pointer = json.loads((baselines / "current.json").read_text())
    (baselines / "current.json").write_text(json.dumps({**pointer, "digest": "0" * 64}))
    with pytest.raises(ValueError, match="digest does not match"):
        release.current()
    record = release.load_record("b0001")
    with pytest.raises(ValueError, match="changed since it was recorded"):
        release.configuration(record.model_copy(update={"configuration_digest": "0" * 64}))
