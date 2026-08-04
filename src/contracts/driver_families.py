"""Strict provider-neutral contracts for judgment-authored driver families."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from src.contracts.assumption_registry import (
    ApplicabilityRule,
    AssumptionOwner,
    AssumptionUnit,
    DriverFamily,
    ScenarioDirection,
    get_assumption_definition,
    judgment_owned_fields,
)
from src.contracts.model_change_requests import ModelChangeCategory


DRIVER_FAMILY_CONTRACT_VERSION = "1.0.0"


class _StrictModel(BaseModel):
    model_config = ConfigDict(
        allow_inf_nan=False,
        extra="forbid",
        frozen=True,
    )


class ScenarioConditions(_StrictModel):
    low: str
    base: str
    high: str

    @field_validator("low", "base", "high")
    @classmethod
    def _require_condition(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("scenario conditions must not be empty")
        return cleaned


class ApplicableDriverAssumption(_StrictModel):
    assumption_name: str
    unit: AssumptionUnit
    applicability: Literal["applicable"]
    low: float
    base: float
    high: float
    conditions: ScenarioConditions
    rationale: str
    evidence_anchor_ids: tuple[str, ...] = Field(min_length=1)
    what_would_change_view: str

    @field_validator("low", "base", "high", mode="before")
    @classmethod
    def _require_json_number(cls, value: object) -> object:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("scenario values must be JSON numbers")
        return value

    @field_validator(
        "assumption_name",
        "rationale",
        "what_would_change_view",
    )
    @classmethod
    def _require_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("required text fields must not be empty")
        return cleaned

    @field_validator("evidence_anchor_ids")
    @classmethod
    def _require_anchors(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(value.strip() for value in values)
        if any(not value for value in cleaned):
            raise ValueError("evidence anchor IDs must not be empty")
        if len(set(cleaned)) != len(cleaned):
            raise ValueError("evidence anchor IDs must be unique")
        return cleaned

    @model_validator(mode="after")
    def _match_registry_definition(self) -> "ApplicableDriverAssumption":
        definition = get_assumption_definition(self.assumption_name)
        if definition.name != self.assumption_name:
            raise ValueError(
                f"use canonical assumption name {definition.name!r}, not alias "
                f"{self.assumption_name!r}"
            )
        if definition.owner != AssumptionOwner.judgment:
            raise ValueError(
                f"{self.assumption_name} is not judgment-owned"
            )
        if self.unit != definition.unit:
            raise ValueError(
                f"{self.assumption_name} requires unit {definition.unit.value}"
            )
        values = (self.low, self.base, self.high)
        if (
            definition.scenario_direction == ScenarioDirection.ascending
            and not values[0] <= values[1] <= values[2]
        ):
            raise ValueError(
                f"{self.assumption_name} scenarios must ascend from low to high"
            )
        if (
            definition.scenario_direction == ScenarioDirection.descending
            and not values[0] >= values[1] >= values[2]
        ):
            raise ValueError(
                f"{self.assumption_name} scenarios must descend from low to high"
            )
        return self


class NotApplicableDriverAssumption(_StrictModel):
    assumption_name: str
    unit: AssumptionUnit
    applicability: Literal["not_applicable"]
    rationale: str
    evidence_anchor_ids: tuple[str, ...] = Field(min_length=1)
    what_would_change_view: str

    @field_validator(
        "assumption_name",
        "rationale",
        "what_would_change_view",
    )
    @classmethod
    def _require_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("required text fields must not be empty")
        return cleaned

    @model_validator(mode="after")
    def _match_conditional_registry_definition(
        self,
    ) -> "NotApplicableDriverAssumption":
        definition = get_assumption_definition(self.assumption_name)
        if definition.name != self.assumption_name:
            raise ValueError(
                f"use canonical assumption name {definition.name!r}, not alias "
                f"{self.assumption_name!r}"
            )
        if definition.owner != AssumptionOwner.judgment:
            raise ValueError(
                f"{self.assumption_name} is not judgment-owned"
            )
        if definition.unit != self.unit:
            raise ValueError(
                f"{self.assumption_name} requires unit {definition.unit.value}"
            )
        if definition.applicability != ApplicabilityRule.conditional:
            raise ValueError(
                f"{self.assumption_name} cannot be marked not_applicable"
            )
        return self


DriverAssumptionProposal = Annotated[
    ApplicableDriverAssumption | NotApplicableDriverAssumption,
    Field(discriminator="applicability"),
]


class DriverFamilyProposal(_StrictModel):
    contract_version: str = DRIVER_FAMILY_CONTRACT_VERSION
    family: DriverFamily
    horizon_years: int = Field(ge=1, le=30)
    assumptions: tuple[DriverAssumptionProposal, ...] = Field(min_length=1)
    family_rationale: str

    @field_validator("horizon_years", mode="before")
    @classmethod
    def _require_integer_horizon(cls, value: object) -> object:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("horizon_years must be an integer")
        return value

    @field_validator("contract_version", "family_rationale")
    @classmethod
    def _require_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("required text fields must not be empty")
        return cleaned

    @model_validator(mode="after")
    def _require_one_complete_family(self) -> "DriverFamilyProposal":
        names = tuple(item.assumption_name for item in self.assumptions)
        if len(set(names)) != len(names):
            raise ValueError("family pack contains duplicate assumptions")

        expected = set(judgment_owned_fields(self.family))
        actual = set(names)
        if actual != expected:
            missing = sorted(expected - actual)
            unexpected = sorted(actual - expected)
            raise ValueError(
                "family pack must be atomic and complete; "
                f"missing={missing}, unexpected={unexpected}"
            )

        for item in self.assumptions:
            definition = get_assumption_definition(item.assumption_name)
            if definition.family != self.family:
                raise ValueError(
                    f"{item.assumption_name} does not belong to {self.family.value}"
                )
        return self


class DriverFamilyCritiqueIssue(_StrictModel):
    code: str
    severity: Literal["warning", "blocking"]
    assumption_names: tuple[str, ...] = Field(min_length=1)
    detail: str
    evidence_anchor_ids: tuple[str, ...] = Field(min_length=1)
    required_revision: str

    @field_validator(
        "code",
        "detail",
        "required_revision",
    )
    @classmethod
    def _require_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("required text fields must not be empty")
        return cleaned

    @field_validator("assumption_names", "evidence_anchor_ids")
    @classmethod
    def _require_unique_non_empty_ids(
        cls,
        values: tuple[str, ...],
    ) -> tuple[str, ...]:
        cleaned = tuple(value.strip() for value in values)
        if any(not value for value in cleaned):
            raise ValueError("identifier lists must not contain empty values")
        if len(set(cleaned)) != len(cleaned):
            raise ValueError("identifier lists must contain unique values")
        return cleaned


class ValuationMethodologyChallenge(_StrictModel):
    """A critic challenge to model capability, never a numeric override."""

    code: str
    severity: Literal["warning", "blocking"]
    category: ModelChangeCategory = ModelChangeCategory.methodology
    required_capability: str
    rationale: str
    evidence_anchor_ids: tuple[str, ...] = Field(min_length=1)

    @field_validator(
        "code",
        "required_capability",
        "rationale",
    )
    @classmethod
    def _require_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("methodology challenge text must not be empty")
        return cleaned

    @field_validator("evidence_anchor_ids")
    @classmethod
    def _require_unique_evidence(
        cls,
        values: tuple[str, ...],
    ) -> tuple[str, ...]:
        cleaned = tuple(value.strip() for value in values)
        if any(not value for value in cleaned):
            raise ValueError("evidence identifiers must not be empty")
        if len(set(cleaned)) != len(cleaned):
            raise ValueError("evidence identifiers must be unique")
        return cleaned


class DriverFamilyCritique(_StrictModel):
    contract_version: str = DRIVER_FAMILY_CONTRACT_VERSION
    family: DriverFamily
    verdict: Literal["accept", "revise", "block"]
    issues: tuple[DriverFamilyCritiqueIssue, ...] = ()
    methodology_challenges: tuple[ValuationMethodologyChallenge, ...] = ()
    summary: str

    @field_validator("contract_version", "summary")
    @classmethod
    def _require_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("required text fields must not be empty")
        return cleaned

    @model_validator(mode="after")
    def _validate_critic_scope(self) -> "DriverFamilyCritique":
        if self.verdict in {"revise", "block"} and not self.issues:
            raise ValueError(f"{self.verdict} verdict requires at least one issue")
        if self.verdict == "accept" and any(
            issue.severity == "blocking" for issue in self.issues
        ):
            raise ValueError("accept verdict cannot contain blocking issues")
        if self.verdict == "accept" and any(
            challenge.severity == "blocking"
            for challenge in self.methodology_challenges
        ):
            raise ValueError(
                "accept verdict cannot contain blocking methodology challenges"
            )
        family_fields = set(judgment_owned_fields(self.family))
        for issue in self.issues:
            unknown = sorted(set(issue.assumption_names) - family_fields)
            if unknown:
                raise ValueError(
                    f"critic issue references assumptions outside "
                    f"{self.family.value}: {unknown}"
                )
        return self
