"""Deterministic regression gate (EVAL-01 PR 6a, docs/EVAL-01_PLAN.md §8).

One verdict over one suite run, for CI. Only "pass" lets a change advance.

- fail: a regression trial failed, or any trial on a critical case showed an
  execution-policy violation (a correct answer reached through a forbidden
  path still fails).
- blocked: no fail, but a regression trial is unknown (missing evidence),
  infrastructure-invalid (error, interrupted), unsupported, or never ran.
- pass: every regression case ran and passed, with no critical violation.

Capability results are reported, never gated. Holdout trials are not seen here;
only their aggregate counts are copied into the report.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from cloudeo.evaluation.contracts import EvalCase, EvalSuite, EvalTrial

GateVerdict = Literal["pass", "fail", "blocked"]
EXIT_CODES: dict[GateVerdict, int] = {"pass": 0, "fail": 1, "blocked": 2}


def _reasons(trial: EvalTrial) -> str:
    grades = (trial.outcome_grade, trial.execution_grade)
    return trial.error or "; ".join(r for g in grades if g for r in g.reasons) or "no reason"


def decide(
    suite: EvalSuite, cases: list[EvalCase], trials: list[EvalTrial]
) -> tuple[GateVerdict, list[str], list[str]]:
    """(verdict, fail reasons, blocked reasons) for one run of `suite`."""
    failed, blocked = [], []
    for t in trials:
        tag = f"{t.case_id}#{t.repetition}"
        execution = t.execution_grade
        if t.provenance.severity == "critical" and execution and execution.verdict == "fail":
            failed.append(f"{tag}: critical execution violation: {'; '.join(execution.reasons)}")
        elif t.provenance.partition != "regression":
            continue
        elif t.status != "completed":
            blocked.append(f"{tag}: {t.status}: {_reasons(t)}")
        elif t.verdict == "fail":
            failed.append(f"{tag}: regression failed: {_reasons(t)}")
        elif t.verdict == "unknown":
            blocked.append(f"{tag}: regression unknown: {_reasons(t)}")
    ran = {t.case_id for t in trials}
    regression = [c.id for c in cases if c.partition == "regression"]
    blocked += [
        f"{case_id}: regression case did not run" for case_id in regression if case_id not in ran
    ]
    if not regression:
        blocked.append(f"suite {suite.id} has no regression cases")
    verdict: GateVerdict = "fail" if failed else "blocked" if blocked else "pass"
    return verdict, failed, blocked


def _counts(trials: list[EvalTrial], partition: str) -> dict[str, int]:
    group = [t for t in trials if t.provenance.partition == partition]
    counts = {v: sum(t.status == "completed" and t.verdict == v for t in group)
              for v in ("pass", "fail", "unknown")}  # fmt: skip
    counts["not_completed"] = sum(t.status != "completed" for t in group)
    return counts


def _trial_row(t: EvalTrial) -> dict[str, Any]:
    return {
        "case_id": t.case_id,
        "repetition": t.repetition,
        "partition": t.provenance.partition,
        "severity": t.provenance.severity,
        "status": t.status,
        "verdict": t.verdict,
        "reasons": _reasons(t) if t.verdict != "pass" else "",
    }


def build_report(
    run_id: str,
    suite: EvalSuite,
    cases: list[EvalCase],
    trials: list[EvalTrial],
    holdout: dict[str, int],
) -> dict[str, Any]:
    verdict, failed, blocked = decide(suite, cases, trials)
    first = trials[0].provenance if trials else None
    return {
        "gate": "eval-01-regression",
        "verdict": verdict,
        "exit_code": EXIT_CODES[verdict],
        "fail_reasons": failed,
        "blocked_reasons": blocked,
        "run_id": run_id,
        "suite_id": suite.id,
        "suite_version": suite.version,
        "suite_digest": suite.digest,
        "code_commit": first.code_commit if first else None,
        "code_dirty": first.code_dirty if first else None,
        "grader_versions": dict(suite.grader_versions),
        "created_at": datetime.now(UTC).isoformat(),
        "regression": _counts(trials, "regression"),
        "capability": _counts(trials, "capability"),
        "holdout": holdout,
        "trials": [_trial_row(t) for t in trials],
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        f"# EVAL-01 regression gate: **{report['verdict'].upper()}**",
        "",
        (
            f"Suite `{report['suite_id']}` v{report['suite_version']} "
            f"(`{report['suite_digest'][:12]}`), commit `{report['code_commit']}`"
            f"{' (dirty)' if report['code_dirty'] else ''}, run `{report['run_id'][:12]}`."
        ),
        "",
        "| Partition | pass | fail | unknown | not completed |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for partition in ("regression", "capability"):
        c = report[partition]
        lines.append(f"| {partition} | {c['pass']} | {c['fail']} | {c['unknown']} "
                     f"| {c['not_completed']} |")  # fmt: skip
    if report["holdout"].get("cases"):
        lines += ["", "Holdout (aggregate only): "
                  + ", ".join(f"{k} {v}" for k, v in report["holdout"].items())]  # fmt: skip
    for title, key in (("Fail", "fail_reasons"), ("Blocked", "blocked_reasons")):
        if report[key]:
            lines += ["", f"## {title}", ""] + [f"- {r}" for r in report[key]]
    return "\n".join(lines) + "\n"


def write_report(out: Path, report: dict[str, Any]) -> tuple[Path, Path]:
    out.mkdir(parents=True, exist_ok=True)
    stem = out / f"gate-{report['run_id']}"
    json_path, md_path = stem.with_suffix(".json"), stem.with_suffix(".md")
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    md_path.write_text(render_markdown(report))
    return json_path, md_path
