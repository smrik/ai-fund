from __future__ import annotations

import sqlite3
from pathlib import Path

from src.stage_04_pipeline.evidence.context import build_business_context_packet
from tests.test_db_only_valuation_inputs import _build_fixture_db


def _build_context_fixture_db(path: Path) -> None:
    _build_fixture_db(path)
    conn = sqlite3.connect(path)

    statement_rows = [
        (f"fact_{idx}", f"fp_{idx}", "MSFT", "ciq_workbook_v1", 20, "income", concept, end, val, 1.0, "annual", "2026-08-04T17:45:05Z")
        for idx, (end, concept, val) in enumerate(
            [
                ("2022-06-30", "as_reported_total_revenue", 198_270_000_000.0),
                ("2023-06-30", "as_reported_total_revenue", 211_915_000_000.0),
                ("2024-06-30", "as_reported_total_revenue", 245_122_000_000.0),
                ("2025-06-30", "as_reported_total_revenue", 281_724_000_000.0),
                ("2026-06-30", "as_reported_total_revenue", 331_839_000_000.0),
                ("2022-06-30", "operating_income", 83_383_000_000.0),
                ("2023-06-30", "operating_income", 88_523_000_000.0),
                ("2024-06-30", "operating_income", 109_433_000_000.0),
                ("2025-06-30", "operating_income", 129_429_000_000.0),
                ("2026-06-30", "operating_income", 155_237_000_000.0),
            ]
        )
    ]
    conn.executemany(
        """
        INSERT INTO statement_facts (
            fact_id, ingestion_fingerprint, ticker, source, source_run_id, statement, concept, period_end, numeric_value, scale_factor, period_kind, ingested_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        statement_rows,
    )

    section_rows = [
        ("MSFT", "0000789019", "10-K", "0000789019-26-000001", "msft-20260630.htm", "2026-07-30", "business", "Item 1. Business", "Microsoft operates in three segments: Productivity and Business Processes, Intelligent Cloud, and More Personal Computing.", "hash1", "v1", "2026-07-30T00:00:00Z"),
        ("MSFT", "0000789019", "10-K", "0000789019-26-000001", "msft-20260630.htm", "2026-07-30", "mda", "Item 7. MD&A", "Management discussion of operations and AI infrastructure investment growth.", "hash2", "v1", "2026-07-30T00:00:00Z"),
    ]
    conn.executemany(
        """
        INSERT INTO edgar_section_cache (
            ticker, cik, form_type, accession_no, doc_name, filing_date, section_key, section_label, section_text, section_hash, parser_version, extracted_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        section_rows,
    )
    conn.commit()
    conn.close()


def test_build_business_context_packet_from_db(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    _build_context_fixture_db(db_path)

    packet = build_business_context_packet(str(db_path), "MSFT")

    fact_names = {fact.fact_name for fact in packet.facts}
    assert "revenue_series_annual" in fact_names
    assert "ebit_series_annual" in fact_names
    assert not any(name.startswith("model_assumption_") for name in fact_names)
    assert not any(ref.source_kind == "valuation_inputs" for ref in packet.source_refs)
    assert packet.run_metadata["ciq_run_id"] == 20
    assert packet.run_metadata["financial_as_of_date"] == "2026-06-30"
    assert packet.run_metadata["retrieval_mode"] == "db_only"
