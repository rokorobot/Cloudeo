from __future__ import annotations

from cloudeo.adapters.treg import TregClient, TregError
from cloudeo.execution.base import ExecutionResult
from cloudeo.models import ToolCandidate


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
            output = f"TREG_ERROR: {exc}"

        # Preserve legacy economics, including values retained after a failure.
        # This extraction does not change the client's shared mutable state.
        return ExecutionResult(
            output=output,
            economics=getattr(self.client, "last_execution_economics", None),
        )
