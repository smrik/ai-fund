import pytest

from src.stage_02_valuation.driver_assessments import (
    DriverAssessment,
    build_driver_consensus,
)
from src.stage_02_valuation.scenario_policy import (
    build_context_scenario_policy,
    fixed_scenario_specs,
)
from src.stage_02_valuation.valuation_types import ForecastDrivers


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


def test_fixed_scenario_specs_preserve_official_defaults():
    specs = {spec.name: spec for spec in fixed_scenario_specs()}

    assert specs["bear"].probability == pytest.approx(0.20)
    assert specs["bear"].growth_multiplier == pytest.approx(0.8)
    assert specs["bear"].margin_shift == pytest.approx(-0.02)
    assert specs["bear"].wacc_shift == pytest.approx(0.01)
    assert specs["bear"].exit_multiple_multiplier == pytest.approx(0.9)
    assert specs["base"].probability == pytest.approx(0.60)
    assert specs["bull"].probability == pytest.approx(0.20)
    assert specs["bull"].growth_multiplier == pytest.approx(1.2)


def test_context_policy_widens_high_cyclicality_downside():
    resilient = build_context_scenario_policy(
        ticker="LOW",
        sector="Technology",
        industry="Software",
        drivers=_drivers(),
        story_profile={
            "cyclicality": "low",
            "capital_intensity": "low",
            "governance_risk": "low",
            "moat_strength": 4,
            "pricing_power": 4,
        },
    )
    cyclical = build_context_scenario_policy(
        ticker="HIGH",
        sector="Industrials",
        industry="Machinery",
        drivers=_drivers(),
        story_profile={
            "cyclicality": "high",
            "capital_intensity": "high",
            "governance_risk": "high",
            "moat_strength": 2,
            "pricing_power": 2,
        },
    )

    resilient_bear = resilient.context_specs[0]
    cyclical_bear = cyclical.context_specs[0]
    assert cyclical_bear.growth_multiplier < resilient_bear.growth_multiplier
    assert cyclical_bear.margin_shift < resilient_bear.margin_shift
    assert cyclical_bear.wacc_shift > resilient_bear.wacc_shift


def test_regime_weights_change_context_probabilities_only():
    policy = build_context_scenario_policy(
        ticker="REG",
        sector="Technology",
        industry="Software",
        drivers=_drivers(),
        story_profile={},
        regime_weights={"bear": 0.35, "base": 0.55, "bull": 0.10},
    )

    official = {spec.name: spec.probability for spec in policy.official_specs}
    context = {spec.name: spec.probability for spec in policy.context_specs}
    assert official == {"bear": 0.2, "base": 0.6, "bull": 0.2}
    assert context == {"bear": 0.35, "base": 0.55, "bull": 0.10}


def test_driver_consensus_flags_disagreement_without_mutating_drivers():
    drivers = _drivers(revenue_growth_near=0.08)
    consensus = build_driver_consensus(
        drivers,
        [
            DriverAssessment(source="industry", field="revenue_growth_near", proposed_value=0.05),
            DriverAssessment(source="company", field="revenue_growth_near", proposed_value=0.14),
        ],
    )

    assert drivers.revenue_growth_near == pytest.approx(0.08)
    assert len(consensus) == 1
    assert consensus[0].field == "revenue_growth_near"
    assert consensus[0].disagreement_flag is True
    assert consensus[0].official_action == "review"
