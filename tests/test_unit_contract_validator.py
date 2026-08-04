from __future__ import annotations

import sqlite3

from db.loader import (
    upsert_canonical_valuation_facts,
    upsert_ciq_comps_snapshot,
    upsert_ciq_valuation_snapshot,
)
from db.schema import create_tables
from src.stage_00_data.ciq_unit_mapping import canonicalize_ciq_valuation_snapshot
from src.stage_00_data.unit_contract_validator import (
    backfill_canonical_database,
    validate_canonical_database,
)


def _raw_snapshot() -> dict[str, object]:
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
        "ebit_margin": 0.4678,
        "op_margin_avg_3yr": 0.451,
        "capex_pct_avg_3yr": 0.285,
        "da_pct_avg_3yr": 0.109,
        "effective_tax_rate": 0.181,
        "effective_tax_rate_avg": 0.181,
        "revenue_cagr_3yr": 0.143,
        "roic": 0.297,
        "fcf_yield": 0.021,
        "debt_to_ebitda": 0.663,
    }


def _validated_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    create_tables(conn)
    conn.execute(
        """
        INSERT INTO ciq_ingest_runs (
            id, run_key, source_file, file_hash, ticker, parser_version,
            ingest_ts, status, rows_parsed, as_of_date
        ) VALUES (20, 'run-20', 'MSFT_Standard.xlsx', 'hash', 'MSFT',
                  'test', '2026-08-04T17:38:19+00:00', 'completed', 8601,
                  '2026-06-30')
        """
    )
    upsert_canonical_valuation_facts(
        conn,
        canonicalize_ciq_valuation_snapshot(_raw_snapshot()),
    )
    return conn


def test_validates_latest_ciq_snapshot_as_canonical() -> None:
    conn = _validated_connection()

    result = validate_canonical_database(conn, "MSFT")

    assert result.status == "pass"
    assert result.latest_ciq_run_id == 20
    assert result.financial_as_of_date == "2026-06-30"
    assert result.facts_checked == 17
    assert result.errors == ()


def test_rejects_missing_required_canonical_metric() -> None:
    conn = _validated_connection()
    conn.execute(
        "DELETE FROM canonical_valuation_facts WHERE metric_key = 'revenue'"
    )
    conn.commit()

    result = validate_canonical_database(conn, "MSFT")

    assert result.status == "fail"
    assert "canonical.required_metric_missing:revenue" in result.errors


def test_rejects_raw_provenance_that_does_not_reproduce_canonical_value() -> None:
    conn = _validated_connection()
    conn.execute(
        """
        UPDATE canonical_valuation_facts
        SET canonical_value = raw_value
        WHERE metric_key = 'revenue'
        """
    )
    conn.commit()

    result = validate_canonical_database(conn, "MSFT")

    assert result.status == "fail"
    assert any(
        error.startswith("canonical.provenance_mismatch:revenue")
        for error in result.errors
    )


def test_rejects_conflicting_values_for_one_source_metric() -> None:
    conn = _validated_connection()
    row = dict(
        conn.execute(
            """
            SELECT * FROM canonical_valuation_facts
            WHERE metric_key = 'revenue'
            """
        ).fetchone()
    )
    row["source_ref"] = f"{row['source_ref']}:conflict"
    row["canonical_value"] = 1.0
    row["raw_value"] = 1.0
    row["raw_scale"] = 1.0
    upsert_canonical_valuation_facts(conn, [row])

    result = validate_canonical_database(conn, "MSFT")

    assert result.status == "fail"
    assert "canonical.source_metric_conflict:revenue" in result.errors


def test_backfills_legacy_ciq_snapshot_and_mixed_unit_comps_rows() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    create_tables(conn)
    conn.execute(
        """
        INSERT INTO ciq_ingest_runs (
            id, run_key, source_file, file_hash, ticker, parser_version,
            ingest_ts, status, rows_parsed, as_of_date
        ) VALUES (20, 'run-20', 'MSFT_Standard.xlsx', 'hash', 'MSFT',
                  'legacy', '2026-08-04T17:38:19+00:00', 'completed', 8601,
                  '2026-06-30')
        """
    )
    upsert_ciq_valuation_snapshot(conn, [_raw_snapshot()])
    upsert_ciq_comps_snapshot(
        conn,
        [
            {
                "target_ticker": "MSFT",
                "peer_ticker": "MSFT",
                "as_of_date": "2026-06-30",
                "run_id": 20,
                "source_file": "MSFT_Standard.xlsx",
                "source_sheet": "Comps",
                "peer_name": "Microsoft",
                "section_name": "Comps",
                "metric_key": "market_cap",
                "metric_label": "Market Cap",
                "value_raw": "3671338",
                "value_num": 3_671_338.0,
                "unit": None,
                "scale_factor": 1.0,
                "is_target": 1,
            }
        ],
    )

    summary = backfill_canonical_database(conn, "MSFT")
    result = validate_canonical_database(conn, "MSFT")
    market_cap = conn.execute(
        """
        SELECT canonical_value FROM canonical_valuation_facts
        WHERE source = 'ciq_comps_snapshot' AND metric_key = 'market_cap'
        """
    ).fetchone()[0]

    assert summary.ciq_valuation_facts == 17
    assert summary.ciq_comps_facts == 1
    assert market_cap == 3_671_338_000_000.0
    assert result.status == "pass"
