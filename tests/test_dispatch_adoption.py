"""Controller.run() executes Treg through DirectToolExecution and the dispatcher.

Behavior equivalence with the pre-migration controller is proven by
test_controller_characterization.py; these tests prove the new path is the one
actually taken, that it is Treg-only, and that it adds no interpretation rule.
"""

import httpx
import pytest
from test_controller_characterization import (
    VERIFIED_OUTPUT,
    ScriptedJev,
    ScriptedTreg,
    run_request,
)

from cloudeo.adapters.treg import TregError
from cloudeo.config import Settings
from cloudeo.core.controller import Controller
from cloudeo.db.session import Database
from cloudeo.execution.base import ExecutionResult
from cloudeo.execution.contracts import (
    DirectToolExecution,
    ExecutionCost,
    ExecutionOutcome,
    HarnessTaskExecution,
    RuntimeIdentity,
)
from cloudeo.execution.dispatch import (
    ExecutionBackendUnavailable,
    ExecutionDispatcher,
)
from cloudeo.execution.treg_backend import (
    LegacyDirectToolBackend,
    TregDirectToolBackend,
)
from cloudeo.uhp import client as uhp_client
from cloudeo.uhp.models import UHPTaskRequest


@pytest.fixture
async def database():
    settings = Settings(_env_file=None, database_url="sqlite+aiosqlite:///:memory:")
    database = Database(settings)
    await database.init()
    try:
        yield database
    finally:
        await database.engine.dispose()


def settings():
    return Settings(_env_file=None)


class RecordingDirectTool:
    """Wraps a real direct-tool backend and records every request it receives."""

    def __init__(self, inner):
        self.inner = inner
        self.requests = []

    async def execute(self, request):
        self.requests.append(request)
        return await self.inner.execute(request)


class FixedOutcome:
    """Direct-tool backend returning a preset outcome regardless of input."""

    def __init__(self, status, output_text, economics=None):
        self.outcome = ExecutionOutcome(
            kind="direct_tool",
            status=status,
            output_text=output_text,
            raw_output=output_text,
            cost=ExecutionCost(direct_tool_economics=economics),
            runtime=RuntimeIdentity(backend="treg"),
        )

    async def execute(self, request):
        return self.outcome


def with_dispatcher(database, direct_tool, *, jev=None):
    dispatcher = ExecutionDispatcher(direct_tool=direct_tool)
    subject = Controller(
        settings(),
        jev or ScriptedJev(),
        ScriptedTreg({}),
        database,
        execution_dispatcher=dispatcher,
    )
    return subject


async def test_default_controller_dispatches_treg_only(database):
    treg = ScriptedTreg({"first": VERIFIED_OUTPUT})
    subject = Controller(settings(), ScriptedJev(), treg, database)
    dispatcher = subject.execution_dispatcher
    assert isinstance(dispatcher, ExecutionDispatcher)
    assert isinstance(dispatcher.direct_tool, TregDirectToolBackend)
    assert dispatcher.harness_task is None
    assert (await subject.run(run_request())).status == "passed"
    assert treg.calls == [["first", False]]


async def test_default_dispatcher_refuses_harness_tasks(database):
    subject = Controller(settings(), ScriptedJev(), ScriptedTreg({}), database)
    task = UHPTaskRequest(input="x", harness_id="chrn_test")
    with pytest.raises(ExecutionBackendUnavailable):
        await subject.execution_dispatcher.execute(HarnessTaskExecution(task=task))


async def test_legacy_execution_backend_argument_is_adopted_not_bypassed(database):
    class LegacyBackend:
        def __init__(self):
            self.calls = []

        async def execute(self, candidate, *, dry_run=False):
            self.calls.append((candidate.id, dry_run))
            return ExecutionResult(output=VERIFIED_OUTPUT, economics={"call_id": "legacy"})

    legacy = LegacyBackend()
    subject = Controller(
        settings(), ScriptedJev(), ScriptedTreg({}), database, execution_backend=legacy
    )
    assert isinstance(subject.execution_dispatcher.direct_tool, LegacyDirectToolBackend)
    result = await subject.run(run_request())
    assert legacy.calls == [("first", False)]
    assert result.attempts[0].economics.call_id == "legacy"


def test_backend_and_dispatcher_arguments_are_exclusive():
    with pytest.raises(ValueError, match="not both"):
        Controller(
            settings(),
            ScriptedJev(),
            ScriptedTreg({}),
            database=None,
            execution_backend=object(),
            execution_dispatcher=ExecutionDispatcher(),
        )


@pytest.mark.parametrize(
    "dry_run,script,expected",
    [
        (
            False,
            {"first": TregError("down"), "second": VERIFIED_OUTPUT},
            [
                ("first", False),
                ("second", False),
            ],
        ),
        (True, {"first": "DRY RUN: treg call first.email"}, [("first", True)]),
    ],
)
async def test_controller_sends_direct_tool_requests_in_legacy_order(
    database, dry_run, script, expected
):
    request = run_request(dry_run=dry_run)
    recorder = RecordingDirectTool(TregDirectToolBackend(ScriptedTreg(script)))
    await with_dispatcher(database, recorder).run(request)
    assert all(type(r) is DirectToolExecution for r in recorder.requests)
    assert [(r.candidate.id, r.dry_run) for r in recorder.requests] == expected
    # The candidate objects are passed through, not copied.
    by_id = {c.id: c for c in request.candidates}
    assert all(r.candidate is by_id[r.candidate.id] for r in recorder.requests)


async def test_dry_run_preparation_error_propagates_through_dispatcher(database):
    error = TregError("cannot prepare command")
    treg = ScriptedTreg({"first": error})
    recorder = RecordingDirectTool(TregDirectToolBackend(treg))
    with pytest.raises(TregError) as caught:
        await with_dispatcher(database, recorder).run(run_request(dry_run=True))
    assert caught.value is error


@pytest.mark.parametrize(
    "status,output_text,expected_run_status,expected_deterministic",
    [
        # A "failed" runtime status does not fail a result the validator passes.
        ("failed", VERIFIED_OUTPUT, "passed", "pass"),
        # A "completed" runtime status does not pass TREG_ERROR text.
        ("completed", "TREG_ERROR: provider unavailable", "escalate", "fail"),
    ],
)
async def test_outcome_status_is_not_a_second_interpretation_rule(
    database, status, output_text, expected_run_status, expected_deterministic
):
    subject = with_dispatcher(database, FixedOutcome(status, output_text))
    result = await subject.run(run_request(max_attempts=1))
    assert result.status == expected_run_status
    assert result.attempts[0].deterministic_status == expected_deterministic
    assert result.attempts[0].output == output_text


async def test_direct_outcome_without_output_text_is_rejected(database):
    subject = with_dispatcher(database, FixedOutcome("unknown", None))
    with pytest.raises(TypeError, match="output_text"):
        await subject.run(run_request())


async def test_treg_path_makes_no_network_or_uhp_calls(database, monkeypatch):
    def no_network(*args, **kwargs):
        raise AssertionError("Controller.run() must not use the network")

    def no_uhp(*args, **kwargs):
        raise AssertionError("Controller.run() must not construct a UHP client")

    monkeypatch.setattr(httpx.AsyncClient, "send", no_network)
    monkeypatch.setattr(uhp_client.UHPClient, "__init__", no_uhp)
    treg = ScriptedTreg({"first": TregError("down"), "second": VERIFIED_OUTPUT})
    subject = Controller(settings(), ScriptedJev(), treg, database)
    result = await subject.run(run_request())
    assert result.status == "passed"
    assert treg.calls == [["first", False], ["second", False]]
