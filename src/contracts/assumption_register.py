from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


ASSUMPTION_REGISTER_CONTRACT_VERSION = "1.0.0"

ALLOWED_STAGES = frozenset({"input_assembly", "wacc", "dcf", "terminal_value"})
ALLOWED_SCOPES = frozenset({
    "growth",
    "margin",
    "tax",
    "working_capital",
    "reinvestment",
    "wacc",
    "terminal_value",
    "capital_structure",
})
ALLOWED_FORECAST_LINES = frozenset({
    "revenue",
    "ebit",
    "nopat",
    "fcff",
    "terminal_value",
    "enterprise_value",
    "equity_value",
})


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AssumptionEntityType(str, Enum):
    ticker = "ticker"
    sector = "sector"
    industry = "industry"
    global_ = "global"


class AssumptionOwner(str, Enum):
    deterministic = "deterministic"
    pm_override = "pm_override"
    system_flag = "system_flag"


class AssumptionApprovalState(str, Enum):
    none = "none"
    review_required = "review_required"
    pm_approved = "pm_approved"
    rejected = "rejected"
    stale_approval = "stale_approval"


class FlagLevel(str, Enum):
    none = "none"
    watch = "watch"
    review_required = "review_required"
    critical = "critical"


class AssumptionValueType(str, Enum):
    numeric = "numeric"


class ModelTrustState(str, Enum):
    clean = "clean"
    watch = "watch"
    review_required = "review_required"
    critical_review_required = "critical_review_required"


FLAG_SEVERITY: dict[FlagLevel, int] = {
    FlagLevel.none: 0,
    FlagLevel.watch: 1,
    FlagLevel.review_required: 2,
    FlagLevel.critical: 3,
}


class AssumptionRegisterEntry(ContractModel):
    entity_type: AssumptionEntityType
    entity_id: str
    ticker: str
    assumption_name: str
    scope: str
    stage: str
    value_type: AssumptionValueType = AssumptionValueType.numeric
    current_value: float
    accepted_low: float | None = None
    accepted_high: float | None = None
    range_rule_id: str
    range_rule_description: str
    source_lineage: dict[str, Any] = Field(default_factory=dict)
    affected_forecast_lines: list[str] = Field(default_factory=list)
    flag_level: FlagLevel = FlagLevel.none
    owner: AssumptionOwner = AssumptionOwner.deterministic
    approval_state: AssumptionApprovalState = AssumptionApprovalState.none
    approval_ref: str | None = None
    out_of_range: bool = False
    valuation_impact: dict[str, Any] | None = None
    evidence_refs: list[str] = Field(default_factory=list)
    advisory_refs: list[str] = Field(default_factory=list)
    notes: dict[str, Any] = Field(default_factory=dict)

    @field_validator("ticker", "entity_id")
    @classmethod
    def _uppercase_identifier(cls, value: str) -> str:
        return str(value).upper().strip()

    @field_validator("stage")
    @classmethod
    def _validate_stage(cls, value: str) -> str:
        if value not in ALLOWED_STAGES:
            raise ValueError(f"stage must be one of {sorted(ALLOWED_STAGES)}")
        return value

    @field_validator("scope")
    @classmethod
    def _validate_scope(cls, value: str) -> str:
        if value not in ALLOWED_SCOPES:
            raise ValueError(f"scope must be one of {sorted(ALLOWED_SCOPES)}")
        return value

    @field_validator("affected_forecast_lines")
    @classmethod
    def _validate_forecast_lines(cls, values: list[str]) -> list[str]:
        unknown = sorted(set(values) - ALLOWED_FORECAST_LINES)
        if unknown:
            raise ValueError(f"unknown affected_forecast_lines: {unknown}")
        return values

    @model_validator(mode="after")
    def _derive_out_of_range(self) -> "AssumptionRegisterEntry":
        if self.accepted_low is not None and self.current_value < self.accepted_low:
            object.__setattr__(self, "out_of_range", True)
        elif self.accepted_high is not None and self.current_value > self.accepted_high:
            object.__setattr__(self, "out_of_range", True)
        return self


class AssumptionRegister(ContractModel):
    contract_version: str = ASSUMPTION_REGISTER_CONTRACT_VERSION
    ticker: str
    generated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    entries: list[AssumptionRegisterEntry] = Field(default_factory=list)
    flag_counts: dict[str, int] = Field(default_factory=dict)
    max_flag_level: FlagLevel = FlagLevel.none
    has_critical: bool = False
    model_trust_state: ModelTrustState = ModelTrustState.clean
    summary: dict[str, Any] = Field(default_factory=dict)

    @field_validator("ticker")
    @classmethod
    def _uppercase_ticker(cls, value: str) -> str:
        return str(value).upper().strip()

    @model_validator(mode="after")
    def _derive_rollups(self) -> "AssumptionRegister":
        counts = {level.value: 0 for level in FlagLevel}
        max_level = FlagLevel.none
        for entry in self.entries:
            counts[entry.flag_level.value] += 1
            if FLAG_SEVERITY[entry.flag_level] > FLAG_SEVERITY[max_level]:
                max_level = entry.flag_level
        object.__setattr__(self, "flag_counts", counts)
        object.__setattr__(self, "max_flag_level", max_level)
        object.__setattr__(self, "has_critical", max_level == FlagLevel.critical)
        if max_level == FlagLevel.critical:
            object.__setattr__(self, "model_trust_state", ModelTrustState.critical_review_required)
        elif max_level == FlagLevel.review_required:
            object.__setattr__(self, "model_trust_state", ModelTrustState.review_required)
        elif max_level == FlagLevel.watch:
            object.__setattr__(self, "model_trust_state", ModelTrustState.watch)
        else:
            object.__setattr__(self, "model_trust_state", ModelTrustState.clean)
        object.__setattr__(self, "summary", {
            "model_trust_state": self.model_trust_state.value,
            "flag_counts": self.flag_counts,
            "max_flag_level": self.max_flag_level.value,
            "has_critical": self.has_critical,
        })
        return self


class AuditDiff(ContractModel):
    event_ts: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    actor: str = "system"
    actor_type: Literal["system", "pm", "agent"] = "system"
    entity_type: AssumptionEntityType
    entity_id: str
    ticker: str
    assumption_name: str
    scope: str
    event_type: str
    changed_fields: dict[str, dict[str, Any]]
    valuation_impact: dict[str, Any] | None = None
    reason: str | None = None
