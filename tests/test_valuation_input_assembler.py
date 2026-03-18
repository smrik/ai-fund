import pytest
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
    from src.stage_02_valuation.story_drivers import StoryDriverProfile
    monkeypatch.setattr(ia, "resolve_story_driver_profile", lambda ticker, sector: (StoryDriverProfile(), "story_global"))

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
    from src.stage_02_valuation.story_drivers import StoryDriverProfile
    monkeypatch.setattr(ia, "resolve_story_driver_profile", lambda ticker, sector: (StoryDriverProfile(), "story_global"))

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
    from src.stage_02_valuation.story_drivers import StoryDriverProfile
    monkeypatch.setattr(ia, "resolve_story_driver_profile", lambda ticker, sector: (StoryDriverProfile(), "story_global"))

    out = build_valuation_inputs("HMRG")

    assert out is not None
    assert out.drivers.ebit_margin_start == 0.35
    # margin_target = 0.5 × margin_start + 0.5 × sector_default = 0.5×0.35 + 0.5×0.20 = 0.275
    assert out.drivers.ebit_margin_target == pytest.approx(0.275, abs=0.001)


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


def test_nwc_drivers_use_ciq_and_blend_with_sector_targets(monkeypatch):
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

    # Tech sector defaults: dso=45, dio=35, dpo=38; CIQ starts: dso=55, dio=50, dpo=45
    # Blend: 70% sector + 30% company-specific
    assert out is not None
    assert out.drivers.dso_start == 55.0
    assert out.drivers.dio_start == 50.0
    assert out.drivers.dpo_start == 45.0
    assert out.drivers.dso_target == pytest.approx(45.0 * 0.7 + 55.0 * 0.3, abs=0.01)  # 48.0
    assert out.drivers.dio_target == pytest.approx(35.0 * 0.7 + 50.0 * 0.3, abs=0.01)  # 39.5
    assert out.drivers.dpo_target == pytest.approx(38.0 * 0.7 + 45.0 * 0.3, abs=0.01)  # 40.1
    assert out.source_lineage["dso_start"] == "ciq"
    assert out.source_lineage["dio_start"] == "ciq"
    assert out.source_lineage["dpo_start"] == "ciq"
    assert out.source_lineage["dso_target"] == "ciq_blend"
    assert out.source_lineage["dio_target"] == "ciq_blend"
    assert out.source_lineage["dpo_target"] == "ciq_blend"


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


# ── New tests for Phase 1/2 hardening ───────────────────────────────────────


def _make_wacc_stub():
    return SimpleNamespace(
        wacc=0.09,
        cost_of_equity=0.11,
        beta_relevered=1.0,
        beta_unlevered_median=0.9,
        size_premium=0.01,
        equity_weight=0.8,
        peers_used=["TEST"],
    )


def _make_mkt(sector="Technology", price=100.0, revenue=1_000_000_000.0):
    return {
        "ticker": "TEST",
        "name": "Test Co",
        "sector": sector,
        "industry": "Software",
        "current_price": price,
        "revenue_ttm": revenue,
        "operating_margin": 0.15,
        "revenue_growth": 0.08,
        "total_debt": 200_000_000.0,
        "cash": 50_000_000.0,
        "shares_outstanding": 100_000_000.0,
        "market_cap": 10_000_000_000.0,
        "enterprise_value": 10_150_000_000.0,
    }


def test_consensus_growth_takes_priority_over_ciq_cagr(monkeypatch):
    """1.1 — CIQ FY1 consensus implied growth beats backward-looking CAGR."""
    from src.stage_02_valuation import input_assembler as ia

    monkeypatch.setattr(ia.md_client, "get_market_data", lambda ticker, as_of_date=None: _make_mkt())
    monkeypatch.setattr(ia.md_client, "get_historical_financials", lambda ticker, as_of_date=None: {
        "revenue_cagr_3yr": 0.06,
    })
    monkeypatch.setattr(ia, "get_ciq_snapshot", lambda ticker, as_of_date=None: {
        "revenue_ttm": 1_000_000_000.0,
        "revenue_cagr_3yr": 0.10,
        "revenue_fy1": 1_200_000_000.0,  # 20% implied growth
    })
    monkeypatch.setattr(ia, "get_ciq_comps_valuation", lambda ticker, as_of_date=None: None)
    monkeypatch.setattr(ia, "compute_wacc_from_yfinance", lambda ticker, hist=None: _make_wacc_stub())
    monkeypatch.setattr(ia, "load_valuation_overrides", lambda: {"tickers": {}, "sectors": {}, "global": {}})
    from src.stage_02_valuation.story_drivers import StoryDriverProfile
    monkeypatch.setattr(ia, "resolve_story_driver_profile", lambda ticker, sector: (StoryDriverProfile(), "story_global"))

    out = build_valuation_inputs("TEST")

    assert out is not None
    assert out.source_lineage["growth_source_detail"] == "ciq_consensus"
    assert out.source_lineage["growth_period_type"] == "consensus_fy1"
    assert out.source_lineage["revenue_alignment_flag"] == "aligned_consensus"
    assert out.source_lineage["revenue_data_quality_flag"] == "ok"
    assert out.drivers.revenue_growth_near == pytest.approx(0.20, abs=0.001)


def test_consensus_growth_falls_back_to_ciq_cagr_when_fy1_missing(monkeypatch):
    """1.1 — No FY1 → falls through to CIQ CAGR."""
    from src.stage_02_valuation import input_assembler as ia

    monkeypatch.setattr(ia.md_client, "get_market_data", lambda ticker, as_of_date=None: _make_mkt())
    monkeypatch.setattr(ia.md_client, "get_historical_financials", lambda ticker, as_of_date=None: {})
    monkeypatch.setattr(ia, "get_ciq_snapshot", lambda ticker, as_of_date=None: {
        "revenue_ttm": 1_000_000_000.0,
        "revenue_cagr_3yr": 0.11,
        # no revenue_fy1
    })
    monkeypatch.setattr(ia, "get_ciq_comps_valuation", lambda ticker, as_of_date=None: None)
    monkeypatch.setattr(ia, "compute_wacc_from_yfinance", lambda ticker, hist=None: _make_wacc_stub())
    monkeypatch.setattr(ia, "load_valuation_overrides", lambda: {"tickers": {}, "sectors": {}, "global": {}})

    out = build_valuation_inputs("TEST")

    assert out is not None
    assert out.source_lineage["growth_source_detail"] == "ciq_cagr_3yr"


def test_forward_comps_take_priority_over_ltm_for_ev_ebitda(monkeypatch):
    """1.2 — Forward comps beat LTM when both present (ev_ebitda sector)."""
    from src.stage_02_valuation import input_assembler as ia
    from src.stage_02_valuation.story_drivers import StoryDriverProfile

    monkeypatch.setattr(ia.md_client, "get_market_data", lambda ticker, as_of_date=None: _make_mkt(sector="Technology"))
    monkeypatch.setattr(ia.md_client, "get_historical_financials", lambda ticker, as_of_date=None: {})
    monkeypatch.setattr(ia, "get_ciq_snapshot", lambda ticker, as_of_date=None: None)
    monkeypatch.setattr(ia, "get_ciq_comps_valuation", lambda ticker, as_of_date=None: {
        "peer_median_tev_ebitda_ltm": 18.0,
        "peer_median_tev_ebitda_fwd": 14.0,  # forward should win
    })
    monkeypatch.setattr(ia, "compute_wacc_from_yfinance", lambda ticker, hist=None: _make_wacc_stub())
    monkeypatch.setattr(ia, "load_valuation_overrides", lambda: {"tickers": {}, "sectors": {}, "global": {}})
    monkeypatch.setattr(ia, "resolve_story_driver_profile", lambda ticker, sector: (StoryDriverProfile(), "story_global"))

    out = build_valuation_inputs("TEST")

    assert out is not None
    assert out.drivers.exit_multiple == 14.0
    assert out.source_lineage["exit_multiple"] == "ciq_comps_tev_ebitda_fwd"


def test_forward_comps_take_priority_over_ltm_for_ev_ebit(monkeypatch):
    """1.2 — Forward comps beat LTM for ev_ebit sectors (e.g. Energy)."""
    from src.stage_02_valuation import input_assembler as ia
    from src.stage_02_valuation.story_drivers import StoryDriverProfile

    monkeypatch.setattr(ia.md_client, "get_market_data", lambda ticker, as_of_date=None: _make_mkt(sector="Energy", revenue=10_000_000_000.0))
    monkeypatch.setattr(ia.md_client, "get_historical_financials", lambda ticker, as_of_date=None: {})
    monkeypatch.setattr(ia, "get_ciq_snapshot", lambda ticker, as_of_date=None: None)
    monkeypatch.setattr(ia, "get_ciq_comps_valuation", lambda ticker, as_of_date=None: {
        "peer_median_tev_ebit_ltm": 11.0,
        "peer_median_tev_ebit_fwd": 8.5,  # forward should win
    })
    monkeypatch.setattr(ia, "compute_wacc_from_yfinance", lambda ticker, hist=None: _make_wacc_stub())
    monkeypatch.setattr(ia, "load_valuation_overrides", lambda: {"tickers": {}, "sectors": {}, "global": {}})
    monkeypatch.setattr(ia, "resolve_story_driver_profile", lambda ticker, sector: (StoryDriverProfile(), "story_global"))

    out = build_valuation_inputs("TEST")

    assert out is not None
    assert out.drivers.exit_multiple == 8.5
    assert out.source_lineage["exit_multiple"] == "ciq_comps_tev_ebit_fwd"


def test_forward_comps_fall_back_to_ltm_when_fwd_missing(monkeypatch):
    """1.2 — No forward comps → falls through to LTM as before."""
    from src.stage_02_valuation import input_assembler as ia
    from src.stage_02_valuation.story_drivers import StoryDriverProfile

    monkeypatch.setattr(ia.md_client, "get_market_data", lambda ticker, as_of_date=None: _make_mkt(sector="Technology"))
    monkeypatch.setattr(ia.md_client, "get_historical_financials", lambda ticker, as_of_date=None: {})
    monkeypatch.setattr(ia, "get_ciq_snapshot", lambda ticker, as_of_date=None: None)
    monkeypatch.setattr(ia, "get_ciq_comps_valuation", lambda ticker, as_of_date=None: {
        "peer_median_tev_ebitda_ltm": 16.0,
        # no fwd
    })
    monkeypatch.setattr(ia, "compute_wacc_from_yfinance", lambda ticker, hist=None: _make_wacc_stub())
    monkeypatch.setattr(ia, "load_valuation_overrides", lambda: {"tickers": {}, "sectors": {}, "global": {}})
    monkeypatch.setattr(ia, "resolve_story_driver_profile", lambda ticker, sector: (StoryDriverProfile(), "story_global"))

    out = build_valuation_inputs("TEST")

    assert out is not None
    assert out.drivers.exit_multiple == 16.0
    assert out.source_lineage["exit_multiple"] == "ciq_comps_tev_ebitda_ltm"


def test_nwc_target_is_pure_sector_default_when_no_company_data(monkeypatch):
    """1.4 — No company-specific NWC → target stays pure sector default."""
    from src.stage_02_valuation import input_assembler as ia

    monkeypatch.setattr(ia.md_client, "get_market_data", lambda ticker, as_of_date=None: _make_mkt())
    monkeypatch.setattr(ia.md_client, "get_historical_financials", lambda ticker, as_of_date=None: {})
    monkeypatch.setattr(ia, "get_ciq_snapshot", lambda ticker, as_of_date=None: None)
    monkeypatch.setattr(ia, "get_ciq_comps_valuation", lambda ticker, as_of_date=None: None)
    monkeypatch.setattr(ia, "compute_wacc_from_yfinance", lambda ticker, hist=None: _make_wacc_stub())
    monkeypatch.setattr(ia, "load_valuation_overrides", lambda: {"tickers": {}, "sectors": {}, "global": {}})

    out = build_valuation_inputs("TEST")

    assert out is not None
    # Tech sector defaults
    assert out.drivers.dso_target == 45.0
    assert out.drivers.dio_target == 35.0
    assert out.drivers.dpo_target == 38.0
    assert out.source_lineage["dso_target"] == "default"
    assert out.source_lineage["dio_target"] == "default"
    assert out.source_lineage["dpo_target"] == "default"


def test_tax_target_uses_company_etr(monkeypatch):
    """2.3 — tax_target converges to company's own ETR (bounded)."""
    from src.stage_02_valuation import input_assembler as ia

    monkeypatch.setattr(ia.md_client, "get_market_data", lambda ticker, as_of_date=None: _make_mkt())
    monkeypatch.setattr(ia.md_client, "get_historical_financials", lambda ticker, as_of_date=None: {
        "effective_tax_rate_avg": 0.17,
    })
    monkeypatch.setattr(ia, "get_ciq_snapshot", lambda ticker, as_of_date=None: None)
    monkeypatch.setattr(ia, "get_ciq_comps_valuation", lambda ticker, as_of_date=None: None)
    monkeypatch.setattr(ia, "compute_wacc_from_yfinance", lambda ticker, hist=None: _make_wacc_stub())
    monkeypatch.setattr(ia, "load_valuation_overrides", lambda: {"tickers": {}, "sectors": {}, "global": {}})

    out = build_valuation_inputs("TEST")

    assert out is not None
    assert out.drivers.tax_rate_start == pytest.approx(0.17, abs=0.001)
    assert out.drivers.tax_rate_target == pytest.approx(0.17, abs=0.001)
    assert out.source_lineage["tax_rate_target"] == "yfinance"


def test_tax_target_bounded_when_etr_very_low(monkeypatch):
    """2.3 — Very low ETR (e.g. 8%) → tax_target floors at 0.15."""
    from src.stage_02_valuation import input_assembler as ia

    monkeypatch.setattr(ia.md_client, "get_market_data", lambda ticker, as_of_date=None: _make_mkt())
    monkeypatch.setattr(ia.md_client, "get_historical_financials", lambda ticker, as_of_date=None: {
        "effective_tax_rate_avg": 0.08,
    })
    monkeypatch.setattr(ia, "get_ciq_snapshot", lambda ticker, as_of_date=None: None)
    monkeypatch.setattr(ia, "get_ciq_comps_valuation", lambda ticker, as_of_date=None: None)
    monkeypatch.setattr(ia, "compute_wacc_from_yfinance", lambda ticker, hist=None: _make_wacc_stub())
    monkeypatch.setattr(ia, "load_valuation_overrides", lambda: {"tickers": {}, "sectors": {}, "global": {}})

    out = build_valuation_inputs("TEST")

    assert out is not None
    # tax_start is bounded to (0.05, 0.40) → 0.08 passes through
    # tax_target is bounded (0.15, 0.30) → floors at 0.15
    assert out.drivers.tax_rate_target == pytest.approx(0.15, abs=0.001)


def test_revenue_growth_terminal_in_lineage(monkeypatch):
    """2.1 — revenue_growth_terminal appears in source_lineage."""
    from src.stage_02_valuation import input_assembler as ia

    monkeypatch.setattr(ia.md_client, "get_market_data", lambda ticker, as_of_date=None: _make_mkt())
    monkeypatch.setattr(ia.md_client, "get_historical_financials", lambda ticker, as_of_date=None: {})
    monkeypatch.setattr(ia, "get_ciq_snapshot", lambda ticker, as_of_date=None: None)
    monkeypatch.setattr(ia, "get_ciq_comps_valuation", lambda ticker, as_of_date=None: None)
    monkeypatch.setattr(ia, "compute_wacc_from_yfinance", lambda ticker, hist=None: _make_wacc_stub())
    monkeypatch.setattr(ia, "load_valuation_overrides", lambda: {"tickers": {}, "sectors": {}, "global": {}})

    out = build_valuation_inputs("TEST")

    assert out is not None
    assert "revenue_growth_terminal" in out.source_lineage
    assert out.source_lineage["revenue_growth_terminal"] == "default"


def test_growth_fade_ratio_differs_by_sector(monkeypatch):
    """2.2 — sector-specific fade ratio (Tech 0.70 vs Energy 0.50) produces different growth_mid."""
    from src.stage_02_valuation import input_assembler as ia

    def _build(sector, revenue):
        from src.stage_02_valuation.story_drivers import StoryDriverProfile
        monkeypatch.setattr(ia.md_client, "get_market_data", lambda ticker, as_of_date=None: _make_mkt(sector=sector, revenue=revenue))
        monkeypatch.setattr(ia.md_client, "get_historical_financials", lambda ticker, as_of_date=None: {"revenue_cagr_3yr": 0.10})
        monkeypatch.setattr(ia, "get_ciq_snapshot", lambda ticker, as_of_date=None: None)
        monkeypatch.setattr(ia, "get_ciq_comps_valuation", lambda ticker, as_of_date=None: None)
        monkeypatch.setattr(ia, "compute_wacc_from_yfinance", lambda ticker, hist=None: _make_wacc_stub())
        monkeypatch.setattr(ia, "load_valuation_overrides", lambda: {"tickers": {}, "sectors": {}, "global": {}})
        monkeypatch.setattr(ia, "resolve_story_driver_profile", lambda ticker, sector: (StoryDriverProfile(), "story_global"))
        return build_valuation_inputs("TEST")

    tech_out = _build("Technology", 1_000_000_000.0)
    energy_out = _build("Energy", 10_000_000_000.0)

    # Both have growth_near = 10%; Tech fades to 7.0%, Energy fades to 5.0%
    assert tech_out is not None and energy_out is not None
    assert tech_out.drivers.revenue_growth_mid == pytest.approx(0.10 * 0.70, abs=0.001)
    assert energy_out.drivers.revenue_growth_mid == pytest.approx(0.10 * 0.50, abs=0.001)


# ── P0: Lease double-count fix ───────────────────────────────────────────────


def test_lease_liabilities_zeroed_when_folded_into_net_debt(monkeypatch):
    """P0 — leases folded into net_debt must not also appear as standalone claim."""
    from src.stage_02_valuation import input_assembler as ia

    monkeypatch.setattr(
        ia.md_client,
        "get_market_data",
        lambda ticker, as_of_date=None: {
            "ticker": ticker,
            "name": "Lease Heavy Co",
            "sector": "Consumer Cyclical",
            "industry": "Retail",
            "current_price": 50.0,
            "revenue_ttm": 5_000_000_000.0,
            "operating_margin": 0.10,
            "revenue_growth": 0.04,
            "total_debt": 2_000_000_000.0,
            "cash": 300_000_000.0,
            "shares_outstanding": 500_000_000.0,
            "market_cap": 25_000_000_000.0,
        },
    )
    monkeypatch.setattr(
        ia.md_client,
        "get_historical_financials",
        lambda ticker, as_of_date=None: {
            # yfinance reports operating lease liability separately
            "lease_liabilities_bs": 1_500_000_000.0,
        },
    )
    monkeypatch.setattr(ia, "get_ciq_snapshot", lambda ticker, as_of_date=None: None)
    monkeypatch.setattr(ia, "get_ciq_comps_valuation", lambda ticker, as_of_date=None: None)
    monkeypatch.setattr(ia, "compute_wacc_from_yfinance", lambda ticker, hist=None: _make_wacc_stub())
    monkeypatch.setattr(ia, "load_valuation_overrides", lambda: {"tickers": {}, "sectors": {}, "global": {}})
    from src.stage_02_valuation.story_drivers import StoryDriverProfile
    monkeypatch.setattr(ia, "resolve_story_driver_profile", lambda ticker, sector: (StoryDriverProfile(), "story_global"))

    out = build_valuation_inputs("LSCO")

    assert out is not None
    # net_debt should include leases: (2000 - 300 + 1500) mm = 3200 mm
    assert out.source_lineage["net_debt"] == "yfinance+leases"
    # lease_liabilities field must be 0 — already captured in net_debt
    assert out.drivers.lease_liabilities == 0.0
    assert out.source_lineage["lease_liabilities"] == "folded_into_net_debt"
    assert out.drivers.net_debt == pytest.approx(3_200_000_000.0, rel=0.01)


# ── Gap 2: Story driver exit multiple ────────────────────────────────────────


def test_high_cyclicality_compresses_exit_multiple(monkeypatch):
    """Gap 2 — high cyclicality story should compress exit_multiple by ~10%."""
    from src.stage_02_valuation import input_assembler as ia
    from src.stage_02_valuation.story_drivers import StoryDriverProfile

    monkeypatch.setattr(ia.md_client, "get_market_data", lambda ticker, as_of_date=None: _make_mkt(sector="Industrials"))
    monkeypatch.setattr(ia.md_client, "get_historical_financials", lambda ticker, as_of_date=None: {})
    monkeypatch.setattr(ia, "get_ciq_snapshot", lambda ticker, as_of_date=None: None)
    # provide a fixed exit multiple so we can measure the compression
    monkeypatch.setattr(ia, "get_ciq_comps_valuation", lambda ticker, as_of_date=None: {
        "peer_median_tev_ebit_ltm": 10.0,
    })
    monkeypatch.setattr(ia, "compute_wacc_from_yfinance", lambda ticker, hist=None: _make_wacc_stub())
    monkeypatch.setattr(ia, "load_valuation_overrides", lambda: {"tickers": {}, "sectors": {}, "global": {}})
    # force high cyclicality story profile
    monkeypatch.setattr(
        ia,
        "resolve_story_driver_profile",
        lambda ticker, sector: (
            StoryDriverProfile(cyclicality="high", governance_risk="medium"),
            "story_ticker",
        ),
    )

    out = build_valuation_inputs("CYC")

    assert out is not None
    # cyc_exit_mult=0.90, gov_exit_mult=1.00 → 10.0 * 0.90 = 9.0
    assert out.drivers.exit_multiple == pytest.approx(9.0, abs=0.01)
    # lineage should record the story adjustment
    assert "story_ticker" in out.source_lineage["exit_multiple"]


def test_story_exit_multiple_unchanged_for_medium_cyclicality(monkeypatch):
    """Gap 2 — medium cyclicality + medium governance → no change to exit_multiple."""
    from src.stage_02_valuation import input_assembler as ia
    from src.stage_02_valuation.story_drivers import StoryDriverProfile

    monkeypatch.setattr(ia.md_client, "get_market_data", lambda ticker, as_of_date=None: _make_mkt(sector="Industrials"))
    monkeypatch.setattr(ia.md_client, "get_historical_financials", lambda ticker, as_of_date=None: {})
    monkeypatch.setattr(ia, "get_ciq_snapshot", lambda ticker, as_of_date=None: None)
    monkeypatch.setattr(ia, "get_ciq_comps_valuation", lambda ticker, as_of_date=None: {
        "peer_median_tev_ebit_ltm": 10.0,
    })
    monkeypatch.setattr(ia, "compute_wacc_from_yfinance", lambda ticker, hist=None: _make_wacc_stub())
    monkeypatch.setattr(ia, "load_valuation_overrides", lambda: {"tickers": {}, "sectors": {}, "global": {}})
    monkeypatch.setattr(
        ia,
        "resolve_story_driver_profile",
        lambda ticker, sector: (
            StoryDriverProfile(cyclicality="medium", governance_risk="medium"),
            "story_global",
        ),
    )

    out = build_valuation_inputs("NCYC")

    assert out is not None
    assert out.drivers.exit_multiple == pytest.approx(10.0, abs=0.01)
