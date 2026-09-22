import json

import httpx
import pytest
from pydantic import ValidationError

from cloudeo.uhp.client import UHPClient, UHPHTTPError, UHPProtocolError, UHPTransportError
from cloudeo.uhp.models import UHP_VERSION, UHPTaskRequest

HEADERS = {"UHP-Version": UHP_VERSION}
HARNESS = {
    "id": "chrn_test",
    "name": "Test worker",
    "base": "future-runtime",
    "object": "harness",
    "defaultModel": "test-model",
    "maxStep": 3,
    "timeoutSeconds": 60,
    "createdAt": 1786403298205,
    "skills": [{"name": "inspect"}],
    "future_config": {"enabled": True},
}
MODEL = {"id": "test-model", "available": True, "default": True, "vendor_info": "kept"}
DISCOVERY = {
    "object": "uhp.discovery",
    "protocol": "uhp",
    "versions": [UHP_VERSION],
    "default_version": UHP_VERSION,
    "conformance_class": "core",
    "capabilities": {"sessions": True, "cancellation": True},
    "implementation": {"name": "Mock server", "version": "test"},
}


def task_result(status="completed", **overrides):
    result = {
        "id": "resp_test",
        "object": "response",
        "created_at": 1786400000,
        "status": status,
        "model": "test-model",
        "store": True,
        "output": [
            {"type": "message", "content": [{"type": "output_text", "text": "partial text"}]},
            {"type": "future_output_type", "vendor_payload": {"nested": [1, 2]}},
        ],
        "error": None,
        "incomplete_details": None,
        "usage": None,
        "metadata": {"session_id": "session_test", "harness_id": "chrn_test"},
        "previous_response_id": None,
    }
    if status == "failed":
        result["error"] = {
            "type": "harness_error",
            "code": "provider_error",
            "message": "Provider failed",
            "detail": {"vendor": "test"},
            "param": None,
        }
    if status == "incomplete":
        result["incomplete_details"] = {"reason": "max_step", "steps": 3}
    result.update(overrides)
    return result


def client(handler):
    return UHPClient(
        "http://test/api/harness", "test-not-a-real-key", transport=httpx.MockTransport(handler)
    )


def check_request(request, method, path, authenticated=True):
    assert request.method == method
    assert request.url.path == "/api/harness" + path
    assert request.headers["UHP-Version"] == UHP_VERSION
    if authenticated:
        assert request.headers["Authorization"] == "Bearer test-not-a-real-key"
    else:
        assert "Authorization" not in request.headers


async def test_discovery_is_unauthenticated_and_defaults_absent_capabilities_false():
    def handler(request):
        check_request(request, "GET", "/v1/uhp", authenticated=False)
        return httpx.Response(200, json=DISCOVERY, headers=HEADERS)

    async with client(handler) as uhp:
        discovery = await uhp.discover()
    assert discovery.protocol_version == UHP_VERSION
    assert discovery.supports("sessions")
    assert not discovery.supports("files_output")
    assert discovery.implementation["version"] == "test"


@pytest.mark.parametrize("empty", [False, True])
async def test_harness_list_and_configuration_are_preserved(empty):
    def handler(request):
        check_request(request, "GET", "/v1/harnesses")
        return httpx.Response(200, json={"harnesses": [] if empty else [HARNESS]}, headers=HEADERS)

    async with client(handler) as uhp:
        result = await uhp.list_harnesses()
    assert result.protocol_version == UHP_VERSION
    if empty:
        assert result.harnesses == []
    else:
        harness = result.harnesses[0]
        assert harness.base == "future-runtime"
        assert harness.default_model == "test-model"
        assert harness.max_step == 3
        assert harness.timeout_seconds == 60
        assert harness.model_extra["future_config"] == {"enabled": True}
        assert harness.model_dump(by_alias=True)["skills"] == HARNESS["skills"]


async def test_get_harness():
    def handler(request):
        check_request(request, "GET", "/v1/harnesses/chrn_test")
        return httpx.Response(200, json=HARNESS, headers=HEADERS)

    async with client(handler) as uhp:
        result = await uhp.get_harness("chrn_test")
    assert result.id == "chrn_test"
    assert result.protocol_version == UHP_VERSION


async def test_model_catalog():
    def handler(request):
        check_request(request, "GET", "/v1/models")
        return httpx.Response(
            200,
            json={"backends": {"codex": {"default": "test-model", "models": [MODEL]}}},
            headers=HEADERS,
        )

    async with client(handler) as uhp:
        result = await uhp.list_models()
    assert result.backends["codex"].models[0].available
    assert result.protocol_version == UHP_VERSION


async def test_harness_model_availability():
    def handler(request):
        check_request(request, "GET", "/v1/harnesses/chrn_test/models")
        return httpx.Response(
            200,
            json={
                "harness_id": "chrn_test",
                "backend": "codex",
                "default": "test-model",
                "fallback": "test-model",
                "models": [MODEL, {"id": "unavailable", "available": False}],
            },
            headers=HEADERS,
        )

    async with client(handler) as uhp:
        result = await uhp.list_harness_models("chrn_test")
    assert result.fallback == "test-model"
    assert [model.available for model in result.models] == [True, False]
    assert result.protocol_version == UHP_VERSION


@pytest.mark.parametrize(
    "status", ["in_progress", "completed", "incomplete", "failed", "cancelled"]
)
async def test_task_status_and_partial_future_output_survive(status):
    wire = task_result(status)

    def handler(request):
        check_request(request, "POST", "/v1/responses")
        payload = json.loads(request.content)
        assert payload == {
            "input": "Inspect",
            "metadata": {"harness_id": "chrn_test"},
            "stream": False,
            "store": True,
        }
        return httpx.Response(200, json=wire, headers=HEADERS)

    async with client(handler) as uhp:
        result = await uhp.run_task(UHPTaskRequest(input="Inspect", harness_id="chrn_test"))
    assert result.status == status
    assert result.response_id == "resp_test"
    assert result.session_id == "session_test"
    assert result.output == wire["output"]
    assert result.usage is None
    assert result.incomplete_details == wire["incomplete_details"]
    assert result.protocol_version == UHP_VERSION
    if status == "failed":
        assert result.error.code == "provider_error"
        assert result.error.detail == {"vendor": "test"}
    assert not hasattr(result, "passed")


async def test_full_request_mapping_budget_and_idempotency():
    data = UHPTaskRequest(
        input=[{"role": "user", "content": [{"type": "input_text", "text": "Inspect"}]}],
        harness_id="chrn_test",
        model="test-model",
        instructions="Bounded work",
        previous_response_id="resp_prior",
        max_step=2,
        timeout_seconds=120,
        max_output_tokens=32,
        store=False,
    )

    def handler(request):
        check_request(request, "POST", "/v1/responses")
        payload = json.loads(request.content)
        assert payload == data.to_wire()
        assert "harness_id" not in payload
        assert payload["metadata"]["harness_id"] == "chrn_test"
        assert payload["previous_response_id"] == "resp_prior"
        assert payload["store"] is False
        assert request.extensions["timeout"]["read"] == 150.0
        assert request.headers["Idempotency-Key"] == "test-attempt-1"
        return httpx.Response(
            200, json=task_result(previous_response_id="resp_prior", store=False), headers=HEADERS
        )

    async with client(handler) as uhp:
        result = await uhp.run_task(data, idempotency_key="test-attempt-1")
    assert result.previous_response_id == "resp_prior"


async def test_model_substitution_and_usage_are_preserved():
    metadata = {
        "session_id": "session_test",
        "harness_id": "chrn_test",
        "requested_model": "wanted-model",
        "model_fallback": True,
        "model_fallback_reason": "Unavailable",
        "ignored_fields": ["max_output_tokens"],
    }
    usage = {"input_tokens": 4, "output_tokens": 2, "total_tokens": 6, "vendor_cost": 0.001}
    async with client(
        lambda request: httpx.Response(
            200, json=task_result(metadata=metadata, usage=usage), headers=HEADERS
        )
    ) as uhp:
        result = await uhp.run_task(UHPTaskRequest(input="Inspect", model="wanted-model"))
    assert result.model == "test-model"
    assert result.metadata == metadata
    assert result.usage == usage


@pytest.mark.parametrize(
    "status,code",
    [
        (400, "unsupported_protocol_version"),
        (404, "harness_not_found"),
        (422, "model_unavailable"),
        (409, "harness_mismatch"),
        (409, "session_busy"),
    ],
)
async def test_structured_http_errors_preserve_protocol_information(status, code):
    detail = {"supported": ["2026-08-11"]} if status == 400 else {"retry_after_ms": 100}
    body = {
        "error": {
            "type": "invalid_request_error",
            "code": code,
            "message": "Request rejected",
            "param": "metadata.harness_id",
            "detail": detail,
        },
        "vendor": "retained",
    }
    version = "2026-08-11" if status == 400 else UHP_VERSION
    async with client(
        lambda request: httpx.Response(status, json=body, headers={"UHP-Version": version})
    ) as uhp:
        with pytest.raises(UHPHTTPError) as caught:
            await uhp.run_task(UHPTaskRequest(input="Inspect"))
    error = caught.value
    assert error.code == code
    assert error.http_status == status
    assert error.message == "Request rejected"
    assert error.detail == detail
    assert error.body == body
    assert error.param == "metadata.harness_id"
    assert error.protocol_version == version
    assert error.version_matches == (version == UHP_VERSION)
    assert error.requested_version == UHP_VERSION


@pytest.mark.parametrize("version", [None, "2026-08-11"])
async def test_missing_or_mismatched_success_version_fails_closed(version):
    headers = {} if version is None else {"UHP-Version": version}
    async with client(lambda request: httpx.Response(200, json=DISCOVERY, headers=headers)) as uhp:
        with pytest.raises(UHPProtocolError) as caught:
            await uhp.discover()
    assert caught.value.code == "protocol_version_mismatch"
    assert caught.value.protocol_version == version
    assert caught.value.body == DISCOVERY


async def test_discovery_must_advertise_requested_version():
    body = {**DISCOVERY, "versions": ["2026-08-11"], "default_version": "2026-08-11"}
    async with client(lambda request: httpx.Response(200, json=body, headers=HEADERS)) as uhp:
        with pytest.raises(UHPProtocolError) as caught:
            await uhp.discover()
    assert caught.value.code == "unsupported_protocol_version"


async def test_get_response():
    def handler(request):
        check_request(request, "GET", "/v1/responses/resp_test")
        return httpx.Response(200, json=task_result(), headers=HEADERS)

    async with client(handler) as uhp:
        assert (await uhp.get_response("resp_test")).response_id == "resp_test"


@pytest.mark.parametrize("status", ["cancelled", "in_progress", "completed"])
async def test_cancel_preserves_actual_state_and_partial_output(status):
    def handler(request):
        check_request(request, "POST", "/v1/responses/resp_test/cancel")
        assert request.content == b""
        return httpx.Response(200, json=task_result(status), headers=HEADERS)

    async with client(handler) as uhp:
        result = await uhp.cancel_response("resp_test")
    assert result.status == status
    assert result.output == task_result(status)["output"]
    assert result.protocol_version == UHP_VERSION


async def test_timeout_does_not_retry_or_claim_cancellation():
    calls = []

    def handler(request):
        calls.append(request)
        assert request.extensions["timeout"]["read"] is None
        raise httpx.ReadTimeout("timeout", request=request)

    async with client(handler) as uhp:
        with pytest.raises(UHPTransportError) as caught:
            await uhp.run_task(UHPTaskRequest(input="Inspect"))
    assert len(calls) == 1
    assert caught.value.http_status is None
    assert caught.value.detail == {"exception_type": "ReadTimeout"}
    assert "may still be running" in caught.value.message


@pytest.mark.parametrize("body", [[], {"status": "completed"}, "not json"])
async def test_malformed_success_is_protocol_error(body):
    async with client(lambda request: httpx.Response(200, json=body, headers=HEADERS)) as uhp:
        with pytest.raises(UHPProtocolError) as caught:
            await uhp.get_response("resp_test")
    assert caught.value.code == "invalid_response"
    assert caught.value.body == body


async def test_non_json_http_error_retains_body():
    async with client(
        lambda request: httpx.Response(502, text="Bad gateway", headers=HEADERS)
    ) as uhp:
        with pytest.raises(UHPHTTPError) as caught:
            await uhp.list_harnesses()
    assert caught.value.body == "Bad gateway"
    assert caught.value.http_status == 502


async def test_redirect_is_not_followed_with_credential():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(307, headers={**HEADERS, "Location": "https://elsewhere.invalid"})

    async with client(handler) as uhp:
        with pytest.raises(UHPHTTPError):
            await uhp.list_models()
    assert len(calls) == 1


@pytest.mark.parametrize("field", ["max_step", "timeout_seconds", "max_output_tokens"])
def test_non_positive_budget_rejected(field):
    with pytest.raises(ValidationError):
        UHPTaskRequest(input="Inspect", **{field: 0})
