from __future__ import annotations

import time

from cloudeo.adapters.treg import TregClient, TregError
from cloudeo.execution.base import ExecutionBackend, ExecutionResult
from cloudeo.execution.contracts import (
    DirectToolExecution,
    ExecutionCost,
    ExecutionError,
    ExecutionOutcome,
    RuntimeIdentity,
)
from cloudeo.models import ToolCandidate

# Same marker the deterministic validators test for.
TREG_ERROR_PREFIX = "TREG_ERROR:"


class TregExecutionBackend:
    def __init__(self, client: TregClient):
        self.client = client

    async def execute(
        self,
        candidate: ToolCandidate,
        *,
        dry_run: bool = False,
    ) -> ExecutionResult:
        try:
            output = await self.client.execute(candidate, dry_run=dry_run)
        except TregError as exc:
            if dry_run:
                raise
            output = f"{TREG_ERROR_PREFIX} {exc}"

        # Preserve legacy economics, including values retained after a failure.
        # This extraction does not change the client's shared mutable state.
        return ExecutionResult(
            output=output,
            economics=getattr(self.client, "last_execution_economics", None),
        )


def outcome_from_treg(
    request: DirectToolExecution,
    result: ExecutionResult,
    *,
    duration_ms: int | None = None,
) -> ExecutionOutcome:
    """Map a legacy Treg result without altering its output or economics."""

    error = None
    if request.dry_run:
        status = "dry_run"
    elif result.output.startswith(TREG_ERROR_PREFIX):
        status = "failed"
        message = result.output[len(TREG_ERROR_PREFIX) :]
        error = ExecutionError(source="treg", message=message.removeprefix(" "))
    else:
        status = "completed"

    return ExecutionOutcome(
        kind="direct_tool",
        status=status,
        output_text=result.output,
        raw_output=result.output,
        # Legacy economics are passed through as-is, including a value that a
        # failed attempt may have retained from an earlier call.
        cost=ExecutionCost(direct_tool_economics=result.economics),
        duration_ms=duration_ms,
        error=error,
        runtime=RuntimeIdentity(backend="treg", requested_tool=request.candidate.treg_tool_id),
        native_result=result,
    )


class LegacyDirectToolBackend:
    """Executes a DirectToolExecution through a legacy Treg-shaped ExecutionBackend."""

    def __init__(self, backend: ExecutionBackend):
        self._legacy = backend

    async def execute(self, request: DirectToolExecution) -> ExecutionOutcome:
        started = time.monotonic()
        # Dry-run preparation errors still propagate, as in the legacy path.
        result = await self._legacy.execute(request.candidate, dry_run=request.dry_run)
        duration_ms = round((time.monotonic() - started) * 1000)
        return outcome_from_treg(request, result, duration_ms=duration_ms)


class TregDirectToolBackend(LegacyDirectToolBackend):
    """Executes a DirectToolExecution through the existing Treg execution path."""

    def __init__(self, client: TregClient):
        super().__init__(TregExecutionBackend(client))
