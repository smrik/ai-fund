import copy

import pytest

from src.stage_02_valuation.professional_dcf import (
    ForecastDrivers,
    ScenarioSpec,
    reverse_dcf_professional,
    run_dcf_professional,
    run_fcfe_valuation,
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


def test_reverse_dcf_professional_round_trip_base_scenario():
    drivers = _drivers(revenue_growth_near=0.10, revenue_growth_mid=0.065)
    base = run_dcf_professional(drivers, ScenarioSpec(name="base", probability=1.0))

    implied = reverse_dcf_professional(drivers, target_price=base.intrinsic_value_per_share, scenario="base")

    assert implied is not None
    assert abs(implied - 0.10) < 0.005


def test_reverse_dcf_professional_returns_none_out_of_range():
    drivers = _drivers()
    implied = reverse_dcf_professional(drivers, target_price=1_000_000.0, scenario="base")
    assert implied is None


def test_driver_validation_raises_on_invalid_inputs():
    scenario = ScenarioSpec(name="base", probability=1.0)

    with pytest.raises(ValueError):
        run_dcf_professional(_drivers(revenue_base=-1.0), scenario)

    with pytest.raises(ValueError):
        run_dcf_professional(_drivers(shares_outstanding=0.0), scenario)

    with pytest.raises(ValueError):
        run_dcf_professional(_drivers(wacc=0.25), scenario)


def test_driver_validation_accepts_boundary_values():
    scenario = ScenarioSpec(name="base", probability=1.0)
    drivers = _drivers(
        revenue_growth_near=-0.20,
        revenue_growth_mid=-0.20,
        revenue_growth_terminal=0.00,
        ebit_margin_start=0.00,
        ebit_margin_target=0.80,
        tax_rate_start=0.05,
        tax_rate_target=0.45,
        capex_pct_start=0.00,
        capex_pct_target=0.35,
        da_pct_start=0.00,
        da_pct_target=0.25,
        wacc=0.20,
        exit_multiple=40.0,
        shares_outstanding=1.0,
    )

    result = run_dcf_professional(drivers, scenario)
    assert result.intrinsic_value_per_share is not None



def test_enterprise_to_equity_bridge_includes_non_operating_assets_and_claims():
    scenario = ScenarioSpec(name="base", probability=1.0)
    base = run_dcf_professional(
        _drivers(
            non_operating_assets=0.0,
            minority_interest=0.0,
            preferred_equity=0.0,
            pension_deficit=0.0,
            lease_liabilities=0.0,
            options_value=0.0,
            convertibles_value=0.0,
        ),
        scenario,
    )
    adjusted = run_dcf_professional(
        _drivers(
            non_operating_assets=100_000_000.0,
            minority_interest=25_000_000.0,
            preferred_equity=10_000_000.0,
            pension_deficit=5_000_000.0,
            lease_liabilities=8_000_000.0,
            options_value=4_000_000.0,
            convertibles_value=3_000_000.0,
        ),
        scenario,
    )

    expected_delta_per_share = (
        100_000_000.0 - (25_000_000.0 + 10_000_000.0 + 5_000_000.0 + 8_000_000.0 + 4_000_000.0 + 3_000_000.0)
    ) / 100_000_000.0

    assert adjusted.enterprise_value_operations == pytest.approx(base.enterprise_value_operations, rel=1e-9)
    assert adjusted.intrinsic_value_per_share == pytest.approx(
        base.intrinsic_value_per_share + expected_delta_per_share,
        rel=1e-9,
    )


def test_ep_and_fcfe_outputs_populated_for_base_case():
    result = run_dcf_professional(_drivers(), ScenarioSpec(name="base", probability=1.0))

    assert result.enterprise_value_operations is not None
    assert result.enterprise_value_total is not None
    assert result.ep_enterprise_value is not None
    assert result.ep_intrinsic_value_per_share is not None
    assert result.dcf_ep_gap_pct is not None
    assert result.fcfe_intrinsic_value_per_share is not None
    assert result.fcfe_equity_value is not None
    assert result.fcfe_terminal_value is not None
    assert result.health_flags is not None
    assert "ep_reconcile_flag" in result.health_flags
    assert result.terminal_breakdown.fcff_11_bridge is not None
    assert result.terminal_breakdown.gordon_formula_mode in {"value_driver", "bridge"}


def test_run_fcfe_valuation_matches_dcf_fcfe_branch():
    drivers = _drivers()
    scenario = ScenarioSpec(name="base", probability=1.0)
    dcf = run_dcf_professional(drivers, scenario)
    fcfe = run_fcfe_valuation(drivers, scenario)

    assert dcf.fcfe_intrinsic_value_per_share is not None
    assert dcf.fcfe_equity_value is not None
    assert fcfe.intrinsic_value_per_share == pytest.approx(dcf.fcfe_intrinsic_value_per_share, rel=1e-9)
    assert fcfe.equity_value == pytest.approx(dcf.fcfe_equity_value, rel=1e-9)


