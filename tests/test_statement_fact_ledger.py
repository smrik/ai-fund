from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from db.loader import (
    insert_ciq_long_form,
    insert_statement_facts,
    load_statement_facts,
    register_ciq_ingest_run,
)
from db.schema import create_tables
from ciq.workbook_parser import parse_ciq_workbook
from src.stage_00_data.source_reconciliation import (
    SourceAmount,
    reconcile_statement_sources,
    source_amount_from_statement_fact,
)
from src.stage_00_data.xbrl_evidence import (
    normalize_financial_fact,
    persist_xbrl_statement_evidence,
)


def _xbrl_fact(**overrides):
    values = {
        "concept": "us-gaap:Assets",
        "taxonomy": "us-gaap",
        "label": "Total assets",
        "value": 512_163_000_000,
        "numeric_value": 512_163_000_000.0,
        "unit": "USD",
        "scale": 0,
        "period_end": date(2025, 6, 30),
        "period_type": "instant",
        "fiscal_year": 2025,
        "fiscal_period": "FY",
        "filing_date": date(2025, 7, 30),
        "form_type": "10-K",
        "accession": "0000950170-25-100235",
        "context_ref": "D2025",
        "semantic_tags": ["balance-sheet", "assets"],
        "business_context": "Consolidated Microsoft Corporation",
        "calculation_context": "Assets rollup",
        "dimensions": {
            "us-gaap:ConsolidationItemsAxis": "us-gaap:ConsolidationEliminationsMember",
            "us-gaap:StatementScenarioAxis": "us-gaap:ActualMember",
        },
        "statement_type": "BalanceSheet",
        "section": "Assets",
        "line_item_sequence": 17,
        "depth": 2,
        "parent_concept": "us-gaap:AssetsCurrent",
        "presentation_order": 12.0,
        "is_abstract": False,
        "is_total": True,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_normalized_xbrl_statement_fact_has_stable_complete_lineage_fingerprint():
    first = normalize_financial_fact(
        _xbrl_fact(),
        ticker="msft",
        cik="0000789019",
    )
    reordered_dimensions = {
        key: value
        for key, value in reversed(list(_xbrl_fact().dimensions.items()))
    }
    second = normalize_financial_fact(
        _xbrl_fact(dimensions=reordered_dimensions),
        ticker="MSFT",
        cik="789019",
    )

    assert first["ticker"] == "MSFT"
    assert first["entity_id"] == "0000789019"
    assert first["source"] == "sec_xbrl_companyfacts_v3"
    assert first["statement"] == "BalanceSheet"
    assert first["concept"] == "us-gaap:Assets"
    assert first["currency"] == "USD"
    assert first["scale_factor"] == 1.0
    assert first["period_kind"] == "annual"
    assert first["ingestion_fingerprint"] == second["ingestion_fingerprint"]
    assert first["metadata"]["dimensions"] == _xbrl_fact().dimensions
    assert first["metadata"]["parent_concept"] == "us-gaap:AssetsCurrent"
    assert first["metadata"]["presentation_order"] == 12.0
    assert first["context"] == {
        "context_ref": "D2025",
        "semantic_tags": ["balance-sheet", "assets"],
        "business_context": "Consolidated Microsoft Corporation",
        "calculation_context": "Assets rollup",
    }
    assert first["fiscal_calendar"]["fiscal_year"] == 2025
    assert first["fiscal_calendar"]["fiscal_period"] == "FY"


def test_statement_fact_persistence_is_idempotent_and_additive():
    conn = sqlite3.connect(":memory:")
    create_tables(conn)
    original = normalize_financial_fact(
        _xbrl_fact(),
        ticker="MSFT",
        cik="789019",
    )
    revised = normalize_financial_fact(
        _xbrl_fact(
            value=513_000_000_000,
            numeric_value=513_000_000_000.0,
            accession="0000950170-25-100236",
        ),
        ticker="MSFT",
        cik="789019",
    )

    assert insert_statement_facts(conn, [original]) == 1
    assert insert_statement_facts(conn, [original]) == 0
    assert insert_statement_facts(conn, [revised]) == 1

    stored = load_statement_facts(conn, "msft")
    assert len(stored) == 2
    assert {row["ingestion_fingerprint"] for row in stored} == {
        original["ingestion_fingerprint"],
        revised["ingestion_fingerprint"],
    }
    assert stored[0]["dimensions"] == _xbrl_fact().dimensions
    assert stored[0]["hierarchy"]["parent_concept"] == "us-gaap:AssetsCurrent"
    assert stored[0]["entity_id"] == "0000789019"
    assert stored[0]["context"]["business_context"] == (
        "Consolidated Microsoft Corporation"
    )
    assert stored[0]["fiscal_calendar"]["fiscal_period"] == "FY"


def test_create_tables_upgrades_legacy_statement_fact_lineage_columns():
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE statement_facts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fact_id TEXT NOT NULL,
            ingestion_fingerprint TEXT NOT NULL UNIQUE,
            ticker TEXT NOT NULL,
            source TEXT NOT NULL,
            source_run_id INTEGER,
            statement TEXT NOT NULL,
            concept TEXT NOT NULL,
            label TEXT,
            value_raw TEXT,
            numeric_value REAL,
            unit TEXT,
            currency TEXT,
            scale REAL,
            scale_factor REAL NOT NULL DEFAULT 1.0,
            period_label TEXT,
            period_kind TEXT NOT NULL,
            period_type TEXT,
            period_start TEXT,
            period_end TEXT,
            fiscal_year INTEGER,
            fiscal_period TEXT,
            filing_date TEXT,
            form_type TEXT,
            accession TEXT,
            context_ref TEXT,
            dimensions_json TEXT NOT NULL DEFAULT '{}',
            hierarchy_json TEXT NOT NULL DEFAULT '{}',
            source_locator TEXT,
            is_derived INTEGER NOT NULL DEFAULT 0,
            derivation_json TEXT,
            ingested_at TEXT NOT NULL
        );
        """
    )

    create_tables(conn)

    columns = {
        row[1] for row in conn.execute("PRAGMA table_info(statement_facts)")
    }
    assert {
        "entity_id",
        "context_json",
        "fiscal_calendar_json",
    } <= columns

    fact = normalize_financial_fact(
        _xbrl_fact(),
        ticker="MSFT",
        cik="789019",
    )
    assert insert_statement_facts(conn, [fact]) == 1
    stored = load_statement_facts(conn, "MSFT")
    assert stored[0]["entity_id"] == "0000789019"
    assert stored[0]["context"]["business_context"] == (
        "Consolidated Microsoft Corporation"
    )
    assert stored[0]["fiscal_calendar"]["fiscal_period"] == "FY"


def test_ciq_statement_ingest_preserves_repeated_presented_lines_and_scale():
    conn = sqlite3.connect(":memory:")
    create_tables(conn)
    run_id, is_new = register_ciq_ingest_run(
        conn,
        {
            "run_key": "ciq-fixture-1",
            "source_file": "MSFT_Standard.xlsx",
            "file_hash": "abc123",
            "ticker": "MSFT",
            "parser_version": "fixture-v1",
            "ingest_ts": "2026-07-26T12:00:00Z",
            "status": "started",
            "error_message": None,
            "template_fingerprint": "template-1",
            "rows_parsed": 0,
            "as_of_date": "2025-06-30",
        },
    )
    assert is_new
    common = {
        "ticker": "MSFT",
        "sheet_name": "Financial Statements",
        "section_name": "CASH FLOW STATEMENT - USD IN MILLIONS",
        "row_label": "Depreciation & Amort.",
        "metric_key": "da",
        "period_date": "2025-06-30",
        "calc_type": "LTM",
        "column_label": "2025-06-30",
        "column_index": 6,
        "unit": "USD",
        "scale_factor": 1_000_000.0,
        "source_file": "MSFT_Standard.xlsx",
    }
    rows = [
        {**common, "value_raw": "22", "value_num": 22.0},
        {**common, "value_raw": "0", "value_num": 0.0},
    ]

    insert_ciq_long_form(conn, run_id, rows)
    stored = load_statement_facts(conn, "MSFT", sources=["ciq_workbook_v1"])

    assert len(stored) == 2
    assert {row["numeric_value"] for row in stored} == {0.0, 22.0}
    assert {row["scale_factor"] for row in stored} == {1_000_000.0}
    assert all(row["statement"] == "CashFlowStatement" for row in stored)
    assert len({row["source_locator"] for row in stored}) == 2

    insert_ciq_long_form(conn, run_id, rows)
    assert len(
        load_statement_facts(conn, "MSFT", sources=["ciq_workbook_v1"])
    ) == 2


def test_real_ciq_zero_da_is_period_and_unit_comparable_to_nonzero_xbrl():
    payload = parse_ciq_workbook(
        Path("ciq/templates/ciq_cleandata.xlsx")
    )
    zero_da = next(
        row
        for row in payload.long_form_records
        if row["sheet_name"] == "Financial Statements"
        and row["statement"] == "IncomeStatement"
        and row["canonical_role"] == "da"
        and row["period_end"] == "2025-05-31"
        and row["value_num"] == 0.0
    )

    conn = sqlite3.connect(":memory:")
    create_tables(conn)
    run_id, _ = register_ciq_ingest_run(
        conn,
        {
            "run_key": "ciq-real-zero-da",
            "source_file": payload.source_file,
            "file_hash": payload.file_hash,
            "ticker": payload.ticker,
            "parser_version": payload.parser_version,
            "ingest_ts": "2026-07-26T12:00:00Z",
            "status": "started",
            "error_message": None,
            "template_fingerprint": payload.template_fingerprint,
            "rows_parsed": 1,
            "as_of_date": "2025-05-31",
        },
    )
    insert_ciq_long_form(conn, run_id, [zero_da])
    ciq_fact = load_statement_facts(
        conn,
        payload.ticker,
        sources=["ciq_workbook_v1"],
    )[0]

    assert ciq_fact["numeric_value"] == 0.0
    assert ciq_fact["period_start"] == "2024-06-01"
    assert ciq_fact["period_end"] == "2025-05-31"
    assert ciq_fact["period_kind"] == "annual"
    assert ciq_fact["unit"] == "USD"
    assert ciq_fact["currency"] == "USD"
    assert ciq_fact["scale_factor"] == 1_000_000.0

    ciq_amount = source_amount_from_statement_fact(ciq_fact)
    xbrl_amount = SourceAmount(
        ticker=payload.ticker,
        source="sec_xbrl_filing_presentation_v1",
        statement="IncomeStatement",
        canonical_key="da",
        value=10.0,
        scale_factor=1_000_000.0,
        unit="USD",
        currency="USD",
        period_start="2024-06-01",
        period_end="2025-05-31",
        period_kind="annual",
        fact_id="xbrl:nonzero-da",
        source_locator="filing#income-statement/da",
    )
    result = reconcile_statement_sources([xbrl_amount], [ciq_amount])

    assert result.overlap_count == 1
    assert result.status == "review_required"
    assert result.comparisons[0].status == "material_disagreement"


def test_xbrl_statement_ingest_persists_complete_selected_payload(monkeypatch):
    facts = [
        _xbrl_fact(
            concept="us-gaap:Assets",
            statement_type="BalanceSheet",
            dimensions={},
        ),
        _xbrl_fact(
            concept="us-gaap:LiabilitiesAndStockholdersEquity",
            label="Liabilities and stockholders' equity",
            statement_type="BalanceSheet",
            dimensions={},
        ),
        _xbrl_fact(
            concept="us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
            label="Cloud revenue",
            statement_type="IncomeStatement",
            period_start=date(2024, 7, 1),
            period_type="duration",
            dimensions={"us-gaap:ProductOrServiceAxis": "msft:CloudMember"},
        ),
    ]

    records = [
        normalize_financial_fact(fact, ticker="MSFT", cik="789019")
        for fact in facts
    ]
    manifest_payload = {
        "contract_version": "statement_coverage_manifest.v1",
        "ticker": "MSFT",
        "source": "sec_xbrl_filing_presentation_v1",
        "accession": "0000950170-25-087063",
        "source_run_id": 17,
        "status": "completed",
        "filing_date": "2025-07-30",
        "evidence_cutoff": "2025-07-30",
        "coverage": {
            "entries": {
                "BalanceSheet": {
                    "presented_fact_ids": [
                        records[0]["fact_id"],
                        records[1]["fact_id"],
                    ],
                    "consolidated_fact_ids": [
                        records[0]["fact_id"],
                        records[1]["fact_id"],
                    ],
                    "dimensioned_fact_ids": [],
                }
            },
            "entry_count": 1,
        },
        "calculation_edges": [],
        "calculation_edge_count": 0,
    }
    manifest_hash = hashlib.sha256(
        json.dumps(
            manifest_payload,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    coverage_manifest = {
        "manifest_id": f"sha256:{manifest_hash}",
        "manifest_hash": manifest_hash,
        **manifest_payload,
    }
    calls = []

    def fake_statement_evidence(*args, **kwargs):
        calls.append((args, kwargs))
        return {
            "ticker": "MSFT",
            "source": "sec_xbrl_companyfacts_v3",
            "status": "completed",
            "facts": records,
            "fact_count": len(records),
            "annual_periods": ["2025-06-30"],
            "ltm_status": "not_available",
            "ltm_details": {},
            "coverage_manifests": [coverage_manifest],
            "errors": [],
        }

    monkeypatch.setattr(
        "src.stage_00_data.xbrl_evidence.get_xbrl_statement_evidence",
        fake_statement_evidence,
    )
    conn = sqlite3.connect(":memory:")
    create_tables(conn)

    first = persist_xbrl_statement_evidence(
        conn,
        "MSFT",
        evidence_cutoff="2025-07-30",
        source_run_id=17,
    )
    second = persist_xbrl_statement_evidence(
        conn,
        "MSFT",
        evidence_cutoff="2025-07-30",
        source_run_id=17,
    )

    assert first["status"] == "completed"
    assert calls[0][1]["evidence_cutoff"] == "2025-07-30"
    assert calls[0][1]["source_run_id"] == 17
    assert first["inserted_count"] == 3
    assert second["inserted_count"] == 0
    assert first["manifest_ids"] == [coverage_manifest["manifest_id"]]
    assert second["manifest_ids"] == [coverage_manifest["manifest_id"]]
    stored_manifest = conn.execute(
        """
        SELECT manifest_id, ticker, source_run_id, accession, status,
               evidence_cutoff
        FROM statement_source_manifests
        """
    ).fetchone()
    assert stored_manifest == (
        coverage_manifest["manifest_id"],
        "MSFT",
        17,
        "0000950170-25-087063",
        "completed",
        "2025-07-30",
    )
    stored = load_statement_facts(
        conn,
        "MSFT",
        sources=["sec_xbrl_companyfacts_v3"],
    )
    assert len(stored) == 3
    assert any(row["dimensions"] for row in stored)


def test_ciq_statement_and_legacy_rows_are_one_atomic_ingest():
    conn = sqlite3.connect(":memory:")
    create_tables(conn)
    run_id, _ = register_ciq_ingest_run(
        conn,
        {
            "run_key": "ciq-atomic-1",
            "source_file": "IBM_Standard.xlsx",
            "file_hash": "atomic-hash",
            "ticker": "IBM",
            "parser_version": "fixture-v1",
            "ingest_ts": "2026-07-26T12:00:00Z",
            "status": "started",
            "error_message": None,
            "template_fingerprint": "template-1",
            "rows_parsed": 1,
            "as_of_date": "2025-12-31",
        },
    )
    conn.execute("DROP TABLE statement_facts")
    row = {
        "ticker": "IBM",
        "sheet_name": "Financial Statements",
        "section_name": "INCOME STATEMENT - USD IN MILLIONS",
        "row_label": "Total Revenues",
        "metric_key": "revenue",
        "period_date": "2025-12-31",
        "calc_type": "REP",
        "column_label": "2025-12-31",
        "column_index": 5,
        "value_raw": "100",
        "value_num": 100.0,
        "unit": "USD",
        "scale_factor": 1_000_000.0,
        "source_file": "IBM_Standard.xlsx",
    }

    with pytest.raises(sqlite3.OperationalError):
        insert_ciq_long_form(conn, run_id, [row])

    assert conn.execute("SELECT COUNT(*) FROM ciq_long_form").fetchone()[0] == 0
