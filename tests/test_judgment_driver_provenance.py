from __future__ import annotations

from types import SimpleNamespace

from scripts.manual import run_guided_ticker_workup as guided
from src.contracts.assumption_registry import DriverFamily, judgment_owned_fields
from src.contracts.valuation_readiness import (
    JudgmentDriverSourceStrength,
    ValuationReadinessEvidence,
    assess_judgment_driver_provenance,
)
from src.stage_04_pipeline.ticker_valuation_execution import (
    build_valuation_readiness,
)


def _ready(**changes: object) -> ValuationReadinessEvidence:
    payload: dict[str, object] = {
        "statement_reconciliation": "reconciled",
        "source_reconciliation": "reconciled",
        "claim_ledger_reconciliation": "reconciled",
        "operating_reconciliation": "reconciled",
        "annual_period_count": 5,
        "ltm_status": "compatible",
        "approved_family_hashes": {},
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


def _sources(default: str = "approved_assumption_register") -> dict[str, str]:
    return {field: default for field in judgment_owned_fields()}


def _render_input() -> dict[str, object]:
    return {
        "ticker": "MSFT",
        "run_started_at": "2026-08-01T09:00:00Z",
        "agent_mode": "heuristic",
        "database": {},
        "profiles": [],
        "queue_decisions": [],
        "profile_runs": [],
        "data_freshness": {},
        "latest_model": {
            "deterministic": {
                "dcf": {"terminal_bridge": {"method_used": "blend"}},
                "batch_row": {
                    "price": 300.0,
                    "iv_base": 228.89,
                    "iv_blended": 228.89,
                    "iv_gordon": 161.40,
                    "iv_exit": 330.11,
                    "drivers_json": '{"terminal_blend_gordon_weight": 0.6, "terminal_blend_exit_weight": 0.4}',
                },
            }
        },
    }


def test_default_judgment_driver_cannot_be_decision_grade_and_names_driver() -> None:
    sources = _sources()
    sources["ebit_margin_target"] = "default"
    verdicts = assess_judgment_driver_provenance(
        sources,
        used_fields=judgment_owned_fields(),
    )

    readiness = _ready(judgment_driver_verdicts=verdicts)

    ebit = next(row for row in verdicts if row.field == "ebit_margin_target")
    assert ebit.source_strength is JudgmentDriverSourceStrength.fallback
    assert ebit.status == "provisional"
    assert ebit.severity == "high"
    assert ebit.reason_code == "readiness.judgment_driver_default.ebit_margin_target"
    assert readiness.trust_status == "provisional"
    assert any("ebit_margin_target" in reason for reason in readiness.reason_codes)
    assert "decision_grade" not in readiness.reason_codes


def test_consensus_is_distinguished_from_pm_approved_judgment() -> None:
    consensus_sources = _sources()
    consensus_sources["revenue_growth_mid"] = "ciq"
    consensus = next(
        row
        for row in assess_judgment_driver_provenance(
            consensus_sources,
            used_fields=judgment_owned_fields(),
        )
        if row.field == "revenue_growth_mid"
    )

    approved_sources = _sources()
    approved = next(
        row
        for row in assess_judgment_driver_provenance(
            approved_sources,
            used_fields=judgment_owned_fields(),
        )
        if row.field == "revenue_growth_mid"
    )

    assert consensus.source_strength is JudgmentDriverSourceStrength.consensus
    assert consensus.status == "provisional"
    assert consensus.severity == "medium"
    assert approved.source_strength is JudgmentDriverSourceStrength.judgment_approved
    assert approved.status == "approved"
    assert approved.severity == "none"


def test_approved_family_pack_overrides_nonjudgment_base_lineage() -> None:
    sources = _sources("default")
    verdicts = assess_judgment_driver_provenance(
        sources,
        approved_family_hashes={
            DriverFamily.revenue: "pack:revenue",
        },
        used_fields=judgment_owned_fields(),
    )

    revenue_mid = next(
        row for row in verdicts if row.field == "revenue_growth_mid"
    )
    tax_target = next(row for row in verdicts if row.field == "tax_rate_target")

    assert revenue_mid.status == "approved"
    assert revenue_mid.source == "default"
    assert revenue_mid.approval_basis == "approved_driver_family_pack"
    assert tax_target.status == "provisional"


def test_missing_lineage_is_reported_for_a_used_driver() -> None:
    sources = _sources()
    del sources["ronic_terminal"]

    verdict = next(
        row
        for row in assess_judgment_driver_provenance(
            sources,
            used_fields=judgment_owned_fields(),
        )
        if row.field == "ronic_terminal"
    )

    assert verdict.used is True
    assert verdict.lineage_recorded is False
    assert verdict.source is None
    assert verdict.status == "provisional"
    assert verdict.severity == "critical"
    assert verdict.reason_code == "readiness.judgment_driver_unrecorded.ronic_terminal"


def test_missing_readiness_verdicts_cannot_retain_decision_grade() -> None:
    readiness = _ready(
        approved_family_hashes={
            family: f"pack:{family.value}" for family in DriverFamily
        },
        judgment_driver_verdicts=(),
    )

    assert readiness.trust_status == "provisional"
    assert "readiness.judgment_driver_provenance_missing" in readiness.reason_codes


def test_all_pm_approved_judgment_drivers_remain_decision_grade() -> None:
    verdicts = assess_judgment_driver_provenance(
        _sources(),
        used_fields=judgment_owned_fields(),
    )

    readiness = _ready(
        approved_family_hashes={
            family: f"pack:{family.value}" for family in DriverFamily
        },
        judgment_driver_verdicts=verdicts,
    )

    assert all(row.status == "approved" for row in verdicts)
    assert readiness.trust_status == "decision_grade"
    readiness.require_decision_grade()


def test_execution_readiness_consumes_snapshot_driver_lineage() -> None:
    sources = _sources()
    sources["ebit_margin_target"] = "default"
    statement_readiness = SimpleNamespace(
        status="decision_grade",
        source_reconciliation=SimpleNamespace(status="pass"),
        annual_period_count=5,
        ltm_status="compatible",
    )
    snapshot = SimpleNamespace(
        market_inputs={
            "source_lineage": sources,
            "base_drivers": {field: 0.0 for field in judgment_owned_fields()},
        },
        claim_ledger={
            "fingerprint": "claim",
            "reconciliation": {"is_decision_grade": True},
        },
        approved_treatments=(),
        statement_reconciliation={"pending_material_disagreement_count": 0},
        source_fingerprints={"source": "fingerprint"},
        comps_inputs={},
    )
    statement_run = SimpleNamespace(readiness=statement_readiness)
    operating = SimpleNamespace(
        status="reconciled",
        fingerprint="operating",
        result=SimpleNamespace(unresolved_clamp_count=0),
    )

    readiness = build_valuation_readiness(
        snapshot=snapshot,
        statement_run=statement_run,
        operating=operating,
        approved_family_hashes={},
    )

    ebit = next(
        row
        for row in readiness.judgment_driver_verdicts
        if row.field == "ebit_margin_target"
    )
    assert ebit.source == "default"
    assert ebit.status == "provisional"
    assert readiness.trust_status == "provisional"
    assert "readiness.judgment_driver_default.ebit_margin_target" in readiness.reason_codes


def test_pm_markdown_shows_per_driver_verdict() -> None:
    sources = _sources()
    sources["ebit_margin_target"] = "default"
    verdicts = assess_judgment_driver_provenance(
        sources,
        used_fields=judgment_owned_fields(),
    )
    result = _render_input()
    result["latest_model"]["deterministic"]["dcf"]["judgment_driver_verdicts"] = [
        row.model_dump(mode="json") for row in verdicts
    ]

    markdown = guided.render_guided_markdown(result)

    assert "## Judgment-Owned Driver Provenance" in markdown
    assert "ebit_margin_target" in markdown
    assert "default" in markdown
    assert "fallback" in markdown
    assert "provisional" in markdown
    assert "revenue_growth_mid" in markdown
    assert "approved_assumption_register" in markdown
