from __future__ import annotations

from dataclasses import asdict

from src.stage_02_valuation.input_assembler import build_valuation_inputs
from src.stage_02_valuation.professional_dcf import (
    ForecastDrivers,
    ScenarioSpec,
    default_scenario_specs,
    run_dcf_professional,
    run_probabilistic_valuation,
)
from src.stage_02_valuation.templates.ic_memo import RiskImpactOutput
from src.stage_04_pipeline.risk_impact import quantify_risk_impact


def _pct(value: float | None) -> float | None:
    if value is None:
        return None
    return round(float(value) * 100.0, 2)


def _usd_mm(value: float | None) -> float | None:
    if value is None:
        return None
    return round(float(value) / 1_000_000.0, 2)


def _scenario_summary(prob_result, current_price: float | None) -> list[dict]:
    rows: list[dict] = []
    weights = {spec.name: spec.probability for spec in default_scenario_specs()}
    for name in ("bear", "base", "bull"):
        result = prob_result.scenario_results.get(name)
        if result is None:
            continue
        iv = round(result.intrinsic_value_per_share, 2)
        upside = None
        if current_price and current_price > 0:
            upside = round((iv / current_price - 1.0) * 100.0, 1)
        rows.append(
            {
                "scenario": name,
                "probability_pct": round(weights.get(name, 0.0) * 100.0, 1),
                "intrinsic_value": iv,
                "upside_pct": upside,
            }
        )
    rows.append(
        {
            "scenario": "expected",
            "probability_pct": 100.0,
            "intrinsic_value": round(prob_result.expected_iv, 2),
            "upside_pct": round((prob_result.expected_upside_pct or 0.0) * 100.0, 1)
            if prob_result.expected_upside_pct is not None
            else None,
        }
    )
    return rows


def _forecast_bridge(base_result) -> list[dict]:
    rows: list[dict] = []
    for year in base_result.projections:
        rows.append(
            {
                "year": year.year,
                "revenue_mm": _usd_mm(year.revenue),
                "growth_pct": _pct(year.growth_rate),
                "ebit_margin_pct": _pct(year.ebit_margin),
                "ebit_mm": _usd_mm(year.ebit),
                "nopat_mm": _usd_mm(year.nopat),
                "capex_mm": _usd_mm(year.capex),
                "da_mm": _usd_mm(year.da),
                "delta_nwc_mm": _usd_mm(year.delta_nwc),
                "fcff_mm": _usd_mm(year.fcff),
                "roic_pct": _pct(year.roic),
            }
        )
    return rows


def _terminal_bridge(base_result) -> dict:
    terminal = base_result.terminal_breakdown
    return {
        "method_used": terminal.method_used,
        "gordon_formula_mode": terminal.gordon_formula_mode,
        "terminal_growth_pct": _pct(terminal.terminal_growth),
        "ronic_terminal_pct": _pct(terminal.ronic_terminal),
        "fcff_11_bridge_mm": _usd_mm(terminal.fcff_11_bridge),
        "fcff_11_value_driver_mm": _usd_mm(terminal.fcff_11_value_driver),
        "tv_gordon_mm": _usd_mm(terminal.tv_gordon),
        "tv_exit_mm": _usd_mm(terminal.tv_exit),
        "tv_blended_mm": _usd_mm(terminal.tv_blended),
        "pv_tv_gordon_mm": _usd_mm(terminal.pv_tv_gordon),
        "pv_tv_exit_mm": _usd_mm(terminal.pv_tv_exit),
        "pv_tv_blended_mm": _usd_mm(terminal.pv_tv_blended),
        "tv_pct_of_ev": round((base_result.tv_pct_of_ev or 0.0) * 100.0, 1)
        if base_result.tv_pct_of_ev is not None
        else None,
    }


def _ev_bridge(base_result) -> dict:
    return {
        "enterprise_value_operations": _usd_mm(base_result.enterprise_value_operations),
        "enterprise_value_operations_mm": _usd_mm(base_result.enterprise_value_operations),
        "pv_fcff_sum_mm": _usd_mm(base_result.pv_fcff_sum),
        "non_operating_assets": _usd_mm(base_result.non_operating_assets),
        "non_operating_assets_mm": _usd_mm(base_result.non_operating_assets),
        "enterprise_value_total": _usd_mm(base_result.enterprise_value_total),
        "enterprise_value_total_mm": _usd_mm(base_result.enterprise_value_total),
        "non_equity_claims": _usd_mm(base_result.non_equity_claims),
        "non_equity_claims_mm": _usd_mm(base_result.non_equity_claims),
        "equity_value": _usd_mm(base_result.equity_value),
        "equity_value_mm": _usd_mm(base_result.equity_value),
        "intrinsic_value_per_share": round(base_result.intrinsic_value_per_share, 2),
        "ep_intrinsic_value_per_share": round(base_result.ep_intrinsic_value_per_share, 2)
        if base_result.ep_intrinsic_value_per_share is not None
        else None,
        "fcfe_intrinsic_value_per_share": round(base_result.fcfe_intrinsic_value_per_share, 2)
        if base_result.fcfe_intrinsic_value_per_share is not None
        else None,
    }


def _driver_rows(drivers: ForecastDrivers, source_lineage: dict[str, str]) -> list[dict]:
    fields = [
        ("revenue_growth_near", "Revenue Growth Near", "pct"),
        ("revenue_growth_mid", "Revenue Growth Mid", "pct"),
        ("revenue_growth_terminal", "Terminal Growth", "pct"),
        ("ebit_margin_start", "EBIT Margin Start", "pct"),
        ("ebit_margin_target", "EBIT Margin Target", "pct"),
        ("wacc", "WACC", "pct"),
        ("exit_multiple", "Exit Multiple", "raw"),
        ("net_debt", "Net Debt", "usd_mm"),
    ]
    rows: list[dict] = []
    for field, label, unit in fields:
        value = getattr(drivers, field)
        if unit == "pct":
            display = _pct(value)
        elif unit == "usd_mm":
            display = _usd_mm(value)
        else:
            display = round(float(value), 2)
        rows.append(
            {
                "field": field,
                "label": label,
                "value": display,
                "source": source_lineage.get(field, "unknown"),
            }
        )
    return rows


def _sensitivity_matrix(
    drivers: ForecastDrivers,
    *,
    grid: str,
) -> list[dict]:
    rows: list[dict] = []
    base = ScenarioSpec(name="base", probability=1.0)

    if grid == "wacc_x_terminal_growth":
        wacc_values = [max(0.03, min(0.20, drivers.wacc + delta)) for delta in (-0.01, 0.0, 0.01)]
        growth_values = [
            max(0.0, min(0.05, drivers.revenue_growth_terminal + delta))
            for delta in (-0.005, 0.0, 0.005)
        ]
        for wacc in wacc_values:
            row = {"wacc_pct": round(wacc * 100.0, 2)}
            for growth in growth_values:
                adjusted = ForecastDrivers(**{**asdict(drivers), "wacc": wacc, "revenue_growth_terminal": growth})
                result = run_dcf_professional(adjusted, base)
                row[f"g_{growth*100:.2f}%"] = round(result.intrinsic_value_per_share, 2)
            rows.append(row)
        return rows

    exit_values = [max(2.0, min(40.0, drivers.exit_multiple * mult)) for mult in (0.9, 1.0, 1.1)]
    wacc_values = [max(0.03, min(0.20, drivers.wacc + delta)) for delta in (-0.01, 0.0, 0.01)]
    for wacc in wacc_values:
        row = {"wacc_pct": round(wacc * 100.0, 2)}
        for multiple in exit_values:
            adjusted = ForecastDrivers(**{**asdict(drivers), "wacc": wacc, "exit_multiple": multiple})
            result = run_dcf_professional(adjusted, base)
            row[f"x_{multiple:.2f}"] = round(result.intrinsic_value_per_share, 2)
        rows.append(row)
    return rows


def _sensitivity_grid_contract(drivers: ForecastDrivers, *, grid: str) -> dict:
    base = ScenarioSpec(name="base", probability=1.0)
    wacc_values = [max(0.03, min(0.20, drivers.wacc + delta)) for delta in (-0.01, 0.0, 0.01)]
    if grid == "wacc_x_terminal_growth":
        column_key = "terminal_growth"
        column_label = "Terminal Growth"
        column_unit = "pct"
        column_values = [
            max(0.0, min(0.05, drivers.revenue_growth_terminal + delta))
            for delta in (-0.005, 0.0, 0.005)
        ]
    else:
        column_key = "exit_multiple"
        column_label = "Exit Multiple"
        column_unit = "multiple"
        column_values = [max(2.0, min(40.0, drivers.exit_multiple * mult)) for mult in (0.9, 1.0, 1.1)]

    cells: list[dict] = []
    iv_values: list[float] = []
    base_case_iv = None
    for wacc in wacc_values:
        for column_value in column_values:
            driver_overrides = {"wacc": wacc}
            if column_key == "terminal_growth":
                driver_overrides["revenue_growth_terminal"] = column_value
            else:
                driver_overrides["exit_multiple"] = column_value
            adjusted = ForecastDrivers(**{**asdict(drivers), **driver_overrides})
            result = run_dcf_professional(adjusted, base)
            iv = round(result.intrinsic_value_per_share, 2)
            iv_values.append(iv)
            is_base_case = wacc == drivers.wacc and column_value in {
                drivers.revenue_growth_terminal,
                drivers.exit_multiple,
            }
            if is_base_case:
                base_case_iv = iv
            cells.append(
                {
                    "grid": grid,
                    "row_axis": "wacc",
                    "row_value": round(wacc, 6),
                    "row_value_pct": round(wacc * 100.0, 2),
                    "column_axis": column_key,
                    "column_value": round(column_value, 6),
                    "column_value_display": round(column_value * 100.0, 2)
                    if column_unit == "pct"
                    else round(column_value, 2),
                    "intrinsic_value": iv,
                    "is_base_case": is_base_case,
                }
            )
    return {
        "grid": grid,
        "label": "WACC x Terminal Growth" if grid == "wacc_x_terminal_growth" else "WACC x Exit Multiple",
        "value_key": "intrinsic_value",
        "row_axis": {"key": "wacc", "label": "WACC", "unit": "pct", "values": [round(v, 6) for v in wacc_values]},
        "column_axis": {
            "key": column_key,
            "label": column_label,
            "unit": column_unit,
            "values": [round(v, 6) for v in column_values],
        },
        "base_case": {
            "wacc": round(drivers.wacc, 6),
            column_key: round(drivers.revenue_growth_terminal if column_key == "terminal_growth" else drivers.exit_multiple, 6),
            "intrinsic_value": base_case_iv,
        },
        "summary": {
            "min_iv": min(iv_values) if iv_values else None,
            "max_iv": max(iv_values) if iv_values else None,
            "spread": round(max(iv_values) - min(iv_values), 2) if iv_values else None,
            "cell_count": len(cells),
        },
        "cells": cells,
    }


def _chart_series(audit: dict, risk_impact_view: dict | None) -> dict:
    projection_curve = [
        {
            "year": row["year"],
            "revenue_mm": row["revenue_mm"],
            "ebit_margin_pct": row["ebit_margin_pct"],
        }
        for row in audit["forecast_bridge"]
    ]
    fcff_curve = [
        {
            "year": row["year"],
            "fcff_mm": row["fcff_mm"],
            "nopat_mm": row["nopat_mm"],
        }
        for row in audit["forecast_bridge"]
    ]
    scenario_iv = [
        {
            "scenario": row["scenario"],
            "intrinsic_value": row["intrinsic_value"],
            "upside_pct": row["upside_pct"],
        }
        for row in audit["scenario_summary"]
    ]
    ev_bridge_waterfall = [
        {"component": "PV Explicit FCFF", "value_mm": audit["ev_bridge"]["pv_fcff_sum_mm"]},
        {"component": "PV Terminal Value", "value_mm": audit["terminal_bridge"]["pv_tv_blended_mm"]},
        {"component": "Non-Operating Assets", "value_mm": audit["ev_bridge"]["non_operating_assets_mm"]},
        {"component": "Non-Equity Claims", "value_mm": -1.0 * (audit["ev_bridge"]["non_equity_claims_mm"] or 0.0)},
        {"component": "Equity Value", "value_mm": audit["ev_bridge"]["equity_value_mm"]},
    ]
    risk_overlay = []
    if risk_impact_view and risk_impact_view.get("available"):
        risk_overlay = [
            {
                "risk_name": row["risk_name"],
                "probability": row["probability"],
                "stressed_iv": row["stressed_iv"],
                "iv_delta_pct": row["iv_delta_pct"],
            }
            for row in risk_impact_view.get("overlay_results", [])
        ]
    return {
        "projection_curve": projection_curve,
        "fcff_curve": fcff_curve,
        "scenario_iv": scenario_iv,
        "ev_bridge_waterfall": ev_bridge_waterfall,
        "risk_overlay": risk_overlay,
    }


def build_dcf_audit_view(
    ticker: str,
    *,
    as_of_date: str | None = None,
    apply_overrides: bool = True,
    risk_output: RiskImpactOutput | None = None,
) -> dict:
    ticker = ticker.upper().strip()
    inputs = build_valuation_inputs(ticker, as_of_date=as_of_date, apply_overrides=apply_overrides)
    if inputs is None:
        return {"ticker": ticker, "available": False}

    prob_result = run_probabilistic_valuation(
        inputs.drivers,
        default_scenario_specs(),
        current_price=inputs.current_price,
    )
    base_result = prob_result.scenario_results["base"]

    risk_impact_view = None
    if risk_output is not None:
        risk_impact_view = quantify_risk_impact(
            ticker,
            risk_output,
            as_of_date=as_of_date,
            apply_overrides=apply_overrides,
        )
    sensitivity_contracts = {
        "wacc_x_terminal_growth": _sensitivity_grid_contract(inputs.drivers, grid="wacc_x_terminal_growth"),
        "wacc_x_exit_multiple": _sensitivity_grid_contract(inputs.drivers, grid="wacc_x_exit_multiple"),
    }

    audit = {
        "ticker": ticker,
        "available": True,
        "company_name": inputs.company_name,
        "sector": inputs.sector,
        "industry": inputs.industry,
        "current_price": inputs.current_price,
        "scenario_summary": _scenario_summary(prob_result, inputs.current_price),
        "forecast_bridge": _forecast_bridge(base_result),
        "terminal_bridge": _terminal_bridge(base_result),
        "ev_bridge": _ev_bridge(base_result),
        "driver_rows": _driver_rows(inputs.drivers, inputs.source_lineage),
        "health_flags": base_result.health_flags or {},
        "model_integrity": {
            "tv_pct_of_ev": round(base_result.tv_pct_of_ev * 100.0, 1) if base_result.tv_pct_of_ev is not None else None,
            "tv_high_flag": bool((base_result.health_flags or {}).get("tv_high_flag", False)),
            "revenue_data_quality_flag": inputs.source_lineage.get("revenue_data_quality_flag", "unknown"),
            "nwc_driver_quality_flag": bool(base_result.nwc_driver_quality_flag),
            "roic_consistency_flag": bool(base_result.roic_consistency_flag),
        },
        "sensitivity": {
            "wacc_x_terminal_growth": _sensitivity_matrix(inputs.drivers, grid="wacc_x_terminal_growth"),
            "wacc_x_exit_multiple": _sensitivity_matrix(inputs.drivers, grid="wacc_x_exit_multiple"),
            "metadata": {
                grid: {
                    "label": payload["label"],
                    "value_key": payload["value_key"],
                    "row_axis": payload["row_axis"],
                    "column_axis": payload["column_axis"],
                    "base_case": payload["base_case"],
                    "summary": payload["summary"],
                }
                for grid, payload in sensitivity_contracts.items()
            },
            "long_form": [
                cell
                for payload in sensitivity_contracts.values()
                for cell in payload["cells"]
            ],
            "summary": [
                {"grid": grid, **payload["summary"]}
                for grid, payload in sensitivity_contracts.items()
            ],
        },
        "risk_impact": risk_impact_view,
    }
    audit["chart_series"] = _chart_series(audit, risk_impact_view)
    return audit
