import json

from cloudeo.core.validators import validate_tool_output
from cloudeo.models import RunRequest, ToolCandidate


def request_and_candidate():
    candidate = ToolCandidate(
        id="trykitt",
        description="Verified work email finder",
        treg_tool_id="trykitt.people.email.find",
        method="POST",
        body={
            "fullName": "Erol Toker",
            "domain": "trykitt.ai",
            "realtime": True,
        },
    )

    request = RunRequest(
        objective=(
            "Find the verified professional email "
            "for Erol Toker at trykitt.ai."
        ),
        state={
            "person": "Erol Toker",
            "company_domain": "trykitt.ai",
        },
        success_criteria=(
            "Return a verified professional email "
            "matching the named person and company domain."
        ),
        candidates=[candidate],
    )

    return request, candidate


def test_trykitt_verified_email_passes():
    request, candidate = request_and_candidate()

    output = json.dumps(
        {
            "fullName": "Erol Toker",
            "domain": "trykitt.ai",
            "email": "erol@trykitt.ai",
            "validIdentity": True,
            "validSMTP": True,
            "validity": "valid",
        }
    )

    result = validate_tool_output(
        request,
        candidate,
        output,
    )

    assert result.status == "pass"


def test_provider_error_fails():
    request, candidate = request_and_candidate()

    result = validate_tool_output(
        request,
        candidate,
        "TREG_ERROR: provider unavailable",
    )

    assert result.status == "fail"


def test_wrong_domain_fails():
    request, candidate = request_and_candidate()

    output = json.dumps(
        {
            "fullName": "Erol Toker",
            "email": "erol@example.com",
            "validIdentity": True,
            "validSMTP": True,
            "validity": "valid",
        }
    )

    result = validate_tool_output(
        request,
        candidate,
        output,
    )

    assert result.status == "fail"
