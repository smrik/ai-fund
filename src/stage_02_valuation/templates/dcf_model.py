"""
Python DCF model template.
Auto-populated from FilingsSummary + market data.
Returns bear/base/bull intrinsic value per share.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class DCFAssumptions:
    # Revenue growth rates (Year 1–5, Year 6–10, terminal)
    revenue_growth_near: float    # e.g. 0.10 = 10%
    revenue_growth_mid: float     # e.g. 0.07
    revenue_growth_terminal: float  # e.g. 0.03

    # Margins
    ebit_margin: float            # e.g. 0.20
    tax_rate: float               # e.g. 0.21
    capex_pct_revenue: float      # e.g. 0.05
    da_pct_revenue: float         # e.g. 0.03
    nwc_change_pct_revenue: float  # e.g. 0.01

    # Discount + terminal value
    wacc: float                   # e.g. 0.09
    exit_multiple: float          # EV/EBIT at terminal year, e.g. 15.0

    # Balance sheet adjustments
    net_debt: float               # total debt - cash, absolute $
    shares_outstanding: float     # shares in units (not millions)


@dataclass
class DCFResult:
    intrinsic_value_per_share: float
    terminal_value: float
    pv_fcfs: float
    enterprise_value: float
    scenario: str


def run_dcf(
    base_revenue: float,
    assumptions: DCFAssumptions,
    scenario_label: str = "base",
) -> DCFResult:
    """
    Standard 10-year DCF with terminal value via exit multiple.
    All monetary values in same unit as base_revenue (typically $).
    """
    revenues = []
    rev = base_revenue

    for year in range(1, 11):
        growth = assumptions.revenue_growth_near if year <= 5 else assumptions.revenue_growth_mid
        rev = rev * (1 + growth)
        revenues.append(rev)

    # Free cash flows
    fcfs = []
    for rev in revenues:
        ebit = rev * assumptions.ebit_margin
        nopat = ebit * (1 - assumptions.tax_rate)
        da = rev * assumptions.da_pct_revenue
        capex = rev * assumptions.capex_pct_revenue
        nwc_change = rev * assumptions.nwc_change_pct_revenue
        fcf = nopat + da - capex - nwc_change
        fcfs.append(fcf)

    # PV of FCFs
    pv_fcfs = sum(
        fcf / ((1 + assumptions.wacc) ** (i + 1))
        for i, fcf in enumerate(fcfs)
    )

    # Terminal value (exit multiple on final year EBIT)
    terminal_ebit = revenues[-1] * assumptions.ebit_margin
    terminal_value = terminal_ebit * assumptions.exit_multiple
    pv_terminal = terminal_value / ((1 + assumptions.wacc) ** 10)

    enterprise_value = pv_fcfs + pv_terminal
    equity_value = enterprise_value - assumptions.net_debt
    intrinsic_per_share = equity_value / assumptions.shares_outstanding if assumptions.shares_outstanding > 0 else 0

    return DCFResult(
        intrinsic_value_per_share=round(intrinsic_per_share, 2),
        terminal_value=round(pv_terminal, 0),
        pv_fcfs=round(pv_fcfs, 0),
        enterprise_value=round(enterprise_value, 0),
        scenario=scenario_label,
    )


def run_scenario_dcf(
    base_revenue: float,
    base_assumptions: DCFAssumptions,
) -> dict[str, DCFResult]:
    """
    Run bear / base / bull scenarios by adjusting key assumptions.
    """
    # Bear: lower growth, lower margins, higher WACC
    bear_assumptions = DCFAssumptions(
        revenue_growth_near=base_assumptions.revenue_growth_near * 0.6,
        revenue_growth_mid=base_assumptions.revenue_growth_mid * 0.6,
        revenue_growth_terminal=base_assumptions.revenue_growth_terminal * 0.7,
        ebit_margin=base_assumptions.ebit_margin * 0.75,
        tax_rate=base_assumptions.tax_rate,
        capex_pct_revenue=base_assumptions.capex_pct_revenue * 1.2,
        da_pct_revenue=base_assumptions.da_pct_revenue,
        nwc_change_pct_revenue=base_assumptions.nwc_change_pct_revenue,
        wacc=base_assumptions.wacc + 0.02,
        exit_multiple=base_assumptions.exit_multiple * 0.7,
        net_debt=base_assumptions.net_debt,
        shares_outstanding=base_assumptions.shares_outstanding,
    )

    # Bull: higher growth, sustained margins, lower WACC
    bull_assumptions = DCFAssumptions(
        revenue_growth_near=base_assumptions.revenue_growth_near * 1.4,
        revenue_growth_mid=base_assumptions.revenue_growth_mid * 1.3,
        revenue_growth_terminal=base_assumptions.revenue_growth_terminal * 1.1,
        ebit_margin=base_assumptions.ebit_margin * 1.15,
        tax_rate=base_assumptions.tax_rate,
        capex_pct_revenue=base_assumptions.capex_pct_revenue * 0.9,
        da_pct_revenue=base_assumptions.da_pct_revenue,
        nwc_change_pct_revenue=base_assumptions.nwc_change_pct_revenue,
        wacc=base_assumptions.wacc - 0.01,
        exit_multiple=base_assumptions.exit_multiple * 1.3,
        net_debt=base_assumptions.net_debt,
        shares_outstanding=base_assumptions.shares_outstanding,
    )

    return {
        "bear": run_dcf(base_revenue, bear_assumptions, "bear"),
        "base": run_dcf(base_revenue, base_assumptions, "base"),
        "bull": run_dcf(base_revenue, bull_assumptions, "bull"),
    }
