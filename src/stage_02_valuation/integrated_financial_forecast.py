"""Deterministic five-year integrated financial forecasts and scenarios.

The public input boundary is deliberately small and replayable. ``historical``
is either (a) a mapping from canonical line-item key to the latest normalized
annual value, or (b) a historical-result adapter exposing ``period_keys`` and
``value(canonical_key, period_key)``. Values use the registry's normalized
sign convention: expenses, cash outflows, accumulated depreciation, and
treasury stock are negative. A real zero is never treated as missing.

Scenario paths are operating and balance-sheet inputs. They are not valuation
or output multipliers, contain no probabilities, and cover five explicit
annual periods. Provisional paths may be calculated for diagnostic review, but
they require a queue ID and leave the result in ``PM_REQUIRED`` state.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
import hashlib
import json
import math
import re
from types import MappingProxyType
from typing import Any

from src.contracts.professional_financial_model import (
    AvailabilityState,
    AvailabilityStatus,
    CheckResult,
    CheckStatus,
    LineItemSpec,
    DriverGroup,
    LineSeries,
    ModelPeriod,
    ModelResult,
    PeriodAxis,
    PeriodType,
    PeriodValue,
    ScheduleResult,
    StatementResult,
)
from src.stage_02_valuation.model_line_items import professional_line_item_registry


FORECAST_YEARS = 5
BALANCE_TOLERANCE = 0.1
CIRCULARITY_POLICY_ID = "lagged_average_interest_minimum_cash_v1"
DEBT_CONVENTION_ID = "borrowings_excluding_lease_liabilities_v1"
SCENARIO_KEYS = ("Base", "Upside", "Downside")

__all__ = (
    "BALANCE_TOLERANCE",
    "CIRCULARITY_POLICY_ID",
    "DEBT_CONVENTION_ID",
    "DRIVER_SPECS",
    "FORECAST_YEARS",
    "CircularityPolicy",
    "DebtConvention",
    "DriverPath",
    "DriverSpec",
    "ForecastCalculationError",
    "ForecastPolicyError",
    "ForecastScenarioBundle",
    "ForecastScenarioResult",
    "IncompleteHistoricalSeedError",
    "IncompleteScenarioDriversError",
    "InvalidScenarioPolicyError",
    "ScenarioDriverSet",
    "UnavailableForecastValueError",
    "build_complete_scenario_forecasts",
    "build_five_year_forecast",
)


class ForecastPolicyError(ValueError):
    """Base error for deterministic forecast-policy violations."""


class IncompleteHistoricalSeedError(ForecastPolicyError):
    """Raised when a required normalized historical seed is unavailable."""


class IncompleteScenarioDriversError(ForecastPolicyError):
    """Raised when a scenario does not supply the exact driver contract."""


class InvalidScenarioPolicyError(ForecastPolicyError):
    """Raised for probabilities, invalid scenario identity, or hidden policy."""


class ForecastCalculationError(ForecastPolicyError):
    """Raised when supplied paths imply an impossible financial state."""


class UnavailableForecastValueError(ForecastPolicyError):
    """Raised when a caller requests a numeric value for a typed gap."""


@dataclass(frozen=True)
class DriverSpec:
    key: str
    unit: str
    minimum: float | None = None
    maximum: float | None = None
    strictly_positive: bool = False


def _spec(
    key: str,
    unit: str,
    minimum: float | None = None,
    maximum: float | None = None,
    *,
    strictly_positive: bool = False,
) -> DriverSpec:
    return DriverSpec(key, unit, minimum, maximum, strictly_positive)


_DRIVER_SPEC_ROWS = (
    _spec("revenue_growth", "percent", -1.0, 5.0),
    _spec("gross_margin", "percent", -1.0, 1.0),
    _spec("sga_percent_revenue", "percent", 0.0, 2.0),
    _spec("rd_percent_revenue", "percent", 0.0, 2.0),
    _spec("other_opex_percent_revenue", "percent", 0.0, 2.0),
    _spec("da_percent_revenue", "percent", 0.0, 2.0),
    _spec("intangible_amortization_percent_revenue", "percent", 0.0, 2.0),
    _spec("stock_comp_percent_revenue", "percent", 0.0, 2.0),
    _spec("effective_tax_rate", "percent", -1.0, 1.0),
    _spec("cash_tax_rate", "percent", 0.0, 1.0),
    _spec("nopat_tax_rate", "percent", 0.0, 1.0),
    _spec("dso", "days", 0.0, 730.0),
    _spec("dio", "days", 0.0, 730.0),
    _spec("dpo", "days", 0.0, 730.0),
    _spec("deferred_revenue_percent_revenue", "percent", 0.0, 5.0),
    _spec("capex_percent_revenue", "percent", 0.0, 5.0),
    _spec("minimum_cash", "currency", 0.0),
    _spec("scheduled_debt_issuance", "currency", 0.0),
    _spec("scheduled_debt_repayment", "currency", 0.0),
    _spec("cost_of_debt", "percent", 0.0, 1.0),
    _spec("cash_yield", "percent", -0.25, 1.0),
    _spec("dividend_payout", "percent", 0.0, 2.0),
    _spec("buyback_amount", "currency", 0.0),
    _spec("common_stock_issuance", "currency", 0.0),
    _spec("average_share_price", "currency_per_share", 0.0, strictly_positive=True),
    _spec("incremental_diluted_shares", "count", 0.0),
    _spec("net_investment_purchases", "currency"),
    _spec("acquisition_spend", "currency", 0.0),
    _spec("asset_sale_proceeds", "currency", 0.0),
    _spec("asset_cost_disposals", "currency", 0.0),
    _spec("asset_disposal_accumulated_depreciation", "currency", 0.0),
    _spec("other_nonoperating_percent_revenue", "percent", -2.0, 2.0),
    _spec("prepaids_percent_revenue", "percent", 0.0, 5.0),
    _spec("other_current_assets_percent_revenue", "percent", 0.0, 5.0),
    _spec("accrued_expenses_percent_revenue", "percent", 0.0, 5.0),
    _spec("other_current_liabilities_percent_revenue", "percent", 0.0, 5.0),
    _spec("deferred_tax_assets_percent_revenue", "percent", 0.0, 5.0),
    _spec("deferred_tax_liabilities_percent_revenue", "percent", 0.0, 5.0),
    _spec("preferred_dividends", "currency", 0.0),
    _spec("minority_earnings_percent", "percent", 0.0, 1.0),
    _spec("other_operating_cash_flow", "currency"),
    _spec("other_investing_cash_flow", "currency"),
    _spec("other_financing_cash_flow", "currency"),
    _spec("fx_cash_adjustment", "currency"),
    _spec("misc_cash_adjustment", "currency"),
)
DRIVER_SPECS: Mapping[str, DriverSpec] = MappingProxyType(
    {row.key: row for row in _DRIVER_SPEC_ROWS}
)
_DIAGNOSTIC_COUNTERPART_POLICIES: Mapping[str, str] = MappingProxyType(
    {
        "acquisition_spend": "acquisition cash spend is provisionally classified as goodwill; an approved purchase-price allocation remains required",
        "other_operating_cash_flow": "other operating cash flow is provisionally matched to other non-current liabilities",
        "other_investing_cash_flow": "other investing cash flow is provisionally matched to other long-term assets",
        "other_financing_cash_flow": "other financing cash flow is provisionally matched to common stock and APIC",
        "misc_cash_adjustment": "miscellaneous cash adjustment is provisionally matched to AOCI",
    }
)
_FINANCE_SEMANTIC_POLICY_DRIVERS = frozenset(
    {
        "capex_percent_revenue",
        "minimum_cash",
        "scheduled_debt_issuance",
        "scheduled_debt_repayment",
        "dividend_payout",
        "buyback_amount",
        "common_stock_issuance",
        "net_investment_purchases",
        "acquisition_spend",
        "asset_sale_proceeds",
        "asset_cost_disposals",
        "asset_disposal_accumulated_depreciation",
        "preferred_dividends",
        "intangible_amortization_percent_revenue",
        "incremental_diluted_shares",
        "nopat_tax_rate",
    }
)




@dataclass(frozen=True)
class DriverPath:
    key: str
    values: tuple[float, ...]
    unit: str
    source_ref: str
    method: str
    approval_ref: str | None = None
    queue_item_id: str | None = None
    driver_group: DriverGroup = DriverGroup.FINANCE_SEMANTIC
    current_driver_fingerprint: str | None = None
    approved_driver_fingerprint: str | None = None

    @staticmethod
    def fingerprint_for(
        *,
        key: str,
        values: Sequence[float],
        unit: str,
        source_ref: str,
        method: str,
    ) -> str:
        normalized_values = tuple(float(value) for value in values)
        payload = {
            "key": str(key).strip(),
            "values": normalized_values,
            "unit": str(unit).strip(),
            "source_ref": str(source_ref).strip(),
            "method": str(method).strip(),
        }
        encoded = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


    def __post_init__(self) -> None:
        key = str(self.key).strip()
        if "probability" in key.lower():
            raise InvalidScenarioPolicyError("scenario probability inputs are prohibited")
        if key not in DRIVER_SPECS:
            raise IncompleteScenarioDriversError(f"unknown scenario driver: {key}")
        if len(self.values) != FORECAST_YEARS:
            raise ValueError("scenario driver paths must contain exactly five annual values")
        spec = DRIVER_SPECS[key]
        if self.unit != spec.unit:
            raise ValueError(f"driver {key} unit must be {spec.unit}")
        normalized: list[float] = []
        for raw in self.values:
            if isinstance(raw, bool) or not isinstance(raw, (int, float)):
                raise TypeError(f"driver {key} values must be numeric")
            value = float(raw)
            if not math.isfinite(value):
                raise ValueError(f"driver {key} values must be finite")
            if spec.minimum is not None and value < spec.minimum:
                raise ValueError(f"driver {key} is below its accepted range")
            if spec.maximum is not None and value > spec.maximum:
                raise ValueError(f"driver {key} is above its accepted range")
            if spec.strictly_positive and value <= 0.0:
                raise ValueError(f"driver {key} must be positive")
            normalized.append(value)
        source_ref = str(self.source_ref).strip()
        method = str(self.method).strip()
        if not source_ref or not method:
            raise ValueError(f"driver {key} requires source_ref and method provenance")
        try:
            driver_group = (
                self.driver_group
                if isinstance(self.driver_group, DriverGroup)
                else DriverGroup(str(self.driver_group))
            )
        except ValueError as exc:
            raise ValueError(f"driver {key} has an invalid driver_group") from exc
        if key in _FINANCE_SEMANTIC_POLICY_DRIVERS and driver_group is not DriverGroup.FINANCE_SEMANTIC:
            raise InvalidScenarioPolicyError(
                f"driver {key} is a finance-semantic policy and cannot be mechanical"
            )
        fingerprint = self.fingerprint_for(
            key=key,
            values=normalized,
            unit=self.unit,
            source_ref=source_ref,
            method=method,
        )
        current = (
            str(self.current_driver_fingerprint).strip().lower()
            if self.current_driver_fingerprint is not None
            else fingerprint
        )
        if not re.fullmatch(r"[0-9a-f]{64}", current) or current != fingerprint:
            raise InvalidScenarioPolicyError(
                f"driver {key} current fingerprint does not match its inputs"
            )
        approved_fingerprint = (
            str(self.approved_driver_fingerprint).strip().lower()
            if self.approved_driver_fingerprint is not None
            else None
        )
        if approved_fingerprint is not None and not re.fullmatch(
            r"[0-9a-f]{64}",
            approved_fingerprint,
        ):
            raise InvalidScenarioPolicyError(
                f"driver {key} approved fingerprint is invalid"
            )
        if self.approval_ref and approved_fingerprint != current:
            raise InvalidScenarioPolicyError(
                f"driver {key} approval fingerprint is missing or stale"
            )
        if not self.approval_ref and not self.queue_item_id:
            raise ValueError(
                f"unapproved driver {key} requires a PM/evidence queue item ID"
            )
        object.__setattr__(self, "key", key)
        object.__setattr__(self, "values", tuple(normalized))
        object.__setattr__(self, "source_ref", source_ref)
        object.__setattr__(self, "method", method)
        object.__setattr__(self, "driver_group", driver_group)
        object.__setattr__(self, "current_driver_fingerprint", current)
        object.__setattr__(self, "approved_driver_fingerprint", approved_fingerprint)

    @property
    def approved(self) -> bool:
        return bool(
            self.approval_ref
            and self.current_driver_fingerprint
            and self.approved_driver_fingerprint == self.current_driver_fingerprint
        )


@dataclass(frozen=True)
class ScenarioDriverSet:
    scenario_key: str
    paths: tuple[DriverPath, ...]
    parent_scenario_key: str | None = None

    def __post_init__(self) -> None:
        scenario_key = str(self.scenario_key).strip()
        if not scenario_key or "probability" in scenario_key.lower():
            raise InvalidScenarioPolicyError("scenario identity cannot be blank/probability based")
        keys = [path.key for path in self.paths]
        if len(set(keys)) != len(keys):
            raise IncompleteScenarioDriversError("scenario contains duplicate driver paths")
        expected = set(DRIVER_SPECS)
        supplied = set(keys)
        if supplied != expected:
            missing = sorted(expected - supplied)
            extra = sorted(supplied - expected)
            raise IncompleteScenarioDriversError(
                f"scenario drivers incomplete; missing={missing}, extra={extra}"
            )
        object.__setattr__(self, "scenario_key", scenario_key)
        object.__setattr__(self, "paths", tuple(sorted(self.paths, key=lambda item: item.key)))

    @property
    def path_map(self) -> Mapping[str, DriverPath]:
        return MappingProxyType({path.key: path for path in self.paths})

    @property
    def unapproved_paths(self) -> tuple[DriverPath, ...]:
        return tuple(path for path in self.paths if not path.approved)

    def value(self, key: str, year: int) -> float:
        if year < 1 or year > FORECAST_YEARS:
            raise IndexError("forecast year is one-based and must be in [1, 5]")
        return self.path_map[key].values[year - 1]


@dataclass(frozen=True)
class CircularityPolicy:
    policy_id: str = CIRCULARITY_POLICY_ID
    uses_excel_iteration: bool = False
    description: str = (
        "Interest expense uses average beginning and scheduled ending borrowings; "
        "interest income uses average cash plus short- and long-term investments on a pre-funding basis; "
        "minimum-cash liquidity draws accrue interest beginning next year; "
        "excess cash is retained and never swept to debt."
    )


@dataclass(frozen=True)
class DebtConvention:
    convention_id: str = DEBT_CONVENTION_ID
    borrowing_definition: str = (
        "short-term borrowings + current portion of long-term debt + long-term debt"
    )
    reported_total_debt_definition: str = (
        "borrowings + current lease liabilities + long-term lease liabilities"
    )
    interest_base: str = "average beginning and scheduled ending borrowings; leases excluded"


@dataclass(frozen=True)
class ForecastScenarioResult:
    scenario_key: str
    model: ModelResult
    liquidity_draws: tuple[float, ...]
    circularity_policy: CircularityPolicy
    debt_convention: DebtConvention
    registry_keys: tuple[str, ...]

    @property
    def line_index(self) -> Mapping[str, LineSeries]:
        lines: dict[str, LineSeries] = {}
        for container in (*self.model.statements, *self.model.supporting_schedules):
            lines.update({line.line_key: line for line in container.lines})
        return MappingProxyType(lines)

    def value(self, line_key: str, year: int) -> PeriodValue:
        if year < 1 or year > FORECAST_YEARS:
            raise IndexError("forecast year is one-based and must be in [1, 5]")
        return self.line_index[line_key].values[year - 1]

    def numeric(self, line_key: str, year: int) -> float:
        period_value = self.value(line_key, year)
        if period_value.state.status is not AvailabilityStatus.AVAILABLE:
            raise UnavailableForecastValueError(
                f"{line_key} year {year} is {period_value.state.status.value}: "
                f"{period_value.state.reason_code}"
            )
        return float(period_value.value)


@dataclass(frozen=True)
class ForecastScenarioBundle:
    scenarios: tuple[ForecastScenarioResult, ...]
    registry_keys: tuple[str, ...]
    input_hash: str

    def scenario(self, scenario_key: str) -> ForecastScenarioResult:
        for item in self.scenarios:
            if item.scenario_key == scenario_key:
                return item
        raise KeyError(scenario_key)

    def line_delta(self, line_key: str, scenario_key: str, year: int) -> float:
        return self.scenario(scenario_key).numeric(line_key, year) - self.scenario(
            "Base"
        ).numeric(line_key, year)


_HISTORICAL_SEED_KEYS = (
    "is.revenue",
    "bs.cash", "bs.short_term_investments", "bs.accounts_receivable",
    "bs.other_receivables", "bs.inventory", "bs.prepaids",
    "bs.other_current_assets", "bs.gross_ppe", "bs.accumulated_depreciation",
    "bs.long_term_investments", "bs.goodwill", "bs.gross_intangibles",
    "bs.accumulated_amortization", "bs.other_intangibles",
    "bs.deferred_tax_assets", "bs.other_long_term_assets",
    "bs.accounts_payable", "bs.accrued_expenses", "bs.short_term_borrowings",
    "bs.current_long_term_debt", "bs.current_lease_liabilities",
    "bs.income_taxes_payable", "bs.deferred_revenue_current",
    "bs.other_current_liabilities", "bs.long_term_debt", "bs.long_term_leases",
    "bs.deferred_revenue_noncurrent", "bs.pension_liability",
    "bs.deferred_tax_liability", "bs.other_noncurrent_liabilities",
    "bs.common_stock_apic", "bs.retained_earnings", "bs.treasury_stock",
    "bs.aoci", "bs.minority_interest", "bs.total_debt",
    "shares.basic_weighted_average", "shares.diluted_weighted_average",
    "shares.period_end",
)
_OPTIONAL_HISTORICAL_SEED_DEFAULTS: Mapping[str, float] = MappingProxyType(
    {"bs.long_term_receivables": 0.0}
)

_SHARE_EVIDENCE_KEYS = (
    "shares.dividend_per_share",
    "shares.options_incremental",
    "shares.rsu_incremental",
    "shares.psu_incremental",
    "shares.convertible_incremental",
    "shares.fully_diluted",
)


def _available() -> AvailabilityState:
    return AvailabilityState(status=AvailabilityStatus.AVAILABLE)


def _typed_state(
    status: AvailabilityStatus,
    reason_code: str,
    message: str,
    *,
    queue_item_id: str | None = None,
) -> AvailabilityState:
    return AvailabilityState(
        status=status,
        reason_code=reason_code,
        message=message,
        queue_item_id=queue_item_id,
    )


def _numeric_value(raw: Any, key: str) -> float | None:
    if raw is None:
        return None
    state = getattr(raw, "state", None)
    if state is not None and getattr(state, "status", None) is not AvailabilityStatus.AVAILABLE:
        return None
    value = getattr(raw, "value", raw)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"historical seed {key} must be numeric")
    normalized = float(value)
    if not math.isfinite(normalized):
        raise ValueError(f"historical seed {key} must be finite")
    return normalized


def _historical_fiscal_seed(
    historical: Any,
) -> tuple[str, date | None]:
    result = getattr(historical, "result", None)
    axis = getattr(result, "period_axis", None)
    periods = tuple(getattr(axis, "periods", ()))
    fiscal_periods = tuple(
        period
        for period in periods
        if getattr(period, "period_type", None) is PeriodType.FISCAL_YEAR
    )
    if fiscal_periods:
        selected = fiscal_periods[-1]
        return str(selected.key), selected.end_date

    period_keys = tuple(getattr(historical, "period_keys", ()))
    fiscal_keys = tuple(
        str(key)
        for key in period_keys
        if re.fullmatch(r"FY\d{2,4}", str(key).strip().upper())
    )
    if not fiscal_keys:
        raise IncompleteHistoricalSeedError(
            "historical result adapter requires at least one fiscal-year actual; "
            "LTM/estimate periods cannot seed an annual forecast"
        )
    return fiscal_keys[-1], None


def _reject_post_fiscal_reference_periods(
    historical: Any,
    fiscal_seed_end: date | None,
) -> None:
    if fiscal_seed_end is None:
        return
    result = getattr(historical, "result", None)
    axis = getattr(result, "period_axis", None)
    periods = tuple(getattr(axis, "periods", ()))
    later_nonannual = tuple(
        period
        for period in periods
        if getattr(period, "period_type", None) is not PeriodType.FISCAL_YEAR
        and getattr(period, "end_date", fiscal_seed_end) > fiscal_seed_end
    )
    if later_nonannual:
        raise IncompleteHistoricalSeedError(
            "post-fiscal LTM/TTM periods cannot be annualized inside the forecast engine; "
            "an explicit YTD plus Q4 stub with exact dates and source references is required"
        )


def _coerce_historical_seed(historical: Any) -> dict[str, float]:
    values: dict[str, float] = {}
    missing: list[str] = []
    period_key: str | None = None
    if isinstance(historical, Mapping):
        for key in _HISTORICAL_SEED_KEYS:
            value = _numeric_value(historical.get(key), key)
            if value is None:
                missing.append(key)
            else:
                values[key] = value
    elif callable(getattr(historical, "value", None)):
        period_key, _ = _historical_fiscal_seed(historical)
        for key in _HISTORICAL_SEED_KEYS:
            try:
                raw = historical.value(key, period_key)
            except (KeyError, LookupError):
                raw = None
            value = _numeric_value(raw, key)
            if value is None:
                missing.append(key)
            else:
                values[key] = value
    else:
        raise TypeError(
            "historical must be a canonical-key mapping or expose "
            "period_keys and value(key, period_key)"
        )
    if missing:
        raise IncompleteHistoricalSeedError(
            "normalized historical seed is incomplete; missing=" + ", ".join(sorted(missing))
        )
    for key, default in _OPTIONAL_HISTORICAL_SEED_DEFAULTS.items():
        raw = historical.get(key) if isinstance(historical, Mapping) else None
        if not isinstance(historical, Mapping):
            try:
                raw = historical.value(key, period_key)
            except (KeyError, LookupError):
                raw = None
        value = _numeric_value(raw, key)
        values[key] = default if value is None else value
    _validate_historical_seed(values)
    return values


def _validate_historical_seed(seed: Mapping[str, float]) -> None:
    if seed["is.revenue"] < 0.0:
        raise IncompleteHistoricalSeedError("is.revenue cannot be negative")
    if seed["bs.accumulated_depreciation"] > 0.0:
        raise IncompleteHistoricalSeedError(
            "bs.accumulated_depreciation must use the normalized negative sign"
        )
    if seed["bs.treasury_stock"] > 0.0:
        raise IncompleteHistoricalSeedError(
            "bs.treasury_stock must use the normalized negative sign"
        )
    if seed["bs.accumulated_amortization"] > 0.0:
        raise IncompleteHistoricalSeedError(
            "bs.accumulated_amortization must use the normalized negative sign"
        )
    if min(seed["bs.gross_intangibles"], seed["bs.other_intangibles"]) < 0.0:
        raise IncompleteHistoricalSeedError(
            "gross and net intangible assets cannot be negative"
        )
    if abs(
        seed["bs.gross_intangibles"]
        + seed["bs.accumulated_amortization"]
        - seed["bs.other_intangibles"]
    ) > BALANCE_TOLERANCE:
        raise IncompleteHistoricalSeedError(
            "net intangibles must tie to gross intangibles plus accumulated amortization"
        )
    if min(
        seed["shares.basic_weighted_average"],
        seed["shares.diluted_weighted_average"],
        seed["shares.period_end"],
    ) <= 0.0:
        raise IncompleteHistoricalSeedError("historical share counts must be positive")
    borrowings = (
        seed["bs.short_term_borrowings"]
        + seed["bs.current_long_term_debt"]
        + seed["bs.long_term_debt"]
    )
    lease_liabilities = (
        seed["bs.current_lease_liabilities"] + seed["bs.long_term_leases"]
    )
    if abs(borrowings + lease_liabilities - seed["bs.total_debt"]) > BALANCE_TOLERANCE:
        raise IncompleteHistoricalSeedError(
            "reported bs.total_debt must tie to borrowings plus lease liabilities"
        )
    assets = (
        seed["bs.cash"] + seed["bs.short_term_investments"]
        + seed["bs.accounts_receivable"] + seed["bs.other_receivables"]
        + seed["bs.inventory"] + seed["bs.prepaids"]
        + seed["bs.other_current_assets"] + seed["bs.gross_ppe"]
        + seed["bs.accumulated_depreciation"] + seed["bs.long_term_investments"]
        + seed["bs.goodwill"] + seed["bs.other_intangibles"]
        + seed["bs.long_term_receivables"]
        + seed["bs.deferred_tax_assets"] + seed["bs.other_long_term_assets"]
    )
    liabilities = (
        seed["bs.accounts_payable"] + seed["bs.accrued_expenses"]
        + seed["bs.short_term_borrowings"] + seed["bs.current_long_term_debt"]
        + seed["bs.current_lease_liabilities"] + seed["bs.income_taxes_payable"]
        + seed["bs.deferred_revenue_current"] + seed["bs.other_current_liabilities"]
        + seed["bs.long_term_debt"] + seed["bs.long_term_leases"]
        + seed["bs.deferred_revenue_noncurrent"] + seed["bs.pension_liability"]
        + seed["bs.deferred_tax_liability"] + seed["bs.other_noncurrent_liabilities"]
    )
    equity = (
        seed["bs.common_stock_apic"] + seed["bs.retained_earnings"]
        + seed["bs.treasury_stock"] + seed["bs.aoci"]
        + seed["bs.minority_interest"]
    )
    if abs(assets - liabilities - equity) > BALANCE_TOLERANCE:
        raise IncompleteHistoricalSeedError(
            "normalized historical balance sheet does not balance within 0.1"
        )


def _forecast_axis(last_period_end: date) -> PeriodAxis:
    if not isinstance(last_period_end, date):
        raise TypeError("last_historical_period_end must be a date")
    periods: list[ModelPeriod] = []
    for index in range(1, FORECAST_YEARS + 1):
        year = last_period_end.year + index
        try:
            end_date = date(year, last_period_end.month, last_period_end.day)
        except ValueError:
            end_date = date(year, last_period_end.month, 28)
        periods.append(
            ModelPeriod(
                index=index,
                key=f"FY{year % 100:02d}E",
                end_date=end_date,
                period_type=PeriodType.FISCAL_YEAR,
            )
        )
    return PeriodAxis(periods=tuple(periods))


class _LineStore:
    def __init__(self, registry: Sequence[LineItemSpec], axis: PeriodAxis) -> None:
        self.registry = tuple(registry)
        self.axis = axis
        self.values: dict[str, list[PeriodValue | None]] = {
            spec.canonical_key: [None] * FORECAST_YEARS for spec in registry
        }
        self.methods: dict[str, str] = {
            spec.canonical_key: "typed_forecast_gap" for spec in registry
        }

    def set(
        self,
        key: str,
        year: int,
        value: float,
        method_id: str,
        source_refs: Sequence[str] = (),
    ) -> None:
        if not math.isfinite(float(value)):
            raise ForecastCalculationError(f"non-finite calculated value for {key}")
        prior_method = self.methods[key]
        if prior_method != "typed_forecast_gap" and prior_method != method_id:
            raise ForecastCalculationError(f"line {key} changed forecast method within the axis")
        self.methods[key] = method_id
        self.values[key][year - 1] = PeriodValue(
            period_key=self.axis.periods[year - 1].key,
            value=float(value),
            state=_available(),
            formula_id=method_id,
            source_refs=tuple(source_refs),
        )

    def series(self) -> dict[str, LineSeries]:
        output: dict[str, LineSeries] = {}
        for spec in self.registry:
            items = self.values[spec.canonical_key]
            if any(item is None for item in items):
                if spec.statement_or_schedule == "segment_build":
                    state = _typed_state(
                        AvailabilityStatus.PM_REQUIRED,
                        "segment_source_or_approval_required",
                        "Segment/KPI history and an approved driver build are required; consolidated values are not silently allocated.",
                    )
                    method = "typed_segment_gap"
                elif spec.statement_or_schedule == "consensus_bridge":
                    state = _typed_state(
                        AvailabilityStatus.UNAVAILABLE,
                        "consensus_snapshot_not_supplied",
                        "Consensus is reference evidence and was not supplied to this forecast run.",
                    )
                    method = "typed_consensus_gap"
                else:
                    status = spec.missing_data_policy
                    state = _typed_state(
                        status,
                        "forecast_method_not_resolved",
                        f"No deterministic forecast value was resolved for {spec.canonical_key}.",
                    )
                    method = "typed_forecast_gap"
                completed = tuple(
                    item if item is not None else PeriodValue(
                        period_key=self.axis.periods[index].key,
                        value=None,
                        state=state,
                        formula_id=method,
                    )
                    for index, item in enumerate(items)
                )
            else:
                completed = tuple(item for item in items if item is not None)
                method = self.methods[spec.canonical_key]
            output[spec.canonical_key] = LineSeries(
                line_key=spec.canonical_key,
                method_id=method,
                values=completed,
            )
        return output


def _set_many(
    store: _LineStore,
    year: int,
    values: Mapping[str, float],
    method_id: str,
    refs: Sequence[str] = (),
) -> None:
    for key, value in values.items():
        store.set(key, year, value, method_id, refs)


def _hash_payload(payload: Any) -> str:
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()

def _calculate_period(
    previous: Mapping[str, float],
    scenario: ScenarioDriverSet,
    year: int,
) -> tuple[dict[str, float], float, dict[str, float]]:
    driver = lambda key: scenario.value(key, year)
    revenue = previous["is.revenue"] * (1.0 + driver("revenue_growth"))
    cost_of_revenue = -revenue * (1.0 - driver("gross_margin"))
    gross_profit = revenue + cost_of_revenue
    sga = -revenue * driver("sga_percent_revenue")
    research_development = -revenue * driver("rd_percent_revenue")
    other_opex = -revenue * driver("other_opex_percent_revenue")
    operating_income = gross_profit + sga + research_development + other_opex
    da = revenue * driver("da_percent_revenue")
    intangible_amortization = (
        revenue * driver("intangible_amortization_percent_revenue")
    )
    if intangible_amortization > da + BALANCE_TOLERANCE:
        raise ForecastCalculationError("intangible amortization exceeds total D&A")
    depreciation = max(0.0, da - intangible_amortization)
    stock_compensation = revenue * driver("stock_comp_percent_revenue")

    scheduled_issuance = driver("scheduled_debt_issuance")
    scheduled_repayment = driver("scheduled_debt_repayment")
    beginning_borrowings = (
        previous["bs.short_term_borrowings"]
        + previous["bs.current_long_term_debt"]
        + previous["bs.long_term_debt"]
    )
    scheduled_borrowings = beginning_borrowings + scheduled_issuance - scheduled_repayment
    if scheduled_borrowings < -BALANCE_TOLERANCE:
        raise ForecastCalculationError("scheduled debt repayment exceeds available borrowings")
    scheduled_borrowings = max(0.0, scheduled_borrowings)
    # Leases stay a separate reported claim; cost of debt applies to borrowings.
    interest_expense = -(
        (beginning_borrowings + scheduled_borrowings) / 2.0
        * driver("cost_of_debt")
    )

    receivables = revenue * driver("dso") / 365.0
    inventory = abs(cost_of_revenue) * driver("dio") / 365.0
    payables = abs(cost_of_revenue) * driver("dpo") / 365.0
    other_receivables = previous["bs.other_receivables"]
    prepaids = revenue * driver("prepaids_percent_revenue")
    other_current_assets = revenue * driver("other_current_assets_percent_revenue")
    accrued_expenses = revenue * driver("accrued_expenses_percent_revenue")
    other_current_liabilities = revenue * driver(
        "other_current_liabilities_percent_revenue"
    )
    deferred_revenue = revenue * driver("deferred_revenue_percent_revenue")
    prior_deferred_revenue = (
        previous["bs.deferred_revenue_current"]
        + previous["bs.deferred_revenue_noncurrent"]
    )
    current_deferred_share = (
        previous["bs.deferred_revenue_current"] / prior_deferred_revenue
        if prior_deferred_revenue > 0.0
        else 1.0
    )
    deferred_revenue_current = deferred_revenue * current_deferred_share
    deferred_revenue_noncurrent = deferred_revenue - deferred_revenue_current

    capex_addition = revenue * driver("capex_percent_revenue")
    sale_proceeds = driver("asset_sale_proceeds")
    asset_cost_disposals = driver("asset_cost_disposals")
    disposal_accumulated_depreciation = driver(
        "asset_disposal_accumulated_depreciation"
    )
    if sale_proceeds > 0.0 and asset_cost_disposals <= 0.0:
        raise ForecastCalculationError(
            "asset sale proceeds require a distinct asset-cost disposal path"
        )
    if disposal_accumulated_depreciation > asset_cost_disposals + BALANCE_TOLERANCE:
        raise ForecastCalculationError(
            "disposed accumulated depreciation exceeds disposed asset cost"
        )
    if asset_cost_disposals > previous["bs.gross_ppe"] + capex_addition + BALANCE_TOLERANCE:
        raise ForecastCalculationError("asset-cost disposals exceed available gross PP&E")
    if disposal_accumulated_depreciation > abs(
        previous["bs.accumulated_depreciation"]
    ) + depreciation + BALANCE_TOLERANCE:
        raise ForecastCalculationError(
            "disposed accumulated depreciation exceeds the available contra-asset balance"
        )
    gross_ppe = (
        previous["bs.gross_ppe"] + capex_addition - asset_cost_disposals
    )
    if gross_ppe < -BALANCE_TOLERANCE:
        raise ForecastCalculationError("asset-cost disposals exceed gross PP&E")
    accumulated_depreciation = (
        previous["bs.accumulated_depreciation"]
        - depreciation
        + disposal_accumulated_depreciation
    )
    net_ppe = gross_ppe + accumulated_depreciation
    disposal_net_book_value = (
        asset_cost_disposals - disposal_accumulated_depreciation
    )
    gain_on_sale_assets = sale_proceeds - disposal_net_book_value
    short_term_investments = (
        previous["bs.short_term_investments"] + driver("net_investment_purchases")
    )
    if min(short_term_investments, gross_ppe, net_ppe) < -BALANCE_TOLERANCE:
        raise ForecastCalculationError(
            "scenario creates negative investments, gross PP&E, or net PP&E"
        )
    acquisition_spend = driver("acquisition_spend")
    goodwill = previous["bs.goodwill"] + acquisition_spend
    gross_intangibles = previous["bs.gross_intangibles"]
    accumulated_amortization = (
        previous["bs.accumulated_amortization"] - intangible_amortization
    )
    other_intangibles = gross_intangibles + accumulated_amortization
    if other_intangibles < -BALANCE_TOLERANCE:
        raise ForecastCalculationError(
            "intangible amortization exceeds the remaining net intangible balance"
        )
    other_intangibles = max(0.0, other_intangibles)
    long_term_receivables = previous["bs.long_term_receivables"]
    deferred_tax_assets = revenue * driver("deferred_tax_assets_percent_revenue")
    deferred_tax_liability = revenue * driver(
        "deferred_tax_liabilities_percent_revenue"
    )
    other_investing_cash_flow = driver("other_investing_cash_flow")
    other_long_term_assets = (
        previous["bs.other_long_term_assets"] - other_investing_cash_flow
    )
    if other_long_term_assets < -BALANCE_TOLERANCE:
        raise ForecastCalculationError(
            "other investing cash inflow exceeds other long-term assets"
        )

    debt_denominator = beginning_borrowings
    if debt_denominator > 0.0:
        short_share = previous["bs.short_term_borrowings"] / debt_denominator
        current_share = previous["bs.current_long_term_debt"] / debt_denominator
        long_share = previous["bs.long_term_debt"] / debt_denominator
    else:
        short_share, current_share, long_share = 0.0, 0.0, 1.0
    # Guard tiny historical rounding drift without creating a hidden debt plug.
    share_total = short_share + current_share + long_share
    short_share, current_share, long_share = (
        short_share / share_total,
        current_share / share_total,
        long_share / share_total,
    )

    def income_statement(interest_income: float) -> dict[str, float]:
        other_nonoperating = (
            revenue * driver("other_nonoperating_percent_revenue")
            + gain_on_sale_assets
        )
        ebt = operating_income + interest_expense + interest_income + other_nonoperating
        income_tax = -ebt * driver("effective_tax_rate")
        net_income_company = ebt + income_tax
        minority_earnings = -net_income_company * driver("minority_earnings_percent")
        net_income_parent = net_income_company + minority_earnings
        preferred_dividends = -driver("preferred_dividends")
        net_income_common = net_income_parent + preferred_dividends
        return {
            "is.revenue": revenue,
            "is.cost_of_revenue": cost_of_revenue,
            "is.gross_profit": gross_profit,
            "is.sga": sga,
            "is.research_development": research_development,
            "is.other_operating_expense": other_opex,
            "is.operating_expenses_total": sga + research_development + other_opex,
            "is.operating_income": operating_income,
            "is.interest_expense": interest_expense,
            "is.interest_income": interest_income,
            "is.net_interest_expense": interest_expense + interest_income,
            "is.affiliates_income": 0.0,
            "is.fx_gain_loss": 0.0,
            "is.other_nonoperating": other_nonoperating,
            "is.ebt_ex_unusual": ebt,
            "is.unusual_items": 0.0,
            "is.ebt": ebt,
            "is.income_tax": income_tax,
            "is.net_income_company": net_income_company,
            "is.minority_earnings": minority_earnings,
            "is.net_income_parent": net_income_parent,
            "is.preferred_dividends": preferred_dividends,
            "is.net_income_common": net_income_common,
            "is.ebitda": operating_income + da,
            "is.ebit": operating_income,
            "is.stock_based_compensation": -stock_compensation,
            "is.da_for_ebitda": da,
        }

    def integrated_cash_and_balance(
        income: Mapping[str, float],
        liquidity_draw: float,
    ) -> tuple[dict[str, float], dict[str, float]]:
        book_tax = -income["is.income_tax"]
        cash_taxes = -max(income["is.ebt"], 0.0) * driver("cash_tax_rate")
        change_deferred_tax_assets = deferred_tax_assets - previous["bs.deferred_tax_assets"]
        change_deferred_tax_liabilities = deferred_tax_liability - previous["bs.deferred_tax_liability"]
        change_deferred_taxes = change_deferred_tax_liabilities - change_deferred_tax_assets
        current_tax_expense = book_tax - change_deferred_taxes
        income_taxes_payable = (
            previous["bs.income_taxes_payable"] + current_tax_expense + cash_taxes
        )
        if income_taxes_payable < -BALANCE_TOLERANCE:
            raise ForecastCalculationError(
                "cash tax path overdraws the income-taxes-payable balance"
            )
        change_income_taxes = (
            income_taxes_payable - previous["bs.income_taxes_payable"]
        )
        change_other_operating_assets = (
            -(prepaids - previous["bs.prepaids"])
            -(other_current_assets - previous["bs.other_current_assets"])
            +(accrued_expenses - previous["bs.accrued_expenses"])
            +(other_current_liabilities - previous["bs.other_current_liabilities"])
        )
        change_receivables = -(receivables - previous["bs.accounts_receivable"])
        change_inventory = -(inventory - previous["bs.inventory"])
        change_payables = payables - previous["bs.accounts_payable"]
        change_deferred_revenue = deferred_revenue - prior_deferred_revenue
        other_operating_cash_flow = driver("other_operating_cash_flow")
        cfo = (
            income["is.net_income_company"] + da - gain_on_sale_assets
            + stock_compensation
            + change_receivables + change_inventory + change_payables
            + change_deferred_revenue + change_income_taxes
            + change_deferred_taxes + change_other_operating_assets
            + other_operating_cash_flow
        )
        capex = -capex_addition
        acquisitions = -acquisition_spend
        investments = -driver("net_investment_purchases")
        cfi = (
            capex + sale_proceeds + acquisitions + investments
            + other_investing_cash_flow
        )
        common_dividend = -max(income["is.net_income_common"], 0.0) * driver(
            "dividend_payout"
        )
        dividends_paid = common_dividend - driver("preferred_dividends")
        buybacks = -driver("buyback_amount")
        common_stock_issued = driver("common_stock_issuance")
        debt_issued = scheduled_issuance + liquidity_draw
        debt_repaid = -scheduled_repayment
        other_financing_cash_flow = driver("other_financing_cash_flow")
        cff = (
            debt_issued + debt_repaid + common_stock_issued + buybacks
            + dividends_paid + other_financing_cash_flow
        )
        fx_adjustment = driver("fx_cash_adjustment")
        misc_adjustment = driver("misc_cash_adjustment")
        net_change_cash = cfo + cfi + cff + fx_adjustment + misc_adjustment
        ending_cash = previous["bs.cash"] + net_change_cash

        total_borrowings = scheduled_borrowings + liquidity_draw
        short_term_borrowings = scheduled_borrowings * short_share + liquidity_draw
        current_long_term_debt = scheduled_borrowings * current_share
        long_term_debt = scheduled_borrowings * long_share
        lease_liabilities = (
            previous["bs.current_lease_liabilities"]
            + previous["bs.long_term_leases"]
        )
        reported_total_debt = total_borrowings + lease_liabilities
        other_noncurrent_liabilities = (
            previous["bs.other_noncurrent_liabilities"]
            + other_operating_cash_flow
        )
        common_stock_apic = (
            previous["bs.common_stock_apic"] + stock_compensation
            + common_stock_issued + other_financing_cash_flow
        )
        retained_earnings = (
            previous["bs.retained_earnings"]
            + income["is.net_income_parent"] + dividends_paid
        )
        treasury_stock = previous["bs.treasury_stock"] + buybacks
        aoci = previous["bs.aoci"] + fx_adjustment + misc_adjustment
        minority_interest = (
            previous["bs.minority_interest"] - income["is.minority_earnings"]
        )
        average_share_price = driver("average_share_price")
        issued_shares = common_stock_issued / average_share_price
        repurchased_shares = driver("buyback_amount") / average_share_price
        period_end_shares = (
            previous["shares.period_end"]
            + issued_shares
            - repurchased_shares
        )
        if period_end_shares <= 0.0:
            raise ForecastCalculationError("share issuance/buyback path exhausts shares")
        basic_shares = (previous["shares.period_end"] + period_end_shares) / 2.0
        incremental_diluted_shares = driver("incremental_diluted_shares")
        diluted_shares = basic_shares + incremental_diluted_shares
        cash_dividend_per_share = abs(common_dividend) / basic_shares

        total_receivables = receivables + other_receivables
        cash_and_investments = ending_cash + short_term_investments
        total_current_assets = (
            ending_cash + short_term_investments + total_receivables
            + inventory + prepaids + other_current_assets
        )
        total_assets = (
            total_current_assets + net_ppe + previous["bs.long_term_investments"]
            + goodwill + other_intangibles + long_term_receivables + deferred_tax_assets
            + other_long_term_assets
        )
        total_current_liabilities = (
            payables + accrued_expenses + short_term_borrowings
            + current_long_term_debt + previous["bs.current_lease_liabilities"]
            + income_taxes_payable + deferred_revenue_current
            + other_current_liabilities
        )
        total_liabilities = (
            total_current_liabilities + long_term_debt
            + previous["bs.long_term_leases"] + deferred_revenue_noncurrent
            + previous["bs.pension_liability"] + deferred_tax_liability
            + other_noncurrent_liabilities
        )
        total_common_equity = (
            common_stock_apic + retained_earnings + treasury_stock + aoci
        )
        total_equity = total_common_equity + minority_interest
        total_liabilities_equity = total_liabilities + total_equity

        nopat = operating_income * (1.0 - driver("nopat_tax_rate"))
        fcff = cfo - income["is.net_income_company"] + nopat + capex
        net_borrowing = debt_issued + debt_repaid
        fcfe = cfo + capex + net_borrowing

        values = {
            **income,
            "cf.net_income": income["is.net_income_company"],
            "cf.da": da,
            "cf.intangible_amortization": intangible_amortization,
            "cf.gain_sale_assets": -gain_on_sale_assets,
            "cf.gain_sale_investments": 0.0,
            "cf.asset_writedown_restructuring": 0.0,
            "cf.credit_loss_provision": 0.0,
            "cf.stock_based_compensation": stock_compensation,
            "cf.change_accounts_receivable": change_receivables,
            "cf.change_inventory": change_inventory,
            "cf.change_accounts_payable": change_payables,
            "cf.change_deferred_revenue": change_deferred_revenue,
            "cf.change_income_taxes": change_income_taxes,
            "cf.change_deferred_taxes": change_deferred_taxes,
            "cf.change_other_operating_assets": change_other_operating_assets,
            "cf.other_operating_activities": other_operating_cash_flow,
            "cf.cash_from_operations": cfo,
            "cf.capex": capex,
            "cf.sale_ppe": sale_proceeds,
            "cf.acquisitions": acquisitions,
            "cf.divestitures": 0.0,
            "cf.investments": investments,
            "cf.other_investing": other_investing_cash_flow,
            "cf.cash_from_investing": cfi,
            "cf.debt_issued": debt_issued,
            "cf.debt_repaid": debt_repaid,
            "cf.common_stock_issued": common_stock_issued,
            "cf.share_repurchase": buybacks,
            "cf.dividends_paid": dividends_paid,
            "cf.other_financing": other_financing_cash_flow,
            "cf.cash_from_financing": cff,
            "cf.fx_adjustment": fx_adjustment,
            "cf.misc_adjustment": misc_adjustment,
            "cf.net_change_cash": net_change_cash,
            "cf.levered_fcf": fcfe,
            "cf.unlevered_fcf": fcff,
            "bs.cash": ending_cash,
            "bs.short_term_investments": short_term_investments,
            "bs.cash_and_investments": cash_and_investments,
            "bs.accounts_receivable": receivables,
            "bs.other_receivables": other_receivables,
            "bs.total_receivables": total_receivables,
            "bs.inventory": inventory,
            "bs.prepaids": prepaids,
            "bs.other_current_assets": other_current_assets,
            "bs.total_current_assets": total_current_assets,
            "bs.gross_ppe": gross_ppe,
            "bs.accumulated_depreciation": accumulated_depreciation,
            "bs.net_ppe": net_ppe,
            "bs.long_term_investments": previous["bs.long_term_investments"],
            "bs.goodwill": goodwill,
            "bs.other_intangibles": other_intangibles,
            "bs.gross_intangibles": gross_intangibles,
            "bs.accumulated_amortization": accumulated_amortization,
            "bs.long_term_receivables": long_term_receivables,
            "bs.deferred_tax_assets": deferred_tax_assets,
            "bs.other_long_term_assets": other_long_term_assets,
            "bs.total_assets": total_assets,
            "bs.accounts_payable": payables,
            "bs.accrued_expenses": accrued_expenses,
            "bs.short_term_borrowings": short_term_borrowings,
            "bs.current_long_term_debt": current_long_term_debt,
            "bs.current_lease_liabilities": previous["bs.current_lease_liabilities"],
            "bs.income_taxes_payable": income_taxes_payable,
            "bs.deferred_revenue_current": deferred_revenue_current,
            "bs.other_current_liabilities": other_current_liabilities,
            "bs.total_current_liabilities": total_current_liabilities,
            "bs.long_term_debt": long_term_debt,
            "bs.long_term_leases": previous["bs.long_term_leases"],
            "bs.deferred_revenue_noncurrent": deferred_revenue_noncurrent,
            "bs.pension_liability": previous["bs.pension_liability"],
            "bs.deferred_tax_liability": deferred_tax_liability,
            "bs.other_noncurrent_liabilities": other_noncurrent_liabilities,
            "bs.total_liabilities": total_liabilities,
            "bs.common_stock_apic": common_stock_apic,
            "bs.retained_earnings": retained_earnings,
            "bs.treasury_stock": treasury_stock,
            "bs.aoci": aoci,
            "bs.total_common_equity": total_common_equity,
            "bs.minority_interest": minority_interest,
            "bs.total_equity": total_equity,
            "bs.total_liabilities_equity": total_liabilities_equity,
            "bs.total_debt": reported_total_debt,
            "bs.net_debt": reported_total_debt - cash_and_investments,
            "bs.working_capital": total_current_assets - total_current_liabilities,
            "bs.net_working_capital": (
                total_receivables + inventory - payables - deferred_revenue
            ),
            "wc.receivables": receivables,
            "wc.inventory": inventory,
            "wc.payables": payables,
            "wc.deferred_revenue": deferred_revenue,
            "wc.operating_nwc": receivables + inventory - payables - deferred_revenue,
            "wc.change_nwc": (
                receivables + inventory - payables - deferred_revenue
                - (previous["bs.accounts_receivable"]
                   + previous["bs.inventory"] - previous["bs.accounts_payable"]
                   - previous["bs.deferred_revenue_current"]
                   - previous["bs.deferred_revenue_noncurrent"])
            ),
            "wc.dso": driver("dso"),
            "wc.dio": driver("dio"),
            "wc.dpo": driver("dpo"),
            "ppe.beginning_gross_ppe": previous["bs.gross_ppe"],
            "ppe.capex": capex_addition,
            "ppe.disposals": asset_cost_disposals,
            "ppe.ending_gross_ppe": gross_ppe,
            "ppe.depreciation": depreciation,
            "ppe.ending_net_ppe": net_ppe,
            "ppe.goodwill": goodwill,
            "ppe.intangibles": other_intangibles,
            "ppe.gross_intangibles": gross_intangibles,
            "ppe.accumulated_amortization": accumulated_amortization,
            "ppe.amortization": intangible_amortization,
            "debt.cash": ending_cash,
            "debt.investments": short_term_investments + previous["bs.long_term_investments"],
            "debt.short_term_debt": short_term_borrowings + current_long_term_debt,
            "debt.long_term_debt": long_term_debt,
            "debt.total_debt": total_borrowings,
            "debt.lease_liabilities": previous["bs.current_lease_liabilities"] + previous["bs.long_term_leases"],
            "debt.net_debt": total_borrowings - ending_cash - short_term_investments - previous["bs.long_term_investments"],
            "debt.interest_expense": interest_expense,
            "debt.interest_income": income["is.interest_income"],
            "capital.cfo": cfo,
            "capital.capex": capex,
            "capital.acquisitions": acquisitions,
            "capital.dividends": dividends_paid,
            "capital.buybacks": buybacks,
            "capital.debt_issuance": debt_issued,
            "capital.debt_repayment": debt_repaid,
            "capital.post_allocation_cash": cfo + capex + acquisitions + dividends_paid + buybacks + debt_issued + debt_repaid,
            "tax.pretax_income": income["is.ebt"],
            "tax.income_tax_expense": income["is.income_tax"],
            "tax.effective_rate": driver("effective_tax_rate"),
            "tax.cash_taxes": cash_taxes,
            "tax.deferred_taxes": change_deferred_taxes,
            "tax.nopat": nopat,
            "shares.basic_weighted_average": basic_shares,
            "shares.diluted_weighted_average": diluted_shares,
            "shares.period_end": period_end_shares,
            "shares.basic_eps": income["is.net_income_common"] / basic_shares,
            "shares.diluted_eps": income["is.net_income_common"] / diluted_shares,
            "shares.cash_dividend_per_share": cash_dividend_per_share,
            "shares.stock_compensation": -stock_compensation,
            "shares.dilution": incremental_diluted_shares,
        }
        diagnostics = {
            "balance_sheet": total_assets - total_liabilities_equity,
            "cash_flow": net_change_cash - (cfo + cfi + cff + fx_adjustment + misc_adjustment),
            "debt_tie": total_borrowings - (short_term_borrowings + current_long_term_debt + long_term_debt),
            "reported_debt_tie": reported_total_debt - total_borrowings - lease_liabilities,
            "cash_tie": ending_cash - previous["bs.cash"] - net_change_cash,
            "interest_expense_tie": interest_expense + (
                (beginning_borrowings + scheduled_borrowings) / 2.0
                * driver("cost_of_debt")
            ),
            "receivables_driver_tie": (
                receivables - revenue * driver("dso") / 365.0
            ),
            "inventory_driver_tie": (
                inventory - abs(cost_of_revenue) * driver("dio") / 365.0
            ),
            "payables_driver_tie": (
                payables - abs(cost_of_revenue) * driver("dpo") / 365.0
            ),
            "deferred_revenue_driver_tie": (
                deferred_revenue
                - revenue * driver("deferred_revenue_percent_revenue")
            ),
            "ppe_gross_roll_forward": (
                gross_ppe
                - previous["bs.gross_ppe"]
                - capex_addition
                + asset_cost_disposals
            ),
            "accumulated_depreciation_roll_forward": (
                accumulated_depreciation
                - previous["bs.accumulated_depreciation"]
                + depreciation
                - disposal_accumulated_depreciation
            ),
            "net_ppe_tie": net_ppe - gross_ppe - accumulated_depreciation,
            "da_split_tie": da - depreciation - intangible_amortization,
            "asset_sale_gain_tie": (
                gain_on_sale_assets
                - sale_proceeds
                + asset_cost_disposals
                - disposal_accumulated_depreciation
            ),
            "accumulated_amortization_roll_forward": (
                accumulated_amortization
                - previous["bs.accumulated_amortization"]
                + intangible_amortization
            ),
            "net_intangibles_tie": (
                other_intangibles - gross_intangibles - accumulated_amortization
            ),
            "investment_roll_forward": (
                short_term_investments
                - previous["bs.short_term_investments"]
                - driver("net_investment_purchases")
            ),
            "debt_roll_forward": (
                total_borrowings - beginning_borrowings - net_borrowing
            ),
            "tax_payable_roll_forward": (
                income_taxes_payable
                - previous["bs.income_taxes_payable"]
                - current_tax_expense
                - cash_taxes
            ),
            "tax_cash_conversion": (
                change_income_taxes + change_deferred_taxes
                - book_tax - cash_taxes
            ),
            "book_current_deferred_tax_identity": (
                book_tax - current_tax_expense - change_deferred_taxes
            ),
            "deferred_tax_asset_roll_forward": (
                deferred_tax_assets - previous["bs.deferred_tax_assets"]
                - change_deferred_tax_assets
            ),
            "deferred_tax_liability_roll_forward": (
                deferred_tax_liability - previous["bs.deferred_tax_liability"]
                - change_deferred_tax_liabilities
            ),
            "retained_earnings_roll_forward": (
                retained_earnings - previous["bs.retained_earnings"]
                - income["is.net_income_parent"] - dividends_paid
            ),
            "apic_roll_forward": (
                common_stock_apic - previous["bs.common_stock_apic"]
                - stock_compensation - common_stock_issued
                - other_financing_cash_flow
            ),
            "treasury_stock_roll_forward": (
                treasury_stock - previous["bs.treasury_stock"] - buybacks
            ),
            "aoci_roll_forward": (
                aoci - previous["bs.aoci"] - fx_adjustment - misc_adjustment
            ),
            "minority_interest_roll_forward": (
                minority_interest - previous["bs.minority_interest"]
                + income["is.minority_earnings"]
            ),
            "lease_liabilities_hold": (
                lease_liabilities - previous["bs.current_lease_liabilities"]
                - previous["bs.long_term_leases"]
            ),
            "shares_tie": period_end_shares - (
                previous["shares.period_end"]
                + issued_shares
                - repurchased_shares
            ),
            "basic_share_average_tie": (
                basic_shares
                - (previous["shares.period_end"] + period_end_shares) / 2.0
            ),
            "incremental_diluted_shares_tie": (
                diluted_shares - basic_shares - incremental_diluted_shares
            ),
            "basic_eps_tie": (
                income["is.net_income_common"] / basic_shares
                - values["shares.basic_eps"]
            ),
            "diluted_eps_tie": (
                income["is.net_income_common"] / diluted_shares
                - values["shares.diluted_eps"]
            ),
            "issuance_cash_share_price_tie": (
                common_stock_issued - issued_shares * average_share_price
            ),
            "buyback_cash_share_price_tie": (
                driver("buyback_amount") - repurchased_shares * average_share_price
            ),
            "cash_dividend_per_share_tie": (
                cash_dividend_per_share - abs(common_dividend) / basic_shares
            ),
            "dividend_retained_earnings_tie": (
                retained_earnings - previous["bs.retained_earnings"]
                - income["is.net_income_parent"] - dividends_paid
            ),
            "stock_compensation_currency_tie": (
                values["shares.stock_compensation"] + stock_compensation
            ),
            "fcff_definition": fcff - (cfo - income["is.net_income_company"] + nopat + capex),
            "fcfe_bridge": fcfe - (cfo + capex + net_borrowing),
            "minimum_cash": ending_cash - driver("minimum_cash"),
        }
        return values, diagnostics

    preliminary_income = income_statement(0.0)
    preliminary_values, _ = integrated_cash_and_balance(preliminary_income, 0.0)
    cash_basis = max(0.0, preliminary_values["bs.cash"])
    beginning_interest_assets = (
        previous["bs.cash"] + previous["bs.short_term_investments"]
        + previous["bs.long_term_investments"]
    )
    ending_pre_funding_interest_assets = (
        cash_basis + short_term_investments + previous["bs.long_term_investments"]
    )
    average_interest_assets = (
        beginning_interest_assets + ending_pre_funding_interest_assets
    ) / 2.0
    interest_income = average_interest_assets * driver("cash_yield")
    final_income = income_statement(interest_income)
    prefunding_values, _ = integrated_cash_and_balance(final_income, 0.0)
    liquidity_draw = max(0.0, driver("minimum_cash") - prefunding_values["bs.cash"])
    values, diagnostics = integrated_cash_and_balance(final_income, liquidity_draw)
    diagnostics["interest_income_tie"] = (
        values["is.interest_income"]
        - average_interest_assets * driver("cash_yield")
    )
    if values["bs.cash"] < driver("minimum_cash") - BALANCE_TOLERANCE:
        raise ForecastCalculationError("minimum-cash liquidity policy failed")
    return values, liquidity_draw, diagnostics

def _build_model_result(
    *,
    scenario: ScenarioDriverSet,
    axis: PeriodAxis,
    registry: tuple[LineItemSpec, ...],
    store: _LineStore,
    period_diagnostics: Sequence[Mapping[str, float]],
    input_hash: str,
    tolerance: float,
) -> ModelResult:
    series = store.series()
    statement_sections = ("income_statement", "balance_sheet", "cash_flow")
    statements = tuple(
        StatementResult(
            statement_key=section,
            lines=tuple(
                series[spec.canonical_key]
                for spec in registry
                if spec.statement_or_schedule == section
            ),
        )
        for section in statement_sections
    )
    schedule_sections = tuple(
        dict.fromkeys(
            spec.statement_or_schedule
            for spec in registry
            if spec.statement_or_schedule not in statement_sections
        )
    )
    schedules = tuple(
        ScheduleResult(
            schedule_key=section,
            lines=tuple(
                series[spec.canonical_key]
                for spec in registry
                if spec.statement_or_schedule == section
            ),
        )
        for section in schedule_sections
    )

    checks: list[CheckResult] = []
    arithmetic_failure_ids: list[str] = []
    for period, diagnostics in zip(axis.periods, period_diagnostics, strict=True):
        for check_name in (
            "balance_sheet",
            "cash_flow",
            "debt_tie",
            "reported_debt_tie",
            "cash_tie",
            "shares_tie",
            "basic_share_average_tie",
            "incremental_diluted_shares_tie",
            "basic_eps_tie",
            "diluted_eps_tie",
            "issuance_cash_share_price_tie",
            "buyback_cash_share_price_tie",
            "cash_dividend_per_share_tie",
            "dividend_retained_earnings_tie",
            "stock_compensation_currency_tie",
            "interest_expense_tie",
            "interest_income_tie",
            "receivables_driver_tie",
            "inventory_driver_tie",
            "payables_driver_tie",
            "deferred_revenue_driver_tie",
            "ppe_gross_roll_forward",
            "accumulated_depreciation_roll_forward",
            "net_ppe_tie",
            "da_split_tie",
            "asset_sale_gain_tie",
            "accumulated_amortization_roll_forward",
            "net_intangibles_tie",
            "investment_roll_forward",
            "debt_roll_forward",
            "tax_payable_roll_forward",
            "tax_cash_conversion",
            "book_current_deferred_tax_identity",
            "deferred_tax_asset_roll_forward",
            "deferred_tax_liability_roll_forward",
            "retained_earnings_roll_forward",
            "apic_roll_forward",
            "treasury_stock_roll_forward",
            "aoci_roll_forward",
            "minority_interest_roll_forward",
            "fcfe_bridge",
            "fcff_definition",
            "lease_liabilities_hold",
        ):
            difference = float(diagnostics[check_name])
            status = CheckStatus.PASS if abs(difference) <= tolerance else CheckStatus.FAIL
            check_id = f"{check_name}:{period.key}"
            if status is CheckStatus.FAIL:
                arithmetic_failure_ids.append(check_id)
            checks.append(
                CheckResult(
                    check_id=check_id,
                    status=status,
                    difference=difference,
                    tolerance=tolerance,
                    message=(
                        "Integrated forecast identity reconciles."
                        if status is CheckStatus.PASS
                        else "Integrated forecast identity exceeds tolerance."
                    ),
                )
            )
        minimum_difference = float(diagnostics["minimum_cash"])
        minimum_status = (
            CheckStatus.PASS
            if minimum_difference >= -tolerance
            else CheckStatus.FAIL
        )
        minimum_check_id = f"minimum_cash:{period.key}"
        if minimum_status is CheckStatus.FAIL:
            arithmetic_failure_ids.append(minimum_check_id)
        checks.append(
            CheckResult(
                check_id=minimum_check_id,
                status=minimum_status,
                difference=min(0.0, minimum_difference),
                tolerance=tolerance,
                message="Ending cash meets the explicit minimum-cash path.",
            )
        )

    required_gaps = tuple(
        spec.canonical_key
        for spec in registry
        if spec.required
        and spec.statement_or_schedule != "segment_build"
        and any(
            value.state.status is not AvailabilityStatus.AVAILABLE
            for value in series[spec.canonical_key].values
        )
    )
    segment_keys = tuple(
        spec.canonical_key
        for spec in registry
        if spec.statement_or_schedule == "segment_build"
    )
    share_evidence_keys = tuple(
        key
        for key in _SHARE_EVIDENCE_KEYS
        if key in series
        and any(
            value.state.status is not AvailabilityStatus.AVAILABLE
            for value in series[key].values
        )
    )
    checks.append(
        CheckResult(
            check_id="scenario_driver_completeness",
            status=CheckStatus.PASS,
            difference=0.0,
            tolerance=0.0,
            message="The scenario supplies every required five-year driver path.",
        )
    )
    checks.append(
        CheckResult(
            check_id="forecast_axis_completeness",
            status=CheckStatus.PASS,
            difference=0.0,
            tolerance=0.0,
            message="Every canonical line carries five typed period values.",
        )
    )
    checks.append(
        CheckResult(
            check_id="required_forecast_coverage",
            status=CheckStatus.BLOCKED if required_gaps else CheckStatus.PASS,
            difference=float(len(required_gaps)),
            tolerance=0.0,
            message=(
                "Required consolidated forecast lines are complete."
                if not required_gaps
                else "Required consolidated lines are unresolved: "
                + ", ".join(required_gaps)
            ),
        )
    )
    if segment_keys:
        checks.append(
            CheckResult(
                check_id="segment_kpi_evidence",
                status=CheckStatus.BLOCKED,
                difference=None,
                tolerance=0.0,
                message=(
                    "Segment/KPI source history and PM-approved allocation drivers "
                    "are required before those lines can be forecast."
                ),
            )
        )
    if share_evidence_keys:
        checks.append(
            CheckResult(
                check_id="share_declaration_and_fds_evidence",
                status=CheckStatus.BLOCKED,
                difference=None,
                tolerance=0.0,
                message=(
                    "Declared DPS and current fully diluted share components require "
                    "source evidence or PM-approved inputs; weighted-average dilution "
                    "is not reused as period-end issuance."
                ),
            )
        )


    counterpart_gaps = tuple(
        key
        for key in _DIAGNOSTIC_COUNTERPART_POLICIES
        if any(
            abs(scenario.value(key, year)) > 1e-12
            for year in range(1, FORECAST_YEARS + 1)
        )
    )
    for key in counterpart_gaps:
        checks.append(
            CheckResult(
                check_id=f"counterpart_policy:{key}",
                status=CheckStatus.BLOCKED,
                difference=max(abs(value) for value in scenario.path_map[key].values),
                tolerance=0.0,
                message=_DIAGNOSTIC_COUNTERPART_POLICIES[key],
            )
        )
    blockers: list[str] = [f"arithmetic_check_failed:{item}" for item in arithmetic_failure_ids]
    blockers.extend(f"required_forecast_gap:{item}" for item in required_gaps)
    blockers.extend(
        f"pm_approval_required:{scenario.scenario_key}:{path.key}:{path.queue_item_id}"
        for path in scenario.unapproved_paths
    )
    blockers.extend(f"source_or_pm_required:{key}" for key in segment_keys)
    blockers.extend(f"source_or_pm_required:{key}" for key in share_evidence_keys)
    blockers.extend(
        f"unsupported_counterpart_policy:{scenario.scenario_key}:{key}"
        for key in counterpart_gaps
    )
    warnings = [
        "Interest and minimum cash use a deterministic lagged-average policy; current-year liquidity draws accrue interest next year.",
        "DIO and DPO use cost of revenue as the disclosed purchases approximation.",
        "Excess cash is retained; the model has no automatic debt cash sweep.",
    ]
    warnings.extend(
        f"Diagnostic-only counterpart policy: {_DIAGNOSTIC_COUNTERPART_POLICIES[key]}."
        for key in counterpart_gaps
    )
    if arithmetic_failure_ids or required_gaps or counterpart_gaps:
        state = _typed_state(
            AvailabilityStatus.BLOCKING,
            "integrated_forecast_check_failed",
            "One or more forecast identities or required consolidated lines failed.",
        )
    elif scenario.unapproved_paths or segment_keys or share_evidence_keys:
        state = _typed_state(
            AvailabilityStatus.PM_REQUIRED,
            "forecast_requires_pm_or_source_evidence",
            "The deterministic diagnostic is calculated, but unapproved drivers or source-dependent modules require review.",
        )
    else:
        state = _available()
    tolerances = {check.check_id: float(check.tolerance or 0.0) for check in checks}
    return ModelResult(
        scenario_key=scenario.scenario_key,
        state=state,
        period_axis=axis,
        statements=statements,
        supporting_schedules=schedules,
        check_results=tuple(checks),
        tolerances=tolerances,
        warnings=tuple(warnings),
        blockers=tuple(blockers),
        input_hash=input_hash,
    )


def build_five_year_forecast(
    historical: Any,
    scenario: ScenarioDriverSet,
    *,
    last_historical_period_end: date,
    registry: Sequence[LineItemSpec] | None = None,
    tolerance: float = BALANCE_TOLERANCE,
) -> ForecastScenarioResult:
    """Build one full five-year annual IS/BS/CF model and its schedules.

    ``historical`` uses the normalized latest-actual convention documented in
    the module docstring. The result includes every supplied registry line for
    all five years. Source-dependent segment/KPI and absent consensus lines are
    typed gaps rather than inferred values.
    """
    if tolerance < 0.0 or not math.isfinite(tolerance):
        raise ValueError("tolerance must be a finite non-negative number")
    if not isinstance(historical, Mapping):
        _, fiscal_seed_end = _historical_fiscal_seed(historical)
        _reject_post_fiscal_reference_periods(historical, fiscal_seed_end)
        if fiscal_seed_end is not None and fiscal_seed_end != last_historical_period_end:
            raise IncompleteHistoricalSeedError(
                "last_historical_period_end must equal the latest fiscal-year "
                "actual used as the forecast seed; LTM cannot advance the annual axis"
            )
    seed = _coerce_historical_seed(historical)

    active_registry = tuple(registry or professional_line_item_registry())
    registry_keys = tuple(spec.canonical_key for spec in active_registry)
    if len(set(registry_keys)) != len(registry_keys):
        raise ForecastPolicyError("forecast registry contains duplicate canonical keys")
    axis = _forecast_axis(last_historical_period_end)
    store = _LineStore(active_registry, axis)
    previous: dict[str, float] = dict(seed)
    liquidity_draws: list[float] = []
    diagnostics: list[dict[str, float]] = []
    source_refs = tuple(path.source_ref for path in scenario.paths)
    for year in range(1, FORECAST_YEARS + 1):
        period_values, liquidity_draw, period_diagnostics = _calculate_period(
            previous, scenario, year
        )
        for key, value in period_values.items():
            if key in store.values:
                store.set(
                    key,
                    year,
                    value,
                    f"integrated_forecast:{key}:v1",
                    source_refs,
                )
        liquidity_draws.append(liquidity_draw)
        diagnostics.append(period_diagnostics)
        previous = {**previous, **period_values}
    input_hash = _hash_payload(
        {
            "historical": dict(sorted(seed.items())),
            "scenario": {
                "scenario_key": scenario.scenario_key,
                "parent_scenario_key": scenario.parent_scenario_key,
                "paths": [
                    {
                        "key": path.key,
                        "values": path.values,
                        "unit": path.unit,
                        "source_ref": path.source_ref,
                        "method": path.method,
                        "approval_ref": path.approval_ref,
                        "driver_group": path.driver_group.value,
                        "current_driver_fingerprint": path.current_driver_fingerprint,
                        "approved_driver_fingerprint": path.approved_driver_fingerprint,
                        "queue_item_id": path.queue_item_id,
                    }
                    for path in scenario.paths
                ],
            },
            "last_historical_period_end": last_historical_period_end.isoformat(),
            "registry_keys": registry_keys,
            "circularity_policy": CIRCULARITY_POLICY_ID,
        }
    )
    model = _build_model_result(
        scenario=scenario,
        axis=axis,
        registry=active_registry,
        store=store,
        period_diagnostics=diagnostics,
        input_hash=input_hash,
        tolerance=tolerance,
    )
    return ForecastScenarioResult(
        scenario_key=scenario.scenario_key,
        model=model,
        liquidity_draws=tuple(liquidity_draws),
        circularity_policy=CircularityPolicy(),
        debt_convention=DebtConvention(),
        registry_keys=registry_keys,
    )


def build_complete_scenario_forecasts(
    historical: Any,
    scenarios: Sequence[ScenarioDriverSet],
    *,
    last_historical_period_end: date,
    registry: Sequence[LineItemSpec] | None = None,
    tolerance: float = BALANCE_TOLERANCE,
) -> ForecastScenarioBundle:
    """Recalculate complete Base, Upside, and Downside integrated statements."""
    scenario_list = tuple(scenarios)
    keys = [scenario.scenario_key for scenario in scenario_list]
    if len(set(keys)) != len(keys):
        raise InvalidScenarioPolicyError("scenario bundle contains duplicate scenario identities")
    if set(keys) != set(SCENARIO_KEYS):
        raise InvalidScenarioPolicyError(
            "scenario bundle must contain exactly Base, Upside, and Downside"
        )
    by_key = {scenario.scenario_key: scenario for scenario in scenario_list}
    if by_key["Base"].parent_scenario_key is not None:
        raise InvalidScenarioPolicyError("Base scenario cannot have a parent")
    for key in ("Upside", "Downside"):
        if by_key[key].parent_scenario_key != "Base":
            raise InvalidScenarioPolicyError(f"{key} scenario must identify parent Base")
    active_registry = tuple(registry or professional_line_item_registry())
    results = tuple(
        build_five_year_forecast(
            historical,
            by_key[key],
            last_historical_period_end=last_historical_period_end,
            registry=active_registry,
            tolerance=tolerance,
        )
        for key in SCENARIO_KEYS
    )
    hashes = {result.model.period_axis.canonical_hash() for result in results}
    if len(hashes) != 1:
        raise ForecastCalculationError("scenario forecast axes are inconsistent")
    registry_keys = tuple(spec.canonical_key for spec in active_registry)
    input_hash = _hash_payload(
        {
            "scenario_input_hashes": [result.model.input_hash for result in results],
            "registry_keys": registry_keys,
            "scenario_keys": SCENARIO_KEYS,
        }
    )
    return ForecastScenarioBundle(
        scenarios=results,
        registry_keys=registry_keys,
        input_hash=input_hash,
    )