import json

import httpx
import pytest
from pydantic import TypeAdapter, ValidationError

from cloudeo.adapters.treg import TregClient, TregError
from cloudeo.core.validators import validate_tool_output
from cloudeo.execution.base import ExecutionResult
from cloudeo.execution.contracts import (
    DirectToolExecution,
    ExecutionOutcome,
    ExecutionRequest,
    HarnessTaskExecution,
    RuntimeIdentity,
)
from cloudeo.execution.dispatch import ExecutionBackendUnavailable, ExecutionDispatcher
from cloudeo.execution.treg_backend import TregDirectToolBackend, outcome_from_treg
from cloudeo.execution.uhp_backend import (
    UHPHarnessTaskBackend,
    outcome_from_uhp,
)
from cloudeo.models import ExecutionEconomics, RunRequest, ToolCandidate
from cloudeo.uhp.client import UHPClient
from cloudeo.uhp.models import UHP_VERSION, UHPTaskRequest, UHPTaskResult

HEADERS = {"UHP-Version": UHP_VERSION}
REQUEST_ADAPTER = TypeAdapter(ExecutionRequest)


def candidate():
    return ToolCandidate(
        id="one", description="First provider", treg_tool_id="one.lookup", provider="acme"
    )


def harness_task(**task):
    fields = {"input": "Reply with exactly: OK", "harness_id": "chrn_test", **task}
    return HarnessTaskExecution(task=UHPTaskRequest(**fields))


def uhp_wire(status="completed", **overrides):
    wire = {
        "id": "resp_test",
        "object": "response",
        "created_at": 1786400000,
        "status": status,
        "model": "actual-model",
        "output": [
            {"type": "reasoning", "summary": [{"text": "thinking"}]},
            {
                "type": "message",
                "role": "assistant",
                "content": [
                    {"type": "output_text", "text": "partial"},
                    {"type": "future_part", "blob": 1},
                    {"type": "output_text", "text": "answer"},
                ],
            },
            {"type": "future_output_type", "vendor_payload": {"nested": [1, 2]}},
        ],
        "error": None,
        "incomplete_details": None,
        "usage": None,
        "metadata": {"session_id": "hsess_test"},
        "previous_response_id": None,
    }
    if status == "failed":
        wire["error"] = {
            "type": "harness_error",
            "code": "provider_error",
            "message": "Provider failed",
            "param": None,
            "detail": {"vendor": "test"},
        }
    if status == "incomplete":
        wire["incomplete_details"] = {"reason": "max_step"}
    wire.update(overrides)
    return wire


def uhp_result(status="completed", **overrides):
    result = UHPTaskResult.model_validate(uhp_wire(status, **overrides))
    result.protocol_version = UHP_VERSION
    return result


def uhp_backend(handler):
    client = UHPClient("http://test/api/harness", transport=httpx.MockTransport(handler))
    return client, UHPHarnessTaskBackend(client)


class FakeTreg(TregClient):
    def __init__(self, output="provider output", error=None):
        self.output = output
        self.error = error
        self.calls = []
        self.last_execution_economics = {"call_id": "earlier", "settled_cost_usd": 0.005}

    async def execute(self, candidate, dry_run=False):
        self.calls.append((candidate, dry_run))
        if self.error is not None:
            raise self.error
        return self.output


# --- Request construction and discrimination ---


def test_direct_tool_request_keeps_candidate_unchanged():
    selected = candidate()
    request = DirectToolExecution(candidate=selected, dry_run=True)
    assert request.kind == "direct_tool"
    assert request.candidate == selected
    assert request.dry_run is True


def test_harness_task_request_reuses_uhp_task_model():
    request = harness_task(model="wanted", max_step=2, timeout_seconds=60)
    assert request.kind == "harness_task"
    assert isinstance(request.task, UHPTaskRequest)
    assert request.task.to_wire()["metadata"] == {"harness_id": "chrn_test"}


def test_harness_task_must_name_a_harness():
    with pytest.raises(ValidationError, match="harness_id"):
        HarnessTaskExecution(task=UHPTaskRequest(input="x"))


@pytest.mark.parametrize(
    "data,expected",
    [
        ({"kind": "direct_tool", "candidate": candidate().model_dump()}, DirectToolExecution),
        (
            {"kind": "harness_task", "task": {"input": "x", "harness_id": "chrn_test"}},
            HarnessTaskExecution,
        ),
    ],
)
def test_request_union_discriminates_on_kind(data, expected):
    assert type(REQUEST_ADAPTER.validate_python(data)) is expected


@pytest.mark.parametrize(
    "data",
    [
        {"kind": "direct_tool", "task": {"input": "x", "harness_id": "chrn_test"}},
        {"kind": "harness_task", "candidate": candidate().model_dump()},
        {"kind": "harness_task", "task": {"input": "x", "harness_id": "h"}, "dry_run": True},
        {"kind": "unknown", "candidate": candidate().model_dump()},
    ],
)
def test_illegal_request_combinations_are_rejected(data):
    with pytest.raises(ValidationError):
        REQUEST_ADAPTER.validate_python(data)


def test_runtime_status_has_no_verification_states():
    statuses = set(ExecutionOutcome.model_fields["status"].annotation.__args__)
    assert statuses == {
        "in_progress",
        "completed",
        "failed",
        "incomplete",
        "cancelled",
        "dry_run",
        "unknown",
    }
    assert not {"passed", "verified", "pass", "fail"} & statuses


# --- Treg mapping ---


async def test_treg_success_maps_to_completed_and_preserves_native_result():
    client = FakeTreg()
    request = DirectToolExecution(candidate=candidate())
    outcome = await TregDirectToolBackend(client).execute(request)
    assert client.calls == [(request.candidate, False)]
    assert outcome.kind == "direct_tool"
    assert outcome.status == "completed"
    assert outcome.output_text == outcome.raw_output == "provider output"
    assert outcome.error is None
    assert outcome.cost.direct_tool_economics == client.last_execution_economics
    assert type(outcome.cost.direct_tool_economics) is dict
    assert outcome.cost.harness_usage is None
    assert outcome.runtime == RuntimeIdentity(backend="treg", requested_tool="one.lookup")
    assert outcome.native_result == ExecutionResult(
        output="provider output", economics=client.last_execution_economics
    )
    assert type(outcome.native_result.economics) is dict
    assert outcome.duration_ms is not None and outcome.duration_ms >= 0
    assert outcome.artifacts == []


async def test_treg_error_keeps_exact_legacy_text_and_retained_economics():
    client = FakeTreg(error=TregError("provider unavailable"))
    outcome = await TregDirectToolBackend(client).execute(
        DirectToolExecution(candidate=candidate())
    )
    assert outcome.status == "failed"
    assert outcome.output_text == "TREG_ERROR: provider unavailable"
    assert outcome.error.source == "treg"
    assert outcome.error.message == "provider unavailable"
    assert outcome.error.code is None
    # Legacy behavior: a failed attempt reports whatever economics the client retained.
    assert outcome.cost.direct_tool_economics == {"call_id": "earlier", "settled_cost_usd": 0.005}


def test_treg_native_result_and_economics_are_kept_as_is():
    extra = {"call_id": "c1", "settled_cost_usd": 0.01, "vendor_field": "kept"}
    result = ExecutionResult(output="ok", economics=extra)
    outcome = outcome_from_treg(DirectToolExecution(candidate=candidate()), result)
    assert outcome.native_result is result
    assert outcome.cost.direct_tool_economics == extra
    typed = ExecutionResult(output="ok", economics=ExecutionEconomics(call_id="c2"))
    typed_outcome = outcome_from_treg(DirectToolExecution(candidate=candidate()), typed)
    assert typed_outcome.cost.direct_tool_economics is typed.economics


def test_treg_error_output_still_fails_existing_validator():
    request = DirectToolExecution(candidate=candidate())
    outcome = outcome_from_treg(request, ExecutionResult(output="TREG_ERROR: provider unavailable"))
    run = RunRequest(objective="Find the work email")
    assert validate_tool_output(run, request.candidate, outcome.output_text).status == "fail"


async def test_treg_dry_run_is_distinguishable():
    client = FakeTreg(output=json.dumps({"dry_run": True}))
    outcome = await TregDirectToolBackend(client).execute(
        DirectToolExecution(candidate=candidate(), dry_run=True)
    )
    assert client.calls[0][1] is True
    assert outcome.status == "dry_run"
    assert outcome.error is None
    assert outcome.output_text == json.dumps({"dry_run": True})


async def test_treg_dry_run_failure_still_propagates():
    client = FakeTreg(error=TregError("cannot prepare command"))
    with pytest.raises(TregError) as caught:
        await TregDirectToolBackend(client).execute(
            DirectToolExecution(candidate=candidate(), dry_run=True)
        )
    assert caught.value is client.error


# --- UHP mapping ---


@pytest.mark.parametrize(
    "status", ["completed", "failed", "incomplete", "cancelled", "in_progress"]
)
def test_uhp_status_maps_faithfully_and_keeps_partial_output(status):
    result = uhp_result(status)
    outcome = outcome_from_uhp(harness_task(), result, duration_ms=12)
    assert outcome.kind == "harness_task"
    assert outcome.status == status
    assert outcome.raw_output == result.output
    assert outcome.raw_output[2]["type"] == "future_output_type"
    assert outcome.output_text == "partial\nanswer"
    assert outcome.duration_ms == 12
    assert outcome.native_result is result
    assert outcome.runtime.response_id == "resp_test"
    assert outcome.runtime.session_id == "hsess_test"
    assert outcome.runtime.protocol_version == UHP_VERSION
    if status == "failed":
        assert outcome.error.source == "uhp_task"
        assert outcome.error.code == "provider_error"
        assert outcome.error.error_type == "harness_error"
        assert outcome.error.detail == {"vendor": "test"}
    else:
        assert outcome.error is None
    if status == "incomplete":
        assert outcome.native_result.incomplete_details == {"reason": "max_step"}


def test_uhp_output_without_text_has_no_output_text():
    result = uhp_result(output=[{"type": "function_call", "name": "shell", "arguments": "{}"}])
    outcome = outcome_from_uhp(harness_task(), result)
    assert outcome.output_text is None
    assert outcome.raw_output == result.output


def test_uhp_actual_harness_stays_null_when_not_echoed():
    outcome = outcome_from_uhp(harness_task(), uhp_result())
    assert outcome.runtime.requested_harness == "chrn_test"
    assert outcome.runtime.actual_harness is None


def test_uhp_actual_harness_recorded_only_when_echoed():
    result = uhp_result(metadata={"session_id": "hsess_test", "harness_id": "chrn_echo"})
    assert outcome_from_uhp(harness_task(), result).runtime.actual_harness == "chrn_echo"


def test_uhp_requested_and_actual_model_are_distinct():
    metadata = {
        "session_id": "hsess_test",
        "requested_model": "wanted",
        "model_fallback": True,
        "model_fallback_reason": "Unavailable",
    }
    outcome = outcome_from_uhp(harness_task(model="wanted"), uhp_result(metadata=metadata))
    assert outcome.runtime.requested_model == "wanted"
    assert outcome.runtime.actual_model == "actual-model"
    assert outcome.runtime.model_fallback is True
    assert outcome.native_result.metadata == metadata


def test_uhp_default_model_request_is_not_backfilled():
    outcome = outcome_from_uhp(harness_task(), uhp_result())
    assert outcome.runtime.requested_model is None
    assert outcome.runtime.model_fallback is None


def test_uhp_usage_is_preserved_and_not_converted_to_money():
    usage = {"input_tokens": 4, "output_tokens": 2, "total_tokens": 6, "vendor_cost": 0.001}
    outcome = outcome_from_uhp(harness_task(), uhp_result(usage=usage))
    assert outcome.cost.harness_usage == usage
    assert outcome.cost.direct_tool_economics is None


def test_uhp_missing_usage_stays_none():
    assert outcome_from_uhp(harness_task(), uhp_result()).cost.harness_usage is None


async def test_uhp_backend_runs_one_request_and_maps_result():
    calls = []

    def handler(request):
        calls.append(request)
        assert json.loads(request.content)["metadata"] == {"harness_id": "chrn_test"}
        return httpx.Response(200, json=uhp_wire(), headers=HEADERS)

    client, backend = uhp_backend(handler)
    async with client:
        outcome = await backend.execute(harness_task())
    assert len(calls) == 1
    assert outcome.status == "completed"
    assert outcome.native_result.protocol_version == UHP_VERSION
    assert outcome.duration_ms is not None


async def test_uhp_transport_timeout_is_unknown_not_cancelled():
    calls = []

    def handler(request):
        calls.append(request)
        raise httpx.ReadTimeout("timeout", request=request)

    client, backend = uhp_backend(handler)
    async with client:
        outcome = await backend.execute(harness_task(timeout_seconds=30))
    assert len(calls) == 1
    assert outcome.status == "unknown"
    assert outcome.status != "cancelled"
    assert outcome.error.source == "uhp_transport"
    assert outcome.error.detail == {"exception_type": "ReadTimeout"}
    assert outcome.native_result is None
    assert outcome.runtime.response_id is None
    assert outcome.runtime.requested_harness == "chrn_test"


async def test_uhp_protocol_error_is_unknown():
    client, backend = uhp_backend(lambda request: httpx.Response(200, json=uhp_wire()))
    async with client:
        outcome = await backend.execute(harness_task())
    assert outcome.status == "unknown"
    assert outcome.error.source == "uhp_protocol"
    assert outcome.error.code == "protocol_version_mismatch"


async def test_uhp_http_error_is_failed_with_structured_error():
    body = {
        "error": {
            "type": "invalid_request_error",
            "code": "harness_mismatch",
            "message": "Session belongs to another harness",
            "param": "metadata.harness_id",
            "detail": None,
        }
    }
    client, backend = uhp_backend(lambda request: httpx.Response(409, json=body, headers=HEADERS))
    async with client:
        outcome = await backend.execute(harness_task(previous_response_id="resp_prior"))
    assert outcome.status == "failed"
    assert outcome.error.source == "uhp_http"
    assert outcome.error.code == "harness_mismatch"
    assert outcome.error.http_status == 409
    assert outcome.error.param == "metadata.harness_id"
    assert outcome.error.body == body
    assert outcome.error.protocol_version == UHP_VERSION


@pytest.mark.parametrize(
    "http_status,error_type,code,expected",
    [
        (400, "invalid_request_error", "invalid_input", "failed"),
        (401, "authentication_error", "missing_credential", "failed"),
        (404, "invalid_request_error", "harness_not_found", "failed"),
        (409, "invalid_request_error", "session_busy", "failed"),
        (422, "invalid_request_error", "model_unavailable", "failed"),
        (429, "rate_limit_error", "rate_limited", "failed"),
        (408, "invalid_request_error", "request_timeout", "unknown"),
        (500, "server_error", "server_error", "unknown"),
        (502, "server_error", "harness_unavailable", "unknown"),
        (503, "server_error", "harness_unavailable", "unknown"),
        (504, "server_error", "timeout", "unknown"),
        (307, None, None, "unknown"),
    ],
)
async def test_uhp_http_status_maps_to_what_cloudeo_knows(http_status, error_type, code, expected):
    body = (
        {
            "error": {
                "type": error_type,
                "code": code,
                "message": "Request not completed",
                "param": "metadata.harness_id",
                "detail": {"vendor": "kept"},
            }
        }
        if code
        else {"vendor": "no envelope"}
    )
    client, backend = uhp_backend(
        lambda request: httpx.Response(http_status, json=body, headers=HEADERS)
    )
    async with client:
        outcome = await backend.execute(harness_task())
    assert outcome.status == expected
    assert outcome.status != "cancelled"
    assert outcome.native_result is None
    error = outcome.error
    assert error.source == "uhp_http"
    assert error.http_status == http_status
    assert error.body == body
    assert error.protocol_version == UHP_VERSION
    if code:
        assert (error.code, error.error_type) == (code, error_type)
        assert error.message == "Request not completed"
        assert error.param == "metadata.harness_id"
        assert error.detail == {"vendor": "kept"}
    else:
        assert error.code == "http_error"


def refuse_connection(request):
    raise httpx.ConnectError("down", request=request)


def malformed_success(request):
    return httpx.Response(200, json={"not": "a response"}, headers=HEADERS)


@pytest.mark.parametrize(
    "handler,source",
    [(refuse_connection, "uhp_transport"), (malformed_success, "uhp_protocol")],
)
async def test_uhp_transport_and_protocol_failures_are_unknown(handler, source):
    client, backend = uhp_backend(handler)
    async with client:
        outcome = await backend.execute(harness_task())
    assert outcome.status == "unknown"
    assert outcome.status != "cancelled"
    assert outcome.error.source == source


# --- Dispatcher ---


class RecordingBackend:
    def __init__(self, kind):
        self.kind = kind
        self.requests = []

    async def execute(self, request):
        self.requests.append(request)
        backend = "treg" if self.kind == "direct_tool" else "uhp"
        return ExecutionOutcome(
            kind=self.kind, status="completed", runtime=RuntimeIdentity(backend=backend)
        )


async def test_dispatcher_routes_each_request_type_to_its_backend():
    direct, harness = RecordingBackend("direct_tool"), RecordingBackend("harness_task")
    dispatcher = ExecutionDispatcher(direct_tool=direct, harness_task=harness)
    tool_request = DirectToolExecution(candidate=candidate())
    task_request = harness_task()

    assert (await dispatcher.execute(tool_request)).kind == "direct_tool"
    assert (await dispatcher.execute(task_request)).kind == "harness_task"
    assert direct.requests == [tool_request]
    assert harness.requests == [task_request]


async def test_dispatcher_does_not_substitute_a_missing_backend():
    direct = RecordingBackend("direct_tool")
    dispatcher = ExecutionDispatcher(direct_tool=direct)
    with pytest.raises(ExecutionBackendUnavailable) as caught:
        await dispatcher.execute(harness_task())
    assert caught.value.kind == "harness_task"
    assert direct.requests == []


async def test_dispatcher_with_real_backends_end_to_end():
    client, uhp = uhp_backend(lambda request: httpx.Response(200, json=uhp_wire(), headers=HEADERS))
    dispatcher = ExecutionDispatcher(
        direct_tool=TregDirectToolBackend(FakeTreg()), harness_task=uhp
    )
    async with client:
        tool = await dispatcher.execute(DirectToolExecution(candidate=candidate()))
        task = await dispatcher.execute(harness_task())
    assert (tool.runtime.backend, tool.status) == ("treg", "completed")
    assert (task.runtime.backend, task.status) == ("uhp", "completed")
