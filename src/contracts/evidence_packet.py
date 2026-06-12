from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import Field, field_validator, model_validator

from src.contracts.assumption_policy import ContractModel


EVIDENCE_PACKET_CONTRACT_VERSION = "1.0.0"


class EvidencePacketKind(str, Enum):
    earnings_update = "earnings_update"
    company_analysis = "company_analysis"
    industry_analysis = "industry_analysis"
    comps_analysis = "comps_analysis"
    risk_review = "risk_review"
    valuation_review = "valuation_review"
    analyst_prep_synthesis = "analyst_prep_synthesis"


class EvidencePacketObservationKind(str, Enum):
    qualitative = "qualitative"
    numeric = "numeric"


class EvidenceImportance(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"


class EvidenceConfidence(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"


class EvidenceSourceQuality(str, Enum):
    real = "real"
    partial = "partial"
    placeholder = "placeholder"


class EvidenceSourceRef(ContractModel):
    source_ref_id: str
    source_kind: str
    source_label: str
    source_locator: str
    captured_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("source_ref_id", "source_kind", "source_label", "source_locator")
    @classmethod
    def _strip_required(cls, value: str) -> str:
        cleaned = str(value).strip()
        if not cleaned:
            raise ValueError("field is required")
        return cleaned


class TextEvidenceSnippet(ContractModel):
    snippet_id: str
    source_ref_id: str
    text: str
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("snippet_id", "source_ref_id", "text")
    @classmethod
    def _strip_required(cls, value: str) -> str:
        cleaned = str(value).strip()
        if not cleaned:
            raise ValueError("field is required")
        return cleaned


class EvidencePacketFact(ContractModel):
    fact_id: str
    fact_name: str
    value: Any
    unit: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("fact_id", "fact_name")
    @classmethod
    def _strip_required(cls, value: str) -> str:
        cleaned = str(value).strip()
        if not cleaned:
            raise ValueError("field is required")
        return cleaned


class EvidencePacketObservation(ContractModel):
    observation_id: str
    observation_kind: EvidencePacketObservationKind
    observation_type: str
    claim: str
    evidence_anchor_ids: list[str] = Field(min_length=1)
    text_snippet_ids: list[str] = Field(default_factory=list)
    direction: str | None = None
    qualitative_importance: EvidenceImportance | None = None
    agent_confidence: EvidenceConfidence | None = None
    materiality: EvidenceImportance | None = None
    thesis_implication: str | None = None
    driver_implication: str | None = None
    evidence_rationale: str | None = None
    pm_question: str | None = None
    what_would_change_mind: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("observation_id", "observation_type", "claim")
    @classmethod
    def _strip_required(cls, value: str) -> str:
        cleaned = str(value).strip()
        if not cleaned:
            raise ValueError("field is required")
        return cleaned

    @model_validator(mode="after")
    def _qualitative_requires_text_snippet(self) -> "EvidencePacketObservation":
        if self.observation_kind == EvidencePacketObservationKind.qualitative and not self.text_snippet_ids:
            raise ValueError("qualitative observations require at least one text_snippet_id")
        return self


class EvidencePacket(ContractModel):
    contract_version: str = EVIDENCE_PACKET_CONTRACT_VERSION
    packet_id: int | None = None
    ticker: str
    profile_name: str
    packet_kind: EvidencePacketKind
    bundle_id: str | None = None
    generated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    source_refs: list[EvidenceSourceRef] = Field(default_factory=list)
    facts: list[EvidencePacketFact] = Field(default_factory=list)
    snippets: list[TextEvidenceSnippet] = Field(default_factory=list)
    observations: list[EvidencePacketObservation] = Field(default_factory=list)
    run_metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("ticker")
    @classmethod
    def _uppercase_ticker(cls, value: str) -> str:
        return str(value).upper().strip()

    @field_validator("profile_name")
    @classmethod
    def _strip_profile(cls, value: str) -> str:
        cleaned = str(value).strip()
        if not cleaned:
            raise ValueError("profile_name is required")
        return cleaned
