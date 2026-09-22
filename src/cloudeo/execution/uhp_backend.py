from __future__ import annotations

import time
from typing import Any

from cloudeo.execution.contracts import (
    ExecutionCost,
    ExecutionError,
    ExecutionOutcome,
    HarnessTaskExecution,
    RuntimeIdentity,
)
from cloudeo.uhp.client import UHPClient, UHPError, UHPHTTPError, UHPProtocolError
from cloudeo.uhp.models import UHPTaskResult


def _output_text(items: list[dict[str, Any]]) -> str | None:
    """Join output_text parts of message items; other item types stay in raw_output."""

    texts = [
        part["text"]
        for item in items
        if item.get("type") == "message" and item.get("role") in (None, "assistant")
        for part in item.get("content") or []
        if isinstance(part, dict)
        and part.get("type") == "output_text"
        and isinstance(part.get("text"), str)
    ]
    return "\n".join(texts) if texts else None


def _requested(request: HarnessTaskExecution) -> dict[str, Any]:
    return {
        "backend": "uhp",
        "requested_harness": request.task.harness_id,
        "requested_model": request.task.model,
    }


def outcome_from_uhp(
    request: HarnessTaskExecution,
    result: UHPTaskResult,
    *,
    duration_ms: int | None = None,
) -> ExecutionOutcome:
    """Map a UHP task result; status is the runtime status, not verification."""

    metadata = result.metadata
    echoed_harness = metadata.get("harness_id")
    fallback = metadata.get("model_fallback")
    error = None
    if result.error is not None:
        error = ExecutionError(
            source="uhp_task",
            message=result.error.message,
            code=result.error.code,
            error_type=result.error.type,
            param=result.error.param,
            detail=result.error.detail,
            protocol_version=result.protocol_version,
        )

    return ExecutionOutcome(
        kind="harness_task",
        status=result.status,
        output_text=_output_text(result.output),
        raw_output=result.output,
        cost=ExecutionCost(harness_usage=result.usage),
        duration_ms=duration_ms,
        error=error,
        runtime=RuntimeIdentity(
            **_requested(request),
            # Only what the server echoed; HarnessRouter CE 0.23.7 may not echo it.
            actual_harness=echoed_harness if isinstance(echoed_harness, str) else None,
            actual_model=result.model,
            model_fallback=fallback if isinstance(fallback, bool) else None,
            response_id=result.response_id,
            session_id=result.session_id,
            protocol_version=result.protocol_version,
        ),
        native_result=result,
    )


def outcome_from_uhp_error(
    request: HarnessTaskExecution,
    exc: UHPError,
    *,
    duration_ms: int | None = None,
) -> ExecutionOutcome:
    """Map a request-level UHP failure.

    An HTTP error is the server rejecting the request. A transport or protocol
    failure leaves the task state unobserved: it may still be running, so the
    status is "unknown" and never "cancelled".
    """

    if isinstance(exc, UHPHTTPError):
        status, source = "failed", "uhp_http"
    elif isinstance(exc, UHPProtocolError):
        status, source = "unknown", "uhp_protocol"
    else:
        status, source = "unknown", "uhp_transport"

    return ExecutionOutcome(
        kind="harness_task",
        status=status,
        duration_ms=duration_ms,
        error=ExecutionError(
            source=source,
            message=exc.message,
            code=exc.code,
            error_type=exc.error_type,
            http_status=exc.http_status,
            param=exc.param,
            detail=exc.detail,
            body=exc.body,
            protocol_version=exc.protocol_version,
        ),
        runtime=RuntimeIdentity(**_requested(request), protocol_version=exc.protocol_version),
    )


class UHPHarnessTaskBackend:
    """Executes a HarnessTaskExecution with one non-streaming UHP request, no retries."""

    def __init__(self, client: UHPClient):
        self.client = client

    async def execute(self, request: HarnessTaskExecution) -> ExecutionOutcome:
        started = time.monotonic()
        try:
            result = await self.client.run_task(request.task)
        except UHPError as exc:
            duration_ms = round((time.monotonic() - started) * 1000)
            return outcome_from_uhp_error(request, exc, duration_ms=duration_ms)
        duration_ms = round((time.monotonic() - started) * 1000)
        return outcome_from_uhp(request, result, duration_ms=duration_ms)
