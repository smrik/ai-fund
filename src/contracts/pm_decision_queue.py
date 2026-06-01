from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import Field, field_validator, model_validator

from src.contracts.assumption_policy import ContractModel


PM_DECISION_QUEUE_CONTRACT_VERSION = "1.0.0"


class PMDecisionQueueItemType(str, Enum):
    advisory_finding = "advisory_finding"
    assumption_change_pack = "assumption_change_pack"


class PMDecisionQueueStatus(str, Enum):
    pending = "pending"
    previewed = "previewed"
    approved = "approved"
    rejected = "rejected"
    deferred = "deferred"


class ProposalMode(str, Enum):
    delta = "delta"
    target = "target"


class QualitativeImportance(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"


class QueueConfidence(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"


class AssumptionChangeProposal(ContractModel):
    assumption_name: str
    proposal_mode: ProposalMode
    proposed_delta: float | None = None
    proposed_target_value: float | None = None
    rationale: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("assumption_name")
    @classmethod
    def _strip_assumption_name(cls, value: str) -> str:
        cleaned = str(value).strip()
        if not cleaned:
            raise ValueError("assumption_name is required")
        return cleaned

    @model_validator(mode="after")
    def _validate_mode_values(self) -> "AssumptionChangeProposal":
        if self.proposal_mode == ProposalMode.delta:
            if self.proposed_delta is None or self.proposed_target_value is not None:
                raise ValueError("delta mode requires proposed_delta and forbids proposed_target_value")
        if self.proposal_mode == ProposalMode.target:
            if self.proposed_target_value is None or self.proposed_delta is not None:
                raise ValueError("target mode requires proposed_target_value and forbids proposed_delta")
        return self


class AssumptionChangePack(ContractModel):
    pack_id: str
    proposals: list[AssumptionChangeProposal] = Field(min_length=1)
    proposal_scope: str = "base_case"
    notes: dict[str, Any] = Field(default_factory=dict)

    @field_validator("pack_id")
    @classmethod
    def _strip_pack_id(cls, value: str) -> str:
        cleaned = str(value).strip()
        if not cleaned:
            raise ValueError("pack_id is required")
        return cleaned


class PMDecisionQueueItem(ContractModel):
    contract_version: str = PM_DECISION_QUEUE_CONTRACT_VERSION
    item_id: int | None = None
    ticker: str
    profile_name: str
    item_type: PMDecisionQueueItemType
    status: PMDecisionQueueStatus = PMDecisionQueueStatus.pending
    title: str
    summary: str | None = None
    evidence_anchor_ids: list[str] = Field(min_length=1)
    evidence_packet_ids: list[str] = Field(default_factory=list)
    proposal_pack: AssumptionChangePack | None = None
    pm_edited_proposal_pack: AssumptionChangePack | None = None
    approved_proposal_pack: AssumptionChangePack | None = None
    qualitative_importance: QualitativeImportance | None = None
    agent_confidence: QueueConfidence | None = None
    translator_confidence: QueueConfidence | None = None
    pm_confidence: QueueConfidence | None = None
    valuation_impact: dict[str, Any] | None = None
    adapter_links: dict[str, Any] = Field(default_factory=dict)
    decision_history: list[dict[str, Any]] = Field(default_factory=list)
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("ticker")
    @classmethod
    def _uppercase_ticker(cls, value: str) -> str:
        return str(value).upper().strip()

    @field_validator("profile_name", "title")
    @classmethod
    def _strip_required(cls, value: str) -> str:
        cleaned = str(value).strip()
        if not cleaned:
            raise ValueError("field is required")
        return cleaned

    @model_validator(mode="after")
    def _validate_item_type_payload(self) -> "PMDecisionQueueItem":
        if self.item_type == PMDecisionQueueItemType.assumption_change_pack and self.proposal_pack is None:
            raise ValueError("assumption_change_pack items require proposal_pack")
        if self.item_type == PMDecisionQueueItemType.advisory_finding:
            if self.proposal_pack is not None:
                raise ValueError("advisory_finding items must not include proposal_pack")
            if self.pm_edited_proposal_pack is not None:
                raise ValueError("advisory_finding items must not include pm_edited_proposal_pack")
            if self.approved_proposal_pack is not None:
                raise ValueError("advisory_finding items must not include approved_proposal_pack")
        if self.metadata.get("observation_id") and not self.evidence_packet_ids:
            raise ValueError("observation-backed queue items require at least one evidence_packet_id")
        return self
