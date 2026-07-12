"""Fail-closed market, WACC-input, and consensus evidence normalization.

One immutable CIQ ingest run is converted into a deterministic evidence packet.
Cached candidates remain inspectable, but ``value`` is only populated when the
source has the date and method metadata needed for safe downstream use.  This
module exposes cost-of-debt proxies; it never selects a WACC methodology.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import sqlite3
from typing import Any, Callable, Iterable, Mapping

import yaml


EVIDENCE_SCHEMA_VERSION = "1.0.0"
CIQ_SOURCE_NAME = "S&P Capital IQ Standard workbook cached result"
CONFIG_SOURCE_NAME = "Local valuation policy configuration"

CORE_FIELD_KEYS: tuple[str, ...] = (
    "current_price",
    "shares_outstanding",
    "market_cap",
    "risk_free_rate",
    "equity_risk_premium",
    "beta",
    "total_debt",
    "lease_liabilities",
    "cost_of_debt",
    "tax_rate",
)

_CONSENSUS_METRICS: tuple[tuple[str, str, str, int], ...] = (
    ("total_revenue_cy_1", "revenue", "CY+1", 1),
    ("total_revenue_cy_2", "revenue", "CY+2", 2),
    ("ebitda_cy_1", "ebitda", "CY+1", 1),
    ("ebitda_cy_2", "ebitda", "CY+2", 2),
    ("diluted_eps_cy_1", "diluted_eps", "CY+1", 1),
    ("diluted_eps_cy_2", "diluted_eps", "CY+2", 2),
)


def _fetch_dicts(conn: sqlite3.Connection, sql: str, params: Iterable[Any]) -> list[dict[str, Any]]:
    cursor = conn.execute(sql, tuple(params))
    columns = [str(item[0]) for item in cursor.description or ()]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def _one_dict(conn: sqlite3.Connection, sql: str, params: Iterable[Any]) -> dict[str, Any] | None:
    rows = _fetch_dicts(conn, sql, params)
    return rows[0] if rows else None


def _as_date(value: date | datetime | str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        raise ValueError("date value cannot be blank")
    return date.fromisoformat(text[:10])


def _optional_date(value: Any) -> date | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        return _as_date(value)
    except (TypeError, ValueError):
        return None


def _iso_timestamp(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value).strip()
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return text
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _finite_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _freshness(source_as_of: date | None, valuation_date: date) -> dict[str, Any]:
    """Describe age without imposing a finance-specific stale threshold."""

    if source_as_of is None:
        return {
            "status": "unknown_source_as_of",
            "valuation_date": valuation_date.isoformat(),
            "source_as_of_date": None,
            "age_days": None,
            "stale_threshold_days": None,
            "staleness_assessment": "not_evaluated",
        }
    age_days = (valuation_date - source_as_of).days
    return {
        "status": "future_dated" if age_days < 0 else "dated",
        "valuation_date": valuation_date.isoformat(),
        "source_as_of_date": source_as_of.isoformat(),
        "age_days": age_days,
        "stale_threshold_days": None,
        "staleness_assessment": "not_evaluated",
    }


def _ticker_from_row_label(value: Any) -> str:
    return str(value or "").strip().upper().rsplit(":", 1)[-1]


def _fact_quality_flags(fact: Mapping[str, Any] | None) -> list[str]:
    if fact is None:
        return []
    flags: set[str] = set()
    if str(fact.get("formula_status") or "").lower() == "formula_cached":
        flags.add("cached_value_not_native_refresh_verified")
    if fact.get("formula_error"):
        flags.add("source_formula_error")
    if fact.get("cached_error"):
        flags.add("source_cached_error")
    if fact.get("unit") in {None, ""}:
        flags.add("parsed_source_unit_missing")
    if fact.get("period_date") in {None, ""}:
        flags.add("source_period_missing")
    return sorted(flags)


def _fact_usable(fact: Mapping[str, Any] | None) -> bool:
    if fact is None or _finite_float(fact.get("value_num")) is None:
        return False
    status = str(fact.get("formula_status") or "").lower()
    return not ("error" in status or fact.get("formula_error") or fact.get("cached_error"))


def _locator(fact: Mapping[str, Any]) -> str:
    return f"{fact.get('source_file') or 'unknown_workbook'}::{fact.get('cell_locator') or 'unknown_cell'}"


def _record(
    field_key: str,
    *,
    status: str,
    valuation_date: date,
    unit: str,
    unit_kind: str,
    value: Any = None,
    candidate_value: Any = None,
    source_value: Any = None,
    source_unit: str | None = None,
    source_name: str | None = None,
    source_locator: str | None = None,
    source_formula: str | None = None,
    source_as_of: date | None = None,
    observed_at: str | None = None,
    method: str | None = None,
    transformation: str | None = None,
    quality_flags: Iterable[str] = (),
    components: Iterable[str] = (),
    reason_code: str | None = None,
    message: str | None = None,
) -> dict[str, Any]:
    return {
        "field_key": field_key,
        "status": status,
        "value": value,
        "candidate_value": candidate_value,
        "unit": unit,
        "unit_kind": unit_kind,
        "source_value": source_value,
        "source_unit": source_unit,
        "source_name": source_name,
        "source_locator": source_locator,
        "source_formula": source_formula,
        "source_as_of_date": source_as_of.isoformat() if source_as_of else None,
        "source_timestamp": None,
        "observed_at": observed_at,
        "freshness": _freshness(source_as_of, valuation_date),
        "method": method,
        "transformation": transformation,
        "quality_flags": sorted(set(quality_flags)),
        "components": sorted(set(components)),
        "reason_code": reason_code,
        "message": message,
    }


def _unavailable(
    field_key: str,
    *,
    valuation_date: date,
    unit: str,
    unit_kind: str,
    reason_code: str,
    message: str,
    **kwargs: Any,
) -> dict[str, Any]:
    return _record(
        field_key,
        status="unavailable",
        valuation_date=valuation_date,
        unit=unit,
        unit_kind=unit_kind,
        reason_code=reason_code,
        message=message,
        **kwargs,
    )


def _pick_fact(
    facts: Iterable[Mapping[str, Any]],
    *,
    sheet_name: str,
    metric_key: str,
    row_index: int | None = None,
    period_date: str | None = None,
) -> Mapping[str, Any] | None:
    matches = [
        fact
        for fact in facts
        if str(fact.get("sheet_name") or "") == sheet_name
        and str(fact.get("metric_key") or "") == metric_key
        and (row_index is None or int(fact.get("row_index") or 0) == row_index)
        and (period_date is None or str(fact.get("period_date") or "") == period_date)
    ]
    matches.sort(
        key=lambda fact: (
            str(fact.get("period_date") or ""),
            str(fact.get("calc_type") or "") == "LTM",
            int(fact.get("column_index") or 0),
        ),
        reverse=True,
    )
    return matches[0] if matches else None


def _from_fact(
    field_key: str,
    fact: Mapping[str, Any] | None,
    *,
    valuation_date: date,
    observed_at: str | None,
    unit: str,
    unit_kind: str,
    source_unit: str,
    transform: Callable[[float], float],
    transformation: str,
    require_source_date: bool,
    method: str,
    extra_flags: Iterable[str] = (),
) -> dict[str, Any]:
    if fact is None:
        return _unavailable(
            field_key,
            valuation_date=valuation_date,
            unit=unit,
            unit_kind=unit_kind,
            reason_code="source_evidence_absent",
            message=f"No {field_key} source fact exists in the selected CIQ run.",
            observed_at=observed_at,
        )
    raw_number = _finite_float(fact.get("value_num"))
    candidate = transform(raw_number) if raw_number is not None else None
    source_as_of = _optional_date(fact.get("period_date"))
    common = {
        "candidate_value": candidate,
        "source_value": raw_number,
        "source_unit": source_unit,
        "source_name": CIQ_SOURCE_NAME,
        "source_locator": _locator(fact),
        "source_formula": fact.get("formula_text"),
        "source_as_of": source_as_of,
        "observed_at": observed_at,
        "method": method,
        "transformation": transformation,
        "quality_flags": set(_fact_quality_flags(fact)) | set(extra_flags),
    }
    if not _fact_usable(fact) or candidate is None:
        return _unavailable(
            field_key,
            valuation_date=valuation_date,
            unit=unit,
            unit_kind=unit_kind,
            reason_code="source_value_unusable",
            message=f"The selected {field_key} source fact is missing, non-numeric, or errored.",
            **common,
        )
    if require_source_date and source_as_of is None:
        return _unavailable(
            field_key,
            valuation_date=valuation_date,
            unit=unit,
            unit_kind=unit_kind,
            reason_code="source_timestamp_missing",
            message=(
                f"A cached {field_key} candidate exists, but the source fact has no as-of "
                "date or timestamp; ingest time is not a source timestamp."
            ),
            **common,
        )
    if source_as_of is None:
        return _unavailable(
            field_key,
            valuation_date=valuation_date,
            unit=unit,
            unit_kind=unit_kind,
            reason_code="source_period_missing",
            message=f"The selected {field_key} source fact has no source period.",
            **common,
        )
    common.pop("candidate_value")
    return _record(
        field_key,
        status="available",
        value=candidate,
        valuation_date=valuation_date,
        unit=unit,
        unit_kind=unit_kind,
        **common,
    )


def _sum_field(
    field_key: str,
    components: Iterable[dict[str, Any]],
    *,
    valuation_date: date,
    observed_at: str | None,
    method: str,
) -> dict[str, Any]:
    parts = list(components)
    keys = [str(part["field_key"]) for part in parts]
    periods = {part.get("source_as_of_date") for part in parts}
    if not parts or any(part.get("status") != "available" for part in parts):
        return _unavailable(
            field_key,
            valuation_date=valuation_date,
            unit="USD",
            unit_kind="currency",
            reason_code="component_evidence_unavailable",
            message=f"{field_key} requires all components: {', '.join(keys)}.",
            observed_at=observed_at,
            method=method,
            components=keys,
        )
    if len(periods) != 1 or None in periods:
        return _unavailable(
            field_key,
            valuation_date=valuation_date,
            unit="USD",
            unit_kind="currency",
            reason_code="component_period_mismatch",
            message=f"{field_key} components do not share one source period.",
            observed_at=observed_at,
            method=method,
            components=keys,
        )
    return _record(
        field_key,
        status="available",
        value=sum(float(part["value"]) for part in parts),
        valuation_date=valuation_date,
        unit="USD",
        unit_kind="currency",
        source_value=[part.get("source_value") for part in parts],
        source_unit="USD mm components",
        source_name=CIQ_SOURCE_NAME,
        source_locator=" + ".join(str(part.get("source_locator")) for part in parts),
        source_formula=" + ".join(keys),
        source_as_of=_as_date(next(iter(periods))),
        observed_at=observed_at,
        method=method,
        transformation="sum normalized component values",
        quality_flags={"derived_from_source_components", "cached_value_not_native_refresh_verified"},
        components=keys,
    )


def _cost_proxy(
    field_key: str,
    interest: dict[str, Any],
    denominator: dict[str, Any],
    *,
    valuation_date: date,
    observed_at: str | None,
    method: str,
) -> dict[str, Any]:
    keys = [str(interest["field_key"]), str(denominator["field_key"])]
    if interest.get("status") != "available" or denominator.get("status") != "available":
        return _unavailable(
            field_key,
            valuation_date=valuation_date,
            unit="ratio",
            unit_kind="percent",
            reason_code="component_evidence_unavailable",
            message=f"{field_key} requires source-backed interest expense and debt.",
            observed_at=observed_at,
            method=method,
            components=keys,
        )
    if interest.get("source_as_of_date") != denominator.get("source_as_of_date"):
        return _unavailable(
            field_key,
            valuation_date=valuation_date,
            unit="ratio",
            unit_kind="percent",
            reason_code="component_period_mismatch",
            message=f"{field_key} numerator and denominator periods do not match.",
            observed_at=observed_at,
            method=method,
            components=keys,
        )
    debt = float(denominator["value"])
    if debt <= 0:
        return _unavailable(
            field_key,
            valuation_date=valuation_date,
            unit="ratio",
            unit_kind="percent",
            reason_code="invalid_denominator",
            message=f"{field_key} debt denominator must be positive.",
            observed_at=observed_at,
            method=method,
            components=keys,
        )
    return _record(
        field_key,
        status="available",
        value=abs(float(interest["value"])) / debt,
        valuation_date=valuation_date,
        unit="ratio",
        unit_kind="percent",
        source_value={"interest_expense": interest["source_value"], "debt": denominator["source_value"]},
        source_unit="USD mm / USD mm",
        source_name=CIQ_SOURCE_NAME,
        source_locator=f"{interest['source_locator']} / {denominator['source_locator']}",
        source_formula=f"abs({interest['field_key']}) / {denominator['field_key']}",
        source_as_of=_as_date(str(interest["source_as_of_date"])),
        observed_at=observed_at,
        method=method,
        transformation="absolute LTM interest expense divided by period-end debt balance",
        quality_flags={"arithmetic_proxy_not_selected_wacc_input", "period_end_debt_denominator"},
        components=keys,
    )


def _config_candidate(
    field_key: str,
    *,
    config_path: Path | None,
    config_data: Mapping[str, Any],
    valuation_date: date,
    observed_at: str | None,
) -> dict[str, Any]:
    candidate = _finite_float((config_data.get("wacc_params") or {}).get(field_key))
    if config_path is None or candidate is None:
        return _unavailable(
            field_key,
            valuation_date=valuation_date,
            unit="ratio",
            unit_kind="percent",
            reason_code="source_evidence_absent",
            message=f"No local configured {field_key} candidate was supplied.",
            observed_at=observed_at,
            method="configured_policy_assumption",
        )
    return _unavailable(
        field_key,
        valuation_date=valuation_date,
        unit="ratio",
        unit_kind="percent",
        reason_code="source_as_of_missing",
        message=(
            f"The local {field_key} has no authoritative upstream locator or as-of date; "
            "it is retained only as an unverified policy candidate."
        ),
        candidate_value=candidate,
        source_value=candidate,
        source_unit="ratio",
        source_name=CONFIG_SOURCE_NAME,
        source_locator=f"{config_path.as_posix()}::wacc_params.{field_key}",
        observed_at=observed_at,
        method="configured_policy_assumption",
        transformation="none",
        quality_flags={"authoritative_upstream_locator_missing", "source_as_of_missing"},
    )


def _reconcile(name: str, reported: dict[str, Any], components: Iterable[dict[str, Any]]) -> dict[str, Any]:
    parts = list(components)
    if reported.get("status") != "available" or any(part.get("status") != "available" for part in parts):
        return {
            "name": name,
            "status": "unavailable",
            "reported_value": reported.get("value"),
            "component_total": None,
            "difference": None,
            "components": [part["field_key"] for part in parts],
        }
    reported_value = float(reported["value"])
    total = sum(float(part["value"]) for part in parts)
    difference = reported_value - total
    return {
        "name": name,
        "status": "tied" if abs(difference) < 0.5 else "difference",
        "reported_value": reported_value,
        "component_total": total,
        "difference": difference,
        "components": [part["field_key"] for part in parts],
    }


def _consensus_packet(
    target_facts: Iterable[Mapping[str, Any]],
    *,
    valuation_date: date,
    observed_at: str | None,
) -> dict[str, Any]:
    facts = list(target_facts)
    observations: list[dict[str, Any]] = []
    for metric_key, metric, relative_period, offset in _CONSENSUS_METRICS:
        is_eps = metric == "diluted_eps"
        fact = _pick_fact(facts, sheet_name="Detailed Comps", metric_key=metric_key)
        item = _from_fact(
            f"consensus_{metric}_{relative_period.lower().replace('+', '_plus_')}",
            fact,
            valuation_date=valuation_date,
            observed_at=observed_at,
            unit="USD_per_share" if is_eps else "USD",
            unit_kind="currency_per_share" if is_eps else "currency",
            source_unit="USD/share" if is_eps else "USD mm",
            transform=(lambda value: value) if is_eps else (lambda value: value * 1_000_000.0),
            transformation="none" if is_eps else "multiply source USD mm by 1,000,000",
            require_source_date=True,
            method="CIQ estimate aggregate; statistic not encoded in source formula",
            extra_flags={"consensus_statistic_unspecified"},
        )
        item.update(
            {
                "metric": metric,
                "estimate_status": "estimate",
                "period_basis": "relative_calendar_year",
                "relative_period": relative_period,
                "relative_period_offset": offset,
                "normalized_period": None,
                "normalized_period_reason": "source_timestamp_missing",
                "consensus_statistic": "unspecified",
            }
        )
        observations.append(item)
    candidate_count = sum(item.get("candidate_value") is not None for item in observations)
    usable_count = sum(item.get("status") == "available" for item in observations)
    if usable_count:
        reason_code = message = None
        status = "available"
    elif candidate_count:
        status = "unavailable"
        reason_code = "frozen_snapshot_timestamp_missing"
        message = (
            "CIQ consensus candidates exist, but DateToday formulas have no persisted "
            "source timestamp, so relative CY periods cannot form an as-of-matched snapshot."
        )
    else:
        status = "unavailable"
        reason_code = "consensus_evidence_absent"
        message = "No requested CIQ consensus facts exist in the selected source run."
    return {
        "status": status,
        "reason_code": reason_code,
        "message": message,
        "source_as_of_date": None,
        "source_timestamp": None,
        "observed_at": observed_at,
        "period_definition": (
            "CY+N is preserved as a relative calendar-year horizon; an absolute year is "
            "unavailable without a verified source timestamp."
        ),
        "observations": observations,
        "coverage": {
            "requested_count": len(observations),
            "candidate_count": candidate_count,
            "usable_count": usable_count,
            "missing_count": len(observations) - candidate_count,
        },
    }


def build_professional_model_evidence(
    conn: sqlite3.Connection,
    *,
    ticker: str,
    run_id: int,
    valuation_date: date | datetime | str,
    config_path: str | Path | None = None,
) -> dict[str, Any]:
    """Build a deterministic source-labelled packet for one explicit CIQ run."""

    normalized_ticker = str(ticker).strip().upper()
    if not normalized_ticker:
        raise ValueError("ticker is required")
    if int(run_id) <= 0:
        raise ValueError("run_id must be positive")
    value_date = _as_date(valuation_date)
    run = _one_dict(
        conn,
        """SELECT id, source_file, file_hash, ticker, parser_version, ingest_ts,
                  status, as_of_date
           FROM ciq_ingest_runs WHERE id = ? LIMIT 1""",
        [int(run_id)],
    )
    if run is None:
        raise ValueError(f"CIQ ingest run {run_id} does not exist")
    run_ticker = str(run.get("ticker") or "").upper()
    if run_ticker and run_ticker != normalized_ticker:
        raise ValueError(f"CIQ ingest run {run_id} belongs to {run_ticker}, not {normalized_ticker}")
    run_status = str(run.get("status") or "").strip().lower()
    if run_status != "completed":
        raise ValueError(f"CIQ ingest run {run_id} is not completed: {run_status or 'missing'}")

    facts = _fetch_dicts(
        conn,
        """SELECT run_id, ticker, sheet_name, row_index, column_index, row_label,
                  metric_key, period_date, calc_type, column_label, cell_locator,
                  value_raw, value_num, unit, scale_factor, source_file,
                  formula_text, cached_value, has_formula, has_cached_value,
                  formula_status, formula_error, cached_error
           FROM ciq_source_facts_v2
           WHERE run_id = ? AND ticker = ?
           ORDER BY sheet_name, row_index, column_index""",
        [int(run_id), normalized_ticker],
    )
    observed_at = _iso_timestamp(run.get("ingest_ts"))
    run_as_of = str(run.get("as_of_date") or "") or None
    target_rows = sorted(
        {
            int(fact.get("row_index") or 0)
            for fact in facts
            if fact.get("sheet_name") == "Detailed Comps"
            and _ticker_from_row_label(fact.get("row_label")) == normalized_ticker
        }
    )
    target_row = target_rows[0] if len(target_rows) == 1 else None
    target_facts = [
        fact
        for fact in facts
        if fact.get("sheet_name") == "Detailed Comps"
        and target_row is not None
        and int(fact.get("row_index") or 0) == target_row
    ]

    fields: dict[str, dict[str, Any]] = {}
    market_specs = {
        "current_price": ("stock_price", "USD_per_share", "currency_per_share", "USD/share", lambda v: v, "none"),
        "shares_outstanding": ("shares_out", "shares", "count", "shares mm", lambda v: v * 1_000_000.0, "multiply source shares mm by 1,000,000"),
        "market_cap": ("market_cap", "USD", "currency", "USD mm", lambda v: v * 1_000_000.0, "multiply source USD mm by 1,000,000"),
    }
    for field_key, (metric, unit, kind, source_unit, transform, transformation) in market_specs.items():
        fact = _pick_fact(
            target_facts,
            sheet_name="Detailed Comps",
            metric_key=metric,
            row_index=target_row,
        ) if target_row is not None else None
        if len(target_rows) > 1:
            fields[field_key] = _unavailable(
                field_key,
                valuation_date=value_date,
                unit=unit,
                unit_kind=kind,
                reason_code="ambiguous_target_row",
                message=f"Multiple Detailed Comps rows match {normalized_ticker}: {target_rows}.",
                observed_at=observed_at,
            )
        else:
            fields[field_key] = _from_fact(
                field_key,
                fact,
                valuation_date=value_date,
                observed_at=observed_at,
                unit=unit,
                unit_kind=kind,
                source_unit=source_unit,
                transform=transform,
                transformation=transformation,
                require_source_date=True,
                method="CIQ DateToday cached observation",
            )

    statement_specs = {
        "total_debt": ("debt", "USD mm", lambda v: v * 1_000_000.0, "multiply source USD mm by 1,000,000"),
        "total_debt_excluding_leases": ("total_debt_excl_leases", "USD mm", lambda v: v * 1_000_000.0, "multiply source USD mm by 1,000,000"),
        "finance_lease_liabilities": ("total_finance_leases", "USD mm", lambda v: v * 1_000_000.0, "multiply source USD mm by 1,000,000"),
        "operating_lease_liabilities": ("total_operating_leases", "USD mm", lambda v: v * 1_000_000.0, "multiply source USD mm by 1,000,000"),
        "lease_liabilities": ("total_leases", "USD mm", lambda v: v * 1_000_000.0, "multiply source USD mm by 1,000,000"),
        "finance_leases_current": ("finance_leases_current", "USD mm", lambda v: v * 1_000_000.0, "multiply source USD mm by 1,000,000"),
        "finance_leases_long_term": ("finance_leases_long_term", "USD mm", lambda v: v * 1_000_000.0, "multiply source USD mm by 1,000,000"),
        "operating_leases_current": ("current_portion_of_operating_lease_liabilities", "USD mm", lambda v: v * 1_000_000.0, "multiply source USD mm by 1,000,000"),
        "operating_leases_long_term": ("long_term_portion_of_operating_lease_liabilities", "USD mm", lambda v: v * 1_000_000.0, "multiply source USD mm by 1,000,000"),
        "interest_expense_ltm": ("interest_expense_incl_cap_interest", "USD mm", lambda v: abs(v) * 1_000_000.0, "absolute value then multiply source USD mm by 1,000,000"),
        "tax_rate": ("effective_tax_rate", "%", lambda v: v / 100.0, "divide source percentage by 100"),
    }
    for field_key, (metric, source_unit, transform, transformation) in statement_specs.items():
        is_tax = field_key == "tax_rate"
        fields[field_key] = _from_fact(
            field_key,
            _pick_fact(facts, sheet_name="Financial Statements", metric_key=metric, period_date=run_as_of),
            valuation_date=value_date,
            observed_at=observed_at,
            unit="ratio" if is_tax else "USD",
            unit_kind="percent" if is_tax else "currency",
            source_unit=source_unit,
            transform=transform,
            transformation=transformation,
            require_source_date=False,
            method="reported effective tax rate" if is_tax else "reported CIQ statement fact",
        )

    fields["current_lease_liabilities"] = _sum_field(
        "current_lease_liabilities",
        [fields["finance_leases_current"], fields["operating_leases_current"]],
        valuation_date=value_date,
        observed_at=observed_at,
        method="finance leases current plus operating leases current",
    )
    fields["long_term_lease_liabilities"] = _sum_field(
        "long_term_lease_liabilities",
        [fields["finance_leases_long_term"], fields["operating_leases_long_term"]],
        valuation_date=value_date,
        observed_at=observed_at,
        method="finance leases long term plus operating leases long term",
    )
    fields["cost_of_debt_proxy_total_debt"] = _cost_proxy(
        "cost_of_debt_proxy_total_debt",
        fields["interest_expense_ltm"],
        fields["total_debt"],
        valuation_date=value_date,
        observed_at=observed_at,
        method="LTM interest expense / period-end total debt including leases",
    )
    fields["cost_of_debt_proxy_borrowings_only"] = _cost_proxy(
        "cost_of_debt_proxy_borrowings_only",
        fields["interest_expense_ltm"],
        fields["total_debt_excluding_leases"],
        valuation_date=value_date,
        observed_at=observed_at,
        method="LTM interest expense / period-end debt excluding leases",
    )
    fields["cost_of_debt"] = _unavailable(
        "cost_of_debt",
        valuation_date=value_date,
        unit="ratio",
        unit_kind="percent",
        reason_code="methodology_not_selected",
        message=(
            "Source-backed proxies are exposed separately; selecting the debt denominator "
            "or another method remains a PM/finance-model decision."
        ),
        observed_at=observed_at,
        method="not selected",
        components=("cost_of_debt_proxy_total_debt", "cost_of_debt_proxy_borrowings_only"),
    )

    config_file = Path(config_path) if config_path is not None else None
    config_data: Mapping[str, Any] = {}
    if config_file is not None and config_file.exists():
        loaded = yaml.safe_load(config_file.read_text(encoding="utf-8")) or {}
        if isinstance(loaded, Mapping):
            config_data = loaded
    fields["risk_free_rate"] = _config_candidate(
        "risk_free_rate",
        config_path=config_file,
        config_data=config_data,
        valuation_date=value_date,
        observed_at=observed_at,
    )
    fields["equity_risk_premium"] = _config_candidate(
        "equity_risk_premium",
        config_path=config_file,
        config_data=config_data,
        valuation_date=value_date,
        observed_at=observed_at,
    )

    beta_fact = next(
        (fact for fact in target_facts if str(fact.get("metric_key") or "") in {"beta", "levered_beta", "raw_beta"}),
        None,
    )
    beta_candidate = _finite_float(beta_fact.get("value_num")) if beta_fact else None
    if beta_candidate is None:
        fields["beta"] = _unavailable(
            "beta",
            valuation_date=value_date,
            unit="x",
            unit_kind="multiple",
            reason_code="source_evidence_absent",
            message="No source-backed beta or beta methodology exists in the selected CIQ run.",
            observed_at=observed_at,
        )
    else:
        fields["beta"] = _unavailable(
            "beta",
            valuation_date=value_date,
            unit="x",
            unit_kind="multiple",
            reason_code="beta_methodology_missing",
            message="A beta candidate exists, but its estimation methodology is not source-labelled.",
            candidate_value=beta_candidate,
            source_value=beta_candidate,
            source_unit="x",
            source_name=CIQ_SOURCE_NAME,
            source_locator=_locator(beta_fact),
            source_formula=beta_fact.get("formula_text"),
            source_as_of=_optional_date(beta_fact.get("period_date")),
            observed_at=observed_at,
            quality_flags=_fact_quality_flags(beta_fact),
        )

    consensus = _consensus_packet(target_facts, valuation_date=value_date, observed_at=observed_at)
    reconciliations = {
        "lease_total": _reconcile(
            "reported total leases vs finance plus operating leases",
            fields["lease_liabilities"],
            [fields["finance_lease_liabilities"], fields["operating_lease_liabilities"]],
        ),
        "lease_maturity": _reconcile(
            "reported total leases vs current plus long-term leases",
            fields["lease_liabilities"],
            [fields["current_lease_liabilities"], fields["long_term_lease_liabilities"]],
        ),
        "debt_total": _reconcile(
            "reported total debt vs debt excluding leases plus total leases",
            fields["total_debt"],
            [fields["total_debt_excluding_leases"], fields["lease_liabilities"]],
        ),
    }
    core_available = sum(fields[key]["status"] == "available" for key in CORE_FIELD_KEYS)
    core_candidates = sum(fields[key].get("candidate_value") is not None for key in CORE_FIELD_KEYS)
    payload: dict[str, Any] = {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "ticker": normalized_ticker,
        "valuation_date": value_date.isoformat(),
        "currency": "USD",
        "source_run": {
            "run_id": int(run["id"]),
            "source_file": run.get("source_file"),
            "source_hash": run.get("file_hash"),
            "parser_version": run.get("parser_version"),
            "run_status": run.get("status"),
            "ingest_timestamp": observed_at,
            "financial_period_as_of": run_as_of,
            "source_refresh_timestamp": None,
            "market_and_consensus_timestamp": None,
            "target_comps_row": target_row,
        },
        "fields": dict(sorted(fields.items())),
        "consensus": consensus,
        "reconciliations": dict(sorted(reconciliations.items())),
        "methodology_state": {
            "final_wacc_methodology_selected": False,
            "cost_of_debt_methodology_selected": False,
            "tax_rate_methodology_selected": False,
            "stale_threshold_selected": False,
        },
        "coverage": {
            "core_requested_count": len(CORE_FIELD_KEYS),
            "core_available_count": core_available,
            "core_unavailable_count": len(CORE_FIELD_KEYS) - core_available,
            "core_candidate_only_count": core_candidates,
            "consensus_candidate_count": consensus["coverage"]["candidate_count"],
            "consensus_usable_count": consensus["coverage"]["usable_count"],
        },
    }
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    payload["evidence_hash"] = hashlib.sha256(canonical).hexdigest()
    return payload


__all__ = ["CORE_FIELD_KEYS", "EVIDENCE_SCHEMA_VERSION", "build_professional_model_evidence"]
