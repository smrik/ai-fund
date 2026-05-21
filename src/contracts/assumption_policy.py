from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


ASSUMPTION_POLICY_CONTRACT_VERSION = "1.0.0"


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PendingAssumptionStatus(str, Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"
    deferred = "deferred"
    superseded = "superseded"


class PendingAssumptionSourceType(str, Enum):
    agent = "agent"
    pm = "pm"
    policy = "policy"
    damodaran = "damodaran"
    migration = "migration"


class ValuationPolicyGlobalDefaults(ContractModel):
    risk_free_rate: float = Field(default=0.045, ge=0.0, le=0.20)
    equity_risk_premium: float = Field(default=0.05, ge=0.0, le=0.20)


class SectorDefaultPolicy(ContractModel):
    sector: str
    defaults: dict[str, float] = Field(default_factory=dict)

    @field_validator("sector")
    @classmethod
    def _clean_sector(cls, value: str) -> str:
        return str(value).strip() or "_default"


class ValuationPolicy(ContractModel):
    contract_version: str = ASSUMPTION_POLICY_CONTRACT_VERSION
    policy_id: int | None = None
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    actor: str = "system"
    global_defaults: ValuationPolicyGlobalDefaults = Field(default_factory=ValuationPolicyGlobalDefaults)
    sector_defaults: dict[str, dict[str, float]] = Field(default_factory=dict)
    source_ref: str | None = None
    notes: str | None = None


class ValuationPolicyPreview(ContractModel):
    current_policy: ValuationPolicy
    proposed_policy: ValuationPolicy
    changed_fields: dict[str, dict[str, Any]] = Field(default_factory=dict)


class DamodaranPolicyDraft(ContractModel):
    draft_id: int | None = None
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    source_file: str
    source_kind: str
    row_key: str
    field: str
    value: float
    unit: str | None = None
    source_date: str | None = None
    status: Literal["draft", "accepted", "rejected"] = "draft"
    raw: dict[str, Any] = Field(default_factory=dict)


class PendingAssumptionChange(ContractModel):
    change_id: int | None = None
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str | None = None
    ticker: str
    assumption_name: str
    current_value: float | None = None
    proposed_value: float
    source_type: PendingAssumptionSourceType = PendingAssumptionSourceType.agent
    source_ref: str
    confidence: str | None = None
    rationale: str | None = None
    citation: str | None = None
    status: PendingAssumptionStatus = PendingAssumptionStatus.pending
    approval_ref: str | None = None
    applied_at: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("ticker")
    @classmethod
    def _uppercase_ticker(cls, value: str) -> str:
        return str(value).upper().strip()

    @field_validator("assumption_name", "source_ref")
    @classmethod
    def _strip_required(cls, value: str) -> str:
        cleaned = str(value).strip()
        if not cleaned:
            raise ValueError("field is required")
        return cleaned




class QoEProposalStatus(str, Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"


class QoEProposal(ContractModel):
    ticker: str
    ebit_adjustment_pct: float = Field(ge=-0.20, le=0.20)
    normalized_ebit: float
    confidence: float = Field(ge=0.0, le=1.0)
    rationale_bullets: list[str] = Field(min_length=1)
    evidence_refs: list[str] = Field(min_length=1)
    status: QoEProposalStatus = QoEProposalStatus.pending

    @field_validator("ticker")
    @classmethod
    def _uppercase_qoe_ticker(cls, value: str) -> str:
        return str(value).upper().strip()

    @field_validator("rationale_bullets", "evidence_refs")
    @classmethod
    def _strip_non_empty_items(cls, values: list[str]) -> list[str]:
        cleaned = [str(v).strip() for v in values if str(v).strip()]
        if not cleaned:
            raise ValueError("at least one non-empty value is required")
        return cleaned


def qoe_proposal_to_api_payload(proposal: QoEProposal) -> dict[str, Any]:
    return proposal.model_dump()


def qoe_proposal_to_pending_change_payload(proposal: QoEProposal) -> dict[str, Any]:
    return {
        "ticker": proposal.ticker,
        "assumption_name": "ebit_margin_start",
        "proposed_value": proposal.normalized_ebit,
        "source_type": PendingAssumptionSourceType.agent.value,
        "source_ref": "qoe",
        "confidence": f"{proposal.confidence:.2f}",
        "rationale": " | ".join(proposal.rationale_bullets),
        "citation": "; ".join(proposal.evidence_refs),
        "status": proposal.status.value,
        "metadata": {
            "qoe_proposal": proposal.model_dump(),
            "ebit_adjustment_pct": proposal.ebit_adjustment_pct,
        },
    }


class PendingAssumptionStackPreview(ContractModel):
    ticker: str
    selected_change_ids: list[int] = Field(default_factory=list)
    current_iv: dict[str, float | None] = Field(default_factory=dict)
    proposed_iv: dict[str, float | None] = Field(default_factory=dict)
    delta_pct: dict[str, float | None] = Field(default_factory=dict)
    resolved_values: dict[str, dict[str, Any]] = Field(default_factory=dict)
    conflicts: list[dict[str, Any]] = Field(default_factory=list)

    @field_validator("ticker")
    @classmethod
    def _uppercase_preview_ticker(cls, value: str) -> str:
        return str(value).upper().strip()
