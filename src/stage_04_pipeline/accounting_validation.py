"""Deterministic validation and repair payloads for accounting findings.

This module never calls an LLM and never mutates valuation inputs. It validates
the small accounting responses returned by focused judgment calls and gives a
repair caller the exact evidence and contract failure that must be fixed.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Callable

from pydantic import ValidationError

from src.contracts.accounting_evidence import (
    AccountingFocusResponse,
    AccountingFinding,
)


_FINDING_STATUSES = {"candidate", "no_adjustment_identified", "missing_evidence"}
_VALUATION_TREATMENTS = {
    "normalized_ebit",
    "ev_equity_bridge",
    "scenario_only",
    "disclosure_only",
    "none",
}
_NON_MUTATING_TREATMENTS = {"scenario_only", "disclosure_only", "none"}


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    message: str
    field: str | None = None


@dataclass(frozen=True)
class ValidationResult:
    valid: bool
    issues: list[ValidationIssue] = field(default_factory=list)


@dataclass(frozen=True)
class RepairCycleResult:
    status: str
    finding: dict[str, Any] | None
    attempts: list[dict[str, Any]]
    final_issues: list[ValidationIssue]


@dataclass(frozen=True)
class FocusFindingRepairResult:
    """Audit result for one finding in a multi-finding focus response."""

    finding_id: str
    status: str
    finding: dict[str, Any]
    attempts: list[dict[str, Any]]
    final_issues: list[ValidationIssue] = field(default_factory=list)


@dataclass(frozen=True)
class FocusRepairResult:
    """Inspectable result of validating and repairing one focus envelope.

    ``response`` contains accepted siblings only.  A rejected item is retained
    in ``finding_results`` with its original payload, both attempts, and final
    issues, so callers can persist the rejection without dropping provenance.
    """

    status: str
    response: dict[str, Any] | None
    envelope_attempts: list[dict[str, Any]]
    finding_results: list[FocusFindingRepairResult]
    final_issues: list[ValidationIssue] = field(default_factory=list)


def _packet_evidence(packet: dict[str, Any]) -> dict[str, dict[str, Any]]:
    evidence: dict[str, dict[str, Any]] = {}
    for collection_name in ("facts", "snippets", "source_refs"):
        for item in packet.get(collection_name) or []:
            if not isinstance(item, dict):
                continue
            key_name = {
                "facts": "fact_id",
                "snippets": "snippet_id",
                "source_refs": "source_ref_id",
            }[collection_name]
            key = str(item.get(key_name) or "").strip()
            if key:
                evidence[key] = {"kind": collection_name[:-1], **item}
    return evidence


def validate_accounting_finding(
    finding: dict[str, Any],
    packet: dict[str, Any],
) -> ValidationResult:
    """Validate one focused finding against its supplied packet and driver map."""

    issues: list[ValidationIssue] = []
    status = str(finding.get("finding_status") or "").strip()
    if status not in _FINDING_STATUSES:
        issues.append(
            ValidationIssue(
                "invalid_finding_status",
                f"finding_status must be one of {sorted(_FINDING_STATUSES)}",
                "finding_status",
            )
        )

    treatment = str(finding.get("valuation_treatment") or "").strip()
    if treatment not in _VALUATION_TREATMENTS:
        issues.append(
            ValidationIssue(
                "invalid_valuation_treatment",
                f"valuation_treatment must be one of {sorted(_VALUATION_TREATMENTS)}",
                "valuation_treatment",
            )
        )

    evidence = _packet_evidence(packet)
    anchor_ids = [str(value).strip() for value in finding.get("evidence_anchor_ids") or []]
    missing_anchors = [anchor for anchor in anchor_ids if anchor not in evidence]
    if status == "candidate" and not anchor_ids:
        issues.append(
            ValidationIssue(
                "candidate_missing_evidence",
                "candidate findings require at least one evidence anchor",
                "evidence_anchor_ids",
            )
        )
    if missing_anchors:
        issues.append(
            ValidationIssue(
                "unknown_evidence_anchor",
                "finding cites evidence anchors not present in the focused packet: "
                + ", ".join(missing_anchors),
                "evidence_anchor_ids",
            )
        )

    if status == "no_adjustment_identified" and not str(finding.get("no_adjustment_reason") or "").strip():
        issues.append(
            ValidationIssue(
                "missing_no_adjustment_reason",
                "no_adjustment_identified requires no_adjustment_reason",
                "no_adjustment_reason",
            )
        )
    if status == "missing_evidence" and not str(finding.get("missing_evidence_reason") or "").strip():
        issues.append(
            ValidationIssue(
                "missing_evidence_reason",
                "missing_evidence requires missing_evidence_reason",
                "missing_evidence_reason",
            )
        )

    allowed_fields = {
        str(value).strip()
        for value in packet.get("allowed_driver_fields") or []
        if str(value).strip()
    }
    claim_driver = str(finding.get("claim_driver_field") or "").strip()
    proposed_driver = str(finding.get("proposed_driver_field") or "").strip()
    if status == "candidate" and not claim_driver:
        issues.append(
            ValidationIssue(
                "missing_claim_driver",
                "candidate findings must name claim_driver_field",
                "claim_driver_field",
            )
        )
    if claim_driver and claim_driver not in allowed_fields:
        issues.append(
            ValidationIssue(
                "claim_driver_not_allowed",
                f"claim driver {claim_driver!r} is not allowed for this focused topic",
                "claim_driver_field",
            )
        )
    if proposed_driver and proposed_driver not in allowed_fields:
        issues.append(
            ValidationIssue(
                "proposed_driver_not_allowed",
                f"proposed driver {proposed_driver!r} is not allowed for this focused topic",
                "proposed_driver_field",
            )
        )
    if status == "candidate" and treatment not in _NON_MUTATING_TREATMENTS:
        if not proposed_driver:
            issues.append(
                ValidationIssue(
                    "missing_proposed_driver",
                    "valuation-changing candidates must name proposed_driver_field",
                    "proposed_driver_field",
                )
            )
        elif claim_driver and proposed_driver != claim_driver:
            issues.append(
                ValidationIssue(
                    "driver_mismatch",
                    "claim concerns driver "
                    f"{claim_driver!r} but proposal changes {proposed_driver!r}; "
                    "preserve the finding and correct the proposal mapping",
                    "proposed_driver_field",
                )
            )

    for required in ("topic", "finding_type", "line_item", "claim"):
        if not str(finding.get(required) or "").strip():
            issues.append(
                ValidationIssue(
                    "missing_required_field",
                    f"{required} is required",
                    required,
                )
            )

    return ValidationResult(valid=not issues, issues=issues)


def build_repair_request(
    finding: dict[str, Any],
    issues: list[ValidationIssue],
    packet: dict[str, Any],
) -> dict[str, Any]:
    """Build the exact structured feedback sent to a focused repair call."""

    evidence_index = _packet_evidence(packet)
    anchor_ids = [str(value).strip() for value in finding.get("evidence_anchor_ids") or []]
    instruction = (
        "Preserve the underlying finding when the cited evidence supports it. "
        "Change only fields identified by the validation errors. "
        "Return the same JSON schema; do not invent evidence or silently drop "
        "the finding. If the evidence supports only a risk or disclosure, "
        "return no_adjustment_identified or missing_evidence instead of a "
        "valuation-changing candidate."
    )
    if any(issue.code == "driver_mismatch" for issue in issues):
        instruction = (
            "The underlying finding is retained. Correct only the mismatched "
            "proposal field: the claim driver and proposed driver must align "
            "when the candidate changes valuation. Do not discard or rewrite "
            "the finding merely because its first proposal mapped to the wrong "
            "driver. "
            + instruction
        )
    evidence_context = [evidence_index[anchor] for anchor in anchor_ids if anchor in evidence_index]
    return {
        "original_finding": finding,
        "validation_errors": [asdict(issue) for issue in issues],
        "allowed_driver_fields": list(packet.get("allowed_driver_fields") or []),
        "evidence_anchor_ids": anchor_ids,
        "evidence": evidence_context,
        "evidence_context": evidence_context,
        "rejection_cause": [asdict(issue) for issue in issues],
        "repair_instruction": instruction,
    }


def _as_dict(value: Any) -> Any:
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return value


def _schema_issues(error: Exception) -> list[ValidationIssue]:
    if isinstance(error, ValidationError):
        return [
            ValidationIssue(
                "invalid_focus_envelope",
                str(item.get("msg") or "invalid focus envelope"),
                ".".join(str(part) for part in item.get("loc", ())) or None,
            )
            for item in error.errors()
        ]
    return [ValidationIssue("invalid_focus_envelope", str(error))]


def _packet_dict(packet: Any) -> dict[str, Any]:
    value = _as_dict(packet)
    if not isinstance(value, dict):
        raise TypeError("focused packet must be a dict or Pydantic model")
    return value


def _parse_focus_response(raw: Any) -> AccountingFocusResponse:
    return raw if isinstance(raw, AccountingFocusResponse) else AccountingFocusResponse.model_validate(raw)


def run_focus_repair_cycle(
    response: Any,
    *,
    packet: Any,
    repair_callable: Callable[[dict[str, Any]], Any],
) -> FocusRepairResult:
    """Validate a multi-finding response with one envelope and item retry.

    The callback is transport-agnostic.  It receives a machine-readable
    envelope request for schema failures, or an item request from
    :func:`build_repair_request` for semantic failures, and may return either
    dictionaries or the corresponding Pydantic models.
    """

    focused_packet = _packet_dict(packet)
    envelope_attempts: list[dict[str, Any]] = [{"raw_output": _as_dict(response)}]
    try:
        parsed = _parse_focus_response(response)
    except (ValidationError, TypeError, ValueError) as error:
        schema_errors = _schema_issues(error)
        envelope_request = {
            "raw_output": _as_dict(response),
            "schema_errors": [asdict(issue) for issue in schema_errors],
            "focused_packet": focused_packet,
            "repair_instruction": (
                "Return one complete AccountingFocusResponse envelope. Preserve "
                "all independently supported findings; do not merge siblings "
                "or silently truncate them."
            ),
        }
        repaired_envelope = repair_callable(envelope_request)
        envelope_attempts.append({"raw_output": _as_dict(repaired_envelope), "schema_errors": [asdict(issue) for issue in schema_errors]})
        try:
            parsed = _parse_focus_response(repaired_envelope)
        except (ValidationError, TypeError, ValueError) as final_error:
            final_issues = _schema_issues(final_error)
            return FocusRepairResult(
                "rejected_after_repair",
                None,
                envelope_attempts,
                [],
                final_issues,
            )
        envelope_repaired = True
    else:
        envelope_repaired = False

    if not parsed.findings:
        return FocusRepairResult(
            "repaired" if envelope_repaired else "accepted",
            parsed.model_dump(mode="json"),
            envelope_attempts,
            [],
        )

    accepted: list[AccountingFinding] = []
    item_results: list[FocusFindingRepairResult] = []
    rejected = False
    for finding_model in parsed.findings:
        original = finding_model.model_dump(mode="json")
        finding_id = str(finding_model.finding_id)
        initial = validate_accounting_finding(original, focused_packet)
        if initial.valid:
            accepted.append(finding_model)
            item_results.append(FocusFindingRepairResult(finding_id, "accepted", original, [original]))
            continue

        rejected = True
        request = build_repair_request(original, initial.issues, focused_packet)
        repaired_raw = repair_callable(request)
        repaired_dict = _as_dict(repaired_raw)
        attempts = [original, repaired_dict]
        try:
            repaired_model = AccountingFinding.model_validate(repaired_raw)
            repaired_dict = repaired_model.model_dump(mode="json")
            final = validate_accounting_finding(repaired_dict, focused_packet)
        except (ValidationError, TypeError, ValueError) as error:
            final = ValidationResult(False, _schema_issues(error))
            repaired_model = None
        if final.valid and repaired_model is not None:
            accepted.append(repaired_model)
            item_results.append(FocusFindingRepairResult(finding_id, "repaired", original, attempts))
        else:
            item_results.append(
                FocusFindingRepairResult(
                    finding_id,
                    "rejected_after_repair",
                    original,
                    attempts,
                    final.issues,
                )
            )

    output = parsed.model_copy(update={"findings": accepted}).model_dump(mode="json")
    return FocusRepairResult(
        "accepted_with_rejections" if rejected else ("repaired" if envelope_repaired else "accepted"),
        output,
        envelope_attempts,
        item_results,
    )


def run_repair_cycle(
    finding: dict[str, Any],
    *,
    packet: dict[str, Any],
    repair_callable: Callable[[dict[str, Any]], dict[str, Any]],
) -> RepairCycleResult:
    """Validate once, repair once when needed, and retain both attempts."""

    attempts = [finding]
    initial = validate_accounting_finding(finding, packet)
    if initial.valid:
        return RepairCycleResult("accepted", finding, attempts, [])

    request = build_repair_request(finding, initial.issues, packet)
    repaired = repair_callable(request)
    attempts.append(repaired)
    final = validate_accounting_finding(repaired, packet)
    if final.valid:
        return RepairCycleResult("repaired", repaired, attempts, [])
    return RepairCycleResult("rejected_after_repair", None, attempts, final.issues)
