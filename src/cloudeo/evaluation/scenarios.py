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
    from cloudeo.adapters.treg import TregClient, TregError
    from cloudeo.config import Settings
    from cloudeo.core.controller import Controller
    from cloudeo.db.models import RunRecord
    from cloudeo.db.session import Database
    from cloudeo.models import RunRequest, ToolCandidate

    # A tool output is text, JSON, or {"raise": message} for a Treg failure.
    def as_output(value):
        if isinstance(value, dict) and set(value) == {"raise"}:
            return value
        return value if isinstance(value, str) else json.dumps(value, sort_keys=True)

    outputs = {tool: as_output(value) for tool, value in fixture["tool_outputs"].items()}

    class FakeTreg(TregClient):
        async def execute(self, candidate, dry_run=False):
            record("treg", "execute", tool_id=candidate.id, treg_tool_id=candidate.treg_tool_id,
                   dry_run=dry_run)  # fmt: skip
            output = outputs.get(candidate.id, {"raise": "no such tool in the fixture"})
            if isinstance(output, dict):
                raise TregError(output["raise"])
            return output

        async def discover(self, request):
            found = [ToolCandidate.model_validate(c) for c in fixture.get("discovered", [])]
            record("treg", "discover", found=[c.treg_tool_id for c in found])
            return found

    class RecordingJev(MockJevClient):
        async def decide(self, state, questions):
            if "tool_route" in questions:
                record("jev", "route")
                route = fixture.get("jev_route")  # the model's routing answer, as fixture data
                # A model can only pick among the choices Cloudeo offered it.
                if route and route["choice"] in questions["tool_route"]["criteria"]:
                    return {"answers": {"tool_route": dict(route)}}
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
        if rows:  # the event exists only when there is something persisted
            record("db", "run_records", rows=[[r.id, r.status] for r in rows])
        stored = "".join(r.payload_json + r.result_json for r in rows)
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
    if "synthetic_secret" in fixture:
        observations["run_record.contains_secret"] = fixture["synthetic_secret"] in stored
    return observations, "complete"


# --- UHP dispatch + orchestration failure mapping: the UHP server is faked ---


def _harness(payload: dict) -> str | None:
    return payload.get("metadata", {}).get("harness_id")


def _uhp_body(fixture_result: dict, payload: dict, n: int) -> dict:
    return {
        "id": f"resp_eval_{n}", "object": "response", "created_at": 1786400000,
        "status": "completed", "model": payload.get("model", "m"), "output": [],
        "error": None, "incomplete_details": None, "usage": None, "metadata": {},
        "previous_response_id": payload.get("previous_response_id"), **fixture_result,
    }  # fmt: skip


@scenario("execution.uhp_dispatch")
@scenario("execution.uhp_dispatch_failure")  # smoke suites name it this way
async def uhp_dispatch(fixture, workdir, record):
    """One HarnessTaskExecution through the real dispatcher and UHP client, then
    orchestration's failure assessment when the outcome is a failure."""
    import httpx

    from cloudeo.control.model import AgentProfile, Role
    from cloudeo.execution.contracts import HarnessTaskExecution
    from cloudeo.execution.dispatch import ExecutionDispatcher
    from cloudeo.execution.uhp_backend import UHPHarnessTaskBackend
    from cloudeo.orchestration.execution_failure import (
        FAILURE_STATUSES,
        assess_execution_failure,
    )
    from cloudeo.uhp.client import UHPClient
    from cloudeo.uhp.models import UHP_VERSION, UHPTaskRequest

    headers = {"UHP-Version": UHP_VERSION}  # a conforming server always sends it
    # Replies in order (the last one repeats), or per harness. {"result": {...}} is a 200.
    by_harness = fixture.get("replies_by_harness", {})
    replies = fixture.get("server_replies") or [fixture.get("server_reply")]
    posts: list[dict] = []

    def server(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content) if request.content else {}
        record("uhp_server", "request", method=request.method, path=request.url.path,
               harness_id=payload.get("metadata", {}).get("harness_id"),
               previous_response_id=payload.get("previous_response_id"))  # fmt: skip
        if request.method == "GET" and request.url.path in fixture.get("get_replies", {}):
            # Discovery or health evidence the runtime offers before any dispatch.
            body = fixture["get_replies"][request.url.path]
            return httpx.Response(200, json=body, headers=headers)
        if request.method == "POST" and request.url.path.endswith("/v1/responses"):
            posts.append(payload)
        harness = payload.get("metadata", {}).get("harness_id")
        reply = by_harness.get(harness) or replies[min(len(posts), len(replies)) - 1]
        if "result" in reply:
            body = _uhp_body(reply["result"], payload, len(posts))
            return httpx.Response(200, json=body, headers=headers)
        return httpx.Response(reply["status_code"], json=reply["body"], headers=headers)

    client = UHPClient(
        "http://uhp.eval/api/harness", "eval-not-a-real-key", transport=httpx.MockTransport(server)
    )
    dispatcher = ExecutionDispatcher(harness_task=UHPHarnessTaskBackend(client))
    task = UHPTaskRequest.model_validate(fixture["task"])
    record("cloudeo", "dispatch_requested", harness_id=task.harness_id)
    # Raw dispatch has no authorization step; any exception here is an
    # infrastructure error, never mistaken for a policy refusal.
    async with client:
        outcome = await dispatcher.execute(HarnessTaskExecution(task=task))
    runtime = outcome.runtime
    fallback = fixture.get("approved_fallback_harness")
    observations = {
        "outcome.status": outcome.status,
        "outcome.error_class": outcome.error.error_class if outcome.error else None,
        "outcome.runtime.actual_model": runtime.actual_model,
        "outcome.runtime.model_fallback": runtime.model_fallback,
        "uhp.task_posts": len(posts),
        "uhp.primary_posts": sum(_harness(p) == task.harness_id for p in posts),
        "uhp.fallback_posts": sum(fallback is not None and _harness(p) == fallback for p in posts),
        "uhp.resumed_posts": sum(1 for p in posts if p.get("previous_response_id")),
        # A retry must resend exactly the same task (harness, model, input).
        "uhp.repeats_identical": all(p == posts[0] for p in posts),
    }
    # Control-owned decisions (identity acceptance, dispatch authorization,
    # fallback, retry) have no Cloudeo entry point yet, so "identity.decision"
    # and "control.*" keys are never observed here. Capability cases that need
    # them cannot pass until revised to the real entry point.
    if "synthetic_secret" in fixture:
        observations["output.contains_secret"] = fixture["synthetic_secret"] in (
            outcome.output_text or ""
        )
    if outcome.status in FAILURE_STATUSES:
        profile = AgentProfile.model_validate(fixture["profile"])
        assessment = assess_execution_failure(
            outcome, role=Role(fixture["role"]), profile=profile.ref
        )
        condition = assessment.condition_if_established
        observations.update({
            "assessment.second_execution_safe": assessment.second_execution_safe,
            "assessment.attention_code": str(assessment.attention.code),
            "assessment.condition_if_established": None if condition is None else str(condition),
        })  # fmt: skip
    return observations, "complete"


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


def _git_bytes(cwd: Path, *args: str) -> str:
    """Raw file content (no strip), so the oracle compares exact bytes."""
    return subprocess.run(
        ["git", "-C", str(cwd), *args], capture_output=True, text=True, check=True
    ).stdout


def _write(root: Path, files: dict[str, str]) -> None:
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)


def _gate_project(fixture, workdir, record):
    """A canonical repo, its broker, and a candidate carrying the executor's work."""
    from cloudeo.workspace.git import GitWorkspaceBroker

    repo = workdir / "canonical"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _write(repo, fixture["files"])
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "initial")
    broker = GitWorkspaceBroker.initialize(
        repo, "eval", _git(repo, "rev-parse", "HEAD"), workdir / "candidates"
    )
    candidate = broker.create_candidate(broker.accepted_state())
    _write(candidate.local_path, fixture["executor_changes"])
    # Local files the project ignores (e.g. .env); they must never leave the machine.
    _write(candidate.local_path, fixture.get("candidate_ignored_files", {}))
    record("executor", "write", paths=sorted(fixture["executor_changes"]))
    return repo, broker, candidate


def _after_audit(fixture, repo, broker, candidate, record) -> str:
    """What happens between the audit and the gate; returns accepted state just before the gate."""
    if fixture.get("post_audit_changes"):
        _write(candidate.local_path, fixture["post_audit_changes"])
        record("executor", "write", paths=sorted(fixture["post_audit_changes"]))
    if fixture.get("post_audit_commit"):
        _git(candidate.local_path, "add", "-A")
        _git(candidate.local_path, "commit", "-q", "-m", "after audit")
        record("executor", "commit")
    if fixture.get("advance_accepted"):
        other = broker.create_candidate(broker.accepted_state())
        _write(other.local_path, fixture["advance_accepted"])
        broker.promote(broker.checkpoint_candidate(other, "another change"))
        record("broker", "promote", candidate_id=other.candidate_id)
    return broker.accepted_state().accepted_commit


def _gate(repo, broker, candidate, verification, accepted_before, record):
    from cloudeo.longhorizon.promotion_gate import checkpoint_and_promote_verified

    result = checkpoint_and_promote_verified(
        broker, candidate, verification, message="eval promotion"
    )
    record("gate", "decision", status=result.decision.status, stage=result.stage)
    refs = _git(repo, "for-each-ref", "--format=%(refname)", "refs/cloudeo").splitlines()
    accepted_after = broker.accepted_state().accepted_commit
    record("git", "refs", refs=refs, accepted_before=accepted_before,
           accepted_after=accepted_after)  # fmt: skip
    checkpoint = result.checkpoint.commit if result.checkpoint else None
    # Read accepted state from Git directly, not from the gate's own result.
    paths = _git(repo, "ls-tree", "-r", "--name-only", accepted_after).splitlines()
    accepted_files = {p: _git_bytes(repo, "show", f"{accepted_after}:{p}") for p in paths}
    return {
        "accepted.files": accepted_files,
        # A promotion's commit sits directly on the base the candidate started from.
        "accepted.parent_is_base": _git(
            repo, "rev-list", "--parents", "-n1", accepted_after
        ).split()[1:]
        == [candidate.base_commit],
        "gate.status": result.decision.status,
        "gate.reason": result.decision.reason,
        "gate.stage": result.stage,
        "gate.promoted": result.promoted,
        "accepted.unchanged": accepted_after == accepted_before,
        "accepted.is_checkpoint": checkpoint is not None and accepted_after == checkpoint,
        # Only this candidate's checkpoints; other promotions have their own.
        "checkpoint.refs_created": sum(
            f"/candidates/{candidate.candidate_id}/checkpoints/" in r for r in refs
        ),
    }


@scenario("longhorizon.promotion_gate")
async def promotion_gate(fixture, workdir, record):
    """The gate with a synthetic auditor verdict (trace partial)."""
    from cloudeo.bridge.audit import current_content_sha256
    from cloudeo.bridge.models import BridgeLimits
    from cloudeo.longhorizon.audit_result import AuditorVerification

    with isolated_git(workdir):
        repo, broker, candidate = _gate_project(fixture, workdir, record)
        head = broker.inspect_candidate(candidate).head_commit
        content = current_content_sha256(candidate, BridgeLimits())
        metadata = {
            "workspace_id": candidate.workspace_id,
            "candidate_id": candidate.candidate_id,
            "candidate_base_commit": candidate.base_commit,
            "audit_snapshot_head": head,
            "audit_snapshot_content_sha256": content,
            "audit_snapshot_unchanged": True,
            "accepted_state_unchanged": True,
            "auditor_remote_workspace_unchanged": True,
        }
        # A producer that did not supply part of its evidence.
        for key in fixture.get("omit_audit_metadata", ()):
            metadata.pop(key)
        # Faked boundary: a clean, complete, read-only audit of exactly this state.
        verification = AuditorVerification(
            status="VERIFIED",
            reason="report_complete",
            episode_status="completed",
            verifier_workspace_mutation_detected=False,
            upstream_metadata=metadata,
        )
        record("auditor", "verified", producer="synthetic_fixture", head=head, content=content)
        accepted_before = _after_audit(fixture, repo, broker, candidate, record)
        observations = _gate(repo, broker, candidate, verification, accepted_before, record)
    return {**observations, "audit.producer": "synthetic_fixture"}, "partial"


@scenario("longhorizon.audit_then_promotion_gate")
async def audit_then_promotion_gate(fixture, workdir, record):
    """The real read-only auditor episode, then the gate. Only the model is faked:
    the offline HarnessRouter returns the fixture's audit report."""
    import gzip

    import httpx
    from lh_harness.role_prompts import MANAGER_NEXT_CLI, build_role_auditor_prompt
    from lh_harness.types import EpisodeBudget

    from cloudeo.bridge.audit import UHPWorkspaceAuditTransport
    from cloudeo.evaluation.fake_harnessrouter import FakeHarnessRouter
    from cloudeo.execution.dispatch import ExecutionDispatcher
    from cloudeo.execution.uhp_backend import UHPHarnessTaskBackend
    from cloudeo.longhorizon.adapter import HarnessExecutionProfile
    from cloudeo.longhorizon.audit_result import normalize_auditor_result
    from cloudeo.longhorizon.workspace_auditor import UHPWorkspaceAuditorAdapter
    from cloudeo.uhp.client import UHPClient

    class NoEnvironment:
        """The auditor must not execute in the LongHorizon Environment."""

        async def exec(self, command, timeout=30, tee_path=None):
            record("environment", "exec", command=command)
            raise RuntimeError("the auditor must not execute in the Environment")

        async def screenshot(self):
            raise RuntimeError("screenshot must not be called")

        async def upload(self, local_path, remote_path):
            raise RuntimeError("upload must not be called")

        async def download(self, remote_path, local_path):
            raise RuntimeError("download must not be called")

    audit = fixture["audit"]
    reply = {"id": "resp_audit", "output": [{"type": "message", "role": "assistant", "content": [
        {"type": "output_text", "text": audit["report"]}]}]}  # fmt: skip
    # What the (faked) auditor model does to its remote copy; a read-only audit does nothing.
    writes = audit.get("remote_writes")

    def remote_work(workspace):
        _write(workspace, writes)
        record("auditor_model", "write", paths=sorted(writes))

    router = FakeHarnessRouter(
        workdir / "harnessrouter",
        response_overrides=reply,
        work=remote_work if writes else None,
    )

    def server(request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/api/harness")
        record("uhp_server", "request", method=request.method, path=path)
        return router(request)

    with isolated_git(workdir):
        repo, broker, candidate = _gate_project(fixture, workdir, record)
        staging = workdir / "staging"
        staging.mkdir()
        client = UHPClient(
            "http://uhp.eval/api/harness", "eval-not-a-real-key",
            transport=httpx.MockTransport(server),
        )  # fmt: skip
        dispatcher = ExecutionDispatcher(harness_task=UHPHarnessTaskBackend(client))
        transport = UHPWorkspaceAuditTransport(broker, client, dispatcher, staging_root=staging)
        auditor = UHPWorkspaceAuditorAdapter(
            HarnessExecutionProfile(**audit["profile"]), transport, candidate
        )
        prompt = build_role_auditor_prompt(
            task=audit["task"], plan_text=audit["plan"], executor_output=audit["executor_output"],
            next_step=MANAGER_NEXT_CLI, workspace_path="/workspace",
        )  # fmt: skip
        async with client:
            episode = await auditor.run_episode(
                prompt, NoEnvironment(), EpisodeBudget(max_duration_seconds=300)
            )
        verification = normalize_auditor_result(episode)
        record("auditor", "verification", status=verification.status, reason=verification.reason,
               mutation_detected=verification.verifier_workspace_mutation_detected)  # fmt: skip
        accepted_before = _after_audit(fixture, repo, broker, candidate, record)
        observations = _gate(repo, broker, candidate, verification, accepted_before, record)

    sent = b"".join(gzip.decompress(u["content"]) if u["content"][:2] == b"\x1f\x8b"
                    else u["content"] for u in router.uploads.values())  # fmt: skip
    sent += json.dumps(router.task_payloads).encode()
    observations.update({
        "audit.status": verification.status,
        "audit.reason": verification.reason,
        "audit.mutations": verification.verifier_workspace_mutations,
        "audit.task_posts": sum(
            1 for e in record.events
            if e.actor == "uhp_server" and e.data["method"] == "POST"
            and e.data["path"] == "/v1/responses"
        ),
        "environment.exec_calls": record.count("environment", "exec"),
    })  # fmt: skip
    if "synthetic_secret" in fixture:
        observations["uploads.contain_secret"] = fixture["synthetic_secret"].encode() in sent
    return observations, "complete"


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
    fallbacks = tuple(AgentProfile.model_validate(f) for f in fixture.get("fallbacks", ()))
    if "fallback" in fixture:  # smoke suites name a single fallback
        fallbacks = (AgentProfile.model_validate(fixture["fallback"]),)
    for profile in (primary, *fallbacks):
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
                    fallbacks=tuple(f.ref for f in fallbacks),
                    fallback_conditions=frozenset({FallbackCondition.MODEL_UNAVAILABLE})
                    if fallbacks
                    else frozenset(),
                ),
            ),
            profiles=(primary, *fallbacks),
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
            "metered_fallback_not_approved" if "needs allow_metered_fallback" in refusal
            else "billing_mode_not_approved" if "is not approved" in refusal
            else "other"
        )  # fmt: skip
    return {
        "approval.refused": refusal is not None,
        "approval.refusal_rule": rule,
        "store.project_profile_saved": saved,
        "billing.observed_metered_api": judge("metered_api"),
        "billing.observed_unreported": judge(None),
        "billing.observed_unknown": judge("unknown"),
    }, "complete"
