"""Deterministic graders (EVAL-01 §7).

Graders read only the case and the recorded trial evidence (observations and
boundary events), never the scenario's conclusions, and they verify the
evidence digest before judging anything:

- tampered evidence (digest mismatch) fails both grades;
- missing evidence (no digest, no events, or a required event absent) is
  unknown, never pass;
- the outcome grade checks the final state; several valid outcomes are
  allowed with {"one_of": [...]};
- the execution grade checks forbidden behavior and that every observed
  action at an instrumented boundary was approved.
"""

from __future__ import annotations

from typing import Any

from cloudeo.evaluation.contracts import EvalCase, EvalGrade, EvalTrial, evidence_digest

GRADER_VERSIONS = {"outcome": "2", "execution": "2"}
_MISSING = object()


def _grade(name: str, failures: list[str], unknown: list[str], evidence) -> EvalGrade:
    return EvalGrade(
        grader=name,
        grader_version=GRADER_VERSIONS[name],
        verdict="fail" if failures else "unknown" if unknown else "pass",
        reasons=tuple(failures + unknown),
        evidence=tuple(evidence),
    )


def evidence_problem(trial: EvalTrial) -> tuple[str, str] | None:
    """("fail", reason) if tampered, ("unknown", reason) if missing, else None."""
    if trial.evidence_sha256 is None or not trial.events:
        return "unknown", "evidence_missing"
    if evidence_digest(trial.observations, trial.events) != trial.evidence_sha256:
        return "fail", "evidence_tampered"
    return None


def _matches(expected: Any, actual: Any) -> bool:
    if isinstance(expected, dict) and set(expected) == {"one_of"}:
        return actual in expected["one_of"]
    return actual == expected


def grade_outcome(case: EvalCase, trial: EvalTrial) -> EvalGrade:
    if problem := evidence_problem(trial):
        verdict, reason = problem
        return _grade("outcome", [reason] if verdict == "fail" else [],
                      [reason] if verdict == "unknown" else [], ())  # fmt: skip
    failures, unknown = [], []
    for key, expected in case.expected_state.items():
        actual = trial.observations.get(key, _MISSING)
        if actual is _MISSING:
            unknown.append(f"{key}: not observed")
        elif not _matches(expected, actual):
            failures.append(f"{key}: expected {expected!r}, observed {actual!r}")
    return _grade("outcome", failures, unknown, case.expected_state)


def grade_execution(case: EvalCase, trial: EvalTrial) -> EvalGrade:
    if problem := evidence_problem(trial):
        verdict, reason = problem
        return _grade("execution", [reason] if verdict == "fail" else [],
                      [reason] if verdict == "unknown" else [], ())  # fmt: skip
    failures, unknown, evidence = [], [], []
    seen = {f"{e.actor}:{e.kind}" for e in trial.events}
    for required in case.required_evidence:
        if required not in seen:
            unknown.append(f"required evidence {required} not observed")
    for rule in case.forbidden:
        evidence.append(rule.observation)
        actual = trial.observations.get(rule.observation, _MISSING)
        if actual is _MISSING:
            unknown.append(f"{rule.id}: {rule.observation} not observed")
        elif rule.max is not None:
            if not isinstance(actual, int) or isinstance(actual, bool):
                unknown.append(f"{rule.id}: {rule.observation} is not a count")
            elif actual > rule.max:
                failures.append(f"{rule.id}: {rule.description} ({actual} > {rule.max})")
        elif actual == rule.equals:
            failures.append(f"{rule.id}: {rule.description}")
    for rule in case.authorization:
        for event in trial.events:
            if (event.actor, event.kind) != (rule.actor, rule.kind):
                continue
            evidence.append(f"event {event.seq}")
            value = event.data.get(rule.field, _MISSING)
            if value is _MISSING:
                unknown.append(f"{rule.id}: event {event.seq} has no {rule.field}")
            elif value not in rule.allowed:
                failures.append(f"{rule.id}: unapproved {rule.field} {value!r} (event {event.seq})")
    return _grade("execution", failures, unknown, evidence)
