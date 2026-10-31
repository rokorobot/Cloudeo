"""Development smoke for a local UHP server. Prints no credentials.

Discovery only:   uv run python dev/uhp_smoke.py
Bounded task:     uv run python dev/uhp_smoke.py --task <harness_id> [--model <id>]

Reads CLOUDEO_UHP_BASE_URL (default: local HarnessRouter CE dev instance) and
CLOUDEO_UHP_API_KEY from the environment. Each --task run starts a new session.
Task output is execution evidence only, not verified success.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import time

from cloudeo.uhp.client import UHPClient, UHPError
from cloudeo.uhp.models import UHPTaskRequest

DEFAULT_BASE_URL = "http://127.0.0.1:18810/api/harness"
PROMPT = "Reply with exactly: CLOUDEO_UHP_OK"


def show(label: str, value: object) -> None:
    print(f"== {label}")
    print(json.dumps(value, indent=1, default=str))


def error_fields(exc: UHPError) -> dict[str, object]:
    fields = ("http_status", "code", "error_type", "message", "param", "protocol_version")
    return {name: getattr(exc, name) for name in fields}


async def discovery(uhp: UHPClient) -> None:
    found = await uhp.discover()
    show("discovery", {**found.model_dump(), "protocol_version": found.protocol_version})
    harnesses = await uhp.list_harnesses()
    show(
        "harnesses",
        [
            h.model_dump(
                include={"id", "name", "base", "default_model", "max_step", "timeout_seconds"}
            )
            for h in harnesses.harnesses
        ],
    )
    for harness in harnesses.harnesses:
        models = await uhp.list_harness_models(harness.id)
        show(
            f"models {harness.id}",
            {
                "default": models.default,
                "fallback": models.fallback,
                "models": [(m.id, m.available) for m in models.models],
            },
        )


async def task(uhp: UHPClient, harness_id: str, model: str | None) -> None:
    request = UHPTaskRequest(
        input=PROMPT, harness_id=harness_id, model=model, max_step=2, timeout_seconds=120
    )
    started = time.monotonic()
    result = await uhp.run_task(request)
    show(
        "task",
        {
            "requested_harness": harness_id,
            "actual_harness": result.metadata.get("harness_id"),
            "requested_model": model,
            "actual_model": result.model,
            "response_id": result.response_id,
            "session_id": result.session_id,
            "status": result.status,
            "output": result.output,
            "error": result.error.model_dump() if result.error else None,
            "incomplete_details": result.incomplete_details,
            "usage": result.usage,
            "metadata": result.metadata,
            "duration_seconds": round(time.monotonic() - started, 2),
            "protocol_version": result.protocol_version,
        },
    )


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", metavar="HARNESS_ID")
    parser.add_argument("--model")
    args = parser.parse_args()
    base_url = os.environ.get("CLOUDEO_UHP_BASE_URL", DEFAULT_BASE_URL)
    api_key = os.environ.get("CLOUDEO_UHP_API_KEY") or None
    print("api key present:", api_key is not None)
    async with UHPClient(base_url, api_key) as uhp:
        try:
            if args.task:
                await task(uhp, args.task, args.model)
            else:
                await discovery(uhp)
        except UHPError as exc:
            show("uhp error", error_fields(exc))
            raise SystemExit(1) from exc


if __name__ == "__main__":
    asyncio.run(main())
