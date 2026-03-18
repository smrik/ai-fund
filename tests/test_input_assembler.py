"""
Tests for bridge field source priority in build_valuation_inputs().
Mocked — no network calls.
"""
from __future__ import annotations

import sys
import os
import unittest.mock as mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.stage_02_valuation.input_assembler import build_valuation_inputs
from src.stage_02_valuation.story_drivers import StoryDriverProfile


# ── Minimal stubs ──────────────────────────────────────────────────────────────

def _make_mkt(ticker="FAKE"):
    return {
        "ticker": ticker,
        "name": "Fake Corp",
        "sector": "Technology",
        "industry": "Software",
        "current_price": 100.0,
        "market_cap": 50_000e6,
        "enterprise_value": 52_000e6,
        "revenue_ttm": 10_000e6,
        "ebitda_ttm": 2_000e6,
        "total_debt": 2_500e6,
        "cash": 500e6,
        "shares_outstanding": 500e6,
        "beta": 1.2,
        "trailingPE": None,
        "forwardPE": None,
        "revenue_growth": 0.10,
        "operating_margin": 0.20,
        "profit_margin": 0.15,
        "free_cashflow": 1_500e6,
        "analyst_target_mean": None,
        "analyst_recommendation": None,
        "number_of_analysts": None,
    }


def _make_hist(
    minority_interest_bs=None,
    preferred_equity_bs=None,
    lease_liabilities_bs=None,
    sbc=None,
    diluted_shares=None,
):
    return {
        "revenue": [10_000e6, 9_000e6, 8_000e6],
        "operating_income": [2_000e6, 1_800e6, 1_600e6],
        "net_income": [1_500e6, 1_350e6, 1_200e6],
        "cffo": [1_800e6, 1_620e6, 1_440e6],
        "capex": [500e6, 450e6, 400e6],
        "da": [300e6, 270e6, 240e6],
        "nwc_change": [100e6, 90e6],
        "interest_expense": [80e6, 72e6, 64e6],
        "revenue_cagr_3yr": 0.1180,
        "op_margin_avg_3yr": 0.20,
        "capex_pct_avg_3yr": 0.05,
        "da_pct_avg_3yr": 0.03,
        "nwc_pct_avg_3yr": 0.01,
        "effective_tax_rate_avg": 0.22,
        "cost_of_debt_derived": 0.03,
        "dso_derived": 45.0,
        "dio_derived": 35.0,
        "dpo_derived": 38.0,
        "minority_interest_bs": minority_interest_bs,
        "preferred_equity_bs": preferred_equity_bs,
        "lease_liabilities_bs": lease_liabilities_bs,
        "sbc": sbc,
        "diluted_shares": diluted_shares,
    }


def _wacc_result():
    r = mock.MagicMock()
    r.wacc = 0.09
    r.cost_of_equity = 0.11
    r.equity_weight = 0.80
    r.debt_weight = 0.20
    r.beta_relevered = 1.2
    r.beta_unlevered_median = 0.9
    r.size_premium = 0.01
    r.peers_used = []
    return r


def _patch_all(hist_kwargs=None, ciq=None, edgar_bridge=None):
    """Return a context manager combo for patching all external calls."""
    import contextlib

    hist = _make_hist(**(hist_kwargs or {}))
    mkt = _make_mkt()

    wacc_r = _wacc_result()
    wacc_results = {"peer_bottom_up": wacc_r, "single_capm": wacc_r}

    @contextlib.contextmanager
    def _ctx():
        with (
            mock.patch("src.stage_02_valuation.input_assembler.md_client.get_market_data", return_value=mkt),
            mock.patch("src.stage_02_valuation.input_assembler.md_client.get_historical_financials", return_value=hist),
            mock.patch("src.stage_02_valuation.input_assembler.get_ciq_snapshot", return_value=ciq),
            mock.patch("src.stage_02_valuation.input_assembler.get_ciq_comps_valuation", return_value=None),
            mock.patch("src.stage_02_valuation.input_assembler.get_ciq_comps_detail", return_value=None),
            mock.patch("src.stage_02_valuation.input_assembler.get_bridge_items_from_xbrl", return_value=edgar_bridge or {}),
            mock.patch("src.stage_02_valuation.input_assembler.compute_wacc_methodology_set_for_ticker", return_value=wacc_results),
            mock.patch("src.stage_02_valuation.input_assembler.resolve_story_driver_profile", return_value=(StoryDriverProfile(), "default")),
            mock.patch("src.stage_02_valuation.input_assembler.apply_story_driver_adjustments", return_value={"growth_add": 0.0, "margin_add": 0.0, "cyclicality_growth_multiplier": 1.0, "cyclicality_wacc_add": 0.0, "governance_wacc_add": 0.0, "capex_target_add": 0.0, "da_target_add": 0.0}),
        ):
            yield

    return _ctx()


# ── Tests ───────────────────────────────────────────────────────────────────────

def test_minority_interest_from_yfinance():
    """When CIQ is absent but yfinance has minority_interest_bs, source = yfinance."""
    with _patch_all(hist_kwargs={"minority_interest_bs": 2_000e6}):
        result = build_valuation_inputs("FAKE", apply_overrides=False)

    assert result is not None
    assert result.drivers.minority_interest > 0
    assert result.source_lineage["minority_interest"] == "yfinance"


def test_minority_interest_from_edgar_xbrl():
    """When yfinance is absent, EDGAR XBRL minority_interest is used."""
    with _patch_all(edgar_bridge={"minority_interest": 1_500e6}):
        result = build_valuation_inputs("FAKE", apply_overrides=False)

    assert result is not None
    assert result.drivers.minority_interest > 0
    assert result.source_lineage["minority_interest"] == "edgar_xbrl"


def test_lease_liabilities_from_yfinance():
    """P0 fix: when yfinance is net_debt source, leases are folded into net_debt (not double-counted)."""
    with _patch_all(hist_kwargs={"lease_liabilities_bs": 5_000e6}):
        result = build_valuation_inputs("FAKE", apply_overrides=False)

    assert result is not None
    # Leases folded into net_debt — standalone field must be zero to prevent double-count
    assert result.drivers.lease_liabilities == 0.0
    assert result.source_lineage["lease_liabilities"] == "folded_into_net_debt"
    assert result.source_lineage["net_debt"] == "yfinance+leases"


def test_lease_liabilities_from_edgar():
    """P0 fix: EDGAR lease liabilities are also folded when yfinance is net_debt source."""
    with _patch_all(edgar_bridge={"lease_liabilities": 4_000e6}):
        result = build_valuation_inputs("FAKE", apply_overrides=False)

    assert result is not None
    # EDGAR leases folded into yfinance net_debt — standalone field must be zero
    assert result.drivers.lease_liabilities == 0.0
    assert result.source_lineage["lease_liabilities"] == "folded_into_net_debt"
    assert result.source_lineage["net_debt"] == "yfinance+leases"


def test_options_value_sbc_proxy():
    """When no CIQ options_value, SBC × 3 is used as proxy (raw dollars)."""
    with _patch_all(hist_kwargs={"sbc": 1_000e6}):
        result = build_valuation_inputs("FAKE", apply_overrides=False)

    assert result is not None
    # 3 × $1B SBC = $3B proxy — within bounds (revenue_base × 2 = $20B)
    assert abs(result.drivers.options_value - 3_000e6) < 1
    assert result.source_lineage["options_value"] == "sbc_proxy"


def test_diluted_shares_preferred_over_basic():
    """diluted_shares from hist preferred over basic sharesOutstanding from mkt."""
    with _patch_all(hist_kwargs={"diluted_shares": 600e6}):
        result = build_valuation_inputs("FAKE", apply_overrides=False)

    assert result is not None
    # diluted = 600mm; mkt basic = 500mm — diluted should win
    assert abs(result.drivers.shares_outstanding - 600e6) < 1
    assert result.source_lineage["shares_outstanding"] == "yfinance_diluted"


def test_no_bridge_data_defaults_to_zero():
    """With no CIQ, yfinance, or EDGAR data, bridge items default to 0."""
    with _patch_all():
        result = build_valuation_inputs("FAKE", apply_overrides=False)

    assert result is not None
    assert result.drivers.minority_interest == 0.0
    assert result.drivers.preferred_equity == 0.0
    assert result.drivers.lease_liabilities == 0.0
    assert result.source_lineage["minority_interest"] == "default"


def test_net_debt_includes_leases_when_yfinance_source():
    """#1: Lease liabilities are added to yfinance net debt (yfinance excludes op leases)."""
    # mkt: total_debt=2500e6, cash=500e6 → raw net_debt = 2000e6
    # lease_liabilities_bs = 5000e6 → adjusted net_debt = 7000e6
    with _patch_all(hist_kwargs={"lease_liabilities_bs": 5_000e6}):
        result = build_valuation_inputs("FAKE", apply_overrides=False)

    assert result is not None
    assert abs(result.drivers.net_debt - 7_000e6) < 1
    assert result.source_lineage["net_debt"] == "yfinance+leases"


def test_margin_target_blends_company_and_sector():
    """#3: margin_target = 0.5×margin_start + 0.5×sector_default."""
    # margin_start from yfinance op_margin_avg_3yr = 0.35 (35%)
    # sector default for Technology = 0.20 (20%)
    # expected target = 0.5×0.35 + 0.5×0.20 = 0.275 (27.5%)
    with _patch_all(hist_kwargs={}):
        result = build_valuation_inputs("FAKE", apply_overrides=False)

    assert result is not None
    # margin_start = 0.20 (from op_margin_avg_3yr in _make_hist)
    # sector default = 0.20 → target = 0.5*0.20 + 0.5*0.20 = 0.20
    assert abs(result.drivers.ebit_margin_target - 0.20) < 0.001


def test_margin_target_blends_when_company_differs_from_sector():
    """#3: A high-margin company's target is blended, not forced to sector default."""
    # Force margin_start high via mkt operating_margin
    import unittest.mock as mock2
    from src.stage_02_valuation.story_drivers import StoryDriverProfile

    high_margin_mkt = _make_mkt()
    high_margin_mkt["operating_margin"] = 0.40  # 40% margin
    wacc_r = _wacc_result()
    wacc_results = {"peer_bottom_up": wacc_r, "single_capm": wacc_r}

    hist = _make_hist()
    hist["op_margin_avg_3yr"] = 0.40  # ensure it's picked up

    with (
        mock2.patch("src.stage_02_valuation.input_assembler.md_client.get_market_data", return_value=high_margin_mkt),
        mock2.patch("src.stage_02_valuation.input_assembler.md_client.get_historical_financials", return_value=hist),
        mock2.patch("src.stage_02_valuation.input_assembler.get_ciq_snapshot", return_value=None),
        mock2.patch("src.stage_02_valuation.input_assembler.get_ciq_comps_valuation", return_value=None),
        mock2.patch("src.stage_02_valuation.input_assembler.get_ciq_comps_detail", return_value=None),
        mock2.patch("src.stage_02_valuation.input_assembler.get_bridge_items_from_xbrl", return_value={}),
        mock2.patch("src.stage_02_valuation.input_assembler.compute_wacc_methodology_set_for_ticker", return_value=wacc_results),
        mock2.patch("src.stage_02_valuation.input_assembler.resolve_story_driver_profile", return_value=(StoryDriverProfile(), "default")),
        mock2.patch("src.stage_02_valuation.input_assembler.apply_story_driver_adjustments", return_value={"growth_add": 0.0, "margin_add": 0.0, "cyclicality_growth_multiplier": 1.0, "cyclicality_wacc_add": 0.0, "governance_wacc_add": 0.0, "capex_target_add": 0.0, "da_target_add": 0.0}),
    ):
        result = build_valuation_inputs("FAKE", apply_overrides=False)

    assert result is not None
    # sector default = 0.20, margin_start = 0.40 → target = 0.5*0.40 + 0.5*0.20 = 0.30
    assert abs(result.drivers.ebit_margin_target - 0.30) < 0.001


def test_ciq_takes_priority_over_yfinance_bridge():
    """CIQ minority_interest takes priority over yfinance balance sheet value."""
    ciq_snap = {
        "minority_interest": 3_000e6,  # raw dollars (adapter multiplies mm×1e6)
        "revenue_ttm": 10_000e6,
        "cash": None,
        "total_debt": None,
        "shares_outstanding": None,
        "as_of_date": None,
        "run_id": None,
        "source_file": None,
    }
    with _patch_all(hist_kwargs={"minority_interest_bs": 2_000e6}, ciq=ciq_snap):
        result = build_valuation_inputs("FAKE", apply_overrides=False)

    assert result is not None
    assert result.source_lineage["minority_interest"] == "ciq"
