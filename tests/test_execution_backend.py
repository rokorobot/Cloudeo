import pytest

from cloudeo.adapters.treg import TregClient, TregError
from cloudeo.execution.treg_backend import TregExecutionBackend
from cloudeo.models import ToolCandidate


class FakeTreg(TregClient):
    def __init__(self):
        self.calls = []
        self.output = "  provider output\nunchanged  "
        self.last_execution_economics = {"call_id": "previous", "settled_cost_usd": 0.005}
        self.error = None

    async def execute(self, candidate, dry_run=False):
        self.calls.append((candidate, dry_run))
        if self.error is not None:
            raise self.error
        return self.output


def candidate():
    return ToolCandidate(id="one", description="First provider", treg_tool_id="one.lookup")


@pytest.mark.parametrize("dry_run", [False, True])
async def test_execution_forwards_candidate_and_preserves_result(dry_run):
    client = FakeTreg()
    selected = candidate()
    result = await TregExecutionBackend(client).execute(selected, dry_run=dry_run)
    assert client.calls == [(selected, dry_run)]
    assert client.calls[0][0] is selected
    assert result.output == client.output
    assert result.economics == client.last_execution_economics


async def test_normal_failure_preserves_error_text_and_legacy_economics():
    client = FakeTreg()
    backend = TregExecutionBackend(client)
    previous = await backend.execute(candidate())
    client.error = TregError("provider unavailable")
    result = await backend.execute(candidate())
    assert result.output == "TREG_ERROR: provider unavailable"
    assert result.economics == previous.economics
    assert result.economics["call_id"] == "previous"


async def test_dry_run_failure_propagates_original_error():
    client = FakeTreg()
    client.error = TregError("cannot prepare command")
    with pytest.raises(TregError) as caught:
        await TregExecutionBackend(client).execute(candidate(), dry_run=True)
    assert caught.value is client.error
    assert client.calls[0][1] is True


async def test_unexpected_exception_is_not_normalized():
    client = FakeTreg()
    client.error = ValueError("unexpected")
    with pytest.raises(ValueError, match="unexpected"):
        await TregExecutionBackend(client).execute(candidate())
