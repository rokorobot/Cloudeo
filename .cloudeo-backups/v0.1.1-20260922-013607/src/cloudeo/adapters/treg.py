from __future__ import annotations

import asyncio
import json
import shlex
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from cloudeo.config import Settings
from cloudeo.models import ToolCandidate


class TregError(RuntimeError):
    pass


class TregClient(ABC):
    @abstractmethod
    async def execute(self, candidate: ToolCandidate, dry_run: bool = False) -> str:
        raise NotImplementedError


class MockTregClient(TregClient):
    async def execute(self, candidate: ToolCandidate, dry_run: bool = False) -> str:
        return json.dumps(
            {
                "backend": "mock",
                "tool": candidate.treg_tool_id,
                "method": candidate.method,
                "query": candidate.query,
                "body": candidate.body,
                "dry_run": dry_run,
                "result": f"Mock successful result from {candidate.id}",
            },
            sort_keys=True,
        )


class TregCLIClient(TregClient):
    """Execute a concrete Treg catalog tool through the user's local Treg CLI.

    If CLOUDEO_TREG_REPO is set, this invokes the cloned repo directly with uv:
      uv run --project /path/to/treg treg call ...
    Otherwise it expects `treg` on PATH.
    """

    def __init__(self, settings: Settings):
        self.timeout = settings.treg_timeout_seconds
        if settings.treg_repo:
            repo = Path(settings.treg_repo).expanduser()
            if not repo.exists():
                raise TregError(f"CLOUDEO_TREG_REPO does not exist: {repo}")
            self.prefix = ["uv", "run", "--project", str(repo), "treg"]
        else:
            self.prefix = ["treg"]

    async def execute(self, candidate: ToolCandidate, dry_run: bool = False) -> str:
        command = [*self.prefix, "call", candidate.treg_tool_id]
        if candidate.method != "GET":
            command.extend(["--method", candidate.method])

        for key, value in candidate.query.items():
            command.extend(["--query", f"{key}={value}"])

        if candidate.body:
            command.extend(["--data", json.dumps(candidate.body, separators=(",", ":"))])

        if dry_run:
            return "DRY RUN: " + shlex.join(command)

        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=self.timeout)
        except TimeoutError as exc:
            process.kill()
            await process.wait()
            raise TregError(f"Treg timed out after {self.timeout}s") from exc

        out = stdout.decode(errors="replace").strip()
        err = stderr.decode(errors="replace").strip()
        if process.returncode != 0:
            raise TregError(
                f"Treg exited {process.returncode}. stdout={out[:1000]!r} stderr={err[:1000]!r}"
            )
        return out


def build_treg_client(settings: Settings) -> TregClient:
    backend = settings.treg_backend.lower()
    if backend == "cli":
        return TregCLIClient(settings)
    if backend == "mock":
        return MockTregClient()
    raise TregError(f"Unsupported Treg backend: {settings.treg_backend}")
