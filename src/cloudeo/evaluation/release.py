"""Release gate and baseline pointer (EVAL-01 PR 6c, docs/EVAL-01_PLAN.md §8).

`baselines/current.json` names the active baseline record (`baselines/bNNNN.json`,
immutable). A candidate replaces it only when every check passes:

- the paired comparison was judged against the frozen thresholds and passed;
- its baseline side is the current baseline, on exact, clean, committed code;
- the regression gate passed on that same commit;
- the holdout gate report (aggregate counts only) ran on that commit with no
  critical violation and nothing unknown or unavailable, or the owner recorded
  why there is no holdout.

fail: a check found a defect (regression, critical violation, comparison fail).
blocked: the evidence is missing, stale, or does not match. Only pass writes a
new record, and only when asked; the pointer moves when that PR is merged, so a
failed release leaves the current baseline active and rollback is a revert.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from cloudeo.evaluation.compare import ThresholdsChanged, check_frozen
from cloudeo.evaluation.contracts import (
    BaselineRecord,
    EvalComparison,
    EvalConfiguration,
    EvalThresholds,
)
from cloudeo.evaluation.runner import DATA

BASELINES = DATA / "baselines"
ReleaseVerdict = Literal["pass", "fail", "blocked"]
EXIT_CODES: dict[ReleaseVerdict, int] = {"pass": 0, "fail": 1, "blocked": 2}


def load_record(record_id: str, baselines: Path | None = None) -> BaselineRecord:
    baselines = baselines or BASELINES
    return BaselineRecord.model_validate_json((baselines / f"{record_id}.json").read_text())


def current(baselines: Path | None = None) -> BaselineRecord:
    baselines = baselines or BASELINES
    pointer = json.loads((baselines / "current.json").read_text())
    record = load_record(pointer["baseline"], baselines)
    if pointer.get("digest") != record.digest:
        raise ValueError(f"current.json digest does not match {record.id}")
    return record


def configuration(record: BaselineRecord, data: Path = DATA) -> EvalConfiguration:
    config = EvalConfiguration.model_validate_json((data / record.configuration_file).read_text())
    if (config.id, config.digest) != (record.configuration_id, record.configuration_digest):
        raise ValueError(f"{record.id}: {record.configuration_file} changed since it was recorded")
    return config


def _holdout(report: dict[str, Any] | None, exception: str | None, commit: str | None,
             failed: list[str], blocked: list[str]) -> None:  # fmt: skip
    if report is None:
        if not exception:
            blocked.append("no holdout report, and no owner-recorded reason for its absence")
        return
    counts = report.get("holdout") or {}
    if report.get("code_commit") != commit or report.get("code_dirty") is not False:
        blocked.append(f"holdout report ran on {report.get('code_commit')}, not clean {commit}")
    if not counts.get("cases"):
        blocked.append("holdout report has no holdout cases")
    if counts.get("critical_violations", 0):
        failed.append(f"holdout: {counts['critical_violations']} critical violation(s)")
    for key in ("unknown", "unavailable"):
        if counts.get(key, 0):
            blocked.append(f"holdout: {counts[key]} {key}")
    if "critical_violations" not in counts:
        blocked.append("holdout report does not count critical violations")


def decide(
    comparison: EvalComparison,
    thresholds: EvalThresholds,
    gate_report: dict[str, Any],
    holdout_report: dict[str, Any] | None,
    holdout_exception: str | None,
    baseline: BaselineRecord,
) -> tuple[ReleaseVerdict, list[str], list[str]]:
    failed: list[str] = []
    blocked: list[str] = []
    try:
        check_frozen(comparison, thresholds)
    except ThresholdsChanged as exc:
        blocked.append(str(exc))
    if comparison.gate_verdict == "fail":
        failed.append("comparison failed: " + "; ".join(comparison.gate_reasons))
    elif comparison.gate_verdict != "pass":
        blocked.append(
            f"comparison is {comparison.gate_verdict}: " + "; ".join(comparison.gate_reasons)
        )
    if comparison.baseline.digest != baseline.configuration_digest:
        blocked.append(
            f"compared against {comparison.baseline.id}, but the current baseline "
            f"{baseline.id} is {baseline.configuration_id}"
        )
    commit = comparison.code_commit
    if commit is None or comparison.code_dirty is not False:
        blocked.append("comparison code is unknown or dirty")
    if gate_report.get("verdict") == "fail":
        failed.append("regression gate failed: " + "; ".join(gate_report.get("fail_reasons", [])))
    elif gate_report.get("verdict") != "pass":
        blocked.append(f"regression gate is {gate_report.get('verdict')}")
    if gate_report.get("code_commit") != commit or gate_report.get("code_dirty") is not False:
        blocked.append(
            f"regression gate ran on {gate_report.get('code_commit')}, not clean {commit}"
        )
    _holdout(holdout_report, holdout_exception, commit, failed, blocked)
    verdict: ReleaseVerdict = "fail" if failed else "blocked" if blocked else "pass"
    return verdict, failed, blocked


def next_record(
    comparison: EvalComparison,
    thresholds: EvalThresholds,
    holdout_report: dict[str, Any] | None,
    holdout_exception: str | None,
    baseline: BaselineRecord,
    approved_by: str,
    configuration_file: str,
) -> BaselineRecord:
    number = int(baseline.id[1:]) + 1
    return BaselineRecord(
        id=f"b{number:04d}",
        configuration_file=configuration_file,
        configuration_id=comparison.candidate.id,
        configuration_digest=comparison.candidate.digest,
        basis="release_gate",
        previous=baseline.id,
        comparison_id=comparison.comparison_id,
        suite_id=comparison.suite_id,
        suite_digest=comparison.suite_digest,
        thresholds_id=thresholds.id,
        thresholds_digest=thresholds.digest,
        code_commit=comparison.code_commit,
        holdout=(holdout_report or {}).get("holdout") if holdout_report else None,
        holdout_exception=None if holdout_report else holdout_exception,
        approved_by=approved_by,
        approved_at=datetime.now(UTC).date().isoformat(),
    )


def apply(record: BaselineRecord, baselines: Path | None = None) -> None:
    """Write the new record and move the pointer, in the working tree only.

    The change takes effect when its reviewed PR is merged.
    """
    baselines = baselines or BASELINES
    path = baselines / f"{record.id}.json"
    with path.open("x") as f:  # records are never overwritten
        f.write(record.model_dump_json(indent=2) + "\n")
    pointer = {"baseline": record.id, "digest": record.digest}
    (baselines / "current.json").write_text(json.dumps(pointer, indent=2) + "\n")
