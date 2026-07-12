from __future__ import annotations

from datetime import date

import pytest

from src.contracts.professional_financial_model import AvailabilityStatus, CheckStatus
from src.stage_02_valuation.integrated_financial_forecast import (
    DRIVER_SPECS,
    FORECAST_YEARS,
    DriverPath,
    IncompleteScenarioDriversError,
    InvalidScenarioPolicyError,
    ScenarioDriverSet,
    build_complete_scenario_forecasts,
)
from tests.test_integrated_financial_model_forecast import (
    BASE_DRIVER_VALUES,
    _driver_path,
    complete_historical_seed,
    driver_set,
)


def test_scenario_driver_sets_are_complete_five_year_paths_without_probabilities() -> None:
    paths = tuple(
        _driver_path(
            key=key,
            value=value,
            scenario_key="Base",
            approved=True,
        )
        for key, value in BASE_DRIVER_VALUES.items()
        if key != "dso"
    )
    with pytest.raises(IncompleteScenarioDriversError, match="dso"):
        ScenarioDriverSet(scenario_key="Base", paths=paths)

    with pytest.raises(ValueError, match="exactly five"):
        DriverPath(
            key="dso",
            values=(45.0,) * 4,
            unit="days",
            source_ref="fixture:dso",
            method="synthetic_test_driver",
            approval_ref="approval:dso",
        )

    with pytest.raises(InvalidScenarioPolicyError, match="probability"):
        DriverPath(
            key="scenario_probability",
            values=(0.5,) * FORECAST_YEARS,
            unit="percent",
            source_ref="fixture:probability",
            method="synthetic_test_driver",
            approval_ref="approval:probability",
        )


def test_base_upside_downside_recalculate_complete_models_on_one_axis() -> None:
    scenarios = (
        driver_set("Base"),
        driver_set(
            "Upside",
            changes={
                "revenue_growth": 0.15,
                "gross_margin": 0.63,
                "sga_percent_revenue": 0.09,
                "dso": 42.0,
                "capex_percent_revenue": 0.055,
            },
        ),
        driver_set(
            "Downside",
            changes={
                "revenue_growth": 0.04,
                "gross_margin": 0.56,
                "sga_percent_revenue": 0.12,
                "dso": 52.0,
                "capex_percent_revenue": 0.07,
            },
        ),
    )
    bundle = build_complete_scenario_forecasts(
        complete_historical_seed(),
        scenarios,
        last_historical_period_end=date(2026, 6, 30),
    )

    assert tuple(item.scenario_key for item in bundle.scenarios) == (
        "Base",
        "Upside",
        "Downside",
    )
    assert not hasattr(bundle, "probabilities")
    assert len({item.model.period_axis.canonical_hash() for item in bundle.scenarios}) == 1
    assert all(set(item.line_index) == set(bundle.registry_keys) for item in bundle.scenarios)
    assert all(
        len(line.values) == FORECAST_YEARS
        for item in bundle.scenarios
        for line in item.line_index.values()
    )

    base = bundle.scenario("Base")
    upside = bundle.scenario("Upside")
    downside = bundle.scenario("Downside")
    assert upside.numeric("is.revenue", 5) > base.numeric("is.revenue", 5) > downside.numeric("is.revenue", 5)
    assert upside.numeric("shares.diluted_eps", 5) > base.numeric("shares.diluted_eps", 5) > downside.numeric("shares.diluted_eps", 5)
    assert bundle.line_delta("is.revenue", "Upside", 1) == pytest.approx(
        upside.numeric("is.revenue", 1) - base.numeric("is.revenue", 1)
    )

    # Full scenario calculations pass independently; outputs are not a scalar
    # applied to Base cash flow or intrinsic value.
    assert upside.numeric("bs.accounts_receivable", 1) == pytest.approx(
        upside.numeric("is.revenue", 1) * 42.0 / 365.0
    )
    assert downside.numeric("cf.capex", 1) == pytest.approx(
        -downside.numeric("is.revenue", 1) * 0.07
    )
    for item in bundle.scenarios:
        arithmetic = [
            check
            for check in item.model.check_results
            if check.check_id.split(":", 1)[0]
            in {"balance_sheet", "cash_flow", "debt_tie", "cash_tie", "shares_tie", "fcfe_bridge"}
        ]
        assert arithmetic
        assert all(check.status is CheckStatus.PASS for check in arithmetic)
        assert all(abs(check.difference or 0.0) <= 0.1 for check in arithmetic)


def test_bundle_rejects_missing_duplicate_or_unapproved_scenario_identity() -> None:
    seed = complete_historical_seed()
    kwargs = {"last_historical_period_end": date(2026, 6, 30)}

    with pytest.raises(InvalidScenarioPolicyError, match="Base, Upside, and Downside"):
        build_complete_scenario_forecasts(seed, (driver_set("Base"),), **kwargs)

    with pytest.raises(InvalidScenarioPolicyError, match="duplicate"):
        build_complete_scenario_forecasts(
            seed,
            (driver_set("Base"), driver_set("Base"), driver_set("Downside")),
            **kwargs,
        )

    bad_upside = ScenarioDriverSet(
        scenario_key="Upside",
        parent_scenario_key="Downside",
        paths=driver_set("Upside").paths,
    )
    with pytest.raises(InvalidScenarioPolicyError, match="parent Base"):
        build_complete_scenario_forecasts(
            seed,
            (driver_set("Base"), bad_upside, driver_set("Downside")),
            **kwargs,
        )


def test_all_scenarios_keep_missing_segment_and_kpi_evidence_typed() -> None:
    bundle = build_complete_scenario_forecasts(
        complete_historical_seed(),
        (driver_set("Base"), driver_set("Upside"), driver_set("Downside")),
        last_historical_period_end=date(2026, 6, 30),
    )

    for scenario in bundle.scenarios:
        for key in ("segment.revenue", "segment.operating_income", "segment.assets", "segment.kpi"):
            values = scenario.line_index[key].values
            assert all(value.value is None for value in values)
            assert all(value.state.status is AvailabilityStatus.PM_REQUIRED for value in values)
