from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
import math
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from src.contracts.assumption_registry import (
    AssumptionOwner,
    AssumptionUnit,
    ApplicabilityRule,
    DriverFamily,
    ScenarioDirection,
    get_assumption_definition,
    judgment_owned_fields,
)
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
    superseded = "superseded"


class ProposalMode(str, Enum):
    delta = "delta"
    target = "target"
    scenarios = "scenarios"


class QualitativeImportance(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"


class QueueConfidence(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"


class ScenarioAssumptionValues(ContractModel):
    low: float
    base: float
    high: float

    @field_validator("low", "base", "high", mode="before")
    @classmethod
    def _require_finite_json_number(cls, value: Any) -> Any:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("scenario values must be JSON numbers")
        if not math.isfinite(float(value)):
            raise ValueError("scenario values must be finite")
        return value


class AssumptionChangeProposal(ContractModel):
    assumption_name: str
    proposal_mode: ProposalMode
    applicability: Literal["applicable", "not_applicable"] = "applicable"
    proposed_delta: float | None = None
    proposed_target_value: float | None = None
    scenario_values: ScenarioAssumptionValues | None = None
    unit: AssumptionUnit | None = None
    horizon_years: int | None = Field(default=None, ge=1, le=30)
    evidence_anchor_ids: list[str] = Field(default_factory=list)
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
            if (
                self.proposed_delta is None
                or self.proposed_target_value is not None
                or self.scenario_values is not None
            ):
                raise ValueError(
                    "delta mode requires proposed_delta and forbids target/scenario values"
                )
        if self.proposal_mode == ProposalMode.target:
            if (
                self.proposed_target_value is None
                or self.proposed_delta is not None
                or self.scenario_values is not None
            ):
                raise ValueError(
                    "target mode requires proposed_target_value and forbids delta/scenario values"
                )
        if self.proposal_mode == ProposalMode.scenarios:
            if self.proposed_delta is not None or self.proposed_target_value is not None:
                raise ValueError(
                    "scenarios mode forbids delta/target values"
                )
            if self.applicability == "applicable" and self.scenario_values is None:
                raise ValueError("applicable scenario proposals require scenario_values")
            if (
                self.applicability == "not_applicable"
                and self.scenario_values is not None
            ):
                raise ValueError(
                    "not_applicable scenario proposals must not contain values"
                )
            if self.unit is None or self.horizon_years is None:
                raise ValueError("scenarios mode requires unit and horizon_years")
            if not self.evidence_anchor_ids:
                raise ValueError("scenarios mode requires evidence_anchor_ids")
            definition = get_assumption_definition(self.assumption_name)
            if definition.name != self.assumption_name:
                raise ValueError(
                    f"use canonical assumption name {definition.name!r}"
                )
            if definition.owner != AssumptionOwner.judgment:
                raise ValueError(
                    f"{self.assumption_name} is not judgment-owned"
                )
            if definition.unit != self.unit:
                raise ValueError(
                    f"{self.assumption_name} requires unit {definition.unit.value}"
                )
            if (
                self.applicability == "not_applicable"
                and definition.applicability != ApplicabilityRule.conditional
            ):
                raise ValueError(
                    f"{self.assumption_name} cannot be marked not_applicable"
                )
            if self.scenario_values is None:
                return self
            values = (
                self.scenario_values.low,
                self.scenario_values.base,
                self.scenario_values.high,
            )
            if (
                definition.scenario_direction == ScenarioDirection.ascending
                and not values[0] <= values[1] <= values[2]
            ):
                raise ValueError(
                    f"{self.assumption_name} scenarios must ascend"
                )
            if (
                definition.scenario_direction == ScenarioDirection.descending
                and not values[0] >= values[1] >= values[2]
            ):
                raise ValueError(
                    f"{self.assumption_name} scenarios must descend"
                )
        return self


class AssumptionChangePack(ContractModel):
    pack_id: str
    proposals: list[AssumptionChangeProposal] = Field(min_length=1)
    proposal_scope: str = "base_case"
    family: DriverFamily | None = None
    analysis_snapshot_hash: str | None = None
    primary_run_id: str | None = None
    critic_run_id: str | None = None
    critic_verdict: Literal["accept", "revise", "block"] | None = None
    notes: dict[str, Any] = Field(default_factory=dict)

    @field_validator("pack_id")
    @classmethod
    def _strip_pack_id(cls, value: str) -> str:
        cleaned = str(value).strip()
        if not cleaned:
            raise ValueError("pack_id is required")
        return cleaned

    @model_validator(mode="after")
    def _validate_atomic_family_pack(self) -> "AssumptionChangePack":
        if self.family is None:
            return self
        for field_name in (
            "analysis_snapshot_hash",
            "primary_run_id",
            "critic_run_id",
            "critic_verdict",
        ):
            if not getattr(self, field_name):
                raise ValueError(
                    f"driver family packs require {field_name}"
                )
        if any(
            proposal.proposal_mode != ProposalMode.scenarios
            for proposal in self.proposals
        ):
            raise ValueError(
                "driver family packs may contain only scenario proposals"
            )
        names = [proposal.assumption_name for proposal in self.proposals]
        if len(set(names)) != len(names):
            raise ValueError("driver family packs contain duplicate assumptions")
        expected = set(judgment_owned_fields(self.family))
        if set(names) != expected:
            raise ValueError(
                "driver family pack must be atomic and complete; "
                f"missing={sorted(expected - set(names))}, "
                f"unexpected={sorted(set(names) - expected)}"
            )
        return self


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
