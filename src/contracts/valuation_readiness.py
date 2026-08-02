"""Strict evidence gate between a completed valuation and its trust label."""

from __future__ import annotations

from collections.abc import Collection, Mapping
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator

from src.contracts.assumption_registry import (
    ASSUMPTION_REGISTRY,
    DriverFamily,
    judgment_owned_fields,
)
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


class JudgmentDriverSourceStrength(str, Enum):
    """Strength assigned to the raw source labels emitted by the assembler."""

    judgment_approved = "judgment_approved"
    consensus = "consensus"
    fallback = "fallback"
    unrecorded = "unrecorded"


class JudgmentDriverSeverity(str, Enum):
    none = "none"
    medium = "medium"
    high = "high"
    critical = "critical"


class JudgmentDriverVerdictStatus(str, Enum):
    approved = "approved"
    provisional = "provisional"
    unused = "unused"


class JudgmentDriverVerdict(BaseModel):
    """Per-driver evidence used by the valuation trust gate and PM reports."""

    model_config = ConfigDict(
        allow_inf_nan=False,
        extra="forbid",
        frozen=True,
    )

    field: str
    family: DriverFamily
    source: str | None = None
    source_strength: JudgmentDriverSourceStrength
    status: JudgmentDriverVerdictStatus
    severity: JudgmentDriverSeverity
    used: bool
    lineage_recorded: bool
    approval_basis: str | None = None
    reason_code: str | None = None


def _normalise_lineage_source(source: object) -> str | None:
    cleaned = str(source or "").strip()
    if not cleaned or cleaned.lower() in {"missing", "unknown", "unrecorded"}:
        return None
    return cleaned


def _is_approved_judgment_source(source: str | None) -> bool:
    if source is None:
        return False
    lowered = source.lower()
    return any(
        token in lowered
        for token in (
            "approved_assumption_register",
            "qoe_llm_approved",
            "pm_approved",
        )
    )


def _classify_judgment_source(
    source: str | None,
) -> JudgmentDriverSourceStrength:
    if source is None:
        return JudgmentDriverSourceStrength.unrecorded
    lowered = source.lower()
    if _is_approved_judgment_source(source):
        return JudgmentDriverSourceStrength.judgment_approved
    if lowered.startswith("ciq") and "blend" not in lowered:
        return JudgmentDriverSourceStrength.consensus
    return JudgmentDriverSourceStrength.fallback


def assess_judgment_driver_provenance(
    source_lineage: Mapping[str, object] | None,
    *,
    approved_family_hashes: Mapping[DriverFamily, str] | None = None,
    used_fields: Collection[str] | None = None,
) -> tuple[JudgmentDriverVerdict, ...]:
    """Classify every judgment-owned driver without changing its value.

    The raw labels intentionally remain those emitted by the valuation
    assembler. A complete approved family hash is the approval proof even if
    the frozen base lineage still shows a deterministic source.
    """

    lineage = source_lineage or {}
    used = None if used_fields is None else {str(field) for field in used_fields}
    approved_families = {
        family if isinstance(family, DriverFamily) else DriverFamily(str(family))
        for family, fingerprint in (approved_family_hashes or {}).items()
        if str(fingerprint).strip()
    }
    verdicts: list[JudgmentDriverVerdict] = []
    for field in judgment_owned_fields():
        definition = ASSUMPTION_REGISTRY[field]
        family = definition.family
        if family is None:
            raise ValueError(f"judgment-owned driver has no family: {field}")
        source = _normalise_lineage_source(lineage.get(field))
        lineage_recorded = source is not None
        is_used = used is None or field in used
        strength = _classify_judgment_source(source)

        if not is_used:
            verdicts.append(
                JudgmentDriverVerdict(
                    field=field,
                    family=family,
                    source=source,
                    source_strength=strength,
                    status=JudgmentDriverVerdictStatus.unused,
                    severity=JudgmentDriverSeverity.none,
                    used=False,
                    lineage_recorded=lineage_recorded,
                )
            )
            continue

        approval_basis: str | None = None
        if family in approved_families:
            strength = JudgmentDriverSourceStrength.judgment_approved
            approval_basis = "approved_driver_family_pack"
        elif strength is JudgmentDriverSourceStrength.judgment_approved:
            approval_basis = source

        if strength is JudgmentDriverSourceStrength.judgment_approved:
            status = JudgmentDriverVerdictStatus.approved
            severity = JudgmentDriverSeverity.none
            reason_code = None
        elif strength is JudgmentDriverSourceStrength.consensus:
            status = JudgmentDriverVerdictStatus.provisional
            severity = JudgmentDriverSeverity.medium
            reason_code = f"readiness.judgment_driver_consensus.{field}"
        elif strength is JudgmentDriverSourceStrength.fallback:
            status = JudgmentDriverVerdictStatus.provisional
            severity = JudgmentDriverSeverity.high
            if source is not None and "default" in source.lower():
                reason_code = f"readiness.judgment_driver_default.{field}"
            else:
                reason_code = f"readiness.judgment_driver_non_judgment.{field}"
        else:
            status = JudgmentDriverVerdictStatus.provisional
            severity = JudgmentDriverSeverity.critical
            reason_code = f"readiness.judgment_driver_unrecorded.{field}"

        verdicts.append(
            JudgmentDriverVerdict(
                field=field,
                family=family,
                source=source,
                source_strength=strength,
                status=status,
                severity=severity,
                used=True,
                lineage_recorded=lineage_recorded,
                approval_basis=approval_basis,
                reason_code=reason_code,
            )
        )
    return tuple(verdicts)


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
    judgment_driver_verdicts: tuple[JudgmentDriverVerdict, ...] = ()

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
        if not self.judgment_driver_verdicts:
            reasons.append("readiness.judgment_driver_provenance_missing")
        else:
            for verdict in self.judgment_driver_verdicts:
                if (
                    verdict.status is JudgmentDriverVerdictStatus.provisional
                    and verdict.used
                    and verdict.reason_code
                ):
                    reasons.append(verdict.reason_code)

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
