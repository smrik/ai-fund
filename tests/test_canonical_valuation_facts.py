from __future__ import annotations

import sqlite3

from db.loader import upsert_canonical_valuation_facts
from db.schema import create_tables
from src.stage_00_data.ciq_unit_mapping import canonicalize_ciq_valuation_snapshot


def _msft_snapshot() -> dict[str, object]:
    return {
        "ticker": "MSFT",
        "as_of_date": "2026-06-30",
        "run_id": 20,
        "source_file": "MSFT_Standard.xlsx",
        "pulled_at": "2026-08-04T17:38:19+00:00",
        "revenue_mm": 331_839.0,
        "operating_income_mm": 155_237.0,
        "capex_mm": 115_948.0,
        "da_mm": 34_300.0,
        "total_debt_mm": 128_813.0,
        "cash_mm": 20_935.0,
        "shares_out_mm": 7_453.0,
        "ebit_margin": 0.467_810_475_6,
        "op_margin_avg_3yr": 0.451,
        "capex_pct_avg_3yr": 0.285,
        "da_pct_avg_3yr": 0.109,
        "effective_tax_rate": 0.181,
        "effective_tax_rate_avg": 0.181,
        "revenue_cagr_3yr": 0.143,
        "debt_to_ebitda": 0.663,
        "roic": 0.297,
        "fcf_yield": 0.021,
    }


def test_ciq_snapshot_is_persisted_in_canonical_units() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    create_tables(conn)

    facts = canonicalize_ciq_valuation_snapshot(_msft_snapshot())
    upsert_canonical_valuation_facts(conn, facts)

    stored = {
        row["metric_key"]: dict(row)
        for row in conn.execute(
            """
            SELECT *
            FROM canonical_valuation_facts
            WHERE ticker = 'MSFT' AND source_snapshot_id = 'ciq:20'
            """
        ).fetchall()
    }

    assert stored["revenue"]["canonical_value"] == 331_839_000_000.0
    assert stored["revenue"]["canonical_unit"] == "USD"
    assert stored["revenue"]["raw_value"] == 331_839.0
    assert stored["revenue"]["raw_unit"] == "USD"
    assert stored["revenue"]["raw_scale"] == 1_000_000.0
    assert stored["diluted_shares"]["canonical_value"] == 7_453_000_000.0
    assert stored["diluted_shares"]["canonical_unit"] == "shares"
    assert stored["ebit_margin"]["canonical_value"] == 0.467_810_475_6
    assert stored["ebit_margin"]["canonical_unit"] == "decimal"
    assert stored["debt_to_ebitda"]["canonical_unit"] == "multiple"
    assert all(row["as_of_date"] == "2026-06-30" for row in stored.values())
    assert all(row["source"] == "ciq_valuation_snapshot" for row in stored.values())


def test_canonical_fact_upsert_is_idempotent_for_one_source_identity() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    create_tables(conn)
    facts = canonicalize_ciq_valuation_snapshot(_msft_snapshot())

    upsert_canonical_valuation_facts(conn, facts)
    upsert_canonical_valuation_facts(conn, facts)

    count = conn.execute(
        "SELECT COUNT(*) FROM canonical_valuation_facts"
    ).fetchone()[0]
    assert count == len(facts)


def test_canonical_table_has_no_downstream_scale_column() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    create_tables(conn)

    columns = {
        row["name"]
        for row in conn.execute(
            "PRAGMA table_info(canonical_valuation_facts)"
        ).fetchall()
    }

    assert "canonical_scale" not in columns
    assert "unit_scale" not in columns
    assert "scale_factor" not in columns
    assert "raw_scale" in columns
