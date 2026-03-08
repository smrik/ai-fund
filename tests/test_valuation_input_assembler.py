from types import SimpleNamespace

from src.stage_02_valuation.input_assembler import (
    build_valuation_inputs,
    determine_model_applicability,
    select_exit_metric_for_sector,
)


def test_sector_exit_metric_mapping():
    assert select_exit_metric_for_sector("Technology") == "ev_ebitda"
    assert select_exit_metric_for_sector("Communication Services") == "ev_ebitda"
    assert select_exit_metric_for_sector("Energy") == "ev_ebit"
    assert select_exit_metric_for_sector("Basic Materials") == "ev_ebit"


def test_financials_and_reits_marked_alt_model_required():
    assert determine_model_applicability("Financial Services", "Banks - Regional") == "alt_model_required"
    assert determine_model_applicability("Real Estate", "REIT - Retail") == "alt_model_required"
    assert determine_model_applicability("Technology", "Software") == "dcf_applicable"


def test_build_valuation_inputs_applies_ciq_precedence(monkeypatch):
    from src.stage_02_valuation import input_assembler as ia

    monkeypatch.setattr(
        ia.md_client,
        "get_market_data",
        lambda ticker, as_of_date=None: {
            "ticker": ticker,
            "name": "Test Co",
            "sector": "Technology",
            "industry": "Software",
            "current_price": 100.0,
            "revenue_ttm": 500_000_000.0,
            "operating_margin": 0.11,
            "revenue_growth": 0.05,
            "total_debt": 300_000_000.0,
            "cash": 100_000_000.0,
            "shares_outstanding": 100_000_000.0,
            "market_cap": 10_000_000_000.0,
            "enterprise_value": 10_200_000_000.0,
            "free_cashflow": 50_000_000.0,
        },
    )
    monkeypatch.setattr(
        ia.md_client,
        "get_historical_financials",
        lambda ticker, as_of_date=None: {
            "revenue_cagr_3yr": 0.06,
            "op_margin_avg_3yr": 0.12,
            "capex_pct_avg_3yr": 0.05,
            "da_pct_avg_3yr": 0.03,
            "effective_tax_rate_avg": 0.22,
        },
    )
    monkeypatch.setattr(
        ia,
        "get_ciq_snapshot",
        lambda ticker, as_of_date=None: {
            "revenue_ttm": 800_000_000.0,
            "revenue_cagr_3yr": 0.14,
            "op_margin_avg_3yr": 0.21,
            "capex_pct_avg_3yr": 0.07,
            "da_pct_avg_3yr": 0.04,
            "effective_tax_rate_avg": 0.19,
            "total_debt": 250_000_000.0,
            "cash": 120_000_000.0,
            "shares_outstanding": 80_000_000.0,
            "run_id": 5,
            "source_file": "ciq_cleandata.xlsx",
            "as_of_date": "2025-12-31",
        },
    )
    monkeypatch.setattr(
        ia,
        "get_ciq_comps_valuation",
        lambda ticker, as_of_date=None: {
            "peer_median_tev_ebitda_ltm": 15.0,
            "run_id": 9,
            "source_file": "ciq_cleandata.xlsx",
            "as_of_date": "2025-12-31",
        },
    )
    monkeypatch.setattr(
        ia,
        "compute_wacc_from_yfinance",
        lambda ticker, hist=None: SimpleNamespace(
            wacc=0.09,
            cost_of_equity=0.11,
            beta_relevered=1.0,
            beta_unlevered_median=0.9,
            size_premium=0.01,
            equity_weight=0.8,
            peers_used=["TEST"],
        ),
    )
    monkeypatch.setattr(ia, "load_valuation_overrides", lambda: {"tickers": {}, "sectors": {}, "global": {}})

    out = build_valuation_inputs("TEST")

    assert out is not None
    assert out.model_applicability_status == "dcf_applicable"
    assert out.drivers.revenue_base == 800_000_000.0
    assert out.drivers.revenue_growth_near == 0.14
    assert out.drivers.ebit_margin_start == 0.21
    assert out.drivers.exit_multiple == 15.0
    assert out.source_lineage["revenue_base"] == "ciq"
    assert out.source_lineage["exit_multiple"] == "ciq_comps_tev_ebitda_ltm"


def test_build_valuation_inputs_uses_sector_exit_metric_multiple(monkeypatch):
    from src.stage_02_valuation import input_assembler as ia

    monkeypatch.setattr(
        ia.md_client,
        "get_market_data",
        lambda ticker, as_of_date=None: {
            "ticker": ticker,
            "name": "Energy Co",
            "sector": "Energy",
            "industry": "Oil & Gas",
            "current_price": 55.0,
            "revenue_ttm": 10_000_000_000.0,
            "operating_margin": 0.14,
            "revenue_growth": 0.04,
            "total_debt": 4_000_000_000.0,
            "cash": 500_000_000.0,
            "shares_outstanding": 1_200_000_000.0,
        },
    )
    monkeypatch.setattr(ia.md_client, "get_historical_financials", lambda ticker, as_of_date=None: {})
    monkeypatch.setattr(ia, "get_ciq_snapshot", lambda ticker, as_of_date=None: None)
    monkeypatch.setattr(
        ia,
        "get_ciq_comps_valuation",
        lambda ticker, as_of_date=None: {
            "peer_median_tev_ebitda_ltm": 7.0,
            "peer_median_tev_ebit_ltm": 10.5,
        },
    )
    monkeypatch.setattr(
        ia,
        "compute_wacc_from_yfinance",
        lambda ticker, hist=None: SimpleNamespace(
            wacc=0.10,
            cost_of_equity=0.12,
            beta_relevered=1.0,
            beta_unlevered_median=0.9,
            size_premium=0.01,
            equity_weight=0.7,
            peers_used=["XOM", "CVX"],
        ),
    )
    monkeypatch.setattr(ia, "load_valuation_overrides", lambda: {"tickers": {}, "sectors": {}, "global": {}})

    out = build_valuation_inputs("XOM")

    assert out is not None
    assert out.drivers.exit_metric == "ev_ebit"
    assert out.drivers.exit_multiple == 10.5
    assert out.source_lineage["exit_multiple"] == "ciq_comps_tev_ebit_ltm"

