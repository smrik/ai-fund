"""Professional deterministic DCF engine with explicit driver paths and terminal decomposition."""
from __future__ import annotations

from dataclasses import dataclass, field
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
    ]:
        if not (low <= value <= high):
            raise ValueError(f"{name} outside bounds [{low}, {high}]")

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


def _nwc_components(revenue: float, dso: float, dio: float, dpo: float) -> tuple[float, float, float, float]:
    ar = revenue * dso / 365.0
    inv = revenue * dio / 365.0
    ap = revenue * dpo / 365.0
    nwc = ar + inv - ap
    return ar, inv, ap, nwc


def _apply_scenario(drivers: ForecastDrivers, scenario: ScenarioSpec) -> ForecastDrivers:
    near = _clamp(drivers.revenue_growth_near * scenario.growth_multiplier, -0.20, 0.50)
    mid = _clamp(drivers.revenue_growth_mid * scenario.growth_multiplier, -0.20, 0.40)
    terminal = _clamp(drivers.revenue_growth_terminal * scenario.growth_multiplier + scenario.terminal_growth_shift, 0.00, 0.05)

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
    )


def run_dcf_professional(drivers: ForecastDrivers, scenario_spec: ScenarioSpec) -> DCFComputationResult:
    _validate_drivers(drivers)
    d = _apply_scenario(drivers, scenario_spec)

    projections: list[ProjectionYear] = []

    revenue = d.revenue_base
    _, _, _, prev_nwc = _nwc_components(revenue, d.dso_start, d.dio_start, d.dpo_start)

    pv_fcff_sum = 0.0

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

        ar, inv, ap, nwc = _nwc_components(revenue, dso, dio, dpo)
        delta_nwc = nwc - prev_nwc
        prev_nwc = nwc

        fcff = nopat + da - capex - delta_nwc
        discount_factor = (1.0 + d.wacc) ** year
        pv_fcff = fcff / discount_factor
        pv_fcff_sum += pv_fcff

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
            )
        )

    y10 = projections[-1]
    revenue_11 = y10.revenue * (1.0 + d.revenue_growth_terminal)
    ebit_11 = revenue_11 * y10.ebit_margin
    nopat_11 = ebit_11 * (1.0 - y10.tax_rate)
    da_11 = revenue_11 * y10.da_pct
    capex_11 = revenue_11 * y10.capex_pct
    _, _, _, nwc_11 = _nwc_components(revenue_11, y10.dso, y10.dio, y10.dpo)
    delta_nwc_11 = nwc_11 - y10.nwc
    fcff_11 = nopat_11 + da_11 - capex_11 - delta_nwc_11

    denominator = d.wacc - d.revenue_growth_terminal
    tv_gordon = fcff_11 / denominator if denominator > 0.002 and fcff_11 > 0 else None

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

    enterprise_value = pv_fcff_sum + pv_tv_blended
    equity_value = enterprise_value - d.net_debt
    iv_blended = equity_value / d.shares_outstanding

    iv_gordon = None
    if gordon_valid and pv_tv_gordon is not None:
        iv_gordon = (pv_fcff_sum + pv_tv_gordon - d.net_debt) / d.shares_outstanding

    iv_exit = None
    if exit_valid and pv_tv_exit is not None:
        iv_exit = (pv_fcff_sum + pv_tv_exit - d.net_debt) / d.shares_outstanding

    reinvestment_10 = y10.capex - y10.da + y10.delta_nwc
    reinvestment_rate_10 = reinvestment_10 / y10.nopat if y10.nopat > 0 else None
    implied_roic = None
    if reinvestment_rate_10 is not None and reinvestment_rate_10 > 0:
        implied_roic = d.revenue_growth_terminal / reinvestment_rate_10

    roic_consistency_flag = bool(
        implied_roic is not None and (implied_roic < 0.02 or implied_roic > 0.35)
    )
    nwc_driver_quality_flag = bool(
        min(d.dso_start, d.dso_target, d.dio_start, d.dio_target, d.dpo_start, d.dpo_target) > 0
    )

    tv_pct_of_ev = None
    if enterprise_value > 0:
        tv_pct_of_ev = pv_tv_blended / enterprise_value

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
    )

    return DCFComputationResult(
        scenario=scenario_spec.name,
        intrinsic_value_per_share=iv_blended,
        enterprise_value=enterprise_value,
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
