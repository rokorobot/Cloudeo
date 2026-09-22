from cloudeo.adapters.treg import (
    _clean_query,
    _new_ledger_entries,
    _parse_treg_stderr,
    discovery_queries,
)
from cloudeo.models import RunRequest


def _request():
    return RunRequest(
        objective=(
            "Find the verified professional email for "
            "Erol Toker at trykitt.ai"
        ),
        state={
            "person": "Erol Toker",
            "company_domain": "trykitt.ai",
        },
    )


def test_discovery_query_is_clean_capability_language():
    queries = discovery_queries(_request())
    assert queries[0] == "verified work email"
    assert all("Erol" not in q for q in queries)
    assert all("trykitt.ai" not in q for q in queries)


def test_clean_query_removes_dangling_imperative_and_preposition():
    assert _clean_query("Find the verified work email for") == (
        "the verified work email"
    )


def test_parse_treg_charge_and_call_id():
    parsed = _parse_treg_stderr(
        "treg: charged $0.0005 · call id abc_123"
    )
    assert parsed["settled_cost_usd"] == 0.0005
    assert parsed["call_id"] == "abc_123"
    assert parsed["idempotent_replay"] is False


def test_parse_idempotent_replay():
    parsed = _parse_treg_stderr(
        "treg: charged $0.005 by the original call "
        "(this is a replay — nothing new charged) · call id xyz"
    )
    assert parsed["idempotent_replay"] is True


def test_new_ledger_entries_detect_reserve_and_settle():
    before = {
        "entries": {
            "items": [
                {
                    "kind": "grant",
                    "amount_micro": 1000000,
                    "created_at": "2026-09-21T21:22:30",
                }
            ]
        }
    }
    after = {
        "entries": {
            "items": [
                {
                    "kind": "settle",
                    "amount_micro": -500,
                    "endpoint_id": "trykitt.people.email.find",
                    "created_at": "2026-09-22T00:00:38",
                },
                {
                    "kind": "reserve",
                    "amount_micro": -5000,
                    "endpoint_id": "trykitt.people.email.find",
                    "created_at": "2026-09-22T00:00:38",
                },
                {
                    "kind": "grant",
                    "amount_micro": 1000000,
                    "created_at": "2026-09-21T21:22:30",
                },
            ]
        }
    }

    new = _new_ledger_entries(before, after)
    assert len(new) == 2
    assert {row["kind"] for row in new} == {"reserve", "settle"}
