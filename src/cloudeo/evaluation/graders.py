"""Deterministic graders (EVAL-01 §7).

Both graders read only the case and the trial's recorded observations, never
the scenario's own conclusions. The outcome grader checks the final state; the
execution grader checks forbidden behavior. A missing observation is unknown.
"""

from __future__ import annotations

from typing import Any

from cloudeo.evaluation.contracts import EvalCase, EvalGrade

GRADER_VERSIONS = {"outcome-v1": "1", "execution-v1": "1"}
_MISSING = object()


def _get(observations: dict[str, Any], key: str) -> Any:
    return observations.get(key, _MISSING)


def grade_outcome(case: EvalCase, observations: dict[str, Any]) -> EvalGrade:
    failures, unknown = [], []
    for key, expected in case.expected_state.items():
        actual = _get(observations, key)
        if actual is _MISSING:
            unknown.append(f"{key}: not observed")
        elif actual != expected:
            failures.append(f"{key}: expected {expected!r}, observed {actual!r}")
    verdict = "fail" if failures else "unknown" if unknown else "pass"
    return EvalGrade(
        grader="outcome-v1",
        grader_version=GRADER_VERSIONS["outcome-v1"],
        verdict=verdict,
        reasons=tuple(failures + unknown),
        evidence=tuple(case.expected_state),
    )


def grade_execution(case: EvalCase, observations: dict[str, Any]) -> EvalGrade:
    failures, unknown = [], []
    for rule in case.forbidden:
        actual = _get(observations, rule.observation)
        if actual is _MISSING:
            unknown.append(f"{rule.id}: {rule.observation} not observed")
        elif rule.max is not None:
            if not isinstance(actual, int) or isinstance(actual, bool):
                unknown.append(f"{rule.id}: {rule.observation} is not a count")
            elif actual > rule.max:
                failures.append(f"{rule.id}: {rule.description} ({actual} > {rule.max})")
        elif actual == rule.equals:
            failures.append(f"{rule.id}: {rule.description}")
    verdict = "fail" if failures else "unknown" if unknown else "pass"
    return EvalGrade(
        grader="execution-v1",
        grader_version=GRADER_VERSIONS["execution-v1"],
        verdict=verdict,
        reasons=tuple(failures + unknown),
        evidence=tuple(rule.observation for rule in case.forbidden),
    )
