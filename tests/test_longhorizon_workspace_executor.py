"""LongHorizon CLI executor bound to a CandidateWorkspace through the UHP bridge.

Real GitWorkspaceBroker, CandidateWorkspace, UHPWorkspaceBridge, UHPClient,
ExecutionDispatcher, UHPHarnessTaskBackend, and LongHorizon types; the
HarnessRouter side is the offline fake from test_uhp_workspace_bridge.
"""

# Pytest fixtures imported from test_uhp_workspace_bridge are requested by
# parameter name, which ruff reports as redefinitions.
# ruff: noqa: F811

import inspect
import json
import os

import httpx
import pytest

pytest.importorskip("lh_harness", reason="requires the optional 'longhorizon' extra")

from lh_harness.adapters.base import AgentAdapter
from lh_harness.environment.base import Environment
from lh_harness.types import EpisodeBudget, EpisodeResult
from test_uhp_workspace_bridge import (  # noqa: F401 - fixtures are used by name
    FakeHarnessRouter,
    accepted,
    broker,
    candidate,
    git,
    isolated_git,
    make_bridge,
    repo,
    snapshot,
    staging,
    standard_work,
)

from cloudeo.longhorizon.adapter import HarnessExecutionProfile, UHPHarnessAgentAdapter
from cloudeo.longhorizon.roles import (
    LONGHORIZON_ROLES,
    MANAGER_ROLE_KEYWORDS,
    RoleEligibilityError,
    bind_longhorizon_roles,
    eligible_roles,
    require_role_eligible,
)
from cloudeo.longhorizon.workspace_executor import UHPWorkspaceExecutorAdapter

PROFILE = HarnessExecutionProfile(harness_id="chrn_claude", model="claude-opus-5", max_step=12)
BUDGET = EpisodeBudget(max_duration_seconds=900)
PROMPT = "Implement the CLI subtask from the manager's plan."


class UntouchableEnvironment:
    """Satisfies LongHorizon's Environment protocol; fails if the adapter uses it."""

    async def exec(self, command, timeout=30, tee_path=None):
        raise AssertionError("the workspace executor must not execute in the Environment")

    async def screenshot(self):
        raise AssertionError("screenshot must not be called")

    async def upload(self, local_path, remote_path):
        raise AssertionError("upload must not be called")

    async def download(self, remote_path, local_path):
        raise AssertionError("download must not be called")


def env():
    environment = UntouchableEnvironment()
    assert isinstance(environment, Environment)
    return environment


async def run_executor(broker, candidate, server, staging, **episode):
    bridge, client = make_bridge(broker, server, staging)
    executor = UHPWorkspaceExecutorAdapter(PROFILE, bridge, candidate)
    async with client:
        return await executor.run_episode(PROMPT, env(), episode.pop("budget", BUDGET), **episode)


def checkpoint_refs(repo):
    return [
        r for r in git(repo, "for-each-ref", "refs/cloudeo").splitlines() if "/checkpoints/" in r
    ]


def decision_refs(repo):
    refs = git(repo, "for-each-ref", "--format=%(refname)", "refs/cloudeo").splitlines()
    return [r for r in refs if r.endswith(("/promoted", "/rejected"))]


# --- A. The principal acceptance test ---


async def test_a_executor_changes_candidate_but_never_accepted_state(
    repo, broker, candidate, staging, tmp_path
):
    a = accepted(repo)
    server = FakeHarnessRouter(tmp_path, work=standard_work)

    result = await run_executor(broker, candidate, server, staging)

    assert isinstance(result, EpisodeResult)
    assert result.status == "done", result.error
    assert result.metadata["cloudeo_runtime_status"] == "completed"
    assert result.metadata["workspace_sync_status"] == "synced"
    root = candidate.local_path
    assert (root / "README.md").read_text() == "updated readme\n"
    assert (root / "src/pkg/new_module.py").exists()
    assert not (root / "docs/old.md").exists()
    assert broker.inspect_candidate(candidate).dirty is True
    # Accepted state is still A: no checkpoint, promotion, or rejection.
    assert accepted(repo) == a
    assert git(root, "rev-parse", "HEAD") == a
    assert checkpoint_refs(repo) == []
    assert decision_refs(repo) == []
    assert result.metadata["independently_verified"] is False


async def test_executor_uses_only_read_only_broker_calls(broker, candidate, staging, tmp_path):
    calls = []

    class SpyBroker:
        def __getattr__(self, name):
            calls.append(name)
            return getattr(broker, name)

    server = FakeHarnessRouter(tmp_path, work=standard_work)
    result = await run_executor(SpyBroker(), candidate, server, staging)
    assert result.status == "done"
    assert set(calls) <= {"inspect_candidate", "accepted_state"}


# --- B. Completed runtime without a synchronized workspace is never done ---


@pytest.mark.parametrize(
    "server_kwargs,code",
    [
        ({"pack": False}, "output_artifact_missing"),
        ({"session_id": None, "work": standard_work}, "missing_session_id"),
    ],
)
async def test_b_completed_without_sync_is_error(
    repo, broker, candidate, staging, tmp_path, server_kwargs, code
):
    before = snapshot(repo, candidate)
    server = FakeHarnessRouter(tmp_path, **server_kwargs)
    result = await run_executor(broker, candidate, server, staging)
    assert result.metadata["cloudeo_runtime_status"] == "completed"
    assert result.status == "error"
    assert result.error.startswith(f"workspace_sync_failed: {code}")
    assert result.metadata["workspace_sync_status"] == "failed"
    assert result.metadata["workspace_sync_error"]["code"] == code
    assert snapshot(repo, candidate) == before


# --- C-F. Runtime states keep their existing mapping; nothing is applied ---


async def test_c_unknown_runtime(repo, broker, candidate, staging, tmp_path):
    before = snapshot(repo, candidate)

    def timeout(request):
        raise httpx.ReadTimeout("timed out", request=request)

    server = FakeHarnessRouter(tmp_path, task_reply=timeout)
    result = await run_executor(broker, candidate, server, staging)
    assert result.status == "error"
    assert result.error.startswith("runtime_state_unobserved")
    assert result.metadata["cloudeo_runtime_status"] == "unknown"
    assert result.metadata["workspace_sync_status"] == "skipped"
    assert snapshot(repo, candidate) == before


@pytest.mark.parametrize(
    "runtime,expected",
    [("failed", "error"), ("cancelled", "cancelled"), ("in_progress", "error")],
)
async def test_d_e_f_non_completed_runtime(
    repo, broker, candidate, staging, tmp_path, runtime, expected
):
    before = snapshot(repo, candidate)
    server = FakeHarnessRouter(tmp_path, work=standard_work, status=runtime)
    result = await run_executor(broker, candidate, server, staging)
    assert result.status == expected
    assert result.metadata["cloudeo_runtime_status"] == runtime
    assert result.metadata["workspace_sync_status"] == "skipped"
    if runtime == "in_progress":
        assert result.error.startswith("runtime_state_unobserved")
    assert snapshot(repo, candidate) == before


# --- G. Incomplete with a valid partial delta ---


@pytest.mark.parametrize("reason,expected", [("max_steps", "timeout"), ("interrupted", "error")])
async def test_g_incomplete_keeps_budget_mapping_and_records_partial_sync(
    repo, broker, candidate, staging, tmp_path, reason, expected
):
    a = accepted(repo)
    server = FakeHarnessRouter(
        tmp_path,
        work=standard_work,
        status="incomplete",
        response_overrides={"incomplete_details": {"reason": reason}},
    )
    result = await run_executor(broker, candidate, server, staging)
    assert result.status == expected
    assert result.metadata["cloudeo_runtime_status"] == "incomplete"
    assert result.metadata["incomplete_details"] == {"reason": reason}
    assert result.metadata["workspace_sync_status"] == "synced"
    assert result.metadata["independently_verified"] is False
    assert broker.inspect_candidate(candidate).dirty is True  # partial, unverified work
    assert accepted(repo) == a


# --- H. Candidate drift during the remote run ---


async def test_h_candidate_drift_is_not_done_and_local_edit_survives(
    repo, broker, candidate, staging, tmp_path
):
    def work(ws):
        standard_work(ws)
        (candidate.local_path / "README.md").write_text("concurrent local edit\n")

    server = FakeHarnessRouter(tmp_path, work=work)
    result = await run_executor(broker, candidate, server, staging)
    assert result.status == "error"
    assert result.error.startswith("workspace_sync_failed: candidate_changed_during_execution")
    assert (candidate.local_path / "README.md").read_text() == "concurrent local edit\n"
    assert (candidate.local_path / "docs/old.md").exists()


# --- I. Profile and fresh sessions ---


async def test_i_profile_budget_and_fresh_session_per_episode(broker, candidate, staging, tmp_path):
    episodes = []

    def work(ws):
        episodes.append(ws.name)
        (ws / f"episode_{len(episodes)}.txt").write_text("x\n")

    server = FakeHarnessRouter(tmp_path, work=work)
    bridge, client = make_bridge(broker, server, staging)
    executor = UHPWorkspaceExecutorAdapter(PROFILE, bridge, candidate)
    async with client:
        first = await executor.run_episode(PROMPT, env(), BUDGET)
        second = await executor.run_episode(PROMPT, env(), EpisodeBudget(max_duration_seconds=60))
    assert (first.status, second.status) == ("done", "done")
    assert len(server.task_payloads) == 2
    for payload, timeout in zip(server.task_payloads, (900, 60), strict=True):
        assert "previous_response_id" not in payload
        assert payload["metadata"] == {"harness_id": "chrn_claude"}
        assert (payload["model"], payload["max_step"], payload["timeout_seconds"]) == (
            "claude-opus-5",
            12,
            timeout,
        )
        text = payload["input"][0]["content"][0]["text"]
        assert text.split("=== TASK ===")[1].strip() == PROMPT
    # Two distinct sessions, one bound candidate carrying both episodes' work.
    assert first.metadata["session_id"] != second.metadata["session_id"]
    assert first.metadata["bridge_run_id"] != second.metadata["bridge_run_id"]
    assert (candidate.local_path / "episode_1.txt").exists()
    assert (candidate.local_path / "episode_2.txt").exists()
    assert second.metadata["added_paths"] == ["episode_2.txt"]


# --- J. Metadata ---


async def test_j_metadata_keeps_runtime_evidence_and_adds_workspace_evidence(
    broker, candidate, staging, tmp_path
):
    usage = {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120}
    server = FakeHarnessRouter(
        tmp_path,
        work=standard_work,
        response_overrides={
            "usage": usage,
            "model": "claude-sonnet-5",
            "metadata": {
                "session_id": "hsess_bridge",
                "requested_model": "claude-opus-5",
                "model_fallback": True,
            },
        },
    )
    result = await run_executor(broker, candidate, server, staging)
    meta = result.metadata
    # Everything episode_result_from_outcome() produces is kept.
    for key in (
        "cloudeo_runtime_status",
        "requested_harness",
        "actual_harness",
        "requested_model",
        "actual_model",
        "model_fallback",
        "response_id",
        "session_id",
        "protocol_version",
        "usage",
        "execution_duration_ms",
        "execution_error",
        "incomplete_details",
        "assistant_visible_output",
    ):
        assert key in meta, key
    assert (meta["requested_harness"], meta["actual_harness"]) == ("chrn_claude", None)
    assert (meta["requested_model"], meta["actual_model"]) == ("claude-opus-5", "claude-sonnet-5")
    assert meta["model_fallback"] is True
    assert meta["usage"] == usage
    assert (meta["response_id"], meta["session_id"]) == ("resp_bridge", "hsess_bridge")
    # Workspace evidence.
    assert meta["supports_workspace_sync"] is True
    assert meta["workspace_sync_status"] == "synced"
    assert meta["workspace_sync_error"] is None
    assert meta["bridge_run_id"].startswith("bridge_")
    assert (meta["workspace_id"], meta["candidate_id"], meta["candidate_base_commit"]) == (
        candidate.workspace_id,
        candidate.candidate_id,
        candidate.base_commit,
    )
    assert meta["added_paths"] == ["src/pkg/new_module.py", "tools.sh"]
    assert "README.md" in meta["changed_paths"]
    assert meta["deleted_paths"] == ["docs/old.md"]
    assert meta["ignored_paths"] == [".env", "build/out.o"]
    assert meta["independently_verified"] is False
    json.dumps(meta)  # plain data


# --- K. Capability ---


def test_k_capability_flags():
    assert UHPHarnessAgentAdapter.supports_workspace_sync is False
    assert UHPWorkspaceExecutorAdapter.supports_workspace_sync is True


def test_executor_conforms_to_agent_adapter(broker, candidate, staging, tmp_path):
    bridge, _ = make_bridge(broker, FakeHarnessRouter(tmp_path), staging)
    executor = UHPWorkspaceExecutorAdapter(PROFILE, bridge, candidate)
    assert isinstance(executor, AgentAdapter)
    ours = inspect.signature(UHPWorkspaceExecutorAdapter.run_episode).parameters
    assert list(ours) == list(inspect.signature(AgentAdapter.run_episode).parameters)


# --- L. Role eligibility (fails closed) ---

ELIGIBILITY = {
    UHPHarnessAgentAdapter: {"manager", "final_response", "auditor_format_repair"},
    UHPWorkspaceExecutorAdapter: {"cli_executor"},
}


def _instances(broker, candidate, staging, tmp_path):
    from cloudeo.execution.dispatch import ExecutionDispatcher
    from cloudeo.execution.uhp_backend import UHPHarnessTaskBackend

    bridge, client = make_bridge(broker, FakeHarnessRouter(tmp_path), staging)
    base = UHPHarnessAgentAdapter(
        PROFILE, ExecutionDispatcher(harness_task=UHPHarnessTaskBackend(client))
    )
    return {
        UHPHarnessAgentAdapter: base,
        UHPWorkspaceExecutorAdapter: UHPWorkspaceExecutorAdapter(PROFILE, bridge, candidate),
    }


@pytest.mark.parametrize("role", LONGHORIZON_ROLES)
def test_l_role_eligibility_matrix(broker, candidate, staging, tmp_path, role):
    for cls, adapter in _instances(broker, candidate, staging, tmp_path).items():
        if role in ELIGIBILITY[cls]:
            require_role_eligible(adapter, role)
            assert bind_longhorizon_roles({role: adapter}) == {f"{role}_agent": adapter}
        else:
            with pytest.raises(RoleEligibilityError):
                require_role_eligible(adapter, role)
            with pytest.raises(RoleEligibilityError):
                bind_longhorizon_roles({role: adapter})


def test_role_eligibility_fails_closed_for_unknowns(broker, candidate, staging, tmp_path):
    adapters = _instances(broker, candidate, staging, tmp_path)
    executor = adapters[UHPWorkspaceExecutorAdapter]

    class Subclass(UHPWorkspaceExecutorAdapter):
        pass

    subclass = Subclass(executor.profile, executor.bridge, executor.candidate)
    assert eligible_roles(subclass) == frozenset()  # exact type only, no inference
    assert eligible_roles(object()) == frozenset()
    with pytest.raises(RoleEligibilityError, match="Unknown"):
        require_role_eligible(executor, "agent")  # the manager's default fallback
    with pytest.raises(RoleEligibilityError, match="Unknown"):
        require_role_eligible(executor, "auditor")
    # One bad binding rejects the whole set.
    with pytest.raises(RoleEligibilityError):
        bind_longhorizon_roles(
            {"cli_executor": executor, "cli_auditor": adapters[UHPHarnessAgentAdapter]}
        )
    assert set(MANAGER_ROLE_KEYWORDS.values()) == {
        "manager_agent",
        "gui_executor_agent",
        "cli_executor_agent",
        "gui_auditor_agent",
        "cli_auditor_agent",
        "auditor_format_repair_agent",
        "final_response_agent",
    }


def test_role_keywords_match_pinned_manager():
    from lh_harness import manager

    parameters = inspect.signature(manager._run_impl).parameters
    assert set(MANAGER_ROLE_KEYWORDS.values()) <= set(parameters)


# --- M, N. Environment and trajectory ---


async def test_m_n_environment_untouched_and_no_trajectory_fabricated(
    broker, candidate, staging, tmp_path
):
    trajectory = tmp_path / "round_1" / "executor_raw_trajectory.jsonl"
    server = FakeHarnessRouter(tmp_path, work=standard_work)
    result = await run_executor(
        broker, candidate, server, staging, live_trajectory_path=str(trajectory)
    )
    assert result.status == "done"  # env methods raise if called
    assert not trajectory.exists()
    assert not trajectory.parent.exists()


# --- Candidate lifecycle ---


async def test_stale_candidate_is_an_executor_error_without_remote_calls(
    repo, broker, candidate, staging, tmp_path
):
    other = broker.create_candidate(broker.accepted_state())
    (other.local_path / "other.txt").write_text("x\n")
    broker.promote(broker.checkpoint_candidate(other, "moves accepted"))
    before = snapshot(repo, candidate)
    server = FakeHarnessRouter(tmp_path, work=standard_work)
    result = await run_executor(broker, candidate, server, staging)
    assert result.status == "error"
    assert result.error.startswith("candidate_stale")
    assert result.metadata["cloudeo_runtime_status"] is None
    assert server.requests == []
    assert snapshot(repo, candidate) == before


async def test_promoted_candidate_is_an_executor_error(repo, broker, candidate, staging, tmp_path):
    (candidate.local_path / "done.txt").write_text("x\n")
    broker.promote(broker.checkpoint_candidate(candidate, "accepted"))
    server = FakeHarnessRouter(tmp_path, work=standard_work)
    result = await run_executor(broker, candidate, server, staging)
    assert result.status == "error"
    assert result.error.startswith("candidate_stale")
    assert server.requests == []


async def test_cleaned_up_candidate_is_an_executor_error(broker, candidate, staging, tmp_path):
    broker.cleanup(candidate, discard=True)
    server = FakeHarnessRouter(tmp_path, work=standard_work)
    result = await run_executor(broker, candidate, server, staging)
    assert result.status == "error"
    assert result.error.startswith("candidate_unavailable")
    assert server.requests == []
    assert not candidate.local_path.exists()  # not recreated


async def test_foreign_candidate_is_an_executor_error(broker, candidate, staging, tmp_path):
    forged = candidate.model_copy(update={"candidate_id": "f" * 32})
    server = FakeHarnessRouter(tmp_path, work=standard_work)
    result = await run_executor(broker, forged, server, staging)
    assert result.status == "error"
    assert result.error.startswith("candidate_unavailable")
    assert server.requests == []


async def test_unsendable_candidate_is_an_executor_error(broker, candidate, staging, tmp_path):
    (candidate.local_path / "link").symlink_to("README.md")
    server = FakeHarnessRouter(tmp_path, work=standard_work)
    result = await run_executor(broker, candidate, server, staging)
    assert result.status == "error"
    assert result.error.startswith("candidate_unavailable")
    assert "symbolic links" in result.error
    assert server.requests == []


def test_executor_requires_a_workspace_capable_bridge(broker, candidate, staging, tmp_path):
    bridge, _ = make_bridge(broker, FakeHarnessRouter(tmp_path), staging)

    class NoSync:
        supports_workspace_sync = False
        broker = bridge.broker

    with pytest.raises(ValueError, match="does not synchronize"):
        UHPWorkspaceExecutorAdapter(PROFILE, NoSync(), candidate)
    assert os.path.isdir(candidate.local_path)
