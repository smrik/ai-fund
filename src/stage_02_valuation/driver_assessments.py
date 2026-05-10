"""Advisory multi-source driver assessments for valuation review."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from statistics import mean
from typing import Any, Literal, cast

from src.stage_02_valuation.valuation_types import ForecastDrivers

Confidence = Literal["low", "medium", "high"]
ApprovalStatus = Literal["advisory", "pm_approved", "blocked"]
AgreementLevel = Literal["none", "low", "medium", "high"]
OfficialAction = Literal["none", "review", "override_required"]

_CONFIDENCE_WEIGHT = {"low": 0.5, "medium": 1.0, "high": 1.5}


@dataclass(slots=True)
class DriverAssessment:
    source: str
    field: str
    proposed_value: float | None = None
    range_low: float | None = None
    range_high: float | None = None
    confidence: Confidence = "medium"
    rationale: str = ""
    evidence_reference: str = ""
    approval_status: ApprovalStatus = "advisory"


@dataclass(slots=True)
class DriverConsensus:
    field: str
    current_value: float | None
    suggested_value: float | None
    suggested_range_low: float | None
    suggested_range_high: float | None
    source_count: int
    agreement_level: AgreementLevel
    disagreement_flag: bool
    official_action: OfficialAction
    sources: list[str]


def _driver_value(drivers: ForecastDrivers, field: str) -> float | None:
    value = getattr(drivers, field, None)
    return float(value) if isinstance(value, (int, float)) else None


def _weighted_mean(assessments: list[DriverAssessment]) -> float | None:
    values = [item for item in assessments if item.proposed_value is not None]
    if not values:
        return None
    total_weight = sum(_CONFIDENCE_WEIGHT[item.confidence] for item in values)
    if total_weight <= 0:
        return None
    return sum(float(item.proposed_value) * _CONFIDENCE_WEIGHT[item.confidence] for item in values) / total_weight


def _agreement_level(values: list[float], current_value: float | None) -> tuple[AgreementLevel, bool]:
    if len(values) <= 1:
        return ("none" if not values else "high"), False

    spread = max(values) - min(values)
    denominator = max(abs(current_value or 0.0), abs(mean(values)), 0.01)
    spread_ratio = spread / denominator
    if spread_ratio <= 0.05:
        return "high", False
    if spread_ratio <= 0.15:
        return "medium", False
    return "low", True


def build_driver_consensus(
    drivers: ForecastDrivers,
    assessments: list[DriverAssessment],
) -> list[DriverConsensus]:
    grouped: dict[str, list[DriverAssessment]] = {}
    for assessment in assessments:
        if assessment.approval_status == "blocked":
            continue
        grouped.setdefault(assessment.field, []).append(assessment)

    rows: list[DriverConsensus] = []
    for field, field_assessments in sorted(grouped.items()):
        current_value = _driver_value(drivers, field)
        proposed_values = [
            float(item.proposed_value)
            for item in field_assessments
            if item.proposed_value is not None
        ]
        range_lows = [
            float(item.range_low)
            for item in field_assessments
            if item.range_low is not None
        ]
        range_highs = [
            float(item.range_high)
            for item in field_assessments
            if item.range_high is not None
        ]
        agreement_level, disagreement_flag = _agreement_level(proposed_values, current_value)
        approved = any(item.approval_status == "pm_approved" for item in field_assessments)
        official_action = cast(
            OfficialAction,
            "override_required" if approved else ("review" if disagreement_flag else "none"),
        )
        rows.append(
            DriverConsensus(
                field=field,
                current_value=current_value,
                suggested_value=_weighted_mean(field_assessments),
                suggested_range_low=min(range_lows) if range_lows else None,
                suggested_range_high=max(range_highs) if range_highs else None,
                source_count=len(field_assessments),
                agreement_level=agreement_level,
                disagreement_flag=disagreement_flag,
                official_action=official_action,
                sources=sorted({item.source for item in field_assessments}),
            )
        )
    return rows


def consensus_to_jsonable(consensus: list[DriverConsensus]) -> list[dict[str, Any]]:
    return [asdict(row) for row in consensus]
