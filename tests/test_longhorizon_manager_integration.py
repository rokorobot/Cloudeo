"""The unmodified LongHorizon manager loop, wrapped by Cloudeo's normalizer and gate.

Real lh_harness.manager.run(), LocalEnvironment, GitWorkspaceBroker,
CandidateWorkspace, UHPWorkspaceBridge, UHPWorkspaceAuditTransport, UHPClient,
ExecutionDispatcher, and all Cloudeo adapters. The HarnessRouter side is the
offline fake, scripted per role: manager plans, format repair, and the final
response are text tasks; the executor and auditor run the bridge protocol.
"""

# Pytest fixtures imported from the bridge tests are requested by parameter
# name, which ruff reports as redefinitions.
# ruff: noqa: F811

import ast
import inspect
import json
import os

import httpx
import pytest

pytest.importorskip("lh_harness", reason="requires the optional 'longhorizon' extra")

from lh_harness.environment.local import LocalEnvironment
from lh_harness.types import HarnessConfig
from test_longhorizon_workspace_auditor import VALID_REPORT
from test_uhp_workspace_bridge import (  # noqa: F401 - fixtures are used by name
    HEADERS,
    FakeHarnessRouter,
    accepted,
    broker,
    candidate,
    git,
    isolated_git,
    repo,
    staging,
    standard_work,
)

from cloudeo.bridge.audit import UHPWorkspaceAuditTransport
from cloudeo.bridge.bridge import UHPWorkspaceBridge
from cloudeo.execution.dispatch import ExecutionDispatcher
from cloudeo.execution.uhp_backend import UHPHarnessTaskBackend
from cloudeo.longhorizon import manager_integration
from cloudeo.longhorizon.adapter import HarnessExecutionProfile, UHPHarnessAgentAdapter
from cloudeo.longhorizon.manager_integration import run_managed_with_promotion_gate
from cloudeo.longhorizon.roles import RoleEligibilityError
from cloudeo.longhorizon.workspace_auditor import UHPWorkspaceAuditorAdapter
from cloudeo.longhorizon.workspace_executor import UHPWorkspaceExecutorAdapter
from cloudeo.uhp.client import UHPClient

TASK = "Refactor the app and update the docs."
PROFILE = HarnessExecutionProfile(harness_id="chrn_claude", model="claude-opus-5", max_step=12)
AUDIT_PROFILE = HarnessExecutionProfile(harness_id="chrn_codex", model="audit-model", max_step=7)
INCOMPLETE_REPORT = VALID_REPORT.replace("Status: complete", "Status: incomplete")
MALFORMED = "Everything looks finished to me."
CLI_PLAN = """\
Task contract: update README.md and add src/pkg/new_module.py; nothing else.
Current task state: nothing done yet.
Subtask: update README.md and add src/pkg/new_module.py.
Acceptance criteria: both files exist with the requested content.
Next: cli"""
DONE_PLAN = "Current task state: the audited CLI subtask completed the objective.\nNext: done"
BLOCKED_PLAN = "Current task state: cannot continue.\nNext: blocked"
# Role prompts are recognized by how they start: later manager prompts quote
# earlier audit text, including the repair wording.
REPAIR_MARKER = "Your previous auditor report lacks a valid three-line control header"
FINAL_MARKER = "Write the reply to the person who asked for this task."


def text_reply(text, n):
    return {
        "id": f"resp_text_{n}",
        "object": "response",
        "created_at": 1786400000,
        "status": "completed",
        "model": "m",
        "output": [
            {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": text}],
            }
        ],
        "error": None,
        "incomplete_details": None,
        "usage": None,
        "metadata": {"session_id": f"hsess_text_{n}"},
        "previous_response_id": None,
    }


class ScriptedHarnessRouter(FakeHarnessRouter):
    """Routes each UHP task by role; records the role order."""

    def __init__(
        self,
        root,
        *,
        plans=(CLI_PLAN, DONE_PLAN),
        executor_work=standard_work,
        auditor_work=None,
        auditor_text=VALID_REPORT,
        auditor_status="completed",
        auditor_pack=True,
        repair_text=VALID_REPORT,
    ):
        super().__init__(root)
        self.plans = list(plans)
        self.executor_work = executor_work
        self.auditor_work = auditor_work
        self.auditor_text = auditor_text
        self.auditor_status = auditor_status
        self.auditor_pack = auditor_pack
        self.repair_text = repair_text
        self.roles = []

    def _task(self, request):
        payload = json.loads(request.content)
        if isinstance(payload["input"], str):
            self.task_payloads.append(payload)
            n = len(self.task_payloads) - 1
            return httpx.Response(
                200, json=text_reply(self._text(payload["input"]), n), headers=HEADERS
            )
        text = next(p["text"] for p in payload["input"][0]["content"] if p["type"] == "input_text")
        if "CLOUDEO WORKSPACE AUDIT" in text:
            self.roles.append("auditor")
            self.work, self.status, self.pack = (
                self.auditor_work,
                self.auditor_status,
                self.auditor_pack,
            )
            self.response_overrides = {
                **text_reply(self.auditor_text, 0),
                "id": f"resp_audit_{len(self.task_payloads)}",
                "status": self.auditor_status,
            }
            self.response_overrides.pop("metadata")
        else:
            self.roles.append("executor")
            self.work, self.status, self.pack = self.executor_work, "completed", True
            self.response_overrides = {}
        return super()._task(request)

    def _text(self, prompt):
        if prompt.startswith(REPAIR_MARKER):
            self.roles.append("repair")
            return self.repair_text
        if prompt.startswith(FINAL_MARKER):
            self.roles.append("final_response")
            return "The objective is complete."
        self.roles.append("manager")
        plan = self.plans.pop(0) if self.plans else BLOCKED_PLAN
        if callable(plan):
            plan = plan()
        return plan


class RacingBroker:
    """Delegates to the real broker, changing state just before one call."""

    def __init__(self, broker, before):
        self._broker = broker
        self._before = before

    def __getattr__(self, name):
        target = getattr(self._broker, name)
        if name not in self._before:
            return target

        def call(*args, **kwargs):
            self._before[name]()
            return target(*args, **kwargs)

        return call


class Setup:
    def __init__(self, broker, candidate, server, staging, tmp_path):
        self.server = server
        self.client = UHPClient(
            "http://uhp.test/api/harness",
            "test-not-a-real-key",
            transport=httpx.MockTransport(server),
        )
        dispatcher = ExecutionDispatcher(harness_task=UHPHarnessTaskBackend(self.client))
        bridge = UHPWorkspaceBridge(broker, self.client, dispatcher, staging_root=staging)
        transport = UHPWorkspaceAuditTransport(
            broker, self.client, dispatcher, staging_root=staging
        )
        self.broker = broker
        self.candidate = candidate
        self.manager = UHPHarnessAgentAdapter(PROFILE, dispatcher)
        self.executor = UHPWorkspaceExecutorAdapter(PROFILE, bridge, candidate)
        self.auditor = UHPWorkspaceAuditorAdapter(AUDIT_PROFILE, transport, candidate)
        self.env = LocalEnvironment(tmp_dir=str(tmp_path / "lh_tmp"))
        self.config = HarnessConfig(
            max_total_episodes=4,
            harness_dir=str(tmp_path / "lh_harness_dir"),
            log_dir=str(tmp_path / "lh_logs"),
        )

    async def run(self, **overrides):
        kwargs = {
            "task": TASK,
            "env": self.env,
            "config": self.config,
            "broker": self.broker,
            "candidate": self.candidate,
            "manager": self.manager,
            "executor": self.executor,
            "auditor": self.auditor,
            **overrides,
        }
        async with self.client:
            return await run_managed_with_promotion_gate(**kwargs)


def refs(repo):
    return git(
        repo, "for-each-ref", "--format=%(refname) %(objectname)", "refs/cloudeo"
    ).splitlines()


def checkpoint_refs(repo):
    return [r for r in refs(repo) if "/checkpoints/" in r]


def promoted_refs(repo):
    return [r for r in refs(repo) if r.split()[0].endswith("/promoted")]


def assert_not_attempted(result, reason):
    assert result.promotion_attempted is False
    assert result.promotion_result is None
    assert result.promotion_not_attempted_reason == reason
    assert result.checkpoint_commit is None
    assert result.promoted is False


async def managed(repo, broker, candidate, staging, tmp_path, **server):
    s = Setup(
        broker, candidate, ScriptedHarnessRouter(tmp_path / "hr", **server), staging, tmp_path
    )
    return s, await s.run()


# --- 1-4, 19. Successful path ---


async def test_1_to_4_verified_objective_is_promoted_exactly_once(
    repo, broker, candidate, staging, tmp_path
):
    a = accepted(repo)
    s, result = await managed(repo, broker, candidate, staging, tmp_path)

    assert s.server.roles == ["manager", "executor", "auditor", "manager", "final_response"]
    assert result.upstream_report["status"] == "complete"
    # 1. The original audit is VERIFIED.
    assert result.verification.status == "VERIFIED"
    assert result.verification.format_repair == "not_needed"
    # 2-3. The gate created the checkpoint and promoted it.
    assert result.promotion_attempted is True
    assert result.promotion_not_attempted_reason is None
    gated = result.promotion_result
    assert (gated.stage, gated.checkpoint_created, gated.decision.status) == (
        "promoted",
        True,
        "VERIFIED_AND_CURRENT",
    )
    assert result.promoted
    assert result.checkpoint_commit == gated.checkpoint.commit
    # 4, 19. Accepted state advanced exactly once, to exactly that checkpoint.
    assert accepted(repo) == result.checkpoint_commit
    assert git(repo, "rev-parse", f"{result.checkpoint_commit}^1") == a
    assert len(promoted_refs(repo)) == 1
    assert git(repo, "show", f"{result.checkpoint_commit}:README.md") == "updated readme"
    # Identity is explicit.
    assert (result.workspace_id, result.candidate_id, result.base_commit) == (
        candidate.workspace_id,
        candidate.candidate_id,
        a,
    )
    assert result.auditor_episodes == 1
    # The manager saw the candidate as the workspace.
    # The executor prompt names the candidate as the workspace (config.workspace_path).
    executor_payloads = [
        json.dumps(p) for p in s.server.task_payloads if "CLOUDEO WORKSPACE BRIDGE" in json.dumps(p)
    ]
    assert executor_payloads and all(str(candidate.local_path) in p for p in executor_payloads)


async def test_2_existing_audited_checkpoint_is_reused(repo, broker, candidate, staging, tmp_path):
    standard_work(candidate.local_path)  # the work already exists and is checkpointed
    existing = broker.checkpoint_candidate(candidate, "before the run")
    _, result = await managed(repo, broker, candidate, staging, tmp_path, executor_work=None)
    gated = result.promotion_result
    assert (gated.stage, gated.checkpoint_created) == ("promoted", False)
    assert gated.checkpoint.commit == existing.commit == accepted(repo)


# --- 5-8. Verification refusals ---


async def test_5_incomplete_audit_does_not_promote(repo, broker, candidate, staging, tmp_path):
    a = accepted(repo)
    _, result = await managed(
        repo, broker, candidate, staging, tmp_path, auditor_text=INCOMPLETE_REPORT
    )
    assert result.upstream_report["status"] != "complete"
    assert result.verification.status == "NOT_VERIFIED"
    assert_not_attempted(result, "objective_not_complete")
    assert accepted(repo) == a and checkpoint_refs(repo) == []


async def test_6_repaired_positive_audit_does_not_promote(
    repo, broker, candidate, staging, tmp_path
):
    a = accepted(repo)
    s, result = await managed(
        repo, broker, candidate, staging, tmp_path, auditor_text=MALFORMED, repair_text=VALID_REPORT
    )
    assert "repair" in s.server.roles
    assert result.format_repair_used is True
    assert result.verification.status == "NOT_VERIFIED"
    assert result.verification.format_repair == "accepted"
    assert result.verification.reason == "report_repaired_not_verification_authority"
    assert result.upstream_report["status"] != "complete"
    assert_not_attempted(result, "objective_not_complete")
    assert accepted(repo) == a and checkpoint_refs(repo) == []


async def test_7_auditor_mutation_does_not_promote(repo, broker, candidate, staging, tmp_path):
    a = accepted(repo)
    _, result = await managed(
        repo,
        broker,
        candidate,
        staging,
        tmp_path,
        auditor_work=lambda ws: (ws / "audit_notes.md").write_text("notes\n"),
    )
    assert result.verification.status == "BLOCKED"
    assert result.verification.reason == "workspace_mutation_detected"
    assert result.verification.verifier_workspace_mutations["added"] == ["audit_notes.md"]
    assert_not_attempted(result, "objective_not_complete")
    assert accepted(repo) == a and checkpoint_refs(repo) == []
    assert not (candidate.local_path / "audit_notes.md").exists()


async def test_8_missing_audit_evidence_does_not_promote(
    repo, broker, candidate, staging, tmp_path
):
    a = accepted(repo)
    _, result = await managed(repo, broker, candidate, staging, tmp_path, auditor_pack=False)
    assert result.verification.status == "BLOCKED"
    assert result.verification.audit_invalid_reasons == ("audit_evidence_invalid",)
    assert_not_attempted(result, "objective_not_complete")
    assert accepted(repo) == a and checkpoint_refs(repo) == []


# --- 9-11. Auditor failures ---


@pytest.mark.parametrize("status,kind", [("failed", "provider_error"), ("cancelled", "cancelled")])
async def test_9_to_11_auditor_failure_is_normalized_and_never_promoted(
    repo, broker, candidate, staging, tmp_path, status, kind
):
    a = accepted(repo)
    s, result = await managed(repo, broker, candidate, staging, tmp_path, auditor_status=status)
    # 10. Upstream ended the run as it always does; Cloudeo still normalized.
    assert s.server.roles[:3] == ["manager", "executor", "auditor"]
    assert result.upstream_report["status"] in ("failed", "cancelled")
    # 9. A structured AUDITOR_ERROR, with LongHorizon's classification.
    assert result.verification.status == "AUDITOR_ERROR"
    assert result.verification.failure.kind == kind
    # 11. Promotion was never attempted.
    assert_not_attempted(result, "objective_not_complete")
    assert accepted(repo) == a and checkpoint_refs(repo) == []


# --- 12-16. Races: the objective completes, then state moves ---


def race_setup(repo, broker, candidate, staging, tmp_path, hook, broker_for_run=None):
    server = ScriptedHarnessRouter(
        tmp_path / "hr", plans=[CLI_PLAN, lambda: (hook(), DONE_PLAN)[1]]
    )
    return Setup(broker_for_run or broker, candidate, server, staging, tmp_path)


async def test_12_workspace_changed_after_audit_is_refused(
    repo, broker, candidate, staging, tmp_path
):
    a = accepted(repo)
    s = race_setup(
        repo,
        broker,
        candidate,
        staging,
        tmp_path,
        lambda: (candidate.local_path / "README.md").write_text("changed after audit\n"),
    )
    result = await s.run()
    assert result.upstream_report["status"] == "complete"
    assert result.verification.status == "VERIFIED"
    assert result.promotion_attempted is True
    gated = result.promotion_result
    # 17. Refused before checkpoint: nothing created, accepted unchanged.
    assert (gated.stage, gated.decision.status) == (
        "refused_before_checkpoint",
        "WORKSPACE_CHANGED",
    )
    assert (gated.checkpoint, gated.checkpoint_created, result.checkpoint_commit) == (
        None,
        False,
        None,
    )
    assert accepted(repo) == a and checkpoint_refs(repo) == []


async def test_13_accepted_state_moved_is_refused(repo, broker, candidate, staging, tmp_path):
    def promote_other():
        other = broker.create_candidate(broker.accepted_state())
        (other.local_path / "other.txt").write_text("x\n")
        broker.promote(broker.checkpoint_candidate(other, "other"))

    s = race_setup(repo, broker, candidate, staging, tmp_path, promote_other)
    other_accepted = None
    result = await s.run()
    other_accepted = accepted(repo)
    gated = result.promotion_result
    assert (gated.stage, gated.decision.status) == (
        "refused_before_checkpoint",
        "VERIFICATION_STALE",
    )
    assert accepted(repo) == other_accepted  # not moved by the gate


async def test_14_candidate_head_changed_is_refused(repo, broker, candidate, staging, tmp_path):
    s = race_setup(
        repo,
        broker,
        candidate,
        staging,
        tmp_path,
        lambda: broker.checkpoint_candidate(candidate, "after the audit"),
    )
    a = accepted(repo)
    result = await s.run()
    gated = result.promotion_result
    assert (gated.stage, gated.decision.status) == ("refused_before_checkpoint", "HEAD_CHANGED")
    assert accepted(repo) == a


async def test_15_18_change_at_checkpoint_time_is_caught_and_checkpoint_kept(
    repo, broker, candidate, staging, tmp_path
):
    a = accepted(repo)
    racing = RacingBroker(
        broker,
        {"checkpoint_candidate": lambda: (candidate.local_path / "late.txt").write_text("late\n")},
    )
    server = ScriptedHarnessRouter(tmp_path / "hr")
    result = await Setup(racing, candidate, server, staging, tmp_path).run()
    gated = result.promotion_result
    assert (gated.stage, gated.checkpoint_created, gated.decision.reason) == (
        "refused_after_checkpoint",
        True,
        "checkpoint_differs_from_audit",
    )
    # 18. The checkpoint is retained, surfaced, and not accepted.
    assert result.checkpoint_commit == gated.checkpoint.commit
    assert any(r.split()[0].endswith(f"/checkpoints/{gated.checkpoint.commit}") for r in refs(repo))
    assert accepted(repo) == a and promoted_refs(repo) == []


async def test_16_accepted_moving_before_promote_is_caught(
    repo, broker, candidate, staging, tmp_path
):
    def promote_other():
        other = broker.create_candidate(broker.accepted_state())
        (other.local_path / "other.txt").write_text("x\n")
        broker.promote(broker.checkpoint_candidate(other, "other"))

    racing = RacingBroker(broker, {"promote": promote_other})
    server = ScriptedHarnessRouter(tmp_path / "hr")
    result = await Setup(racing, candidate, server, staging, tmp_path).run()
    gated = result.promotion_result
    assert (gated.stage, gated.decision.status) == (
        "refused_after_checkpoint",
        "VERIFICATION_STALE",
    )
    assert accepted(repo) != gated.checkpoint.commit  # the other candidate's commit won


# --- Not attempted: distinct from refused ---


async def test_manager_failed_before_audit(repo, broker, candidate, staging, tmp_path):
    # A GUI step has no eligible Cloudeo adapter: it fails explicitly, upstream
    # aborts, and no audit exists.
    a = accepted(repo)
    s, result = await managed(
        repo,
        broker,
        candidate,
        staging,
        tmp_path,
        plans=[CLI_PLAN.replace("Next: cli", "Next: gui")],
    )
    assert "auditor" not in s.server.roles
    assert result.upstream_report["status"] == "failed"
    assert result.verification is None
    assert_not_attempted(result, "manager_failed_before_audit")
    assert accepted(repo) == a


async def test_auditor_missing(repo, broker, candidate, staging, tmp_path):
    s, result = await managed(repo, broker, candidate, staging, tmp_path, plans=[BLOCKED_PLAN])
    assert s.server.roles[0] == "manager" and "auditor" not in s.server.roles
    assert result.verification is None
    assert_not_attempted(result, "auditor_missing")


async def test_only_the_final_audit_is_authority(repo, broker, candidate, staging, tmp_path):
    """Round 1 audits incomplete work; round 2 finishes it; only round 2 counts."""
    server = ScriptedHarnessRouter(
        tmp_path / "hr", plans=[CLI_PLAN, CLI_PLAN, DONE_PLAN], auditor_text=INCOMPLETE_REPORT
    )
    texts = iter([INCOMPLETE_REPORT, VALID_REPORT])
    original = server._task

    def task(request):
        payload = json.loads(request.content)
        if not isinstance(payload["input"], str) and "CLOUDEO WORKSPACE AUDIT" in json.dumps(
            payload
        ):
            server.auditor_text = next(texts)
        return original(request)

    server._task = task
    works = iter([lambda ws: (ws / "README.md").write_text("half\n"), standard_work])
    server.executor_work = lambda ws: next(works)(ws)
    result = await Setup(broker, candidate, server, staging, tmp_path).run()
    assert result.auditor_episodes == 2
    assert result.verification.status == "VERIFIED"
    assert result.promoted


# --- 20-23. Authority boundaries ---


async def test_20_21_only_the_gate_checkpoints_and_promotes(
    repo, broker, candidate, staging, tmp_path
):
    callers = []

    class Spy:
        def __getattr__(self, name):
            target = getattr(broker, name)
            if name not in ("checkpoint_candidate", "promote", "reject", "cleanup"):
                return target

            def call(*args, **kwargs):
                callers.append((name, inspect.stack()[1].filename))
                return target(*args, **kwargs)

            return call

    server = ScriptedHarnessRouter(tmp_path / "hr")
    result = await Setup(Spy(), candidate, server, staging, tmp_path).run()
    assert result.promoted
    assert [name for name, _ in callers] == ["checkpoint_candidate", "promote"]
    assert all(path.endswith("cloudeo/longhorizon/promotion_gate.py") for _, path in callers)
    # No call to a broker mutator, and no ref strings, anywhere in the code.
    tree = ast.parse(inspect.getsource(manager_integration))
    called = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert not called & {"promote", "checkpoint_candidate", "reject", "cleanup"}
    docstrings = {
        ast.get_docstring(node, clean=False)
        for node in ast.walk(tree)
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef)
    }
    strings = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and node.value not in docstrings
    ]
    assert not any("refs/cloudeo" in value or "update-ref" in value for value in strings)


async def test_22_executor_completion_is_not_verification(
    repo, broker, candidate, staging, tmp_path
):
    a = accepted(repo)
    _, result = await managed(
        repo, broker, candidate, staging, tmp_path, auditor_text=INCOMPLETE_REPORT
    )
    # The executor finished and synced; that alone never promotes.
    assert (candidate.local_path / "src/pkg/new_module.py").exists()
    assert result.verification.status != "VERIFIED"
    assert not result.promoted and accepted(repo) == a
    # The normalizer only ever sees auditor episodes.
    assert result.verification.upstream_metadata["workspace_access"] == "read_only_snapshot"


async def test_23_repaired_prose_is_never_authority_even_if_upstream_completes(
    repo, broker, candidate, staging, tmp_path, monkeypatch
):
    # Force upstream to treat the repaired text as complete; the normalizer
    # still caps it and the gate refuses.
    s = Setup(
        broker,
        candidate,
        ScriptedHarnessRouter(tmp_path / "hr", auditor_text=MALFORMED, repair_text=VALID_REPORT),
        staging,
        tmp_path,
    )
    monkeypatch.setattr(
        manager_integration.lh_manager, "_latest_auditor_is_clean_complete", lambda *a, **k: True
    )
    a = accepted(repo)
    result = await s.run()
    assert result.upstream_report["status"] == "complete"
    assert result.verification.status == "NOT_VERIFIED"
    assert result.promotion_attempted is True
    gated = result.promotion_result
    assert (gated.stage, gated.decision.status) == ("refused_before_checkpoint", "NOT_VERIFIED")
    assert accepted(repo) == a and checkpoint_refs(repo) == []


# --- Validation fails closed before anything runs ---


async def test_candidate_identity_and_paths_are_validated(
    repo, broker, candidate, staging, tmp_path
):
    server = ScriptedHarnessRouter(tmp_path / "hr")
    s = Setup(broker, candidate, server, staging, tmp_path)
    other = broker.create_candidate(broker.accepted_state())
    cases = [
        ({"candidate": other}, ValueError, "bound to candidate"),
        (
            {
                "config": HarnessConfig(
                    workspace_path="/elsewhere",
                    harness_dir=str(tmp_path / "h"),
                    log_dir=str(tmp_path / "l"),
                )
            },
            ValueError,
            "refusing to substitute",
        ),
        (
            {
                "config": HarnessConfig(
                    harness_dir=str(candidate.local_path / ".harness"), log_dir=str(tmp_path / "l")
                )
            },
            ValueError,
            "inside the candidate",
        ),
        (
            {
                "config": HarnessConfig(
                    harness_dir=str(tmp_path / "h"), log_dir=str(candidate.local_path / "logs")
                )
            },
            ValueError,
            "inside the candidate",
        ),
        ({"auditor": s.executor}, RoleEligibilityError, "not eligible"),
        ({"executor": s.auditor}, RoleEligibilityError, "not eligible"),
    ]
    for overrides, error, match in cases:
        with pytest.raises(error, match=match):
            await s.run(**overrides)
    assert server.requests == []  # nothing ran


async def test_executor_and_auditor_must_share_the_gate_broker(
    repo, broker, candidate, staging, tmp_path
):
    server = ScriptedHarnessRouter(tmp_path / "hr")
    s = Setup(broker, candidate, server, staging, tmp_path)
    with pytest.raises(ValueError, match="Workspace Broker"):
        await s.run(broker=RacingBroker(broker, {}))
    assert server.requests == []
    assert os.path.isdir(candidate.local_path)
