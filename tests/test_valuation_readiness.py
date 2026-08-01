from __future__ import annotations

import pytest

from src.contracts.valuation_readiness import (
    ReconciliationGateStatus,
    ValuationReadinessEvidence,
    ValuationTrustStatus,
)


def _ready(**changes: object) -> ValuationReadinessEvidence:
    payload: dict[str, object] = {
        "statement_reconciliation": "reconciled",
        "source_reconciliation": "reconciled",
        "claim_ledger_reconciliation": "reconciled",
        "operating_reconciliation": "reconciled",
        "annual_period_count": 5,
        "ltm_status": "compatible",
        "approved_family_hashes": {
            "revenue": "family-revenue",
            "profitability_tax": "family-profitability",
            "reinvestment_working_capital": "family-reinvestment",
            "terminal_capital_comps": "family-terminal",
        },
        "statement_reconciliation_hash": "statement-hash",
        "source_reconciliation_hash": "source-hash",
        "claim_ledger_hash": "claim-hash",
        "operating_reconciliation_hash": "operating-hash",
        "peer_set_fingerprint": "peer-set-hash",
        "treatment_set_fingerprint": "treatment-set-hash",
        "prompt_contract_fingerprint": "prompt-contract-hash",
        "dcf_engine_fingerprint": "dcf-v1",
        "comps_engine_fingerprint": "comps-v1",
        "bridge_engine_fingerprint": "bridge-v1",
        "unresolved_clamp_count": 0,
        "pending_material_disagreement_count": 0,
        "pending_model_change_count": 0,
    }
    payload.update(changes)
    return ValuationReadinessEvidence.model_validate(payload)


def test_complete_reconciled_evidence_is_decision_grade() -> None:
    readiness = _ready()

    assert readiness.trust_status == ValuationTrustStatus.decision_grade
    assert readiness.reason_codes == ()
    readiness.require_decision_grade()


def test_missing_driver_family_or_ltm_is_explicitly_provisional() -> None:
    readiness = _ready(
        approved_family_hashes={
            "revenue": "family-revenue",
            "profitability_tax": "family-profitability",
        },
        ltm_status="unavailable",
    )

    assert readiness.trust_status == ValuationTrustStatus.provisional
    assert "readiness.driver_families_incomplete" in readiness.reason_codes
    assert "readiness.ltm_unavailable" in readiness.reason_codes
    with pytest.raises(ValueError, match="driver_families_incomplete"):
        readiness.require_decision_grade()


@pytest.mark.parametrize(
    ("changes", "reason_code"),
    [
        (
            {"statement_reconciliation": ReconciliationGateStatus.failed},
            "readiness.statement_reconciliation_failed",
        ),
        (
            {"claim_ledger_reconciliation": ReconciliationGateStatus.failed},
            "readiness.claim_ledger_failed",
        ),
        (
            {"operating_reconciliation": ReconciliationGateStatus.failed},
            "readiness.operating_reconciliation_failed",
        ),
        ({"annual_period_count": 2}, "readiness.history_insufficient"),
    ],
)
def test_failed_core_reconciliation_or_short_history_blocks(
    changes: dict[str, object],
    reason_code: str,
) -> None:
    readiness = _ready(**changes)

    assert readiness.trust_status == ValuationTrustStatus.blocked
    assert reason_code in readiness.reason_codes


def test_every_fingerprint_and_open_finding_affects_readiness_identity() -> None:
    ready = _ready()
    changed = _ready(
        peer_set_fingerprint="peer-set-restated",
        unresolved_clamp_count=1,
    )

    assert ready.readiness_fingerprint != changed.readiness_fingerprint
    assert changed.trust_status == ValuationTrustStatus.provisional
    assert "readiness.unresolved_clamps" in changed.reason_codes
