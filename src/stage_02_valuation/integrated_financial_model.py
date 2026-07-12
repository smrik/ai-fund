"""Deterministic historical three-statement model construction.

This module is deliberately limited to source-backed historical periods.  It
does not synthesize quarters, segments, consensus, or forecast assumptions.
Every registered line receives a value with exact cell lineage, a deterministic
derived formula, or a typed unavailable state.  The resulting ``ModelResult``
is therefore safe to hand to the forecast engine and workbook renderer without
conflating missing evidence with zero.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3
from typing import Any, Iterable, Mapping, Sequence

from src.contracts.professional_financial_model import (
    AvailabilityState,
    AvailabilityStatus,
    CheckResult,
    CheckStatus,
    EstimateStatus,
    FactFormulaStatus,
    LineItemSpec,
    LineSeries,
    ModelInputSnapshot,
    ModelPeriod,
    ModelResult,
    PeriodAxis,
    PeriodType,
    PeriodValue,
    ScheduleResult,
    SourceFact,
    StatementResult,
)
from src.stage_02_valuation.model_line_items import (
    PRIMARY_STATEMENT_SHEET,
    REGISTRY_VERSION,
    professional_line_item_registry,
    validate_line_item_registry,
)


HISTORICAL_ENGINE_VERSION = "integrated_historicals_v1"
PRIMARY_STATEMENTS = frozenset({"income_statement", "balance_sheet", "cash_flow"})
SOURCE_DEPENDENT_SECTIONS = frozenset({"segment_build", "consensus_bridge"})
DEFAULT_TOLERANCES: Mapping[str, float] = {
    "balance_sheet": 0.1,
    "cash_flow": 0.1,
    "debt_tie": 0.1,
    "cash_tie": 0.1,
    "diluted_eps": 0.02,
    "coverage": 0.0,
}


class HistoricalModelError(ValueError):
    """Base class for deterministic historical-model failures."""


class AmbiguousHistoricalSourceError(HistoricalModelError):
    """Raised when source identity or restatement selection is ambiguous."""


class IncompleteHistoricalAxisError(HistoricalModelError):
    """Raised when annual actuals do not form a coherent fiscal axis."""


@dataclass(frozen=True, slots=True)
class HistoricalSourceReference:
    """Exact source-cell identity retained for audit and workbook lineage."""

    source_ref: str
    ticker: str
    ciq_run_id: int | None
    source_file: str
    sheet_name: str
    row_index: int
    column_index: int
    a1_locator: str
    cell_locator: str
    row_label: str
    formula_text: str | None
    formula_status: str
    source_value: float | None

    period_key: str | None = None
    period_end: date | None = None
    period_type: PeriodType | None = None
    estimate_status: EstimateStatus = EstimateStatus.UNKNOWN
    raw_source_value: Any = None
    displayed_value: str | None = None
    unit: str | None = None
    unit_kind: str | None = None
    scale: float | None = None
    currency: str | None = None
    formula_error: str | None = None

@dataclass(frozen=True, slots=True)
class HistoricalPeriodLineage:
    """Resolution and sign audit for one canonical line in one period."""

    canonical_key: str
    period_key: str
    method_id: str
    formula_id: str | None
    state: AvailabilityState
    source_refs: tuple[HistoricalSourceReference, ...]
    source_value: float | None
    normalized_value: float | None
    source_sign: str
    normalized_sign: str
    normalization_rule: str

    period_end: date | None = None
    period_type: PeriodType | None = None
    raw_source_value: Any = None
    source_unit: str | None = None
    source_unit_kind: str | None = None
    source_scale: float | None = None
    source_currency: str | None = None
    formula_status: str = "unverified"
    formula_error: str | None = None
    derived_value: float | None = None
    transformation_rule: str = "unverified"
    upstream_dependencies: tuple[str, ...] = ()
    downstream_dependencies: tuple[str, ...] = ()

@dataclass(frozen=True, slots=True)
class HistoricalCoverageSummary:
    registry_line_count: int
    period_count: int
    typed_cell_count: int
    direct_cell_count: int
    derived_cell_count: int
    unavailable_cell_count: int
    required_direct_cell_count: int
    required_direct_available_count: int
    source_dependent_gap_count: int

    @property
    def required_direct_coverage(self) -> float:
        if self.required_direct_cell_count == 0:
            return 1.0
        return self.required_direct_available_count / self.required_direct_cell_count


@dataclass(frozen=True, slots=True)
class HistoricalFinancialModel:
    """Typed historical output used by forecasts and the workbook v2 renderer."""

    ticker: str
    engine_version: str
    registry_version: str
    registry: tuple[LineItemSpec, ...]
    result: ModelResult
    lineage: tuple[HistoricalPeriodLineage, ...]
    coverage: HistoricalCoverageSummary
    limitations: tuple[str, ...]

    @property
    def period_keys(self) -> tuple[str, ...]:
        return tuple(period.key for period in self.result.period_axis.periods)

    def line(self, canonical_key: str) -> LineSeries:
        for container in (*self.result.statements, *self.result.supporting_schedules):
            for line in container.lines:
                if line.line_key == canonical_key:
                    return line
        raise KeyError(canonical_key)

    def value(self, canonical_key: str, period_key: str) -> PeriodValue:
        for value in self.line(canonical_key).values:
            if value.period_key == period_key:
                return value
        raise KeyError((canonical_key, period_key))

    def period_lineage(
        self,
        canonical_key: str,
        period_key: str,
    ) -> HistoricalPeriodLineage:
        for item in self.lineage:
            if item.canonical_key == canonical_key and item.period_key == period_key:
                return item
        raise KeyError((canonical_key, period_key))


@dataclass(frozen=True, slots=True)
class _FactRecord:
    ticker: str
    ciq_run_id: int | None
    source_file: str
    sheet_name: str
    row_index: int
    column_index: int
    a1_locator: str
    cell_locator: str
    row_label: str
    canonical_key: str | None
    period_key: str
    period_end: date
    period_type: PeriodType
    estimate_status: EstimateStatus
    formula_text: str | None
    formula_status: str
    value: float | None
    usable: bool
    source_ref: str
    raw_source_value: Any
    displayed_value: str | None
    unit: str | None
    unit_kind: str | None
    scale: float | None
    currency: str | None
    formula_error: str | None

    @property
    def row_identity(self) -> tuple[str, int]:
        return (self.sheet_name, self.row_index)

    def reference(self) -> HistoricalSourceReference:
        return HistoricalSourceReference(
            source_ref=self.source_ref,
            ticker=self.ticker,
            ciq_run_id=self.ciq_run_id,
            source_file=self.source_file,
            sheet_name=self.sheet_name,
            row_index=self.row_index,
            column_index=self.column_index,
            a1_locator=self.a1_locator,
            cell_locator=self.cell_locator,
            row_label=self.row_label,
            formula_text=self.formula_text,
            formula_status=self.formula_status,
            source_value=self.value,
            period_key=self.period_key,
            period_end=self.period_end,
            period_type=self.period_type,
            estimate_status=self.estimate_status,
            raw_source_value=self.raw_source_value,
            displayed_value=self.displayed_value,
            unit=self.unit,
            unit_kind=self.unit_kind,
            scale=self.scale,
            currency=self.currency,
            formula_error=self.formula_error,
        )


@dataclass(frozen=True, slots=True)
class _ResolvedValue:
    period_value: PeriodValue
    lineage: HistoricalPeriodLineage


def _available() -> AvailabilityState:
    return AvailabilityState(status=AvailabilityStatus.AVAILABLE)


def _unavailable(
    status: AvailabilityStatus,
    reason_code: str,
    message: str,
) -> AvailabilityState:
    return AvailabilityState(status=status, reason_code=reason_code, message=message)


def _as_date(value: Any) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    try:
        return date.fromisoformat(text[:10])
    except ValueError as exc:
        raise IncompleteHistoricalAxisError(f"invalid period date {value!r}") from exc


def _numeric(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
    else:
        try:
            number = float(str(value).replace(",", "").strip())
        except (TypeError, ValueError):
            return None
    return number if math.isfinite(number) else None


def _period_from_raw(
    *,
    calculation_type: Any,
    period_type: Any,
    period_end: date | None,
) -> tuple[str, PeriodType] | None:
    calc = str(calculation_type or "").strip().upper()
    typed = str(getattr(period_type, "value", period_type) or "").strip().lower()
    fiscal_match = re.fullmatch(r"FY(\d{2}|\d{4})", calc)
    if fiscal_match:
        fiscal_year = int(fiscal_match.group(1))
        period_key = f"FY{fiscal_year % 100:02d}"
        if period_end is not None and fiscal_year % 100 != period_end.year % 100:
            raise IncompleteHistoricalAxisError(
                f"{calc} does not match period end {period_end.isoformat()}"
            )
        return period_key, PeriodType.FISCAL_YEAR
    if calc in {"LTM", "TTM"}:
        return "LTM", PeriodType.LTM
    if typed == PeriodType.FISCAL_YEAR.value and period_end is not None:
        return f"FY{period_end.year % 100:02d}", PeriodType.FISCAL_YEAR
    if typed == PeriodType.LTM.value:
        return "LTM", PeriodType.LTM
    return None


def _formula_usable(status: str, value: float | None) -> bool:
    normalized = status.strip().lower()
    bad = {
        "error",
        "formula_error",
        "cached_error",
        "formula_cache_missing",
        "stale",
        "unavailable",
    }
    return value is not None and normalized not in bad


def _record_from_source_fact(fact: SourceFact) -> _FactRecord | None:
    period = _period_from_raw(
        calculation_type=fact.calculation_type,
        period_type=fact.period_type,
        period_end=fact.period_end,
    )
    if period is None or fact.period_end is None:
        return None
    value = _numeric(fact.cached_value)
    status = fact.formula_status.value
    formula_error = fact.formula_error
    usable = (
        fact.quality_state.status is AvailabilityStatus.AVAILABLE
        and fact.estimate_status is EstimateStatus.ACTUAL
        and not formula_error
        and _formula_usable(status, value)
    )
    return _FactRecord(
        ticker=fact.ticker,
        ciq_run_id=fact.ciq_run_id,
        source_file=fact.source_file,
        sheet_name=fact.workbook_sheet,
        row_index=fact.row_index,
        column_index=fact.column_index,
        a1_locator=fact.cell_locator,
        cell_locator=f"{fact.workbook_sheet}!{fact.cell_locator}",
        row_label=fact.row_label,
        canonical_key=fact.canonical_key,
        period_key=period[0],
        period_end=fact.period_end,
        period_type=period[1],
        estimate_status=fact.estimate_status,
        formula_text=fact.formula_text,
        formula_status=status,
        value=value,
        usable=usable,
        source_ref=fact.fact_id,
        raw_source_value=fact.cached_value,
        displayed_value=fact.displayed_value,
        unit=fact.unit,
        unit_kind=fact.unit_kind.value,
        scale=fact.scale,
        currency=fact.currency,
        formula_error=formula_error,
    )


def _mapping_status(record: Mapping[str, Any]) -> AvailabilityStatus:
    quality = record.get("quality_state")
    if isinstance(quality, AvailabilityState):
        return quality.status
    if isinstance(quality, Mapping):
        raw = quality.get("status", AvailabilityStatus.AVAILABLE.value)
    else:
        raw = AvailabilityStatus.AVAILABLE.value
    try:
        return AvailabilityStatus(str(getattr(raw, "value", raw)).lower())
    except ValueError:
        return AvailabilityStatus.UNAVAILABLE


def _record_from_mapping(record: Mapping[str, Any]) -> _FactRecord | None:
    sheet = str(record.get("sheet_name") or record.get("workbook_sheet") or "").strip()
    period_end = _as_date(record.get("period_date") or record.get("period_end"))
    period = _period_from_raw(
        calculation_type=record.get("calc_type") or record.get("calculation_type"),
        period_type=record.get("period_type"),
        period_end=period_end,
    )
    if period is None or period_end is None:
        return None
    row_index = int(record.get("row_index") or 0)
    column_index = int(record.get("column_index") or 0)
    if row_index <= 0 or column_index <= 0:
        raise AmbiguousHistoricalSourceError("source facts require positive row and column indices")
    a1 = str(record.get("a1_locator") or "").strip().upper()
    cell = str(record.get("cell_locator") or "").strip()
    if not a1 and "!" in cell:
        a1 = cell.rsplit("!", 1)[-1].upper()
    if not cell:
        cell = f"{sheet}!{a1}"
    value_raw = record.get("value_num")
    if value_raw is None:
        value_raw = record.get("cached_value")
    value = _numeric(value_raw)
    formula_status = str(record.get("formula_status") or "literal").strip().lower()
    raw_source_value = (
        record.get("cached_value")
        if "cached_value" in record
        else record.get("value_raw", value_raw)
    )
    raw_displayed = record.get("displayed_value", record.get("value_raw"))
    displayed_value = None if raw_displayed is None else str(raw_displayed)
    raw_unit = record.get("unit")
    unit = None if raw_unit in (None, "") else str(raw_unit)
    raw_unit_kind = getattr(record.get("unit_kind"), "value", record.get("unit_kind"))
    unit_kind = None if raw_unit_kind in (None, "") else str(raw_unit_kind)
    scale = _numeric(record.get("scale", record.get("scale_factor")))
    currency = None if record.get("currency") in (None, "") else str(record.get("currency"))
    formula_error = str(record.get("formula_error") or record.get("cached_error") or "").strip() or None
    raw_estimate = str(
        getattr(record.get("estimate_status"), "value", record.get("estimate_status") or "actual")
    ).lower()
    try:
        estimate_status = EstimateStatus(raw_estimate)
    except ValueError:
        estimate_status = EstimateStatus.UNKNOWN
    ticker = str(record.get("ticker") or "UNKNOWN").strip().upper()
    run_raw = record.get("run_id", record.get("ciq_run_id"))
    run_id = int(run_raw) if run_raw is not None else None
    source_file = str(record.get("source_file") or "unknown-source").strip()
    source_ref = str(record.get("fact_id") or "").strip()
    if not source_ref:
        source_ref = f"ciq-v2:{run_id if run_id is not None else 'na'}:{cell}"
    return _FactRecord(
        ticker=ticker,
        ciq_run_id=run_id,
        source_file=source_file,
        sheet_name=sheet,
        row_index=row_index,
        column_index=column_index,
        a1_locator=a1,
        cell_locator=cell,
        row_label=str(record.get("row_label") or "").strip(),
        canonical_key=(str(record.get("canonical_key")).strip() if record.get("canonical_key") else None),
        period_key=period[0],
        period_end=period_end,
        period_type=period[1],
        estimate_status=estimate_status,
        formula_text=(str(record.get("formula_text")) if record.get("formula_text") is not None else None),
        formula_status=formula_status,
        value=value,
        usable=(
            _mapping_status(record) is AvailabilityStatus.AVAILABLE
            and estimate_status is EstimateStatus.ACTUAL
            and not formula_error
            and _formula_usable(formula_status, value)
        ),
        source_ref=source_ref,
        raw_source_value=raw_source_value,
        displayed_value=displayed_value,
        unit=unit,
        unit_kind=unit_kind,
        scale=scale,
        currency=currency,
        formula_error=formula_error,
    )


def _canonical_input_hash(records: Sequence[_FactRecord]) -> str:
    payload = [
        {
            "source_ref": fact.source_ref,
            "ticker": fact.ticker,
            "run_id": fact.ciq_run_id,
            "cell": fact.cell_locator,
            "row_label": fact.row_label,
            "period_key": fact.period_key,
            "period_end": fact.period_end.isoformat(),
            "period_type": fact.period_type.value,
            "estimate_status": fact.estimate_status.value,
            "raw_source_value": fact.raw_source_value,
            "value": fact.value,
            "unit": fact.unit,
            "unit_kind": fact.unit_kind,
            "scale": fact.scale,
            "currency": fact.currency,
            "formula_text": fact.formula_text,
            "formula_status": fact.formula_status,
            "formula_error": fact.formula_error,
        }
        for fact in sorted(records, key=lambda item: item.source_ref)
    ]
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _normalize_records(
    source: ModelInputSnapshot | Iterable[SourceFact | Mapping[str, Any]],
) -> tuple[list[_FactRecord], str, str]:
    if isinstance(source, ModelInputSnapshot):
        raw: Iterable[SourceFact | Mapping[str, Any]] = source.source_facts
        input_hash = str(source.content_hash)
        ticker = source.ticker
    else:
        raw = source
        input_hash = ""
        ticker = ""
    records: list[_FactRecord] = []
    for item in raw:
        record = (
            _record_from_source_fact(item)
            if isinstance(item, SourceFact)
            else _record_from_mapping(item)
        )
        if record is not None and record.sheet_name == PRIMARY_STATEMENT_SHEET:
            records.append(record)
    if not records:
        raise IncompleteHistoricalAxisError("no annual Financial Statements source facts")

    tickers = {record.ticker for record in records if record.ticker != "UNKNOWN"}
    if len(tickers) > 1:
        raise AmbiguousHistoricalSourceError(f"mixed tickers in source facts: {sorted(tickers)}")
    run_ids = {record.ciq_run_id for record in records if record.ciq_run_id is not None}
    if len(run_ids) > 1:
        raise AmbiguousHistoricalSourceError(f"mixed CIQ run IDs in source facts: {sorted(run_ids)}")
    inferred_ticker = ticker or (next(iter(tickers)) if tickers else "UNKNOWN")
    return records, inferred_ticker, input_hash or _canonical_input_hash(records)


def _period_axis(records: Sequence[_FactRecord]) -> tuple[PeriodAxis, tuple[str, ...]]:
    by_key: dict[str, set[tuple[date, PeriodType]]] = {}
    for record in records:
        by_key.setdefault(record.period_key, set()).add((record.period_end, record.period_type))
    inconsistent = {key: values for key, values in by_key.items() if len(values) != 1}
    if inconsistent:
        raise IncompleteHistoricalAxisError(f"inconsistent period identities: {sorted(inconsistent)}")

    fy = sorted(
        (
            (key, next(iter(values))[0])
            for key, values in by_key.items()
            if next(iter(values))[1] is PeriodType.FISCAL_YEAR
        ),
        key=lambda item: item[1],
    )
    if not fy:
        raise IncompleteHistoricalAxisError("at least one fiscal-year actual is required")
    years = [period_end.year for _, period_end in fy]
    if any(right - left != 1 for left, right in zip(years, years[1:])):
        raise IncompleteHistoricalAxisError(f"fiscal-year actuals are non-contiguous: {years}")
    if len({period_end for _, period_end in fy}) != len(fy):
        raise IncompleteHistoricalAxisError("fiscal-year period dates must be unique")

    ltm_values = sorted(
        (
            (key, next(iter(values))[0])
            for key, values in by_key.items()
            if next(iter(values))[1] is PeriodType.LTM
        ),
        key=lambda item: item[1],
    )
    warnings: list[str] = []
    if len(ltm_values) > 1:
        warnings.append("Multiple LTM periods were present; the latest LTM was selected deterministically.")
        ltm_values = ltm_values[-1:]
    if ltm_values and ltm_values[0][1] <= fy[-1][1]:
        raise IncompleteHistoricalAxisError("LTM period must follow the latest fiscal-year actual")
    ordered = [(key, end, PeriodType.FISCAL_YEAR) for key, end in fy]
    ordered.extend((key, end, PeriodType.LTM) for key, end in ltm_values)
    periods = tuple(
        ModelPeriod(index=index, key=key, end_date=end, period_type=kind)
        for index, (key, end, kind) in enumerate(ordered, start=1)
    )
    return PeriodAxis(periods=periods), tuple(warnings)


def _expected_row_band(spec: LineItemSpec) -> tuple[int, int] | None:
    if spec.canonical_key.startswith("is."):
        return (1, 182)
    if spec.canonical_key.startswith("cf."):
        return (183, 280)
    if spec.canonical_key.startswith("bs."):
        return (281, 471)
    return None


def _source_candidates(spec: LineItemSpec, records: Sequence[_FactRecord]) -> list[_FactRecord]:
    aliases = set(spec.source_mappings)
    candidates = [
        record
        for record in records
        if record.row_label in aliases or record.canonical_key == spec.canonical_key
    ]
    if not candidates:
        return []
    identities = {record.row_identity for record in candidates}
    band = _expected_row_band(spec)
    if len(identities) > 1 and band is not None:
        in_band = {
            identity for identity in identities if band[0] <= identity[1] <= band[1]
        }
        if in_band:
            identities = in_band
            candidates = [record for record in candidates if record.row_identity in identities]
    if len(identities) <= 1:
        return candidates

    period_keys = sorted({record.period_key for record in candidates})
    vectors: dict[tuple[str, int], tuple[tuple[bool, float | None], ...]] = {}
    coverage: dict[tuple[str, int], int] = {}
    for identity in identities:
        rows = [record for record in candidates if record.row_identity == identity]
        values: list[tuple[bool, float | None]] = []
        for key in period_keys:
            matches = [record for record in rows if record.period_key == key]
            usable = [record for record in matches if record.usable]
            values.append((bool(usable), usable[0].value if len(usable) == 1 else None))
        vectors[identity] = tuple(values)
        coverage[identity] = sum(1 for usable, _ in values if usable)
    max_coverage = max(coverage.values())
    best = sorted(identity for identity, count in coverage.items() if count == max_coverage)
    if len(best) == 1:
        return [record for record in candidates if record.row_identity == best[0]]
    if len({vectors[identity] for identity in best}) == 1:
        selected = best[0]
        return [record for record in candidates if record.row_identity == selected]
    rows = [f"{sheet}!{row}" for sheet, row in best]
    raise AmbiguousHistoricalSourceError(
        f"{spec.canonical_key} has conflicting source/restatement rows: {rows}"
    )


def _sign(value: float | None) -> str:
    if value is None:
        return "not_applicable"
    if value == 0:
        return "zero"
    return "positive" if value > 0 else "negative"


def _normalize_sign(value: float, sign_convention: str) -> tuple[float, str]:
    if sign_convention.strip().lower() == "negative":
        normalized = 0.0 if value == 0 else -abs(value)
        return normalized, "negative=-abs(source)"
    return value, "source_sign_preserved"


def _only_source_value(
    refs: Sequence[HistoricalSourceReference],
    field: str,
) -> Any:
    values = {
        getattr(ref, field)
        for ref in refs
        if getattr(ref, field) is not None
    }
    return next(iter(values)) if len(values) == 1 else None


def _lineage_evidence_fields(
    spec: LineItemSpec,
    period: ModelPeriod,
    refs: Sequence[HistoricalSourceReference],
    *,
    record: _FactRecord | None = None,
    derived_value: float | None = None,
    transformation_rule: str,
) -> dict[str, Any]:
    formula_errors = tuple(
        sorted({ref.formula_error for ref in refs if ref.formula_error})
    )
    if record is not None:
        formula_status = record.formula_status
        formula_error = record.formula_error
        raw_source_value = record.raw_source_value
    elif derived_value is not None:
        formula_status = "derived"
        formula_error = " | ".join(formula_errors) or None
        raw_source_value = None
    else:
        formula_status = "unavailable"
        formula_error = " | ".join(formula_errors) or None
        raw_source_value = None
    return {
        "period_end": period.end_date,
        "period_type": period.period_type,
        "raw_source_value": raw_source_value,
        "source_unit": _only_source_value(refs, "unit"),
        "source_unit_kind": _only_source_value(refs, "unit_kind"),
        "source_scale": _only_source_value(refs, "scale"),
        "source_currency": _only_source_value(refs, "currency"),
        "formula_status": formula_status,
        "formula_error": formula_error,
        "derived_value": derived_value,
        "transformation_rule": transformation_rule,

        "upstream_dependencies": tuple(spec.dependencies),
    }

def _direct_values(
    spec: LineItemSpec,
    records: Sequence[_FactRecord],
    period_axis: PeriodAxis,
) -> list[_ResolvedValue] | None:
    candidates = _source_candidates(spec, records)
    if not candidates:
        return None
    resolved: list[_ResolvedValue] = []
    for period in period_axis.periods:
        matches = [record for record in candidates if record.period_key == period.key]
        if len(matches) > 1:
            usable_values = {record.value for record in matches if record.usable}
            if len(usable_values) > 1:
                raise AmbiguousHistoricalSourceError(
                    f"{spec.canonical_key} {period.key} has conflicting source cells"
                )
            matches = sorted(matches, key=lambda item: (item.column_index, item.source_ref))[:1]
        record = matches[0] if matches else None
        if record is None or not record.usable or record.value is None:
            state = _unavailable(
                spec.missing_data_policy,
                "historical_source_value_unavailable",
                f"{spec.display_label} has no usable source value for {period.key}",
            )
            period_value = PeriodValue(period_key=period.key, state=state)
            lineage = HistoricalPeriodLineage(
                canonical_key=spec.canonical_key,
                period_key=period.key,
                method_id="historical:unavailable",
                formula_id=None,
                state=state,
                source_refs=((record.reference(),) if record is not None else ()),
                source_value=(record.value if record is not None else None),
                normalized_value=None,
                source_sign=_sign(record.value if record is not None else None),
                normalized_sign="not_applicable",
                normalization_rule="not_available",
                **_lineage_evidence_fields(
                    spec,
                    period,
                    (record.reference(),) if record is not None else (),
                    record=record,
                    transformation_rule="not_available",
                ),
            )
        else:
            value, rule = _normalize_sign(record.value, spec.sign_convention)
            if spec.canonical_key == "tax.effective_rate" and abs(value) > 1.0:
                value /= 100.0
                rule = "percentage_points_to_decimal_rate"
            reference = record.reference()
            state = _available()
            period_value = PeriodValue(
                period_key=period.key,
                value=value,
                state=state,
                source_refs=(record.source_ref,),
            )
            lineage = HistoricalPeriodLineage(
                canonical_key=spec.canonical_key,
                period_key=period.key,
                method_id="historical:direct",
                formula_id=None,
                state=state,
                source_refs=(reference,),
                source_value=record.value,
                normalized_value=value,
                source_sign=_sign(record.value),
                normalized_sign=_sign(value),
                normalization_rule=rule,
                **_lineage_evidence_fields(
                    spec,
                    period,
                    (reference,),
                    record=record,
                    transformation_rule=rule,
                ),
            )
        resolved.append(_ResolvedValue(period_value=period_value, lineage=lineage))
    return resolved


def _dedupe_refs(
    dependencies: Sequence[_ResolvedValue],
) -> tuple[HistoricalSourceReference, ...]:
    refs: dict[str, HistoricalSourceReference] = {}
    for dependency in dependencies:
        for ref in dependency.lineage.source_refs:
            refs[ref.source_ref] = ref
    return tuple(refs[key] for key in sorted(refs))


def _dependency_values(
    spec: LineItemSpec,
    period_index: int,
    resolved_by_key: Mapping[str, Sequence[_ResolvedValue]],
) -> tuple[list[_ResolvedValue], list[float]] | None:
    dependencies: list[_ResolvedValue] = []
    values: list[float] = []
    for key in spec.dependencies:
        resolved = resolved_by_key[key][period_index]
        value = _numeric(resolved.period_value.value)
        if resolved.period_value.state.status is not AvailabilityStatus.AVAILABLE or value is None:
            return None
        dependencies.append(resolved)
        values.append(value)
    return dependencies, values


def _calculate_formula(
    spec: LineItemSpec,
    period_index: int,
    period: ModelPeriod,
    resolved_by_key: Mapping[str, Sequence[_ResolvedValue]],
) -> tuple[float, str, tuple[HistoricalSourceReference, ...]] | None:
    key = spec.canonical_key
    if key == "ppe.ending_gross_ppe":
        current = resolved_by_key["bs.gross_ppe"][period_index]
        value = _numeric(current.period_value.value)
        if (
            current.period_value.state.status is not AvailabilityStatus.AVAILABLE
            or value is None
        ):
            return None
        return value, "historical:ppe.ending_gross_ppe", _dedupe_refs((current,))
    deps = _dependency_values(spec, period_index, resolved_by_key)
    if key in {"wc.change_nwc", "ppe.beginning_gross_ppe"}:
        if period_index == 0 or period.period_type is PeriodType.LTM:
            return None
        dependency_key = "wc.operating_nwc" if key == "wc.change_nwc" else "bs.gross_ppe"
        current = resolved_by_key[dependency_key][period_index]
        prior = resolved_by_key[dependency_key][period_index - 1]
        current_value = _numeric(current.period_value.value)
        prior_value = _numeric(prior.period_value.value)
        if (
            current.period_value.state.status is not AvailabilityStatus.AVAILABLE
            or prior.period_value.state.status is not AvailabilityStatus.AVAILABLE
            or current_value is None
            or prior_value is None
        ):
            return None
        value = current_value - prior_value if key == "wc.change_nwc" else prior_value
        return value, f"historical:{key}:prior_period", _dedupe_refs((current, prior))
    if deps is None:
        return None
    dependencies, values = deps
    by_key = dict(zip(spec.dependencies, values, strict=True))

    if key == "is.other_operating_expense":
        value = (
            by_key["is.operating_expenses_total"]
            - by_key["is.sga"]
            - by_key["is.research_development"]
        )
    elif key == "cf.stock_based_compensation":
        value = abs(values[0])
    elif key == "ppe.capex":
        value = abs(values[0])
    elif key == "ppe.depreciation":
        value = by_key["cf.da"] - by_key["cf.intangible_amortization"]
        if value < 0.0:
            return None
    elif key == "cf.levered_fcf":
        value = (
            by_key["cf.cash_from_operations"]
            + by_key["cf.capex"]
            + by_key["cf.debt_issued"]
            + by_key["cf.debt_repaid"]
        )
    elif key == "cf.unlevered_fcf":
        pretax_income = by_key["is.ebt"]
        if pretax_income == 0.0:
            return None
        tax_rate = -by_key["is.income_tax"] / pretax_income
        nopat = by_key["is.ebit"] * (1.0 - tax_rate)
        value = (
            by_key["cf.cash_from_operations"]
            - by_key["cf.net_income"]
            + nopat
            + by_key["cf.capex"]
        )
    elif key == "wc.operating_nwc":
        value = (
            by_key["wc.receivables"]
            + by_key["wc.inventory"]
            - by_key["wc.payables"]
            - by_key["wc.deferred_revenue"]
        )
    elif key == "wc.dso":
        if by_key["is.revenue"] == 0.0:
            return None
        value = by_key["wc.receivables"] / by_key["is.revenue"] * 365.0
    elif key == "wc.dio":
        if by_key["is.cost_of_revenue"] == 0.0:
            return None
        value = by_key["wc.inventory"] / abs(by_key["is.cost_of_revenue"]) * 365.0
    elif key == "wc.dpo":
        if by_key["is.cost_of_revenue"] == 0.0:
            return None
        value = by_key["wc.payables"] / abs(by_key["is.cost_of_revenue"]) * 365.0
    elif key == "ppe.ending_net_ppe":
        value = by_key["bs.net_ppe"]
    elif key == "ppe.intangibles":
        value = by_key["bs.other_intangibles"]
    elif key == "debt.total_debt":
        value = sum(values)
    elif key == "debt.interest_expense":
        value = by_key["is.interest_expense"]
    elif key == "debt.interest_income":
        value = by_key["is.interest_income"]
    elif key == "debt.net_debt":
        value = by_key["debt.total_debt"] - by_key["debt.cash"] - by_key["debt.investments"]
    elif key == "tax.effective_rate":
        if by_key["tax.pretax_income"] == 0.0:
            return None
        value = -by_key["tax.income_tax_expense"] / by_key["tax.pretax_income"]
    elif key == "tax.nopat":
        rate = by_key["tax.effective_rate"]
        value = by_key["is.ebit"] * (1.0 - rate)
    elif key == "shares.basic_eps":
        if by_key["shares.basic_weighted_average"] == 0.0:
            return None
        value = by_key["is.net_income_common"] / by_key["shares.basic_weighted_average"]
    elif key == "shares.diluted_eps":
        if by_key["shares.diluted_weighted_average"] == 0.0:
            return None
        value = by_key["is.net_income_common"] / by_key["shares.diluted_weighted_average"]
    elif key == "shares.dilution":
        value = by_key["shares.diluted_weighted_average"] - by_key["shares.basic_weighted_average"]
    elif key == "shares.cash_dividend_per_share":
        basic_shares = by_key["shares.basic_weighted_average"]
        if basic_shares == 0.0:
            return None
        common_cash_dividend = (
            by_key["cf.dividends_paid"] - by_key["is.preferred_dividends"]
        )
        value = abs(common_cash_dividend) / basic_shares
    elif key == "bs.net_debt":
        value = by_key["bs.total_debt"] - by_key["bs.cash_and_investments"]
    elif len(values) == 1:
        value = values[0]
    else:
        value = sum(values)
    if not math.isfinite(float(value)):
        return None
    return float(value), f"historical:{key}", _dedupe_refs(dependencies)


def _derived_values(
    spec: LineItemSpec,
    period_axis: PeriodAxis,
    resolved_by_key: Mapping[str, Sequence[_ResolvedValue]],
) -> list[_ResolvedValue]:
    resolved: list[_ResolvedValue] = []
    for period_index, period in enumerate(period_axis.periods):
        formula = _calculate_formula(spec, period_index, period, resolved_by_key) if spec.dependencies else None
        if formula is None:
            prior_period_line = spec.canonical_key in {
                "wc.change_nwc",
                "ppe.beginning_gross_ppe",
            }
            boundary = prior_period_line and period_index == 0
            ltm_prior_unavailable = prior_period_line and period.period_type is PeriodType.LTM
            if boundary or ltm_prior_unavailable:
                status = AvailabilityStatus.UNAVAILABLE
                reason = (
                    "ltm_year_ago_balance_unavailable"
                    if ltm_prior_unavailable
                    else "prior_period_outside_source_axis"
                )
                message = f"{spec.display_label} requires a period before {period.key}"
            else:
                status = spec.missing_data_policy
                reason = (
                    "historical_source_mapping_missing"
                    if not spec.dependencies
                    else "historical_dependency_unavailable"
                )
                message = f"{spec.display_label} cannot be resolved for {period.key}"
            state = _unavailable(status, reason, message)
            period_value = PeriodValue(period_key=period.key, state=state)
            lineage = HistoricalPeriodLineage(
                canonical_key=spec.canonical_key,
                period_key=period.key,
                method_id="historical:unavailable",
                formula_id=None,
                state=state,
                source_refs=(),
                source_value=None,
                normalized_value=None,
                source_sign="not_applicable",
                normalized_sign="not_applicable",
                normalization_rule="not_available",
                **_lineage_evidence_fields(
                    spec,
                    period,
                    (),
                    transformation_rule="not_available",
                ),
            )
        else:
            value, formula_id, refs = formula
            state = _available()
            period_value = PeriodValue(
                period_key=period.key,
                value=value,
                state=state,
                formula_id=formula_id,
                source_refs=tuple(ref.source_ref for ref in refs),
            )
            lineage = HistoricalPeriodLineage(
                canonical_key=spec.canonical_key,
                period_key=period.key,
                method_id="historical:derived",
                formula_id=formula_id,
                state=state,
                source_refs=refs,
                source_value=None,
                normalized_value=value,
                source_sign="mixed" if len(refs) > 1 else (_sign(refs[0].source_value) if refs else "not_applicable"),
                normalized_sign=_sign(value),
                normalization_rule="deterministic_formula",
                **_lineage_evidence_fields(
                    spec,
                    period,
                    refs,
                    derived_value=value,
                    transformation_rule=f"deterministic_formula:{formula_id}",
                ),
            )
        resolved.append(_ResolvedValue(period_value=period_value, lineage=lineage))
    return resolved


def _check(
    check_id: str,
    difference: float | None,
    tolerance: float,
    *,
    unavailable_message: str,
) -> CheckResult:
    if difference is None or not math.isfinite(difference):
        return CheckResult(
            check_id=check_id,
            status=CheckStatus.BLOCKED,
            tolerance=tolerance,
            message=unavailable_message,
        )
    status = CheckStatus.PASS if abs(difference) <= tolerance else CheckStatus.FAIL
    return CheckResult(
        check_id=check_id,
        status=status,
        difference=difference,
        tolerance=tolerance,
        message=("Within tolerance" if status is CheckStatus.PASS else "Outside tolerance"),
    )


def _number(
    resolved_by_key: Mapping[str, Sequence[_ResolvedValue]],
    key: str,
    period_index: int,
) -> float | None:
    item = resolved_by_key[key][period_index].period_value
    if item.state.status is not AvailabilityStatus.AVAILABLE:
        return None
    return _numeric(item.value)


def _accounting_checks(
    period_axis: PeriodAxis,
    resolved_by_key: Mapping[str, Sequence[_ResolvedValue]],
    tolerances: Mapping[str, float],
) -> list[CheckResult]:
    checks: list[CheckResult] = []
    for index, period in enumerate(period_axis.periods):
        assets = _number(resolved_by_key, "bs.total_assets", index)
        liabilities_equity = _number(resolved_by_key, "bs.total_liabilities_equity", index)
        checks.append(
            _check(
                f"balance_sheet:{period.key}",
                None if assets is None or liabilities_equity is None else assets - liabilities_equity,
                tolerances["balance_sheet"],
                unavailable_message="Total assets or liabilities and equity is unavailable",
            )
        )

        cash_flow_keys = (
            "cf.cash_from_operations",
            "cf.cash_from_investing",
            "cf.cash_from_financing",
            "cf.fx_adjustment",
            "cf.misc_adjustment",
            "cf.net_change_cash",
        )
        cash_flow_values = [_number(resolved_by_key, key, index) for key in cash_flow_keys]
        cash_flow_difference = (
            None
            if any(value is None for value in cash_flow_values)
            else sum(float(value) for value in cash_flow_values[:5]) - float(cash_flow_values[5])
        )
        checks.append(
            _check(
                f"cash_flow:{period.key}",
                cash_flow_difference,
                tolerances["cash_flow"],
                unavailable_message="Cash-flow bridge inputs are unavailable",
            )
        )

        debt_total = _number(resolved_by_key, "bs.total_debt", index)
        debt_components = [
            _number(resolved_by_key, key, index)
            for key in (
                "bs.short_term_borrowings",
                "bs.current_long_term_debt",
                "bs.long_term_debt",
                "bs.current_lease_liabilities",
                "bs.long_term_leases",
            )
        ]
        debt_difference = (
            None
            if debt_total is None or any(value is None for value in debt_components)
            else debt_total - sum(float(value) for value in debt_components)
        )
        checks.append(
            _check(
                f"debt_tie:{period.key}",
                debt_difference,
                tolerances["debt_tie"],
                unavailable_message="Total debt or debt components are unavailable",
            )
        )

        cash_and_investments = _number(resolved_by_key, "bs.cash_and_investments", index)
        cash = _number(resolved_by_key, "bs.cash", index)
        short_investments = _number(resolved_by_key, "bs.short_term_investments", index)
        cash_difference = (
            None
            if cash_and_investments is None or cash is None or short_investments is None
            else cash_and_investments - cash - short_investments
        )
        checks.append(
            _check(
                f"cash_tie:{period.key}",
                cash_difference,
                tolerances["cash_tie"],
                unavailable_message="Cash or short-term investments are unavailable",
            )
        )

        net_income = _number(resolved_by_key, "is.net_income_common", index)
        diluted_shares = _number(resolved_by_key, "shares.diluted_weighted_average", index)
        diluted_eps = _number(resolved_by_key, "shares.diluted_eps", index)
        eps_difference = (
            None
            if net_income is None or diluted_shares in {None, 0.0} or diluted_eps is None
            else net_income / diluted_shares - diluted_eps
        )
        checks.append(
            _check(
                f"diluted_eps:{period.key}",
                eps_difference,
                tolerances["diluted_eps"],
                unavailable_message="Net income, diluted shares, or diluted EPS is unavailable",
            )
        )
    return checks


def build_historical_financial_model(
    source: ModelInputSnapshot | Iterable[SourceFact | Mapping[str, Any]],
    *,
    registry: Sequence[LineItemSpec] | None = None,
    tolerances: Mapping[str, float] | None = None,
) -> HistoricalFinancialModel:
    """Build annual/LTM historical statements and supporting schedules.

    ``source`` may be a validated ``ModelInputSnapshot`` or exact rows returned
    by ``get_ciq_source_facts_v2``.  The builder rejects mixed runs, conflicting
    restatement rows, fiscal gaps, and accounting breaks.  Zero remains a real
    value; unavailable source evidence never becomes zero.
    """

    records, ticker, input_hash = _normalize_records(source)
    period_axis, axis_warnings = _period_axis(records)
    line_registry = validate_line_item_registry(
        tuple(registry) if registry is not None else professional_line_item_registry()
    )
    tolerance_map = dict(DEFAULT_TOLERANCES)
    if tolerances:
        tolerance_map.update({key: float(value) for key, value in tolerances.items()})

    resolved_by_key: dict[str, list[_ResolvedValue]] = {}
    for spec in line_registry:
        direct = _direct_values(spec, records, period_axis) if spec.source_mappings else None
        resolved_by_key[spec.canonical_key] = (
            direct
            if direct is not None
            else _derived_values(spec, period_axis, resolved_by_key)
        )

    series_by_section: dict[str, list[LineSeries]] = {}
    lineage: list[HistoricalPeriodLineage] = []
    for spec in line_registry:
        resolved = resolved_by_key[spec.canonical_key]
        methods = {item.lineage.method_id for item in resolved}
        method_id = next(iter(methods)) if len(methods) == 1 else "historical:mixed"
        series_by_section.setdefault(spec.statement_or_schedule, []).append(
            LineSeries(
                line_key=spec.canonical_key,
                method_id=method_id,
                values=tuple(item.period_value for item in resolved),
            )
        )
        lineage.extend(item.lineage for item in resolved)

    downstream_by_key: dict[str, list[str]] = {
        spec.canonical_key: [] for spec in line_registry
    }
    for spec in line_registry:
        for dependency in spec.dependencies:
            downstream_by_key[dependency].append(spec.canonical_key)
    lineage = [
        replace(
            item,
            downstream_dependencies=tuple(sorted(downstream_by_key[item.canonical_key])),
        )
        for item in lineage
    ]
    statements = tuple(
        StatementResult(statement_key=section, lines=tuple(lines))
        for section, lines in series_by_section.items()
        if section in PRIMARY_STATEMENTS
    )
    schedules = tuple(
        ScheduleResult(schedule_key=section, lines=tuple(lines))
        for section, lines in series_by_section.items()
        if section not in PRIMARY_STATEMENTS
    )

    checks = _accounting_checks(period_axis, resolved_by_key, tolerance_map)
    required_direct = [
        spec
        for spec in line_registry
        if spec.required and spec.source_mappings and spec.statement_or_schedule not in SOURCE_DEPENDENT_SECTIONS
    ]
    required_direct_cells = len(required_direct) * len(period_axis.periods)
    required_direct_available = sum(
        1
        for spec in required_direct
        for item in resolved_by_key[spec.canonical_key]
        if item.lineage.method_id == "historical:direct"
        and item.period_value.state.status is AvailabilityStatus.AVAILABLE
    )
    direct_gap = required_direct_cells - required_direct_available
    checks.append(
        CheckResult(
            check_id="coverage:consolidated_direct",
            status=CheckStatus.PASS if direct_gap == 0 else CheckStatus.FAIL,
            difference=float(direct_gap),
            tolerance=tolerance_map["coverage"],
            message=("All required direct historical cells are source-backed" if direct_gap == 0 else f"{direct_gap} required direct cells are missing"),
        )
    )
    expected_typed = len(line_registry) * len(period_axis.periods)
    checks.append(
        CheckResult(
            check_id="coverage:registry_typed",
            status=CheckStatus.PASS,
            difference=float(expected_typed - len(lineage)),
            tolerance=tolerance_map["coverage"],
            message="Every registry line has a typed state on the complete period axis",
        )
    )
    source_dependent_gaps = sum(
        1
        for spec in line_registry
        if spec.required and spec.statement_or_schedule in SOURCE_DEPENDENT_SECTIONS
        and any(
            item.period_value.state.status is not AvailabilityStatus.AVAILABLE
            for item in resolved_by_key[spec.canonical_key]
        )
    )
    checks.append(
        CheckResult(
            check_id="coverage:source_dependent",
            status=CheckStatus.BLOCKED if source_dependent_gaps else CheckStatus.PASS,
            difference=float(source_dependent_gaps),
            tolerance=tolerance_map["coverage"],
            message=(
                f"{source_dependent_gaps} required source-dependent modules remain unavailable"
                if source_dependent_gaps
                else "All required source-dependent modules are available"
            ),
        )
    )

    failed_checks = [check.check_id for check in checks if check.status is CheckStatus.FAIL]
    blockers: list[str] = []
    if direct_gap:
        blockers.append("required_direct_history_missing")
    blockers.extend(f"accounting_check_failed:{check_id}" for check_id in failed_checks if not check_id.startswith("coverage:"))
    if source_dependent_gaps:
        blockers.append("source_dependent_modules_unavailable")
    if direct_gap or any(item.startswith("accounting_check_failed:") for item in blockers):
        state = _unavailable(
            AvailabilityStatus.BLOCKING,
            "historical_integrity_blocked",
            "Required history is missing or one or more accounting checks failed",
        )
    elif source_dependent_gaps:
        state = _unavailable(
            AvailabilityStatus.PM_REQUIRED,
            "source_dependent_modules_unavailable",
            "Consolidated history is usable, but segment/source-dependent modules remain gated",
        )
    else:
        state = _available()

    all_tolerances = {check.check_id: float(check.tolerance or 0.0) for check in checks}
    warnings = list(axis_warnings)
    unavailable_optional = sum(
        1
        for spec in line_registry
        if not spec.required
        for item in resolved_by_key[spec.canonical_key]
        if item.period_value.state.status is not AvailabilityStatus.AVAILABLE
    )
    if unavailable_optional:
        warnings.append(f"{unavailable_optional} optional historical cells remain typed unavailable.")
    result = ModelResult(
        scenario_key="historical_actual",
        state=state,
        period_axis=period_axis,
        statements=statements,
        supporting_schedules=schedules,
        check_results=tuple(checks),
        tolerances=all_tolerances,
        warnings=tuple(warnings),
        blockers=tuple(blockers),
        input_hash=input_hash,
    )

    direct_count = sum(item.method_id == "historical:direct" for item in lineage)
    derived_count = sum(item.method_id == "historical:derived" for item in lineage)
    unavailable_count = len(lineage) - direct_count - derived_count
    coverage = HistoricalCoverageSummary(
        registry_line_count=len(line_registry),
        period_count=len(period_axis.periods),
        typed_cell_count=len(lineage),
        direct_cell_count=direct_count,
        derived_cell_count=derived_count,
        unavailable_cell_count=unavailable_count,
        required_direct_cell_count=required_direct_cells,
        required_direct_available_count=required_direct_available,
        source_dependent_gap_count=source_dependent_gaps,
    )
    limitations = (
        "Quarterly, NTM, calendar-year, and mixed-period facts are excluded from the annual/LTM axis.",
        "Segment history is never inferred from consolidated financial-statement rows.",
        "Consensus history remains unavailable unless a separately governed estimate source is supplied.",
        "The first displayed period cannot show prior-period working-capital or beginning-PP&E values without an earlier source year.",
    )
    return HistoricalFinancialModel(
        ticker=ticker,
        engine_version=HISTORICAL_ENGINE_VERSION,
        registry_version=REGISTRY_VERSION,
        registry=line_registry,
        result=result,
        lineage=tuple(lineage),
        coverage=coverage,
        limitations=limitations,
    )


def build_historical_financial_model_from_sqlite(
    db_path: str | Path,
    *,
    ticker: str = "MSFT",
    run_id: int | None = None,
    registry: Sequence[LineItemSpec] | None = None,
    tolerances: Mapping[str, float] | None = None,
) -> HistoricalFinancialModel:
    """Read exact v2 source facts from a cache DB without mutating it."""

    path = Path(db_path).resolve()
    uri = f"file:{path.as_posix()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row
    try:
        selected_run = run_id
        if selected_run is None:
            row = connection.execute(
                """
                SELECT r.id
                FROM ciq_ingest_runs r
                WHERE UPPER(r.ticker) = UPPER(?)
                  AND r.status = 'completed'
                  AND EXISTS (
                      SELECT 1 FROM ciq_source_facts_v2 f WHERE f.run_id = r.id
                  )
                ORDER BY r.id DESC
                LIMIT 1
                """,
                [ticker],
            ).fetchone()
            if row is None:
                raise HistoricalModelError(f"no completed v2 source-fact run for {ticker.upper()}")
            selected_run = int(row["id"])
        rows = [
            dict(row)
            for row in connection.execute(
                """
                SELECT *
                FROM ciq_source_facts_v2
                WHERE run_id = ? AND UPPER(ticker) = UPPER(?)
                ORDER BY sheet_name, row_index, column_index
                """,
                [selected_run, ticker],
            ).fetchall()
        ]
    finally:
        connection.close()
    if not rows:
        raise HistoricalModelError(
            f"no v2 source facts for {ticker.upper()} run {selected_run}"
        )
    return build_historical_financial_model(
        rows,
        registry=registry,
        tolerances=tolerances,
    )


__all__ = [
    "AmbiguousHistoricalSourceError",
    "HISTORICAL_ENGINE_VERSION",
    "HistoricalCoverageSummary",
    "HistoricalFinancialModel",
    "HistoricalModelError",
    "HistoricalPeriodLineage",
    "HistoricalSourceReference",
    "IncompleteHistoricalAxisError",
    "build_historical_financial_model",
    "build_historical_financial_model_from_sqlite",
]
