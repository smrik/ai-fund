from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from db.loader import upsert_canonical_valuation_facts
from db.schema import create_tables
from src.stage_02_valuation.input_assembler import build_valuation_inputs_from_db


def _fact(
    *,
    ticker: str,
    subject_key: str,
    source: str,
    snapshot: str,
    metric: str,
    value: float,
    unit: str,
    as_of_date: str,
) -> dict[str, object]:
    return {
        "ticker": ticker,
        "subject_key": subject_key,
        "as_of_date": as_of_date,
        "period_date": as_of_date,
        "source": source,
        "source_snapshot_id": snapshot,
        "metric_key": metric,
        "canonical_value": value,
        "canonical_unit": unit,
        "raw_value": value,
        "raw_unit": unit,
        "raw_scale": 1.0,
        "source_ref": f"fixture:{source}:{subject_key}:{metric}",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }


def _build_fixture_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    create_tables(conn)
    conn.execute(
        """
        INSERT INTO ciq_ingest_runs (
            run_key, source_file, file_hash, ticker, parser_version,
            ingest_ts, status, as_of_date
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "fixture-run-20",
            "MSFT_Standard.xlsx",
            "fixture-hash",
            "MSFT",
            "fixture",
            "2026-08-04T17:45:05Z",
            "completed",
            "2026-06-30",
        ),
    )
    run_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
    assert run_id == 1
    conn.execute("UPDATE ciq_ingest_runs SET id = 20 WHERE id = 1")

    market_payload = {
        "ticker": "MSFT",
        "name": "Microsoft Corporation",
        "sector": "Technology",
        "industry": "Software - Infrastructure",
    }
    conn.execute(
        "INSERT INTO market_data_cache (ticker, data_type, data_json, fetched_at) VALUES (?, ?, ?, ?)",
        ("MSFT", "market_data", json.dumps(market_payload), "2026-08-04T15:59:37Z"),
    )

    facts: list[dict[str, object]] = []
    ciq_values = {
        "revenue": (331_839_000_000.0, "USD"),
        "operating_income": (155_237_000_000.0, "USD"),
        "op_margin_avg_3yr": (0.4568, "decimal"),
        "capex_pct_avg_3yr": (0.2533, "decimal"),
        "da_pct_avg_3yr": (0.08115, "decimal"),
        "effective_tax_rate_avg": (0.20257, "decimal"),
        "revenue_cagr_3yr": (0.16124, "decimal"),
        "total_debt": (128_813_000_000.0, "USD"),
        "cash": (20_935_000_000.0, "USD"),
        "diluted_shares": (7_453_000_000.0, "shares"),
    }
    for metric, (value, unit) in ciq_values.items():
        facts.append(
            _fact(
                ticker="MSFT",
                subject_key="MSFT",
                source="ciq_valuation_snapshot",
                snapshot="ciq:20",
                metric=metric,
                value=value,
                unit=unit,
                as_of_date="2026-06-30",
            )
        )

    market_values = {
        "current_price": (497.3301, "USD/share"),
        "market_cap": (3_692_947_570_688.0, "USD"),
        "beta": (1.099, "multiple"),
        "cash": (76_651_003_904.0, "USD"),
        "total_debt": (128_812_998_656.0, "USD"),
        "shares_outstanding": (7_425_545_491.0, "shares"),
        "revenue_ttm": (331_839_012_864.0, "USD"),
        "operating_margin": (0.45111, "decimal"),
        "revenue_growth": (0.177, "decimal"),
    }
    for metric, (value, unit) in market_values.items():
        facts.append(
            _fact(
                ticker="MSFT",
                subject_key="MSFT",
                source="market_data_cache:market_data",
                snapshot="market:fixture",
                metric=metric,
                value=value,
                unit=unit,
                as_of_date="2026-08-04",
            )
        )

    historical_values = {
        "revenue_cagr_3yr": (0.1635, "decimal"),
        "op_margin_avg_3yr": (0.4568, "decimal"),
        "capex_pct_avg_3yr": (0.2533, "decimal"),
        "da_pct_avg_3yr": (0.1020, "decimal"),
        "effective_tax_rate_avg": (0.1842, "decimal"),
        "dso_derived": (88.1, "days"),
        "dio_derived": (4.9, "days"),
        "dpo_derived": (123.0, "days"),
        "cogs_pct_of_revenue": (0.3116, "decimal"),
        "cost_of_debt_derived": (0.0537, "decimal"),
        "invested_capital_derived": (568_616_000_000.0, "USD"),
    }
    for metric, (value, unit) in historical_values.items():
        facts.append(
            _fact(
                ticker="MSFT",
                subject_key="MSFT",
                source="market_data_cache:historical_financials",
                snapshot="historical:fixture",
                metric=metric,
                value=value,
                unit=unit,
                as_of_date="2026-08-04",
            )
        )

    facts.append(
        _fact(
            ticker="__GLOBAL__",
            subject_key="DGS10",
            source="macro_series",
            snapshot="fred:DGS10:fixture",
            metric="dgs10",
            value=0.0475,
            unit="decimal",
            as_of_date="2026-07-31",
        )
    )
    upsert_canonical_valuation_facts(conn, facts)
    conn.close()


def test_db_only_entrypoint_resolves_latest_snapshot_and_uses_canonical_values(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "msft-canonical.db"
    _build_fixture_db(db_path)

    result = build_valuation_inputs_from_db(db_path, " msft ")

    assert result is not None
    assert result.ticker == "MSFT"
    assert result.as_of_date == "2026-06-30"
    assert result.ciq_lineage["snapshot_run_id"] == 20
    assert result.drivers.revenue_base == 331_839_000_000.0
    assert result.source_lineage["revenue_base"].startswith("canonical_db:")
    assert result.claim_ledger["unit"] == "USD"
    assert "unit_scale" not in result.claim_ledger
