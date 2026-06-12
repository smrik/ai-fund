"""
Quick tests for the deterministic valuation pipeline.

The live Yahoo demo is kept behind a main guard so pytest collection remains
offline and deterministic.
"""

import sys

sys.path.insert(0, ".")

from config import LLM_MODEL
from src.stage_02_valuation.templates.dcf_model import DCFAssumptions, run_scenario_dcf


def _demo_market_data() -> dict:
    return {
        "name": "Halozyme Therapeutics",
        "current_price": 55.0,
        "market_cap": 7.0e9,
        "revenue_ttm": 1.1e9,
        "operating_margin": 0.42,
        "pe_trailing": 22.0,
        "ev_ebitda": 18.0,
        "total_debt": 1.5e9,
        "cash": 0.6e9,
        "shares_outstanding": 125e6,
    }


def _run_standalone_dcf(mkt: dict) -> dict:
    net_debt = (mkt.get("total_debt") or 0) - (mkt.get("cash") or 0)
    shares = mkt.get("shares_outstanding") or 1
    assumptions = DCFAssumptions(
        revenue_growth_near=0.15,
        revenue_growth_mid=0.10,
        revenue_growth_terminal=0.03,
        ebit_margin=0.40,
        tax_rate=0.21,
        capex_pct_revenue=0.03,
        da_pct_revenue=0.02,
        nwc_change_pct_revenue=0.01,
        wacc=0.10,
        exit_multiple=18.0,
        net_debt=net_debt,
        shares_outstanding=shares,
    )
    return run_scenario_dcf(mkt.get("revenue_ttm", 0), assumptions)


def test_standalone_dcf_runs_without_llm_or_network():
    scenarios = _run_standalone_dcf(_demo_market_data())

    assert set(scenarios) == {"bear", "base", "bull"}
    assert scenarios["base"].intrinsic_value_per_share > 0
    assert LLM_MODEL


def test_reverse_dcf_returns_plausible_growth():
    """reverse_dcf_professional should recover a growth rate close to the original setup."""
    from src.stage_02_valuation.professional_dcf import (
        ForecastDrivers,
        ScenarioSpec,
        reverse_dcf_professional,
        run_dcf_professional,
    )

    drivers = ForecastDrivers(
        revenue_base=10e9,
        revenue_growth_near=0.10,
        revenue_growth_mid=0.065,
        revenue_growth_terminal=0.03,
        ebit_margin_start=0.20,
        ebit_margin_target=0.20,
        tax_rate_start=0.21,
        tax_rate_target=0.21,
        capex_pct_start=0.05,
        capex_pct_target=0.05,
        da_pct_start=0.04,
        da_pct_target=0.04,
        dso_start=50.0,
        dso_target=50.0,
        dio_start=50.0,
        dio_target=50.0,
        dpo_start=45.0,
        dpo_target=45.0,
        wacc=0.09,
        exit_multiple=15.0,
        exit_metric="ev_ebitda",
        net_debt=1e9,
        shares_outstanding=100e6,
    )

    base_result = run_dcf_professional(drivers, ScenarioSpec(name="base", probability=1.0))
    target_price = base_result.intrinsic_value_per_share

    implied = reverse_dcf_professional(
        drivers=drivers,
        target_price=target_price,
        scenario="base",
    )

    assert implied is not None
    assert abs(implied - 0.10) < 0.01


if __name__ == "__main__":
    from src.stage_00_data.market_data import get_market_data

    print("Testing imports...")
    print(f"  config: LLM_MODEL = {LLM_MODEL}")
    print("  base_agent, valuation_agent, dcf_model, ic_memo, market_data")
    print()

    ticker = "HALO"
    print(f"Running standalone DCF for {ticker}...")
    market_data = get_market_data(ticker)
    name = market_data.get("name", ticker)
    price = market_data.get("current_price", 0)
    mcap = market_data.get("market_cap", 0)
    rev = market_data.get("revenue_ttm", 0)
    op_margin = market_data.get("operating_margin", 0) or 0
    pe = market_data.get("pe_trailing") or 0
    ev_ebitda = market_data.get("ev_ebitda") or 0

    print(f"  {name}")
    print(f"  Price: ${price:,.2f} | MCap: ${mcap / 1e9:.1f}B")
    print(f"  Revenue TTM: ${rev / 1e9:.2f}B | Op Margin: {op_margin * 100:.1f}%")
    print(f"  PE: {pe:.1f} | EV/EBITDA: {ev_ebitda:.1f}")
    print()

    print("  DCF Results (bear / base / bull):")
    for label, result in _run_standalone_dcf(market_data).items():
        iv = result.intrinsic_value_per_share
        upside = (iv / price - 1) * 100 if price else 0
        tv_pct = (result.terminal_value / result.enterprise_value * 100) if result.enterprise_value else 0
        print(f"    {label.upper():>5}: ${iv:>8.2f}  ({upside:+6.1f}%)  [TV = {tv_pct:.0f}% of EV]")

    print()
    print("Standalone valuation works; no LLM needed for computation.")
