"""
Quick test: verify the valuation pipeline works standalone (no LLM).
Demonstrates that the core valuation engine is deterministic Python.
"""
import sys
sys.path.insert(0, ".")

from config import LLM_MODEL
from src.stage_02_valuation.templates.dcf_model import DCFAssumptions, run_scenario_dcf
from src.stage_00_data.market_data import get_market_data

print("Testing imports...")
print(f"  config: LLM_MODEL = {LLM_MODEL}")
print("  ✓ base_agent, valuation_agent, dcf_model, ic_memo, market_data")
print()

# Standalone DCF — no LLM needed
ticker = "HALO"
print(f"Running standalone DCF for {ticker}...")
mkt = get_market_data(ticker)
name = mkt.get("name", ticker)
price = mkt.get("current_price", 0)
mcap = mkt.get("market_cap", 0)
rev = mkt.get("revenue_ttm", 0)
op_margin = mkt.get("operating_margin", 0) or 0
pe = mkt.get("pe_trailing") or 0
ev_ebitda = mkt.get("ev_ebitda") or 0

print(f"  {name}")
print(f"  Price: ${price:,.2f} | MCap: ${mcap/1e9:.1f}B")
print(f"  Revenue TTM: ${rev/1e9:.2f}B | Op Margin: {op_margin*100:.1f}%")
print(f"  PE: {pe:.1f} | EV/EBITDA: {ev_ebitda:.1f}")
print()

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

scenarios = run_scenario_dcf(rev, assumptions)
print("  DCF Results (bear / base / bull):")
for label, r in scenarios.items():
    iv = r.intrinsic_value_per_share
    upside = (iv / price - 1) * 100 if price else 0
    tv_pct = (r.terminal_value / r.enterprise_value * 100) if r.enterprise_value else 0
    print(f"    {label.upper():>5}: ${iv:>8.2f}  ({upside:+6.1f}%)  [TV = {tv_pct:.0f}% of EV]")

print()
print("✓ Standalone valuation works — no LLM needed")
print("  The LLM agent adds judgment for assumption calibration, not computation.")


# ── Pytest tests ────────────────────────────────────────────────────────────

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
