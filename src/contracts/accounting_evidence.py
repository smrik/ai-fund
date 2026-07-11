"""Typed contracts for focused accounting evidence and repair artifacts.

These models describe what an accounting judgment call saw and returned.  They
do not decide materiality, adjustment direction, or whether a proposed driver
is semantically aligned; those are deterministic validation concerns outside
this contract module.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
from typing import Any

from pydantic import Field, field_validator, model_validator

from src.contracts.assumption_policy import ContractModel
from src.contracts.evidence_packet import (
    EvidencePacket,
    EvidencePacketFact,
    EvidencePacketKind,
    EvidenceSourceRef,
    TextEvidenceSnippet,
)


ACCOUNTING_EVIDENCE_CONTRACT_VERSION = "0.1.0"


class AccountingTopic(str, Enum):
    """The bounded topic partitions used for focused accounting calls."""

    qoe = "qoe"
    ev_equity_bridge = "ev_equity_bridge"
    contingencies_and_taxes = "contingencies_and_taxes"
    segments_and_disclosure = "segments_and_disclosure"


class AccountingFocusKey(str, Enum):
    """Stable reasoning-level dispatch keys under the four parent topics."""

    qoe_revenue = "qoe_revenue"
    qoe_opex_and_compensation = "qoe_opex_and_compensation"
    qoe_nonrecurring = "qoe_nonrecurring"
    qoe_cash_conversion = "qoe_cash_conversion"
    bridge_cash_debt_investments = "bridge_cash_debt_investments"
    bridge_leases_pensions_claims = "bridge_leases_pensions_claims"
    tax_contingencies = "tax_contingencies"
    segments_disclosure = "segments_disclosure"


ACCOUNTING_FOCUS_TO_TOPIC: dict[AccountingFocusKey, AccountingTopic] = {
    AccountingFocusKey.qoe_revenue: AccountingTopic.qoe,
    AccountingFocusKey.qoe_opex_and_compensation: AccountingTopic.qoe,
    AccountingFocusKey.qoe_nonrecurring: AccountingTopic.qoe,
    AccountingFocusKey.qoe_cash_conversion: AccountingTopic.qoe,
    AccountingFocusKey.bridge_cash_debt_investments: AccountingTopic.ev_equity_bridge,
    AccountingFocusKey.bridge_leases_pensions_claims: AccountingTopic.ev_equity_bridge,
    AccountingFocusKey.tax_contingencies: AccountingTopic.contingencies_and_taxes,
    AccountingFocusKey.segments_disclosure: AccountingTopic.segments_and_disclosure,
}

ACCOUNTING_FOCUS_KEYS: tuple[AccountingFocusKey, ...] = tuple(ACCOUNTING_FOCUS_TO_TOPIC)

# Backward-compatible defaults for callers that still construct a parent-topic
# finding. Focused dispatch callers should always provide the narrower key.
_DEFAULT_FOCUS_FOR_TOPIC = {
    AccountingTopic.qoe: AccountingFocusKey.qoe_revenue,
    AccountingTopic.ev_equity_bridge: AccountingFocusKey.bridge_cash_debt_investments,
    AccountingTopic.contingencies_and_taxes: AccountingFocusKey.tax_contingencies,
    AccountingTopic.segments_and_disclosure: AccountingFocusKey.segments_disclosure,
}


class AccountingFindingStatus(str, Enum):
    candidate = "candidate"
    no_adjustment_identified = "no_adjustment_identified"
    missing_evidence = "missing_evidence"


class BookedOrDisclosedStatus(str, Enum):
    booked = "booked"
    disclosed_not_booked = "disclosed_not_booked"
    unclear = "unclear"
    not_applicable = "not_applicable"


class AccountingTreatment(str, Enum):
    """A proposed accounting interpretation, without prescribing direction."""

    no_adjustment = "no_adjustment"
    normalize = "normalize"
    reclassify = "reclassify"
    bridge_adjustment = "bridge_adjustment"
    scenario_only = "scenario_only"
    disclosure_only = "disclosure_only"
    unclear = "unclear"


class ValuationTreatment(str, Enum):
    normalized_ebit = "normalized_ebit"
    ev_equity_bridge = "ev_equity_bridge"
    scenario_only = "scenario_only"
    disclosure_only = "disclosure_only"
    none = "none"


class RepairStatus(str, Enum):
    original_valid = "original_valid"
    repaired = "repaired"
    rejected_after_repair = "rejected_after_repair"


class AccountingPacketStatus(str, Enum):
    complete = "complete"
    partial = "partial"
    missing_evidence = "missing_evidence"
    unavailable = "unavailable"


class AccountingEvidenceAnchor(ContractModel):
    anchor_id: str
    source_ref: str | None = None
    locator: str | None = None
    citation_text: str
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("anchor_id", "citation_text")
    @classmethod
    def _required_text(cls, value: str) -> str:
        cleaned = str(value).strip()
        if not cleaned:
            raise ValueError("field is required")
        return cleaned


class AccountingSourceFact(ContractModel):
    fact_id: str
    fact_name: str
    value: Any
    unit: str | None = None
    currency: str | None = None
    period: str | None = None
    evidence_anchor_ids: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("fact_id", "fact_name")
    @classmethod
    def _required_text(cls, value: str) -> str:
        cleaned = str(value).strip()
        if not cleaned:
            raise ValueError("field is required")
        return cleaned


class FocusedAccountingEvidencePacket(ContractModel):
    contract_version: str = ACCOUNTING_EVIDENCE_CONTRACT_VERSION
    packet_id: str
    ticker: str
    topic: AccountingTopic
    generated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    base_packet_id: int | None = None
    source_refs: list[EvidenceSourceRef] = Field(default_factory=list)
    facts: list[AccountingSourceFact] = Field(default_factory=list)
    evidence_anchors: list[AccountingEvidenceAnchor] = Field(default_factory=list)
    snippets: list[TextEvidenceSnippet] = Field(default_factory=list)
    allowed_driver_fields: list[str] = Field(default_factory=list)
    current_model_fields: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("packet_id")
    @classmethod
    def _packet_id_required(cls, value: str) -> str:
        cleaned = str(value).strip()
        if not cleaned:
            raise ValueError("packet_id is required")
        return cleaned

    @field_validator("ticker")
    @classmethod
    def _uppercase_ticker(cls, value: str) -> str:
        cleaned = str(value).upper().strip()
        if not cleaned:
            raise ValueError("ticker is required")
        return cleaned

    def as_evidence_packet(self) -> EvidencePacket:
        """Compose the focused view into the repository's persisted packet shape."""

        return EvidencePacket(
            packet_id=self.base_packet_id,
            ticker=self.ticker,
            profile_name=f"accounting:{self.topic.value}",
            packet_kind=EvidencePacketKind.accounting,
            generated_at=self.generated_at,
            source_refs=self.source_refs,
            facts=[
                EvidencePacketFact(
                    fact_id=fact.fact_id,
                    fact_name=fact.fact_name,
                    value=fact.value,
                    unit=fact.unit,
                    metadata={
                        **fact.metadata,
                        "currency": fact.currency,
                        "period": fact.period,
                        "evidence_anchor_ids": fact.evidence_anchor_ids,
                    },
                )
                for fact in self.facts
            ],
            snippets=self.snippets,
            run_metadata={
                **self.metadata,
                "accounting_topic": self.topic.value,
                "allowed_driver_fields": self.allowed_driver_fields,
                "evidence_anchor_count": len(self.evidence_anchors),
            },
        )


class AccountingFinding(ContractModel):
    finding_id: str | None = None
    topic: AccountingTopic
    focus_key: AccountingFocusKey | None = None
    finding_status: AccountingFindingStatus
    finding_type: str
    line_item: str
    claim: str
    claim_driver_field: str | None = None
    proposed_driver_field: str | None = None
    direction: str | None = None
    reported_value: Any = None
    proposed_value: Any = None
    currency: str | None = None
    period: str | None = None
    booked_or_disclosed_status: BookedOrDisclosedStatus = BookedOrDisclosedStatus.unclear
    accounting_treatment: AccountingTreatment = AccountingTreatment.unclear
    valuation_treatment: ValuationTreatment = ValuationTreatment.none
    cash_impact: Any = None
    tax_impact: Any = None
    timing: str | None = None
    materiality_rationale: str | None = None
    evidence_anchor_ids: list[str] = Field(default_factory=list)
    citation_text: str | None = None
    confidence: str | None = None
    pm_question: str | None = None
    what_would_change_mind: str | None = None
    no_adjustment_reason: str | None = None
    missing_evidence_reason: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("finding_type", "line_item", "claim")
    @classmethod
    def _required_text(cls, value: str) -> str:
        cleaned = str(value).strip()
        if not cleaned:
            raise ValueError("field is required")
        return cleaned

    @model_validator(mode="after")
    def _state_explanations(self) -> "AccountingFinding":
        if self.focus_key is None:
            self.focus_key = _DEFAULT_FOCUS_FOR_TOPIC[self.topic]
        elif ACCOUNTING_FOCUS_TO_TOPIC[self.focus_key] != self.topic:
            raise ValueError(
                f"focus_key {self.focus_key.value!r} does not belong to topic {self.topic.value!r}"
            )
        if self.finding_id is None:
            identity = self.model_dump(mode="json", exclude={"finding_id"})
            canonical = json.dumps(identity, sort_keys=True, separators=(",", ":"))
            self.finding_id = "finding:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
        if self.finding_status == AccountingFindingStatus.candidate and not self.evidence_anchor_ids:
            raise ValueError("candidate findings require evidence_anchor_ids")
        if self.finding_status == AccountingFindingStatus.no_adjustment_identified and not (
            self.no_adjustment_reason or self.materiality_rationale
        ):
            raise ValueError("no_adjustment_identified findings require a reason")
        if self.finding_status == AccountingFindingStatus.missing_evidence and not self.missing_evidence_reason:
            raise ValueError("missing_evidence findings require missing_evidence_reason")
        return self


class AccountingFocusResponse(ContractModel):
    """Agent-facing envelope for one focus, including empty outcomes."""

    focus_key: AccountingFocusKey
    packet_status: AccountingPacketStatus
    findings: list[AccountingFinding] = Field(default_factory=list)
    coverage_notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _findings_match_focus(self) -> "AccountingFocusResponse":
        parent_topic = ACCOUNTING_FOCUS_TO_TOPIC[self.focus_key]
        for finding in self.findings:
            if finding.focus_key != self.focus_key:
                raise ValueError(
                    f"finding {finding.finding_id!r} focus_key does not match response focus_key"
                )
            if finding.topic != parent_topic:
                raise ValueError(
                    f"finding {finding.finding_id!r} topic does not match response focus_key"
                )
        if self.packet_status == AccountingPacketStatus.missing_evidence and not self.coverage_notes:
            raise ValueError("missing_evidence responses require coverage_notes")
        return self


class AccountingValidationIssue(ContractModel):
    code: str
    message: str
    field: str | None = None
    severity: str = "error"
    metadata: dict[str, Any] = Field(default_factory=dict)


class AccountingRepairAttempt(ContractModel):
    attempt_number: int = Field(ge=1)
    raw_output: Any
    validation_issues: list[AccountingValidationIssue] = Field(default_factory=list)
    repair_prompt: str | None = None
    parsed_finding: AccountingFinding | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class AccountingRepairResult(ContractModel):
    status: RepairStatus
    finding: AccountingFinding | None = None
    attempts: list[AccountingRepairAttempt] = Field(min_length=1)
    final_issues: list[AccountingValidationIssue] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _result_matches_status(self) -> "AccountingRepairResult":
        if self.status in {RepairStatus.repaired, RepairStatus.original_valid} and self.finding is None:
            raise ValueError("successful repair results require finding")
        if self.status == RepairStatus.rejected_after_repair and self.finding is not None:
            raise ValueError("rejected_after_repair results must not contain finding")
        return self


# Short aliases keep the contract vocabulary convenient for callers without
# creating a second model or changing the serialized schema.
FocusedAccountingPacket = FocusedAccountingEvidencePacket
FindingStatus = AccountingFindingStatus
ValidationIssue = AccountingValidationIssue
RepairAttempt = AccountingRepairAttempt
RepairResult = AccountingRepairResult


__all__ = [
    "ACCOUNTING_EVIDENCE_CONTRACT_VERSION",
    "AccountingEvidenceAnchor",
    "AccountingFinding",
    "AccountingFindingStatus",
    "AccountingFocusKey",
    "ACCOUNTING_FOCUS_KEYS",
    "ACCOUNTING_FOCUS_TO_TOPIC",
    "AccountingFocusResponse",
    "AccountingPacketStatus",
    "AccountingSourceFact",
    "AccountingTopic",
    "AccountingTreatment",
    "AccountingValidationIssue",
    "BookedOrDisclosedStatus",
    "FocusedAccountingEvidencePacket",
    "RepairStatus",
    "AccountingRepairAttempt",
    "AccountingRepairResult",
    "ValuationTreatment",
    "FindingStatus",
    "FocusedAccountingPacket",
    "ValidationIssue",
    "RepairAttempt",
    "RepairResult",
]
