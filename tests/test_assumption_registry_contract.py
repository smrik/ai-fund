from __future__ import annotations

from dataclasses import fields

from src.contracts.assumption_registry import (
    ASSUMPTION_REGISTRY,
    AssumptionOwner,
    DriverFamily,
    canonical_assumption_name,
    get_assumption_definition,
    judgment_owned_fields,
)
from src.stage_02_valuation.valuation_types import ForecastDrivers
from src.stage_04_pipeline.agentic_handoff_profiles import (
    AGENT_PROPOSABLE_ASSUMPTION_FIELDS,
)


def test_registry_covers_every_forecast_driver_without_extra_fields() -> None:
    driver_fields = {field.name for field in fields(ForecastDrivers)}

    assert set(ASSUMPTION_REGISTRY) == driver_fields


def test_registry_canonicalizes_the_legacy_terminal_growth_alias_only_explicitly() -> None:
    assert canonical_assumption_name("terminal_growth") == "revenue_growth_terminal"
    assert (
        get_assumption_definition("revenue_growth_terminal").owner
        == AssumptionOwner.judgment
    )
    assert "wacc" not in judgment_owned_fields()
    assert set(judgment_owned_fields(DriverFamily.revenue)) == {
        "revenue_growth_near",
        "revenue_growth_mid",
        "revenue_growth_terminal",
    }


def test_legacy_agent_allowlist_is_derived_from_judgment_ownership() -> None:
    expected = {
        name
        for name, definition in ASSUMPTION_REGISTRY.items()
        if definition.owner == AssumptionOwner.judgment
    }

    assert set(AGENT_PROPOSABLE_ASSUMPTION_FIELDS) == expected
    assert "terminal_growth" not in AGENT_PROPOSABLE_ASSUMPTION_FIELDS
    assert "wacc" not in AGENT_PROPOSABLE_ASSUMPTION_FIELDS
    assert "net_debt" not in AGENT_PROPOSABLE_ASSUMPTION_FIELDS
    assert "ebit_margin_start" not in AGENT_PROPOSABLE_ASSUMPTION_FIELDS


def test_only_judgment_owned_drivers_support_direct_preview_and_apply() -> None:
    for definition in ASSUMPTION_REGISTRY.values():
        expected = definition.owner == AssumptionOwner.judgment
        assert definition.preview_supported is expected
        assert definition.apply_supported is expected
