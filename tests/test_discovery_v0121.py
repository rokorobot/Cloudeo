from cloudeo.adapters.treg import candidate_endpoint_ids, discovery_queries
from cloudeo.models import RunRequest


def _request():
    return RunRequest(
        objective="Find the verified professional email for Erol Toker at trykitt.ai",
        state={"person": "Erol Toker", "company_domain": "trykitt.ai"},
    )


def test_discovery_query_removes_runtime_entities():
    queries = discovery_queries(_request())
    joined = " | ".join(queries).lower()
    assert "erol" not in joined
    assert "toker" not in joined
    assert "trykitt.ai" not in joined
    assert any("work email" in q.lower() for q in queries)


def test_routed_capability_anchors_provider_children():
    rows = [
        {
            "id": "contactout.people.work_email.available",
            "kind": "data",
            "capability": "people.email.work.availability",
            "score": 18.901,
        },
        {
            "id": "treg.people.email.find",
            "kind": "routed",
            "capability": "people.email.find",
            "score": 18.901,
            "routed_children": [
                "aiark.people.email.find",
                "trykitt.people.email.find",
                "tomba.people.email.find",
            ],
        },
        {
            "id": "trykitt.people.email.find",
            "kind": "data",
            "capability": "people.email.find",
            "score": 18.901,
        },
        {
            "id": "tomba.people.email.find",
            "kind": "data",
            "capability": "people.email.find",
            "score": 18.901,
        },
    ]
    ids = candidate_endpoint_ids(rows, 12)
    assert ids[:2] == [
        "trykitt.people.email.find",
        "tomba.people.email.find",
    ]
    assert "contactout.people.work_email.available" not in ids
