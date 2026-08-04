from __future__ import annotations

import sqlite3

import pytest

from db.loader import upsert_canonical_valuation_facts
from db.schema import create_tables
from src.stage_00_data.ciq_unit_mapping import (
    canonicalize_ciq_comps_snapshot,
    canonicalize_ciq_valuation_snapshot,
    ciq_comps_unit_spec,
)
from src.stage_00_data.unit_contract import CanonicalUnit, UnitContractError
from src.stage_00_data.source_unit_mapping import (
    canonicalize_macro_observation,
    canonicalize_market_cache,
    macro_series_unit_spec,
)


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


@pytest.mark.parametrize(
    ("metric_key", "canonical_unit", "raw_unit", "raw_scale"),
    [
        ("market_cap", CanonicalUnit.USD, "USD", 1_000_000.0),
        ("shares_out", CanonicalUnit.SHARES, "shares", 1_000_000.0),
        ("stock_price", CanonicalUnit.USD_PER_SHARE, "USD/share", 1.0),
        ("diluted_eps_ltm", CanonicalUnit.USD_PER_SHARE, "USD/share", 1.0),
        ("gross_margin_fy", CanonicalUnit.DECIMAL, "%", 0.01),
        ("total_revenue_ltm__2", CanonicalUnit.DECIMAL, "%", 0.01),
        ("of_52w_high", CanonicalUnit.DECIMAL, "decimal", 1.0),
        ("avg_days_sales_out", CanonicalUnit.DAYS, "days", 1.0),
        ("tev_ebitda_ltm", CanonicalUnit.MULTIPLE, "multiple", 1.0),
    ],
)
def test_ciq_comps_metrics_have_explicit_units(
    metric_key: str,
    canonical_unit: CanonicalUnit,
    raw_unit: str,
    raw_scale: float,
) -> None:
    spec = ciq_comps_unit_spec(metric_key)

    assert spec.canonical_unit is canonical_unit
    assert spec.raw_unit == raw_unit
    assert spec.raw_scale == raw_scale


def test_unknown_numeric_ciq_comps_metric_fails_closed() -> None:
    with pytest.raises(UnitContractError, match="comps_metric_unmapped"):
        ciq_comps_unit_spec("mystery_numeric_metric")


def test_ciq_comps_rows_are_canonicalized_without_mixed_scales() -> None:
    rows = [
        {
            "target_ticker": "MSFT",
            "peer_ticker": "MSFT",
            "as_of_date": "2026-06-30",
            "run_id": 20,
            "source_file": "MSFT_Standard.xlsx",
            "metric_key": "market_cap",
            "value_num": 3_671_338.0,
            "unit": "USD",
            "scale_factor": 1_000_000.0,
        },
        {
            "target_ticker": "MSFT",
            "peer_ticker": "MSFT",
            "as_of_date": "2026-06-30",
            "run_id": 20,
            "source_file": "MSFT_Standard.xlsx",
            "metric_key": "gross_margin_fy",
            "value_num": 67.944,
            "unit": "%",
            "scale_factor": 0.01,
        },
    ]

    facts = canonicalize_ciq_comps_snapshot(rows)
    by_metric = {fact["metric_key"]: fact for fact in facts}

    assert by_metric["market_cap"]["canonical_value"] == 3_671_338_000_000.0
    assert by_metric["market_cap"]["canonical_unit"] == "USD"
    assert by_metric["gross_margin_fy"]["canonical_value"] == pytest.approx(
        0.67944
    )
    assert by_metric["gross_margin_fy"]["canonical_unit"] == "decimal"
    assert all(fact["subject_key"] == "MSFT" for fact in facts)


def test_market_cache_valuation_inputs_are_canonicalized_on_write() -> None:
    facts = canonicalize_market_cache(
        ticker="MSFT",
        data_type="market_data",
        data={
            "current_price": 497.3301,
            "revenue_ttm": 331_839_012_864.0,
            "operating_margin": 0.46781,
            "total_debt": 128_812_998_656.0,
            "cash": 76_651_003_904.0,
            "shares_outstanding": 7_425_545_491.0,
        },
        fetched_at="2026-08-04T17:38:19+00:00",
    )
    by_metric = {fact["metric_key"]: fact for fact in facts}

    assert by_metric["current_price"]["canonical_unit"] == "USD/share"
    assert by_metric["revenue_ttm"]["canonical_value"] == 331_839_012_864.0
    assert by_metric["revenue_ttm"]["canonical_unit"] == "USD"
    assert by_metric["operating_margin"]["canonical_value"] == 0.46781
    assert by_metric["operating_margin"]["canonical_unit"] == "decimal"
    assert by_metric["shares_outstanding"]["canonical_unit"] == "shares"
    assert all(fact["raw_scale"] == 1.0 for fact in facts)


def test_historical_cache_valuation_inputs_keep_absolute_units() -> None:
    facts = canonicalize_market_cache(
        ticker="MSFT",
        data_type="historical_financials",
        data={
            "revenue_cagr_3yr": 0.143,
            "op_margin_avg_3yr": 0.451,
            "dso_derived": 68.0,
            "lease_liabilities_bs": 88_519_000_000.0,
            "diluted_shares": 7_453_000_000.0,
            "invested_capital_derived": 568_616_000_000.0,
        },
        fetched_at="2026-08-04T17:38:19+00:00",
    )
    by_metric = {fact["metric_key"]: fact for fact in facts}

    assert by_metric["lease_liabilities_bs"]["canonical_unit"] == "USD"
    assert by_metric["diluted_shares"]["canonical_unit"] == "shares"
    assert by_metric["dso_derived"]["canonical_unit"] == "days"
    assert by_metric["revenue_cagr_3yr"]["canonical_unit"] == "decimal"
    assert (
        by_metric["invested_capital_derived"]["canonical_value"]
        == 568_616_000_000.0
    )


@pytest.mark.parametrize(
    ("series_id", "raw_value", "canonical_value", "canonical_unit"),
    [
        ("DGS10", 4.75, 0.0475, CanonicalUnit.DECIMAL),
        ("VIXCLS", 15.86, 15.86, CanonicalUnit.INDEX),
        ("ICSA", 197_000.0, 197_000.0, CanonicalUnit.COUNT),
        ("RSAFS", 768_553.0, 768_553_000_000.0, CanonicalUnit.USD),
    ],
)
def test_macro_series_are_normalized_from_declared_native_units(
    series_id: str,
    raw_value: float,
    canonical_value: float,
    canonical_unit: CanonicalUnit,
) -> None:
    fact = canonicalize_macro_observation(
        series_id=series_id,
        series_date="2026-07-31",
        value=raw_value,
        fetched_at="2026-08-04T17:38:19+00:00",
    )

    assert fact["canonical_value"] == pytest.approx(canonical_value)
    assert fact["canonical_unit"] == canonical_unit.value
    assert fact["ticker"] == "__GLOBAL__"


def test_unknown_macro_series_fails_closed() -> None:
    with pytest.raises(UnitContractError, match="macro_series_unmapped"):
        macro_series_unit_spec("UNKNOWN_SERIES")
