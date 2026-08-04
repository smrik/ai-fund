"""Auditable requests for valuation capabilities the current model lacks."""

from __future__ import annotations

from enum import Enum

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from src.contracts.judgment_runs import canonical_semantic_hash


class ModelChangeStatus(str, Enum):
    pending = "pending"
    accepted = "accepted"
    rejected = "rejected"
    implemented = "implemented"


class ModelChangeCategory(str, Enum):
    methodology = "methodology"
    applicability = "applicability"
    source_treatment = "source_treatment"
    data_model = "data_model"
    other = "other"


class ValuationModelChangeRequest(BaseModel):
    """A PM decision record; it cannot carry or apply a numeric proxy."""

    model_config = ConfigDict(
        allow_inf_nan=False,
        extra="forbid",
        frozen=True,
    )

    request_id: str
    ticker: str
    analysis_snapshot_hash: str
    category: ModelChangeCategory
    current_model: str
    required_capability: str
    rationale: str
    evidence_anchor_ids: tuple[str, ...] = Field(min_length=1)
    evidence_fingerprints: tuple[str, ...] = Field(min_length=1)
    status: ModelChangeStatus = ModelChangeStatus.pending
    implementation_intent: str | None = None
    decision_actor: str | None = None
    created_at: str
    decided_at: str | None = None

    @field_validator(
        "request_id",
        "ticker",
        "analysis_snapshot_hash",
        "current_model",
        "required_capability",
        "rationale",
        "implementation_intent",
        "decision_actor",
        "created_at",
        "decided_at",
    )
    @classmethod
    def _normalize_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("text fields must not be empty")
        return cleaned

    @field_validator("ticker")
    @classmethod
    def _uppercase_ticker(cls, value: str) -> str:
        return value.upper()

    @field_validator("evidence_anchor_ids", "evidence_fingerprints")
    @classmethod
    def _unique_evidence(
        cls,
        values: tuple[str, ...],
    ) -> tuple[str, ...]:
        cleaned = tuple(value.strip() for value in values)
        if any(not value for value in cleaned):
            raise ValueError("evidence identifiers must not be empty")
        if len(set(cleaned)) != len(cleaned):
            raise ValueError("evidence identifiers must be unique")
        return cleaned

    def identity_payload(self) -> dict[str, object]:
        return {
            "ticker": self.ticker,
            "analysis_snapshot_hash": self.analysis_snapshot_hash,
            "category": self.category.value,
            "current_model": self.current_model,
            "required_capability": self.required_capability,
            "rationale": self.rationale,
            "evidence_anchor_ids": self.evidence_anchor_ids,
            "evidence_fingerprints": self.evidence_fingerprints,
        }

    @model_validator(mode="after")
    def _validate_identity_and_decision(self) -> "ValuationModelChangeRequest":
        expected_id = model_change_request_id(self.identity_payload())
        if self.request_id != expected_id:
            raise ValueError("request_id does not match immutable request identity")
        decided = self.status != ModelChangeStatus.pending
        if decided and (self.decision_actor is None or self.decided_at is None):
            raise ValueError("decided model-change requests require actor and time")
        if not decided and any(
            value is not None
            for value in (
                self.implementation_intent,
                self.decision_actor,
                self.decided_at,
            )
        ):
            raise ValueError("pending model-change requests cannot carry a decision")
        if self.status in {
            ModelChangeStatus.accepted,
            ModelChangeStatus.implemented,
        } and self.implementation_intent is None:
            raise ValueError(
                "accepted model-change requests require implementation intent"
            )
        return self


def model_change_request_id(identity_payload: dict[str, object]) -> str:
    return "model-change:" + canonical_semantic_hash(identity_payload)[:24]


def build_model_change_request(
    *,
    ticker: str,
    analysis_snapshot_hash: str,
    category: ModelChangeCategory | str,
    current_model: str,
    required_capability: str,
    rationale: str,
    evidence_anchor_ids: tuple[str, ...],
    evidence_fingerprints: tuple[str, ...],
    created_at: str,
) -> ValuationModelChangeRequest:
    identity = {
        "ticker": ticker.strip().upper(),
        "analysis_snapshot_hash": analysis_snapshot_hash.strip(),
        "category": ModelChangeCategory(category).value,
        "current_model": current_model.strip(),
        "required_capability": required_capability.strip(),
        "rationale": rationale.strip(),
        "evidence_anchor_ids": evidence_anchor_ids,
        "evidence_fingerprints": evidence_fingerprints,
    }
    return ValuationModelChangeRequest(
        request_id=model_change_request_id(identity),
        created_at=created_at,
        **identity,
    )


def decide_model_change_request(
    request: ValuationModelChangeRequest,
    *,
    status: ModelChangeStatus | str,
    actor: str,
    decided_at: str,
    implementation_intent: str | None = None,
) -> ValuationModelChangeRequest:
    selected_status = ModelChangeStatus(status)
    if selected_status == ModelChangeStatus.pending:
        raise ValueError("a decision cannot return a request to pending")
    payload = request.model_dump(mode="json")
    payload.update(
        {
            "status": selected_status,
            "implementation_intent": implementation_intent,
            "decision_actor": actor,
            "decided_at": decided_at,
        }
    )
    return ValuationModelChangeRequest.model_validate(payload)
