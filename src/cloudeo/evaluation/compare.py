"""Paired comparisons of two configurations under a hard budget (EVAL-01 PR 5, plan §8).

- Identical cases, fixtures and repetitions on both sides; each (case,
  repetition) pair runs both configurations in a seeded random order, so
  provider and time drift does not favor one side.
- Budget: before anything runs, the planned trials' reserves must fit the
  per-run cap and what is left of the weekly cap. During the run, a trial
  starts only if its reserve still fits; the rest are reported as not run.
  A trial's cost counts as reported where the runtime reported it, else as
  its full reserve. Unknown cost is never zero.
- Every attempted trial stays in the report, with its status.
- Thresholds are not approved yet, so a comparison is observational and can
  never authorize promotion.
"""

from __future__ import annotations

import json
import random
import statistics
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from cloudeo.evaluation.contracts import (
    ConfigMetrics,
    EvalCase,
    EvalComparison,
    EvalConfiguration,
    EvalTrial,
    Provenance,
)
from cloudeo.evaluation.graders import GRADER_VERSIONS
from cloudeo.evaluation.runner import (
    DATA,
    _code_state,
    _run_trial,
    capabilities,
    holdout_dir,
    load_suite,
)
from cloudeo.evaluation.store import TrialStore

LEDGER_WINDOW = timedelta(days=7)


class BudgetExceeded(RuntimeError):
    """The planned comparison does not fit the per-run or weekly cap; nothing ran."""


class DirtyCodeRefused(RuntimeError):
    """Live comparisons need a committed, clean tree so results name exact code."""


def _merge(base: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


def apply_configuration(case: EvalCase, config: EvalConfiguration) -> dict[str, Any]:
    return _merge(case.fixture, config.fixture_overrides.get(case.entry_point, {}))


class Ledger:
    """Append-only spend ledger (JSON lines) for the weekly cap."""

    def __init__(self, path: Path):
        self.path = path

    def entries(self) -> list[dict[str, Any]]:
        if not self.path.is_file():
            return []
        return [json.loads(line) for line in self.path.read_text().splitlines() if line.strip()]

    def spent_this_week(self, now: datetime) -> float:
        since = now - LEDGER_WINDOW
        return sum(
            e["counted_usd"] for e in self.entries() if datetime.fromisoformat(e["at"]) >= since
        )

    def record(self, run_id: str, counted_usd: float, reported_usd: float | None) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        entry = {"run_id": run_id, "at": datetime.now(UTC).isoformat(),
                 "counted_usd": round(counted_usd, 6), "reported_usd": reported_usd}  # fmt: skip
        with self.path.open("a") as f:
            f.write(json.dumps(entry) + "\n")


def counted_cost(trial: EvalTrial) -> float:
    if trial.cost_usd_reported is not None:
        return trial.cost_usd_reported
    return trial.cost_usd_reserved or 0.0


def plan(cases: list[EvalCase], repetitions: int, configs: tuple[EvalConfiguration, ...],
         seed: int) -> list[tuple[int, EvalCase, EvalConfiguration]]:  # fmt: skip
    """Pairs in case order per repetition, each pair's two sides in seeded random order."""
    rng = random.Random(seed)
    order = []
    for repetition in range(1, repetitions + 1):
        for case in cases:
            sides = list(configs)
            rng.shuffle(sides)
            order += [(repetition, case, config) for config in sides]
    return order


def estimate(order) -> float:
    return round(sum(config.max_cost_usd_per_trial for _, _, config in order), 6)


async def run_comparison(
    suite_id: str,
    baseline: EvalConfiguration,
    candidate: EvalConfiguration,
    out: Path,
    *,
    repetitions: int,
    run_cap_usd: float,
    week_cap_usd: float,
    ledger: Ledger,
    seed: int,
    require_clean: bool = False,
    data: Path = DATA,
) -> EvalComparison:
    if baseline.id == candidate.id:
        raise ValueError("baseline and candidate need different configuration ids")
    suite, cases = load_suite(suite_id, data, holdout_dir())
    cases = [c for c in cases if c.partition != "holdout"]  # holdout is for promotion review
    order = plan(cases, repetitions, (baseline, candidate), seed)
    planned = estimate(order)
    now = datetime.now(UTC)
    week_left = week_cap_usd - ledger.spent_this_week(now)
    if planned > run_cap_usd:
        raise BudgetExceeded(f"planned ${planned:.2f} exceeds the per-run cap ${run_cap_usd:.2f}")
    if planned > week_left:
        raise BudgetExceeded(
            f"planned ${planned:.2f} exceeds the ${max(week_left, 0):.2f} left of the "
            f"${week_cap_usd:.2f} weekly cap"
        )
    commit, dirty, lock_sha = _code_state()
    if require_clean and (commit is None or dirty is not False):
        raise DirtyCodeRefused("live comparisons need a committed, clean working tree")

    store = TrialStore(out)
    run_id = uuid.uuid4().hex
    store.mark_abandoned(run_id)
    caps = capabilities()
    spent = 0.0
    try:
        for repetition, case, config in order:
            if spent + config.max_cost_usd_per_trial > run_cap_usd:
                break  # the remaining planned trials are reported as not run
            provenance = Provenance(
                code_commit=commit, code_dirty=dirty, python=_python(), uv_lock_sha256=lock_sha,
                suite_id=suite.id, suite_version=suite.version, suite_digest=suite.digest,
                case_digest=case.digest, fixture_digest=case.fixture_digest,
                partition=case.partition, severity=case.severity,
                grader_versions=dict(GRADER_VERSIONS), capabilities=caps,
                configuration_id=config.id, configuration_digest=config.digest,
            )  # fmt: skip
            trial = await _run_trial(
                store, run_id, suite, case, repetition, config.id, provenance, caps,
                fixture=apply_configuration(case, config),
                reserve=config.max_cost_usd_per_trial,
            )  # fmt: skip
            spent += counted_cost(trial)
    finally:
        trials = store.trials(run_id)
        reported = [t.cost_usd_reported for t in trials]
        ledger.record(
            run_id,
            sum(counted_cost(t) for t in trials),
            None if any(r is None for r in reported) else sum(reported),
        )
    comparison = build_comparison(
        run_id, suite.id, suite.digest, baseline, candidate, cases, repetitions, seed, trials
    )
    (out / f"comparison-{run_id}.json").write_text(comparison.model_dump_json(indent=2) + "\n")
    (out / f"comparison-{run_id}.md").write_text(render_markdown(comparison))
    return comparison


def _python() -> str:
    import sys

    return sys.version.split()[0]


def _quantile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(q * (len(ordered) - 1)))]


def _metrics(config: EvalConfiguration, trials: list[EvalTrial], planned: int) -> ConfigMetrics:
    mine = [t for t in trials if t.label == config.id]
    verified = [t for t in mine if t.verdict == "pass"]
    durations = [
        (t.finished_at - t.started_at).total_seconds() * 1000
        for t in mine
        if t.status == "completed" and t.finished_at
    ]
    reported = [t.cost_usd_reported for t in mine]
    counted = sum(counted_cost(t) for t in mine)
    per_case: dict[str, list[int]] = {}
    for t in mine:
        k_n = per_case.setdefault(t.case_id, [0, 0])
        k_n[0] += t.verdict == "pass"
        k_n[1] += 1
    known_cost = None if any(r is None for r in reported) else round(sum(reported), 6)
    return ConfigMetrics(
        configuration_id=config.id,
        attempted=len(mine),
        completed=sum(t.status == "completed" for t in mine),
        verified=len(verified),
        outcome_pass=sum(bool(t.outcome_grade) and t.outcome_grade.verdict == "pass" for t in mine),
        execution_violations=sum(
            bool(t.execution_grade) and t.execution_grade.verdict == "fail" for t in mine
        ),
        unknown=sum(t.verdict == "unknown" and t.status == "completed" for t in mine),
        unsupported=sum(t.status == "unsupported" for t in mine),
        infrastructure_invalid=sum(t.status in ("error", "interrupted") for t in mine),
        not_run_budget=planned - len(mine),
        cost_usd_reported=known_cost,
        cost_usd_counted=round(counted, 6),
        cost_usd_per_verified=(
            round(known_cost / len(verified), 6) if known_cost is not None and verified else None
        ),
        duration_ms_median=statistics.median(durations) if durations else None,
        duration_ms_p95=_quantile(durations, 0.95) if len(durations) >= 20 else None,
        per_case={case: f"{k}/{n}" for case, (k, n) in sorted(per_case.items())},
    )


def _case_rates(trials: list[EvalTrial], config_id: str) -> dict[str, float]:
    rates: dict[str, list[int]] = {}
    for t in trials:
        if t.label == config_id and t.status == "completed":
            rates.setdefault(t.case_id, []).append(t.verdict == "pass")
    return {case: sum(v) / len(v) for case, v in rates.items()}


def paired_difference(trials, baseline_id, candidate_id, seed, resamples=2000):
    """Mean over cases of (candidate - baseline) verified rate, with a 95%
    case-clustered bootstrap interval: cases are resampled, not repetitions."""
    base, cand = _case_rates(trials, baseline_id), _case_rates(trials, candidate_id)
    cases = sorted(set(base) & set(cand))
    if not cases:
        return None, None
    diffs = [cand[c] - base[c] for c in cases]
    mean = sum(diffs) / len(diffs)
    rng = random.Random(seed)
    boots = sorted(sum(rng.choice(diffs) for _ in diffs) / len(diffs) for _ in range(resamples))
    low, high = boots[int(0.025 * resamples)], boots[int(0.975 * resamples) - 1]
    return round(mean, 6), (round(low, 6), round(high, 6))


def build_comparison(run_id, suite_id, suite_digest, baseline, candidate, cases, repetitions,
                     seed, trials) -> EvalComparison:  # fmt: skip
    planned_each = len(cases) * repetitions
    names = sorted(set(baseline.variables) | set(candidate.variables))
    changed = {
        n: (baseline.variables.get(n), candidate.variables.get(n))
        for n in names
        if baseline.variables.get(n) != candidate.variables.get(n)
    }
    done = {(t.case_id, t.repetition, t.label) for t in trials if t.status == "completed"}
    pairs = sum(
        (c.id, r, baseline.id) in done and (c.id, r, candidate.id) in done
        for c in cases
        for r in range(1, repetitions + 1)
    )
    coverage = pairs / planned_each if planned_each else 0.0
    severity = {c.id: c.severity for c in cases}
    critical = tuple(
        f"{t.label}/{t.case_id}#{t.repetition}: " + "; ".join(t.execution_grade.reasons)
        for t in trials
        if severity.get(t.case_id) == "critical"
        and t.execution_grade
        and t.execution_grade.verdict == "fail"
    )
    diff, ci = paired_difference(trials, baseline.id, candidate.id, seed)
    reasons = ["comparison thresholds are not approved yet: results are observational only"]
    if coverage < 1.0:
        reasons.append(f"coverage {coverage:.0%} of planned pairs")
    if critical:
        reasons.append(f"{len(critical)} critical execution violation(s)")
    return EvalComparison(
        comparison_id=f"cmp-{run_id[:12]}", run_id=run_id, suite_id=suite_id,
        suite_digest=suite_digest, baseline=baseline, candidate=candidate,
        changed_variables=changed,
        comparison_kind="single_variable" if len(changed) == 1 else "system",
        repetitions=repetitions, seed=seed, matched_pairs=pairs, coverage=round(coverage, 6),
        metrics=(_metrics(baseline, trials, planned_each), _metrics(candidate, trials, planned_each)),
        verified_rate_difference=diff, difference_ci95=ci, critical_findings=critical,
        gate_verdict="observational", gate_reasons=tuple(reasons),
    )  # fmt: skip


def _cell(value) -> str:
    return "—" if value is None else str(value)


def _usd(value: float | None) -> str:
    return "unknown" if value is None else f"${value:.4f}"


def render_markdown(c: EvalComparison) -> str:
    base, cand = c.metrics
    rows = [
        ("Attempted", base.attempted, cand.attempted),
        ("Completed", base.completed, cand.completed),
        ("Verified (outcome and execution pass)", base.verified, cand.verified),
        ("Outcome pass", base.outcome_pass, cand.outcome_pass),
        ("Execution-policy violations", base.execution_violations, cand.execution_violations),
        ("Unknown verdict", base.unknown, cand.unknown),
        ("Unsupported", base.unsupported, cand.unsupported),
        ("Infrastructure-invalid", base.infrastructure_invalid, cand.infrastructure_invalid),
        ("Not run (budget)", base.not_run_budget, cand.not_run_budget),
        ("Cost reported by runtime", _usd(base.cost_usd_reported), _usd(cand.cost_usd_reported)),
        ("Cost counted against budget", _usd(base.cost_usd_counted), _usd(cand.cost_usd_counted)),
        ("Cost per verified success", _usd(base.cost_usd_per_verified),
         _usd(cand.cost_usd_per_verified)),
        ("Median duration (ms)", base.duration_ms_median, cand.duration_ms_median),
        ("p95 duration (ms, n≥20 only)", base.duration_ms_p95, cand.duration_ms_p95),
    ]  # fmt: skip
    lines = [
        f"# Comparison {c.comparison_id}",
        "",
        (
            f"Suite `{c.suite_id}` (digest `{c.suite_digest[:12]}`), run `{c.run_id}`, "
            f"{c.repetitions} repetition(s), seed {c.seed}."
        ),
        "",
        f"**Gate verdict: {c.gate_verdict}.** " + " ".join(f"{r}." for r in c.gate_reasons),
        "",
        f"Kind: **{c.comparison_kind}** comparison. Changed variables:",
        "",
        *[f"- `{k}`: `{a}` → `{b}`" for k, (a, b) in c.changed_variables.items()],
        "",
        f"Matched pairs: {c.matched_pairs}; coverage {c.coverage:.0%}.",
        "",
        f"| Metric | `{c.baseline.id}` (baseline) | `{c.candidate.id}` (candidate) |",
        "| --- | --- | --- |",
        *[f"| {name} | {_cell(a)} | {_cell(b)} |" for name, a, b in rows],
        "",
        "Verified-success difference (candidate − baseline, mean over cases): "
        + (
            "not computable (no case completed on both sides)"
            if c.verified_rate_difference is None
            else f"{c.verified_rate_difference:+.3f}, 95% case-clustered bootstrap interval "
            f"[{c.difference_ci95[0]:+.3f}, {c.difference_ci95[1]:+.3f}]"
        ),
        "",
        "Per case (verified k/n):",
        "",
        f"| Case | `{c.baseline.id}` | `{c.candidate.id}` |",
        "| --- | --- | --- |",
        *[
            f"| `{case}` | {base.per_case.get(case, '—')} | {cand.per_case.get(case, '—')} |"
            for case in sorted(set(base.per_case) | set(cand.per_case))
        ],
        "",
        "Critical findings: " + ("none" if not c.critical_findings else ""),
        *[f"- {f}" for f in c.critical_findings],
        "",
        (
            "Repeated runs of one case are not independent tasks; the interval resamples "
            "cases. A small pilot cannot establish a small difference."
        ),
        "",
    ]
    return "\n".join(lines)
