from cloudeo.adapters.treg import candidate_from_catalog_detail
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
        success_criteria=(
            "Return a verified professional email matching "
            "the named person and company domain."
        ),
    )


def test_candidates_are_optional_for_discovery():
    request = _request()
    assert request.candidates == []


def test_trykitt_schema_auto_binds():
    detail = {
        "endpoint": {
            "id": "trykitt.people.email.find",
            "provider": "trykitt",
            "method": "POST",
            "summary": "Find a verified B2B email",
            "cost": {
                "type": "per_success",
                "value": 0.005,
                "currency": "USD",
            },
            "observed": {
                "ok_rate": 1.0,
                "hit_rate": 0.38,
                "p50_ms": 3800,
            },
            "input": {
                "body": {
                    "fullName": {
                        "type": "string",
                        "required": True,
                    },
                    "domain": {
                        "type": "string",
                        "required": True,
                    },
                    "realtime": {
                        "type": "boolean",
                        "required": True,
                        "enum": [True],
                    },
                },
                "bodyType": "json",
            },
        },
        "provider": {
            "display_name": "Kitt AI",
        },
    }

    candidate = candidate_from_catalog_detail(
        _request(),
        detail,
    )

    assert candidate is not None
    assert candidate.method == "POST"
    assert candidate.body == {
        "fullName": "Erol Toker",
        "domain": "trykitt.ai",
        "realtime": True,
    }
    assert candidate.query == {}


def test_tomba_schema_auto_binds():
    detail = {
        "endpoint": {
            "id": "tomba.people.email.find",
            "provider": "tomba",
            "method": "GET",
            "summary": "Find work email",
            "input": {
                "queryParams": {
                    "domain": {
                        "type": "string",
                        "required": True,
                    },
                    "full_name": {
                        "type": "string",
                        "required": False,
                    },
                }
            },
        },
        "provider": {
            "display_name": "Tomba",
        },
    }

    candidate = candidate_from_catalog_detail(
        _request(),
        detail,
    )

    assert candidate is not None
    assert candidate.method == "GET"
    assert candidate.query == {
        "domain": "trykitt.ai",
        "full_name": "Erol Toker",
    }
    assert candidate.body == {}


def test_missing_required_input_discards_provider():
    detail = {
        "endpoint": {
            "id": "example.people.email.find",
            "provider": "example",
            "method": "GET",
            "input": {
                "queryParams": {
                    "linkedin_url": {
                        "type": "string",
                        "required": True,
                    }
                }
            },
        },
        "provider": {
            "display_name": "Example",
        },
    }

    candidate = candidate_from_catalog_detail(
        _request(),
        detail,
    )

    assert candidate is None
