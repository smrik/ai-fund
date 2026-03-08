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



def test_margin_target_reverts_to_sector_default(monkeypatch):
    from src.stage_02_valuation import input_assembler as ia

    monkeypatch.setattr(
        ia.md_client,
        "get_market_data",
        lambda ticker, as_of_date=None: {
            "ticker": ticker,
            "name": "High Margin Co",
            "sector": "Technology",
            "industry": "Software",
            "current_price": 120.0,
            "revenue_ttm": 2_000_000_000.0,
            "operating_margin": 0.35,
            "revenue_growth": 0.06,
            "total_debt": 100_000_000.0,
            "cash": 50_000_000.0,
            "shares_outstanding": 100_000_000.0,
        },
    )
    monkeypatch.setattr(ia.md_client, "get_historical_financials", lambda ticker, as_of_date=None: {})
    monkeypatch.setattr(ia, "get_ciq_snapshot", lambda ticker, as_of_date=None: None)
    monkeypatch.setattr(ia, "get_ciq_comps_valuation", lambda ticker, as_of_date=None: None)
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

    out = build_valuation_inputs("HMRG")

    assert out is not None
    assert out.drivers.ebit_margin_start == 0.35
    assert out.drivers.ebit_margin_target == 0.20


def test_net_debt_lineage_defaults_when_debt_and_cash_missing(monkeypatch):
    from src.stage_02_valuation import input_assembler as ia

    monkeypatch.setattr(
        ia.md_client,
        "get_market_data",
        lambda ticker, as_of_date=None: {
            "ticker": ticker,
            "name": "No Debt Data Co",
            "sector": "Industrials",
            "industry": "Machinery",
            "current_price": 50.0,
            "revenue_ttm": 1_000_000_000.0,
            "operating_margin": 0.12,
            "revenue_growth": 0.04,
            "total_debt": None,
            "cash": None,
            "shares_outstanding": 200_000_000.0,
        },
    )
    monkeypatch.setattr(ia.md_client, "get_historical_financials", lambda ticker, as_of_date=None: {})
    monkeypatch.setattr(ia, "get_ciq_snapshot", lambda ticker, as_of_date=None: None)
    monkeypatch.setattr(ia, "get_ciq_comps_valuation", lambda ticker, as_of_date=None: None)
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

    out = build_valuation_inputs("NODEBT")

    assert out is not None
    assert out.drivers.net_debt == 0.0
    assert out.source_lineage["net_debt"] == "default"


def test_nwc_drivers_use_ciq_then_revert_to_sector_targets(monkeypatch):
    from src.stage_02_valuation import input_assembler as ia

    monkeypatch.setattr(
        ia.md_client,
        "get_market_data",
        lambda ticker, as_of_date=None: {
            "ticker": ticker,
            "name": "NWC Co",
            "sector": "Technology",
            "industry": "Software",
            "current_price": 80.0,
            "revenue_ttm": 3_000_000_000.0,
            "operating_margin": 0.18,
            "revenue_growth": 0.10,
            "total_debt": 500_000_000.0,
            "cash": 200_000_000.0,
            "shares_outstanding": 150_000_000.0,
        },
    )
    monkeypatch.setattr(
        ia.md_client,
        "get_historical_financials",
        lambda ticker, as_of_date=None: {
            "dso_derived": 70.0,
            "dio_derived": 75.0,
            "dpo_derived": 80.0,
        },
    )
    monkeypatch.setattr(
        ia,
        "get_ciq_snapshot",
        lambda ticker, as_of_date=None: {
            "dso": 55.0,
            "dio": 50.0,
            "dpo": 45.0,
        },
    )
    monkeypatch.setattr(ia, "get_ciq_comps_valuation", lambda ticker, as_of_date=None: None)
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

    out = build_valuation_inputs("NWCX")

    assert out is not None
    assert out.drivers.dso_start == 55.0
    assert out.drivers.dio_start == 50.0
    assert out.drivers.dpo_start == 45.0
    assert out.drivers.dso_target == 45.0
    assert out.drivers.dio_target == 35.0
    assert out.drivers.dpo_target == 38.0
    assert out.source_lineage["dso_start"] == "ciq"
    assert out.source_lineage["dio_start"] == "ciq"
    assert out.source_lineage["dpo_start"] == "ciq"


def test_nwc_drivers_fallback_to_yfinance_and_respect_bounds(monkeypatch):
    from src.stage_02_valuation import input_assembler as ia

    monkeypatch.setattr(
        ia.md_client,
        "get_market_data",
        lambda ticker, as_of_date=None: {
            "ticker": ticker,
            "name": "Bounds Co",
            "sector": "Technology",
            "industry": "Software",
            "current_price": 95.0,
            "revenue_ttm": 4_000_000_000.0,
            "operating_margin": 0.16,
            "revenue_growth": 0.08,
            "total_debt": 300_000_000.0,
            "cash": 100_000_000.0,
            "shares_outstanding": 250_000_000.0,
        },
    )
    monkeypatch.setattr(
        ia.md_client,
        "get_historical_financials",
        lambda ticker, as_of_date=None: {
            "dso_derived": 500.0,
            "dio_derived": -10.0,
            "dpo_derived": 300.0,
        },
    )
    monkeypatch.setattr(ia, "get_ciq_snapshot", lambda ticker, as_of_date=None: None)
    monkeypatch.setattr(ia, "get_ciq_comps_valuation", lambda ticker, as_of_date=None: None)
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

    out = build_valuation_inputs("BNDX")

    assert out is not None
    assert out.drivers.dso_start == 180.0
    assert out.drivers.dio_start == 5.0
    assert out.drivers.dpo_start == 180.0
    assert out.source_lineage["dso_start"] == "yfinance"
    assert out.source_lineage["dio_start"] == "yfinance"
    assert out.source_lineage["dpo_start"] == "yfinance"


def test_revenue_alignment_flags_when_growth_comes_from_cagr(monkeypatch):
    from src.stage_02_valuation import input_assembler as ia

    monkeypatch.setattr(
        ia.md_client,
        "get_market_data",
        lambda ticker, as_of_date=None: {
            "ticker": ticker,
            "name": "Growth Co",
            "sector": "Technology",
            "industry": "Software",
            "current_price": 90.0,
            "revenue_ttm": 1_000_000_000.0,
            "operating_margin": 0.18,
            "revenue_growth": None,
            "total_debt": 200_000_000.0,
            "cash": 50_000_000.0,
            "shares_outstanding": 100_000_000.0,
        },
    )
    monkeypatch.setattr(
        ia.md_client,
        "get_historical_financials",
        lambda ticker, as_of_date=None: {
            "revenue_cagr_3yr": 0.11,
        },
    )
    monkeypatch.setattr(ia, "get_ciq_snapshot", lambda ticker, as_of_date=None: None)
    monkeypatch.setattr(ia, "get_ciq_comps_valuation", lambda ticker, as_of_date=None: None)
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

    out = build_valuation_inputs("GROW")

    assert out is not None
    assert out.source_lineage["growth_source_detail"] == "yfinance_cagr_3yr"
    assert out.source_lineage["revenue_period_type"] == "ttm"
    assert out.source_lineage["growth_period_type"] == "cagr_3yr"
    assert out.source_lineage["revenue_alignment_flag"] == "mixed_ttm_vs_cagr"
    assert out.source_lineage["revenue_data_quality_flag"] == "needs_review"



def test_revenue_alignment_flags_when_growth_comes_from_ttm_yoy(monkeypatch):
    from src.stage_02_valuation import input_assembler as ia

    monkeypatch.setattr(
        ia.md_client,
        "get_market_data",
        lambda ticker, as_of_date=None: {
            "ticker": ticker,
            "name": "Aligned Co",
            "sector": "Technology",
            "industry": "Software",
            "current_price": 90.0,
            "revenue_ttm": 1_000_000_000.0,
            "operating_margin": 0.18,
            "revenue_growth": 0.09,
            "total_debt": 200_000_000.0,
            "cash": 50_000_000.0,
            "shares_outstanding": 100_000_000.0,
        },
    )
    monkeypatch.setattr(ia.md_client, "get_historical_financials", lambda ticker, as_of_date=None: {})
    monkeypatch.setattr(ia, "get_ciq_snapshot", lambda ticker, as_of_date=None: None)
    monkeypatch.setattr(ia, "get_ciq_comps_valuation", lambda ticker, as_of_date=None: None)
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

    out = build_valuation_inputs("ALIGN")

    assert out is not None
    assert out.source_lineage["growth_source_detail"] == "yfinance_ttm_yoy"
    assert out.source_lineage["revenue_period_type"] == "ttm"
    assert out.source_lineage["growth_period_type"] == "ttm_yoy"
    assert out.source_lineage["revenue_alignment_flag"] == "aligned_ttm"
    assert out.source_lineage["revenue_data_quality_flag"] == "ok"
