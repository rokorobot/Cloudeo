"""Normalize a LongHorizon auditor EpisodeResult into one Cloudeo verification result.

LongHorizon owns the report contract: control-header validation, parsing, the
acceptance-constraint guard, and the integrity/contract interpretation are
delegated to its public functions. Cloudeo owns only what LongHorizon leaves
ambiguous for a verification decision:

- Report source. The text is taken only from LongHorizon's visible-output
  metadata keys (VISIBLE_OUTPUT_KEYS). actions_log is never a report source:
  for Cloudeo's UHP adapters it holds raw output items, and in the pinned
  manager's format-repair path it holds repaired text while the primary
  episode's assistant_visible_output still wins (ADR-019). Different non-empty
  texts under several visible keys are ambiguous and fail closed.
- Format repair. A repaired report is used only when the caller passes the
  repair episode explicitly, the primary report was malformed, and the repair
  episode itself is acceptable; it is then parsed as the sole report text.
  Repair recovers syntax only and is never verification authority: a repaired
  report is capped at NOT_VERIFIED, however positive its conclusion. No
  structured evidence exists that could verify without the report text (the
  read-only guard proves only that the auditor did not write), so there is no
  path from a repaired report to VERIFIED.
- Fail-closed precedence. Mutation evidence, audit-boundary problems, runtime
  failures, and unusable reports are all decided before report content, and
  none can yield VERIFIED.

The mutation evidence keeps LongHorizon's own names:
verifier_workspace_mutation_detected and verifier_workspace_mutations.
"""

from __future__ import annotations

import copy
from typing import Any, Literal

try:
    from lh_harness.auditor_agent import (
        VISIBLE_OUTPUT_KEYS,
        audit_report_from_episode_result,
        has_valid_auditor_control_header,
    )
    from lh_harness.provider_errors import classify_agent_runtime_failure
    from lh_harness.types import EpisodeResult
except ModuleNotFoundError as exc:  # pragma: no cover - depends on the install
    raise ImportError(
        "cloudeo.longhorizon requires the optional 'longhorizon' extra "
        "(LongHorizon-Harness pinned at v0.1.7)."
    ) from exc

from pydantic import BaseModel, ConfigDict

from cloudeo.longhorizon.workspace_auditor import (
    AUDITOR_WORKSPACE_MUTATION_DETECTED,
)

AuditorVerificationStatus = Literal["VERIFIED", "NOT_VERIFIED", "BLOCKED", "AUDITOR_ERROR"]
FormatRepair = Literal["not_needed", "not_provided", "accepted", "rejected"]

# Cloudeo audit-boundary codes (workspace_auditor.py) that are infrastructure
# failures rather than evidence about the audited state.
_TRANSPORT_ERRORS = frozenset({"workspace_upload_failed"})


class AuditorFailure(BaseModel):
    model_config = ConfigDict(frozen=True)

    # LongHorizon's classifier kind (provider_error, timeout, authentication,
    # ...), "cancelled", or a Cloudeo audit-boundary code.
    kind: str
    source: Literal["longhorizon_classifier", "episode_status", "cloudeo_audit_boundary"]
    abort_reason: str | None = None
    message: str = ""


class AuditorVerification(BaseModel):
    """One stable verification result for one auditor episode (and optional repair).

    VERIFIED only means the report, read from an unambiguous trusted source of
    a read-only audit, parses as complete / clean / aligned. It is not a
    checkpoint or promotion decision.
    """

    model_config = ConfigDict(frozen=True)

    status: AuditorVerificationStatus
    # Machine-readable reason for status.
    reason: str
    report_text: str = ""
    # e.g. "metadata.assistant_visible_output" or
    # "repair.metadata.assistant_visible_output"; None when no report was used.
    report_source: str | None = None
    report_status: str | None = None
    integrity_status: str | None = None
    contract_audit_status: str | None = None
    format_repair: FormatRepair = "not_needed"
    episode_status: str
    verifier_workspace_mutation_detected: bool | None = None
    verifier_workspace_mutations: dict[str, list[str]] | None = None
    audit_invalid_reasons: tuple[str, ...] = ()
    failure: AuditorFailure | None = None
    # Evidence for debugging and audit trails, copied unmodified.
    upstream_error: str | None = None
    upstream_metadata: dict[str, Any]
    repair_metadata: dict[str, Any] | None = None

    @property
    def verified(self) -> bool:
        return self.status == "VERIFIED"


def normalize_auditor_result(
    primary: EpisodeResult,
    *,
    repair: EpisodeResult | None = None,
    round_index: int = 1,
    language: str = "en",
) -> AuditorVerification:
    metadata = primary.metadata if isinstance(primary.metadata, dict) else {}
    mutation_detected = metadata.get("verifier_workspace_mutation_detected")
    mutations = metadata.get("verifier_workspace_mutations")
    invalid = tuple(str(code) for code in metadata.get("audit_invalid_reasons") or ())
    base: dict[str, Any] = {
        "episode_status": primary.status,
        "verifier_workspace_mutation_detected": (
            mutation_detected if isinstance(mutation_detected, bool) else None
        ),
        "verifier_workspace_mutations": _mutation_lists(mutations),
        "audit_invalid_reasons": invalid,
        "upstream_error": primary.error,
        "upstream_metadata": copy.deepcopy(metadata),
        "repair_metadata": copy.deepcopy(repair.metadata) if repair is not None else None,
    }

    # 1. A workspace mutation blocks, whatever the runtime or report says.
    if mutation_detected is True or AUDITOR_WORKSPACE_MUTATION_DETECTED in invalid:
        return AuditorVerification(status="BLOCKED", reason="workspace_mutation_detected", **base)
    # 2. Cloudeo audit-boundary problems (stale, drift, missing evidence, ...).
    if invalid:
        code = invalid[0]
        failure = AuditorFailure(
            kind=code, source="cloudeo_audit_boundary", message=primary.error or ""
        )
        if code in _TRANSPORT_ERRORS:
            return AuditorVerification(
                status="AUDITOR_ERROR", reason="auditor_transport_failure", failure=failure, **base
            )
        return AuditorVerification(
            status="BLOCKED", reason="audit_boundary_invalid", failure=failure, **base
        )
    # 3. Runtime or provider failure of the auditor itself.
    failure = _runtime_failure(primary)
    if failure is not None:
        return AuditorVerification(
            status="AUDITOR_ERROR", reason="auditor_runtime_failure", failure=failure, **base
        )
    # 4. Without evidence that the audit was read-only, nothing can be verified.
    if mutation_detected is not False or metadata.get("verifier_workspace_guard") is not True:
        return AuditorVerification(status="BLOCKED", reason="read_only_evidence_missing", **base)

    # 5. The report itself.
    selected = _select_report(metadata)
    if isinstance(selected, str):
        return AuditorVerification(status="BLOCKED", reason=selected, **base)
    source, text = selected
    format_repair: FormatRepair = "not_needed"
    if not has_valid_auditor_control_header(text):
        if repair is None:
            return AuditorVerification(
                status="BLOCKED",
                reason="report_malformed",
                report_text=text,
                report_source=source,
                format_repair="not_provided",
                **base,
            )
        repaired = _acceptable_repair(repair)
        if repaired is None:
            return AuditorVerification(
                status="BLOCKED",
                reason="report_malformed",
                report_text=text,
                report_source=source,
                format_repair="rejected",
                **base,
            )
        source, text = f"repair.{repaired[0]}", repaired[1]
        format_repair = "accepted"

    report = audit_report_from_episode_result(
        _parse_input(primary, text), round_index, language=language
    )
    positive = (report.status, report.integrity_status, report.contract_audit_status) == (
        "complete",
        "clean",
        "aligned",
    )
    if not positive:
        reason = "report_not_complete"
    elif format_repair == "accepted":
        # The positive conclusion exists only in text a repair model rewrote.
        reason = "report_repaired_not_verification_authority"
    else:
        reason = "report_complete"
    return AuditorVerification(
        status="VERIFIED" if reason == "report_complete" else "NOT_VERIFIED",
        reason=reason,
        report_text=report.report_text,
        report_source=source,
        report_status=report.status,
        integrity_status=report.integrity_status,
        contract_audit_status=report.contract_audit_status,
        format_repair=format_repair,
        **base,
    )


def _select_report(metadata: dict[str, Any]) -> tuple[str, str] | str:
    """(source, text) from LongHorizon's visible-output keys, or a blocking reason.

    Follows LongHorizon's key precedence, but only among visible-output keys:
    actions_log is never read, and conflicting keys are ambiguous.
    """
    present = [
        (key, value.strip())
        for key in VISIBLE_OUTPUT_KEYS
        if isinstance(value := metadata.get(key), str) and value.strip()
    ]
    if not present:
        return "report_missing"
    if len({text for _, text in present}) > 1:
        return "report_source_ambiguous"
    key, text = present[0]
    return f"metadata.{key}", text


def _acceptable_repair(repair: EpisodeResult) -> tuple[str, str] | None:
    """The repaired report, only if the repair episode is itself trustworthy."""
    metadata = repair.metadata if isinstance(repair.metadata, dict) else {}
    if repair.status != "done" or _runtime_failure(repair) is not None:
        return None
    if metadata.get("verifier_workspace_mutation_detected") or metadata.get(
        "audit_invalid_reasons"
    ):
        return None
    selected = _select_report(metadata)
    if isinstance(selected, str) or not has_valid_auditor_control_header(selected[1]):
        return None
    return selected


def _parse_input(primary: EpisodeResult, text: str) -> EpisodeResult:
    """The selected text as the only report LongHorizon can see.

    The primary's guard metadata is kept; every other visible-output key and
    actions_log are removed, so LongHorizon's own precedence cannot pick a
    different text.
    """
    metadata = {k: v for k, v in primary.metadata.items() if k not in VISIBLE_OUTPUT_KEYS}
    metadata["assistant_visible_output"] = text
    metadata["actions_log_diagnostics_only"] = True
    return EpisodeResult(
        status=primary.status,
        actions_log="",
        error=primary.error,
        duration_ms=primary.duration_ms,
        metadata=metadata,
    )


def _runtime_failure(result: EpisodeResult) -> AuditorFailure | None:
    if result.status == "cancelled":
        return AuditorFailure(kind="cancelled", source="episode_status", message=result.error or "")
    failure = classify_agent_runtime_failure(result)
    if failure is not None:
        return AuditorFailure(
            kind=failure.kind,
            source="longhorizon_classifier",
            abort_reason=failure.abort_reason,
            message=failure.message,
        )
    if result.status != "done":  # pragma: no cover - the classifier covers error/timeout
        return AuditorFailure(
            kind=result.status, source="episode_status", message=result.error or ""
        )
    return None


def _mutation_lists(raw: object) -> dict[str, list[str]] | None:
    """LongHorizon's verifier_workspace_mutations shape, copied; None if absent."""
    if not isinstance(raw, dict):
        return None
    return {str(k): [str(p) for p in v] for k, v in raw.items() if isinstance(v, list)}
