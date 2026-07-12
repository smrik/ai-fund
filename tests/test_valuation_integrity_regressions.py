from __future__ import annotations

import sqlite3
from types import SimpleNamespace

import pytest

from src.stage_00_data import ciq_adapter
from src.stage_02_valuation import input_assembler as ia
from src.stage_02_valuation.professional_dcf import run_dcf_professional
from src.stage_02_valuation.story_drivers import StoryDriverProfile
from src.stage_02_valuation.valuation_types import ForecastDrivers, ScenarioSpec
from src.stage_02_valuation.wacc import PeerData, compute_wacc


def _drivers(**overrides) -> ForecastDrivers:
    values = dict(
        revenue_base=1_000_000_000.0,
        revenue_growth_near=0.08,
        revenue_growth_mid=0.04,
        revenue_growth_terminal=0.025,
        ebit_margin_start=0.18,
        ebit_margin_target=0.20,
        tax_rate_start=0.22,
        tax_rate_target=0.23,
        capex_pct_start=0.05,
        capex_pct_target=0.045,
        da_pct_start=0.03,
        da_pct_target=0.028,
        dso_start=45.0,
        dso_target=44.0,
        dio_start=4.0,
        dio_target=5.0,
        dpo_start=115.0,
        dpo_target=100.0,
        wacc=0.09,
        exit_multiple=12.0,
        exit_metric="ev_ebitda",
        net_debt=200_000_000.0,
        shares_outstanding=100_000_000.0,
    )
    values.update(overrides)
    return ForecastDrivers(**values)


def test_nwc_driver_quality_flag_is_false_for_valid_positive_day_inputs() -> None:
    result = run_dcf_professional(_drivers(), ScenarioSpec(name="base", probability=1.0))

    assert result.nwc_driver_quality_flag is False


def test_ciq_snapshot_prefers_direct_day_metrics_and_preserves_cogs_ratio(
    tmp_path, monkeypatch
) -> None:
    db_path = tmp_path / "ciq.sqlite"
    monkeypatch.setattr(ciq_adapter, "DB_PATH", db_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE ciq_valuation_snapshot (
                ticker TEXT, as_of_date TEXT, run_id INTEGER, source_file TEXT,
                revenue_mm REAL, operating_income_mm REAL, capex_mm REAL, da_mm REAL,
                total_debt_mm REAL, cash_mm REAL, shares_out_mm REAL,
                ebit_margin REAL, op_margin_avg_3yr REAL, capex_pct_avg_3yr REAL,
                da_pct_avg_3yr REAL, effective_tax_rate REAL, effective_tax_rate_avg REAL,
                revenue_cagr_3yr REAL, debt_to_ebitda REAL, roic REAL, fcf_yield REAL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE ciq_long_form (
                run_id INTEGER, ticker TEXT, metric_key TEXT, value_num REAL,
                period_date TEXT, column_index INTEGER
            )
            """
        )
        conn.execute(
            """
            INSERT INTO ciq_valuation_snapshot (
                ticker, as_of_date, run_id, source_file, revenue_mm, operating_income_mm,
                capex_mm, da_mm, total_debt_mm, cash_mm, shares_out_mm
            ) VALUES ('MSFT', '2026-03-31', 2, 'MSFT_Standard.xlsx',
                      318273, 148957, 97225, 35500, 125432, 32105, 7458.25)
            """
        )
        conn.executemany(
            """
            INSERT INTO ciq_long_form
                (run_id, ticker, metric_key, value_num, period_date, column_index)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (2, "MSFT", "avg_days_sales_out", 64.07283, "2026-03-31", 13),
                (2, "MSFT", "avg_days_inv_out", 3.73979, "2026-03-31", 13),
                (2, "MSFT", "avg_days_payable_out", 114.94872, "2026-03-31", 13),
                (2, "MSFT", "cost_of_goods_sold", 100863.0, "2026-03-31", 13),
                (2, "MSFT", "revenue", 318273.0, "2026-03-31", 13),
            ],
        )

    snapshot = ciq_adapter.get_ciq_snapshot("MSFT")

    assert snapshot is not None
    assert snapshot["dso"] == pytest.approx(64.07283)
    assert snapshot["dio"] == pytest.approx(3.73979)
    assert snapshot["dpo"] == pytest.approx(114.94872)
    assert snapshot["cogs_pct_of_revenue"] == pytest.approx(100863 / 318273)


def _stub_actual_inputs(monkeypatch, *, story: StoryDriverProfile | None = None):
    from src.stage_02_valuation import input_assembler as ia

    monkeypatch.setattr(
        ia.md_client,
        "get_market_data",
        lambda ticker, **kwargs: {
            "ticker": ticker,
            "name": "Microsoft Corporation",
            "sector": "Technology",
            "industry": "Software",
            "current_price": 385.10,
            "market_cap": 2_860_690.20297e6,
            "enterprise_value": 2_907_894.20297e6,
        },
    )
    monkeypatch.setattr(ia.md_client, "get_historical_financials", lambda ticker, **kwargs: {})
    monkeypatch.setattr(
        ia,
        "get_ciq_snapshot",
        lambda ticker, as_of_date=None: {
            "revenue_ttm": 318_273e6,
            "revenue_fy1": 350_100.3e6,
            "op_margin_avg_3yr": 0.44,
            "capex_pct_avg_3yr": 0.1810701,
            "da_pct_avg_3yr": 0.0815616,
            "effective_tax_rate_avg": 0.2041,
            "total_debt": 125_432e6,
            "cash": 32_105e6,
            "shares_outstanding": 7_458.25e6,
            "dso": 64.07283,
            "dio": 3.73979,
            "dpo": 114.94872,
            "cogs_pct_of_revenue": 100_863 / 318_273,
            "run_id": 2,
            "source_file": "MSFT_Standard.xlsx",
            "as_of_date": "2026-03-31",
        },
    )
    monkeypatch.setattr(
        ia,
        "get_ciq_comps_valuation",
        lambda ticker, as_of_date=None: {
            "target_net_debt": 47_204.0,
            "target_shares_out": 7_428.4347,
            "peer_median_tev_ebitda_fwd": 18.4278,
            "run_id": 2,
            "source_file": "MSFT_Standard.xlsx",
            "as_of_date": "2026-03-31",
        },
    )
    monkeypatch.setattr(ia, "get_ciq_comps_detail", lambda ticker, as_of_date=None: None)
    monkeypatch.setattr(ia, "get_bridge_items_from_xbrl", lambda ticker: {})
    monkeypatch.setattr(
        ia,
        "compute_wacc_from_yfinance",
        lambda ticker, hist=None: SimpleNamespace(
            wacc=0.09,
            cost_of_equity=0.10,
            beta_relevered=1.0,
            beta_unlevered_median=1.0,
            size_premium=-0.0006,
            equity_weight=0.98,
            debt_weight=0.02,
            peers_used=["market (fallback)"],
        ),
    )
    monkeypatch.setattr(ia, "load_valuation_overrides", lambda: {"global": {}, "sectors": {}, "tickers": {}})
    monkeypatch.setattr(
        ia,
        "resolve_story_driver_profile",
        lambda ticker, sector: (story or StoryDriverProfile(), "story_sector"),
    )
    return ia


def test_cash_investments_enter_equity_bridge_once_and_current_shares_are_used(monkeypatch) -> None:
    ia = _stub_actual_inputs(monkeypatch)

    inputs = ia.build_valuation_inputs("MSFT", apply_overrides=False)

    assert inputs is not None
    assert inputs.drivers.net_debt == pytest.approx(47_204e6)
    assert inputs.drivers.non_operating_assets == 0
    assert inputs.drivers.shares_outstanding == pytest.approx(7_428.4347e6)
    assert inputs.drivers.cogs_pct_of_revenue == pytest.approx(100_863 / 318_273)
    assert inputs.source_lineage["net_debt"] == "ciq_comps_net_debt"
    assert inputs.source_lineage["non_operating_assets"] == "included_in_net_debt"
    assert inputs.source_lineage["shares_outstanding"] == "ciq_current_shares"
    assert inputs.source_lineage["cogs_pct_of_revenue"] == "ciq"


def test_unapproved_story_does_not_mutate_deterministic_inputs(monkeypatch) -> None:
    story = StoryDriverProfile(
        moat_strength=5,
        pricing_power=5,
        cyclicality="low",
        capital_intensity="low",
        governance_risk="low",
        competitive_advantage_years=10,
    )
    ia = _stub_actual_inputs(monkeypatch, story=story)

    inputs = ia.build_valuation_inputs("MSFT", apply_overrides=False)

    assert inputs is not None
    assert inputs.drivers.revenue_growth_near == pytest.approx(0.10)
    assert inputs.drivers.wacc == pytest.approx(0.09)
    assert inputs.drivers.exit_multiple == pytest.approx(18.4278)
    assert inputs.story_adjustments is None


def test_wacc_rejects_missing_market_cap_and_marks_beta_fallback_degraded() -> None:
    with pytest.raises(ValueError, match="market cap"):
        compute_wacc(PeerData(ticker="MSFT", beta=None, market_cap=None), [])

    degraded = compute_wacc(
        PeerData(ticker="MSFT", beta=None, market_cap=2_860_690e6),
        [],
    )
    assert degraded.quality_status == "degraded_fallback"
    assert degraded.missing_inputs == ["beta"]
    assert degraded.beta_source == "market_beta_assumption"


def test_ciq_comps_market_snapshot_runs_without_yfinance_cache(monkeypatch) -> None:
    ia = _stub_actual_inputs(monkeypatch)

    def _missing(*args, **kwargs):
        raise RuntimeError("No cached market row")

    monkeypatch.setattr(ia.md_client, "get_market_data", _missing)
    monkeypatch.setattr(ia.md_client, "get_historical_financials", _missing)
    monkeypatch.setattr(
        ia,
        "get_ciq_comps_detail",
        lambda ticker, as_of_date=None: {
            "target": {
                "ticker": "MSFT",
                "company_name": "Microsoft Corporation",
                "stock_price": 385.10,
                "market_cap_mm": 2_860_690.20297,
                "tev_mm": 2_907_894.20297,
                "shares_out_mm": 7_428.4347,
                "cash_mm": 78_228.0,
                "debt_mm": 125_432.0,
                "revenue_ltm_mm": 318_273.0,
            },
            "peers": [],
            "medians": {},
            "source_lineage": {"run_id": 2, "source_file": "MSFT_Standard.xlsx"},
        },
    )

    inputs = ia.build_valuation_inputs("MSFT", apply_overrides=False)

    assert inputs is not None
    assert inputs.current_price == pytest.approx(385.10)
    assert inputs.company_name == "Microsoft Corporation"
    assert inputs.source_lineage["current_price"] == "ciq_comps"


def test_ciq_company_name_replaces_ticker_placeholder_from_market_cache(monkeypatch) -> None:
    ia = _stub_actual_inputs(monkeypatch)
    monkeypatch.setattr(
        ia.md_client,
        "get_market_data",
        lambda ticker, **kwargs: {
            "ticker": ticker,
            "name": ticker,
            "sector": "Technology",
            "industry": "Software",
            "current_price": 385.10,
            "market_cap": 2_860_690.20297e6,
            "enterprise_value": 2_907_894.20297e6,
        },
    )
    monkeypatch.setattr(
        ia,
        "get_ciq_comps_detail",
        lambda ticker, as_of_date=None: {
            "target": {
                "ticker": ticker,
                "company_name": "Microsoft Corporation",
                "stock_price": 385.10,
                "market_cap_mm": 2_860_690.20297,
                "tev_mm": 2_907_894.20297,
                "shares_out_mm": 7_428.4347,
                "cash_mm": 78_228.0,
                "debt_mm": 125_432.0,
            },
            "peers": [],
            "medians": {},
        },
    )

    inputs = ia.build_valuation_inputs("MSFT", apply_overrides=False)

    assert inputs is not None
    assert inputs.company_name == "Microsoft Corporation"

def test_batch_runner_source_only_flag_reaches_input_assembler(monkeypatch) -> None:
    from src.stage_02_valuation import batch_runner

    captured = {}

    def _build(ticker, apply_overrides=True):
        captured["ticker"] = ticker
        captured["apply_overrides"] = apply_overrides
        return None

    monkeypatch.setattr(batch_runner, "build_valuation_inputs", _build)

    assert batch_runner.value_single_ticker("MSFT", apply_overrides=False) is None
    assert captured == {"ticker": "MSFT", "apply_overrides": False}


def test_net_debt_component_bridge_requires_both_sides() -> None:
    assert ia._net_debt_from_components({"total_debt": 125_000.0, "cash": None}) is None
    assert ia._net_debt_from_components({"total_debt": None, "cash": 78_000.0}) is None
    assert ia._net_debt_from_components({"total_debt": 125_000.0, "cash": 78_000.0}) == pytest.approx(47_000.0)
