"""EVAL-01 PR 5: paired comparisons, budget caps, reports, and live scenarios.

Live scenarios run here against the offline fake HarnessRouter (no network,
no credentials); the real HarnessRouter is used only by the live-eval workflow.
"""

import asyncio
import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from cloudeo.evaluation import compare as cmp
from cloudeo.evaluation import scenarios
from cloudeo.evaluation.contracts import EvalConfiguration
from cloudeo.evaluation.fake_harnessrouter import HEADERS, FakeHarnessRouter
from cloudeo.evaluation.runner import DATA, capabilities, load_suite, verify_store
from cloudeo.evaluation.store import TrialStore

SMOKE = "smoke-v3"


def config(id, reserve=0.1, **variables):
    return EvalConfiguration(
        id=id, description=id, variables=variables or {"executor": id},
        max_cost_usd_per_trial=reserve,
    )  # fmt: skip


def compare(out, a, b, *, suite=SMOKE, repetitions=2, run_cap=7.0, week_cap=20.0, **kw):
    return asyncio.run(
        cmp.run_comparison(
            suite, a, b, out, repetitions=repetitions, run_cap_usd=run_cap,
            week_cap_usd=week_cap, ledger=cmp.Ledger(out / "ledger.jsonl"), seed=7, **kw,
        )
    )  # fmt: skip


def test_pairs_run_both_sides_on_identical_cases_in_seeded_random_order(tmp_path):
    c = compare(tmp_path, config("base"), config("cand"))
    trials = TrialStore(tmp_path).trials(c.run_id)
    # Without the longhorizon extra one case is unsupported on both sides: fewer
    # matched pairs and lower coverage, reported rather than hidden.
    pairs = 10 if capabilities()["longhorizon"] else 8
    assert len(trials) == 2 * 5 * 2 and c.matched_pairs == pairs
    assert c.coverage == pairs / 10
    firsts = [trials[i].label for i in range(0, len(trials), 2)]
    assert set(firsts) == {"base", "cand"}  # neither side always runs first
    order = cmp.plan(load_suite(SMOKE)[1], 2, (config("base"), config("cand")), 7)
    assert [(r, k.id, x.id) for r, k, x in order] == [
        (t.repetition, t.case_id, t.label) for t in trials
    ]
    assert c.gate_verdict == "observational"
    assert (tmp_path / f"comparison-{c.run_id}.json").is_file()
    assert "Gate verdict: observational" in (tmp_path / f"comparison-{c.run_id}.md").read_text()


def test_changed_variables_and_system_comparisons_are_labelled(tmp_path):
    single = compare(tmp_path / "a", config("side-a", model="x"), config("side-b", model="y"))
    assert single.comparison_kind == "single_variable"
    assert single.changed_variables == {"model": ("x", "y")}
    system = compare(
        tmp_path / "b",
        config("side-a", model="x", harness="h1"),
        config("side-b", model="y", harness="h2"),
    )
    assert system.comparison_kind == "system"


def test_a_plan_over_the_run_cap_is_refused_before_anything_runs(tmp_path):
    with pytest.raises(cmp.BudgetExceeded, match="per-run cap"):
        compare(tmp_path, config("side-a", 1.0), config("side-b", 1.0), run_cap=7.0)  # 20 x $1
    assert not (tmp_path / "index.sqlite").exists()


def test_the_weekly_cap_counts_earlier_runs(tmp_path):
    ledger = cmp.Ledger(tmp_path / "ledger.jsonl")
    ledger.record("earlier", 18.5, None)
    old = {"run_id": "old", "at": (datetime.now(UTC) - timedelta(days=8)).isoformat(),
           "counted_usd": 100.0, "reported_usd": None}  # fmt: skip
    with ledger.path.open("a") as f:
        f.write(json.dumps(old) + "\n")  # outside the 7-day window
    with pytest.raises(cmp.BudgetExceeded, match="weekly cap"):
        compare(tmp_path, config("side-a"), config("side-b"))  # $2.00 planned, $1.50 left
    compare(tmp_path, config("side-a", 0.05), config("side-b", 0.05))  # $1.00 fits
    assert ledger.spent_this_week(datetime.now(UTC)) == pytest.approx(19.5)


def test_unknown_cost_counts_as_the_full_reserve(tmp_path):
    c = compare(tmp_path, config("side-a", 0.1), config("side-b", 0.2))
    base, cand = c.metrics
    assert (base.cost_usd_reported, cand.cost_usd_reported) == (None, None)
    assert (base.cost_usd_counted, cand.cost_usd_counted) == (1.0, 2.0)
    assert base.cost_usd_per_verified is None  # never computed from unknown cost


def test_spend_above_the_reserve_stops_the_run_and_keeps_what_ran(tmp_path, monkeypatch):
    real = scenarios.SCENARIOS["core.controller.run"]

    async def expensive(fixture, workdir, record):
        observations, completeness = await real(fixture, workdir, record)
        return {**observations, "cost.usd_reported": 1.5}, completeness

    monkeypatch.setitem(scenarios.SCENARIOS, "core.controller.run", expensive)
    c = compare(tmp_path, config("side-a"), config("side-b"), run_cap=2.5)  # $2.00 planned
    trials = TrialStore(tmp_path).trials(c.run_id)
    assert len(trials) < 20 and c.coverage < 1.0
    assert sum(m.not_run_budget for m in c.metrics) == 20 - len(trials)
    assert any("coverage" in r for r in c.gate_reasons)
    assert sum(cmp.counted_cost(t) for t in trials) <= 2.5 + 1.5  # stops at the first overrun


def test_live_comparisons_refuse_a_dirty_tree(tmp_path, monkeypatch):
    monkeypatch.setattr(cmp, "_code_state", lambda: ("a" * 40, True, None))
    with pytest.raises(cmp.DirtyCodeRefused):
        compare(tmp_path, config("side-a"), config("side-b"), require_clean=True)


def test_a_comparison_can_be_regraded_from_retained_evidence(tmp_path):
    c = compare(tmp_path, config("side-a"), config("side-b"))
    assert verify_store(tmp_path) == []
    trial = TrialStore(tmp_path).trials(c.run_id)[0]
    path = tmp_path / "trials" / f"{trial.trial_id}.json"
    forged = trial.model_copy(update={"observations": {**trial.observations, "x": 1}})
    path.write_text(forged.model_dump_json())
    assert [t.trial_id for t, _ in verify_store(tmp_path)] == [trial.trial_id]


def test_the_shipped_live_configurations_fit_the_owner_caps():
    configs = [
        EvalConfiguration.model_validate_json((DATA / "configurations" / f"{n}.json").read_text())
        for n in ("opus-5-5", "gpt-5-6")
    ]
    _, cases = load_suite("live-smoke-v1")
    planned = cmp.estimate(cmp.plan(cases, 3, tuple(configs), 1))
    assert planned <= 7.0  # owner cap per run, 2026-10-31
    assert {c.variables["executor_model"] for c in configs} == {"claude-opus-5-5", "gpt-5.6"}
    assert all(c.mode == "live" and "live_uhp" in c.required_capabilities for c in cases)


# --- Live scenarios against the fake HarnessRouter ---


def text_server(answers):
    """A fake HarnessRouter for text tasks: replies per prompt, echoing the model."""
    seen = []

    def handler(request):
        payload = json.loads(request.content)
        seen.append(payload)
        text = answers[payload["input"]]
        body = {
            "id": f"resp_{len(seen)}", "object": "response", "created_at": 1786400000,
            "status": "completed", "model": payload["model"], "error": None,
            "output": [{"type": "message", "role": "assistant",
                        "content": [{"type": "output_text", "text": text}]}],
            "incomplete_details": None, "usage": {"input_tokens": 10, "output_tokens": 3},
            "metadata": {"session_id": f"s{len(seen)}"}, "previous_response_id": None,
        }  # fmt: skip
        return httpx.Response(200, json=body, headers=HEADERS)

    return handler, seen


def live_configs():
    return [
        EvalConfiguration.model_validate_json((DATA / "configurations" / f"{n}.json").read_text())
        for n in ("opus-5-5", "gpt-5-6")
    ]


@pytest.mark.parametrize(
    "case_id,answer,passes",
    [
        ("live-exact-reply", "CLOUDEO_LIVE_OK", True),
        ("live-exact-reply", "Sure! CLOUDEO_LIVE_OK", False),
        ("live-arithmetic", "1610", True),
        ("live-arithmetic", "1611", False),
    ],
)
def test_live_text_cases_go_through_control_and_judge_the_exact_answer(
    tmp_path, monkeypatch, case_id, answer, passes
):
    case = next(c for c in load_suite("live-smoke-v1")[1] if c.id == case_id)
    handler, seen = text_server({case.fixture["task"]["input"]: answer})
    monkeypatch.setattr(scenarios, "LIVE_TRANSPORT", httpx.MockTransport(handler))
    for configuration in live_configs():
        fixture = cmp.apply_configuration(case, configuration)
        observations, _ = asyncio.run(
            scenarios.SCENARIOS[case.entry_point](fixture, tmp_path, scenarios.Recorder())
        )
        assert observations["output.exact_match"] is passes
        assert observations["control.dispatched"] is True
        # The approved model was sent and echoed, so identity is confirmed.
        assert seen[-1]["model"] == configuration.variables["executor_model"]
        assert seen[-1]["metadata"]["harness_id"] == configuration.variables["executor_harness"]
        assert observations["identity.actual_matches_approved"] is True
        assert "cost.usd_reported" not in observations  # tokens are not money


def test_live_workspace_edit_runs_the_bridge_under_control_authorization(tmp_path, monkeypatch):
    case = next(c for c in load_suite("live-smoke-v1")[1] if c.id == "live-workspace-edit")
    expected = case.fixture["expected_file"]

    def work(ws):
        (ws / "notes").mkdir(exist_ok=True)
        (ws / "notes" / "greeting.txt").write_text(expected["content"])

    router = FakeHarnessRouter(tmp_path / "hr", work=work)
    monkeypatch.setattr(scenarios, "LIVE_TRANSPORT", httpx.MockTransport(router))
    fixture = cmp.apply_configuration(case, live_configs()[0])
    recorder = scenarios.Recorder()
    (tmp_path / "w").mkdir()
    observations, _ = asyncio.run(
        scenarios.SCENARIOS[case.entry_point](fixture, tmp_path / "w", recorder)
    )
    assert observations["workspace.expected_file_matches"] is True
    assert observations["bridge.sync_status"].endswith("synced")
    assert observations["accepted.unchanged"] is True
    assert [e.data for e in recorder.events if e.kind == "authorization"] == [{"granted": True}]
    assert router.task_payloads[0]["model"] == "claude-opus-5-5"


def test_live_comparison_end_to_end_with_the_fake_runtime(tmp_path, monkeypatch):
    cases = load_suite("live-smoke-v1")[1]
    answers = {c.fixture["task"]["input"]: c.fixture["expected_output"]
               for c in cases if c.entry_point == "live.harness_task"}  # fmt: skip
    handler, _ = text_server(answers)
    monkeypatch.setattr(scenarios, "LIVE_TRANSPORT", httpx.MockTransport(handler))
    opus, gpt = live_configs()
    c = compare(tmp_path, opus, gpt, suite="live-smoke-v1", repetitions=1)
    assert c.comparison_kind == "system"
    assert set(c.changed_variables) == {"executor_harness", "executor_model", "executor_provider"}
    by_case = {(t.case_id, t.label): t for t in TrialStore(tmp_path).trials(c.run_id)}
    for config_id in ("opus-5-5", "gpt-5-6"):
        assert by_case[("live-exact-reply", config_id)].verdict == "pass"
        assert by_case[("live-arithmetic", config_id)].verdict == "pass"
        # The text-only fake cannot serve a bridge run: an infrastructure error, kept.
        assert by_case[("live-workspace-edit", config_id)].status == "error"
    assert all(m.infrastructure_invalid == 1 for m in c.metrics)
    assert all(m.cost_usd_counted == pytest.approx(3 * 0.35) for m in c.metrics)
