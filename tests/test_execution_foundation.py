import json

import pytest
import pytest_asyncio
from sqlmodel import select

from cloudeo.adapters.jev import MockJevClient
from cloudeo.adapters.treg import TregClient
from cloudeo.config import Settings
from cloudeo.core.controller import Controller
from cloudeo.db.models import RunRecord
from cloudeo.db.session import Database
from cloudeo.execution.base import ExecutionResult
from cloudeo.models import RunRequest, ToolCandidate

VERIFIED_OUTPUT = json.dumps(
    {
        "email": "ada@example.com",
        "fullName": "Ada Example",
        "validIdentity": True,
        "validSMTP": True,
        "validity": "valid",
    }
)


class DiscoveryOnlyTreg(TregClient):
    def __init__(self):
        self.discovery_calls = []
        self.candidates = []
        self.last_discovery_query = "work email"
        self.last_discovery_evidence = {
            "selected_query": "work email",
            "capability_anchor": "people.email.find",
            "queries": [],
            "endpoints": [],
        }

    async def execute(self, candidate, dry_run=False):
        raise AssertionError("Injected backend must own execution")

    async def discover(self, request):
        self.discovery_calls.append(request)
        return self.candidates


class FakeBackend:
    def __init__(self, outputs):
        self.outputs = outputs
        self.calls = []

    async def execute(self, candidate, *, dry_run=False):
        self.calls.append((candidate, dry_run))
        return ExecutionResult(
            output=self.outputs[candidate.id],
            economics={"settled_cost_usd": 0.005, "call_id": candidate.id},
        )


class RecordingJev(MockJevClient):
    def __init__(self, choice="first", confidence=0.94):
        self.choice = choice
        self.confidence = confidence
        self.verifications = []

    async def decide(self, state, questions):
        if "tool_route" in questions:
            return {
                "answers": {
                    "tool_route": {
                        "choice": self.choice,
                        "confidence": self.confidence,
                        "probabilities": {"first": 0.8, "second": 0.15, "escalate": 0.05},
                    }
                }
            }
        self.verifications.append((state, questions))
        return await super().decide(state, questions)


@pytest_asyncio.fixture
async def database():
    settings = Settings(_env_file=None, database_url="sqlite+aiosqlite:///:memory:")
    database = Database(settings)
    await database.init()
    try:
        yield database
    finally:
        await database.engine.dispose()


def request(**overrides):
    values = {
        "objective": "Find the verified work email for Ada Example",
        "state": {"person": "Ada Example", "company_domain": "example.com"},
        "candidates": [
            ToolCandidate(id=name, description="Work email provider", treg_tool_id=f"{name}.email")
            for name in ("first", "second")
        ],
        "route_confidence": 0.65,
        "verify_probability": 0.85,
        "max_attempts": 2,
    }
    values.update(overrides)
    return RunRequest(**values)


def controller(database, outputs, *, jev=None, treg=None):
    backend = FakeBackend(outputs)
    jev = jev if jev is not None else RecordingJev()
    treg = treg if treg is not None else DiscoveryOnlyTreg()
    settings = Settings(_env_file=None)
    return Controller(settings, jev, treg, database, execution_backend=backend), backend, jev


@pytest.mark.parametrize(
    "output,status,verification_count,probability",
    [
        (VERIFIED_OUTPUT, "passed", 0, 1.0),
        ("TREG_ERROR: unavailable", "escalate", 0, 0.0),
        ("Unstructured candidate evidence", "passed", 1, 0.93),
    ],
)
async def test_injected_backend_preserves_verification_paths(
    database,
    output,
    status,
    verification_count,
    probability,
):
    subject, backend, jev = controller(database, {"first": output})
    run_request = request(max_attempts=1)
    result = await subject.run(run_request)
    assert result.status == status
    assert backend.calls == [(run_request.candidates[0], False)]
    assert backend.calls[0][0] is run_request.candidates[0]
    assert len(jev.verifications) == verification_count
    assert result.attempts[0].verification_probability == probability
    assert result.attempts[0].output == output
    assert result.attempts[0].economics.call_id == "first"


@pytest.mark.parametrize(
    "max_attempts,expected_ids,status",
    [
        (1, ["first"], "escalate"),
        (2, ["first", "second"], "passed"),
    ],
)
async def test_retry_order_and_attempt_limit(database, max_attempts, expected_ids, status):
    subject, backend, jev = controller(
        database,
        {
            "first": "mock_fail unstructured result",
            "second": VERIFIED_OUTPUT,
        },
    )
    result = await subject.run(request(max_attempts=max_attempts))
    assert [candidate.id for candidate, _ in backend.calls] == expected_ids
    assert [attempt.tool_id for attempt in result.attempts] == expected_ids
    assert result.status == status
    assert len(jev.verifications) == 1
    assert result.attempts[0].verification_probability == 0.20
    if status == "passed":
        assert result.selected_tool == "second"


async def test_exhaustion_preserves_escalation_response(database):
    subject, backend, jev = controller(
        database,
        {
            "first": "TREG_ERROR: first unavailable",
            "second": "TREG_ERROR: second unavailable",
        },
    )
    result = await subject.run(request())
    assert result.status == "escalate"
    assert result.selected_tool == "first"
    assert result.route_confidence == 0.94
    assert result.reason == "No attempted tool produced a result above the verification threshold."
    assert [candidate.id for candidate, _ in backend.calls] == ["first", "second"]
    assert all(not attempt.passed for attempt in result.attempts)
    assert not jev.verifications


async def test_dry_run_prepares_once_without_validation_or_fallback(database, monkeypatch):
    def unexpected_validation(*args):
        raise AssertionError("Dry run must not validate")

    monkeypatch.setattr("cloudeo.core.controller.validate_tool_output", unexpected_validation)
    subject, backend, jev = controller(database, {"first": "DRY RUN: treg call first.email"})
    result = await subject.run(request(dry_run=True))
    assert [(candidate.id, dry_run) for candidate, dry_run in backend.calls] == [("first", True)]
    assert result.status == "dry_run"
    assert result.selected_tool == "first"
    assert len(result.attempts) == 1
    assert result.attempts[0].verification_source == "dry_run"
    assert result.attempts[0].verification_probability == 0.0
    assert result.attempts[0].passed is False
    assert not jev.verifications


async def test_discovery_stays_on_treg_with_injected_executor(database):
    treg = DiscoveryOnlyTreg()
    treg.candidates = request().candidates
    subject, backend, _ = controller(database, {"first": VERIFIED_OUTPUT}, treg=treg)
    run_request = request(candidates=[])
    result = await subject.run(run_request)
    assert treg.discovery_calls == [run_request]
    assert result.discovery_used is True
    assert result.discovery_query == "work email"
    assert result.discovery_evidence.capability_anchor == "people.email.find"
    assert result.discovered_candidates == ["first", "second"]
    assert backend.calls[0][0] is treg.candidates[0]


@pytest.mark.parametrize("choice,confidence", [("escalate", 0.94), ("first", 0.1)])
async def test_routing_gate_never_executes(database, choice, confidence):
    subject, backend, jev = controller(database, {}, jev=RecordingJev(choice, confidence))
    result = await subject.run(request())
    assert result.status == "escalate"
    assert result.selected_tool is None
    assert result.attempts == []
    assert not backend.calls
    assert not jev.verifications


async def test_legacy_duplicate_ranking_is_preserved(database):
    subject, backend, _ = controller(
        database,
        {
            "first": "TREG_ERROR: unavailable",
            "second": "TREG_ERROR: unavailable",
        },
        jev=RecordingJev(choice="second"),
    )
    result = await subject.run(request(max_attempts=3))
    assert [candidate.id for candidate, _ in backend.calls] == ["second", "first", "second"]
    assert result.status == "escalate"


async def test_legacy_unknown_dry_run_choice_is_preserved(database):
    subject, backend, _ = controller(database, {}, jev=RecordingJev(choice="unknown"))
    with pytest.raises(KeyError, match="unknown"):
        await subject.run(request(dry_run=True))
    assert not backend.calls


async def test_persistence_preserves_complete_request_and_response(database):
    subject, _, _ = controller(database, {"first": VERIFIED_OUTPUT})
    run_request = request()
    result = await subject.run(run_request)
    async with database.session() as session:
        record = (await session.exec(select(RunRecord))).one()
    assert record.id == result.run_id
    assert record.objective == run_request.objective
    assert record.status == result.status
    assert record.selected_tool == result.selected_tool
    assert record.route_confidence == result.route_confidence
    assert json.loads(record.payload_json) == run_request.model_dump(mode="json")
    assert json.loads(record.result_json) == result.model_dump(mode="json")
