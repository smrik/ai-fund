"""Dashboard-facing override workbench for previewing and applying valuation changes."""
from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any

import yaml

from db.loader import insert_valuation_override_audit
from db.schema import create_tables, get_connection
from src.stage_02_valuation.input_assembler import (
    OVERRIDES_PATH,
    build_valuation_inputs,
    clear_valuation_overrides_cache,
)
from src.stage_02_valuation.professional_dcf import (
    ForecastDrivers,
    default_scenario_specs,
    run_probabilistic_valuation,
)
from src.stage_04_pipeline.recommendations import load_recommendations


DISPLAY_FIELDS: list[tuple[str, str, str]] = [
    ("revenue_growth_near", "Revenue Growth (Near)", "pct"),
    ("revenue_growth_mid", "Revenue Growth (Mid)", "pct"),
    ("ebit_margin_start", "EBIT Margin (Start)", "pct"),
    ("ebit_margin_target", "EBIT Margin (Target)", "pct"),
    ("tax_rate_start", "Tax Rate (Start)", "pct"),
    ("tax_rate_target", "Tax Rate (Target)", "pct"),
    ("capex_pct_start", "Capex % (Start)", "pct"),
    ("capex_pct_target", "Capex % (Target)", "pct"),
    ("da_pct_start", "D&A % (Start)", "pct"),
    ("da_pct_target", "D&A % (Target)", "pct"),
    ("dso_start", "DSO (Start)", "days"),
    ("dio_start", "DIO (Start)", "days"),
    ("dpo_start", "DPO (Start)", "days"),
    ("wacc", "WACC", "pct"),
    ("exit_multiple", "Exit Multiple", "x"),
    ("net_debt", "Net Debt", "usd"),
    ("non_operating_assets", "Non-Operating Assets", "usd"),
    ("lease_liabilities", "Lease Liabilities", "usd"),
    ("minority_interest", "Minority Interest", "usd"),
    ("preferred_equity", "Preferred Equity", "usd"),
    ("pension_deficit", "Pension Deficit", "usd"),
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _approx_equal(left: float | None, right: float | None, tol: float = 1e-9) -> bool:
    if left is None and right is None:
        return True
    if left is None or right is None:
        return False
    return abs(float(left) - float(right)) <= tol


def _load_overrides_data() -> dict[str, Any]:
    if not OVERRIDES_PATH.exists():
        return {"global": {}, "sectors": {}, "tickers": {}}
    data = yaml.safe_load(OVERRIDES_PATH.read_text(encoding="utf-8")) or {}
    data.setdefault("global", {})
    data.setdefault("sectors", {})
    data.setdefault("tickers", {})
    return data


def _write_overrides_data(data: dict[str, Any]) -> None:
    OVERRIDES_PATH.parent.mkdir(parents=True, exist_ok=True)
    OVERRIDES_PATH.write_text(
        yaml.dump(data, default_flow_style=False, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def _recommendation_map(ticker: str) -> dict[str, Any]:
    recs = load_recommendations(ticker)
    if recs is None:
        return {}
    out: dict[str, Any] = {}
    for rec in recs.recommendations:
        if isinstance(rec.proposed_value, (int, float)):
            out[rec.field] = rec
    return out


def _field_rows(
    ticker: str,
    baseline_inputs: Any,
    effective_inputs: Any,
) -> list[dict[str, Any]]:
    recommendation_map = _recommendation_map(ticker)
    overrides = _load_overrides_data()
    ticker_overrides = overrides.get("tickers", {}).get(ticker.upper(), {})

    rows: list[dict[str, Any]] = []
    for field, label, unit in DISPLAY_FIELDS:
        if not hasattr(baseline_inputs.drivers, field) or not hasattr(effective_inputs.drivers, field):
            continue

        baseline_value = getattr(baseline_inputs.drivers, field)
        effective_value = getattr(effective_inputs.drivers, field)
        rec = recommendation_map.get(field)
        agent_value = float(rec.proposed_value) if rec and isinstance(rec.proposed_value, (int, float)) else None

        initial_mode = "default"
        if rec is not None and _approx_equal(effective_value, agent_value):
            initial_mode = "agent"
        elif not _approx_equal(effective_value, baseline_value):
            initial_mode = "custom"

        rows.append(
            {
                "field": field,
                "label": label,
                "unit": unit,
                "baseline_value": float(baseline_value) if baseline_value is not None else None,
                "baseline_source": baseline_inputs.source_lineage.get(field),
                "effective_value": float(effective_value) if effective_value is not None else None,
                "effective_source": effective_inputs.source_lineage.get(field),
                "ticker_override_value": ticker_overrides.get(field),
                "ticker_override_present": field in ticker_overrides,
                "agent_value": agent_value,
                "agent_name": rec.agent if rec else None,
                "agent_confidence": rec.confidence if rec else None,
                "agent_status": rec.status if rec else None,
                "agent_rationale": rec.rationale if rec else None,
                "agent_citation": rec.citation if rec else None,
                "initial_mode": initial_mode,
            }
        )
    return rows


def build_override_workbench(ticker: str) -> dict[str, Any]:
    ticker = ticker.upper().strip()
    baseline_inputs = build_valuation_inputs(ticker, apply_overrides=False)
    effective_inputs = build_valuation_inputs(ticker, apply_overrides=True)
    if baseline_inputs is None or effective_inputs is None:
        return {"ticker": ticker, "available": False, "fields": []}

    current_result = run_probabilistic_valuation(
        effective_inputs.drivers,
        default_scenario_specs(),
        current_price=effective_inputs.current_price,
    )
    return {
        "ticker": ticker,
        "available": True,
        "company_name": effective_inputs.company_name,
        "sector": effective_inputs.sector,
        "industry": effective_inputs.industry,
        "current_price": effective_inputs.current_price,
        "current_iv_base": round(current_result.scenario_results["base"].intrinsic_value_per_share, 2),
        "current_expected_iv": round(current_result.expected_iv, 2),
        "fields": _field_rows(ticker, baseline_inputs, effective_inputs),
    }


def _resolved_value(row: dict[str, Any], mode: str, custom_values: dict[str, float | None]) -> tuple[float | None, str]:
    field = row["field"]
    if mode == "default":
        return row["baseline_value"], "default"
    if mode == "agent":
        return row["agent_value"], "agent"
    if mode == "custom":
        return custom_values.get(field), "custom"
    raise ValueError(f"Unknown selection mode: {mode}")


def _valuation_to_dict(result: Any) -> dict[str, Any]:
    scenarios = {
        name: round(item.intrinsic_value_per_share, 2)
        for name, item in (result.scenario_results or {}).items()
    }
    return {
        "scenarios": scenarios,
        "expected_iv": round(result.expected_iv, 2) if result.expected_iv is not None else None,
        "expected_upside_pct": result.expected_upside_pct,
    }


def _replace_drivers(drivers: ForecastDrivers, resolved: dict[str, float]) -> ForecastDrivers:
    payload = asdict(drivers)
    payload.update(resolved)
    return ForecastDrivers(**payload)


def preview_override_selections(
    ticker: str,
    selections: dict[str, str],
    custom_values: dict[str, float | None] | None = None,
) -> dict[str, Any]:
    ticker = ticker.upper().strip()
    custom_values = custom_values or {}
    baseline_inputs = build_valuation_inputs(ticker, apply_overrides=False)
    effective_inputs = build_valuation_inputs(ticker, apply_overrides=True)
    if baseline_inputs is None or effective_inputs is None:
        return {}

    rows = _field_rows(ticker, baseline_inputs, effective_inputs)
    row_map = {row["field"]: row for row in rows}
    specs = default_scenario_specs()

    current_result = run_probabilistic_valuation(
        effective_inputs.drivers,
        specs,
        current_price=effective_inputs.current_price,
    )
    current_iv = _valuation_to_dict(current_result)

    resolved_values: dict[str, dict[str, Any]] = {}
    replacement_values: dict[str, float] = {}
    for field, mode in selections.items():
        row = row_map.get(field)
        if row is None:
            continue
        value, resolved_mode = _resolved_value(row, mode, custom_values)
        if value is None:
            continue
        replacement_values[field] = float(value)
        resolved_values[field] = {
            "mode": resolved_mode,
            "value": float(value),
            "baseline_value": row["baseline_value"],
            "effective_value": row["effective_value"],
            "agent_value": row["agent_value"],
        }

    proposed_drivers = _replace_drivers(effective_inputs.drivers, replacement_values)
    proposed_result = run_probabilistic_valuation(
        proposed_drivers,
        specs,
        current_price=effective_inputs.current_price,
    )
    proposed_iv = _valuation_to_dict(proposed_result)

    delta_pct: dict[str, float | None] = {}
    for scenario, current_value in current_iv["scenarios"].items():
        proposed_value = proposed_iv["scenarios"].get(scenario)
        if current_value and proposed_value is not None:
            delta_pct[scenario] = round((proposed_value / current_value - 1.0) * 100.0, 1)
        else:
            delta_pct[scenario] = None

    return {
        "ticker": ticker,
        "resolved_values": resolved_values,
        "current_iv": current_iv["scenarios"],
        "proposed_iv": proposed_iv["scenarios"],
        "current_expected_iv": current_iv["expected_iv"],
        "proposed_expected_iv": proposed_iv["expected_iv"],
        "delta_pct": delta_pct,
    }


def apply_override_selections(
    ticker: str,
    selections: dict[str, str],
    custom_values: dict[str, float | None] | None = None,
    actor: str = "dashboard",
) -> dict[str, Any]:
    ticker = ticker.upper().strip()
    custom_values = custom_values or {}

    baseline_inputs = build_valuation_inputs(ticker, apply_overrides=False)
    effective_inputs = build_valuation_inputs(ticker, apply_overrides=True)
    if baseline_inputs is None or effective_inputs is None:
        return {"ticker": ticker, "applied_count": 0, "applied_fields": []}

    rows = _field_rows(ticker, baseline_inputs, effective_inputs)
    row_map = {row["field"]: row for row in rows}
    preview = preview_override_selections(ticker, selections=selections, custom_values=custom_values)

    overrides = _load_overrides_data()
    ticker_overrides = overrides.setdefault("tickers", {}).setdefault(ticker, {})
    current_iv_json = json.dumps(preview.get("current_iv", {}))
    proposed_iv_json = json.dumps(preview.get("proposed_iv", {}))
    event_ts = _now()

    audit_rows: list[dict[str, Any]] = []
    applied_fields: list[str] = []
    for field, mode in selections.items():
        row = row_map.get(field)
        if row is None:
            continue
        resolved_value, _ = _resolved_value(row, mode, custom_values)
        if resolved_value is None:
            continue

        prior_override = ticker_overrides.get(field)
        write_action = "noop"
        resulting_override = prior_override

        if mode == "default":
            baseline_value = row["baseline_value"]
            if _approx_equal(row["effective_value"], baseline_value):
                ticker_overrides.pop(field, None)
                resulting_override = None
                write_action = "remove_ticker_override"
            else:
                ticker_overrides[field] = float(baseline_value)
                resulting_override = float(baseline_value)
                write_action = "set_ticker_override_to_baseline"
        else:
            ticker_overrides[field] = float(resolved_value)
            resulting_override = float(resolved_value)
            write_action = "set_ticker_override"

        audit_rows.append(
            {
                "event_ts": event_ts,
                "ticker": ticker,
                "actor": actor,
                "field": field,
                "selection_mode": mode,
                "baseline_value": row["baseline_value"],
                "baseline_source": row["baseline_source"],
                "effective_value_before": row["effective_value"],
                "effective_source_before": row["effective_source"],
                "agent_value": row["agent_value"],
                "agent_status": row["agent_status"],
                "agent_confidence": row["agent_confidence"],
                "custom_value": custom_values.get(field),
                "applied_value": float(resolved_value),
                "prior_ticker_override_value": prior_override,
                "resulting_ticker_override_value": resulting_override,
                "write_action": write_action,
                "current_iv_json": current_iv_json,
                "proposed_iv_json": proposed_iv_json,
                "current_iv_base": preview.get("current_iv", {}).get("base"),
                "proposed_iv_base": preview.get("proposed_iv", {}).get("base"),
                "current_expected_iv": preview.get("current_expected_iv"),
                "proposed_expected_iv": preview.get("proposed_expected_iv"),
            }
        )
        applied_fields.append(field)

    if not ticker_overrides:
        overrides["tickers"].pop(ticker, None)

    _write_overrides_data(overrides)
    clear_valuation_overrides_cache()

    conn = get_connection()
    try:
        create_tables(conn)
        insert_valuation_override_audit(conn, audit_rows)
    finally:
        conn.close()

    return {
        "ticker": ticker,
        "applied_count": len(applied_fields),
        "applied_fields": applied_fields,
        "preview": preview,
    }


def load_override_audit_history(ticker: str, limit: int = 50) -> list[dict[str, Any]]:
    ticker = ticker.upper().strip()
    conn = get_connection()
    try:
        create_tables(conn)
        rows = conn.execute(
            """
            SELECT event_ts, ticker, actor, field, selection_mode, baseline_value,
                   baseline_source, effective_value_before, effective_source_before,
                   agent_value, agent_status, agent_confidence, custom_value,
                   applied_value, prior_ticker_override_value,
                   resulting_ticker_override_value, write_action,
                   current_iv_json, proposed_iv_json,
                   current_iv_base, proposed_iv_base,
                   current_expected_iv, proposed_expected_iv
            FROM valuation_override_audit
            WHERE ticker = ?
            ORDER BY event_ts DESC, id DESC
            LIMIT ?
            """,
            [ticker, max(1, int(limit))],
        ).fetchall()
    finally:
        conn.close()

    return [dict(row) for row in rows]
