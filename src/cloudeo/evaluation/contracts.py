"""EVAL-01 contracts: cases, suites, trials and grades (docs/EVAL-01_PLAN.md §4).

Evaluation records are separate from operational run and control records. A
value that was not observed stays None or "unknown"; it is never inferred from
what was requested.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Identifier = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,63}$")
Sha256 = Field(pattern=r"^[0-9a-f]{64}$")

Verdict = Literal["pass", "fail", "unknown"]
Partition = Literal["regression", "capability", "holdout"]
Severity = Literal["critical", "major", "minor"]
# "unsupported": a required capability is absent in this environment.
# "interrupted": the trial started but the runner stopped before it finished.
# "error": the scenario raised; the trial is infrastructure-invalid, not a pass.
TrialStatus = Literal["running", "completed", "unsupported", "interrupted", "error"]


def canonical_sha256(data: Any) -> str:
    encoded = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("ascii")).hexdigest()


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Forbidden(_Frozen):
    """A behavior the trial must not show, judged from one observation.

    Exactly one of `equals` or `max` is set. A missing observation grades
    unknown, never pass.
    """

    id: str = Identifier
    observation: str
    equals: Any = None
    max: int | None = None
    description: str

    @model_validator(mode="after")
    def _one_predicate(self):
        if (self.equals is None) == (self.max is None):
            raise ValueError("set exactly one of equals or max")
        return self


class AuthorizationRule(_Frozen):
    """Every event from `actor` of `kind` must carry `field` with an approved value."""

    id: str = Identifier
    actor: str
    kind: str
    field: str
    allowed: tuple[Any, ...]


class EvalCase(_Frozen):
    id: str = Identifier
    revision: int = Field(ge=1)
    task: str
    entry_point: str
    # Scenario inputs; the fixture digest covers exactly this.
    fixture: dict[str, Any]
    required_capabilities: tuple[str, ...] = ()
    # Approved permissions, profiles and billing the scenario may use.
    approvals: dict[str, Any] = Field(default_factory=dict)
    budgets: dict[str, Any] = Field(default_factory=dict)
    # Observation key -> required value, or {"one_of": [...]} when several
    # outcomes are valid (alternative routes). Missing observations grade unknown.
    expected_state: dict[str, Any]
    forbidden: tuple[Forbidden, ...] = ()
    authorization: tuple[AuthorizationRule, ...] = ()
    # "actor:kind" events that must be present; without them the side-effect
    # boundary was not observed and the execution grade cannot pass.
    required_evidence: tuple[str, ...] = ()
    graders: tuple[str, ...] = ("outcome", "execution")
    partition: Partition
    severity: Severity
    mode: Literal["deterministic", "live", "both"] = "deterministic"

    @property
    def fixture_digest(self) -> str:
        return canonical_sha256(self.fixture)

    @property
    def digest(self) -> str:
        return canonical_sha256(self.model_dump(mode="json"))


class SuiteEntry(_Frozen):
    case_id: str = Identifier
    revision: int = Field(ge=1)
    case_digest: str = Sha256
    # Holdout content lives in restricted storage outside the repository; the
    # manifest carries only its ID, revision and digest.
    holdout: bool = False


class EvalSuite(_Frozen):
    """An immutable manifest of exact case revisions."""

    id: str = Identifier
    version: int = Field(ge=1)
    description: str
    cases: tuple[SuiteEntry, ...] = Field(min_length=1)
    grader_versions: dict[str, str]

    @model_validator(mode="after")
    def _unique(self):
        ids = [entry.case_id for entry in self.cases]
        if len(ids) != len(set(ids)):
            raise ValueError("a suite lists each case once")
        return self

    @property
    def digest(self) -> str:
        return canonical_sha256(self.model_dump(mode="json"))


class EvalGrade(_Frozen):
    grader: str
    grader_version: str
    verdict: Verdict
    reasons: tuple[str, ...] = ()
    # Observation keys the verdict relied on.
    evidence: tuple[str, ...] = ()


class Provenance(_Frozen):
    code_commit: str | None
    code_dirty: bool | None
    python: str
    uv_lock_sha256: str | None
    suite_id: str
    suite_version: int
    suite_digest: str
    case_digest: str
    fixture_digest: str
    partition: Partition | None = None
    severity: Severity | None = None
    grader_versions: dict[str, str]
    capabilities: dict[str, bool]


class EvidenceEvent(_Frozen):
    """One ordered, observable event at an instrumented boundary."""

    seq: int = Field(ge=0)
    actor: str
    kind: str
    data: dict[str, Any] = Field(default_factory=dict)


def evidence_digest(observations: dict[str, Any], events: tuple[EvidenceEvent, ...]) -> str:
    return canonical_sha256(
        {"observations": observations, "events": [e.model_dump(mode="json") for e in events]}
    )


class EvalTrial(_Frozen):
    trial_id: str
    run_id: str
    suite_id: str
    case_id: str
    case_revision: int
    repetition: int = Field(ge=1)
    label: str
    status: TrialStatus
    started_at: datetime
    finished_at: datetime | None = None
    provenance: Provenance
    observations: dict[str, Any] = Field(default_factory=dict)
    events: tuple[EvidenceEvent, ...] = ()
    # SHA-256 over the canonical observations and events, fixed when recorded.
    evidence_sha256: str | None = None
    # "complete" only when every surface the case grades was instrumented.
    trace_completeness: Literal["complete", "partial", "unavailable"] = "unavailable"
    outcome_grade: EvalGrade | None = None
    execution_grade: EvalGrade | None = None
    error: str | None = None

    @property
    def verdict(self) -> Verdict:
        """Overall success needs both grades to pass; any fail is a fail."""
        grades = (self.outcome_grade, self.execution_grade)
        if any(g is not None and g.verdict == "fail" for g in grades):
            return "fail"
        if all(g is not None and g.verdict == "pass" for g in grades):
            return "pass"
        return "unknown"
