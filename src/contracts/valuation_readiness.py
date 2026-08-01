"""Strict evidence gate between a completed valuation and its trust label."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator

from src.contracts.assumption_registry import DriverFamily
from src.contracts.judgment_runs import canonical_semantic_hash


class ReconciliationGateStatus(str, Enum):
    reconciled = "reconciled"
    pending = "pending"
    failed = "failed"


class LTMStatus(str, Enum):
    compatible = "compatible"
    unavailable = "unavailable"
    incompatible = "incompatible"


class ValuationTrustStatus(str, Enum):
    decision_grade = "decision_grade"
    provisional = "provisional"
    blocked = "blocked"


class ValuationReadinessEvidence(BaseModel):
    """Frozen proof required before a replay can claim decision-grade status."""

    model_config = ConfigDict(
        allow_inf_nan=False,
        extra="forbid",
        frozen=True,
    )

    statement_reconciliation: ReconciliationGateStatus
    source_reconciliation: ReconciliationGateStatus
    claim_ledger_reconciliation: ReconciliationGateStatus
    operating_reconciliation: ReconciliationGateStatus
    annual_period_count: int = Field(ge=0)
    ltm_status: LTMStatus
    approved_family_hashes: dict[DriverFamily, str]
    statement_reconciliation_hash: str | None = None
    source_reconciliation_hash: str | None = None
    claim_ledger_hash: str | None = None
    operating_reconciliation_hash: str | None = None
    peer_set_fingerprint: str | None = None
    treatment_set_fingerprint: str | None = None
    prompt_contract_fingerprint: str | None = None
    dcf_engine_fingerprint: str | None = None
    comps_engine_fingerprint: str | None = None
    bridge_engine_fingerprint: str | None = None
    unresolved_clamp_count: int = Field(default=0, ge=0)
    pending_material_disagreement_count: int = Field(default=0, ge=0)
    pending_model_change_count: int = Field(default=0, ge=0)

    @field_validator("approved_family_hashes")
    @classmethod
    def _family_hashes_are_non_empty(
        cls,
        value: dict[DriverFamily, str],
    ) -> dict[DriverFamily, str]:
        normalized: dict[DriverFamily, str] = {}
        for family, fingerprint in value.items():
            cleaned = fingerprint.strip()
            if not cleaned:
                raise ValueError("approved family hashes must not be empty")
            normalized[family] = cleaned
        return normalized

    @field_validator(
        "statement_reconciliation_hash",
        "source_reconciliation_hash",
        "claim_ledger_hash",
        "operating_reconciliation_hash",
        "peer_set_fingerprint",
        "treatment_set_fingerprint",
        "prompt_contract_fingerprint",
        "dcf_engine_fingerprint",
        "comps_engine_fingerprint",
        "bridge_engine_fingerprint",
    )
    @classmethod
    def _optional_fingerprints_are_non_empty(
        cls,
        value: str | None,
    ) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("fingerprints must not be empty")
        return cleaned

    @computed_field
    @property
    def reason_codes(self) -> tuple[str, ...]:
        reasons: list[str] = []
        statuses = (
            (
                "statement_reconciliation",
                self.statement_reconciliation,
            ),
            ("source_reconciliation", self.source_reconciliation),
            (
                "claim_ledger",
                self.claim_ledger_reconciliation,
            ),
            ("operating_reconciliation", self.operating_reconciliation),
        )
        for label, status in statuses:
            if status == ReconciliationGateStatus.failed:
                reasons.append(f"readiness.{label}_failed")
            elif status == ReconciliationGateStatus.pending:
                reasons.append(f"readiness.{label}_pending")
        if self.annual_period_count < 3:
            reasons.append("readiness.history_insufficient")
        if self.ltm_status != LTMStatus.compatible:
            reasons.append(f"readiness.ltm_{self.ltm_status.value}")
        if set(self.approved_family_hashes) != set(DriverFamily):
            reasons.append("readiness.driver_families_incomplete")

        required_fingerprints = (
            ("statement_fingerprint_missing", self.statement_reconciliation_hash),
            ("source_fingerprint_missing", self.source_reconciliation_hash),
            ("claim_ledger_fingerprint_missing", self.claim_ledger_hash),
            (
                "operating_fingerprint_missing",
                self.operating_reconciliation_hash,
            ),
            ("peer_set_fingerprint_missing", self.peer_set_fingerprint),
            ("treatment_fingerprint_missing", self.treatment_set_fingerprint),
            (
                "prompt_contract_fingerprint_missing",
                self.prompt_contract_fingerprint,
            ),
            ("dcf_engine_fingerprint_missing", self.dcf_engine_fingerprint),
            ("comps_engine_fingerprint_missing", self.comps_engine_fingerprint),
            ("bridge_engine_fingerprint_missing", self.bridge_engine_fingerprint),
        )
        for code, fingerprint in required_fingerprints:
            if fingerprint is None:
                reasons.append(f"readiness.{code}")
        if self.unresolved_clamp_count:
            reasons.append("readiness.unresolved_clamps")
        if self.pending_material_disagreement_count:
            reasons.append("readiness.material_disagreements_pending")
        if self.pending_model_change_count:
            reasons.append("readiness.model_changes_pending")
        return tuple(reasons)

    @computed_field
    @property
    def trust_status(self) -> ValuationTrustStatus:
        hard_blockers = {
            "readiness.statement_reconciliation_failed",
            "readiness.source_reconciliation_failed",
            "readiness.claim_ledger_failed",
            "readiness.operating_reconciliation_failed",
            "readiness.history_insufficient",
        }
        if hard_blockers.intersection(self.reason_codes):
            return ValuationTrustStatus.blocked
        if self.reason_codes:
            return ValuationTrustStatus.provisional
        return ValuationTrustStatus.decision_grade

    @computed_field
    @property
    def readiness_fingerprint(self) -> str:
        return canonical_semantic_hash(
            self.model_dump(mode="json", exclude_computed_fields=True)
        )

    def require_decision_grade(self) -> None:
        if self.trust_status != ValuationTrustStatus.decision_grade:
            raise ValueError(
                "valuation is not decision-grade: "
                + ", ".join(self.reason_codes)
            )
