"""Trial lifecycle: load and validate a suite, run each case in isolation, grade, record."""

from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import shutil
import subprocess
import sys
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path

from cloudeo.evaluation import scenarios
from cloudeo.evaluation.contracts import (
    EvalCase,
    EvalSuite,
    EvalTrial,
    Provenance,
    evidence_digest,
)
from cloudeo.evaluation.graders import GRADER_VERSIONS, grade_execution, grade_outcome
from cloudeo.evaluation.store import TrialStore

DATA = Path(__file__).parent
REPO = DATA.parents[2]
# A capability is available when its implementing module imports.
CAPABILITIES = {
    "longhorizon": "lh_harness",
    "v2_control": "cloudeo.control.model",
    "orchestration": "cloudeo.orchestration.execution_failure",
}


class ManifestError(ValueError):
    pass


def load_suite(suite_id: str, data: Path = DATA) -> tuple[EvalSuite, list[EvalCase]]:
    """The suite and its exact case revisions; any digest mismatch is refused."""
    suite = EvalSuite.model_validate_json((data / "suites" / f"{suite_id}.json").read_text())
    if suite.grader_versions != GRADER_VERSIONS:
        raise ManifestError(
            f"suite pins graders {suite.grader_versions}, this code has {GRADER_VERSIONS}"
        )
    cases = []
    for entry in suite.cases:
        path = data / "cases" / f"{entry.case_id}.r{entry.revision}.json"
        case = EvalCase.model_validate_json(path.read_text())
        if (case.id, case.revision) != (entry.case_id, entry.revision):
            raise ManifestError(f"{path.name} does not hold {entry.case_id} r{entry.revision}")
        if case.digest != entry.case_digest:
            raise ManifestError(f"{entry.case_id} r{entry.revision}: case digest mismatch")
        if case.entry_point not in scenarios.SCENARIOS:
            raise ManifestError(f"{case.id}: unknown entry point {case.entry_point!r}")
        cases.append(case)
    return suite, cases


def capabilities() -> dict[str, bool]:
    def available(module: str) -> bool:
        try:
            return importlib.util.find_spec(module) is not None
        except ModuleNotFoundError:
            return False

    return {name: available(module) for name, module in CAPABILITIES.items()}


def _code_state() -> tuple[str | None, bool | None, str | None]:
    lock = REPO / "uv.lock"
    lock_sha = hashlib.sha256(lock.read_bytes()).hexdigest() if lock.is_file() else None
    try:
        commit = subprocess.run(
            ["git", "-C", str(REPO), "rev-parse", "HEAD"], capture_output=True, text=True,
            check=True).stdout.strip()  # fmt: skip
        dirty = bool(subprocess.run(
            ["git", "-C", str(REPO), "status", "--porcelain", "--untracked-files=no"],
            capture_output=True, text=True, check=True).stdout.strip())  # fmt: skip
    except (OSError, subprocess.CalledProcessError):
        return None, None, lock_sha  # unknown, never guessed
    return commit, dirty, lock_sha


async def run_suite(
    suite_id: str,
    out: Path,
    *,
    repetitions: int = 1,
    label: str = "baseline",
    data: Path = DATA,
) -> tuple[str, list[EvalTrial]]:
    suite, cases = load_suite(suite_id, data)
    store = TrialStore(out)
    run_id = uuid.uuid4().hex
    store.mark_abandoned(run_id)
    caps = capabilities()
    commit, dirty, lock_sha = _code_state()
    for repetition in range(1, repetitions + 1):
        for case in cases:
            provenance = Provenance(
                code_commit=commit, code_dirty=dirty, python=sys.version.split()[0],
                uv_lock_sha256=lock_sha, suite_id=suite.id, suite_version=suite.version,
                suite_digest=suite.digest, case_digest=case.digest,
                fixture_digest=case.fixture_digest, grader_versions=dict(GRADER_VERSIONS),
                capabilities=caps,
            )  # fmt: skip
            await _run_trial(store, run_id, suite, case, repetition, label, provenance, caps)
    return run_id, store.trials(run_id)


async def _run_trial(store, run_id, suite, case, repetition, label, provenance, caps) -> None:
    trial = EvalTrial(
        trial_id=uuid.uuid4().hex, run_id=run_id, suite_id=suite.id, case_id=case.id,
        case_revision=case.revision, repetition=repetition, label=label, status="running",
        started_at=datetime.now(UTC), provenance=provenance,
    )  # fmt: skip
    store.start(trial)

    def done(**update) -> None:
        store.finish(trial.model_copy(update={"finished_at": datetime.now(UTC), **update}))

    missing = [c for c in case.required_capabilities if not caps.get(c)]
    if missing:
        done(status="unsupported", error=f"missing capabilities: {', '.join(missing)}")
        return
    workdir = Path(tempfile.mkdtemp(prefix=f"cloudeo-eval-{case.id}-"))
    recorder = scenarios.Recorder()
    try:
        observations, completeness = await scenarios.SCENARIOS[case.entry_point](
            case.fixture, workdir, recorder
        )
    except (KeyboardInterrupt, asyncio.CancelledError):
        done(status="interrupted", events=tuple(recorder.events), error="interrupted")
        raise
    except Exception as exc:  # noqa: BLE001 - infrastructure-invalid; recorded, never a pass
        done(status="error", events=tuple(recorder.events), error=f"{type(exc).__name__}: {exc}")
        return
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    events = tuple(recorder.events)
    recorded = trial.model_copy(
        update={
            "status": "completed",
            "observations": observations,
            "events": events,
            "trace_completeness": completeness,
            "evidence_sha256": evidence_digest(observations, events),
        }
    )
    # Graded from the recorded evidence, exactly as a later regrade would be.
    store.finish(
        recorded.model_copy(
            update={
                "finished_at": datetime.now(UTC),
                "outcome_grade": grade_outcome(case, recorded),
                "execution_grade": grade_execution(case, recorded),
            }
        )
    )


def verify_store(out: Path, data: Path = DATA) -> list[tuple[EvalTrial, list[str]]]:
    """Regrade every stored trial from its retained evidence file.

    A trial is reported when its file differs from the index, its evidence
    digest does not match, or regrading gives a different verdict.
    """
    store = TrialStore(out)
    cases = {}
    report = []
    for indexed in store.trials():
        problems = []
        path = out / "trials" / f"{indexed.trial_id}.json"
        if indexed.status == "running":
            continue
        if not path.is_file():
            report.append((indexed, ["evidence file missing"]))
            continue
        retained = EvalTrial.model_validate_json(path.read_text())
        if retained != indexed:
            problems.append("evidence file differs from the index")
        if retained.status == "completed":
            key = (retained.suite_id, retained.case_id)
            if key not in cases:
                cases.update(
                    {(retained.suite_id, c.id): c for c in load_suite(retained.suite_id, data)[1]}
                )
            case = cases[key]
            regraded = (grade_outcome(case, retained), grade_execution(case, retained))
            if regraded != (retained.outcome_grade, retained.execution_grade):
                problems.append(
                    "regrade differs: " + "; ".join(r for g in regraded for r in g.reasons)
                )
        if problems:
            report.append((retained, problems))
    return report
