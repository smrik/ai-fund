import ast
from pathlib import Path

import pytest
from types import SimpleNamespace

from src.stage_02_valuation.input_assembler import (
    build_valuation_inputs,
    determine_model_applicability,
    select_exit_metric_for_sector,
)
from src.stage_02_valuation.valuation_types import ForecastDrivers


def test_sector_exit_metric_mapping():
    assert select_exit_metric_for_sector("Technology") == "ev_ebitda"
    assert select_exit_metric_for_sector("Communication Services") == "ev_ebitda"
    assert select_exit_metric_for_sector("Energy") == "ev_ebit"
    assert select_exit_metric_for_sector("Basic Materials") == "ev_ebit"


def test_financials_and_reits_marked_alt_model_required():
    assert determine_model_applicability("Financial Services", "Banks - Regional") == "alt_model_required"
    assert determine_model_applicability("Real Estate", "REIT - Retail") == "alt_model_required"
    assert determine_model_applicability("Technology", "Software") == "dcf_applicable"


def test_apply_overrides_prefers_approved_assumption_register(monkeypatch):
    import db.loader as db_loader
    from src.stage_02_valuation import input_assembler as ia

    drivers = SimpleNamespace(ebit_margin_start=0.18)
    source_lineage = {"ebit_margin_start": "ciq"}
    monkeypatch.setattr(ia, "load_valuation_overrides", lambda: {"global": {}, "sectors": {}, "tickers": {"IBM": {"ebit_margin_start": 0.19}}})
    monkeypatch.setattr(db_loader, "get_approved_assumption_overrides", lambda ticker: {"ebit_margin_start": 0.21})

    ia._apply_overrides(drivers, source_lineage, ticker="IBM", sector="Technology")

    assert drivers.ebit_margin_start == pytest.approx(0.21)
    assert source_lineage["ebit_margin_start"] == "approved_assumption_register"


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
            "da_pct_avg_3yr": 0.0,
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
    da_event = next(
        event
        for event in out.clamp_events
        if event.field_name == "da_pct_start"
    )
    assert out.drivers.da_pct_start == 0.0
    assert da_event.raw_value == 0.0
    assert da_event.resolved_value == 0.0
    assert da_event.bound_hit is None
    assert da_event.source == "ciq"


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
    assert out.drivers.dso_start == 500.0
    assert out.drivers.dio_start == 0.0
    assert out.drivers.dpo_start == 300.0
    assert out.source_lineage["dso_start"] == "yfinance"
    assert out.source_lineage["dio_start"] == "yfinance"
    assert out.source_lineage["dpo_start"] == "yfinance"
    events = {event.field_name: event for event in out.clamp_events}
    assert events["dso_start"].raw_value == 500.0
    assert events["dso_start"].resolved_value == 500.0
    assert events["dso_start"].bound_hit is None
    assert events["dso_start"].source == "yfinance"
    assert events["dio_start"].bound_hit == "lower"
    assert events["dpo_start"].bound_hit is None


def test_historical_extremes_pass_through_and_forecast_bounds_remain_tight() -> None:
    from src.stage_02_valuation import input_assembler as ia

    events = []
    capex = ia._bounded(
        0.2533291124,
        0.01,
        0.25,
        0.06,
        field_name="capex_pct_start",
        source="filing",
        events=events,
    )
    dio = ia._bounded(
        1.5,
        5.0,
        220.0,
        35.0,
        field_name="dio_start",
        source="filing",
        events=events,
    )
    target = ia._bounded(
        0.30,
        0.005,
        0.25,
        0.06,
        field_name="capex_pct_target",
        source="judgment",
        events=events,
    )

    assert capex == pytest.approx(0.2533291124)
    assert dio == pytest.approx(1.5)
    assert events[0].was_clamped is False
    assert events[1].was_clamped is False
    assert target == pytest.approx(0.25)
    assert events[2].lower_bound == pytest.approx(0.005)
    assert events[2].upper_bound == pytest.approx(0.25)
    assert events[2].bound_hit == "upper"
    assert events[2].to_dict()["was_clamped"] is True


def test_erroneous_historical_sign_and_magnitude_are_still_clamped() -> None:
    from src.stage_02_valuation import input_assembler as ia

    events = []
    negative_margin = ia._bounded(
        -0.10,
        0.02,
        0.60,
        0.14,
        field_name="ebit_margin_start",
        source="filing",
        events=events,
    )
    negative_ratio = ia._bounded(
        -0.10,
        0.01,
        0.25,
        0.06,
        field_name="capex_pct_start",
        source="filing",
        events=events,
    )
    excessive_days = ia._bounded(
        900.0,
        5.0,
        180.0,
        50.0,
        field_name="dso_start",
        source="filing",
        events=events,
    )

    assert negative_margin == pytest.approx(0.0)
    assert negative_ratio == pytest.approx(0.0)
    assert excessive_days == pytest.approx(730.0)
    assert events[0].bound_hit == "lower"
    assert events[1].bound_hit == "lower"
    assert events[2].bound_hit == "upper"
    assert events[0].to_dict()["was_clamped"] is True
    assert events[1].to_dict()["was_clamped"] is True
    assert events[2].to_dict()["was_clamped"] is True


def test_every_bounded_call_emits_canonical_clamp_audit_metadata() -> None:
    from src.stage_02_valuation import input_assembler as ia

    tree = ast.parse(Path(ia.__file__).read_text(encoding="utf-8"))
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_bounded"
    ]

    assert calls, "input assembler must retain auditable bounded resolutions"
    driver_fields = set(ForecastDrivers.__dataclass_fields__)
    for call in calls:
        keywords = {
            keyword.arg: keyword.value
            for keyword in call.keywords
            if keyword.arg is not None
        }
        assert {"field_name", "source", "events"} <= set(keywords), (
            f"silent _bounded call at line {call.lineno}"
        )
        field_node = keywords["field_name"]
        assert isinstance(field_node, ast.Constant)
        assert field_node.value in driver_fields, (
            f"non-canonical clamp field at line {call.lineno}: "
            f"{field_node.value!r}"
        )


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


def test_exit_multiple_uses_comps_detail_median_before_sector_default(monkeypatch):
    from src.stage_02_valuation import input_assembler as ia
    from src.stage_02_valuation.story_drivers import StoryDriverProfile

    monkeypatch.setattr(ia.md_client, "get_market_data", lambda ticker, as_of_date=None: _make_mkt(sector="Technology"))
    monkeypatch.setattr(ia.md_client, "get_historical_financials", lambda ticker, as_of_date=None: {})
    monkeypatch.setattr(ia, "get_ciq_snapshot", lambda ticker, as_of_date=None: None)
    monkeypatch.setattr(ia, "get_ciq_comps_valuation", lambda ticker, as_of_date=None: None)
    monkeypatch.setattr(
        ia,
        "get_ciq_comps_detail",
        lambda ticker, as_of_date=None: {
            "medians": {"tev_ebitda_ltm": 13.25},
            "source_lineage": {"source": "public_market_yfinance_fallback"},
        },
    )
    monkeypatch.setattr(ia, "compute_wacc_from_yfinance", lambda ticker, hist=None: _make_wacc_stub())
    monkeypatch.setattr(ia, "load_valuation_overrides", lambda: {"tickers": {}, "sectors": {}, "global": {}})
    monkeypatch.setattr(ia, "resolve_story_driver_profile", lambda ticker, sector: (StoryDriverProfile(), "story_global"))

    out = build_valuation_inputs("TEST")

    assert out is not None
    assert out.drivers.exit_multiple == pytest.approx(13.25)
    assert out.source_lineage["exit_multiple"] == "public_market_yfinance_fallback_tev_ebitda_ltm"
    exit_item = next(item for item in out.default_resolution["fields"] if item["field"] == "exit_multiple")
    assert exit_item["needs_pm_review"] is False
    assert exit_item["source_class"] == "public_market"


def test_exit_multiple_uses_opt_in_public_peer_fallback_before_sector_default(monkeypatch):
    from src.stage_02_valuation import input_assembler as ia
    from src.stage_02_valuation.story_drivers import StoryDriverProfile

    monkeypatch.setattr(ia.md_client, "get_market_data", lambda ticker, as_of_date=None: _make_mkt(sector="Technology"))
    monkeypatch.setattr(ia.md_client, "get_historical_financials", lambda ticker, as_of_date=None: {})
    monkeypatch.setattr(ia, "get_ciq_snapshot", lambda ticker, as_of_date=None: None)
    monkeypatch.setattr(ia, "get_ciq_comps_valuation", lambda ticker, as_of_date=None: None)
    monkeypatch.setattr(ia, "get_ciq_comps_detail", lambda ticker, as_of_date=None: None)
    monkeypatch.setattr(
        ia.md_client,
        "get_peer_multiples",
        lambda peers: [
            {"ticker": "AAA", "market_cap_mm": 1000.0, "ev_ebitda": 10.0, "pe_trailing": 18.0},
            {"ticker": "BBB", "market_cap_mm": 1200.0, "ev_ebitda": 14.0, "pe_trailing": 20.0},
            {"ticker": "CCC", "market_cap_mm": 1400.0, "ev_ebitda": 16.0, "pe_trailing": 22.0},
        ],
    )
    monkeypatch.setattr(ia, "compute_wacc_from_yfinance", lambda ticker, hist=None: _make_wacc_stub())
    monkeypatch.setattr(
        ia,
        "load_valuation_overrides",
        lambda: {"tickers": {"TEST": {"public_comps_fallback": True}}, "sectors": {}, "global": {}},
    )
    monkeypatch.setattr(ia, "resolve_story_driver_profile", lambda ticker, sector: (StoryDriverProfile(), "story_global"))

    out = build_valuation_inputs(
        "TEST",
        allow_public_comps_fallback=True,
    )

    assert out is not None
    assert out.drivers.exit_multiple == pytest.approx(14.0)
    assert out.source_lineage["exit_multiple"] == "public_market_yfinance_fallback_tev_ebitda_ltm"
    assert out.ciq_lineage["public_comps_fallback_used"] is True
    assert out.ciq_lineage["public_comps_fallback_peer_count"] == 3
    assert out.default_resolution["status"] == "review_required"


def test_default_path_never_uses_legacy_public_peer_fallback(monkeypatch):
    from src.stage_02_valuation import input_assembler as ia
    from src.stage_02_valuation.story_drivers import StoryDriverProfile

    monkeypatch.setattr(
        ia.md_client,
        "get_market_data",
        lambda ticker, as_of_date=None: _make_mkt(sector="Technology"),
    )
    monkeypatch.setattr(
        ia.md_client,
        "get_historical_financials",
        lambda ticker, as_of_date=None: {},
    )
    monkeypatch.setattr(
        ia,
        "get_ciq_snapshot",
        lambda ticker, as_of_date=None: None,
    )
    monkeypatch.setattr(
        ia,
        "get_ciq_comps_valuation",
        lambda ticker, as_of_date=None: None,
    )
    monkeypatch.setattr(
        ia,
        "get_ciq_comps_detail",
        lambda ticker, as_of_date=None: None,
    )

    public_fallback_calls = 0

    def tracked_public_fallback(peers):
        nonlocal public_fallback_calls
        public_fallback_calls += 1
        return [
            {
                "ticker": "AAA",
                "market_cap_mm": 1000.0,
                "ev_ebitda": 10.0,
                "pe_trailing": 18.0,
            },
            {
                "ticker": "BBB",
                "market_cap_mm": 1200.0,
                "ev_ebitda": 14.0,
                "pe_trailing": 20.0,
            },
            {
                "ticker": "CCC",
                "market_cap_mm": 1400.0,
                "ev_ebitda": 16.0,
                "pe_trailing": 22.0,
            },
        ]

    monkeypatch.setattr(
        ia.md_client,
        "get_peer_multiples",
        tracked_public_fallback,
    )
    monkeypatch.setattr(
        ia,
        "compute_wacc_from_yfinance",
        lambda ticker, hist=None: _make_wacc_stub(),
    )
    monkeypatch.setattr(
        ia,
        "load_valuation_overrides",
        lambda: {
            "tickers": {"TEST": {"public_comps_fallback": True}},
            "sectors": {},
            "global": {},
        },
    )
    monkeypatch.setattr(
        ia,
        "resolve_story_driver_profile",
        lambda ticker, sector: (StoryDriverProfile(), "story_global"),
    )

    out = build_valuation_inputs("TEST")

    assert public_fallback_calls == 0
    assert out is not None
    assert out.drivers.exit_multiple == pytest.approx(
        ia.SECTOR_DEFAULTS["Technology"]["exit_multiple"]
    )
    assert out.source_lineage["exit_multiple"] == "default"
    assert out.ciq_lineage["public_comps_fallback_used"] is False
    assert out.ciq_lineage["public_comps_fallback_peer_count"] is None


def test_default_resolution_flags_material_unresolved_defaults(monkeypatch):
    from src.stage_02_valuation import input_assembler as ia
    from src.stage_02_valuation.story_drivers import StoryDriverProfile

    monkeypatch.setattr(ia.md_client, "get_market_data", lambda ticker, as_of_date=None: _make_mkt(sector="Technology"))
    monkeypatch.setattr(ia.md_client, "get_historical_financials", lambda ticker, as_of_date=None: {})
    monkeypatch.setattr(ia, "get_ciq_snapshot", lambda ticker, as_of_date=None: None)
    monkeypatch.setattr(ia, "get_ciq_comps_valuation", lambda ticker, as_of_date=None: None)
    monkeypatch.setattr(ia, "get_ciq_comps_detail", lambda ticker, as_of_date=None: None)
    monkeypatch.setattr(ia, "compute_wacc_from_yfinance", lambda ticker, hist=None: _make_wacc_stub())
    monkeypatch.setattr(ia, "load_valuation_overrides", lambda: {"tickers": {}, "sectors": {}, "global": {}})
    monkeypatch.setattr(ia, "resolve_story_driver_profile", lambda ticker, sector: (StoryDriverProfile(), "story_global"))

    out = build_valuation_inputs("TEST")

    assert out is not None
    assert out.default_resolution["status"] == "review_required_high"
    assert out.source_lineage["default_resolution_status"] == "review_required_high"
    exit_item = next(item for item in out.default_resolution["fields"] if item["field"] == "exit_multiple")
    assert exit_item["needs_pm_review"] is True
    assert exit_item["source_class"] == "missing_default"
    dpo_item = next(item for item in out.default_resolution["fields"] if item["field"] == "dpo_start")
    assert dpo_item["needs_pm_review"] is True


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


def test_yfinance_lease_split_keeps_equity_bridge_unchanged(monkeypatch):
    """Leases stay separate and every debt/cash balance is consumed exactly once."""
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
    assert (
        out.source_lineage["net_debt"]
        == "yfinance_debt_ex_leases_minus_operating_cash"
    )
    assert out.drivers.net_debt == pytest.approx(1_900_000_000.0)
    assert out.drivers.lease_liabilities == pytest.approx(1_500_000_000.0)
    assert out.source_lineage["lease_liabilities"] == "yfinance_separate_claim"
    assert out.drivers.non_operating_assets == pytest.approx(200_000_000.0)
    assert (
        out.drivers.net_debt
        + out.drivers.lease_liabilities
        - out.drivers.non_operating_assets
        == pytest.approx(3_200_000_000.0)
    )


# ── Gap 2: Story driver exit multiple ────────────────────────────────────────


def test_story_profile_is_context_only_in_official_numeric_inputs(monkeypatch):
    """Forward values stay mechanical until the judgment layer authors them."""
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
    assert out.drivers.exit_multiple == pytest.approx(10.0, abs=0.01)
    assert out.story_adjustments is None
    assert out.source_lineage["story_profile"] == "story_ticker"
    assert "story_ticker" not in out.source_lineage["exit_multiple"]


def test_sector_story_provenance_compresses_exit_multiple_less_than_reasoned(monkeypatch):
    """A sector row scores every ticker in the sector alike, so it must not swing the model
    as hard as an assessment of one business. Same profile, weaker provenance, smaller move."""
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
            StoryDriverProfile(cyclicality="high", governance_risk="medium"),
            "story_sector",
        ),
    )

    out = build_valuation_inputs("CYC", apply_story_overlay=True)

    assert out is not None
    # authority 0.4 → multiplier is 1.0 + (0.85 - 1.0) * 0.4 = 0.94 → 10.0 * 0.94 = 9.4
    assert out.drivers.exit_multiple == pytest.approx(9.4, abs=0.01)


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


def _lease_case(monkeypatch, *, ciq_snapshot, hist):
    """Assemble drivers with a controlled debt/lease source, returning (drivers, lineage)."""
    out = _lease_inputs_case(
        monkeypatch,
        ciq_snapshot=ciq_snapshot,
        hist=hist,
    )
    return out.drivers, out.source_lineage


def _lease_inputs_case(
    monkeypatch,
    *,
    ciq_snapshot,
    hist,
    overrides=None,
    ciq_comps=None,
):
    """Assemble a full valuation-input artifact with controlled bridge sources."""
    from src.stage_02_valuation import input_assembler as ia

    monkeypatch.setattr(ia.md_client, "get_market_data", lambda ticker, as_of_date=None: _make_mkt())
    monkeypatch.setattr(ia.md_client, "get_historical_financials", lambda ticker, as_of_date=None: hist)
    monkeypatch.setattr(ia, "get_ciq_snapshot", lambda ticker, as_of_date=None: ciq_snapshot)
    monkeypatch.setattr(
        ia,
        "get_ciq_comps_valuation",
        lambda ticker, as_of_date=None: ciq_comps,
    )
    monkeypatch.setattr(ia, "get_ciq_comps_detail", lambda ticker, as_of_date=None: None)
    monkeypatch.setattr(ia, "get_bridge_items_from_xbrl", lambda ticker: {})
    monkeypatch.setattr(ia, "compute_wacc_from_yfinance", lambda ticker, hist=None: _make_wacc_stub())
    monkeypatch.setattr(
        ia,
        "load_valuation_overrides",
        lambda: overrides or {"tickers": {}, "sectors": {}, "global": {}},
    )

    out = ia.build_valuation_inputs("LEASE")
    assert out is not None
    return out


def test_ciq_bridge_uses_split_cash_and_lease_claims_exactly_once(monkeypatch):
    """The PM split convention changes presentation, never the total debt-minus-cash claim."""

    out = _lease_inputs_case(
        monkeypatch,
        ciq_snapshot={
            "revenue_ttm": 318_273_000_000.0,
            "total_debt": 125_432_000_000.0,
            "cash": 32_105_000_000.0,
            "lease_liabilities": 85_170_000_000.0,
            "shares_outstanding": 7_432_000_000.0,
        },
        hist={},
    )

    operating_cash = 0.02 * 318_273_000_000.0
    excess_cash = 32_105_000_000.0 - operating_cash
    debt_ex_leases = 125_432_000_000.0 - 85_170_000_000.0

    assert out.drivers.net_debt == pytest.approx(debt_ex_leases - operating_cash)
    assert out.drivers.lease_liabilities == pytest.approx(85_170_000_000.0)
    assert out.drivers.non_operating_assets == pytest.approx(excess_cash)
    bridge_adjustment = (
        out.drivers.net_debt
        + out.drivers.lease_liabilities
        - out.drivers.non_operating_assets
    )
    assert bridge_adjustment == pytest.approx(93_327_000_000.0)
    assert out.claim_ledger["reconciliation"]["is_reconciled"] is True
    assert out.claim_ledger["reconciliation"]["is_decision_grade"] is True
    assert out.bridge_cutover["mode"] == "shadow"
    assert out.bridge_cutover["reconciled"]["ev_to_equity_adjustment_usd"] == (
        pytest.approx(93_327_000_000.0)
    )
    assert out.bridge_cutover["legacy"]["ev_to_equity_adjustment_usd"] == (
        pytest.approx(67_587_460_000.0)
    )
    assert out.valuation_status == "provisional"
    assert "readiness.not_supplied" in out.valuation_readiness["reason_codes"]
    assert out.operating_cash_policy == {
        "policy": "min(total_cash, revenue_base * rate)",
        "rate": 0.02,
        "source": "pm_decision_2026-07-25",
        "operating_cash_usd": pytest.approx(operating_cash),
        "classification_range_usd": [0.0, pytest.approx(operating_cash)],
        "equity_value_effect_range_usd": [0.0, 0.0],
    }


def test_ciq_comps_prices_use_same_full_reconciled_bridge_as_dcf(monkeypatch):
    out = _lease_inputs_case(
        monkeypatch,
        ciq_snapshot={
            "revenue_ttm": 10_000_000_000.0,
            "total_debt": 2_000_000_000.0,
            "cash": 1_000_000_000.0,
            "lease_liabilities": 200_000_000.0,
            "minority_interest": 300_000_000.0,
            "shares_outstanding": 100_000_000.0,
        },
        hist={},
        ciq_comps={
            "peer_median_tev_ebitda_ltm": 10.0,
            "target_ebitda_ltm": 1_000_000_000.0,
            "target_shares_out": 100_000_000.0,
            "target_net_debt": 1_000_000_000.0,
            "implied_price_ev_ebitda": 90.0,
            "implied_price_base": 90.0,
        },
    )

    # 10x $1bn less debt/cash plus the $300m minority claim.
    assert out.ciq_lineage["comps_iv_ev_ebitda"] == pytest.approx(87.0)
    assert out.ciq_lineage["comps_iv_base"] == pytest.approx(87.0)
    assert out.ciq_lineage["comps_bridge_basis"] == (
        "reconciled_claim_ledger"
    )
    assert out.ciq_lineage["comps_ev_to_equity_adjustment_usd"] == (
        pytest.approx(1_300_000_000.0)
    )


def test_bridge_assembly_fails_closed_with_named_untied_reported_line(monkeypatch):
    with pytest.raises(ValueError) as exc_info:
        _lease_inputs_case(
            monkeypatch,
            ciq_snapshot={
                "total_debt": 100_000_000.0,
                "cash": 50_000_000.0,
                "lease_liabilities": 500_000_000.0,
                "shares_outstanding": 100_000_000.0,
            },
            hist={},
        )

    message = str(exc_info.value)
    assert "total_debt" in message
    assert "does not tie" in message
    assert "reported=" in message
    assert "allocated=" in message


def test_raw_bridge_override_is_rejected_before_driver_mutation(monkeypatch):
    from src.stage_02_valuation.input_assembler import BridgeMutationPathError

    with pytest.raises(BridgeMutationPathError) as exc_info:
        _lease_inputs_case(
            monkeypatch,
            ciq_snapshot={
                "revenue_ttm": 10_000_000_000.0,
                "total_debt": 2_000_000_000.0,
                "cash": 1_000_000_000.0,
                "lease_liabilities": 200_000_000.0,
                "shares_outstanding": 100_000_000.0,
            },
            hist={},
            overrides={
                "global": {},
                "sectors": {},
                "tickers": {
                    "LEASE": {"lease_liabilities": 2_500_000_000.0}
                },
            },
        )

    assert exc_info.value.fields == ("lease_liabilities",)
    assert exc_info.value.to_dict()["reason_code"] == (
        "bridge_mutation_requires_reconciled_claim_ledger"
    )


def test_snapshot_investment_is_unclaimed_and_blocks_decision_grade(monkeypatch):
    out = _lease_inputs_case(
        monkeypatch,
        ciq_snapshot={
            "as_of_date": "2025-12-31",
            "currency": "USD",
            "revenue_ttm": 10_000_000_000.0,
            "total_debt": 2_000_000_000.0,
            "cash": 1_000_000_000.0,
            "lease_liabilities": 200_000_000.0,
            "shares_outstanding": 100_000_000.0,
            "investments": 500_000_000.0,
        },
        hist={},
    )

    reported = {
        line["line_id"]: line for line in out.claim_ledger["reported_lines"]
    }
    assert reported["ciq:investments"]["semantic_type"] == "asset"
    allocation = next(
        item
        for item in out.claim_ledger["allocations"]
        if item["allocation_id"] == "ciq:investments"
    )
    assert allocation["component"] == "unclaimed"
    assert out.claim_ledger["reconciliation"][
        "material_unclaimed_allocation_ids"
    ] == ["ciq:investments"]
    assert out.claim_ledger["reconciliation"]["is_reconciled"] is True
    assert out.claim_ledger["reconciliation"]["is_decision_grade"] is False
    assert out.valuation_status == "blocked"
    assert "ciq:investments" in " ".join(
        out.valuation_readiness["reason_codes"]
    )


def test_snapshot_bridge_metadata_mismatch_fails_with_named_line(monkeypatch):
    with pytest.raises(ValueError) as exc_info:
        _lease_inputs_case(
            monkeypatch,
            ciq_snapshot={
                "as_of_date": "2025-12-31",
                "currency": "USD",
                "revenue_ttm": 10_000_000_000.0,
                "total_debt": 2_000_000_000.0,
                "cash": 1_000_000_000.0,
                "lease_liabilities": 200_000_000.0,
                "shares_outstanding": 100_000_000.0,
                "bridge_unclaimed_lines": [
                    {
                        "line_id": "ciq:foreign_investment",
                        "value": 500_000_000.0,
                        "source_ref": "ciq:foreign_investment",
                        "currency": "EUR",
                        "period_end": "2025-12-31",
                        "period_type": "instant",
                        "semantic_type": "asset",
                    }
                ],
            },
            hist={},
        )

    assert "currency mismatch" in str(exc_info.value)
    assert "ciq:foreign_investment" in str(exc_info.value)


def test_bridge_override_without_claim_reclassification_fails_closed(monkeypatch):
    with pytest.raises(ValueError) as exc_info:
        _lease_inputs_case(
            monkeypatch,
            ciq_snapshot={
                "revenue_ttm": 1_000_000_000.0,
                "total_debt": 200_000_000.0,
                "cash": 50_000_000.0,
                "shares_outstanding": 100_000_000.0,
            },
            hist={},
            overrides={
                "global": {},
                "sectors": {},
                "tickers": {
                    "LEASE": {
                        "non_operating_assets": 111_955_000_000.0,
                    }
                },
            },
        )

    message = str(exc_info.value)
    assert "non_operating_assets" in message
    assert "does not tie" in message


def test_other_bridge_claim_override_must_tie_to_reported_source(monkeypatch):
    with pytest.raises(ValueError) as exc_info:
        _lease_inputs_case(
            monkeypatch,
            ciq_snapshot={
                "revenue_ttm": 1_000_000_000.0,
                "total_debt": 200_000_000.0,
                "cash": 50_000_000.0,
                "shares_outstanding": 100_000_000.0,
            },
            hist={},
            overrides={
                "global": {},
                "sectors": {},
                "tickers": {
                    "LEASE": {
                        "minority_interest": 500_000_000.0,
                    }
                },
            },
        )

    message = str(exc_info.value)
    assert "minority_interest" in message
    assert "does not tie" in message


def test_ciq_leases_are_not_double_counted(monkeypatch):
    """CIQ's `debt` already includes leases. Leaving `lease_liabilities` populated as well made
    `_claims_total()` count them twice — measured at ~$7.06/share on MSFT."""
    drivers, lineage = _lease_case(
        monkeypatch,
        ciq_snapshot={
            # CIQ reports raw dollars; `total_debt` already contains the 851m of leases.
            "total_debt": 1_254_000_000.0,
            "cash": 321_000_000.0,
            "lease_liabilities": 851_000_000.0,
            "shares_outstanding": 100_000_000.0,
        },
        hist={},
    )

    assert drivers.lease_liabilities == 851_000_000.0
    assert lineage["lease_liabilities"] == "ciq_separate_claim"
    assert drivers.net_debt == pytest.approx(403_000_000.0 - 20_000_000.0)
    assert drivers.non_operating_assets == pytest.approx(301_000_000.0)
    assert (
        drivers.net_debt
        + drivers.lease_liabilities
        - drivers.non_operating_assets
        == pytest.approx(1_254_000_000.0 - 321_000_000.0)
    )


def test_yfinance_leases_are_a_separate_claim(monkeypatch):
    """Public-market debt ex leases and leases remain separate but reconcile."""
    drivers, lineage = _lease_case(
        monkeypatch,
        ciq_snapshot=None,
        hist={"lease_liabilities_bs": 851_000_000.0},
    )

    assert drivers.lease_liabilities == 851_000_000.0
    assert lineage["lease_liabilities"] == "yfinance_separate_claim"
    assert (
        lineage["net_debt"]
        == "yfinance_debt_ex_leases_minus_operating_cash"
    )
    assert drivers.net_debt == pytest.approx(200_000_000.0 - 20_000_000.0)
    assert drivers.non_operating_assets == pytest.approx(30_000_000.0)
    assert (
        drivers.net_debt
        + drivers.lease_liabilities
        - drivers.non_operating_assets
        == pytest.approx(200_000_000.0 - 50_000_000.0 + 851_000_000.0)
    )


def test_no_lease_data_leaves_the_claim_untouched(monkeypatch):
    """Absent lease data must not invent a lineage marker."""
    drivers, lineage = _lease_case(
        monkeypatch,
        ciq_snapshot={"total_debt": 400_000_000.0, "cash": 100_000_000.0, "shares_outstanding": 100_000_000.0},
        hist={},
    )
    assert drivers.lease_liabilities == 0.0
    assert lineage["lease_liabilities"] == "default"
