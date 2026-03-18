"""Professional deterministic DCF engine with explicit driver paths and terminal decomposition."""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


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

    # NWC accuracy: use COGS (not revenue) as denominator for DIO and DPO
    cogs_pct_of_revenue: float = 0.60

    # Share dilution / buyback projection (Phase A — applied at terminal value)
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


def default_scenario_specs() -> list[ScenarioSpec]:
    return [
        ScenarioSpec(name="bear", probability=0.20, growth_multiplier=0.8, margin_shift=-0.02, wacc_shift=0.01, exit_multiple_multiplier=0.9),
        ScenarioSpec(name="base", probability=0.60),
        ScenarioSpec(name="bull", probability=0.20, growth_multiplier=1.2, margin_shift=0.02, wacc_shift=-0.01, exit_multiple_multiplier=1.1),
    ]


def _validate_drivers(drivers: ForecastDrivers) -> None:
    if drivers.revenue_base <= 0:
        raise ValueError("revenue_base must be > 0")
    if drivers.shares_outstanding <= 0:
        raise ValueError("shares_outstanding must be > 0")

    for name, value, low, high in [
        ("revenue_growth_near", drivers.revenue_growth_near, -0.20, 0.50),
        ("revenue_growth_mid", drivers.revenue_growth_mid, -0.20, 0.40),
        ("revenue_growth_terminal", drivers.revenue_growth_terminal, 0.00, 0.05),
        ("ebit_margin_start", drivers.ebit_margin_start, 0.00, 0.80),
        ("ebit_margin_target", drivers.ebit_margin_target, 0.00, 0.80),
        ("tax_rate_start", drivers.tax_rate_start, 0.05, 0.45),
        ("tax_rate_target", drivers.tax_rate_target, 0.05, 0.45),
        ("capex_pct_start", drivers.capex_pct_start, 0.00, 0.35),
        ("capex_pct_target", drivers.capex_pct_target, 0.00, 0.35),
        ("da_pct_start", drivers.da_pct_start, 0.00, 0.25),
        ("da_pct_target", drivers.da_pct_target, 0.00, 0.25),
        ("wacc", drivers.wacc, 0.03, 0.20),
        ("exit_multiple", drivers.exit_multiple, 2.0, 40.0),
        ("ronic_terminal", drivers.ronic_terminal, 0.04, 0.45),
        ("debt_weight", drivers.debt_weight, 0.00, 0.80),
    ]:
        if not (low <= value <= high):
            raise ValueError(f"{name} outside bounds [{low}, {high}]")

    if drivers.cost_of_equity is not None and not (0.04 <= drivers.cost_of_equity <= 0.30):
        raise ValueError("cost_of_equity outside bounds [0.04, 0.30]")

    if drivers.invested_capital_start is not None and drivers.invested_capital_start <= 0:
        raise ValueError("invested_capital_start must be > 0 when provided")

    if drivers.exit_metric not in {"ev_ebitda", "ev_ebit"}:
        raise ValueError("exit_metric must be ev_ebitda or ev_ebit")


def _linear_path(start: float, end: float, year: int) -> float:
    if year <= 1:
        return start
    if year >= 10:
        return end
    alpha = (year - 1) / 9.0
    return start + (end - start) * alpha


def _growth_for_year(near: float, mid: float, year: int) -> float:
    if year <= 3:
        return near
    # Fade from near to mid during years 4-10.
    alpha = (year - 3) / 7.0
    return near + (mid - near) * alpha


def _nwc_components(
    revenue: float,
    dso: float,
    dio: float,
    dpo: float,
    cogs_pct: float = 0.60,
) -> tuple[float, float, float, float]:
    ar = revenue * dso / 365.0
    cogs = revenue * cogs_pct
    inv = cogs * dio / 365.0
    ap = cogs * dpo / 365.0
    nwc = ar + inv - ap
    return ar, inv, ap, nwc


def _claims_total(d: ForecastDrivers) -> float:
    return (
        d.net_debt
        + d.minority_interest
        + d.preferred_equity
        + d.pension_deficit
        + d.lease_liabilities
        + d.options_value
        + d.convertibles_value
    )


def _derive_initial_invested_capital(d: ForecastDrivers, nwc_start: float) -> float:
    if d.invested_capital_start is not None and d.invested_capital_start > 0:
        return d.invested_capital_start

    # Deterministic operating-capital proxy fallback when source systems do not provide IC.
    ppne_proxy = max(
        d.revenue_base * max(d.capex_pct_start * 3.0, d.da_pct_start * 4.0, 0.15),
        1.0,
    )
    ic = nwc_start + ppne_proxy
    return max(ic, d.revenue_base * 0.25)


def _apply_scenario(drivers: ForecastDrivers, scenario: ScenarioSpec) -> ForecastDrivers:
    near = _clamp(drivers.revenue_growth_near * scenario.growth_multiplier, -0.20, 0.50)
    mid = _clamp(drivers.revenue_growth_mid * scenario.growth_multiplier, -0.20, 0.40)
    terminal = _clamp(drivers.revenue_growth_terminal * scenario.growth_multiplier + scenario.terminal_growth_shift, 0.00, 0.05)

    ke = drivers.cost_of_equity
    if ke is not None:
        ke = _clamp(ke + scenario.wacc_shift, 0.04, 0.30)

    return ForecastDrivers(
        revenue_base=drivers.revenue_base,
        revenue_growth_near=near,
        revenue_growth_mid=mid,
        revenue_growth_terminal=terminal,
        ebit_margin_start=_clamp(drivers.ebit_margin_start + scenario.margin_shift, 0.00, 0.80),
        ebit_margin_target=_clamp(drivers.ebit_margin_target + scenario.margin_shift, 0.00, 0.80),
        tax_rate_start=drivers.tax_rate_start,
        tax_rate_target=drivers.tax_rate_target,
        capex_pct_start=drivers.capex_pct_start,
        capex_pct_target=drivers.capex_pct_target,
        da_pct_start=drivers.da_pct_start,
        da_pct_target=drivers.da_pct_target,
        dso_start=drivers.dso_start,
        dso_target=drivers.dso_target,
        dio_start=drivers.dio_start,
        dio_target=drivers.dio_target,
        dpo_start=drivers.dpo_start,
        dpo_target=drivers.dpo_target,
        wacc=_clamp(drivers.wacc + scenario.wacc_shift, 0.03, 0.20),
        exit_multiple=_clamp(drivers.exit_multiple * scenario.exit_multiple_multiplier, 2.0, 40.0),
        exit_metric=drivers.exit_metric,
        net_debt=drivers.net_debt,
        shares_outstanding=drivers.shares_outstanding,
        terminal_blend_gordon_weight=drivers.terminal_blend_gordon_weight,
        terminal_blend_exit_weight=drivers.terminal_blend_exit_weight,
        invested_capital_start=drivers.invested_capital_start,
        ronic_terminal=drivers.ronic_terminal,
        non_operating_assets=drivers.non_operating_assets,
        minority_interest=drivers.minority_interest,
        preferred_equity=drivers.preferred_equity,
        pension_deficit=drivers.pension_deficit,
        lease_liabilities=drivers.lease_liabilities,
        options_value=drivers.options_value,
        convertibles_value=drivers.convertibles_value,
        cost_of_equity=ke,
        debt_weight=drivers.debt_weight,
        cogs_pct_of_revenue=drivers.cogs_pct_of_revenue,
        annual_dilution_pct=drivers.annual_dilution_pct,
    )


def _compute_fcfe(
    d: ForecastDrivers,
    projections: list[ProjectionYear],
    fcff_11_for_gordon: float,
    nopat_11: float,
    non_equity_claims: float,
    shares_out: float | None = None,
) -> tuple[float | None, float | None, float | None, float]:
    ke = d.cost_of_equity if d.cost_of_equity is not None else _clamp(d.wacc + 0.015, 0.04, 0.30)

    pv_fcfe_sum = 0.0
    for p in projections:
        net_borrowing = p.reinvestment * d.debt_weight
        fcfe = p.fcff + net_borrowing
        pv_fcfe = fcfe / ((1.0 + ke) ** p.year)
        p.fcfe = fcfe
        p.pv_fcfe = pv_fcfe
        pv_fcfe_sum += pv_fcfe

    terminal_growth = d.revenue_growth_terminal
    terminal_reinvestment = max(0.0, nopat_11 - fcff_11_for_gordon)
    fcfe_11 = fcff_11_for_gordon + terminal_reinvestment * d.debt_weight
    denominator_ke = ke - terminal_growth
    terminal_value = fcfe_11 / denominator_ke if denominator_ke > 0.002 and fcfe_11 > 0 else None
    pv_terminal = terminal_value / ((1.0 + ke) ** 10) if terminal_value is not None else 0.0

    # FCFE already flows to equity; do not subtract net debt again.
    non_debt_claims = non_equity_claims - d.net_debt
    equity_value = pv_fcfe_sum + pv_terminal + d.non_operating_assets - non_debt_claims

    shares = shares_out if (shares_out is not None and shares_out > 0) else d.shares_outstanding
    iv = None
    if shares > 0:
        iv = equity_value / shares

    return iv, equity_value, terminal_value, ke


def run_dcf_professional(drivers: ForecastDrivers, scenario_spec: ScenarioSpec) -> DCFComputationResult:
    _validate_drivers(drivers)
    d = _apply_scenario(drivers, scenario_spec)

    projections: list[ProjectionYear] = []

    revenue = d.revenue_base
    _, _, _, prev_nwc = _nwc_components(revenue, d.dso_start, d.dio_start, d.dpo_start, cogs_pct=d.cogs_pct_of_revenue)
    ic_prev = _derive_initial_invested_capital(d, prev_nwc)

    pv_fcff_sum = 0.0
    pv_ep_sum = 0.0

    for year in range(1, 11):
        growth_rate = _growth_for_year(d.revenue_growth_near, d.revenue_growth_mid, year)
        revenue *= 1.0 + growth_rate

        margin = _linear_path(d.ebit_margin_start, d.ebit_margin_target, year)
        tax_rate = _linear_path(d.tax_rate_start, d.tax_rate_target, year)
        capex_pct = _linear_path(d.capex_pct_start, d.capex_pct_target, year)
        da_pct = _linear_path(d.da_pct_start, d.da_pct_target, year)
        dso = _linear_path(d.dso_start, d.dso_target, year)
        dio = _linear_path(d.dio_start, d.dio_target, year)
        dpo = _linear_path(d.dpo_start, d.dpo_target, year)

        ebit = revenue * margin
        nopat = ebit * (1.0 - tax_rate)
        da = revenue * da_pct
        capex = revenue * capex_pct

        ar, inv, ap, nwc = _nwc_components(revenue, dso, dio, dpo, cogs_pct=d.cogs_pct_of_revenue)
        delta_nwc = nwc - prev_nwc
        prev_nwc = nwc

        reinvestment = capex - da + delta_nwc
        fcff = nopat + da - capex - delta_nwc

        discount_factor = (1.0 + d.wacc) ** year
        pv_fcff = fcff / discount_factor
        pv_fcff_sum += pv_fcff

        roic = nopat / ic_prev if ic_prev > 0 else None
        economic_profit = nopat - d.wacc * ic_prev
        pv_economic_profit = economic_profit / discount_factor
        pv_ep_sum += pv_economic_profit

        ic_end = max(ic_prev + reinvestment, 1.0)

        projections.append(
            ProjectionYear(
                year=year,
                revenue=revenue,
                growth_rate=growth_rate,
                ebit_margin=margin,
                tax_rate=tax_rate,
                capex_pct=capex_pct,
                da_pct=da_pct,
                dso=dso,
                dio=dio,
                dpo=dpo,
                ebit=ebit,
                nopat=nopat,
                da=da,
                capex=capex,
                ar=ar,
                inventory=inv,
                ap=ap,
                nwc=nwc,
                delta_nwc=delta_nwc,
                fcff=fcff,
                discount_factor=discount_factor,
                pv_fcff=pv_fcff,
                reinvestment=reinvestment,
                invested_capital_start=ic_prev,
                invested_capital_end=ic_end,
                roic=roic,
                economic_profit=economic_profit,
                pv_economic_profit=pv_economic_profit,
            )
        )

        ic_prev = ic_end

    y10 = projections[-1]
    revenue_11 = y10.revenue * (1.0 + d.revenue_growth_terminal)
    ebit_11 = revenue_11 * y10.ebit_margin
    nopat_11 = ebit_11 * (1.0 - y10.tax_rate)
    da_11 = revenue_11 * y10.da_pct
    capex_11 = revenue_11 * y10.capex_pct
    _, _, _, nwc_11 = _nwc_components(revenue_11, y10.dso, y10.dio, y10.dpo, cogs_pct=d.cogs_pct_of_revenue)
    delta_nwc_11 = nwc_11 - y10.nwc
    fcff_11_bridge = nopat_11 + da_11 - capex_11 - delta_nwc_11

    terminal_growth = d.revenue_growth_terminal
    ronic_terminal = max(d.ronic_terminal, terminal_growth + 0.005)
    fcff_11_value_driver = None
    gordon_formula_mode = "bridge"
    if nopat_11 > 0 and ronic_terminal > terminal_growth + 0.0005:
        reinvestment_rate_terminal = _clamp(terminal_growth / ronic_terminal, 0.0, 0.95)
        fcff_11_value_driver = nopat_11 * (1.0 - reinvestment_rate_terminal)
        gordon_formula_mode = "value_driver"

    fcff_11_for_gordon = fcff_11_value_driver if fcff_11_value_driver is not None else fcff_11_bridge

    denominator = d.wacc - terminal_growth
    tv_gordon = fcff_11_for_gordon / denominator if denominator > 0.002 and fcff_11_for_gordon > 0 else None

    terminal_metric_10 = y10.ebit + y10.da if d.exit_metric == "ev_ebitda" else y10.ebit
    tv_exit = terminal_metric_10 * d.exit_multiple if terminal_metric_10 > 0 and d.exit_multiple > 0 else None

    gordon_valid = tv_gordon is not None
    exit_valid = tv_exit is not None

    pv_tv_gordon = tv_gordon / ((1.0 + d.wacc) ** 10) if gordon_valid else None
    pv_tv_exit = tv_exit / ((1.0 + d.wacc) ** 10) if exit_valid else None

    if gordon_valid and exit_valid:
        wg = d.terminal_blend_gordon_weight
        we = d.terminal_blend_exit_weight
        total = wg + we
        if total <= 0:
            wg, we = 0.60, 0.40
            total = 1.0
        wg /= total
        we /= total
        tv_blended = tv_gordon * wg + tv_exit * we
        pv_tv_blended = pv_tv_gordon * wg + pv_tv_exit * we
        method_used = "blend"
    elif gordon_valid:
        tv_blended = tv_gordon
        pv_tv_blended = float(pv_tv_gordon)
        method_used = "gordon_only"
    elif exit_valid:
        tv_blended = tv_exit
        pv_tv_blended = float(pv_tv_exit)
        method_used = "exit_only"
    else:
        tv_blended = 0.0
        pv_tv_blended = 0.0
        method_used = "none"

    enterprise_value_operations = pv_fcff_sum + pv_tv_blended
    enterprise_value_total = enterprise_value_operations + d.non_operating_assets
    non_equity_claims = _claims_total(d)

    equity_value = enterprise_value_total - non_equity_claims

    # Gap 3 (Phase A): project shares to Year 10 to capture dilution/buyback effect
    shares_y10 = d.shares_outstanding * (1.0 + d.annual_dilution_pct) ** 10
    shares_y10 = max(shares_y10, 1.0)

    iv_blended = equity_value / shares_y10

    iv_gordon = None
    if gordon_valid and pv_tv_gordon is not None:
        iv_gordon = (pv_fcff_sum + pv_tv_gordon + d.non_operating_assets - non_equity_claims) / shares_y10

    iv_exit = None
    if exit_valid and pv_tv_exit is not None:
        iv_exit = (pv_fcff_sum + pv_tv_exit + d.non_operating_assets - non_equity_claims) / shares_y10

    reinvestment_10 = y10.reinvestment
    reinvestment_rate_10 = reinvestment_10 / y10.nopat if y10.nopat > 0 else None
    implied_roic = None
    if reinvestment_rate_10 is not None and reinvestment_rate_10 > 0:
        implied_roic = terminal_growth / reinvestment_rate_10

    roic_consistency_flag = bool(
        implied_roic is not None and (implied_roic < 0.02 or implied_roic > 0.35)
    )
    nwc_driver_quality_flag = bool(
        min(d.dso_start, d.dso_target, d.dio_start, d.dio_target, d.dpo_start, d.dpo_target) > 0
    )

    tv_pct_of_ev = None
    if enterprise_value_operations > 0:
        tv_pct_of_ev = pv_tv_blended / enterprise_value_operations

    ic0 = projections[0].invested_capital_start if projections else None
    ic10 = projections[-1].invested_capital_end if projections else None
    terminal_ep = None
    pv_terminal_ep = None
    if ic10 is not None:
        ep_11 = nopat_11 - d.wacc * ic10
        if denominator > 0.002:
            terminal_ep = ep_11 / denominator
            pv_terminal_ep = terminal_ep / ((1.0 + d.wacc) ** 10)

    ep_enterprise_value = None
    ep_intrinsic_value_per_share = None
    dcf_ep_gap_pct = None
    ep_reconcile_flag = None
    if ic0 is not None:
        ep_enterprise_value = ic0 + pv_ep_sum + (pv_terminal_ep or 0.0)
        if enterprise_value_operations != 0:
            dcf_ep_gap_pct = (ep_enterprise_value - enterprise_value_operations) / enterprise_value_operations
            ep_reconcile_flag = abs(dcf_ep_gap_pct) <= 0.15
        ep_equity = ep_enterprise_value + d.non_operating_assets - non_equity_claims
        ep_intrinsic_value_per_share = ep_equity / shares_y10

    fcfe_iv, fcfe_equity_value, fcfe_terminal_value, cost_of_equity_used = _compute_fcfe(
        d=d,
        projections=projections,
        fcff_11_for_gordon=fcff_11_for_gordon,
        nopat_11=nopat_11,
        non_equity_claims=non_equity_claims,
        shares_out=shares_y10,
    )

    health_flags = {
        "tv_high_flag": bool(tv_pct_of_ev is not None and tv_pct_of_ev > 0.75),
        "tv_extreme_flag": bool(tv_pct_of_ev is not None and tv_pct_of_ev > 0.90),
        "terminal_growth_guardrail_flag": bool(terminal_growth > 0.04),
        "terminal_ronic_guardrail_flag": bool(d.ronic_terminal <= terminal_growth + 0.005),
        "terminal_denominator_guardrail_flag": bool(denominator <= 0.002),
        "tv_method_fallback_flag": bool(method_used != "blend"),
        "fcff_interest_contamination_flag": False,
        "ep_reconcile_flag": bool(ep_reconcile_flag) if ep_reconcile_flag is not None else False,
    }

    terminal_breakdown = TerminalBreakdown(
        method_used=method_used,
        gordon_valid=gordon_valid,
        exit_valid=exit_valid,
        tv_gordon=tv_gordon,
        tv_exit=tv_exit,
        tv_blended=tv_blended,
        pv_tv_gordon=pv_tv_gordon,
        pv_tv_exit=pv_tv_exit,
        pv_tv_blended=pv_tv_blended,
        terminal_growth=terminal_growth,
        ronic_terminal=ronic_terminal,
        fcff_11_bridge=fcff_11_bridge,
        fcff_11_value_driver=fcff_11_value_driver,
        gordon_formula_mode=gordon_formula_mode,
    )

    return DCFComputationResult(
        scenario=scenario_spec.name,
        intrinsic_value_per_share=iv_blended,
        enterprise_value=enterprise_value_total,
        equity_value=equity_value,
        pv_fcff_sum=pv_fcff_sum,
        iv_gordon=iv_gordon,
        iv_exit=iv_exit,
        iv_blended=iv_blended,
        terminal_breakdown=terminal_breakdown,
        projections=projections,
        tv_method_fallback_flag=method_used != "blend",
        tv_pct_of_ev=tv_pct_of_ev,
        roic_consistency_flag=roic_consistency_flag,
        nwc_driver_quality_flag=nwc_driver_quality_flag,
        enterprise_value_operations=enterprise_value_operations,
        enterprise_value_total=enterprise_value_total,
        non_operating_assets=d.non_operating_assets,
        non_equity_claims=non_equity_claims,
        ep_enterprise_value=ep_enterprise_value,
        ep_intrinsic_value_per_share=ep_intrinsic_value_per_share,
        dcf_ep_gap_pct=dcf_ep_gap_pct,
        ep_reconcile_flag=ep_reconcile_flag,
        fcfe_intrinsic_value_per_share=fcfe_iv,
        fcfe_equity_value=fcfe_equity_value,
        fcfe_pv_sum=sum((p.pv_fcfe or 0.0) for p in projections),
        fcfe_terminal_value=fcfe_terminal_value,
        cost_of_equity_used=cost_of_equity_used,
        health_flags=health_flags,
    )


def run_fcfe_valuation(drivers: ForecastDrivers, scenario_spec: ScenarioSpec) -> FCFEComputationResult:
    """Direct FCFE branch using the same deterministic forecast path and bridge assumptions."""
    result = run_dcf_professional(drivers, scenario_spec)

    if result.fcfe_intrinsic_value_per_share is None or result.fcfe_equity_value is None:
        raise ValueError("FCFE valuation could not be computed for the provided assumptions")

    return FCFEComputationResult(
        scenario=result.scenario,
        intrinsic_value_per_share=result.fcfe_intrinsic_value_per_share,
        equity_value=result.fcfe_equity_value,
        pv_fcfe_sum=result.fcfe_pv_sum or 0.0,
        terminal_value=result.fcfe_terminal_value or 0.0,
        cost_of_equity=result.cost_of_equity_used or _clamp(drivers.wacc + 0.015, 0.04, 0.30),
    )


def run_probabilistic_valuation(
    drivers: ForecastDrivers,
    scenario_specs: list[ScenarioSpec],
    current_price: float | None = None,
) -> ProbabilisticValuationResult:
    if not scenario_specs:
        raise ValueError("scenario_specs must not be empty")

    prob_sum = sum(max(0.0, s.probability) for s in scenario_specs)
    if prob_sum <= 0:
        raise ValueError("scenario probabilities must sum to > 0")

    scenario_results: dict[str, DCFComputationResult] = {}
    expected_iv = 0.0

    for spec in scenario_specs:
        norm_prob = max(0.0, spec.probability) / prob_sum
        normalized = ScenarioSpec(
            name=spec.name,
            probability=norm_prob,
            growth_multiplier=spec.growth_multiplier,
            margin_shift=spec.margin_shift,
            wacc_shift=spec.wacc_shift,
            terminal_growth_shift=spec.terminal_growth_shift,
            exit_multiple_multiplier=spec.exit_multiple_multiplier,
        )
        result = run_dcf_professional(drivers, normalized)
        scenario_results[normalized.name] = result
        expected_iv += result.intrinsic_value_per_share * norm_prob

    expected_upside_pct = None
    if current_price and current_price > 0:
        expected_upside_pct = expected_iv / current_price - 1.0

    return ProbabilisticValuationResult(
        scenario_results=scenario_results,
        expected_iv=expected_iv,
        expected_upside_pct=expected_upside_pct,
    )


def reverse_dcf_professional(
    drivers: ForecastDrivers,
    target_price: float,
    scenario: ScenarioSpec | str = "base",
    low: float = -0.10,
    high: float = 0.50,
    tol: float = 0.001,
    max_iter: int = 60,
) -> float | None:
    """Solve implied near-term growth using the professional deterministic DCF engine."""
    if target_price is None or target_price <= 0:
        return None

    _validate_drivers(drivers)

    scenario_spec = scenario if isinstance(scenario, ScenarioSpec) else ScenarioSpec(name=str(scenario), probability=1.0)

    fade_ratio = 0.65
    if abs(drivers.revenue_growth_near) > 1e-9:
        fade_ratio = drivers.revenue_growth_mid / drivers.revenue_growth_near

    def _iv(growth_near: float) -> float:
        growth_mid = _clamp(growth_near * fade_ratio, -0.20, 0.40)
        probe = replace(
            drivers,
            revenue_growth_near=growth_near,
            revenue_growth_mid=growth_mid,
        )
        result = run_dcf_professional(probe, scenario_spec)
        return result.intrinsic_value_per_share

    try:
        iv_low = _iv(low)
        iv_high = _iv(high)
    except Exception:
        return None

    if iv_low > iv_high:
        low, high = high, low
        iv_low, iv_high = iv_high, iv_low

    if target_price < iv_low or target_price > iv_high:
        return None

    for _ in range(max_iter):
        mid = (low + high) / 2
        iv_mid = _iv(mid)

        if abs(iv_mid - target_price) / max(abs(target_price), 1.0) < tol:
            return round(mid, 4)

        if iv_mid < target_price:
            low = mid
        else:
            high = mid

    return round((low + high) / 2, 4)
