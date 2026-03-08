import copy

from src.stage_02_valuation.professional_dcf import (
    ForecastDrivers,
    ScenarioSpec,
    run_dcf_professional,
    run_probabilistic_valuation,
)


def _drivers(**overrides) -> ForecastDrivers:
    base = ForecastDrivers(
        revenue_base=1_000_000_000.0,
        revenue_growth_near=0.08,
        revenue_growth_mid=0.04,
        revenue_growth_terminal=0.025,
        ebit_margin_start=0.18,
        ebit_margin_target=0.20,
        tax_rate_start=0.22,
        tax_rate_target=0.23,
        capex_pct_start=0.05,
        capex_pct_target=0.045,
        da_pct_start=0.03,
        da_pct_target=0.028,
        dso_start=45.0,
        dso_target=44.0,
        dio_start=40.0,
        dio_target=39.0,
        dpo_start=35.0,
        dpo_target=36.0,
        wacc=0.09,
        exit_multiple=12.0,
        exit_metric="ev_ebitda",
        net_debt=200_000_000.0,
        shares_outstanding=100_000_000.0,
    )
    for key, value in overrides.items():
        setattr(base, key, value)
    return base


def test_terminal_blend_fallback_when_gordon_invalid():
    drivers = _drivers(wacc=0.03, revenue_growth_terminal=0.04)
    result = run_dcf_professional(drivers, ScenarioSpec(name="base", probability=1.0))

    assert result.terminal_breakdown.gordon_valid is False
    assert result.tv_method_fallback_flag is True
    assert result.terminal_breakdown.method_used == "exit_only"
    assert result.iv_exit is not None
    assert result.iv_blended == result.iv_exit


def test_nwc_driver_bridge_uses_dso_dio_dpo_identity():
    result = run_dcf_professional(_drivers(), ScenarioSpec(name="base", probability=1.0))
    year1 = result.projections[0]
    expected_nwc = year1.ar + year1.inventory - year1.ap
    assert abs(year1.nwc - expected_nwc) < 1e-6


def test_probability_weighted_expected_iv():
    drivers = _drivers()
    scenarios = [
        ScenarioSpec(name="bear", probability=0.2, growth_multiplier=0.8, margin_shift=-0.02, wacc_shift=0.01),
        ScenarioSpec(name="base", probability=0.6),
        ScenarioSpec(name="bull", probability=0.2, growth_multiplier=1.2, margin_shift=0.02, wacc_shift=-0.01),
    ]
    out = run_probabilistic_valuation(drivers, scenarios, current_price=10.0)

    weighted = sum(out.scenario_results[s.name].intrinsic_value_per_share * s.probability for s in scenarios)
    assert abs(out.expected_iv - weighted) < 1e-6
    assert out.expected_upside_pct is not None


def test_monotonicity_higher_wacc_lowers_iv():
    base = run_dcf_professional(_drivers(wacc=0.08), ScenarioSpec(name="base", probability=1.0))
    higher = run_dcf_professional(_drivers(wacc=0.12), ScenarioSpec(name="base", probability=1.0))
    assert base.intrinsic_value_per_share > higher.intrinsic_value_per_share


def test_deterministic_same_inputs_same_outputs():
    drivers = _drivers()
    scenario = ScenarioSpec(name="base", probability=1.0)
    r1 = run_dcf_professional(drivers, scenario)
    r2 = run_dcf_professional(copy.deepcopy(drivers), copy.deepcopy(scenario))

    assert r1.intrinsic_value_per_share == r2.intrinsic_value_per_share
    assert r1.enterprise_value == r2.enterprise_value
    assert r1.tv_method_fallback_flag == r2.tv_method_fallback_flag
