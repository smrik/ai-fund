from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from src.contracts.assumption_policy import ContractModel


ANALYST_PREP_CONTRACT_VERSION = "0.1.0"

ANALYST_PREP_DRIVER_FIELD_WHITELIST = {
    "revenue_growth_near",
    "revenue_growth_mid",
    "ebit_margin_start",
    "ebit_margin_target",
    "wacc",
    "terminal_growth",
    "exit_multiple",
    "revenue_growth_terminal",
}

SourceQuality = Literal["real", "partial", "placeholder", "missing"]
ReviewStatus = Literal["ok", "review_required", "missing", "conflict"]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class MissingDataFlag(ContractModel):
    flag_id: str
    label: str
    severity: Literal["low", "medium", "high"] = "medium"
    reason: str
    suggested_check: str | None = None
    source: str | None = None


class AnalystPrepSection(ContractModel):
    section_id: str
    title: str
    summary: str
    source_quality: SourceQuality = "partial"
    evidence_anchor_ids: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ThesisBridgeCard(ContractModel):
    card_id: str
    title: str
    claim: str
    business_evidence_summary: str
    model_implication: str
    linked_assumption_fields: list[str] = Field(default_factory=list)
    evidence_anchor_ids: list[str] = Field(min_length=1)
    numeric_fact_refs: list[str] = Field(default_factory=list)
    source_quality: SourceQuality = "partial"
    agent_confidence: str | None = None
    deterministic_confidence: str | None = None
    counter_evidence: str | None = None
    what_would_change_mind: str | None = None

    @field_validator("linked_assumption_fields")
    @classmethod
    def _fields_are_whitelisted(cls, values: list[str]) -> list[str]:
        cleaned = [str(value).strip() for value in values if str(value).strip()]
        invalid = sorted(set(cleaned) - ANALYST_PREP_DRIVER_FIELD_WHITELIST)
        if invalid:
            raise ValueError(f"unsupported linked assumption fields: {', '.join(invalid)}")
        return cleaned

    @model_validator(mode="after")
    def _numeric_claims_need_fact_refs(self) -> "ThesisBridgeCard":
        text = " ".join([self.claim, self.business_evidence_summary, self.model_implication])
        has_digit = any(char.isdigit() for char in text)
        if has_digit and not self.numeric_fact_refs:
            raise ValueError("numeric thesis claims require numeric_fact_refs")
        return self


class ModelDriverBridgeCard(ContractModel):
    assumption_name: str
    label: str
    current_value: float | None = None
    proposed_or_effective_value: float | None = None
    source: str | None = None
    rationale: str
    valuation_impact: dict[str, Any] | None = None
    evidence_anchor_ids: list[str] = Field(default_factory=list)
    pm_review_status: ReviewStatus = "ok"

    @field_validator("assumption_name")
    @classmethod
    def _assumption_is_whitelisted(cls, value: str) -> str:
        cleaned = str(value).strip()
        if cleaned not in ANALYST_PREP_DRIVER_FIELD_WHITELIST:
            raise ValueError(f"unsupported model driver field: {cleaned}")
        return cleaned


class CompsJudgmentCard(ContractModel):
    title: str = "Comps Judgment"
    peer_set_quality: SourceQuality = "missing"
    peer_count: int | None = None
    primary_metric: str | None = None
    target_vs_peer_median: dict[str, Any] = Field(default_factory=dict)
    premium_discount_argument: str | None = None
    exit_multiple_support: str | None = None
    warnings: list[str] = Field(default_factory=list)
    evidence_anchor_ids: list[str] = Field(default_factory=list)


class SegmentDriverRow(ContractModel):
    segment: str
    revenue_growth: float | None = None
    margin: float | None = None
    revenue_mix: float | None = None
    source_ref: str | None = None
    quality: Literal["real", "partial", "missing"] = "missing"


class AnalystPrepPack(ContractModel):
    contract_version: str = ANALYST_PREP_CONTRACT_VERSION
    ticker: str
    generated_at: str = Field(default_factory=_now)
    source_quality: SourceQuality = "partial"
    sections: list[AnalystPrepSection] = Field(default_factory=list)
    thesis_cards: list[ThesisBridgeCard] = Field(default_factory=list)
    driver_cards: list[ModelDriverBridgeCard] = Field(default_factory=list)
    comps_card: CompsJudgmentCard | None = None
    missing_data: list[MissingDataFlag] = Field(default_factory=list)
    segment_driver_rows: list[SegmentDriverRow] = Field(default_factory=list)
    evidence_packet_ids: list[int] = Field(default_factory=list)
    evidence_map: list[dict[str, Any]] = Field(default_factory=list)
    conflict_groups: list[dict[str, Any]] = Field(default_factory=list)
    export_metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("ticker")
    @classmethod
    def _uppercase_ticker(cls, value: str) -> str:
        cleaned = str(value).upper().strip()
        if not cleaned:
            raise ValueError("ticker is required")
        return cleaned
