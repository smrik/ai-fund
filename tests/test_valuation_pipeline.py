"""
Quick test: verify the valuation pipeline works standalone (no LLM).
Demonstrates that the core valuation engine is deterministic Python.
"""
import sys
sys.path.insert(0, ".")

from config import LLM_MODEL
from src.agents.base_agent import BaseAgent
from src.agents.valuation_agent import ValuationAgent
from src.templates.dcf_model import DCFAssumptions, run_dcf, run_scenario_dcf
from src.templates.ic_memo import ICMemo, ValuationRange
from src.data.market_data import get_market_data

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
    """reverse_dcf should return a growth rate that reproduces the target price."""
    import sys
    import os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from src.valuation.batch_runner import reverse_dcf
    from src.templates.dcf_model import DCFAssumptions, run_dcf

    rev = 10e9
    assumptions = DCFAssumptions(
        revenue_growth_near=0.10,
        revenue_growth_mid=0.065,
        revenue_growth_terminal=0.03,
        ebit_margin=0.20,
        tax_rate=0.21,
        capex_pct_revenue=0.05,
        da_pct_revenue=0.04,
        nwc_change_pct_revenue=0.01,
        wacc=0.09,
        exit_multiple=15.0,
        net_debt=1e9,
        shares_outstanding=100e6,
    )
    base_result = run_dcf(rev, assumptions)
    target_price = base_result.intrinsic_value_per_share

    implied = reverse_dcf(
        revenue=rev,
        assumptions=assumptions,
        target_price=target_price,
        shares=100e6,
        net_debt=1e9,
    )

    assert implied is not None
    # Should recover approximately the original growth rate (10%)
    assert abs(implied - 0.10) < 0.01
