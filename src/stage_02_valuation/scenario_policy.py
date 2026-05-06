"""Scenario policy builders for official and advisory context-aware DCF cases."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping

from src.stage_02_valuation.driver_assessments import DriverConsensus
from src.stage_02_valuation.valuation_types import ForecastDrivers, ScenarioSpec

SCENARIO_ORDER = ("bear", "base", "bull")


@dataclass(frozen=True, slots=True)
class ScenarioShock:
    name: str
    probability: float
    growth_multiplier: float = 1.0
    margin_shift: float = 0.0
    wacc_shift: float = 0.0
    terminal_growth_shift: float = 0.0
    exit_multiple_multiplier: float = 1.0

    def to_spec(self, probability: float | None = None) -> ScenarioSpec:
        return ScenarioSpec(
            name=self.name,
            probability=self.probability if probability is None else probability,
            growth_multiplier=self.growth_multiplier,
            margin_shift=self.margin_shift,
            wacc_shift=self.wacc_shift,
            terminal_growth_shift=self.terminal_growth_shift,
            exit_multiple_multiplier=self.exit_multiple_multiplier,
        )


@dataclass(slots=True)
class ScenarioPolicyResult:
    official_specs: list[ScenarioSpec]
    context_specs: list[ScenarioSpec]
    metadata: dict[str, Any]


DEFAULT_SCENARIO_SHOCKS: dict[str, ScenarioShock] = {
    "bear": ScenarioShock(
        name="bear",
        probability=0.20,
        growth_multiplier=0.8,
        margin_shift=-0.02,
        wacc_shift=0.01,
        exit_multiple_multiplier=0.9,
    ),
    "base": ScenarioShock(name="base", probability=0.60),
    "bull": ScenarioShock(
        name="bull",
        probability=0.20,
        growth_multiplier=1.2,
        margin_shift=0.02,
        wacc_shift=-0.01,
        exit_multiple_multiplier=1.1,
    ),
}


def fixed_scenario_specs() -> list[ScenarioSpec]:
    return [DEFAULT_SCENARIO_SHOCKS[name].to_spec() for name in SCENARIO_ORDER]


def _story_bucket(story_profile: Mapping[str, Any] | None, key: str, default: str = "medium") -> str:
    value = str((story_profile or {}).get(key, default)).strip().lower()
    return value if value in {"low", "medium", "high"} else default


def _story_score(story_profile: Mapping[str, Any] | None, key: str, default: int = 3) -> int:
    try:
        value = int((story_profile or {}).get(key, default))
    except (TypeError, ValueError):
        return default
    return max(1, min(5, value))


def _growth_maturity(drivers: ForecastDrivers) -> str:
    if drivers.revenue_growth_near >= 0.12:
        return "high_growth"
    if drivers.revenue_growth_near <= 0.04:
        return "mature"
    return "middle"


def _disagreement_width(consensus: list[DriverConsensus] | None) -> float:
    if not consensus:
        return 1.0
    stressed_fields = {
        "revenue_growth_near",
        "revenue_growth_mid",
        "ebit_margin_target",
        "capex_pct_target",
        "wacc",
        "exit_multiple",
    }
    disagreement_count = sum(
        1
        for row in consensus
        if row.field in stressed_fields and row.disagreement_flag
    )
    return min(1.25, 1.0 + disagreement_count * 0.05)


def _context_probabilities(regime_weights: Any | None) -> tuple[dict[str, float], str]:
    if regime_weights is None:
        return {name: DEFAULT_SCENARIO_SHOCKS[name].probability for name in SCENARIO_ORDER}, "fixed_default"

    if isinstance(regime_weights, Mapping):
        return {
            name: float(regime_weights.get(name, DEFAULT_SCENARIO_SHOCKS[name].probability))
            for name in SCENARIO_ORDER
        }, "regime_mapping"

    return {
        "bear": float(getattr(regime_weights, "bear", DEFAULT_SCENARIO_SHOCKS["bear"].probability)),
        "base": float(getattr(regime_weights, "base", DEFAULT_SCENARIO_SHOCKS["base"].probability)),
        "bull": float(getattr(regime_weights, "bull", DEFAULT_SCENARIO_SHOCKS["bull"].probability)),
    }, "regime_model"


def build_context_scenario_policy(
    *,
    ticker: str,
    sector: str,
    industry: str,
    drivers: ForecastDrivers,
    story_profile: Mapping[str, Any] | None = None,
    regime_weights: Any | None = None,
    driver_consensus: list[DriverConsensus] | None = None,
) -> ScenarioPolicyResult:
    """Build official fixed specs plus advisory specs adjusted for company context."""
    official_specs = fixed_scenario_specs()
    probabilities, probability_source = _context_probabilities(regime_weights)

    cyclicality = _story_bucket(story_profile, "cyclicality")
    capital_intensity = _story_bucket(story_profile, "capital_intensity")
    governance_risk = _story_bucket(story_profile, "governance_risk")
    moat_strength = _story_score(story_profile, "moat_strength")
    pricing_power = _story_score(story_profile, "pricing_power")
    maturity = _growth_maturity(drivers)

    width = {"low": 0.75, "medium": 1.0, "high": 1.35}[cyclicality]
    if capital_intensity == "high":
        width += 0.10
    elif capital_intensity == "low":
        width -= 0.05
    if maturity == "high_growth":
        width += 0.10
    elif maturity == "mature":
        width -= 0.10
    width *= _disagreement_width(driver_consensus)
    width = max(0.60, min(1.60, width))

    resilience = max(0, moat_strength - 3) * 0.05 + max(0, pricing_power - 3) * 0.04
    governance_pressure = {"low": -0.001, "medium": 0.0, "high": 0.004}[governance_risk]
    capital_pressure = {"low": -0.001, "medium": 0.0, "high": 0.003}[capital_intensity]

    bear = DEFAULT_SCENARIO_SHOCKS["bear"]
    bull = DEFAULT_SCENARIO_SHOCKS["bull"]
    context_specs = [
        ScenarioSpec(
            name="bear",
            probability=probabilities["bear"],
            growth_multiplier=max(0.60, 1.0 - (1.0 - bear.growth_multiplier) * width + resilience),
            margin_shift=bear.margin_shift * width + resilience * 0.01,
            wacc_shift=max(0.0, bear.wacc_shift * width + governance_pressure + capital_pressure),
            terminal_growth_shift=bear.terminal_growth_shift,
            exit_multiple_multiplier=max(
                0.70,
                1.0 - (1.0 - bear.exit_multiple_multiplier) * width - max(0.0, governance_pressure * 5),
            ),
        ),
        ScenarioSpec(name="base", probability=probabilities["base"]),
        ScenarioSpec(
            name="bull",
            probability=probabilities["bull"],
            growth_multiplier=min(1.50, 1.0 + (bull.growth_multiplier - 1.0) * width + resilience),
            margin_shift=bull.margin_shift * width + resilience * 0.01,
            wacc_shift=min(0.0, bull.wacc_shift * max(0.75, width - max(0.0, governance_pressure * 10))),
            terminal_growth_shift=bull.terminal_growth_shift,
            exit_multiple_multiplier=min(1.35, 1.0 + (bull.exit_multiple_multiplier - 1.0) * width + resilience),
        ),
    ]

    metadata = {
        "policy": "context_advisory_v1",
        "official_policy": "fixed_default",
        "ticker": ticker.upper(),
        "sector": sector,
        "industry": industry,
        "probability_source": probability_source,
        "context_inputs": {
            "cyclicality": cyclicality,
            "capital_intensity": capital_intensity,
            "governance_risk": governance_risk,
            "moat_strength": moat_strength,
            "pricing_power": pricing_power,
            "maturity": maturity,
            "driver_disagreement_width": round(_disagreement_width(driver_consensus), 4),
            "shock_width": round(width, 4),
        },
        "official_specs": [asdict(spec) for spec in official_specs],
        "context_specs": [asdict(spec) for spec in context_specs],
    }
    return ScenarioPolicyResult(
        official_specs=official_specs,
        context_specs=context_specs,
        metadata=metadata,
    )
