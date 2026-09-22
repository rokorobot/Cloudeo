from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Literal

from cloudeo.models import RunRequest, ToolCandidate


@dataclass(frozen=True)
class ValidationOutcome:
    status: Literal["pass", "fail", "inconclusive"]
    evidence: tuple[str, ...] = ()


def validate_tool_output(
    request: RunRequest,
    candidate: ToolCandidate,
    output: str,
) -> ValidationOutcome:
    if output.startswith("TREG_ERROR:"):
        return ValidationOutcome(
            "fail",
            ("Treg/provider execution failed.",),
        )

    task_text = f"{request.objective}\n{request.success_criteria}".lower()

    # v0.1.1 first deterministic vertical: verified work-email lookup.
    if "email" not in task_text:
        return ValidationOutcome("inconclusive")

    try:
        payload = json.loads(output)
    except (TypeError, json.JSONDecodeError):
        return ValidationOutcome(
            "inconclusive",
            ("Tool output is not structured JSON.",),
        )

    if not isinstance(payload, dict):
        return ValidationOutcome("inconclusive")

    # Preserve the existing mock-control-loop behavior.
    if payload.get("backend") == "mock":
        return ValidationOutcome(
            "inconclusive",
            ("Mock backend output requires mock/Jev verification.",),
        )

    nested = payload.get("data")
    data: dict[str, Any] = nested if isinstance(nested, dict) else payload

    email = _first_email(data)
    if not email:
        return ValidationOutcome(
            "fail",
            ("No email address was returned.",),
        )

    evidence: list[str] = [f"Email returned: {email}"]

    expected_domain = _expected_domain(request, candidate)
    if expected_domain:
        actual_domain = email.rsplit("@", 1)[-1].lower()

        if actual_domain != expected_domain:
            return ValidationOutcome(
                "fail",
                (
                    f"Email domain mismatch: expected {expected_domain}, "
                    f"got {actual_domain}.",
                ),
            )

        evidence.append(
            f"Email domain matches expected domain {expected_domain}."
        )

    expected_person = _expected_person(request, candidate)
    returned_person = _first_string(
        data,
        "fullName",
        "full_name",
        "name",
    )

    identity_supported = False

    valid_identity = data.get("validIdentity")

    if valid_identity is False:
        return ValidationOutcome(
            "fail",
            ("Provider explicitly reported validIdentity=false.",),
        )

    if valid_identity is True:
        identity_supported = True
        evidence.append("Provider reported validIdentity=true.")

    if expected_person and returned_person:
        if _normalize_name(returned_person) != _normalize_name(expected_person):
            return ValidationOutcome(
                "fail",
                (
                    f"Person mismatch: expected {expected_person!r}, "
                    f"got {returned_person!r}.",
                ),
            )

        identity_supported = True
        evidence.append(
            f"Returned person matches {expected_person}."
        )

    verification_supported = False

    valid_smtp = data.get("validSMTP")

    if valid_smtp is False:
        return ValidationOutcome(
            "fail",
            ("Provider explicitly reported validSMTP=false.",),
        )

    if valid_smtp is True:
        verification_supported = True
        evidence.append("Provider reported validSMTP=true.")

    validity = _first_string(data, "validity", "status")

    if validity:
        normalized = validity.strip().lower()

        if normalized in {"invalid", "failed", "undeliverable"}:
            return ValidationOutcome(
                "fail",
                (
                    f"Provider reported email status={normalized!r}.",
                ),
            )

        if normalized in {"valid", "verified", "deliverable"}:
            verification_supported = True
            evidence.append(
                f"Provider reported {normalized} email status."
            )

    verification = data.get("verification")

    if isinstance(verification, dict):
        status = verification.get("status")

        if isinstance(status, str):
            normalized = status.strip().lower()

            if normalized in {"invalid", "failed", "undeliverable"}:
                return ValidationOutcome(
                    "fail",
                    (
                        f"Provider verification status={normalized!r}.",
                    ),
                )

            if normalized in {"valid", "verified", "deliverable"}:
                verification_supported = True
                evidence.append(
                    f"Provider verification.status={normalized}."
                )

    if expected_person and not identity_supported:
        evidence.append(
            "Identity requires semantic verification."
        )

    if not verification_supported:
        evidence.append(
            "Email validity requires semantic verification."
        )

    if (
        (not expected_person or identity_supported)
        and verification_supported
    ):
        return ValidationOutcome(
            "pass",
            tuple(evidence),
        )

    return ValidationOutcome(
        "inconclusive",
        tuple(evidence),
    )


def _expected_domain(
    request: RunRequest,
    candidate: ToolCandidate,
) -> str | None:
    values = (
        request.state.get("company_domain"),
        request.state.get("domain"),
        candidate.body.get("domain"),
        candidate.query.get("domain"),
    )

    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip().lower().removeprefix("www.")

    return None


def _expected_person(
    request: RunRequest,
    candidate: ToolCandidate,
) -> str | None:
    values = (
        request.state.get("person"),
        candidate.body.get("fullName"),
        candidate.query.get("full_name"),
    )

    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()

    return None


def _first_email(data: dict[str, Any]) -> str | None:
    for key in (
        "email",
        "work_email",
        "workEmail",
        "displayText",
    ):
        value = data.get(key)

        if (
            isinstance(value, str)
            and re.fullmatch(
                r"[^\s@]+@[^\s@]+\.[^\s@]+",
                value.strip(),
            )
        ):
            return value.strip()

    return None


def _first_string(
    data: dict[str, Any],
    *keys: str,
) -> str | None:
    for key in keys:
        value = data.get(key)

        if isinstance(value, str) and value.strip():
            return value.strip()

    return None


def _normalize_name(value: str) -> str:
    return " ".join(
        re.findall(r"[a-z0-9]+", value.lower())
    )
