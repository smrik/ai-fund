"""Deterministic validation and repair payloads for accounting findings.

This module never calls an LLM and never mutates valuation inputs. It validates
the small accounting responses returned by focused judgment calls and gives a
repair caller the exact evidence and contract failure that must be fixed.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import math
import re
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
_ACCOUNTING_TO_VALUATION = {
    "normalize": "normalized_ebit",
    "bridge_adjustment": "ev_equity_bridge",
    "scenario_only": "scenario_only",
    "disclosure_only": "disclosure_only",
}
_PM_OVERREACH = re.compile(
    r"\b(?:approved|applied|decision[- ]ready|implemented|automatically\s+(?:changed|applied)|"
    r"set\s+the\s+model|the\s+pm\s+(?:must|should)\s+(?:approve|apply|set|change))\b",
    re.IGNORECASE,
)
_WORD = re.compile(r"[a-z][a-z0-9_-]{3,}")
_STOPWORDS = {
    "accounting", "candidate", "company", "disclosed", "evidence", "fiscal",
    "finding", "identified", "reported", "review", "separately", "supported",
    "treatment", "value", "year",
}
_TEXT_FIELDS = (
    "finding_type", "line_item", "claim", "direction", "timing",
    "materiality_rationale", "citation_text", "pm_question",
    "what_would_change_mind", "no_adjustment_reason", "missing_evidence_reason",
)
_NUMERIC_GROUNDED_FIELDS = (
    "reported_value", "proposed_value", "cash_impact", "tax_impact",
)


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
def _is_finite_number(value: Any) -> bool:
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(float(value))


def _values_equal(left: Any, right: Any) -> bool:
    if _is_finite_number(left) and _is_finite_number(right):
        return math.isclose(float(left), float(right), rel_tol=1e-12, abs_tol=1e-12)
    return left == right


def _semantic_tokens(value: Any) -> set[str]:
    return {token for token in _WORD.findall(str(value or "").lower()) if token not in _STOPWORDS}


def _cited_evidence(
    evidence: dict[str, dict[str, Any]],
    anchor_ids: list[str],
) -> list[dict[str, Any]]:
    return [evidence[anchor] for anchor in anchor_ids if anchor in evidence]
def _grounding_issues(
    finding: dict[str, Any],
    packet: dict[str, Any],
    cited: list[dict[str, Any]],
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    fact_values = [item.get("value") for item in cited if item.get("kind") == "fact"]
    current_fields = packet.get("current_model_fields") or {}
    proposed_driver = str(finding.get("proposed_driver_field") or "").strip()
    for field_name in _NUMERIC_GROUNDED_FIELDS:
        value = finding.get(field_name)
        if value is None:
            continue
        allowed = list(fact_values)
        if field_name == "proposed_value" and proposed_driver in current_fields:
            allowed.append(current_fields[proposed_driver])
        if not any(_values_equal(value, candidate) for candidate in allowed):
            issues.append(
                ValidationIssue(
                    "numeric_value_not_anchored",
                    f"{field_name} must exactly match a cited structured fact or supplied current-model value",
                    field_name,
                )
            )

    units: set[str] = set()
    periods: set[str] = set()
    for item in cited:
        metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        for candidate in (
            item.get("unit"), metadata.get("unit"), metadata.get("currency"), item.get("currency")
        ):
            if candidate is not None and str(candidate).strip():
                units.add(str(candidate).strip().lower())
        for candidate in (
            item.get("period"), metadata.get("period"), metadata.get("period_end"), metadata.get("period_start")
        ):
            if candidate is not None and str(candidate).strip():
                periods.add(str(candidate).strip().lower())
    supplied_unit = str(finding.get("currency") or "").strip().lower()
    if supplied_unit and supplied_unit not in units:
        issues.append(
            ValidationIssue(
                "numeric_metadata_mismatch",
                "currency/unit is not supported by the cited evidence",
                "currency",
            )
        )
    supplied_period = str(finding.get("period") or "").strip().lower()
    if supplied_period and supplied_period not in periods:
        issues.append(
            ValidationIssue(
                "numeric_metadata_mismatch",
                "period is not supported by the cited evidence",
                "period",
            )
        )

    citation = str(finding.get("citation_text") or "").strip()
    if citation:
        snippet_texts = [
            str(item.get("text") or "") for item in cited if item.get("kind") == "snippet"
        ]
        if not any(citation in text for text in snippet_texts):
            issues.append(
                ValidationIssue(
                    "citation_not_in_anchor",
                    "citation_text is not present in a cited snippet",
                    "citation_text",
                )
            )

    if cited:
        claim_tokens = _semantic_tokens(
            " ".join(
                str(finding.get(field) or "")
                for field in ("finding_type", "line_item", "claim")
            )
        )
        evidence_tokens: set[str] = set()
        for item in cited:
            evidence_tokens |= _semantic_tokens(item.get("fact_name"))
            evidence_tokens |= _semantic_tokens(item.get("text"))
        if claim_tokens and not claim_tokens.intersection(evidence_tokens):
            issues.append(
                ValidationIssue(
                    "evidence_anchor_not_relevant",
                    "cited anchors do not share a material semantic term with the finding",
                    "evidence_anchor_ids",
                )
            )
    return issues


def _forward_driver_supported(
    finding: dict[str, Any],
    cited: list[dict[str, Any]],
) -> bool:
    proposed_driver = str(finding.get("proposed_driver_field") or "").strip()
    for item in cited:
        if item.get("kind") != "fact":
            continue
        metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        role = str(metadata.get("fact_role") or "").lower()
        driver = str(metadata.get("driver_field") or "")
        period_type = " ".join(
            str(metadata.get(key) or "").lower()
            for key in ("period_type", "estimate_status", "series_type")
        )
        if (role == "current_model_driver" and driver == proposed_driver) or any(
            token in period_type for token in ("forecast", "estimate", "forward")
        ):
            return True
    return False


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
    cited = _cited_evidence(evidence, anchor_ids)
    issues.extend(_grounding_issues(finding, packet, cited))

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
    if status == "candidate" and treatment not in _NON_MUTATING_TREATMENTS and not claim_driver:
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

    packet_topic = str(packet.get("topic") or "").strip()
    finding_topic = str(finding.get("topic") or "").strip()
    if packet_topic and finding_topic != packet_topic:
        issues.append(
            ValidationIssue(
                "focus_topic_mismatch",
                "finding topic does not match the system-owned focused packet",
                "topic",
            )
        )
    packet_focus = str(packet.get("focus_key") or "").strip()
    finding_focus = str(finding.get("focus_key") or "").strip()
    if packet_focus and finding_focus != packet_focus:
        issues.append(
            ValidationIssue(
                "focus_topic_mismatch",
                "finding focus_key does not match the system-owned focused packet",
                "focus_key",
            )
        )

    accounting_treatment = str(finding.get("accounting_treatment") or "").strip()
    if status == "candidate":
        expected_valuation = _ACCOUNTING_TO_VALUATION.get(accounting_treatment)
        if expected_valuation != treatment:
            issues.append(
                ValidationIssue(
                    "status_treatment_conflict",
                    "candidate accounting and valuation treatments are not a permitted pair",
                    "accounting_treatment",
                )
            )
        if treatment in _NON_MUTATING_TREATMENTS and any(
            finding.get(field_name) not in (None, "")
            for field_name in ("claim_driver_field", "proposed_driver_field", "proposed_value")
        ):
            issues.append(
                ValidationIssue(
                    "status_treatment_conflict",
                    "scenario/disclosure-only candidates cannot name or change model drivers",
                    "proposed_driver_field",
                )
            )
        for field_name, message in (
            ("materiality_rationale", "candidate findings require a materiality rationale"),
            ("what_would_change_mind", "candidate findings require a falsifier"),
        ):
            if not str(finding.get(field_name) or "").strip():
                issues.append(ValidationIssue("missing_candidate_governance", message, field_name))
        pm_question = str(finding.get("pm_question") or "").strip()
        if not pm_question or not pm_question.endswith("?"):
            issues.append(
                ValidationIssue(
                    "invalid_pm_question",
                    "candidate pm_question must be concrete and end with '?'",
                    "pm_question",
                )
            )
        current_fields = packet.get("current_model_fields") or {}
        if treatment not in _NON_MUTATING_TREATMENTS and current_fields and proposed_driver not in current_fields:
            issues.append(
                ValidationIssue(
                    "driver_not_current",
                    "valuation-changing proposal must target a supplied current-model driver",
                    "proposed_driver_field",
                )
            )
        forward_driver_names = ("target", "growth", "near", "mid", "long")
        if (
            treatment == "normalized_ebit"
            and proposed_driver
            and any(token in proposed_driver.lower() for token in forward_driver_names)
            and not _forward_driver_supported(finding, cited)
        ):
            issues.append(
                ValidationIssue(
                    "historical_to_forward_driver",
                    "historical evidence cannot change a forward driver without a forward-looking anchor for that driver",
                    "proposed_driver_field",
                )
            )
    elif status == "no_adjustment_identified":
        if accounting_treatment != "no_adjustment" or treatment != "none":
            issues.append(
                ValidationIssue(
                    "status_treatment_conflict",
                    "no-adjustment findings require no_adjustment/none treatments",
                    "accounting_treatment",
                )
            )
        if any(
            finding.get(field_name) not in (None, "")
            for field_name in (
                "claim_driver_field", "proposed_driver_field", "proposed_value",
                "cash_impact", "tax_impact",
            )
        ):
            issues.append(
                ValidationIssue(
                    "status_treatment_conflict",
                    "no-adjustment findings cannot contain a valuation proposal",
                    "proposed_value",
                )
            )
    elif status == "missing_evidence":
        if treatment != "none" or any(
            finding.get(field_name) not in (None, "")
            for field_name in _NUMERIC_GROUNDED_FIELDS + ("claim_driver_field", "proposed_driver_field")
        ):
            issues.append(
                ValidationIssue(
                    "status_treatment_conflict",
                    "missing-evidence findings cannot contain numeric or valuation proposals",
                    "valuation_treatment",
                )
            )

    if len(anchor_ids) != len(set(anchor_ids)):
        issues.append(
            ValidationIssue(
                "duplicate_evidence_anchor",
                "evidence_anchor_ids must be unique within a finding",
                "evidence_anchor_ids",
            )
        )
    confidence = str(finding.get("confidence") or "").strip().lower()
    if confidence and confidence not in {"low", "medium", "high"}:
        issues.append(
            ValidationIssue(
                "invalid_confidence",
                "confidence must be low, medium, or high",
                "confidence",
            )
        )
    for field_name in _TEXT_FIELDS:
        value = str(finding.get(field_name) or "")
        if _PM_OVERREACH.search(value):
            issues.append(
                ValidationIssue(
                    "pm_authority_overreach",
                    f"{field_name} claims approval, application, or PM authority",
                    field_name,
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


def _focus_envelope_issues(
    response: AccountingFocusResponse,
    packet: dict[str, Any],
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    expected_focus = str(packet.get("focus_key") or "").strip()
    if expected_focus and response.focus_key.value != expected_focus:
        issues.append(
            ValidationIssue(
                "focus_key_mismatch",
                "response focus_key does not match the system-owned packet focus",
                "focus_key",
            )
        )
    expected_status = str(packet.get("packet_status") or "").strip()
    if expected_status and response.packet_status.value != expected_status:
        issues.append(
            ValidationIssue(
                "packet_status_mismatch",
                "response packet_status does not match the system-owned packet status",
                "packet_status",
            )
        )

    signatures: set[tuple[str, str, tuple[str, ...]]] = set()
    treatments_by_anchor: dict[str, str] = {}
    for finding in response.findings:
        payload = finding.model_dump(mode="json")
        signature = (
            str(payload.get("finding_type") or "").strip().lower(),
            str(payload.get("line_item") or "").strip().lower(),
            tuple(sorted(str(value) for value in payload.get("evidence_anchor_ids") or [])),
        )
        if signature in signatures:
            issues.append(
                ValidationIssue(
                    "duplicate_atomic_item",
                    "multiple findings represent the same atomic item and evidence",
                    "findings",
                )
            )
        signatures.add(signature)
        treatment = str(payload.get("valuation_treatment") or "")
        if treatment in {"normalized_ebit", "ev_equity_bridge"}:
            for anchor in payload.get("evidence_anchor_ids") or []:
                previous = treatments_by_anchor.get(str(anchor))
                if previous and previous != treatment:
                    issues.append(
                        ValidationIssue(
                            "double_count_group_conflict",
                            "the same evidence anchor is used in normalized EBIT and the EV-equity bridge",
                            "findings",
                        )
                    )
                treatments_by_anchor[str(anchor)] = treatment
    for note in response.coverage_notes:
        if _PM_OVERREACH.search(str(note)):
            issues.append(
                ValidationIssue(
                    "pm_authority_overreach",
                    "coverage notes claim approval, application, or PM authority",
                    "coverage_notes",
                )
            )
    return issues


def _repair_integrity_issues(
    original: dict[str, Any],
    repaired: dict[str, Any],
    initial_issues: list[ValidationIssue],
) -> list[ValidationIssue]:
    mutable_fields = {issue.field for issue in initial_issues if issue.field}
    immutable_fields = {
        "finding_id", "topic", "focus_key", "finding_status", "finding_type",
        "line_item", "claim", "evidence_anchor_ids",
    }
    issues: list[ValidationIssue] = []
    for field_name in sorted(set(original).union(repaired)):
        if field_name in mutable_fields and field_name not in immutable_fields:
            continue
        if original.get(field_name) != repaired.get(field_name):
            issues.append(
                ValidationIssue(
                    "repair_identity_changed" if field_name in immutable_fields else "repair_modified_unflagged_field",
                    f"repair changed system-owned or unflagged field {field_name!r}",
                    field_name,
                )
            )
    return issues
def run_focus_repair_cycle(
    response: Any,
    *,
    packet: Any,
    repair_callable: Callable[[dict[str, Any]], Any],
) -> FocusRepairResult:
    """Validate one bounded focus envelope and permit at most one repair per layer."""

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
                "Return one complete AccountingFocusResponse envelope. Preserve all "
                "independently supported findings; do not merge or silently truncate them. "
                "focus_key and packet_status must exactly match the focused packet."
            ),
        }
        repaired_envelope = repair_callable(envelope_request)
        envelope_attempts.append(
            {
                "raw_output": _as_dict(repaired_envelope),
                "schema_errors": [asdict(issue) for issue in schema_errors],
            }
        )
        try:
            parsed = _parse_focus_response(repaired_envelope)
        except (ValidationError, TypeError, ValueError) as final_error:
            return FocusRepairResult(
                "rejected_after_repair",
                None,
                envelope_attempts,
                [],
                _schema_issues(final_error),
            )
        envelope_repaired = True
    else:
        envelope_repaired = False

    envelope_issues = _focus_envelope_issues(parsed, focused_packet)
    if envelope_issues:
        if envelope_repaired:
            return FocusRepairResult(
                "rejected_after_repair",
                None,
                envelope_attempts,
                [],
                envelope_issues,
            )
        envelope_request = {
            "raw_output": parsed.model_dump(mode="json"),
            "schema_errors": [asdict(issue) for issue in envelope_issues],
            "focused_packet": focused_packet,
            "repair_instruction": (
                "Correct only the envelope fields identified by validation. System-owned "
                "focus_key and packet_status must match the packet, and findings must remain "
                "independent, bounded, and free of double counting."
            ),
        }
        repaired_envelope = repair_callable(envelope_request)
        envelope_attempts.append(
            {
                "raw_output": _as_dict(repaired_envelope),
                "schema_errors": [asdict(issue) for issue in envelope_issues],
            }
        )
        try:
            parsed = _parse_focus_response(repaired_envelope)
        except (ValidationError, TypeError, ValueError) as final_error:
            return FocusRepairResult(
                "rejected_after_repair",
                None,
                envelope_attempts,
                [],
                _schema_issues(final_error),
            )
        final_envelope_issues = _focus_envelope_issues(parsed, focused_packet)
        if final_envelope_issues:
            return FocusRepairResult(
                "rejected_after_repair",
                None,
                envelope_attempts,
                [],
                final_envelope_issues,
            )
        envelope_repaired = True

    if not parsed.findings:
        return FocusRepairResult(
            "repaired" if envelope_repaired else "accepted",
            parsed.model_dump(mode="json"),
            envelope_attempts,
            [],
        )

    accepted: list[AccountingFinding] = []
    item_results: list[FocusFindingRepairResult] = []
    any_repaired = False
    any_rejected = False
    for finding_model in parsed.findings:
        original = finding_model.model_dump(mode="json")
        finding_id = str(finding_model.finding_id)
        initial = validate_accounting_finding(original, focused_packet)
        if initial.valid:
            accepted.append(finding_model)
            item_results.append(
                FocusFindingRepairResult(finding_id, "accepted", original, [original])
            )
            continue

        request = build_repair_request(original, initial.issues, focused_packet)
        repaired_raw = repair_callable(request)
        raw_repaired_dict = _as_dict(repaired_raw)
        attempts = [original, raw_repaired_dict]
        try:
            if not isinstance(raw_repaired_dict, dict):
                raise TypeError("item repair must return one finding object")
            repaired_payload = dict(raw_repaired_dict)
            if not repaired_payload.get("finding_id"):
                repaired_payload["finding_id"] = finding_id
            repaired_model = AccountingFinding.model_validate(repaired_payload)
            repaired_dict = repaired_model.model_dump(mode="json")
            semantic = validate_accounting_finding(repaired_dict, focused_packet)
            integrity = _repair_integrity_issues(original, repaired_dict, initial.issues)
            final = ValidationResult(
                semantic.valid and not integrity,
                [*semantic.issues, *integrity],
            )
        except (ValidationError, TypeError, ValueError) as error:
            final = ValidationResult(False, _schema_issues(error))
            repaired_model = None
        if final.valid and repaired_model is not None:
            any_repaired = True
            accepted.append(repaired_model)
            item_results.append(
                FocusFindingRepairResult(finding_id, "repaired", original, attempts)
            )
        else:
            any_rejected = True
            item_results.append(
                FocusFindingRepairResult(
                    finding_id,
                    "rejected_after_repair",
                    original,
                    attempts,
                    final.issues,
                )
            )

    coverage_notes = list(parsed.coverage_notes)
    if not accepted and not coverage_notes:
        coverage_notes.append(
            "All model-returned findings were rejected by deterministic validation."
        )
    final_payload = {
        "focus_key": parsed.focus_key.value,
        "packet_status": parsed.packet_status.value,
        "findings": [finding.model_dump(mode="json") for finding in accepted],
        "coverage_notes": coverage_notes,
    }
    try:
        final_response = AccountingFocusResponse.model_validate(final_payload)
    except (ValidationError, TypeError, ValueError) as error:
        return FocusRepairResult(
            "rejected_after_repair",
            None,
            envelope_attempts,
            item_results,
            _schema_issues(error),
        )
    final_envelope_issues = _focus_envelope_issues(final_response, focused_packet)
    if final_envelope_issues:
        return FocusRepairResult(
            "rejected_after_repair",
            None,
            envelope_attempts,
            item_results,
            final_envelope_issues,
        )

    status = (
        "accepted_with_rejections"
        if any_rejected
        else "repaired"
        if envelope_repaired or any_repaired
        else "accepted"
    )
    return FocusRepairResult(
        status,
        final_response.model_dump(mode="json"),
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
    semantic = validate_accounting_finding(repaired, packet)
    integrity = _repair_integrity_issues(finding, repaired, initial.issues)
    final = ValidationResult(
        semantic.valid and not integrity,
        [*semantic.issues, *integrity],
    )
    if final.valid:
        return RepairCycleResult("repaired", repaired, attempts, [])
    return RepairCycleResult("rejected_after_repair", None, attempts, final.issues)
