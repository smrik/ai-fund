"""Shared valuation data contracts used across assembly, policy, and DCF stages."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(slots=True)
class ForecastDrivers:
    revenue_base: float
    revenue_growth_near: float
    revenue_growth_mid: float
    revenue_growth_terminal: float

    ebit_margin_start: float
    ebit_margin_target: float

    tax_rate_start: float
    tax_rate_target: float

    capex_pct_start: float
    capex_pct_target: float
    da_pct_start: float
    da_pct_target: float

    dso_start: float
    dso_target: float
    dio_start: float
    dio_target: float
    dpo_start: float
    dpo_target: float

    wacc: float
    exit_multiple: float
    exit_metric: Literal["ev_ebitda", "ev_ebit"]

    net_debt: float
    shares_outstanding: float

    terminal_blend_gordon_weight: float = 0.60
    terminal_blend_exit_weight: float = 0.40

    # Institutional hardening extensions.
    invested_capital_start: float | None = None
    ronic_terminal: float = 0.12

    non_operating_assets: float = 0.0
    minority_interest: float = 0.0
    preferred_equity: float = 0.0
    pension_deficit: float = 0.0
    lease_liabilities: float = 0.0
    options_value: float = 0.0
    convertibles_value: float = 0.0

    cost_of_equity: float | None = None
    debt_weight: float = 0.20

    # NWC accuracy: use COGS (not revenue) as denominator for DIO and DPO.
    cogs_pct_of_revenue: float = 0.60

    # Share dilution / buyback projection applied through the forecast horizon.
    annual_dilution_pct: float = 0.0


@dataclass(slots=True)
class ScenarioSpec:
    name: str
    probability: float
    growth_multiplier: float = 1.0
    margin_shift: float = 0.0
    wacc_shift: float = 0.0
    terminal_growth_shift: float = 0.0
    exit_multiple_multiplier: float = 1.0


@dataclass(slots=True)
class ProjectionYear:
    year: int
    revenue: float
    growth_rate: float
    ebit_margin: float
    tax_rate: float
    capex_pct: float
    da_pct: float
    dso: float
    dio: float
    dpo: float
    ebit: float
    nopat: float
    da: float
    capex: float
    ar: float
    inventory: float
    ap: float
    nwc: float
    delta_nwc: float
    fcff: float
    discount_factor: float
    pv_fcff: float

    reinvestment: float = 0.0
    invested_capital_start: float = 0.0
    invested_capital_end: float = 0.0
    roic: float | None = None
    economic_profit: float | None = None
    pv_economic_profit: float | None = None
    fcfe: float | None = None
    pv_fcfe: float | None = None


@dataclass(slots=True)
class TerminalBreakdown:
    method_used: str
    gordon_valid: bool
    exit_valid: bool
    tv_gordon: float | None
    tv_exit: float | None
    tv_blended: float
    pv_tv_gordon: float | None
    pv_tv_exit: float | None
    pv_tv_blended: float

    terminal_growth: float = 0.0
    ronic_terminal: float | None = None
    fcff_11_bridge: float | None = None
    fcff_11_value_driver: float | None = None
    gordon_formula_mode: str = "legacy"


@dataclass(slots=True)
class DCFComputationResult:
    scenario: str
    intrinsic_value_per_share: float
    enterprise_value: float
    equity_value: float
    pv_fcff_sum: float
    iv_gordon: float | None
    iv_exit: float | None
    iv_blended: float
    terminal_breakdown: TerminalBreakdown
    projections: list[ProjectionYear]
    tv_method_fallback_flag: bool
    tv_pct_of_ev: float | None
    roic_consistency_flag: bool
    nwc_driver_quality_flag: bool

    enterprise_value_operations: float | None = None
    enterprise_value_total: float | None = None
    non_operating_assets: float = 0.0
    non_equity_claims: float = 0.0

    ep_enterprise_value: float | None = None
    ep_intrinsic_value_per_share: float | None = None
    dcf_ep_gap_pct: float | None = None
    ep_reconcile_flag: bool | None = None

    fcfe_intrinsic_value_per_share: float | None = None
    fcfe_equity_value: float | None = None
    fcfe_pv_sum: float | None = None
    fcfe_terminal_value: float | None = None
    cost_of_equity_used: float | None = None

    health_flags: dict[str, bool] | None = None


@dataclass(slots=True)
class FCFEComputationResult:
    scenario: str
    intrinsic_value_per_share: float
    equity_value: float
    pv_fcfe_sum: float
    terminal_value: float
    cost_of_equity: float


@dataclass(slots=True)
class ProbabilisticValuationResult:
    scenario_results: dict[str, DCFComputationResult]
    expected_iv: float
    expected_upside_pct: float | None
