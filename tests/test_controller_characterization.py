"""Golden characterization of Controller.run() on the default Treg wiring.

tests/fixtures/controller_golden_v0122.json was captured from the controller at
main 10d4b71, before execution-dispatch adoption, using capture() below. These
tests require the current controller to reproduce it exactly (run IDs are
normalized). Do not regenerate the fixture to make a behavior change pass.
"""

import importlib
import json
from pathlib import Path

import httpx
import pytest
from sqlmodel import select

from cloudeo import config
from cloudeo.adapters.jev import MockJevClient
from cloudeo.adapters.treg import TregClient, TregError
from cloudeo.config import Settings
from cloudeo.core import controller as controller_module
from cloudeo.core.controller import Controller
from cloudeo.db.models import RunRecord
from cloudeo.db.session import Database
from cloudeo.models import RunRequest, ToolCandidate

GOLDEN = Path(__file__).parent / "fixtures" / "controller_golden_v0122.json"
RUN_ID = "<run_id>"

VERIFIED_OUTPUT = json.dumps(
    {
        "email": "ada@example.com",
        "fullName": "Ada Example",
        "validIdentity": True,
        "validSMTP": True,
        "validity": "valid",
    },
    sort_keys=True,
)


class ScriptedTreg(TregClient):
    """Treg client whose economics follow the legacy shared-attribute pattern."""

    def __init__(self, script):
        self.script = script
        self.calls = []
        self.last_execution_economics = None

    async def execute(self, candidate, dry_run=False):
        self.calls.append([candidate.id, dry_run])
        step = self.script[candidate.id]
        if isinstance(step, Exception):
            # Economics are intentionally not updated: a failure keeps the
            # previous attempt's values, as the legacy client does.
            raise step
        n = len(self.calls)
        self.last_execution_economics = {
            "call_id": f"{candidate.id}-{n}",
            "settled_cost_usd": round(0.001 * n, 6),
            "latency_ms": 5 * n,
            "provider_requested": candidate.provider,
            "provider_served": candidate.id,
        }
        return step


class ScriptedJev(MockJevClient):
    def __init__(self, choice="first", confidence=0.94, probabilities=None):
        self.choice = choice
        self.confidence = confidence
        self.probabilities = probabilities or {"first": 0.8, "second": 0.15, "escalate": 0.05}
        self.verification_outputs = []

    async def decide(self, state, questions):
        if "tool_route" in questions:
            answer = {
                "choice": self.choice,
                "confidence": self.confidence,
                "probabilities": self.probabilities,
            }
            return {"answers": {"tool_route": answer}}
        self.verification_outputs.append(state["tool_output"])
        return await super().decide(state, questions)


def unavailable(name):
    return TregError(f"{name} unavailable")


SCENARIOS = {
    "deterministic_pass": {"script": {"first": VERIFIED_OUTPUT}},
    "jev_verified": {"script": {"first": "Unstructured candidate evidence"}},
    "treg_error_then_pass": {"script": {"first": unavailable("first"), "second": VERIFIED_OUTPUT}},
    "jev_fail_then_treg_error_stale_economics": {
        "script": {"first": "mock_fail unstructured result", "second": unavailable("second")}
    },
    "all_treg_errors_escalate": {
        "script": {"first": unavailable("first"), "second": unavailable("second")}
    },
    "duplicate_ranking_preserved": {
        "script": {"first": unavailable("first"), "second": unavailable("second")},
        "jev": {"choice": "second"},
        "request": {"max_attempts": 3},
    },
    "attempt_limit_one": {
        "script": {"first": "mock_fail unstructured result", "second": VERIFIED_OUTPUT},
        "request": {"max_attempts": 1},
    },
    "routing_escalate_no_execution": {
        "script": {},
        "jev": {"confidence": 0.1},
    },
    "dry_run": {
        "script": {"first": "DRY RUN: treg call first.email"},
        "request": {"dry_run": True},
    },
    "dry_run_preparation_error": {
        "script": {"first": TregError("cannot prepare command")},
        "request": {"dry_run": True},
    },
}

API_SCENARIOS = [
    "deterministic_pass",
    "treg_error_then_pass",
    "dry_run",
    "dry_run_preparation_error",
]


def run_request(**overrides):
    values = {
        "objective": "Find the verified work email for Ada Example",
        "state": {"person": "Ada Example", "company_domain": "example.com"},
        "candidates": [
            ToolCandidate(
                id=name,
                description="Work email provider",
                treg_tool_id=f"{name}.email",
                provider=f"{name}-provider",
            )
            for name in ("first", "second")
        ],
        "route_confidence": 0.65,
        "verify_probability": 0.85,
        "max_attempts": 2,
    }
    values.update(overrides)
    return RunRequest(**values)


def normalize(value):
    """Replace the generated run ID wherever it appears; nothing else changes."""
    text = json.dumps(value)
    run_id = value.get("run_id") or value.get("id")
    return json.loads(text.replace(run_id, RUN_ID) if run_id else text)


async def build(name):
    spec = SCENARIOS[name]
    settings = Settings(_env_file=None, database_url="sqlite+aiosqlite:///:memory:")
    database = Database(settings)
    await database.init()
    treg = ScriptedTreg(spec["script"])
    jev = ScriptedJev(**spec.get("jev", {}))
    # Default wiring, exactly as api/app.py constructs the controller.
    subject = Controller(settings, jev, treg, database)
    return subject, database, treg, jev, run_request(**spec.get("request", {}))


async def observe(name, monkeypatch):
    subject, database, treg, jev, request = await build(name)
    validator_inputs = []
    original = controller_module.validate_tool_output

    def recording_validator(req, candidate, output):
        validator_inputs.append([candidate.id, output])
        return original(req, candidate, output)

    monkeypatch.setattr(controller_module, "validate_tool_output", recording_validator)
    observed = {}
    try:
        response = await subject.run(request)
    except Exception as exc:  # noqa: BLE001 - characterizing the raised type
        observed["error"] = {"type": type(exc).__name__, "message": str(exc)}
    else:
        observed["response"] = normalize(response.model_dump(mode="json"))
    async with database.session() as session:
        rows = (await session.exec(select(RunRecord))).all()
    observed["records"] = [
        normalize(
            {
                "id": row.id,
                "objective": row.objective,
                "status": row.status,
                "selected_tool": row.selected_tool,
                "route_confidence": row.route_confidence,
                "payload": json.loads(row.payload_json),
                "result": json.loads(row.result_json),
            }
        )
        for row in rows
    ]
    observed["treg_calls"] = treg.calls
    observed["validator_inputs"] = validator_inputs
    observed["verification_outputs"] = jev.verification_outputs
    await database.engine.dispose()
    return observed


def api_module(monkeypatch):
    # Never let the API module build clients from a local .env (real Jev/Treg).
    for key, value in {
        "jev_backend": "mock",
        "treg_backend": "mock",
        "treg_repo": None,
        "database_url": "sqlite+aiosqlite:///:memory:",
    }.items():
        monkeypatch.setattr(config.settings, key, value)
    return importlib.import_module("cloudeo.api.app")


async def observe_api(name, monkeypatch):
    app_module = api_module(monkeypatch)
    subject, database, _, _, request = await build(name)
    monkeypatch.setattr(app_module, "controller", subject)
    transport = httpx.ASGITransport(app=app_module.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://cloudeo.test") as client:
        reply = await client.post("/v1/runs", json=request.model_dump(mode="json"))
    await database.engine.dispose()
    body = reply.json()
    return {"status_code": reply.status_code, "body": normalize(body) if "run_id" in body else body}


async def capture(monkeypatch):
    """Produce the golden document. Used once, against the pre-migration controller."""
    scenarios = {}
    for name in SCENARIOS:
        with monkeypatch.context() as scoped:
            scenarios[name] = await observe(name, scoped)
    api = {}
    for name in API_SCENARIOS:
        with monkeypatch.context() as scoped:
            api[name] = await observe_api(name, scoped)
    return {"scenarios": scenarios, "api": api}


@pytest.fixture(scope="module")
def golden():
    return json.loads(GOLDEN.read_text())


@pytest.mark.parametrize("name", list(SCENARIOS))
async def test_controller_matches_pre_migration_golden(name, golden, monkeypatch):
    assert await observe(name, monkeypatch) == golden["scenarios"][name]


@pytest.mark.parametrize("name", API_SCENARIOS)
async def test_api_matches_pre_migration_golden(name, golden, monkeypatch):
    assert await observe_api(name, monkeypatch) == golden["api"][name]


def test_golden_covers_the_required_behaviors(golden):
    scenarios = golden["scenarios"]
    # TREG_ERROR text reaches the validator verbatim and fails deterministically.
    assert ["first", "TREG_ERROR: first unavailable"] in scenarios["treg_error_then_pass"][
        "validator_inputs"
    ]
    # Legacy stale economics: the failed second attempt reports the first call's values.
    stale = scenarios["jev_fail_then_treg_error_stale_economics"]["response"]["attempts"]
    assert stale[1]["output"] == "TREG_ERROR: second unavailable"
    assert stale[1]["economics"]["call_id"] == stale[0]["economics"]["call_id"] == "first-1"
    # Legacy duplicate ranking and dry-run semantics.
    assert scenarios["duplicate_ranking_preserved"]["treg_calls"] == [
        ["second", False],
        ["first", False],
        ["second", False],
    ]
    assert scenarios["dry_run"]["validator_inputs"] == []
    assert scenarios["dry_run_preparation_error"]["error"] == {
        "type": "TregError",
        "message": "cannot prepare command",
    }
    assert golden["api"]["dry_run_preparation_error"] == {
        "status_code": 502,
        "body": {"detail": "cannot prepare command"},
    }
