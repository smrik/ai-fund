"""Deterministic accounting adjustment ledger and PM queue translation.

Findings enter the ledger after validation/repair. Duplicates keep provenance,
conflicts stay explicit, and only PM-reviewable candidates become queue items.
This module never mutates valuation inputs.
"""

from __future__ import annotations

import hashlib
import json
from enum import Enum
from typing import Any, Mapping

from pydantic import Field, field_validator

from src.contracts.assumption_registry import (
    AssumptionOwner,
    get_assumption_definition,
)
from src.contracts.assumption_policy import ContractModel
from src.contracts.pm_decision_queue import (
    AssumptionChangePack,
    AssumptionChangeProposal,
    PMDecisionQueueItem,
    PMDecisionQueueItemType,
    ProposalMode,
    QueueConfidence,
)
from src.stage_04_pipeline.agentic_handoff_profiles import (
    AGENT_PROPOSABLE_ASSUMPTION_FIELDS,
    get_agentic_handoff_profile,
)

ACCOUNTING_LEDGER_CONTRACT_VERSION = "1.0.0"

_NON_MUTATING_TREATMENTS = frozenset({"scenario_only", "disclosure_only", "none"})
_QUEUEABLE_FINDING_STATUSES = frozenset({"candidate"})
_LEDGER_ONLY_STATUSES = frozenset({"no_adjustment_identified", "missing_evidence"})


class AccountingLedgerStatus(str, Enum):
    candidate = "candidate"
    no_adjustment_identified = "no_adjustment_identified"
    missing_evidence = "missing_evidence"
    duplicate = "duplicate"
    conflict = "conflict"
    rejected_after_repair = "rejected_after_repair"


def _as_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, Mapping):
        return dict(value)
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    raise TypeError(f"unsupported finding payload type: {type(value)!r}")


def _text(value: Any) -> str:
    return str(value or "").strip()


def _sorted_anchors(finding: Mapping[str, Any]) -> list[str]:
    anchors = [_text(anchor) for anchor in finding.get("evidence_anchor_ids") or []]
    return sorted(anchor for anchor in anchors if anchor)


def finding_fingerprint(finding: Mapping[str, Any] | Any) -> str:
    """Stable identity for merge/dedupe.

    Based on focus, line item, period, proposed driver, and evidence anchors.
    Claim prose is intentionally excluded so wording variants still dedupe.
    """

    payload = _as_dict(finding)
    identity = {
        "focus_key": _text(payload.get("focus_key")),
        "line_item": _text(payload.get("line_item")).lower(),
        "period": _text(payload.get("period")),
        "proposed_driver_field": _text(payload.get("proposed_driver_field")),
        "evidence_anchor_ids": _sorted_anchors(payload),
    }
    canonical = json.dumps(identity, sort_keys=True, separators=(",", ":"))
    return "acctfp:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:20]


def conflict_group_key(finding: Mapping[str, Any] | Any) -> str:
    """Group key for contradictory proposals on the same accounting object."""

    payload = _as_dict(finding)
    identity = {
        "focus_key": _text(payload.get("focus_key")),
        "line_item": _text(payload.get("line_item")).lower(),
        "period": _text(payload.get("period")),
        "proposed_driver_field": _text(payload.get("proposed_driver_field")),
    }
    canonical = json.dumps(identity, sort_keys=True, separators=(",", ":"))
    return "acctcg:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def _proposal_signature(finding: Mapping[str, Any]) -> str:
    identity = {
        "proposed_value": finding.get("proposed_value"),
        "direction": _text(finding.get("direction")).lower(),
        "valuation_treatment": _text(finding.get("valuation_treatment")).lower(),
        "accounting_treatment": _text(finding.get("accounting_treatment")).lower(),
    }
    return json.dumps(identity, sort_keys=True, separators=(",", ":"), default=str)


def _initial_ledger_status(finding: Mapping[str, Any]) -> AccountingLedgerStatus:
    status = _text(finding.get("finding_status"))
    if status == AccountingLedgerStatus.no_adjustment_identified.value:
        return AccountingLedgerStatus.no_adjustment_identified
    if status == AccountingLedgerStatus.missing_evidence.value:
        return AccountingLedgerStatus.missing_evidence
    if status == AccountingLedgerStatus.candidate.value:
        return AccountingLedgerStatus.candidate
    # Unknown/invalid statuses stay auditable without becoming queue mutations.
    return AccountingLedgerStatus.rejected_after_repair


class AccountingLedgerEntry(ContractModel):
    entry_id: str
    fingerprint: str
    finding_id: str
    ledger_status: AccountingLedgerStatus
    finding: dict[str, Any]
    duplicate_of: str | None = None
    conflict_group_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("entry_id", "fingerprint", "finding_id")
    @classmethod
    def _required(cls, value: str) -> str:
        cleaned = str(value).strip()
        if not cleaned:
            raise ValueError("field is required")
        return cleaned


class AccountingAdjustmentLedger(ContractModel):
    contract_version: str = ACCOUNTING_LEDGER_CONTRACT_VERSION
    ticker: str
    entries: list[AccountingLedgerEntry] = Field(default_factory=list)
    conflict_groups: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("ticker")
    @classmethod
    def _uppercase_ticker(cls, value: str) -> str:
        return str(value).upper().strip()


def merge_findings_into_ledger(
    *,
    ticker: str,
    findings: list[Mapping[str, Any] | Any] | None = None,
    rejected_findings: list[Mapping[str, Any] | Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> AccountingAdjustmentLedger:
    """Merge validated findings into a deterministic adjustment ledger.

    Rules:
    - first occurrence of a fingerprint is primary
    - later same-fingerprint findings are duplicates with provenance
    - same conflict key with different proposal signatures become a conflict group
    - rejected_after_repair findings remain visible and non-queueable for mutation
    """

    entries: list[AccountingLedgerEntry] = []
    fingerprint_primary: dict[str, tuple[str, str]] = {}
    conflict_bucket: dict[str, list[AccountingLedgerEntry]] = {}

    ordered: list[tuple[AccountingLedgerStatus | None, dict[str, Any]]] = []
    for raw in findings or []:
        payload = _as_dict(raw)
        ordered.append((_initial_ledger_status(payload), payload))
    for raw in rejected_findings or []:
        payload = _as_dict(raw)
        ordered.append((AccountingLedgerStatus.rejected_after_repair, payload))

    for index, (forced_status, payload) in enumerate(ordered):
        finding_id = _text(payload.get("finding_id")) or f"finding:anonymous:{index}"
        if not _text(payload.get("finding_id")):
            payload = {**payload, "finding_id": finding_id}

        fingerprint = finding_fingerprint(payload)
        status = forced_status or AccountingLedgerStatus.candidate
        duplicate_of: str | None = None
        conflict_group_id: str | None = None

        if status == AccountingLedgerStatus.candidate:
            proposal_signature = _proposal_signature(payload)
            primary = fingerprint_primary.get(fingerprint)
            if primary is not None and primary[1] == proposal_signature:
                status = AccountingLedgerStatus.duplicate
                duplicate_of = primary[0]
            elif primary is None:
                fingerprint_primary[fingerprint] = (finding_id, proposal_signature)

        entry = AccountingLedgerEntry(
            entry_id=f"ledger:{ticker.upper()}:{finding_id}",
            fingerprint=fingerprint,
            finding_id=finding_id,
            ledger_status=status,
            finding=payload,
            duplicate_of=duplicate_of,
            conflict_group_id=conflict_group_id,
            metadata={
                "focus_key": _text(payload.get("focus_key")),
                "period": _text(payload.get("period")),
                "proposed_driver_field": _text(payload.get("proposed_driver_field")),
            },
        )
        entries.append(entry)

        if status in {
            AccountingLedgerStatus.candidate,
            AccountingLedgerStatus.duplicate,
            AccountingLedgerStatus.conflict,
        } and _text(payload.get("finding_status")) == "candidate":
            key = conflict_group_key(payload)
            conflict_bucket.setdefault(key, []).append(entry)

    conflict_groups: list[dict[str, Any]] = []
    for key, group_entries in conflict_bucket.items():
        # Only primary candidates participate in contradiction detection.
        primaries = [
            entry
            for entry in group_entries
            if entry.ledger_status == AccountingLedgerStatus.candidate
        ]
        signatures = {_proposal_signature(entry.finding) for entry in primaries}
        if len(primaries) < 2 or len(signatures) < 2:
            continue
        conflict_group_id = key
        finding_ids = [entry.finding_id for entry in primaries]
        conflict_groups.append(
            {
                "conflict_group_id": conflict_group_id,
                "finding_ids": finding_ids,
                "fingerprints": [entry.fingerprint for entry in primaries],
                "reason": "contradictory_proposals_for_same_accounting_object",
            }
        )
        for entry in primaries:
            entry.ledger_status = AccountingLedgerStatus.conflict
            entry.conflict_group_id = conflict_group_id

    return AccountingAdjustmentLedger(
        ticker=ticker,
        entries=entries,
        conflict_groups=conflict_groups,
        metadata=dict(metadata or {}),
    )


def _to_queue_confidence(value: Any | None) -> QueueConfidence | None:
    if value is None:
        return None
    raw = value.value if hasattr(value, "value") else value
    text = str(raw).strip().lower()
    if text in {"low", "medium", "high"}:
        return QueueConfidence(text)
    return None


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _profile_for_finding(finding: Mapping[str, Any], profile_name: str | None) -> str:
    if profile_name:
        return profile_name
    topic = _text(finding.get("topic"))
    mapping = {
        "qoe": "accounting_qoe",
        "ev_equity_bridge": "accounting_ev_equity_bridge",
        "contingencies_and_taxes": "accounting_contingencies_and_taxes",
        "segments_and_disclosure": "accounting_segments_and_disclosure",
    }
    return mapping.get(topic, "accounting_qoe")


def _queue_title(finding: Mapping[str, Any]) -> str:
    focus = _text(finding.get("focus_key")).replace("_", " ")
    line_item = _text(finding.get("line_item")) or _text(finding.get("finding_type"))
    if finding.get("model_change_required"):
        # A structural request is not scoped to one accounting focus; naming one
        # here would mislabel it (open-ended discovery findings in particular).
        return f"Accounting model change: {line_item or 'request'}"
    if focus and line_item:
        return f"Accounting: {focus} — {line_item}"
    return f"Accounting: {line_item or 'finding'}"


def _build_target_proposal(
    finding: Mapping[str, Any],
    *,
    assumption_name: str,
) -> AssumptionChangeProposal | None:
    target = _safe_float(finding.get("proposed_value"))
    if target is None:
        return None
    return AssumptionChangeProposal(
        assumption_name=assumption_name,
        proposal_mode=ProposalMode.target,
        proposed_target_value=target,
        rationale=_text(finding.get("claim")) or None,
        metadata={
            "direction": _text(finding.get("direction")) or None,
            "source": "accounting_finding",
            "finding_id": _text(finding.get("finding_id")),
        },
    )


def _finding_metadata(
    entry: AccountingLedgerEntry,
    *,
    duplicate_finding_ids: list[str] | None = None,
) -> dict[str, Any]:
    finding = entry.finding
    metadata = {
        "observation_id": entry.finding_id,
        "finding_id": entry.finding_id,
        "ledger_entry_id": entry.entry_id,
        "fingerprint": entry.fingerprint,
        "ledger_status": entry.ledger_status.value,
        "focus_key": _text(finding.get("focus_key")) or None,
        "topic": _text(finding.get("topic")) or None,
        "finding_type": _text(finding.get("finding_type")) or None,
        "line_item": _text(finding.get("line_item")) or None,
        "period": _text(finding.get("period")) or None,
        "claim_driver_field": _text(finding.get("claim_driver_field")) or None,
        "proposed_driver_field": _text(finding.get("proposed_driver_field")) or None,
        "direction": _text(finding.get("direction")) or None,
        "proposed_value": finding.get("proposed_value"),
        "accounting_treatment": _text(finding.get("accounting_treatment")) or None,
        "valuation_treatment": _text(finding.get("valuation_treatment")) or None,
        "booked_or_disclosed_status": _text(finding.get("booked_or_disclosed_status")) or None,
        "cash_impact": finding.get("cash_impact"),
        "tax_impact": finding.get("tax_impact"),
        "timing": _text(finding.get("timing")) or None,
        "materiality_rationale": _text(finding.get("materiality_rationale")) or None,
        "pm_question": _text(finding.get("pm_question")) or None,
        "what_would_change_mind": _text(finding.get("what_would_change_mind")) or None,
        "citation_text": _text(finding.get("citation_text")) or None,
        "model_change_required": bool(finding.get("model_change_required")),
        "model_change_request": _text(finding.get("model_change_request")) or None,
        "conflict_group_id": entry.conflict_group_id,
        "duplicate_of": entry.duplicate_of,
        "duplicate_finding_ids": list(duplicate_finding_ids or []),
        "source": "accounting_ledger",
    }
    # Producer-specific provenance (e.g. the discovery question that generated the
    # finding) travels with the queue item so PM review can trace it back.
    extra = finding.get("metadata")
    if isinstance(extra, Mapping) and extra:
        metadata["finding_metadata"] = dict(extra)
    return {key: value for key, value in metadata.items() if value not in (None, [], {})}


def translate_accounting_ledger_to_queue_items(
    ledger: AccountingAdjustmentLedger,
    *,
    ticker: str,
    profile_name: str | None = None,
    evidence_packet_id: int | str,
    require_mutation_driver: bool = True,
) -> list[PMDecisionQueueItem]:
    """Translate ledger entries into PM Decision Queue items.

    - active candidates with mutation treatment + target value -> assumption_change_pack
    - scenario/disclosure candidates -> advisory_finding
    - conflict candidates -> advisory_finding (visible, not auto-applicable)
    - duplicates / no-adjustment / missing / rejected -> ledger only
    """

    duplicates_by_primary: dict[str, list[str]] = {}
    for entry in ledger.entries:
        if entry.ledger_status == AccountingLedgerStatus.duplicate and entry.duplicate_of:
            duplicates_by_primary.setdefault(entry.duplicate_of, []).append(entry.finding_id)

    items: list[PMDecisionQueueItem] = []
    for entry in ledger.entries:
        finding = entry.finding
        finding_status = _text(finding.get("finding_status"))
        if finding_status not in _QUEUEABLE_FINDING_STATUSES:
            continue
        if entry.ledger_status in {
            AccountingLedgerStatus.duplicate,
            AccountingLedgerStatus.no_adjustment_identified,
            AccountingLedgerStatus.missing_evidence,
            AccountingLedgerStatus.rejected_after_repair,
        }:
            continue
        if entry.ledger_status not in {
            AccountingLedgerStatus.candidate,
            AccountingLedgerStatus.conflict,
        }:
            continue

        anchors = _sorted_anchors(finding)
        if not anchors:
            # Queue contract requires evidence anchors; keep unanchored items ledger-only.
            continue

        resolved_profile = _profile_for_finding(finding, profile_name)
        profile = get_agentic_handoff_profile(resolved_profile)
        treatment = _text(finding.get("valuation_treatment")) or "none"
        metadata = _finding_metadata(
            entry,
            duplicate_finding_ids=duplicates_by_primary.get(entry.finding_id, []),
        )
        confidence = _to_queue_confidence(finding.get("confidence"))

        # Conflicts are always advisory so neither side can be applied blindly.
        if entry.ledger_status == AccountingLedgerStatus.conflict or treatment in _NON_MUTATING_TREATMENTS:
            items.append(
                PMDecisionQueueItem(
                    ticker=ticker,
                    profile_name=resolved_profile,
                    item_type=PMDecisionQueueItemType.advisory_finding,
                    status="pending",
                    title=_queue_title(finding),
                    summary=_text(finding.get("claim")) or None,
                    evidence_anchor_ids=anchors,
                    evidence_packet_ids=[str(evidence_packet_id)],
                    agent_confidence=confidence,
                    translator_confidence=QueueConfidence.high,
                    metadata=metadata,
                )
            )
            continue

        if finding.get("model_change_required"):
            items.append(
                PMDecisionQueueItem(
                    ticker=ticker,
                    profile_name=resolved_profile,
                    item_type=PMDecisionQueueItemType.advisory_finding,
                    status="pending",
                    title=_queue_title(finding),
                    summary=_text(finding.get("claim")) or None,
                    evidence_anchor_ids=anchors,
                    evidence_packet_ids=[str(evidence_packet_id)],
                    agent_confidence=confidence,
                    translator_confidence=QueueConfidence.medium,
                    metadata={
                        **metadata,
                        "queue_reason": "model_change_required",
                    },
                )
            )
            continue

        proposed_driver = _text(finding.get("proposed_driver_field"))
        allowed = set(AGENT_PROPOSABLE_ASSUMPTION_FIELDS)
        allowed.intersection_update(profile.allowed_assumption_fields)
        finding_metadata = finding.get("metadata")
        if (
            proposed_driver
            and proposed_driver in profile.allowed_assumption_fields
            and isinstance(finding_metadata, Mapping)
            and finding_metadata.get("derived_from_claim_ledger") is True
            and get_assumption_definition(proposed_driver).owner
            == AssumptionOwner.reconciled
        ):
            allowed.add(proposed_driver)
        if require_mutation_driver and (not proposed_driver or proposed_driver not in allowed):
            items.append(
                PMDecisionQueueItem(
                    ticker=ticker,
                    profile_name=resolved_profile,
                    item_type=PMDecisionQueueItemType.advisory_finding,
                    status="pending",
                    title=_queue_title(finding),
                    summary=_text(finding.get("claim")) or None,
                    evidence_anchor_ids=anchors,
                    evidence_packet_ids=[str(evidence_packet_id)],
                    agent_confidence=confidence,
                    translator_confidence=QueueConfidence.medium,
                    metadata={
                        **metadata,
                        "queue_reason": "driver_not_proposable_or_missing",
                    },
                )
            )
            continue

        proposal = _build_target_proposal(finding, assumption_name=proposed_driver)
        if proposal is None:
            # Candidate without a numeric target stays advisory; do not invent deltas.
            items.append(
                PMDecisionQueueItem(
                    ticker=ticker,
                    profile_name=resolved_profile,
                    item_type=PMDecisionQueueItemType.advisory_finding,
                    status="pending",
                    title=_queue_title(finding),
                    summary=_text(finding.get("claim")) or None,
                    evidence_anchor_ids=anchors,
                    evidence_packet_ids=[str(evidence_packet_id)],
                    agent_confidence=confidence,
                    translator_confidence=QueueConfidence.medium,
                    metadata={
                        **metadata,
                        "queue_reason": "missing_proposed_value",
                    },
                )
            )
            continue

        pack = AssumptionChangePack(
            pack_id=f"pack:accounting:{entry.finding_id}",
            proposals=[proposal],
            notes={
                "ledger_entry_id": entry.entry_id,
                "fingerprint": entry.fingerprint,
                "valuation_treatment": treatment,
            },
        )
        items.append(
            PMDecisionQueueItem(
                ticker=ticker,
                profile_name=resolved_profile,
                item_type=PMDecisionQueueItemType.assumption_change_pack,
                status="pending",
                title=_queue_title(finding),
                summary=_text(finding.get("claim")) or None,
                evidence_anchor_ids=anchors,
                evidence_packet_ids=[str(evidence_packet_id)],
                proposal_pack=pack,
                agent_confidence=confidence,
                translator_confidence=QueueConfidence.high,
                metadata=metadata,
            )
        )

    return items


def translate_accounting_findings_to_queue_items(
    *,
    ticker: str,
    findings: list[Mapping[str, Any] | Any],
    evidence_packet_id: int | str,
    profile_name: str | None = None,
    rejected_findings: list[Mapping[str, Any] | Any] | None = None,
) -> tuple[AccountingAdjustmentLedger, list[PMDecisionQueueItem]]:
    """Convenience: merge then translate in one deterministic step."""

    ledger = merge_findings_into_ledger(
        ticker=ticker,
        findings=findings,
        rejected_findings=rejected_findings,
    )
    items = translate_accounting_ledger_to_queue_items(
        ledger,
        ticker=ticker,
        profile_name=profile_name,
        evidence_packet_id=evidence_packet_id,
    )
    return ledger, items


__all__ = [
    "ACCOUNTING_LEDGER_CONTRACT_VERSION",
    "AccountingAdjustmentLedger",
    "AccountingLedgerEntry",
    "AccountingLedgerStatus",
    "conflict_group_key",
    "finding_fingerprint",
    "merge_findings_into_ledger",
    "translate_accounting_findings_to_queue_items",
    "translate_accounting_ledger_to_queue_items",
]
