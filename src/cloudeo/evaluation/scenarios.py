"""Scenarios: run one case through a production entry point with fake external boundaries.

Each scenario gets a fresh working directory and an event recorder, builds its
fixture there, calls the real Cloudeo entry point, and returns observations:
flat key -> JSON value. Only external boundaries are faked (Treg, Jev, the UHP
server, the auditor model). Scenarios observe; graders judge.
"""

from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from cloudeo.evaluation.contracts import EvidenceEvent


class Recorder:
    def __init__(self) -> None:
        self.events: list[EvidenceEvent] = []

    def __call__(self, actor: str, kind: str, **data: Any) -> None:
        self.events.append(EvidenceEvent(seq=len(self.events), actor=actor, kind=kind, data=data))

    def count(self, actor: str, kind: str) -> int:
        return sum(1 for e in self.events if e.actor == actor and e.kind == kind)


# (fixture, workdir, recorder) -> (observations, trace completeness)
Scenario = Callable[[dict[str, Any], Path, Recorder], Awaitable[tuple[dict[str, Any], str]]]
SCENARIOS: dict[str, Scenario] = {}


def scenario(entry_point: str):
    def register(fn: Scenario) -> Scenario:
        SCENARIOS[entry_point] = fn
        return fn

    return register


# --- core.controller.run: Treg and Jev faked, everything else real ---


@scenario("core.controller.run")
async def controller_run(fixture, workdir, record):
    from sqlmodel import select

    from cloudeo.adapters.jev import MockJevClient
    from cloudeo.adapters.treg import TregClient
    from cloudeo.config import Settings
    from cloudeo.core.controller import Controller
    from cloudeo.db.models import RunRecord
    from cloudeo.db.session import Database
    from cloudeo.models import RunRequest

    outputs = {
        tool: value if isinstance(value, str) else json.dumps(value, sort_keys=True)
        for tool, value in fixture["tool_outputs"].items()
    }

    class FakeTreg(TregClient):
        async def execute(self, candidate, dry_run=False):
            record("treg", "execute", tool_id=candidate.id, treg_tool_id=candidate.treg_tool_id,
                   dry_run=dry_run)  # fmt: skip
            return outputs.get(candidate.id, "TREG_ERROR: no such tool in the fixture")

        async def discover(self, request):
            record("treg", "discover")
            return []

    class RecordingJev(MockJevClient):
        async def decide(self, state, questions):
            if "tool_route" in questions:
                record("jev", "route")
            else:
                record("jev", "verify", tool_output=state["tool_output"])
            return await super().decide(state, questions)

    # No .env, no shared database: the trial owns its whole environment.
    settings = Settings(_env_file=None, database_url=f"sqlite+aiosqlite:///{workdir}/runs.db")
    database = Database(settings)
    await database.init()
    try:
        response = await Controller(settings, RecordingJev(), FakeTreg(), database).run(
            RunRequest.model_validate(fixture["request"])
        )
        async with database.session() as session:
            rows = (await session.exec(select(RunRecord))).all()
        record("db", "run_records", rows=[[r.id, r.status] for r in rows])
    finally:
        await database.engine.dispose()

    verified = [e.data["tool_output"] for e in record.events if e.kind == "verify"]
    observations = {
        "response.status": response.status,
        "response.selected_tool": response.selected_tool,
        "attempts.tool_ids": [a.tool_id for a in response.attempts],
        "attempts.deterministic_status": [a.deterministic_status for a in response.attempts],
        "attempts.verification_source": [a.verification_source for a in response.attempts],
        "treg.execute_calls": record.count("treg", "execute"),
        "treg.discover_calls": record.count("treg", "discover"),
        "jev.route_calls": record.count("jev", "route"),
        "jev.verify_calls": record.count("jev", "verify"),
        "run_record.persisted": [(r.id, r.status) for r in rows]
        == [(response.run_id, response.status)],
    }
    # Judged against the case's own oracle, not Cloudeo's validation labels,
    # so a broken validator cannot hide what reached Jev.
    if "oracle_invalid_tools" in fixture:
        invalid = {outputs[tool] for tool in fixture["oracle_invalid_tools"]}
        observations["jev.verified_oracle_invalid"] = sum(o in invalid for o in verified)
    return observations, "complete"


# --- UHP dispatch + orchestration failure mapping: the UHP server is faked ---


@scenario("execution.uhp_dispatch_failure")
async def uhp_dispatch_failure(fixture, workdir, record):
    import httpx

    from cloudeo.control.model import AgentProfile, Role
    from cloudeo.execution.contracts import HarnessTaskExecution
    from cloudeo.execution.dispatch import ExecutionDispatcher
    from cloudeo.execution.uhp_backend import UHPHarnessTaskBackend
    from cloudeo.orchestration.execution_failure import assess_execution_failure
    from cloudeo.uhp.client import UHPClient
    from cloudeo.uhp.models import UHPTaskRequest

    reply = fixture["server_reply"]

    def server(request: httpx.Request) -> httpx.Response:
        record("uhp_server", "request", method=request.method, path=request.url.path)
        return httpx.Response(reply["status_code"], json=reply["body"])

    client = UHPClient(
        "http://uhp.eval/api/harness", "eval-not-a-real-key", transport=httpx.MockTransport(server)
    )
    dispatcher = ExecutionDispatcher(harness_task=UHPHarnessTaskBackend(client))
    async with client:
        outcome = await dispatcher.execute(
            HarnessTaskExecution(task=UHPTaskRequest.model_validate(fixture["task"]))
        )
    profile = AgentProfile.model_validate(fixture["profile"])
    assessment = assess_execution_failure(outcome, role=Role(fixture["role"]), profile=profile.ref)
    task_posts = sum(
        1
        for e in record.events
        if e.data.get("method") == "POST" and e.data.get("path", "").endswith("/v1/responses")
    )
    condition = assessment.condition_if_established
    return {
        "outcome.status": outcome.status,
        "outcome.error_class": outcome.error.error_class if outcome.error else None,
        "outcome.runtime.actual_model": outcome.runtime.actual_model,
        "uhp.task_posts": task_posts,
        "assessment.second_execution_safe": assessment.second_execution_safe,
        "assessment.attention_code": str(assessment.attention.code),
        "assessment.condition_if_established": None if condition is None else str(condition),
    }, "complete"


# --- Promotion gate: real Git broker; the auditor's verdict is the faked boundary ---


@contextmanager
def isolated_git(workdir: Path) -> Iterator[None]:
    config = workdir / "gitconfig"
    config.write_text("")
    keys = ("GIT_CONFIG_GLOBAL", "GIT_CONFIG_NOSYSTEM", "HOME", "GIT_DIR", "GIT_WORK_TREE",
            "GIT_INDEX_FILE")  # fmt: skip
    saved = {k: os.environ.get(k) for k in keys}
    for key in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"):
        os.environ.pop(key, None)
    os.environ.update(GIT_CONFIG_GLOBAL=str(config), GIT_CONFIG_NOSYSTEM="1", HOME=str(workdir))
    try:
        yield
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _git(cwd: Path, *args: str) -> str:
    identity = ["-c", "user.name=Cloudeo Eval", "-c", "user.email=eval@example.invalid"]
    return subprocess.run(
        ["git", "-C", str(cwd), *identity, *args], capture_output=True, text=True, check=True
    ).stdout.strip()


def _write(root: Path, files: dict[str, str]) -> None:
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)


@scenario("longhorizon.promotion_gate")
async def promotion_gate(fixture, workdir, record):
    from cloudeo.bridge.audit import current_content_sha256
    from cloudeo.bridge.models import BridgeLimits
    from cloudeo.longhorizon.audit_result import AuditorVerification
    from cloudeo.longhorizon.promotion_gate import checkpoint_and_promote_verified
    from cloudeo.workspace.git import GitWorkspaceBroker

    with isolated_git(workdir):
        repo = workdir / "canonical"
        repo.mkdir()
        _git(repo, "init", "-q", "-b", "main")
        _write(repo, fixture["files"])
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "initial")
        broker = GitWorkspaceBroker.initialize(
            repo, "eval", _git(repo, "rev-parse", "HEAD"), workdir / "candidates"
        )
        accepted_before = broker.accepted_state().accepted_commit
        candidate = broker.create_candidate(broker.accepted_state())

        _write(candidate.local_path, fixture["executor_changes"])
        record("executor", "write", paths=sorted(fixture["executor_changes"]))

        head = broker.inspect_candidate(candidate).head_commit
        content = current_content_sha256(candidate, BridgeLimits())
        # Faked boundary: a clean, complete, read-only audit of exactly this state.
        verification = AuditorVerification(
            status="VERIFIED",
            reason="report_complete",
            episode_status="completed",
            verifier_workspace_mutation_detected=False,
            upstream_metadata={
                "workspace_id": candidate.workspace_id,
                "candidate_id": candidate.candidate_id,
                "candidate_base_commit": candidate.base_commit,
                "audit_snapshot_head": head,
                "audit_snapshot_content_sha256": content,
                "audit_snapshot_unchanged": True,
                "accepted_state_unchanged": True,
                "auditor_remote_workspace_unchanged": True,
            },
        )
        record("auditor", "verified", producer="synthetic_fixture", head=head, content=content)

        _write(candidate.local_path, fixture["post_audit_changes"])
        record("executor", "write", paths=sorted(fixture["post_audit_changes"]))

        result = checkpoint_and_promote_verified(
            broker, candidate, verification, message="eval promotion"
        )
        record("gate", "decision", status=result.decision.status, stage=result.stage)
        refs = _git(repo, "for-each-ref", "--format=%(refname)", "refs/cloudeo").splitlines()
        accepted_after = broker.accepted_state().accepted_commit
        record("git", "refs", refs=refs, accepted_before=accepted_before,
               accepted_after=accepted_after)  # fmt: skip

    return {
        "gate.status": result.decision.status,
        "gate.reason": result.decision.reason,
        "gate.stage": result.stage,
        "gate.promoted": result.promoted,
        "accepted.unchanged": accepted_after == accepted_before,
        "checkpoint.refs_created": sum("/checkpoints/" in r for r in refs),
        "audit.producer": "synthetic_fixture",
    }, "partial"  # the auditor episode itself is not exercised here


# --- Billing policy at project-profile approval and at runtime observation ---


@scenario("control.billing_approval")
async def billing_approval(fixture, workdir, record):
    from datetime import datetime

    from pydantic import ValidationError

    from cloudeo.control.model import (
        AgentProfile,
        BillingMode,
        BillingPolicy,
        FallbackCondition,
        ProjectExecutionProfile,
        Role,
        RoleBinding,
        observed_billing,
    )
    from cloudeo.control.store import NotFoundError, SqliteControlStore

    store = SqliteControlStore(workdir / "control.db")
    primary = AgentProfile.model_validate(fixture["primary"])
    fallback = AgentProfile.model_validate(fixture["fallback"])
    for profile in (primary, fallback):
        store.register_profile(profile)

    refusal = None
    try:
        project = ProjectExecutionProfile(
            project_id="eval",
            version=1,
            bindings=(
                RoleBinding(
                    role=Role.PRIMARY_CODE_EXECUTOR,
                    primary=primary.ref,
                    fallbacks=(fallback.ref,),
                    fallback_conditions=frozenset({FallbackCondition.MODEL_UNAVAILABLE}),
                ),
            ),
            profiles=(primary, fallback),
            billing_policy=BillingPolicy.model_validate(fixture["billing_policy"]),
            approved_by="eval",
            approved_at=datetime.fromisoformat(fixture["approved_at"]),
        )
        store.save_profile(project)
        record("control", "approval", outcome="approved")
    except ValidationError as exc:
        refusal = str(exc)
        record("control", "approval", outcome="refused", message=refusal)

    try:
        store.current_profile("eval")
        saved = True
    except NotFoundError:
        saved = False

    def judge(observed: str | None) -> str:
        return observed_billing(primary, None if observed is None else BillingMode(observed))

    rule = None
    if refusal is not None:
        rule = (
            "metered_fallback_not_approved"
            if "needs allow_metered_fallback" in refusal
            else "other"
        )
    return {
        "approval.refused": refusal is not None,
        "approval.refusal_rule": rule,
        "store.project_profile_saved": saved,
        "billing.observed_metered_api": judge("metered_api"),
        "billing.observed_unreported": judge(None),
    }, "complete"
