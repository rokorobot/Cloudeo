"""Typed dispatch of an already-selected execution request.

The dispatcher never chooses a harness, a model, or Treg versus UHP; that is
the future policy layer's job. It only sends each request type to its backend.
"""

from __future__ import annotations

from typing import Protocol, assert_never

from cloudeo.execution.contracts import (
    DirectToolExecution,
    ExecutionOutcome,
    ExecutionRequest,
    HarnessTaskExecution,
)


class DirectToolExecutionBackend(Protocol):
    async def execute(self, request: DirectToolExecution) -> ExecutionOutcome: ...


class HarnessTaskExecutionBackend(Protocol):
    async def execute(self, request: HarnessTaskExecution) -> ExecutionOutcome: ...


class ExecutionBackendUnavailable(LookupError):
    def __init__(self, kind: str):
        super().__init__(f"No execution backend configured for {kind!r} requests")
        self.kind = kind


class ExecutionDispatcher:
    def __init__(
        self,
        *,
        direct_tool: DirectToolExecutionBackend | None = None,
        harness_task: HarnessTaskExecutionBackend | None = None,
    ):
        self.direct_tool = direct_tool
        self.harness_task = harness_task

    async def execute(self, request: ExecutionRequest) -> ExecutionOutcome:
        match request:
            case DirectToolExecution():
                if self.direct_tool is None:
                    raise ExecutionBackendUnavailable(request.kind)
                return await self.direct_tool.execute(request)
            case HarnessTaskExecution():
                if self.harness_task is None:
                    raise ExecutionBackendUnavailable(request.kind)
                return await self.harness_task.execute(request)
            case _:
                assert_never(request)
