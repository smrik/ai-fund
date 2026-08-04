"""Pure statement tie-outs for historical operating-model starting points."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from typing import Literal, Mapping, Sequence

from src.contracts.judgment_runs import canonical_semantic_hash
from src.stage_00_data.source_reconciliation import (
    SourceAmount,
    reconciliation_tolerance,
)
from src.stage_02_valuation.valuation_types import ForecastDrivers


OperatingStatus = Literal["reconciled", "pending", "failed"]
TieOutStatus = Literal["pass", "fail"]
BoundHit = Literal["lower", "upper", "default"] | None


@dataclass(frozen=True, slots=True)
class ClampEvent:
    field_name: str
    raw_value: float | None
    resolved_value: float
    lower_bound: float
    upper_bound: float
    default_value: float
    source: str

    def __post_init__(self) -> None:
        numeric = (
            self.resolved_value,
            self.lower_bound,
            self.upper_bound,
            self.default_value,
        )
        if any(not math.isfinite(float(value)) for value in numeric):
            raise ValueError("clamp event values must be finite")
        if self.lower_bound > self.upper_bound:
            raise ValueError("clamp lower bound cannot exceed upper bound")
        if self.raw_value is not None and not math.isfinite(
            float(self.raw_value)
        ):
            raise ValueError("clamp raw value must be finite when present")
        if not self.field_name.strip() or not self.source.strip():
            raise ValueError("clamp event requires field_name and source")

    @property
    def was_clamped(self) -> bool:
        return self.raw_value is None or not math.isclose(
            float(self.raw_value),
            float(self.resolved_value),
            rel_tol=0.0,
            abs_tol=0.0,
        )

    @property
    def bound_hit(self) -> BoundHit:
        if not self.was_clamped:
            return None
        if self.raw_value is None:
            return "default"
        if float(self.raw_value) < self.lower_bound:
            return "lower"
        if float(self.raw_value) > self.upper_bound:
            return "upper"
        return "default"

    def to_dict(self) -> dict[str, object]:
        return {
            **asdict(self),
            "was_clamped": self.was_clamped,
            "bound_hit": self.bound_hit,
        }


@dataclass(frozen=True, slots=True)
class OperatingTieOut:
    name: str
    driver_name: str
    driver_value: float
    expected_value: float
    reported_value: float
    difference: float
    tolerance: float
    status: TieOutStatus
    source_fact_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class OperatingReconciliationResult:
    status: OperatingStatus
    tie_outs: tuple[OperatingTieOut, ...]
    clamp_events: tuple[ClampEvent, ...]
    reason_codes: tuple[str, ...]

    @property
    def unresolved_clamp_count(self) -> int:
        return sum(event.was_clamped for event in self.clamp_events)

    @property
    def fingerprint(self) -> str:
        return canonical_semantic_hash(asdict(self))

    def to_dict(self) -> dict[str, object]:
        return {
            **asdict(self),
            "clamp_events": tuple(
                event.to_dict() for event in self.clamp_events
            ),
            "unresolved_clamp_count": self.unresolved_clamp_count,
            "fingerprint": self.fingerprint,
        }


def _tie_out(
    *,
    name: str,
    driver_name: str,
    driver_value: float,
    expected: float,
    reported: SourceAmount,
    supporting_facts: Sequence[SourceAmount],
) -> OperatingTieOut:
    actual = abs(reported.base_value)
    difference = abs(expected - actual)
    tolerance = reconciliation_tolerance(
        expected,
        actual,
        monetary=True,
        usd_per_currency_unit=(
            float(reported.usd_per_currency_unit)
            if reported.usd_per_currency_unit is not None
            else 1.0
        ),
    )
    return OperatingTieOut(
        name=name,
        driver_name=driver_name,
        driver_value=float(driver_value),
        expected_value=float(expected),
        reported_value=float(actual),
        difference=float(difference),
        tolerance=float(tolerance),
        status="pass" if difference <= tolerance else "fail",
        source_fact_ids=tuple(
            amount.fact_id for amount in supporting_facts
        ),
    )


def _source_compatibility_reasons(
    reported: Mapping[str, SourceAmount],
) -> list[str]:
    if not reported:
        return []
    amounts = tuple(reported.values())
    tickers = {amount.ticker.upper() for amount in amounts}
    unit_kinds = {amount.unit_kind for amount in amounts}
    currencies = {
        amount.unit_currency
        for amount in amounts
        if amount.unit_currency
    }
    period_ends = {amount.period_end for amount in amounts}
    duration_amounts = tuple(
        amount for amount in amounts if amount.period_start
    )
    period_starts = {
        amount.period_start for amount in duration_amounts
    }
    period_kinds = {
        str(amount.period_kind or "").strip().lower()
        for amount in duration_amounts
    }
    reasons: list[str] = []
    if len(tickers) > 1:
        reasons.append("operating.ticker_mismatch")
    if unit_kinds != {"currency_scalar"}:
        reasons.append("operating.unit_mismatch")
    if len(currencies) != 1:
        reasons.append("operating.currency_mismatch")
    if len(period_ends) > 1:
        reasons.append("operating.period_mismatch")
    if len(period_starts) > 1 or len(period_kinds) > 1:
        reasons.append("operating.duration_window_mismatch")
    if currencies and next(iter(currencies)) != "USD":
        if any(
            amount.usd_per_currency_unit is None
            or not amount.fx_fingerprint
            for amount in amounts
        ):
            reasons.append("operating.fx_missing")
        fx_rates = {
            float(amount.usd_per_currency_unit)
            for amount in amounts
            if amount.usd_per_currency_unit is not None
        }
        fx_fingerprints = {
            amount.fx_fingerprint
            for amount in amounts
            if amount.fx_fingerprint
        }
        if len(fx_rates) > 1 or len(fx_fingerprints) > 1:
            reasons.append("operating.fx_mismatch")
    return reasons


def reconcile_operating_model(
    *,
    drivers: ForecastDrivers,
    reported: Mapping[str, SourceAmount],
    inventory_applicable: bool,
    clamp_events: Sequence[ClampEvent] = (),
) -> OperatingReconciliationResult:
    """Tie historical driver starts to authoritative reported statements."""

    reasons = _source_compatibility_reasons(reported)
    required = (
        "revenue",
        "cost_of_revenue",
        "accounts_receivable",
        "accounts_payable",
        "capex",
        "da",
    )
    if inventory_applicable:
        required = (*required, "inventory")
    missing = [key for key in required if key not in reported]
    reasons.extend(f"operating.{key}_missing" for key in missing)
    if reasons:
        status: OperatingStatus = (
            "failed"
            if any(
                reason.endswith("mismatch")
                or reason == "operating.fx_missing"
                for reason in reasons
            )
            else "pending"
        )
        events = tuple(clamp_events)
        if any(event.was_clamped for event in events):
            reasons.append("operating.clamp_fired")
        return OperatingReconciliationResult(
            status=status,
            tie_outs=(),
            clamp_events=events,
            reason_codes=tuple(dict.fromkeys(reasons)),
        )

    revenue = reported["revenue"]
    revenue_difference = abs(
        float(drivers.revenue_base) - revenue.base_value
    )
    revenue_tolerance = reconciliation_tolerance(
        float(drivers.revenue_base),
        revenue.base_value,
        monetary=True,
    )
    if revenue_difference > revenue_tolerance:
        reasons.append("operating.revenue_base_failed")

    cogs = reported["cost_of_revenue"]
    tie_outs = [
        _tie_out(
            name="dso_to_accounts_receivable",
            driver_name="dso_start",
            driver_value=drivers.dso_start,
            expected=(
                revenue.base_value * float(drivers.dso_start) / 365.0
            ),
            reported=reported["accounts_receivable"],
            supporting_facts=(
                revenue,
                reported["accounts_receivable"],
            ),
        ),
        _tie_out(
            name="dpo_to_accounts_payable",
            driver_name="dpo_start",
            driver_value=drivers.dpo_start,
            expected=(
                abs(cogs.base_value) * float(drivers.dpo_start) / 365.0
            ),
            reported=reported["accounts_payable"],
            supporting_facts=(cogs, reported["accounts_payable"]),
        ),
        _tie_out(
            name="capex_pct_to_cash_flow",
            driver_name="capex_pct_start",
            driver_value=drivers.capex_pct_start,
            expected=(
                revenue.base_value * float(drivers.capex_pct_start)
            ),
            reported=reported["capex"],
            supporting_facts=(revenue, reported["capex"]),
        ),
        _tie_out(
            name="da_pct_to_cash_flow",
            driver_name="da_pct_start",
            driver_value=drivers.da_pct_start,
            expected=revenue.base_value * float(drivers.da_pct_start),
            reported=reported["da"],
            supporting_facts=(revenue, reported["da"]),
        ),
    ]
    if inventory_applicable:
        tie_outs.insert(
            1,
            _tie_out(
                name="dio_to_inventory",
                driver_name="dio_start",
                driver_value=drivers.dio_start,
                expected=(
                    abs(cogs.base_value) * float(drivers.dio_start) / 365.0
                ),
                reported=reported["inventory"],
                supporting_facts=(cogs, reported["inventory"]),
            ),
        )
    for tie in tie_outs:
        if tie.status == "fail":
            reasons.append(f"operating.{tie.name}_failed")
    events = tuple(clamp_events)
    if any(event.was_clamped for event in events):
        reasons.append("operating.clamp_fired")
    status = (
        "failed"
        if any(
            reason == "operating.revenue_base_failed"
            or reason.endswith("_failed")
            for reason in reasons
        )
        else "reconciled"
    )
    return OperatingReconciliationResult(
        status=status,
        tie_outs=tuple(tie_outs),
        clamp_events=events,
        reason_codes=tuple(dict.fromkeys(reasons)),
    )


__all__ = [
    "ClampEvent",
    "OperatingReconciliationResult",
    "OperatingTieOut",
    "reconcile_operating_model",
]
