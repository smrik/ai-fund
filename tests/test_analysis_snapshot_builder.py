from __future__ import annotations

from dataclasses import replace
import sqlite3

import pytest

from db.loader import insert_statement_facts
from db.schema import create_tables
from src.stage_04_pipeline.statement_reconciliation_service import (
    reconcile_ticker_statements,
)
from src.stage_02_valuation.input_assembler import ValuationInputsWithLineage
from src.stage_02_valuation.valuation_types import ForecastDrivers
from src.stage_04_pipeline.analysis_snapshot_builder import (
    build_valuation_analysis_snapshot,
)
from src.stage_04_pipeline.valuation_run_store import (
    persist_analysis_snapshot,
)
from tests.test_statement_reconciliation_service import (
    _persist_complete_manifests,
    _ready_facts,
)


def _drivers() -> ForecastDrivers:
    return ForecastDrivers(
        revenue_base=1000.0,
        revenue_growth_near=0.08,
        revenue_growth_mid=0.05,
        revenue_growth_terminal=0.025,
        ebit_margin_start=0.20,
        ebit_margin_target=0.23,
        tax_rate_start=0.21,
        tax_rate_target=0.22,
        capex_pct_start=0.05,
        capex_pct_target=0.06,
        da_pct_start=0.04,
        da_pct_target=0.045,
        dso_start=40.0,
        dso_target=38.0,
        dio_start=20.0,
        dio_target=18.0,
        dpo_start=35.0,
        dpo_target=37.0,
        wacc=0.09,
        exit_multiple=14.0,
        exit_metric="ev_ebitda",
        net_debt=100.0,
        shares_outstanding=50.0,
    )


def _inputs() -> ValuationInputsWithLineage:
    return ValuationInputsWithLineage(
        ticker="TEST",
        company_name="Test Company",
        sector="Industrials",
        industry="Machinery",
        current_price=25.0,
        as_of_date="2026-07-26",
        model_applicability_status="supported_v1",
        drivers=_drivers(),
        source_lineage={"revenue_base": "ciq"},
        ciq_lineage={"peer_count": 3},
        wacc_inputs={"wacc": 0.09, "source": "deterministic"},
        claim_ledger={
            "reconciliation": {
                "is_reconciled": True,
                "is_decision_grade": True,
            },
            "fingerprint": "claim-ledger-hash",
        },
        operating_cash_policy={"rate": 0.02},
    )


def _connection(
    facts: list[dict[str, object]] | None = None,
) -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    create_tables(conn)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS valuation_statement_reconciliation_runs (
            run_hash TEXT PRIMARY KEY,
            ticker TEXT NOT NULL,
            as_of_date TEXT NOT NULL,
            facts_fingerprint TEXT NOT NULL,
            selected_fact_ids_json TEXT NOT NULL,
            readiness_json TEXT NOT NULL,
            readiness_hash TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    if facts:
        insert_statement_facts(conn, facts)
        _persist_complete_manifests(
            conn,
            facts,
            evidence_cutoff="2026-07-26",
        )
    return conn


def _build(
    *,
    captured_at: str,
    facts: list[dict[str, object]] | None = None,
    return_connection: bool = False,
):
    conn = _connection(_ready_facts() if facts is None else facts)
    reconciliation_run = reconcile_ticker_statements(conn, "TEST")
    snapshot = build_valuation_analysis_snapshot(
        conn=conn,
        valuation_inputs=_inputs(),
        statement_reconciliation_run=reconciliation_run,
        operating_reconciliation={
            "status": "reconciled",
            "fingerprint": "operating-hash",
            "clamp_events": [],
        },
        comps_inputs={"peers": [{"ticker": "PEER", "ev_ebitda": 12.0}]},
        valuation_policy={
            "scenario_probabilities": {
                "low": 0.25,
                "base": 0.50,
                "high": 0.25,
            }
        },
        evidence={"fact:revenue": {"value": 1000.0}},
        upstream_context={
            "business": {"status": "complete"},
            "industry": {"status": "complete"},
        },
        approved_treatments=({"treatment_id": "cash-policy-v1"},),
        captured_at=captured_at,
    )
    return (snapshot, conn) if return_connection else snapshot


def test_builder_freezes_reconciled_inputs_and_stable_source_fingerprints() -> None:
    snapshot = _build(captured_at="2026-07-26T10:00:00Z")

    assert snapshot.ticker == "TEST"
    assert snapshot.identity["company_name"] == "Test Company"
    assert snapshot.statements["annual_period_count"] == 3
    assert snapshot.statements["ltm_status"] == "constructed"
    assert snapshot.market_inputs["base_drivers"]["revenue_base"] == 1000.0
    assert snapshot.claim_ledger["fingerprint"] == "claim-ledger-hash"
    assert snapshot.source_fingerprints.keys() >= {
        "sec_xbrl_filing_presentation_v1",
        "ciq_workbook_v1",
        "claim_ledger",
        "operating_reconciliation",
        "comps",
        "approved_treatments",
        "evidence",
        "valuation_policy",
        "wacc",
        "statement_reconciliation_run",
    }


def test_builder_hash_is_order_and_capture_time_independent() -> None:
    first = _build(captured_at="2026-07-26T10:00:00Z")
    second = _build(captured_at="2026-07-26T11:00:00Z")

    assert second.snapshot_hash == first.snapshot_hash


def test_builder_rejects_empty_or_forged_statement_reconciliation() -> None:
    conn = _connection()
    forged = reconcile_ticker_statements(conn, "TEST")
    forged = replace(
        forged,
        ticker="TEST",
        facts_fingerprint="forged",
    )

    with pytest.raises(ValueError, match="statement facts"):
        build_valuation_analysis_snapshot(
            conn=conn,
            valuation_inputs=_inputs(),
            statement_reconciliation_run=forged,
            operating_reconciliation={
                "status": "reconciled",
                "fingerprint": "operating-hash",
            },
            comps_inputs={"peers": [{"ticker": "PEER"}]},
            valuation_policy={
                "scenario_probabilities": {
                    "low": 0.25,
                    "base": 0.50,
                    "high": 0.25,
                }
            },
            evidence={"fact:revenue": {"value": 1000.0}},
            upstream_context={"business": {}, "industry": {}},
            captured_at="2026-07-26T10:00:00Z",
        )


def test_builder_rejects_post_as_of_statement_evidence() -> None:
    facts = _ready_facts()
    facts[0] = {
        **facts[0],
        "period_end": "2026-08-01",
        "filing_date": "2026-08-02",
        "ingestion_fingerprint": "post-as-of",
        "fact_id": "post-as-of",
    }

    with pytest.raises(ValueError, match="post-as-of"):
        _build(captured_at="2026-07-26T10:00:00Z", facts=facts)


def test_snapshot_store_requires_the_exact_persisted_reconciliation_run() -> None:
    snapshot, conn = _build(
        captured_at="2026-07-26T10:00:00Z",
        return_connection=True,
    )

    assert persist_analysis_snapshot(conn, snapshot) == snapshot.snapshot_hash
    conn.execute(
        """
        UPDATE valuation_statement_reconciliation_runs
        SET selected_fact_ids_json = '["forged"]'
        WHERE run_hash = ?
        """,
        (
            snapshot.statement_reconciliation[
                "reconciliation_run_hash"
            ],
        ),
    )
    conn.commit()
    with pytest.raises(ValueError, match="reconciliation run"):
        persist_analysis_snapshot(conn, snapshot)


def test_builder_rejects_unreconciled_claim_ledger() -> None:
    inputs = _inputs()
    inputs.claim_ledger["reconciliation"]["is_reconciled"] = False

    with pytest.raises(ValueError, match="claim ledger"):
        build_valuation_analysis_snapshot(
            conn=_connection(_ready_facts()),
            valuation_inputs=inputs,
            statement_reconciliation_run=reconcile_ticker_statements(
                _connection(_ready_facts()),
                "TEST",
            ),
            operating_reconciliation={
                "status": "reconciled",
                "fingerprint": "operating-hash",
            },
            comps_inputs={"peers": [{"ticker": "PEER"}]},
            valuation_policy={
                "scenario_probabilities": {
                    "low": 0.25,
                    "base": 0.50,
                    "high": 0.25,
                }
            },
            evidence={"fact:revenue": {"value": 1000.0}},
            upstream_context={"business": {}, "industry": {}},
            captured_at="2026-07-26T10:00:00Z",
        )
