"""Canonical valuation-assumption vocabulary and ownership metadata.

This registry is intentionally static.  It is the shared contract between
judgment prompts, PM review, and deterministic replay; it does not contain
ticker-specific finance rules or choose assumption values.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class AssumptionOwner(str, Enum):
    historical = "historical"
    deterministic = "deterministic"
    reconciled = "reconciled"
    judgment = "judgment"


class AssumptionUnit(str, Enum):
    decimal = "decimal"
    days = "days"
    money = "money"
    multiple = "multiple"
    shares = "shares"
    categorical = "categorical"


class DriverFamily(str, Enum):
    revenue = "revenue"
    profitability_tax = "profitability_tax"
    reinvestment_working_capital = "reinvestment_working_capital"
    terminal_capital_comps = "terminal_capital_comps"


class ApplicabilityRule(str, Enum):
    required = "required"
    conditional = "conditional"


class ScenarioDirection(str, Enum):
    ascending = "ascending"
    descending = "descending"
    unordered = "unordered"


@dataclass(frozen=True, slots=True)
class AssumptionDefinition:
    name: str
    unit: AssumptionUnit
    owner: AssumptionOwner
    family: DriverFamily | None = None
    applicability: ApplicabilityRule = ApplicabilityRule.required
    scenario_direction: ScenarioDirection | None = None
    aliases: tuple[str, ...] = ()
    preview_supported: bool = True
    apply_supported: bool = True


def _definition(
    name: str,
    unit: AssumptionUnit,
    owner: AssumptionOwner,
    *,
    family: DriverFamily | None = None,
    applicability: ApplicabilityRule = ApplicabilityRule.required,
    scenario_direction: ScenarioDirection | None = None,
    aliases: tuple[str, ...] = (),
    preview_supported: bool | None = None,
    apply_supported: bool | None = None,
) -> AssumptionDefinition:
    directly_mutable = owner == AssumptionOwner.judgment
    return AssumptionDefinition(
        name=name,
        unit=unit,
        owner=owner,
        family=family,
        applicability=applicability,
        scenario_direction=scenario_direction,
        aliases=aliases,
        preview_supported=(
            directly_mutable
            if preview_supported is None
            else preview_supported
        ),
        apply_supported=(
            directly_mutable
            if apply_supported is None
            else apply_supported
        ),
    )


ASSUMPTION_REGISTRY: dict[str, AssumptionDefinition] = {
    "revenue_base": _definition(
        "revenue_base", AssumptionUnit.money, AssumptionOwner.historical
    ),
    "revenue_growth_near": _definition(
        "revenue_growth_near",
        AssumptionUnit.decimal,
        AssumptionOwner.judgment,
        family=DriverFamily.revenue,
        scenario_direction=ScenarioDirection.ascending,
    ),
    "revenue_growth_mid": _definition(
        "revenue_growth_mid",
        AssumptionUnit.decimal,
        AssumptionOwner.judgment,
        family=DriverFamily.revenue,
        scenario_direction=ScenarioDirection.ascending,
    ),
    "revenue_growth_terminal": _definition(
        "revenue_growth_terminal",
        AssumptionUnit.decimal,
        AssumptionOwner.judgment,
        family=DriverFamily.revenue,
        scenario_direction=ScenarioDirection.ascending,
        aliases=("terminal_growth",),
    ),
    "ebit_margin_start": _definition(
        "ebit_margin_start", AssumptionUnit.decimal, AssumptionOwner.historical
    ),
    "ebit_margin_target": _definition(
        "ebit_margin_target",
        AssumptionUnit.decimal,
        AssumptionOwner.judgment,
        family=DriverFamily.profitability_tax,
        scenario_direction=ScenarioDirection.ascending,
    ),
    "tax_rate_start": _definition(
        "tax_rate_start", AssumptionUnit.decimal, AssumptionOwner.historical
    ),
    "tax_rate_target": _definition(
        "tax_rate_target",
        AssumptionUnit.decimal,
        AssumptionOwner.judgment,
        family=DriverFamily.profitability_tax,
        scenario_direction=ScenarioDirection.descending,
    ),
    "capex_pct_start": _definition(
        "capex_pct_start", AssumptionUnit.decimal, AssumptionOwner.historical
    ),
    "capex_pct_target": _definition(
        "capex_pct_target",
        AssumptionUnit.decimal,
        AssumptionOwner.judgment,
        family=DriverFamily.reinvestment_working_capital,
        scenario_direction=ScenarioDirection.descending,
    ),
    "da_pct_start": _definition(
        "da_pct_start", AssumptionUnit.decimal, AssumptionOwner.historical
    ),
    "da_pct_target": _definition(
        "da_pct_target",
        AssumptionUnit.decimal,
        AssumptionOwner.judgment,
        family=DriverFamily.reinvestment_working_capital,
        scenario_direction=ScenarioDirection.unordered,
    ),
    "dso_start": _definition(
        "dso_start", AssumptionUnit.days, AssumptionOwner.historical
    ),
    "dso_target": _definition(
        "dso_target",
        AssumptionUnit.days,
        AssumptionOwner.judgment,
        family=DriverFamily.reinvestment_working_capital,
        scenario_direction=ScenarioDirection.descending,
    ),
    "dio_start": _definition(
        "dio_start",
        AssumptionUnit.days,
        AssumptionOwner.historical,
        applicability=ApplicabilityRule.conditional,
    ),
    "dio_target": _definition(
        "dio_target",
        AssumptionUnit.days,
        AssumptionOwner.judgment,
        family=DriverFamily.reinvestment_working_capital,
        applicability=ApplicabilityRule.conditional,
        scenario_direction=ScenarioDirection.descending,
    ),
    "dpo_start": _definition(
        "dpo_start", AssumptionUnit.days, AssumptionOwner.historical
    ),
    "dpo_target": _definition(
        "dpo_target",
        AssumptionUnit.days,
        AssumptionOwner.judgment,
        family=DriverFamily.reinvestment_working_capital,
        scenario_direction=ScenarioDirection.ascending,
    ),
    "wacc": _definition(
        "wacc", AssumptionUnit.decimal, AssumptionOwner.deterministic
    ),
    "exit_multiple": _definition(
        "exit_multiple",
        AssumptionUnit.multiple,
        AssumptionOwner.judgment,
        family=DriverFamily.terminal_capital_comps,
        scenario_direction=ScenarioDirection.ascending,
    ),
    "exit_metric": _definition(
        "exit_metric", AssumptionUnit.categorical, AssumptionOwner.deterministic
    ),
    "net_debt": _definition(
        "net_debt", AssumptionUnit.money, AssumptionOwner.reconciled
    ),
    "shares_outstanding": _definition(
        "shares_outstanding", AssumptionUnit.shares, AssumptionOwner.reconciled
    ),
    "terminal_blend_gordon_weight": _definition(
        "terminal_blend_gordon_weight",
        AssumptionUnit.decimal,
        AssumptionOwner.deterministic,
    ),
    "terminal_blend_exit_weight": _definition(
        "terminal_blend_exit_weight",
        AssumptionUnit.decimal,
        AssumptionOwner.deterministic,
    ),
    "invested_capital_start": _definition(
        "invested_capital_start",
        AssumptionUnit.money,
        AssumptionOwner.historical,
        applicability=ApplicabilityRule.conditional,
    ),
    "ronic_terminal": _definition(
        "ronic_terminal",
        AssumptionUnit.decimal,
        AssumptionOwner.judgment,
        family=DriverFamily.terminal_capital_comps,
        scenario_direction=ScenarioDirection.ascending,
    ),
    "non_operating_assets": _definition(
        "non_operating_assets", AssumptionUnit.money, AssumptionOwner.reconciled
    ),
    "minority_interest": _definition(
        "minority_interest", AssumptionUnit.money, AssumptionOwner.reconciled
    ),
    "preferred_equity": _definition(
        "preferred_equity", AssumptionUnit.money, AssumptionOwner.reconciled
    ),
    "pension_deficit": _definition(
        "pension_deficit", AssumptionUnit.money, AssumptionOwner.reconciled
    ),
    "lease_liabilities": _definition(
        "lease_liabilities", AssumptionUnit.money, AssumptionOwner.reconciled
    ),
    "options_value": _definition(
        "options_value", AssumptionUnit.money, AssumptionOwner.reconciled
    ),
    "convertibles_value": _definition(
        "convertibles_value", AssumptionUnit.money, AssumptionOwner.reconciled
    ),
    "cost_of_equity": _definition(
        "cost_of_equity",
        AssumptionUnit.decimal,
        AssumptionOwner.deterministic,
        applicability=ApplicabilityRule.conditional,
    ),
    "debt_weight": _definition(
        "debt_weight", AssumptionUnit.decimal, AssumptionOwner.deterministic
    ),
    "cogs_pct_of_revenue": _definition(
        "cogs_pct_of_revenue",
        AssumptionUnit.decimal,
        AssumptionOwner.judgment,
        family=DriverFamily.profitability_tax,
        scenario_direction=ScenarioDirection.descending,
    ),
    "annual_dilution_pct": _definition(
        "annual_dilution_pct",
        AssumptionUnit.decimal,
        AssumptionOwner.judgment,
        family=DriverFamily.terminal_capital_comps,
        scenario_direction=ScenarioDirection.descending,
    ),
}


def canonical_assumption_name(name: str) -> str:
    cleaned = str(name).strip()
    if cleaned in ASSUMPTION_REGISTRY:
        return cleaned
    for definition in ASSUMPTION_REGISTRY.values():
        if cleaned in definition.aliases:
            return definition.name
    raise KeyError(f"unknown valuation assumption: {name}")


def get_assumption_definition(name: str) -> AssumptionDefinition:
    return ASSUMPTION_REGISTRY[canonical_assumption_name(name)]


def judgment_owned_fields(
    family: DriverFamily | str | None = None,
) -> tuple[str, ...]:
    selected_family = DriverFamily(family) if family is not None else None
    return tuple(
        name
        for name, definition in ASSUMPTION_REGISTRY.items()
        if definition.owner == AssumptionOwner.judgment
        and (selected_family is None or definition.family == selected_family)
    )
