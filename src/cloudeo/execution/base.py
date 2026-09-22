from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from cloudeo.models import ExecutionEconomics, ToolCandidate


@dataclass(frozen=True)
class ExecutionResult:
    output: str
    economics: ExecutionEconomics | dict[str, Any] | None = None


class ExecutionBackend(Protocol):
    async def execute(
        self,
        candidate: ToolCandidate,
        *,
        dry_run: bool = False,
    ) -> ExecutionResult: ...
