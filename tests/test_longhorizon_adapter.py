import inspect
import json

import httpx
import pytest

pytest.importorskip("lh_harness", reason="requires the optional 'longhorizon' extra")

from lh_harness.adapters.base import AgentAdapter
from lh_harness.environment.base import Environment
from lh_harness.types import EpisodeBudget, EpisodeResult
from pydantic import ValidationError

from cloudeo.execution.contracts import (
    ExecutionCost,
    ExecutionOutcome,
    HarnessTaskExecution,
    RuntimeIdentity,
)
from cloudeo.execution.dispatch import ExecutionDispatcher
from cloudeo.execution.uhp_backend import UHPHarnessTaskBackend
from cloudeo.longhorizon.adapter import (
    BUDGET_INCOMPLETE_REASONS,
    RUNTIME_STATE_UNOBSERVED,
    HarnessExecutionProfile,
    UHPHarnessAgentAdapter,
    episode_result_from_outcome,
)
from cloudeo.uhp.client import UHPClient
from cloudeo.uhp.models import UHP_VERSION

HEADERS = {"UHP-Version": UHP_VERSION}
PROFILE = HarnessExecutionProfile(harness_id="chrn_claude", model="claude-opus-5", max_step=4)
BUDGET = EpisodeBudget(max_duration_seconds=120)
METADATA_KEYS = {
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
}


class UntouchableEnvironment:
    """Satisfies LongHorizon's Environment protocol; fails if the adapter uses it."""

    async def exec(self, command, timeout=30, tee_path=None):
        raise AssertionError("The UHP adapter must not execute in the LongHorizon Environment")

    async def screenshot(self):
        raise AssertionError("screenshot must not be called")

    async def upload(self, local_path, remote_path):
        raise AssertionError("upload must not be called")

    async def download(self, remote_path, local_path):
        raise AssertionError("download must not be called")


def response(status="completed", **overrides):
    body = {
        "id": "resp_1",
        "object": "response",
        "created_at": 1786400000,
        "status": status,
        "model": "claude-opus-5",
        "output": [
            {"type": "reasoning", "summary": [{"text": "thinking"}]},
            {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "CLOUDEO_UHP_OK"}],
            },
        ],
        "error": None,
        "incomplete_details": None,
        "usage": {"input_tokens": 10, "output_tokens": 3, "total_tokens": 13},
        "metadata": {"session_id": "hsess_1"},
        "previous_response_id": None,
    }
    if status == "failed":
        body["error"] = {
            "type": "harness_error",
            "code": "provider_error",
            "message": "Provider failed",
            "param": None,
            "detail": {"vendor": "x"},
        }
    body.update(overrides)
    return body


class Recorder:
    def __init__(self, reply):
        self.reply = reply
        self.payloads = []

    def __call__(self, request):
        self.payloads.append(json.loads(request.content))
        return self.reply(request) if callable(self.reply) else self.reply


def adapter_for(reply, profile=PROFILE, **options):
    recorder = Recorder(reply)
    client = UHPClient("http://uhp.test/api/harness", transport=httpx.MockTransport(recorder))
    dispatcher = ExecutionDispatcher(harness_task=UHPHarnessTaskBackend(client))
    return UHPHarnessAgentAdapter(profile, dispatcher, **options), recorder, client


async def run(reply, *, budget=BUDGET, profile=PROFILE, **options):
    adapter, recorder, client = adapter_for(reply, profile, **options)
    async with client:
        result = await adapter.run_episode("Reply with exactly: CLOUDEO_UHP_OK", env(), budget)
    return result, recorder


def env():
    environment = UntouchableEnvironment()
    assert isinstance(environment, Environment)
    return environment


def ok(status="completed", **overrides):
    return httpx.Response(200, json=response(status, **overrides), headers=HEADERS)


# --- Protocol and capability ---


def test_adapter_conforms_to_longhorizon_agent_adapter():
    adapter, _, _ = adapter_for(ok())
    assert isinstance(adapter, AgentAdapter)
    ours = inspect.signature(UHPHarnessAgentAdapter.run_episode).parameters
    theirs = inspect.signature(AgentAdapter.run_episode).parameters
    assert list(ours) == list(theirs)
    assert ours["live_trajectory_path"].default is None


def test_adapter_declares_no_workspace_sync():
    adapter, _, _ = adapter_for(ok())
    assert UHPHarnessAgentAdapter.supports_workspace_sync is False
    assert adapter.supports_workspace_sync is False


def test_adapter_requires_a_harness_task_backend():
    with pytest.raises(ValueError, match="harness-task backend"):
        UHPHarnessAgentAdapter(PROFILE, ExecutionDispatcher())


@pytest.mark.parametrize(
    "fields",
    [{"harness_id": "", "model": "m"}, {"harness_id": "h", "model": ""}, {"harness_id": "h"}],
)
def test_profile_must_be_explicit(fields):
    with pytest.raises(ValidationError):
        HarnessExecutionProfile(**fields)


# --- Request shape: explicit profile, fresh session, no routing ---


async def test_episode_uses_profile_exactly_and_a_fresh_session():
    adapter, recorder, client = adapter_for(ok())
    async with client:
        await adapter.run_episode("first", env(), BUDGET)
        await adapter.run_episode("second", env(), EpisodeBudget(max_duration_seconds=30))
    assert recorder.payloads == [
        {
            "input": "first",
            "model": "claude-opus-5",
            "max_step": 4,
            "timeout_seconds": 120,
            "store": True,
            "stream": False,
            "metadata": {"harness_id": "chrn_claude"},
        },
        {
            "input": "second",
            "model": "claude-opus-5",
            "max_step": 4,
            "timeout_seconds": 30,
            "store": True,
            "stream": False,
            "metadata": {"harness_id": "chrn_claude"},
        },
    ]
    assert all("previous_response_id" not in payload for payload in recorder.payloads)


async def test_adapter_dispatches_exactly_one_preselected_request():
    seen = []

    class RecordingDispatcher(ExecutionDispatcher):
        async def execute(self, request):
            seen.append(request)
            return await super().execute(request)

    recorder = Recorder(ok())
    client = UHPClient("http://uhp.test/api/harness", transport=httpx.MockTransport(recorder))
    dispatcher = RecordingDispatcher(harness_task=UHPHarnessTaskBackend(client))
    adapter = UHPHarnessAgentAdapter(PROFILE, dispatcher)
    async with client:
        await adapter.run_episode("task", env(), BUDGET)
    assert len(seen) == 1
    assert type(seen[0]) is HarnessTaskExecution
    assert (seen[0].task.harness_id, seen[0].task.model) == (PROFILE.harness_id, PROFILE.model)
    assert seen[0].task.previous_response_id is None


# --- Status mapping ---


async def test_completed_maps_to_done_with_visible_output():
    result, _ = await run(ok())
    assert isinstance(result, EpisodeResult)
    assert result.status == "done"
    assert result.error is None
    assert result.metadata["cloudeo_runtime_status"] == "completed"
    assert result.metadata["assistant_visible_output"] == "CLOUDEO_UHP_OK"
    assert result.metadata["actions_log_diagnostics_only"] is False
    assert json.loads(result.actions_log) == response()["output"]


async def test_failed_maps_to_error_with_structured_error():
    result, _ = await run(ok("failed"))
    assert result.status == "error"
    assert "provider_error" in result.error
    assert result.metadata["cloudeo_runtime_status"] == "failed"
    assert result.metadata["execution_error"]["code"] == "provider_error"
    assert result.metadata["execution_error"]["detail"] == {"vendor": "x"}


async def test_cancelled_maps_to_cancelled():
    result, _ = await run(ok("cancelled"))
    assert result.status == "cancelled"
    assert result.metadata["cloudeo_runtime_status"] == "cancelled"


@pytest.mark.parametrize("reason", sorted(BUDGET_INCOMPLETE_REASONS))
async def test_budget_incomplete_maps_to_timeout(reason):
    result, _ = await run(ok("incomplete", incomplete_details={"reason": reason}))
    assert result.status == "timeout"
    assert result.metadata["cloudeo_runtime_status"] == "incomplete"
    assert result.metadata["incomplete_details"] == {"reason": reason}
    # Partial output is still visible to LongHorizon.
    assert result.metadata["assistant_visible_output"] == "CLOUDEO_UHP_OK"


@pytest.mark.parametrize(
    "details", [None, {}, {"reason": "interrupted"}, {"reason": "no_confident_action"}]
)
async def test_other_incomplete_maps_to_error(details):
    result, _ = await run(ok("incomplete", incomplete_details=details))
    assert result.status == "error"
    assert result.metadata["cloudeo_runtime_status"] == "incomplete"


async def test_unknown_after_transport_timeout_maps_to_error_unobserved():
    def timeout(request):
        raise httpx.ReadTimeout("timed out", request=request)

    result, _ = await run(timeout)
    assert result.status == "error"
    assert result.error.startswith(RUNTIME_STATE_UNOBSERVED)
    assert result.metadata["cloudeo_runtime_status"] == "unknown"
    assert result.metadata["execution_error"]["source"] == "uhp_transport"
    assert result.metadata["response_id"] is None


async def test_unknown_after_gateway_error_maps_to_error_unobserved():
    result, _ = await run(httpx.Response(503, text="unavailable", headers=HEADERS))
    assert result.status == "error"
    assert result.error.startswith(RUNTIME_STATE_UNOBSERVED)
    assert result.metadata["cloudeo_runtime_status"] == "unknown"
    assert result.metadata["execution_error"]["http_status"] == 503


async def test_in_progress_within_budget_maps_to_error_unobserved():
    result, _ = await run(ok("in_progress"))
    assert result.status == "error"
    assert result.error.startswith(RUNTIME_STATE_UNOBSERVED)
    assert result.metadata["cloudeo_runtime_status"] == "in_progress"


async def test_in_progress_after_exhausted_episode_budget_maps_to_timeout():
    ticks = iter([100.0, 100.0 + BUDGET.max_duration_seconds + 1])
    result, _ = await run(ok("in_progress"), clock=lambda: next(ticks))
    assert result.status == "timeout"
    assert result.error.startswith(RUNTIME_STATE_UNOBSERVED)
    assert result.metadata["cloudeo_runtime_status"] == "in_progress"


def outcome(status):
    return ExecutionOutcome(
        kind="harness_task",
        status=status,
        runtime=RuntimeIdentity(backend="uhp", requested_harness="chrn_claude"),
        cost=ExecutionCost(),
    )


@pytest.mark.parametrize(
    "status,expected",
    [
        ("completed", "done"),
        ("failed", "error"),
        ("cancelled", "cancelled"),
        ("incomplete", "error"),
        ("unknown", "error"),
        ("in_progress", "error"),
    ],
)
def test_mapping_table_preserves_every_runtime_state(status, expected):
    result = episode_result_from_outcome(outcome(status), budget=BUDGET, episode_duration_ms=5)
    assert result.status == expected
    assert result.metadata["cloudeo_runtime_status"] == status
    assert METADATA_KEYS <= set(result.metadata)
    if status in {"unknown", "in_progress"}:
        assert result.status != "cancelled"
        assert result.error.startswith(RUNTIME_STATE_UNOBSERVED)


def test_dry_run_and_direct_tool_outcomes_are_rejected():
    with pytest.raises(TypeError):
        episode_result_from_outcome(outcome("dry_run"), budget=BUDGET, episode_duration_ms=1)
    direct = ExecutionOutcome(
        kind="direct_tool", status="completed", runtime=RuntimeIdentity(backend="treg")
    )
    with pytest.raises(TypeError):
        episode_result_from_outcome(direct, budget=BUDGET, episode_duration_ms=1)


# --- Metadata preservation ---


async def test_identity_usage_and_protocol_are_preserved():
    result, _ = await run(ok())
    meta = result.metadata
    assert METADATA_KEYS <= set(meta)
    assert meta["requested_harness"] == "chrn_claude"
    assert meta["actual_harness"] is None  # HarnessRouter did not echo it
    assert meta["requested_model"] == "claude-opus-5"
    assert meta["actual_model"] == "claude-opus-5"
    assert meta["model_fallback"] is None
    assert meta["response_id"] == "resp_1"
    assert meta["session_id"] == "hsess_1"
    assert meta["protocol_version"] == UHP_VERSION
    assert meta["usage"] == {"input_tokens": 10, "output_tokens": 3, "total_tokens": 13}
    assert isinstance(meta["execution_duration_ms"], int)
    assert meta["execution_error"] is None
    assert meta["supports_workspace_sync"] is False
    assert "output_text" not in meta


async def test_echoed_harness_and_model_fallback_are_kept_separate():
    metadata = {
        "session_id": "hsess_1",
        "harness_id": "chrn_echoed",
        "requested_model": "claude-opus-5",
        "model_fallback": True,
    }
    result, _ = await run(ok(model="claude-sonnet-5", metadata=metadata))
    meta = result.metadata
    assert (meta["requested_harness"], meta["actual_harness"]) == ("chrn_claude", "chrn_echoed")
    assert (meta["requested_model"], meta["actual_model"]) == ("claude-opus-5", "claude-sonnet-5")
    assert meta["model_fallback"] is True


async def test_no_text_output_is_marked_diagnostic_only():
    result, _ = await run(ok(output=[{"type": "function_call", "name": "x", "arguments": "{}"}]))
    assert result.status == "done"
    assert result.metadata["assistant_visible_output"] == ""
    assert result.metadata["actions_log_diagnostics_only"] is True


# --- Isolation ---


async def test_no_real_network_or_environment_use(monkeypatch):
    async def no_network(self, request):
        raise AssertionError("real network transport used")

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", no_network)
    result, recorder = await run(ok())
    assert result.status == "done"
    assert len(recorder.payloads) == 1
