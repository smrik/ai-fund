"""Cache-only adapter from model engines to the professional workbook payload.

The adapter is intentionally a strict boundary.  It binds one workbook hash,
one CIQ ingest run, one explicit valuation JSON path, source-backed historical
lineage, and a complete three-scenario forecast bundle.  It never follows a
``latest`` alias, calls the network, recalculates Excel, or rewrites the source
workbook.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, timedelta
import json
import math
from pathlib import Path
import sqlite3
from typing import Any, Iterable, Mapping, Sequence

from src.contracts.professional_financial_model import (
    AvailabilityState,
    AvailabilityStatus,
    ConsensusSnapshot,
    DependencyScope,
    DriverApprovalRecord,
    DriverApprovalState,
    DriverGroup,
    FactFormulaStatus,
    ModuleBlocker,
    ModuleWorkflow,
    PeriodType,
    SourcePresentationRecord,
    UnitKind,
    WorkbookManifest,
    WorkflowGate,
    aggregate_package_workflow,
)
from src.stage_02_valuation.integrated_financial_model import (
    HistoricalFinancialModel,
    HistoricalSourceReference,
    build_historical_financial_model_from_sqlite,
)
from src.stage_02_valuation.model_line_items import LineItemSpec
from src.stage_04_pipeline.professional_model_workbook import (
    ComparableCompany,
    HistoricalSourceCell,
    ModelLine,
    NormalizedProfessionalWorkbookPayload,
    ScenarioForecast,
    SourceWorkbookRun,
    TypedAvailability,
    render_professional_model_workbook,
)


SOURCE_DEPENDENT_SECTIONS = frozenset({"segment_build", "consensus_bridge"})
SHEET_BY_SECTION: Mapping[str, str] = {
    "income_statement": "Income_Statement",
    "balance_sheet": "Balance_Sheet",
    "cash_flow": "Cash_Flow",
    "working_capital": "Working_Capital",
    "ppe_intangibles": "PP&E_Intangibles",
    "debt_cash_interest": "Debt_Cash_Interest",
    "capital_allocation": "Capital_Allocation",
    "taxes": "Taxes",
    "segment_build": "Segment_Build",
    "consensus_bridge": "Consensus_Bridge",
    "shares_eps": "Shares_EPS",
}

# The renderer's initial DCF/check contract predates the canonical registry.
# These aliases are additive: every non-source-dependent canonical registry
# line remains present alongside the small renderer compatibility projection.
CORE_RENDERER_ALIASES: Mapping[str, str] = {
    "revenue": "is.revenue",
    "ebit": "is.ebit",
    "depreciation_amortization": "cf.da",
    "capex": "cf.capex",
    "change_in_net_working_capital": "wc.change_nwc",
    "total_assets": "bs.total_assets",
    "total_liabilities_and_equity": "bs.total_liabilities_equity",
    "cash": "bs.cash",
    "ending_cash": "bs.cash",
}

ALIAS_LABELS: Mapping[str, str] = {
    "revenue": "Revenue (DCF alias)",
    "ebit": "EBIT (DCF alias)",
    "depreciation_amortization": "Depreciation & amortization (DCF alias)",
    "capex": "Capital expenditures (DCF alias)",
    "change_in_net_working_capital": "Change in net working capital (DCF alias)",
    "total_assets": "Total assets (check alias)",
    "total_liabilities_and_equity": "Total liabilities and equity (check alias)",
    "cash": "Balance-sheet cash (check alias)",
    "ending_cash": "Ending cash (cash-flow check alias)",
}


# These values are frozen legacy cross-checks only.  They are deliberately
# method-specific: the adapter never imports the legacy blended comps value,
# probability-weighted value, target, or recommendation into model inputs.
LEGACY_DIAGNOSTIC_VALUATION_FIELDS: Mapping[str, str] = {
    "diagnostic_comps_ev_ebitda_per_share": "comps_iv_ev_ebitda",
    "diagnostic_comps_ev_ebit_per_share": "comps_iv_ev_ebit",
    "diagnostic_comps_pe_per_share": "comps_iv_pe",
    "diagnostic_economic_profit_per_share": "ep_iv_base",
    "diagnostic_v1_gordon_per_share": "iv_gordon",
    "diagnostic_v1_exit_per_share": "iv_exit",
    "diagnostic_reverse_dcf_implied_growth_pct_points": "implied_growth_pct",
}


# Enterprise-to-equity bridge evidence must come from the exact current-period
# historical lines.  Keeping reported debt, borrowings, and leases separate
# avoids silently conflating different claim definitions.
BRIDGE_VALUATION_LINES: Mapping[str, str] = {
    "bridge_cash": "bs.cash",
    "bridge_short_term_investments": "bs.short_term_investments",
    "bridge_long_term_investments": "bs.long_term_investments",
    "bridge_gross_debt": "bs.total_debt",
    "bridge_short_term_borrowings": "bs.short_term_borrowings",
    "bridge_current_long_term_debt": "bs.current_long_term_debt",
    "bridge_long_term_debt": "bs.long_term_debt",
    "bridge_current_lease_liabilities": "bs.current_lease_liabilities",
    "bridge_long_term_lease_liabilities": "bs.long_term_leases",
    "bridge_lease_liabilities": "debt.lease_liabilities",
    "bridge_minority_interest": "bs.minority_interest",
    "bridge_pension_liability": "bs.pension_liability",
}

BORROWING_COMPONENT_LINES = (
    "bs.short_term_borrowings",
    "bs.current_long_term_debt",
    "bs.long_term_debt",
)


class ProfessionalModelAdapterError(ValueError):
    """Raised when a source, run, forecast, or valuation binding is unsafe."""


@dataclass(frozen=True, slots=True)
class ProfessionalModelArtifacts:
    output_dir: Path
    workbook_path: Path
    manifest_path: Path
    payload: NormalizedProfessionalWorkbookPayload
    manifest: WorkbookManifest


def _mapping(value: Any, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ProfessionalModelAdapterError(f"{field_name} must be an object")
    return value


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _first_not_none(*values: float | None) -> float | None:
    for value in values:
        if value is not None:
            return value
    return None


def _safe_ratio(numerator: float, denominator: float) -> float:
    if denominator == 0.0:
        return 0.0
    return numerator / denominator


def _iso_date(value: Any, field_name: str) -> date:
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError as exc:
        raise ProfessionalModelAdapterError(f"{field_name} is not an ISO date") from exc


def _normalize_scenario_key(value: Any) -> str:
    key = str(value or "").strip().lower()
    aliases = {"bull": "upside", "bear": "downside"}
    return aliases.get(key, key)


def _source_preflight(document: Mapping[str, Any]) -> Mapping[str, Any]:
    value = document.get("source_preflight")
    return _mapping(value, "valuation source_preflight")


def _driver_approval_records(
    document: Mapping[str, Any],
) -> tuple[DriverApprovalRecord, ...]:
    """Parse the explicit API approval packet; no other metadata implies approval."""

    raw = document.get("driver_approvals")
    if raw is None:
        return ()
    if isinstance(raw, Mapping):
        candidate = raw.get("records")
        if candidate is None:
            candidate = tuple(raw.values())
    else:
        candidate = raw
    if not isinstance(candidate, Sequence) or isinstance(candidate, (str, bytes)):
        raise ProfessionalModelAdapterError("driver_approvals must be a record list")
    records: list[DriverApprovalRecord] = []
    try:
        for item in candidate:
            if not isinstance(item, Mapping):
                raise ProfessionalModelAdapterError(
                    "driver approval entries must be objects"
                )
            records.append(DriverApprovalRecord.model_validate(item))
    except ValueError as exc:
        raise ProfessionalModelAdapterError(
            f"invalid driver approval record: {exc}"
        ) from exc
    identities = [
        (_normalize_scenario_key(record.scenario_key), record.driver_key)
        for record in records
    ]
    if len(set(identities)) != len(identities):
        raise ProfessionalModelAdapterError(
            "driver approvals contain duplicate scenario/driver identities"
        )
    return tuple(
        sorted(
            records,
            key=lambda record: (_normalize_scenario_key(record.scenario_key), record.driver_key),
        )
    )

def _validate_run_binding(
    *,
    ticker: str,
    requested_run_id: int,
    preflight: Mapping[str, Any],
    valuation_document: Mapping[str, Any],
) -> None:
    expected_ticker = ticker.upper().strip()
    if str(preflight.get("ticker") or "").upper() != expected_ticker:
        raise ProfessionalModelAdapterError("preflight ticker does not match requested ticker")
    source = _mapping(preflight.get("source"), "preflight source")
    if int(source.get("run_id") or 0) != requested_run_id:
        raise ProfessionalModelAdapterError("preflight run identity does not match requested run")
    if str(source.get("ingest_status") or "").lower() != "matched":
        raise ProfessionalModelAdapterError("preflight does not identify a matched ingest run")

    if str(valuation_document.get("ticker") or "").upper() != expected_ticker:
        raise ProfessionalModelAdapterError("valuation ticker does not match requested ticker")
    valuation_preflight = _source_preflight(valuation_document)
    valuation_source = _mapping(
        valuation_preflight.get("source"),
        "valuation source_preflight source",
    )
    if int(valuation_source.get("run_id") or 0) != requested_run_id:
        raise ProfessionalModelAdapterError("valuation run identity does not match requested run identity")
    source_hash = str(source.get("sha256") or "").lower()
    if str(valuation_source.get("sha256") or "").lower() != source_hash:
        raise ProfessionalModelAdapterError("valuation source hash does not match fresh preflight")

    lineage = valuation_document.get("ciq_lineage")
    if isinstance(lineage, Mapping):
        for key in ("snapshot_run_id", "comps_run_id"):
            value = lineage.get(key)
            if value is not None and int(value) != requested_run_id:
                raise ProfessionalModelAdapterError(
                    f"valuation {key} does not match requested run identity"
                )


def load_frozen_valuation_document(
    path: str | Path,
    *,
    ticker: str,
    requested_run_id: int,
    expected_source_hash: str | None = None,
) -> dict[str, Any]:
    """Load one explicit immutable valuation artifact; reject ``latest`` aliases."""

    source_path = Path(path).expanduser().resolve()
    if "latest" in source_path.stem.lower():
        raise ProfessionalModelAdapterError(
            "latest valuation aliases are prohibited; provide a timestamped frozen JSON"
        )
    if not source_path.is_file():
        raise ProfessionalModelAdapterError(f"valuation JSON does not exist: {source_path}")
    try:
        document = json.loads(source_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProfessionalModelAdapterError(f"invalid valuation JSON: {source_path}") from exc
    document = dict(_mapping(document, "valuation JSON"))
    if str(document.get("ticker") or "").upper() != ticker.upper().strip():
        raise ProfessionalModelAdapterError("valuation JSON ticker mismatch")
    source = _mapping(_source_preflight(document).get("source"), "valuation source")
    if int(source.get("run_id") or 0) != requested_run_id:
        raise ProfessionalModelAdapterError("valuation JSON run identity mismatch")
    if expected_source_hash is not None and str(source.get("sha256") or "").lower() != expected_source_hash.lower():
        raise ProfessionalModelAdapterError("valuation JSON source hash mismatch")
    return document


def _scenario_results(bundle: Any) -> dict[str, Any]:
    raw = getattr(bundle, "scenarios", None)
    if raw is None:
        raw = getattr(bundle, "scenario_results", None)
    if raw is None and isinstance(bundle, Mapping):
        raw = bundle.get("scenarios") or bundle.get("scenario_results")
    if isinstance(raw, Mapping):
        items: Iterable[tuple[Any, Any]] = raw.items()
    elif raw is not None:
        items = (
            (
                getattr(item, "scenario_key", getattr(getattr(item, "model", None), "scenario_key", None)),
                item,
            )
            for item in raw
        )
    else:
        raise ProfessionalModelAdapterError("forecast bundle exposes no scenario results")
    normalized: dict[str, Any] = {}
    for raw_key, result in items:
        key = _normalize_scenario_key(raw_key)
        if key in normalized:
            raise ProfessionalModelAdapterError(f"duplicate forecast scenario: {key}")
        normalized[key] = result
    required = {"base", "upside", "downside"}
    if set(normalized) != required:
        raise ProfessionalModelAdapterError(
            f"forecast scenarios must be exactly {sorted(required)}; got {sorted(normalized)}"
        )
    return normalized


def _forecast_model(result: Any) -> Any:
    return getattr(result, "model", result)


def _forecast_periods(result: Any) -> tuple[str, ...]:
    model = _forecast_model(result)
    axis = getattr(model, "period_axis", None)
    periods = getattr(axis, "periods", None)
    if periods is None:
        raise ProfessionalModelAdapterError("forecast result has no period axis")
    keys = tuple(str(period.key) for period in periods)
    if len(keys) != 5 or len(set(keys)) != 5:
        raise ProfessionalModelAdapterError("forecast result must contain five unique periods")
    return keys


def _forecast_line_index(result: Any) -> Mapping[str, Any]:
    line_index = getattr(result, "line_index", None)
    if isinstance(line_index, Mapping):
        return line_index
    model = _forecast_model(result)
    index: dict[str, Any] = {}
    for container in (
        *tuple(getattr(model, "statements", ())),
        *tuple(getattr(model, "supporting_schedules", ())),
    ):
        for line in container.lines:
            index[line.line_key] = line
    if not index:
        raise ProfessionalModelAdapterError("forecast result has no line index")
    return index


def _forecast_values(result: Any, key: str, periods: Sequence[str]) -> tuple[tuple[str, float | None], ...]:
    line = _forecast_line_index(result).get(key)
    if line is None:
        raise ProfessionalModelAdapterError(f"forecast line missing: {key}")
    values_by_period = {str(value.period_key): value for value in line.values}
    if set(values_by_period) != set(periods):
        raise ProfessionalModelAdapterError(f"forecast line {key} does not cover the five-year axis")
    output: list[tuple[str, float | None]] = []
    for period in periods:
        value = values_by_period[period]
        numeric = _number(value.value)
        if value.state.status is AvailabilityStatus.AVAILABLE and numeric is None:
            raise ProfessionalModelAdapterError(f"available forecast value is non-numeric: {key}/{period}")
        output.append((period, numeric if value.state.status is AvailabilityStatus.AVAILABLE else None))
    return tuple(output)


def _refs_for_line(
    historical: Any,
    specs: Mapping[str, LineItemSpec],
    key: str,
    period: str,
    *,
    visited: frozenset[str] = frozenset(),
) -> tuple[HistoricalSourceReference, ...]:
    if key in visited:
        return ()
    lineage = historical.period_lineage(key, period)
    refs = tuple(getattr(lineage, "source_refs", ()))
    if refs:
        return tuple(sorted(refs, key=lambda ref: ref.source_ref))
    spec = specs[key]
    collected: dict[str, HistoricalSourceReference] = {}
    for dependency in spec.dependencies:
        for ref in _refs_for_line(
            historical,
            specs,
            dependency,
            period,
            visited=visited | {key},
        ):
            collected[ref.source_ref] = ref
    return tuple(collected[key] for key in sorted(collected))


def _historical_cell(
    historical: Any,
    specs: Mapping[str, LineItemSpec],
    spec: LineItemSpec,
    period: str,
) -> HistoricalSourceCell:
    period_value = historical.value(spec.canonical_key, period)
    lineage = historical.period_lineage(spec.canonical_key, period)
    refs = _refs_for_line(historical, specs, spec.canonical_key, period)
    if not refs:
        if period_value.state.status is AvailabilityStatus.AVAILABLE:
            raise ProfessionalModelAdapterError(
                f"available historical line has no underlying source refs: {spec.canonical_key}/{period}"
            )
        period_type_value = getattr(lineage, "period_type", None)
        if hasattr(period_type_value, "value"):
            period_type_value = period_type_value.value
        reason_code = period_value.state.reason_code or "historical_value_unavailable"
        return HistoricalSourceCell(
            period_key=period,
            value=None,
            source_sheet=None,
            source_cell=None,
            source_row_id=f"unavailable:{spec.canonical_key}:{period}",
            source_formula=f"UNAVAILABLE {reason_code} | no source locator",
            formula_status="typed_unavailable",
            raw_value=getattr(lineage, "raw_source_value", None),
            normalized_value=None,
            derived_value=None,
            transformation_rule=str(
                getattr(lineage, "transformation_rule", None)
                or getattr(lineage, "normalization_rule", None)
                or getattr(lineage, "method_id", "historical:typed_unavailable")
            ),
            unit=getattr(lineage, "source_unit", None),
            unit_kind=getattr(lineage, "source_unit_kind", None),
            scale=_number(getattr(lineage, "source_scale", None)),
            currency=getattr(lineage, "source_currency", None),
            period_type=str(period_type_value) if period_type_value is not None else None,
            period_end=getattr(lineage, "period_end", None),
            formula_error=str(getattr(lineage, "formula_error", None) or "") or None,
            upstream_dependencies=tuple(getattr(lineage, "upstream_dependencies", ())),
            downstream_dependencies=tuple(getattr(lineage, "downstream_dependencies", ())),
        )
    primary = refs[0]
    if "!" in primary.cell_locator:
        locator_sheet, locator_cell = primary.cell_locator.rsplit("!", 1)
    else:
        locator_sheet, locator_cell = primary.sheet_name, primary.a1_locator
    method_id = str(getattr(lineage, "method_id", "historical:unknown"))
    formula_id = getattr(lineage, "formula_id", None)
    ref_ids = ",".join(ref.source_ref for ref in refs)
    if method_id == "historical:direct":
        source_formula = primary.formula_text
        formula_status = primary.formula_status
        source_row_id = primary.source_ref
    elif period_value.state.status is AvailabilityStatus.AVAILABLE:
        source_formula = f"DERIVED {formula_id or method_id} | underlying refs: {ref_ids}"
        formula_status = "derived_from_source"
        source_row_id = f"derived:{spec.canonical_key}:{period}|refs:{ref_ids}"
    else:
        source_formula = (
            f"UNAVAILABLE {period_value.state.reason_code or 'historical_value_unavailable'} | "
            f"available underlying refs: {ref_ids}"
        )
        formula_status = "typed_unavailable"
        source_row_id = f"unavailable:{spec.canonical_key}:{period}|refs:{ref_ids}"
    numeric_value = (
        _number(period_value.value)
        if period_value.state.status is AvailabilityStatus.AVAILABLE
        else None
    )
    raw_value = getattr(lineage, "raw_source_value", None)
    if raw_value is None:
        raw_value = getattr(primary, "raw_source_value", None)
    if raw_value is None:
        raw_value = getattr(primary, "source_value", None)
    normalized_value = getattr(lineage, "normalized_value", None)
    if normalized_value is None and method_id == "historical:direct":
        normalized_value = numeric_value
    derived_value = getattr(lineage, "derived_value", None)
    if derived_value is None and method_id != "historical:direct":
        derived_value = numeric_value
    period_type_value = getattr(lineage, "period_type", None)
    if hasattr(period_type_value, "value"):
        period_type_value = period_type_value.value
    formula_error = getattr(lineage, "formula_error", None) or getattr(
        primary,
        "formula_error",
        None,
    )
    transformation_rule = (
        getattr(lineage, "transformation_rule", None)
        or getattr(lineage, "normalization_rule", None)
        or method_id
    )
    return HistoricalSourceCell(
        period_key=period,
        value=numeric_value,
        source_sheet=locator_sheet,
        source_cell=locator_cell,
        source_row_id=source_row_id,
        source_formula=source_formula,
        formula_status=formula_status,
        raw_value=raw_value,
        normalized_value=_number(normalized_value),
        derived_value=_number(derived_value),
        transformation_rule=str(transformation_rule),
        unit=getattr(lineage, "source_unit", None) or getattr(primary, "unit", None),
        unit_kind=getattr(lineage, "source_unit_kind", None) or getattr(primary, "unit_kind", None),
        scale=_number(getattr(lineage, "source_scale", None) or getattr(primary, "scale", None)),
        currency=getattr(lineage, "source_currency", None) or getattr(primary, "currency", None),
        period_type=str(period_type_value) if period_type_value is not None else None,
        period_end=getattr(lineage, "period_end", None) or getattr(primary, "period_end", None),
        formula_error=str(formula_error) if formula_error else None,
        upstream_dependencies=tuple(getattr(lineage, "upstream_dependencies", ())),
        downstream_dependencies=tuple(getattr(lineage, "downstream_dependencies", ())),
    )


def _unit_for_key(key: str, currency: str) -> str:
    if key in {"wc.dso", "wc.dio", "wc.dpo"}:
        return "days"
    if key == "tax.effective_rate":
        return "%"
    if key == "shares.stock_compensation":
        return f"{currency} mm"
    if key.startswith("shares."):
        if key.endswith("eps") or key in {
            "shares.dividend_per_share",
            "shares.cash_dividend_per_share",
        }:
            return f"{currency}/share"
        return "mm shares"
    return f"{currency} mm"


def _model_lines(
    *,
    historical: Any,
    scenarios: Mapping[str, Any],
    forecast_periods: Sequence[str],
    currency: str,
) -> tuple[ModelLine, ...]:
    registry = tuple(historical.registry)
    specs = {spec.canonical_key: spec for spec in registry}
    lines: list[ModelLine] = []
    for spec in registry:
        if spec.statement_or_schedule in SOURCE_DEPENDENT_SECTIONS:
            historical_evidence_available = all(
                historical.value(spec.canonical_key, period).state.status
                is AvailabilityStatus.AVAILABLE
                and bool(_refs_for_line(historical, specs, spec.canonical_key, period))
                for period in historical.period_keys
            )
            forecast_evidence_available = True
            for result in scenarios.values():
                forecast_line = _forecast_line_index(result).get(spec.canonical_key)
                if forecast_line is None:
                    forecast_evidence_available = False
                    break
                values = {str(value.period_key): value for value in forecast_line.values}
                if set(values) != set(forecast_periods) or any(
                    values[period].state.status is not AvailabilityStatus.AVAILABLE
                    or _number(values[period].value) is None
                    for period in forecast_periods
                ):
                    forecast_evidence_available = False
                    break
            if not historical_evidence_available or not forecast_evidence_available:
                continue
        sheet = SHEET_BY_SECTION.get(spec.statement_or_schedule)
        if sheet is None:
            raise ProfessionalModelAdapterError(
                f"registry section has no workbook mapping: {spec.statement_or_schedule}"
            )
        historical_cells = tuple(
            _historical_cell(historical, specs, spec, period)
            for period in historical.period_keys
        )
        forecasts = tuple(
            ScenarioForecast(
                scenario_key=scenario,
                values=_forecast_values(result, spec.canonical_key, forecast_periods),
            )
            for scenario, result in scenarios.items()
        )
        lines.append(
            ModelLine(
                canonical_key=spec.canonical_key,
                label=spec.display_label,
                sheet=sheet,
                unit=_unit_for_key(spec.canonical_key, currency),
                historical=historical_cells,
                scenario_forecasts=forecasts,
            )
        )

    by_key = {line.canonical_key: line for line in lines}
    for alias, canonical in CORE_RENDERER_ALIASES.items():
        source = by_key[canonical]
        alias_history = tuple(
            replace(
                item,
                source_row_id=f"renderer_alias:{alias}->{canonical}|{item.source_row_id}",
                source_formula=(
                    f"RENDERER ALIAS {canonical} | "
                    + (item.source_formula or "source value; no source formula")
                ),
                formula_status=f"renderer_alias:{item.formula_status}",
            )
            for item in source.historical
        )
        lines.append(
            ModelLine(
                canonical_key=alias,
                label=ALIAS_LABELS[alias],
                sheet=source.sheet,
                unit=source.unit,
                historical=alias_history,
                scenario_forecasts=source.scenario_forecasts,
            )
        )
    return tuple(lines)


def _history_number(historical: Any, key: str) -> float | None:
    try:
        value = historical.value(key, historical.period_keys[-1])
    except KeyError:
        return None
    return _number(value.value) if value.state.status is AvailabilityStatus.AVAILABLE else None


def _history_sum(historical: Any, keys: Sequence[str]) -> float | None:
    values = tuple(_history_number(historical, key) for key in keys)
    if not values or any(value is None for value in values):
        return None
    return sum(value for value in values if value is not None)


def _valuation_inputs(
    *,
    valuation_date: date,
    historical: Any,
    document: Mapping[str, Any],
) -> dict[str, float | None]:
    market = _mapping(document.get("market"), "valuation market")
    assumptions = _mapping(document.get("assumptions"), "valuation assumptions")
    wacc = _mapping(document.get("wacc"), "valuation wacc")
    valuation = _mapping(document.get("valuation"), "valuation output")
    tax_rate = _number(assumptions.get("tax_rate_target_pct"))
    pre_tax_cost = _number(wacc.get("cost_of_debt"))
    if pre_tax_cost is None:
        after_tax = _number(wacc.get("cost_of_debt_after_tax"))
        if after_tax is not None and tax_rate is not None and tax_rate < 1.0:
            pre_tax_cost = after_tax / (1.0 - tax_rate)
    current_fdso = _number(market.get("current_fully_diluted_shares_mm"))
    if current_fdso is not None and current_fdso <= 0.0:
        current_fdso = None
    inputs = {
        "risk_free_rate": _number(wacc.get("risk_free_rate")),
        "beta": _first_not_none(
            _number(wacc.get("beta_raw")),
            _number(wacc.get("beta_relevered")),
        ),
        "equity_risk_premium": _number(wacc.get("equity_risk_premium")),
        "pre_tax_cost_of_debt": pre_tax_cost,
        "size_premium": _number(wacc.get("size_premium")),
        "backend_selected_wacc": _number(wacc.get("wacc")),
        "backend_cost_of_equity": _number(wacc.get("cost_of_equity")),
        "backend_debt_weight": _number(wacc.get("debt_weight")),
        "backend_equity_weight": _number(wacc.get("equity_weight")),
        "tax_rate": tax_rate,
        "debt_value": _history_number(historical, "bs.total_debt"),
        "equity_value": _number(market.get("market_cap_mm")),
        "terminal_growth": _number(assumptions.get("growth_terminal_pct")),
        "net_debt": _first_not_none(
            _history_number(historical, "bs.net_debt"),
            _number(assumptions.get("net_debt_mm")),
        ),
        "current_basic_shares": _number(assumptions.get("shares_outstanding_mm")),
        "current_fully_diluted_shares": (
            current_fdso
            if str(market.get("current_fully_diluted_shares_as_of") or "")
            == valuation_date.isoformat()
            else None
        ),
        "current_price": _number(market.get("price")),
    }
    inputs.update(
        {
            input_key: _number(valuation.get(source_field))
            for input_key, source_field in LEGACY_DIAGNOSTIC_VALUATION_FIELDS.items()
        }
    )
    inputs.update(
        {
            input_key: _history_number(historical, canonical_line)
            for input_key, canonical_line in BRIDGE_VALUATION_LINES.items()
        }
    )
    inputs["bridge_total_borrowings"] = _history_sum(
        historical,
        BORROWING_COMPONENT_LINES,
    )

    raw_bridge = document.get("forecast_bridge")
    first_bridge = (
        raw_bridge[0]
        if isinstance(raw_bridge, Sequence)
        and not isinstance(raw_bridge, (str, bytes))
        and raw_bridge
        and isinstance(raw_bridge[0], Mapping)
        else {}
    )
    raw_stub_bridge = first_bridge.get("fcff_stub_bridge")
    stub_bridge = raw_stub_bridge if isinstance(raw_stub_bridge, Mapping) else {}
    try:
        stub_start = _iso_date(first_bridge.get("stub_start"), "stub_start")
        stub_end = _iso_date(first_bridge.get("period_end"), "period_end")
    except ProfessionalModelAdapterError:
        stub_start = None
        stub_end = None

    if stub_start is not None and stub_end is not None and stub_start <= stub_end:
        periods: list[tuple[date, date]] = [(stub_start, stub_end)]
        annual_start = stub_end + timedelta(days=1)
        for _ in range(4):
            annual_end = date(
                annual_start.year + 1,
                annual_start.month,
                annual_start.day,
            ) - timedelta(days=1)
            periods.append((annual_start, annual_end))
            annual_start = annual_end + timedelta(days=1)
        for index, (period_start, period_end) in enumerate(periods, start=1):
            midpoint_days = (
                (period_start - valuation_date).days
                + (period_end - valuation_date).days
            ) / 2.0
            inputs[f"dcf_discount_exponent_{index}"] = midpoint_days / 365.0
        inputs["dcf_terminal_discount_exponent"] = (
            periods[-1][1] - valuation_date
        ).days / 365.0
    else:
        for index in range(1, 6):
            inputs[f"dcf_discount_exponent_{index}"] = None
        inputs["dcf_terminal_discount_exponent"] = None

    for scenario in ("base", "upside", "downside"):
        bridge_item = stub_bridge.get(scenario)
        item = bridge_item if isinstance(bridge_item, Mapping) else {}
        annual_fcff = _number(item.get("annual_fcff"))
        ytd_fcff = _number(item.get("ytd_fcff"))
        stub_fcff = _number(item.get("stub_fcff"))
        tolerance = _first_not_none(_number(item.get("tolerance")), 0.1)
        reconciled = (
            annual_fcff is not None
            and ytd_fcff is not None
            and stub_fcff is not None
            and abs(annual_fcff - ytd_fcff - stub_fcff) <= tolerance
        )
        inputs[f"dcf_annual_fy26_fcff_{scenario}"] = annual_fcff if reconciled else None
        inputs[f"dcf_ytd_fcff_{scenario}"] = ytd_fcff if reconciled else None
        inputs[f"dcf_stub_fcff_{scenario}"] = stub_fcff if reconciled else None

    governance_raw = document.get("dcf_scenario_governance")
    governance = governance_raw if isinstance(governance_raw, Mapping) else {}
    for scenario in ("base", "upside", "downside"):
        raw_item = governance.get(scenario)
        item = raw_item if isinstance(raw_item, Mapping) else {}
        inputs[f"dcf_wacc_{scenario}"] = _number(item.get("wacc"))
        inputs[f"dcf_terminal_growth_{scenario}"] = _number(
            item.get("terminal_growth")
        )
        inputs[f"dcf_nopat_tax_rate_{scenario}"] = _number(
            item.get("tax_rate")
        )
    return inputs


def _check_payload(
    *,
    preflight: Mapping[str, Any],
    historical: Any,
    scenarios: Mapping[str, Any],
    valuation_document: Mapping[str, Any],
    valuation_source_path: Path,
) -> tuple[dict[str, float | int | str | None], tuple[str, ...], tuple[str, ...]]:
    preflight_workbook = _mapping(preflight.get("workbook"), "preflight workbook")
    formula_errors = int(preflight_workbook.get("formula_error_count") or 0)
    backend: dict[str, float | int | str | None] = {
        "source.formula_error_count": formula_errors,
        "valuation.source_path": str(valuation_source_path),
    }
    blockers = {str(item) for item in preflight.get("blockers", ()) if str(item)}
    scenario_control = valuation_document.get("scenario_control")
    scenario_control_map = (
        scenario_control if isinstance(scenario_control, Mapping) else {}
    )
    formula_first_pass = (
        str(scenario_control_map.get("formula_first_gate") or "").upper() == "PASS"
    )
    policy_pass = (
        str(scenario_control_map.get("policy_gate") or "").upper() == "PASS"
        and bool(scenario_control_map.get("approval_ref"))
        and bool(scenario_control_map.get("current_input_hash"))
    )
    backend["scenario.formula_first_gate"] = (
        "PASS" if formula_first_pass else "BLOCKED"
    )
    backend["scenario.policy_gate"] = "PASS" if policy_pass else "BLOCKED"
    if not formula_first_pass:
        blockers.add("scenario_formula_first_control_absent")
    if not policy_pass:
        blockers.add("pm_approval_required:scenario:policy_matrix")

    raw_formula_error_records = preflight_workbook.get("errors", ())
    formula_error_records: list[tuple[str, str, str]] = []
    if isinstance(raw_formula_error_records, Sequence) and not isinstance(
        raw_formula_error_records,
        (str, bytes),
    ):
        for record in raw_formula_error_records:
            if not isinstance(record, Mapping):
                continue
            sheet = str(record.get("sheet") or "").strip()
            cell = str(record.get("cell") or "").strip().upper()
            if not sheet or not cell:
                continue
            formula_error_records.append(
                (sheet, cell, str(record.get("kind") or "formula_error"))
            )
    backend["source.formula_error_cells"] = ",".join(
        f"{sheet}!{cell}" for sheet, cell, _kind in formula_error_records
    )
    backend["source.formula_error_records_exposed"] = len(formula_error_records)
    backend["source.formula_errors_truncated"] = int(
        bool(preflight_workbook.get("errors_truncated"))
    )
    for index, (sheet, cell, kind) in enumerate(formula_error_records, start=1):
        prefix = f"source.formula_error.{index:03d}"
        backend[f"{prefix}.cell"] = f"{sheet}!{cell}"
        backend[f"{prefix}.kind"] = kind

    if formula_errors:
        blockers.add(f"source_formula_errors:{formula_errors}")
    for blocker in getattr(historical.result, "blockers", ()):
        blockers.add(f"historical:{blocker}")
    for check in getattr(historical.result, "check_results", ()):
        backend[f"historical.{check.check_id}.status"] = check.status.value
        if check.difference is not None:
            backend[f"historical.{check.check_id}.difference"] = check.difference

    for scenario, result in scenarios.items():
        model = _forecast_model(result)
        for blocker in getattr(model, "blockers", ()):
            blockers.add(str(blocker))
        for check in getattr(model, "check_results", ()):
            backend[f"forecast.{scenario}.{check.check_id}.status"] = check.status.value
            if check.difference is not None:
                backend[f"forecast.{scenario}.{check.check_id}.difference"] = check.difference

    base_result = scenarios["base"]
    first_forecast_period = _forecast_periods(base_result)[0]
    base_index = _forecast_line_index(base_result)
    ltm_period = historical.period_keys[-1]
    for key in ("is.revenue", "is.ebit"):
        forecast_value = next(
            value
            for value in base_index[key].values
            if value.period_key == first_forecast_period
        )
        ltm_value = historical.value(key, ltm_period)
        forecast_numeric = _number(forecast_value.value)
        ltm_numeric = _number(ltm_value.value)
        if forecast_numeric is not None and ltm_numeric is not None:
            check_key = key.replace(".", "_")
            backend[
                f"forecast.base.{first_forecast_period}.{check_key}_vs_ltm_delta"
            ] = forecast_numeric - ltm_numeric
            backend[
                f"forecast.base.{first_forecast_period}.{check_key}_vs_ltm_pct"
            ] = _safe_ratio(forecast_numeric - ltm_numeric, ltm_numeric)

    wacc = _mapping(valuation_document.get("wacc"), "valuation wacc")
    quality = str(wacc.get("quality_status") or "unknown")
    missing_inputs_raw = wacc.get("missing_inputs", ())
    if isinstance(missing_inputs_raw, Sequence) and not isinstance(
        missing_inputs_raw,
        (str, bytes),
    ):
        missing_inputs = tuple(str(item) for item in missing_inputs_raw if str(item))
    elif missing_inputs_raw:
        missing_inputs = (str(missing_inputs_raw),)
    else:
        missing_inputs = ()
    backend["wacc.quality_status"] = quality
    backend["wacc.missing_inputs"] = ",".join(missing_inputs)
    backend["wacc.missing_input_count"] = len(missing_inputs)
    if quality not in {"source_backed", "available", "complete"}:
        blockers.add(f"wacc_degraded:{quality}")
        backend["wacc.approval_state"] = "BLOCKED_DEGRADED_INPUTS"
    else:
        backend["wacc.approval_state"] = "EVIDENCE_COMPLETE"

    if _number(wacc.get("cost_of_debt")) is None and _number(
        wacc.get("cost_of_debt_after_tax")
    ) is not None:
        blockers.add("wacc_degraded:unsupported_after_tax_cost_of_debt_reverse_engineering")
    if _number(wacc.get("beta_raw")) is None:
        blockers.add("wacc_degraded:beta_source_window_benchmark_or_peer_regression_absent")
    for key in ("risk_free_rate", "equity_risk_premium"):
        if not wacc.get(f"{key}_source") or not wacc.get(f"{key}_as_of_date"):
            blockers.add(f"wacc_degraded:{key}_source_or_date_absent")
    backend["wacc.debt_basis"] = str(
        wacc.get("debt_basis") or "book_total_debt_including_leases_unapproved"
    )
    backend["wacc.lease_treatment"] = str(
        wacc.get("lease_treatment") or "unapproved"
    )
    method_availability = valuation_document.get("method_availability")
    fcfe_metadata: Mapping[str, Any] = {}
    if isinstance(method_availability, Mapping):
        candidate = method_availability.get("fcfe")
        if isinstance(candidate, Mapping):
            fcfe_metadata = candidate
    fcfe_state = str(fcfe_metadata.get("status") or "unavailable").upper()
    backend["fcfe.state"] = fcfe_state
    backend["fcfe.reason_code"] = str(
        fcfe_metadata.get("reason_code") or "fcfe_method_evidence_not_provided"
    )
    backend["fcfe.detail"] = str(
        fcfe_metadata.get("detail")
        or "No source-backed FCFE method-availability detail was supplied."
    )
    backend["fcfe.source_legacy_value_omitted"] = int(
        bool(fcfe_metadata.get("legacy_value_omitted"))
    )

    valuation = _mapping(valuation_document.get("valuation"), "valuation output")
    fcfe_legacy_value_present = _number(valuation.get("fcfe_iv_base")) is not None
    backend["fcfe.legacy_value_present"] = int(fcfe_legacy_value_present)
    backend["fcfe.legacy_value_state"] = (
        "OMITTED_NON_APPROVED" if fcfe_legacy_value_present else "NOT_PRESENT"
    )

    current_period = historical.period_keys[-1]
    for input_key, canonical_line in BRIDGE_VALUATION_LINES.items():
        component = input_key.removeprefix("bridge_")
        prefix = f"valuation_bridge.{component}"
        backend[f"{prefix}.source_line"] = canonical_line
        backend[f"{prefix}.period"] = current_period
        backend[f"{prefix}.state"] = (
            "AVAILABLE"
            if _history_number(historical, canonical_line) is not None
            else "UNAVAILABLE"
        )

    total_borrowings = _history_sum(historical, BORROWING_COMPONENT_LINES)
    backend["valuation_bridge.total_borrowings.source_lines"] = ",".join(
        BORROWING_COMPONENT_LINES
    )
    backend[
        "valuation_bridge.total_borrowings.derivation"
    ] = "SUM_EXACT_CURRENT_LINES"
    backend["valuation_bridge.total_borrowings.period"] = current_period
    backend["valuation_bridge.total_borrowings.state"] = (
        "AVAILABLE" if total_borrowings is not None else "UNAVAILABLE"
    )

    gross_debt = _history_number(historical, "bs.total_debt")
    lease_liabilities = _history_number(historical, "debt.lease_liabilities")
    backend["valuation_bridge.claims_tie.tolerance"] = 0.1
    if gross_debt is None or total_borrowings is None or lease_liabilities is None:
        backend["valuation_bridge.claims_tie.status"] = "UNAVAILABLE"
    else:
        claims_tie = gross_debt - total_borrowings - lease_liabilities
        backend["valuation_bridge.claims_tie.difference"] = claims_tie
        backend["valuation_bridge.claims_tie.status"] = (
            "PASS" if abs(claims_tie) <= 0.1 else "FAIL"
        )
        if abs(claims_tie) > 0.1:
            blockers.add(f"valuation_bridge_claims_tie:{claims_tie:.6f}")

    current_leases = _history_number(historical, "bs.current_lease_liabilities")
    long_term_leases = _history_number(historical, "bs.long_term_leases")
    backend["valuation_bridge.lease_liabilities_tie.tolerance"] = 0.1
    if (
        lease_liabilities is None
        or current_leases is None
        or long_term_leases is None
    ):
        backend["valuation_bridge.lease_liabilities_tie.status"] = "UNAVAILABLE"
    else:
        lease_tie = lease_liabilities - current_leases - long_term_leases
        backend["valuation_bridge.lease_liabilities_tie.difference"] = lease_tie
        backend["valuation_bridge.lease_liabilities_tie.status"] = (
            "PASS" if abs(lease_tie) <= 0.1 else "FAIL"
        )
        if abs(lease_tie) > 0.1:
            blockers.add(f"valuation_bridge_lease_liabilities_tie:{lease_tie:.6f}")

    diagnostic_model_state = "BLOCKED_BY_MODEL" if blockers else "NOT_MODEL_APPROVED"
    present_diagnostics: list[str] = []
    for input_key, source_field in LEGACY_DIAGNOSTIC_VALUATION_FIELDS.items():
        diagnostic = input_key.removeprefix("diagnostic_")
        prefix = f"valuation.legacy_diagnostic.{diagnostic}"
        is_present = _number(valuation.get(source_field)) is not None
        if is_present:
            present_diagnostics.append(input_key)
        backend[f"{prefix}.source_field"] = source_field
        backend[f"{prefix}.unit"] = (
            "PERCENTAGE_POINTS"
            if source_field == "implied_growth_pct"
            else "CURRENCY_PER_SHARE"
        )
        backend[f"{prefix}.availability"] = "AVAILABLE" if is_present else "UNAVAILABLE"
        backend[f"{prefix}.approval_state"] = "NON_APPROVED"
        backend[f"{prefix}.model_state"] = diagnostic_model_state
    backend["valuation.legacy_diagnostics.approval_state"] = "NON_APPROVED"
    backend["valuation.legacy_diagnostics.model_state"] = diagnostic_model_state
    backend[
        "valuation.legacy_diagnostics.decision_use"
    ] = "DIAGNOSTIC_ONLY_NO_DECISION_OUTPUT"
    backend["valuation.legacy_diagnostics.present_inputs"] = ",".join(
        present_diagnostics
    )
    backend["fcfe.legacy_value_model_state"] = diagnostic_model_state

    warnings = {
        "segments_unavailable",
        "consensus_unavailable",
        "sotp_unavailable",
    }
    if fcfe_state != "AVAILABLE":
        warnings.add("fcfe_unavailable")
    else:
        warnings.add("fcfe_legacy_method_non_approved")
    if present_diagnostics or fcfe_legacy_value_present:
        warnings.add("legacy_valuation_diagnostics_non_approved")
        if blockers:
            warnings.add("legacy_valuation_diagnostics_model_blocked")
    if "expected_iv" in valuation or valuation_document.get("scenarios"):
        warnings.add("probability_weighted_v1_outputs_ignored")
    source_pass = (
        formula_errors == 0
        and not tuple(preflight.get("blockers", ()))
        and str(preflight.get("status") or "").lower() in {"ready", "ok", "full"}
    )
    historical_gates = tuple(
        WorkflowGate(
            gate_id=f"historical:{check.check_id}",
            module_id="historical",
            reported_status=check.status.value,
        )
        for check in getattr(historical.result, "check_results", ())
    ) or (
        WorkflowGate(
            gate_id="historical:evidence",
            module_id="historical",
            reported_status=None,
        ),
    )
    forecast_gates: list[WorkflowGate] = []
    for scenario, result in scenarios.items():
        model = _forecast_model(result)
        checks = tuple(getattr(model, "check_results", ()))
        if checks:
            forecast_gates.extend(
                WorkflowGate(
                    gate_id=f"forecast:{scenario}:{check.check_id}",
                    module_id="forecast",
                    reported_status=check.status.value,
                )
                for check in checks
            )
    pm_required = any(item.startswith("pm_approval_required:") for item in blockers)
    forecast_gates.append(
        WorkflowGate(
            gate_id="forecast:driver_approvals",
            module_id="forecast",
            reported_status="NEEDS_PM_REVIEW" if pm_required else "PASS",
        )
    )
    valuation_gate_status = (
        "PASS"
        if quality in {"source_backed", "available", "complete"}
        else "NEEDS_PM_REVIEW"
    )
    modules = (
        ModuleWorkflow(
            module_id="source",
            gates=(
                WorkflowGate(
                    gate_id="source:preflight",
                    module_id="source",
                    reported_status="PASS" if source_pass else "BLOCKED",
                ),
            ),
        ),
        ModuleWorkflow(module_id="historical", gates=historical_gates),
        ModuleWorkflow(module_id="forecast", gates=tuple(forecast_gates)),
        ModuleWorkflow(
            module_id="valuation",
            gates=(
                WorkflowGate(
                    gate_id="valuation:wacc_quality",
                    module_id="valuation",
                    reported_status=valuation_gate_status,
                ),
            ),
        ),
        ModuleWorkflow(
            module_id="calculation",
            gates=(
                WorkflowGate(
                    gate_id="calculation:verification",
                    module_id="calculation",
                    reported_status=None,
                ),
            ),
        ),
        ModuleWorkflow(
            module_id="optional_evidence",
            gates=(
                WorkflowGate(
                    gate_id="optional_evidence:segments_consensus_sotp",
                    module_id="optional_evidence",
                    reported_status="PARTIAL",
                ),
            ),
            required_for_package_full=True,
        ),
    )
    workflow_blockers = (
        (
            ModuleBlocker(
                blocker_id="source_preflight_unproven_scope",
                module_id="source",
                scope=DependencyScope.UNPROVEN,
            ),
        )
        if not source_pass
        else ()
    )
    package_workflow = aggregate_package_workflow(modules, blockers=workflow_blockers)
    backend["workflow.package.state"] = package_workflow.state.value
    backend["workflow.package.global_blockers"] = ",".join(package_workflow.global_blocker_ids)
    for module_id, state in package_workflow.module_states.items():
        backend[f"workflow.module.{module_id}.state"] = state.value
    return backend, tuple(sorted(blockers)), tuple(sorted(warnings))

def adapt_professional_workbook_payload(
    *,
    ticker: str,
    requested_run_id: int,
    preflight: Mapping[str, Any],
    historical: HistoricalFinancialModel | Any,
    forecast_bundle: Any,
    valuation_document: Mapping[str, Any],
    comparables: Sequence[ComparableCompany],
    valuation_source_path: str | Path,
) -> NormalizedProfessionalWorkbookPayload:
    """Create the renderer payload without dropping canonical model lines."""

    if requested_run_id <= 0:
        raise ProfessionalModelAdapterError("requested_run_id must be positive")
    _validate_run_binding(
        ticker=ticker,
        requested_run_id=requested_run_id,
        preflight=preflight,
        valuation_document=valuation_document,
    )
    if str(getattr(historical, "ticker", "")).upper() != ticker.upper().strip():
        raise ProfessionalModelAdapterError("historical ticker does not match requested ticker")
    observed_historical_runs = {
        ref.ciq_run_id
        for spec in historical.registry
        for period in historical.period_keys
        for ref in getattr(
            historical.period_lineage(spec.canonical_key, period),
            "source_refs",
            (),
        )
        if ref.ciq_run_id is not None
    }
    if observed_historical_runs != {requested_run_id}:
        raise ProfessionalModelAdapterError(
            "historical source refs do not match the requested run identity"
        )
    scenarios = _scenario_results(forecast_bundle)
    forecast_axes = {_forecast_periods(result) for result in scenarios.values()}
    if len(forecast_axes) != 1:
        raise ProfessionalModelAdapterError("forecast scenarios use different period axes")
    forecast_periods = next(iter(forecast_axes))

    source = _mapping(preflight.get("source"), "preflight source")
    parser = _mapping(preflight.get("parser"), "preflight parser")
    workbook = _mapping(preflight.get("workbook"), "preflight workbook")
    source_run = SourceWorkbookRun(
        source_file=str(source.get("source_file") or Path(str(source.get("path"))).name),
        source_path=str(source.get("path")),
        source_hash=str(source.get("sha256")).lower(),
        run_id=requested_run_id,
        parser_version=str(source.get("parser_version") or parser.get("parser_version")),
        status=str(preflight.get("status") or "unavailable"),
        fact_count=int(parser.get("rows_parsed") or 0),
        formula_error_count=int(workbook.get("formula_error_count") or 0),
    )

    currency = str(source.get("currency") or "USD").upper()
    lines = _model_lines(
        historical=historical,
        scenarios=scenarios,
        forecast_periods=forecast_periods,
        currency=currency,
    )
    backend, blockers, warnings = _check_payload(
        preflight=preflight,
        historical=historical,
        scenarios=scenarios,
        valuation_document=valuation_document,
        valuation_source_path=Path(valuation_source_path).resolve(),
    )
    ciq_lineage_raw = valuation_document.get("ciq_lineage")
    ciq_lineage = ciq_lineage_raw if isinstance(ciq_lineage_raw, Mapping) else {}
    price_source_file = str(
        ciq_lineage.get("comps_source_file")
        or ciq_lineage.get("snapshot_source_file")
        or source_run.source_file
    )
    price_run_id = ciq_lineage.get("comps_run_id") or ciq_lineage.get("snapshot_run_id")
    current_price_source = (
        f"CIQ frozen snapshot | {price_source_file} | run {price_run_id} | stock_price"
        if price_run_id is not None
        else f"CIQ frozen valuation market packet | {price_source_file} | stock_price"
    )
    current_price_as_of_raw = (
        ciq_lineage.get("comps_as_of_date")
        or ciq_lineage.get("snapshot_as_of_date")
    )
    current_price_as_of = (
        _iso_date(current_price_as_of_raw, "current_price_as_of")
        if current_price_as_of_raw
        else None
    )
    backend["market.current_price.source"] = current_price_source
    backend["market.current_price.as_of"] = (
        current_price_as_of.isoformat() if current_price_as_of else "UNVERIFIED"
    )
    backend["market.current_price.run_id"] = (
        int(price_run_id) if price_run_id is not None else None
    )
    raw_decision_context = valuation_document.get("decision_context")
    decision_context = (
        {str(key): str(value) for key, value in raw_decision_context.items() if value is not None}
        if isinstance(raw_decision_context, Mapping)
        else {}
    )
    workbook_as_of_date = _iso_date(source.get("workbook_as_of_date"), "workbook_as_of_date")
    valuation_date_raw = valuation_document.get("valuation_date")
    valuation_date = (
        _iso_date(valuation_date_raw, "valuation_date")
        if valuation_date_raw
        else None
    )
    if valuation_date is None:
        blockers = tuple(sorted((*blockers, "valuation_date_explicit_absent")))
    effective_valuation_date = valuation_date or workbook_as_of_date
    valuation_inputs = _valuation_inputs(
        historical=historical,
        document=valuation_document,
        valuation_date=effective_valuation_date,
    )
    current_price = valuation_inputs.get("current_price")
    current_price_available = (
        current_price is not None
        and current_price > 0.0
        and current_price_as_of is not None
    )
    if not current_price_available:
        valuation_inputs["current_price"] = None
    current_price_state = (
        AvailabilityState(status=AvailabilityStatus.AVAILABLE)
        if current_price_available
        else AvailabilityState(
            status=AvailabilityStatus.UNAVAILABLE,
            reason_code="current_price_nonpositive_or_evidence_incomplete",
            message="Current price requires a numeric value and exact frozen as-of date.",
        )
    )
    current_price_presentation = SourcePresentationRecord(
        source_id=f"market.current_price:run:{price_run_id or requested_run_id}",
        canonical_key="market.current_price",
        raw_value=current_price,
        normalized_value=current_price if current_price_available else None,
        transform="identity_from_frozen_ciq_snapshot",
        unit=f"{currency}/share",
        unit_kind=UnitKind.CURRENCY,
        scale=1.0,
        currency=currency,
        period_type=(
            PeriodType.DATE if current_price_as_of is not None else PeriodType.NONE
        ),
        as_of_date=current_price_as_of,
        formula_status=FactFormulaStatus.NOT_FORMULA,
        source_refs=(current_price_source,),
        downstream_dependencies=(
            "assumptions.current_price",
            "cover.current_price",
            "dcf.current_price",
            "summary.current_price",
        ),
        state=current_price_state,
    )
    raw_consensus_snapshot = valuation_document.get("consensus_snapshot")
    if raw_consensus_snapshot is None:
        consensus_snapshot = None
    elif isinstance(raw_consensus_snapshot, Mapping):
        try:
            consensus_snapshot = ConsensusSnapshot.model_validate(raw_consensus_snapshot)
        except ValueError as exc:
            raise ProfessionalModelAdapterError("invalid consensus snapshot contract") from exc
    else:
        raise ProfessionalModelAdapterError("consensus_snapshot must be an object")
    if consensus_snapshot is not None and consensus_snapshot.ticker != ticker.upper().strip():
        raise ProfessionalModelAdapterError("consensus snapshot ticker does not match requested ticker")
    consensus_forecast_lineage = any(line.sheet == "Consensus_Bridge" for line in lines)
    if consensus_forecast_lineage and consensus_snapshot is None:
        blockers = tuple(sorted((*blockers, "consensus_lineage_without_qualified_snapshot")))
    segments_available = any(line.sheet == "Segment_Build" for line in lines)
    consensus_available = consensus_snapshot is not None
    driver_approvals = _driver_approval_records(valuation_document)
    return NormalizedProfessionalWorkbookPayload(
        ticker=ticker,
        company_name=str(valuation_document.get("company_name") or ticker.upper()),
        as_of_date=workbook_as_of_date,
        currency=currency,
        unit_convention=f"{currency} mm except per-share data",
        source=source_run,
        historical_periods=tuple(historical.period_keys),
        forecast_periods=forecast_periods,
        lines=lines,
        valuation_inputs=valuation_inputs,
        availability={
            "segments": TypedAvailability(
                "available" if segments_available else "pm_required",
                None if segments_available else "segment_source_or_approval_required",
                None
                if segments_available
                else "No source-backed segment history or approved segment driver set is available.",
            ),
            "consensus": TypedAvailability(
                "available" if consensus_available else "unavailable",
                None if consensus_available else "consensus_snapshot_unavailable",
                None if consensus_available else "No frozen as-of-matched consensus snapshot is available.",
            ),
            "sotp": TypedAvailability(
                "unavailable",
                "segment_evidence_unavailable",
                "SOTP is unavailable without source-backed segment evidence.",
            ),
        },
        comparables=tuple(comparables),
        sotp_components=(),
        consensus_snapshot=consensus_snapshot,
        current_price_source=current_price_source,
        current_price_as_of=current_price_as_of,
        valuation_date=valuation_date,
        decision_context=decision_context,
        source_presentations=(current_price_presentation,),
        driver_approvals=driver_approvals,
        backend_checks=backend,
        warnings=warnings,
        blockers=blockers,
    )


def load_run_comparables(
    db_path: str | Path,
    *,
    ticker: str,
    run_id: int,
) -> tuple[ComparableCompany, ...]:
    """Load exact-run peer observations from SQLite in read-only mode."""

    path = Path(db_path).resolve()
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(
            """
            SELECT peer_ticker, peer_name, is_target, metric_key, value_num
            FROM ciq_comps_snapshot
            WHERE run_id = ? AND UPPER(target_ticker) = UPPER(?)
            ORDER BY peer_ticker, metric_key
            """,
            [run_id, ticker],
        ).fetchall()
    except sqlite3.Error as exc:
        raise ProfessionalModelAdapterError("exact-run comparable cache is unavailable") from exc
    finally:
        connection.close()
    by_peer: dict[str, dict[str, Any]] = {}
    for row in rows:
        if bool(row["is_target"]):
            continue
        peer = str(row["peer_ticker"]).upper()
        entry = by_peer.setdefault(
            peer,
            {"ticker": peer, "company_name": str(row["peer_name"] or peer)},
        )
        entry[str(row["metric_key"])] = row["value_num"]
    return tuple(
        ComparableCompany(
            ticker=peer,
            company_name=str(values["company_name"]),
            enterprise_value=_number(values.get("tev")),
            equity_value=_number(values.get("market_cap")),
            revenue=_number(values.get("total_revenue_ltm")),
            ebitda=_number(values.get("ebitda_ltm")),
            net_income=None,
            share_price=_number(values.get("stock_price")),
        )
        for peer, values in sorted(by_peer.items())
    )


def render_professional_model_v2_payload(
    payload: NormalizedProfessionalWorkbookPayload,
    *,
    output_root: str | Path,
) -> ProfessionalModelArtifacts:
    output_dir = Path(output_root) / payload.ticker / str(payload.source.run_id)
    workbook_path = output_dir / f"{payload.ticker}_professional_model_v2.xlsx"
    manifest_path = output_dir / "manifest.json"
    existing = tuple(path for path in (workbook_path, manifest_path) if path.exists())
    if existing:
        raise ProfessionalModelAdapterError(
            "refusing to overwrite existing professional-model artifact(s): "
            + ", ".join(str(path) for path in existing)
        )
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest = render_professional_model_workbook(payload, workbook_path)
    manifest_path.write_text(
        json.dumps(manifest.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return ProfessionalModelArtifacts(
        output_dir=output_dir,
        workbook_path=workbook_path,
        manifest_path=manifest_path,
        payload=payload,
        manifest=manifest,
    )


def build_professional_model_v2(
    *,
    ticker: str,
    db_path: str | Path,
    run_id: int,
    workbook_path: str | Path,
    valuation_json: str | Path,
    output_dir: str | Path,
    forecast_bundle: Any | None = None,
) -> ProfessionalModelArtifacts:
    """Run the complete cache-only adapter and renderer workflow."""

    from scripts.manual.professional_model_preflight import build_preflight_manifest

    preflight = build_preflight_manifest(
        ticker=ticker,
        workbook_path=workbook_path,
        db_path=db_path,
        require_ingested=True,
    )
    source = _mapping(preflight.get("source"), "preflight source")
    if int(source.get("run_id") or 0) != run_id:
        raise ProfessionalModelAdapterError(
            "fresh preflight does not bind the explicitly requested run identity"
        )
    valuation_document = load_frozen_valuation_document(
        valuation_json,
        ticker=ticker,
        requested_run_id=run_id,
        expected_source_hash=str(source.get("sha256")),
    )
    historical = build_historical_financial_model_from_sqlite(
        db_path,
        ticker=ticker,
        run_id=run_id,
    )
    if forecast_bundle is None:
        forecast_bundle = build_diagnostic_scenario_forecasts(
            historical,
            valuation_document,
        )
    payload = adapt_professional_workbook_payload(
        ticker=ticker,
        requested_run_id=run_id,
        preflight=preflight,
        historical=historical,
        forecast_bundle=forecast_bundle,
        valuation_document=valuation_document,
        comparables=load_run_comparables(db_path, ticker=ticker, run_id=run_id),
        valuation_source_path=valuation_json,
    )
    return render_professional_model_v2_payload(payload, output_root=output_dir)


def build_diagnostic_scenario_forecasts(
    historical: HistoricalFinancialModel,
    valuation_document: Mapping[str, Any],
) -> Any:
    """Build PM-gated five-year paths from one explicit frozen valuation file.

    The latest fiscal year is the forecast seed.  LTM remains reference-only
    and is never substituted into the annual seed or driver ratios.  The first
    five frozen ``forecast_bridge`` records supply explicit annual operating
    paths where available; approval is accepted only from a matching API
    fingerprint record and every unmatched or stale path remains PM-gated.
    """

    try:
        from src.stage_02_valuation.integrated_financial_forecast import (
            DRIVER_SPECS,
            FORECAST_YEARS,
            DriverPath,
            ScenarioDriverSet,
            build_complete_scenario_forecasts,
        )
    except ImportError as exc:
        raise ProfessionalModelAdapterError(
            "integrated forecast engine is unavailable; workbook remains blocked"
        ) from exc
    approval_records = _driver_approval_records(valuation_document)
    approvals_by_key = {
        (_normalize_scenario_key(record.scenario_key), record.driver_key): record
        for record in approval_records
    }


    assumptions = _mapping(
        valuation_document.get("assumptions"),
        "valuation assumptions",
    )
    wacc = _mapping(valuation_document.get("wacc"), "valuation wacc")
    fiscal_year_periods = tuple(
        period
        for period in historical.result.period_axis.periods
        if period.period_type is PeriodType.FISCAL_YEAR
    )
    if not fiscal_year_periods:
        raise ProfessionalModelAdapterError(
            "diagnostic forecast requires a fiscal-year historical anchor"
        )
    fiscal_seed_period = fiscal_year_periods[-1]

    prior_fiscal_period = fiscal_year_periods[-2] if len(fiscal_year_periods) >= 2 else None

    def h_at(key: str, period_key: str, default: float = 0.0) -> float:
        value = historical.value(key, period_key)
        numeric = _number(value.value)
        if value.state.status is AvailabilityStatus.AVAILABLE and numeric is not None:
            return numeric
        return default

    def h(key: str, default: float = 0.0) -> float:
        return h_at(key, fiscal_seed_period.key, default)

    revenue = h("is.revenue", 1.0)
    if revenue <= 0.0:
        raise ProfessionalModelAdapterError(
            "diagnostic forecast requires positive source-backed fiscal-year revenue"
        )

    # CIQ Standard labels `Other Operating Exp., Total` as a subtotal that
    # already includes SG&A and R&D.  Preserve the visible FY seed ratios and
    # solve gross margin from the frozen EBIT-margin path instead of hiding the
    # margin change in an aggregate operating-expense plug.
    other_opex_residual = (
        h("is.operating_income")
        - h("is.gross_profit")
        - h("is.sga")
        - h("is.research_development")
    )
    other_opex_percent_revenue = max(
        0.0,
        -other_opex_residual / revenue,
    )
    debt_tax_rate = _first_not_none(
        _number(assumptions.get("tax_rate_target_pct")),
        0.21,
    )
    pre_tax_cost_of_debt = _number(wacc.get("cost_of_debt"))
    cost_of_debt_provenance = "frozen_v1:wacc:cost_of_debt:pretax"
    if pre_tax_cost_of_debt is None:
        after_tax_cost_of_debt = _number(wacc.get("cost_of_debt_after_tax"))
        if after_tax_cost_of_debt is not None and 0.0 <= debt_tax_rate < 1.0:
            pre_tax_cost_of_debt = after_tax_cost_of_debt / (1.0 - debt_tax_rate)
            cost_of_debt_provenance = (
                "derived:frozen_v1:wacc:cost_of_debt_after_tax/"
                "(1-tax_rate_target_pct)"
            )
    if pre_tax_cost_of_debt is None:
        pre_tax_cost_of_debt = 0.05
        cost_of_debt_provenance = "diagnostic_default:pretax_cost_of_debt"

    liquid_asset_keys = (
        "bs.cash",
        "bs.short_term_investments",
        "bs.long_term_investments",
    )
    current_liquid_assets = sum(h(key) for key in liquid_asset_keys)
    prior_liquid_assets = (
        sum(h_at(key, prior_fiscal_period.key) for key in liquid_asset_keys)
        if prior_fiscal_period is not None
        else current_liquid_assets
    )
    average_liquid_assets = (current_liquid_assets + prior_liquid_assets) / 2.0
    cash_yield = max(_safe_ratio(h("is.interest_income"), average_liquid_assets), 0.0)
    nopat_tax_rate = _number(assumptions.get("nopat_tax_rate_pct"))
    if nopat_tax_rate is None or not 0.0 <= nopat_tax_rate <= 1.0:
        raise ProfessionalModelAdapterError(
            "diagnostic forecast requires a distinct source-backed NOPAT tax rate"
        )
    historical_cash_tax_rate = _safe_ratio(
        abs(h("tax.cash_taxes")),
        abs(h("tax.pretax_income")),
    )
    if not 0.0 <= historical_cash_tax_rate <= 1.0:
        historical_cash_tax_rate = 0.0
    asset_sale_proceeds = max(h("cf.sale_ppe"), 0.0)
    asset_cost_disposals = _first_not_none(
        _number(assumptions.get("asset_cost_disposals_mm")),
        0.0,
    )
    asset_disposal_accumulated_depreciation = _first_not_none(
        _number(assumptions.get("asset_disposal_accumulated_depreciation_mm")),
        0.0,
    )
    base: dict[str, float] = {
        "revenue_growth": _first_not_none(
            _number(assumptions.get("growth_near_pct")),
            0.0,
        ),
        "gross_margin": h("is.gross_profit") / revenue,
        "sga_percent_revenue": abs(h("is.sga")) / revenue,
        "rd_percent_revenue": abs(h("is.research_development")) / revenue,
        "other_opex_percent_revenue": other_opex_percent_revenue,
        "da_percent_revenue": _first_not_none(
            _number(assumptions.get("da_pct")),
            abs(h("cf.da")) / revenue,
        ),
        "intangible_amortization_percent_revenue": abs(
            h("cf.intangible_amortization")
        )
        / revenue,
        "stock_comp_percent_revenue": abs(
            h("is.stock_based_compensation")
        )
        / revenue,
        "effective_tax_rate": _first_not_none(
            _number(assumptions.get("tax_rate_target_pct")),
            0.21,
        ),
        "cash_tax_rate": historical_cash_tax_rate,
        "nopat_tax_rate": nopat_tax_rate,
        "dso": _first_not_none(_number(assumptions.get("dso_start")), 0.0),
        "dio": _first_not_none(_number(assumptions.get("dio_start")), 0.0),
        "dpo": _first_not_none(_number(assumptions.get("dpo_start")), 0.0),
        "deferred_revenue_percent_revenue": (
            h("bs.deferred_revenue_current")
            + h("bs.deferred_revenue_noncurrent")
        )
        / revenue,
        "capex_percent_revenue": _first_not_none(
            _number(assumptions.get("capex_pct")),
            abs(h("cf.capex")) / revenue,
        ),
        "minimum_cash": h("bs.cash"),
        # No source-backed maturity schedule is present in the frozen packet.
        # Hold issuance and repayment at zero pending explicit PM approval.
        "scheduled_debt_issuance": 0.0,
        "scheduled_debt_repayment": 0.0,
        "cost_of_debt": pre_tax_cost_of_debt,
        "cash_yield": cash_yield,
        "dividend_payout": _safe_ratio(
            abs(h("cf.dividends_paid")),
            h("is.net_income_common"),
        ),
        "buyback_amount": abs(h("cf.share_repurchase")),
        "common_stock_issuance": max(h("cf.common_stock_issued"), 0.0),
        "average_share_price": _first_not_none(
            _number(
                _mapping(
                    valuation_document.get("market"),
                    "market",
                ).get("price")
            ),
            1.0,
        ),
        "incremental_diluted_shares": max(h("shares.dilution"), 0.0),
        "net_investment_purchases": abs(h("cf.investments")),
        "acquisition_spend": abs(h("cf.acquisitions")),
        "asset_sale_proceeds": asset_sale_proceeds,
        "asset_cost_disposals": asset_cost_disposals,
        "asset_disposal_accumulated_depreciation": asset_disposal_accumulated_depreciation,
        "other_nonoperating_percent_revenue": h("is.other_nonoperating")
        / revenue,
        "prepaids_percent_revenue": h("bs.prepaids") / revenue,
        "other_current_assets_percent_revenue": h("bs.other_current_assets")
        / revenue,
        "accrued_expenses_percent_revenue": h("bs.accrued_expenses")
        / revenue,
        "other_current_liabilities_percent_revenue": h(
            "bs.other_current_liabilities"
        )
        / revenue,
        "deferred_tax_assets_percent_revenue": h("bs.deferred_tax_assets")
        / revenue,
        "deferred_tax_liabilities_percent_revenue": h(
            "bs.deferred_tax_liability"
        )
        / revenue,
        "preferred_dividends": abs(h("is.preferred_dividends")),
        "minority_earnings_percent": _safe_ratio(
            h("is.minority_earnings"),
            h("is.net_income_company"),
        ),
        # Non-recurring and residual cash-flow lines are explicitly held at
        # zero rather than repeating a one-year historical inflow/outflow.
        "other_operating_cash_flow": 0.0,
        "other_investing_cash_flow": 0.0,
        "other_financing_cash_flow": 0.0,
        "fx_cash_adjustment": 0.0,
        "misc_cash_adjustment": 0.0,
    }
    missing = set(DRIVER_SPECS) - set(base)
    extra = set(base) - set(DRIVER_SPECS)
    if missing or extra:
        raise ProfessionalModelAdapterError(
            "diagnostic driver mapping does not match forecast contract; "
            f"missing={sorted(missing)}, extra={sorted(extra)}"
        )

    raw_forecast_bridge = valuation_document.get("forecast_bridge")
    if isinstance(raw_forecast_bridge, Sequence) and not isinstance(
        raw_forecast_bridge,
        (str, bytes),
    ):
        raw_bridge_records = tuple(raw_forecast_bridge[:FORECAST_YEARS])
    else:
        raw_bridge_records = ()
    bridge_records: tuple[Mapping[str, Any], ...] = tuple(
        record if isinstance(record, Mapping) else {}
        for record in raw_bridge_records
    )
    if len(bridge_records) < FORECAST_YEARS:
        bridge_records += tuple(
            {} for _ in range(FORECAST_YEARS - len(bridge_records))
        )

    first_bridge = bridge_records[0]
    expected_forecast_start = fiscal_seed_period.end_date + timedelta(days=1)
    expected_forecast_end = date(
        fiscal_seed_period.end_date.year + 1,
        fiscal_seed_period.end_date.month,
        fiscal_seed_period.end_date.day,
    )
    basis = str(first_bridge.get("bridge_basis") or "").strip().lower()
    try:
        bridge_period_start = _iso_date(
            first_bridge.get("period_start"),
            "forecast_bridge[0].period_start",
        )
        bridge_period_end = _iso_date(
            first_bridge.get("period_end"),
            "forecast_bridge[0].period_end",
        )
        ytd_period_end = _iso_date(
            first_bridge.get("ytd_period_end"),
            "forecast_bridge[0].ytd_period_end",
        )
    except ProfessionalModelAdapterError as exc:
        raise ProfessionalModelAdapterError(
            "first annual forecast requires an explicit FY26 YTD+Q4 stub with exact dates"
        ) from exc
    stub_refs = first_bridge.get("stub_source_refs")
    actual_anchor_period = next(
        (
            period
            for period in historical.result.period_axis.periods
            if period.end_date == ytd_period_end
            and period.period_type in {PeriodType.LTM, PeriodType.FISCAL_QUARTER}
        ),
        None,
    )
    stub_revenue_raw = _number(first_bridge.get("revenue"))
    stub_scale_to_model = _number(first_bridge.get("revenue_scale_to_model"))
    valid_stub_refs = (
        isinstance(stub_refs, Sequence)
        and not isinstance(stub_refs, (str, bytes))
        and bool(tuple(str(item).strip() for item in stub_refs if str(item).strip()))
    )
    if (
        int(first_bridge.get("year") or 0) != 1
        or basis != "explicit_ytd_plus_q4_stub"
        or bridge_period_start != expected_forecast_start
        or bridge_period_end != expected_forecast_end
        or not (bridge_period_start <= ytd_period_end < bridge_period_end)
        or not valid_stub_refs
        or actual_anchor_period is None
        or stub_revenue_raw is None
        or stub_scale_to_model is None
        or stub_scale_to_model <= 0.0
        or stub_revenue_raw <= 0.0
    ):
        raise ProfessionalModelAdapterError(
            "first annual forecast requires an explicit FY26 YTD+Q4 stub; "
            "TTM/FY1 growth cannot be applied to the FY25 seed"
        )
    stub_revenue_model = stub_revenue_raw * stub_scale_to_model
    legacy_ltm_revenue = _number(assumptions.get("revenue_mm"))
    legacy_growth = _number(assumptions.get("growth_near_pct"))
    bridge_growth = _number(first_bridge.get("growth_rate"))
    legacy_consensus_chain = (
        legacy_ltm_revenue is not None
        and legacy_ltm_revenue > 0.0
        and legacy_growth is not None
        and bridge_growth is not None
        and abs(stub_revenue_model / legacy_ltm_revenue - 1.0 - legacy_growth) <= 1e-9
        and abs(bridge_growth - legacy_growth) <= 1e-9
        and abs(legacy_ltm_revenue - revenue) > 1e-6
    )
    snapshot_raw = valuation_document.get("consensus_snapshot")
    snapshot = snapshot_raw if isinstance(snapshot_raw, Mapping) else {}
    qualified_period_match = (
        str(snapshot.get("eligibility_state") or "").upper() == "ELIGIBLE"
        and str(snapshot.get("metric") or "").lower() == "revenue"
        and str(snapshot.get("period_type") or "").lower() == "fiscal_year"
        and str(snapshot.get("period_end") or "") == bridge_period_end.isoformat()
    )
    if legacy_consensus_chain and not qualified_period_match:
        raise ProfessionalModelAdapterError(
            "unqualified_consensus_lineage: CY+1/LTM growth cannot be aliased to "
            "FY1 or applied to the FY25 annual seed; require a period-matched FY26 "
            "YTD plus Q4 bridge"
        )
    first_year_growth = stub_revenue_model / revenue - 1.0
    def bridge_path(source_field: str, fallback: float) -> tuple[float, ...]:
        values: list[float] = []
        for record in bridge_records:
            source_value = _number(record.get(source_field))
            values.append(fallback if source_value is None else source_value)
        return tuple(values)

    visible_opex_ratio = (
        base["sga_percent_revenue"]
        + base["rd_percent_revenue"]
        + base["other_opex_percent_revenue"]
    )
    seed_ebit_margin = base["gross_margin"] - visible_opex_ratio
    ebit_margin_path = bridge_path("ebit_margin", seed_ebit_margin)
    bridge_paths: dict[str, tuple[float, ...]] = {
        "revenue_growth": (
            first_year_growth,
            *bridge_path("growth_rate", base["revenue_growth"])[1:],
        ),
        "da_percent_revenue": bridge_path(
            "da_pct",
            base["da_percent_revenue"],
        ),
        "intangible_amortization_percent_revenue": bridge_path(
            "intangible_amortization_pct",
            base["intangible_amortization_percent_revenue"],
        ),
        "effective_tax_rate": bridge_path(
            "tax_rate",
            base["effective_tax_rate"],
        ),
        "cash_tax_rate": bridge_path("cash_tax_rate", base["cash_tax_rate"]),
        "nopat_tax_rate": bridge_path("nopat_tax_rate", base["nopat_tax_rate"]),
        "asset_cost_disposals": bridge_path(
            "asset_cost_disposals", base["asset_cost_disposals"]
        ),
        "asset_disposal_accumulated_depreciation": bridge_path(
            "asset_disposal_accumulated_depreciation",
            base["asset_disposal_accumulated_depreciation"],
        ),
        "capex_percent_revenue": bridge_path(
            "capex_pct",
            base["capex_percent_revenue"],
        ),
        "dso": bridge_path("dso", base["dso"]),
        "dio": bridge_path("dio", base["dio"]),
        "dpo": bridge_path("dpo", base["dpo"]),
    }

    raw_context_scenarios = valuation_document.get("context_scenarios")
    normalized_context: dict[str, Mapping[str, Any]] = {}
    if isinstance(raw_context_scenarios, Mapping):
        for raw_key, raw_value in raw_context_scenarios.items():
            if isinstance(raw_value, Mapping):
                normalized_context[_normalize_scenario_key(raw_key)] = raw_value

    scenario_policy = (
        ("Base", "base", 1.0, 0.0),
        ("Upside", "upside", 1.2, 0.02),
        ("Downside", "downside", 0.8, -0.02),
    )
    visible_opex_drivers = {
        "sga_percent_revenue",
        "rd_percent_revenue",
        "other_opex_percent_revenue",
    }
    debt_policy_drivers = {
        "minimum_cash",
        "scheduled_debt_issuance",
        "scheduled_debt_repayment",
        "cost_of_debt",
        "cash_yield",
    }
    zero_nonrecurring_cash_policy_drivers = {
        "other_operating_cash_flow",
        "other_investing_cash_flow",
        "other_financing_cash_flow",
        "fx_cash_adjustment",
        "misc_cash_adjustment",
    }
    capital_allocation_policy_drivers = {
        "dividend_payout",
        "buyback_amount",
        "common_stock_issuance",
        "average_share_price",
        "incremental_diluted_shares",
        "preferred_dividends",
    }
    bridge_source_fields = {
        "da_percent_revenue": "da_pct",
        "intangible_amortization_percent_revenue": "intangible_amortization_pct",
        "effective_tax_rate": "tax_rate",
        "cash_tax_rate": "cash_tax_rate",
        "nopat_tax_rate": "nopat_tax_rate",
        "asset_cost_disposals": "asset_cost_disposals",
        "asset_disposal_accumulated_depreciation": "asset_disposal_accumulated_depreciation",
        "capex_percent_revenue": "capex_pct",
        "dso": "dso",
        "dio": "dio",
        "dpo": "dpo",
    }

    def provenance(
        key: str,
        context_source: str,
    ) -> tuple[str, str]:
        fiscal_source = fiscal_seed_period.key
        if key == "revenue_growth":
            return (
                "frozen_v1:forecast_bridge:year_1:explicit_ytd_plus_q4_stub|"
                "frozen_v1:forecast_bridge:years_2_5:growth_rate|"
                f"{context_source}:growth_multiplier|"
                f"historical:{fiscal_source}:annual_seed",
                "diagnostic_unapproved_stub_anchored_growth_with_context_multiplier",
            )
        if key == "gross_margin":
            return (
                "frozen_v1:forecast_bridge:first_5:ebit_margin|"
                f"historical:{fiscal_source}:visible_opex_ratios|"
                f"{context_source}:margin_shift",
                "diagnostic_unapproved_year_by_year_ebit_margin_bridge_to_"
                "gross_margin_with_context_shift",
            )
        if key == "cash_tax_rate":
            return (
                f"frozen_v1:forecast_bridge:first_5:cash_tax_rate|"
                f"historical:{fiscal_source}:tax.cash_taxes/tax.pretax_income:fallback",
                "diagnostic_unapproved_distinct_cash_tax_rate_path",
            )
        if key == "nopat_tax_rate":
            return (
                f"frozen_v1:forecast_bridge:first_5:nopat_tax_rate|"
                "frozen_v1:assumptions:nopat_tax_rate_pct:distinct_from_book_and_cash_tax",
                "diagnostic_unapproved_distinct_nopat_tax_rate_path",
            )
        if key == "intangible_amortization_percent_revenue":
            return (
                f"frozen_v1:forecast_bridge:first_5:intangible_amortization_pct|"
                f"historical:{fiscal_source}:cf.intangible_amortization/is.revenue:fallback",
                "diagnostic_unapproved_separate_intangible_amortization_path",
            )
        if key in bridge_source_fields:
            source_field = bridge_source_fields[key]
            return (
                f"frozen_v1:forecast_bridge:first_5:{source_field}|"
                f"frozen_v1:assumptions_or_historical:{fiscal_source}:fallback",
                "diagnostic_unapproved_year_by_year_forecast_bridge_path",
            )
        if key in visible_opex_drivers:
            return (
                f"historical:{fiscal_source}:visible_opex_ratio:{key}",
                "diagnostic_unapproved_fiscal_seed_visible_opex_ratio_"
                "held_constant",
            )
        if key == "cost_of_debt":
            return (
                cost_of_debt_provenance,
                "diagnostic_unapproved_pretax_cost_of_debt_path",
            )
        if key == "cash_yield":
            prior_key = (
                prior_fiscal_period.key
                if prior_fiscal_period is not None
                else fiscal_seed_period.key
            )
            return (
                f"historical:{prior_key}:{fiscal_source}:average_cash_st_lt_investments|"
                f"historical:{fiscal_source}:interest_income",
                "diagnostic_unapproved_interest_income_over_average_liquid_assets",
            )
        if key in debt_policy_drivers:
            return (
                f"historical_or_frozen_wacc:{fiscal_source}:"
                f"common_fixed_debt_policy:{key}",
                "diagnostic_unapproved_common_fixed_debt_policy",
            )
        if key in capital_allocation_policy_drivers:
            return (
                f"historical_or_frozen_market:{fiscal_source}:"
                f"common_fixed_capital_allocation_policy:{key}",
                "diagnostic_unapproved_common_fixed_capital_allocation_policy",
            )
        if key in zero_nonrecurring_cash_policy_drivers:
            return (
                f"diagnostic_policy:common_fixed_zero_nonrecurring_cash:{key}",
                "diagnostic_unapproved_common_fixed_zero_nonrecurring_cash_policy",
            )
        return (
            f"historical_or_frozen_assumption:{fiscal_source}:"
            f"common_fixed_policy:{key}",
            "diagnostic_unapproved_common_fixed_operating_or_balance_sheet_policy",
        )

    driver_sets = []
    common_paths = {
        key: (value,) * FORECAST_YEARS for key, value in base.items()
    }
    for (
        scenario_key,
        normalized_scenario,
        default_growth_multiplier,
        default_margin_shift,
    ) in scenario_policy:
        context = normalized_context.get(normalized_scenario, {})
        growth_multiplier = _first_not_none(
            _number(context.get("growth_multiplier")),
            default_growth_multiplier,
        )
        margin_shift = _first_not_none(
            _number(context.get("margin_shift")),
            default_margin_shift,
        )
        context_source = (
            f"frozen_v1:context_scenarios:{normalized_scenario}"
            if context
            else f"diagnostic_default_context:{normalized_scenario}"
        )
        path_values = {**common_paths, **bridge_paths}
        path_values["revenue_growth"] = tuple(
            value * growth_multiplier
            for value in bridge_paths["revenue_growth"]
        )
        path_values["gross_margin"] = tuple(
            ebit_margin + margin_shift + visible_opex_ratio
            for ebit_margin in ebit_margin_path
        )

        paths = []
        for key, values in sorted(path_values.items()):
            source_ref, method = provenance(
                key,
                context_source,
            )
            fingerprint = DriverPath.fingerprint_for(
                key=key,
                values=values,
                unit=DRIVER_SPECS[key].unit,
                source_ref=source_ref,
                method=method,
            )
            approval = approvals_by_key.get(
                (normalized_scenario, key)
            ) or approvals_by_key.get(("", key))
            effective_approval = (
                approval.with_current_fingerprint(fingerprint)
                if approval is not None
                else None
            )
            approved = (
                effective_approval is not None
                and effective_approval.approval_state is DriverApprovalState.APPROVED
                and effective_approval.approved_driver_fingerprint == fingerprint
            )
            paths.append(
                DriverPath(
                    key=key,
                    values=values,
                    unit=DRIVER_SPECS[key].unit,
                    source_ref=source_ref,
                    method=method,
                    approval_ref=(
                        effective_approval.approval_ref if approved else None
                    ),
                    queue_item_id=(
                        None if approved else f"pmq:{scenario_key}:{key}"
                    ),
                    driver_group=(
                        effective_approval.driver_group
                        if effective_approval is not None
                        else DriverGroup.FINANCE_SEMANTIC
                    ),
                    current_driver_fingerprint=fingerprint,
                    approved_driver_fingerprint=(
                        effective_approval.approved_driver_fingerprint
                        if effective_approval is not None
                        else None
                    ),
                )
            )
        driver_sets.append(
            ScenarioDriverSet(
                scenario_key=scenario_key,
                parent_scenario_key=(
                    None if scenario_key == "Base" else "Base"
                ),
                paths=tuple(paths),
            )
        )

    historical_seed: dict[str, float] = {}
    for spec in historical.registry:
        period_value = historical.value(
            spec.canonical_key,
            fiscal_seed_period.key,
        )
        numeric = _number(period_value.value)
        if (
            period_value.state.status is AvailabilityStatus.AVAILABLE
            and numeric is not None
        ):
            historical_seed[spec.canonical_key] = numeric
    return build_complete_scenario_forecasts(
        historical_seed,
        tuple(driver_sets),
        last_historical_period_end=fiscal_seed_period.end_date,
    )

__all__ = [
    "CORE_RENDERER_ALIASES",
    "ProfessionalModelAdapterError",
    "ProfessionalModelArtifacts",
    "adapt_professional_workbook_payload",
    "build_diagnostic_scenario_forecasts",
    "build_professional_model_v2",
    "load_frozen_valuation_document",
    "load_run_comparables",
    "render_professional_model_v2_payload",
]
