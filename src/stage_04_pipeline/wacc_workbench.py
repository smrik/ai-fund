from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from db.schema import create_tables, get_connection
from src.stage_00_data.ciq_adapter import get_ciq_comps_detail
from src.stage_02_valuation.input_assembler import (
    OVERRIDES_PATH,
    build_valuation_inputs,
    clear_valuation_overrides_cache,
    load_valuation_overrides,
)
from src.stage_02_valuation.professional_dcf import default_scenario_specs, run_probabilistic_valuation
from src.stage_02_valuation.wacc import WACCResult, blend_wacc_results, compute_wacc_methodology_set_for_ticker


@dataclass(slots=True)
class WACCMethodBreakdown:
    method: str
    wacc: float
    cost_of_equity: float
    cost_of_debt_after_tax: float
    beta_source: str
    beta_value: float | None
    assumptions: dict[str, float | str | None]


METHOD_LABELS = {
    "peer_bottom_up": "Peer Bottom-Up",
    "industry_proxy": "Industry Proxy",
    "self_hamada": "Self Hamada",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


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


def _normalize_selection(
    *,
    mode: str,
    selected_method: str | None = None,
    weights: dict[str, float] | None = None,
) -> dict[str, Any]:
    cleaned_mode = str(mode or "").strip()
    if cleaned_mode not in {"single_method", "blended"}:
        raise ValueError("mode must be 'single_method' or 'blended'")

    if cleaned_mode == "single_method":
        if selected_method not in METHOD_LABELS:
            raise ValueError("selected_method must be one of the supported WACC methods")
        return {
            "mode": "single_method",
            "selected_method": selected_method,
            "weights": {},
        }

    clean_weights = {
        method: float(weight)
        for method, weight in (weights or {}).items()
        if method in METHOD_LABELS and weight is not None
    }
    total = sum(weight for weight in clean_weights.values() if weight > 0)
    if total <= 0:
        raise ValueError("weights must contain at least one positive method weight")
    normalized = {
        method: round(weight / total, 6)
        for method, weight in clean_weights.items()
        if weight > 0
    }
    return {
        "mode": "blended",
        "selected_method": None,
        "weights": normalized,
    }


def _peer_tickers(ticker: str) -> list[str]:
    detail = get_ciq_comps_detail(ticker)
    if not detail:
        return []
    return [
        str(peer.get("ticker") or "").upper()
        for peer in detail.get("peers", [])
        if peer.get("ticker")
    ]


def _compute_method_results(ticker: str) -> dict[str, WACCResult]:
    return compute_wacc_methodology_set_for_ticker(
        ticker,
        peer_tickers=_peer_tickers(ticker),
    )


def _method_to_breakdown(method: str, result: WACCResult) -> WACCMethodBreakdown:
    beta_source = {
        "peer_bottom_up": "peer_unlevered_median",
        "industry_proxy": "industry_proxy_beta",
        "self_hamada": "target_observed_beta",
    }.get(method, "unknown")
    assumptions = {
        "label": METHOD_LABELS.get(method, method),
        "risk_free_rate": result.risk_free_rate,
        "equity_risk_premium": result.equity_risk_premium,
        "size_premium": result.size_premium,
        "equity_weight": result.equity_weight,
        "debt_weight": result.debt_weight,
        "target_de_ratio": result.target_de_ratio,
        "peers_used": ", ".join(result.peers_used[:8]),
    }
    return WACCMethodBreakdown(
        method=method,
        wacc=result.wacc,
        cost_of_equity=result.cost_of_equity,
        cost_of_debt_after_tax=result.cost_of_debt_after_tax,
        beta_source=beta_source,
        beta_value=result.beta_relevered,
        assumptions=assumptions,
    )


def _selection_payload_from_overrides(ticker: str) -> dict[str, Any]:
    overrides = load_valuation_overrides()
    ticker_blob = overrides.get("tickers", {}).get(ticker.upper(), {})
    method_blob = ticker_blob.get("wacc_methodology")
    if not isinstance(method_blob, dict):
        return {"mode": "single_method", "selected_method": "peer_bottom_up", "weights": {}}
    try:
        return _normalize_selection(
            mode=method_blob.get("mode"),
            selected_method=method_blob.get("selected_method"),
            weights=method_blob.get("weights"),
        )
    except ValueError:
        return {"mode": "single_method", "selected_method": "peer_bottom_up", "weights": {}}


def _effective_result(method_results: dict[str, WACCResult], selection: dict[str, Any]) -> WACCResult:
    if selection["mode"] == "single_method":
        return method_results[selection["selected_method"]]
    return blend_wacc_results(method_results, selection["weights"])


def _valuation_to_dict(result: Any) -> dict[str, Any]:
    return {
        "scenarios": {
            name: round(item.intrinsic_value_per_share, 2)
            for name, item in (result.scenario_results or {}).items()
        },
        "expected_iv": round(result.expected_iv, 2) if result.expected_iv is not None else None,
    }


def _clone_inputs_with_wacc(inputs: Any, result: WACCResult):
    payload = asdict(inputs.drivers)
    payload["wacc"] = result.wacc
    payload["cost_of_equity"] = result.cost_of_equity
    payload["debt_weight"] = result.debt_weight
    cloned = inputs.__class__(
        ticker=inputs.ticker,
        company_name=inputs.company_name,
        sector=inputs.sector,
        industry=inputs.industry,
        current_price=inputs.current_price,
        as_of_date=inputs.as_of_date,
        model_applicability_status=inputs.model_applicability_status,
        drivers=inputs.drivers.__class__(**payload),
        source_lineage=dict(inputs.source_lineage),
        ciq_lineage=dict(inputs.ciq_lineage),
        wacc_inputs=dict(inputs.wacc_inputs),
        story_profile=inputs.story_profile,
        story_adjustments=inputs.story_adjustments,
    )
    return cloned


def build_wacc_workbench(ticker: str, apply_overrides: bool = True) -> dict[str, Any]:
    ticker = ticker.upper().strip()
    effective_inputs = build_valuation_inputs(ticker, apply_overrides=apply_overrides)
    if effective_inputs is None:
        return {"ticker": ticker, "available": False, "methods": []}

    method_results = _compute_method_results(ticker)
    selection = _selection_payload_from_overrides(ticker) if apply_overrides else {
        "mode": "single_method",
        "selected_method": "peer_bottom_up",
        "weights": {},
    }
    effective_result = _effective_result(method_results, selection)

    return {
        "ticker": ticker,
        "available": True,
        "company_name": effective_inputs.company_name,
        "sector": effective_inputs.sector,
        "industry": effective_inputs.industry,
        "current_price": effective_inputs.current_price,
        "methods": [asdict(_method_to_breakdown(method, result)) for method, result in method_results.items()],
        "current_selection": selection,
        "effective_preview": {
            "wacc": effective_inputs.drivers.wacc,
            "cost_of_equity": getattr(effective_inputs.drivers, "cost_of_equity", None),
            "debt_weight": getattr(effective_inputs.drivers, "debt_weight", None),
            "expected_method_wacc": effective_result.wacc,
        },
    }


def preview_wacc_methodology_selection(
    ticker: str,
    *,
    mode: str,
    selected_method: str | None = None,
    weights: dict[str, float] | None = None,
) -> dict[str, Any]:
    ticker = ticker.upper().strip()
    effective_inputs = build_valuation_inputs(ticker, apply_overrides=True)
    if effective_inputs is None:
        return {}

    method_results = _compute_method_results(ticker)
    selection = _normalize_selection(mode=mode, selected_method=selected_method, weights=weights)
    selected_result = _effective_result(method_results, selection)
    proposed_inputs = _clone_inputs_with_wacc(effective_inputs, selected_result)

    current_result = run_probabilistic_valuation(
        effective_inputs.drivers,
        default_scenario_specs(),
        current_price=effective_inputs.current_price,
    )
    proposed_result = run_probabilistic_valuation(
        proposed_inputs.drivers,
        default_scenario_specs(),
        current_price=effective_inputs.current_price,
    )

    current_iv = _valuation_to_dict(current_result)
    proposed_iv = _valuation_to_dict(proposed_result)

    return {
        "ticker": ticker,
        "selection": selection,
        "effective_wacc": selected_result.wacc,
        "current_wacc": effective_inputs.drivers.wacc,
        "current_iv": current_iv["scenarios"],
        "proposed_iv": proposed_iv["scenarios"],
        "current_expected_iv": current_iv["expected_iv"],
        "proposed_expected_iv": proposed_iv["expected_iv"],
        "method_result": asdict(_method_to_breakdown(
            selection["selected_method"] if selection["mode"] == "single_method" else "blended",
            selected_result,
        )),
    }


def _insert_wacc_methodology_audit(conn, row: dict[str, Any]) -> None:
    create_tables(conn)
    conn.execute(
        """
        INSERT INTO wacc_methodology_audit (
            event_ts, ticker, actor, mode, selected_method, weights_json,
            effective_wacc, prior_config_json, resulting_config_json, preview_json
        ) VALUES (
            :event_ts, :ticker, :actor, :mode, :selected_method, :weights_json,
            :effective_wacc, :prior_config_json, :resulting_config_json, :preview_json
        )
        """,
        row,
    )
    conn.commit()


def apply_wacc_methodology_selection(
    ticker: str,
    *,
    mode: str,
    selected_method: str | None = None,
    weights: dict[str, float] | None = None,
    actor: str = "dashboard",
) -> dict[str, Any]:
    ticker = ticker.upper().strip()
    selection = _normalize_selection(mode=mode, selected_method=selected_method, weights=weights)
    preview = preview_wacc_methodology_selection(
        ticker,
        mode=selection["mode"],
        selected_method=selection["selected_method"],
        weights=selection["weights"],
    )

    overrides = _load_overrides_data()
    ticker_blob = overrides.setdefault("tickers", {}).setdefault(ticker, {})
    prior_config = ticker_blob.get("wacc_methodology")
    resulting_config = {
        "mode": selection["mode"],
        "selected_method": selection["selected_method"],
        "weights": selection["weights"] if selection["mode"] == "blended" else None,
    }
    ticker_blob["wacc_methodology"] = resulting_config
    _write_overrides_data(overrides)
    clear_valuation_overrides_cache()

    with get_connection() as conn:
        _insert_wacc_methodology_audit(
            conn,
            {
                "event_ts": _now(),
                "ticker": ticker,
                "actor": actor,
                "mode": selection["mode"],
                "selected_method": selection["selected_method"],
                "weights_json": json.dumps(selection["weights"], sort_keys=True),
                "effective_wacc": preview.get("effective_wacc"),
                "prior_config_json": json.dumps(prior_config, sort_keys=True) if prior_config is not None else None,
                "resulting_config_json": json.dumps(resulting_config, sort_keys=True),
                "preview_json": json.dumps(preview, sort_keys=True),
            },
        )

    return preview


def load_wacc_methodology_audit_history(ticker: str, limit: int = 25) -> list[dict[str, Any]]:
    ticker = ticker.upper().strip()
    with get_connection() as conn:
        create_tables(conn)
        rows = conn.execute(
            """
            SELECT event_ts, ticker, actor, mode, selected_method, weights_json,
                   effective_wacc, prior_config_json, resulting_config_json, preview_json
            FROM wacc_methodology_audit
            WHERE ticker = ?
            ORDER BY event_ts DESC
            LIMIT ?
            """,
            [ticker, limit],
        ).fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        out.append(
            {
                "event_ts": row["event_ts"],
                "ticker": row["ticker"],
                "actor": row["actor"],
                "mode": row["mode"],
                "selected_method": row["selected_method"],
                "weights": json.loads(row["weights_json"] or "{}"),
                "effective_wacc": row["effective_wacc"],
                "prior_config": json.loads(row["prior_config_json"]) if row["prior_config_json"] else None,
                "resulting_config": json.loads(row["resulting_config_json"]) if row["resulting_config_json"] else None,
                "preview": json.loads(row["preview_json"]) if row["preview_json"] else None,
            }
        )
    return out
