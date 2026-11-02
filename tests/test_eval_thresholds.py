"""EVAL-01 PR 6b: frozen comparison thresholds and pass / fail / inconclusive verdicts.

Exit criteria (docs/EVAL-01_PLAN.md §5, PR 6): an inconclusive comparison cannot
claim improvement; thresholds are frozen by digest before a run.
"""

import asyncio

import pytest

from cloudeo.evaluation import compare as cmp
from cloudeo.evaluation.__main__ import main as cli
from cloudeo.evaluation.contracts import ConfigMetrics, EvalConfiguration, EvalTrial

V1 = cmp.THRESHOLDS / "thresholds-v1.json"


def thresholds(**changes):
    t = cmp.load_thresholds(V1)
    return t.model_copy(update=changes) if changes else t


def metrics(id="m", tokens_per_verified=1000.0, median=10_000.0, p95=None):
    return ConfigMetrics(
        configuration_id=id, attempted=60, completed=60, verified=57, outcome_pass=57,
        execution_violations=0, unknown=0, unsupported=0, infrastructure_invalid=0,
        not_run_budget=0, cost_usd_reported=None, cost_usd_counted=21.0,
        cost_usd_per_verified=None, duration_ms_median=median, duration_ms_p95=p95,
        per_case={}, tokens_total=None, tokens_per_verified=tokens_per_verified,
    )  # fmt: skip


def judge(t=None, *, cases=12, repetitions=5, coverage=1.0, critical=0, diff=0.0,
          ci=(-0.05, 0.05), base=None, cand=None):  # fmt: skip
    return cmp.judge(
        t or thresholds(), cases=cases, repetitions=repetitions, coverage=coverage,
        critical=critical, diff=diff, ci=ci, base=base or metrics("b"), cand=cand or metrics("c"),
    )  # fmt: skip


def test_the_shipped_thresholds_are_the_owner_approved_values():
    t = thresholds()
    assert (t.id, t.approved_at, t.primary_metric) == (
        "thresholds-v1",
        "2026-11-02",
        "verified_success_rate",
    )
    assert t.max_critical_violations == 0 and t.min_coverage == 0.95
    assert (t.min_cases, t.min_repetitions, t.non_inferiority_margin) == (12, 5, 0.1)
    assert t.improvement_lower_bound_above == 0.0
    assert (t.max_tokens_per_verified_ratio, t.max_median_duration_ratio,
            t.max_p95_duration_ratio) == (1.25, 1.5, 1.5)  # fmt: skip
    assert (t.run_cap_usd, t.week_cap_usd) == (45.0, 60.0)


def test_non_inferior_within_every_limit_passes_without_claiming_improvement():
    assert judge() == ("pass", [], False)


def test_improvement_is_claimed_only_when_the_lower_bound_is_above_zero():
    assert judge(diff=0.2, ci=(0.05, 0.35)) == ("pass", [], True)
    assert judge(diff=0.2, ci=(-0.01, 0.35))[2] is False
    # Not enough evidence to pass: no improvement claim either.
    verdict, _, improved = judge(cases=3, diff=0.2, ci=(0.05, 0.35))
    assert (verdict, improved) == ("inconclusive", False)


@pytest.mark.parametrize(
    "kwargs, reason",
    [
        ({"critical": 1}, "critical execution violation"),
        ({"diff": -0.15, "ci": (-0.3, 0.0)}, "worse than the margin"),
        ({"cand": metrics(tokens_per_verified=1300.0)}, "tokens per verified success 1.30x"),
        ({"cand": metrics(median=16_000.0)}, "median duration 1.60x"),
        ({"base": metrics(p95=10_000.0), "cand": metrics(p95=16_000.0)}, "p95 duration 1.60x"),
    ],
)
def test_fail(kwargs, reason):
    verdict, reasons, improved = judge(**kwargs)
    assert verdict == "fail" and not improved
    assert any(reason in r for r in reasons), reasons


@pytest.mark.parametrize(
    "kwargs, reason",
    [
        ({"cases": 11}, "11 case(s)"),
        ({"repetitions": 3}, "3 repetition(s)"),
        ({"coverage": 0.9}, "coverage 90% below 95%"),
        ({"diff": None, "ci": None}, "not computable"),
        ({"diff": -0.05, "ci": (-0.2, 0.1)}, "does not exclude a drop"),
        ({"cand": metrics(tokens_per_verified=None)}, "tokens per verified success unknown"),
        ({"base": metrics(median=None)}, "median duration unknown"),
    ],
)
def test_inconclusive(kwargs, reason):
    verdict, reasons, improved = judge(**kwargs)
    assert verdict == "inconclusive" and not improved
    assert any(reason in r for r in reasons), reasons


def test_p95_is_judged_only_when_both_sides_have_it():
    assert judge(cand=metrics(p95=99_000.0))[0] == "pass"


def trial_with(usage):
    return EvalTrial.model_construct(observations={} if usage is None else {"usage": usage})


def test_tokens_are_read_from_runtime_usage_and_never_guessed():
    assert cmp.trial_tokens(trial_with({"total_tokens": 900})) == 900
    assert cmp.trial_tokens(trial_with({"input_tokens": 700, "output_tokens": 200})) == 900
    assert cmp.trial_tokens(trial_with({"input_tokens": 700})) is None
    assert cmp.trial_tokens(trial_with(None)) is None


def config(id):
    return EvalConfiguration(
        id=id, description=id, variables={"executor": id}, max_cost_usd_per_trial=0.1
    )


def run(out, **kw):
    return asyncio.run(
        cmp.run_comparison(
            "smoke-v3", config("base"), config("cand"), out, repetitions=1, run_cap_usd=7.0,
            week_cap_usd=20.0, ledger=cmp.Ledger(out / "ledger.jsonl"), seed=7, **kw,
        )
    )  # fmt: skip


def test_a_judged_comparison_records_its_frozen_thresholds(tmp_path, monkeypatch):
    monkeypatch.setattr(cmp, "_code_state", lambda: ("a" * 40, False, None))
    t = thresholds()
    c = run(tmp_path, thresholds=t)
    # Five offline cases, one repetition, no runtime tokens: too little to pass.
    assert c.gate_verdict == "inconclusive" and not c.improvement_claimed
    assert any("5 case(s)" in r for r in c.gate_reasons)
    assert (c.thresholds_id, c.thresholds_digest) == ("thresholds-v1", t.digest)
    cmp.check_frozen(c, t)
    with pytest.raises(cmp.ThresholdsChanged, match="judged against"):
        cmp.check_frozen(c, thresholds(non_inferiority_margin=0.2))
    report = (tmp_path / f"comparison-{c.run_id}.md").read_text()
    assert "Gate verdict: inconclusive" in report and "thresholds-v1" in report


def test_an_observational_comparison_cannot_be_used_as_judged(tmp_path):
    c = run(tmp_path)
    assert c.gate_verdict == "observational" and c.thresholds_digest is None
    with pytest.raises(cmp.ThresholdsChanged, match="observational"):
        cmp.check_frozen(c, thresholds())


def test_thresholds_require_committed_clean_code(tmp_path, monkeypatch):
    monkeypatch.setattr(cmp, "_code_state", lambda: ("a" * 40, True, None))
    with pytest.raises(cmp.DirtyCodeRefused):
        run(tmp_path, thresholds=thresholds())


def test_cli_uses_the_release_caps_of_the_thresholds_file(tmp_path, capsys):
    args = ["compare", "--suite", "live-smoke-v2", "--out", str(tmp_path), "--estimate-only",
            "--baseline", str(cmp.DATA / "configurations" / "opus-5-5.json"),
            "--candidate", str(cmp.DATA / "configurations" / "gpt-5-6.json")]  # fmt: skip
    assert cli([*args, "--thresholds", str(V1)]) == 0
    out = capsys.readouterr().out
    assert "thresholds: thresholds-v1" in out and "run cap $45.00" in out
    assert "of $60.00)" in out
    cli(args)
    assert "run cap $7.00" in capsys.readouterr().out  # without thresholds: unchanged
