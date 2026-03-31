"""
JSON exporter for per-ticker valuation results.

Two public functions:
  build_nested_structure() — pure transformation, no I/O
  export_ticker_json()    — writes dated + latest JSON files
"""
from __future__ import annotations

import json
import math
from datetime import datetime, date
from pathlib import Path
from typing import Any


_SCHEMA_VERSION = "1.0"


# ── JSON serialisation helper ────────────────────────────────────────────────

def _json_default(obj: Any) -> Any:
    """Handle numpy / datetime types that json.dump can't serialise natively."""
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    # numpy scalars (int64, float64, bool_)
    try:
        import numpy as np  # type: ignore
        if isinstance(obj, (np.integer,)):
            return int(obj)
        if isinstance(obj, (np.floating,)):
            v = float(obj)
            return None if math.isnan(v) or math.isinf(v) else v
        if isinstance(obj, np.bool_):
            return bool(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
    except ImportError:
        pass
    # plain float NaN / inf
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return None
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serialisable")


def _safe(d: dict, key: str) -> Any:
    return d.get(key)


# ── Core transformation ───────────────────────────────────────────────────────

def build_nested_structure(
    result: dict,
    qoe: dict | None = None,
    comps_detail: dict | None = None,
    comps_analysis: dict | None = None,
) -> dict:
    """
    Transform the flat ~120-key result dict from value_single_ticker() into
    a nested JSON structure with logical sections.

    Pure function — no I/O, no side-effects.
    """
    r = result  # shorthand

    # Deserialise embedded JSON strings
    def _parse_json_field(key: str, fallback: Any) -> Any:
        raw = r.get(key)
        if not raw:
            return fallback
        try:
            return json.loads(raw)
        except Exception:
            return fallback

    drivers_raw = _parse_json_field("drivers_json", {})
    forecast_bridge = _parse_json_field("forecast_bridge_json", [])
    story_profile = _parse_json_field("story_profile_json", {})
    story_adjustments = _parse_json_field("story_adjustments_json", {})

    ticker = str(r.get("ticker") or "").upper()
    price = r.get("price")

    # ── market ───────────────────────────────────────────────────────────────
    market = {
        "price": price,
        "market_cap_mm": r.get("market_cap_mm"),
        "ev_mm": r.get("ev_mm"),
        "pe_trailing": r.get("pe_trailing"),
        "pe_forward": r.get("pe_forward"),
        "ev_ebitda": r.get("ev_ebitda"),
        "analyst_target": r.get("analyst_target"),
        "analyst_recommendation": r.get("analyst_recommendation"),
        "num_analysts": r.get("num_analysts"),
    }

    # ── assumptions ──────────────────────────────────────────────────────────
    # All percentage fields stored as decimals (0.066, not 6.6).
    # All _mm fields stored in $mm (divide raw dollar values by 1e6).
    def _mm(v: Any) -> Any:
        return round(float(v) / 1e6, 3) if v is not None else None

    assumptions = {
        "revenue_mm": _mm(drivers_raw.get("revenue_base")) or r.get("revenue_mm"),
        "growth_near_pct": drivers_raw.get("revenue_growth_near"),
        "growth_mid_pct": drivers_raw.get("revenue_growth_mid"),
        "growth_terminal_pct": drivers_raw.get("revenue_growth_terminal"),
        "ebit_margin_start_pct": drivers_raw.get("ebit_margin_start"),
        "ebit_margin_target_pct": drivers_raw.get("ebit_margin_target"),
        "capex_pct": drivers_raw.get("capex_pct_start"),
        "da_pct": drivers_raw.get("da_pct_start"),
        "tax_rate_start_pct": drivers_raw.get("tax_rate_start"),
        "tax_rate_target_pct": drivers_raw.get("tax_rate_target"),
        "dso_start": drivers_raw.get("dso_start"),
        "dso_target": drivers_raw.get("dso_target"),
        "dio_start": drivers_raw.get("dio_start"),
        "dio_target": drivers_raw.get("dio_target"),
        "dpo_start": drivers_raw.get("dpo_start"),
        "dpo_target": drivers_raw.get("dpo_target"),
        "exit_multiple": drivers_raw.get("exit_multiple"),
        "exit_metric": drivers_raw.get("exit_metric"),
        "net_debt_mm": _mm(drivers_raw.get("net_debt")) or r.get("net_debt_mm"),
        "shares_outstanding_mm": _mm(drivers_raw.get("shares_outstanding")),
        "ronic_terminal_pct": drivers_raw.get("ronic_terminal"),
        "invested_capital_mm": _mm(drivers_raw.get("invested_capital_start")),
        "non_operating_assets_mm": _mm(drivers_raw.get("non_operating_assets")) or r.get("non_operating_assets_used_mm"),
        "minority_interest_mm": _mm(drivers_raw.get("minority_interest")) or r.get("minority_interest_used_mm"),
        "preferred_equity_mm": _mm(drivers_raw.get("preferred_equity")) or r.get("preferred_equity_used_mm"),
        "pension_deficit_mm": _mm(drivers_raw.get("pension_deficit")) or r.get("pension_deficit_used_mm"),
        "lease_liabilities_mm": _mm(drivers_raw.get("lease_liabilities")) or r.get("lease_liabilities_used_mm"),
        "options_value_mm": _mm(drivers_raw.get("options_value")) or r.get("options_value_used_mm"),
        "convertibles_value_mm": _mm(drivers_raw.get("convertibles_value")) or r.get("convertibles_value_used_mm"),
        "scenario_prob_bear": r.get("scenario_prob_bear"),
        "scenario_prob_base": r.get("scenario_prob_base"),
        "scenario_prob_bull": r.get("scenario_prob_bull"),
    }

    # ── wacc ─────────────────────────────────────────────────────────────────
    peers_used_raw = r.get("peers_used") or ""
    peers_list = [p.strip() for p in peers_used_raw.split(",") if p.strip()] if peers_used_raw else []

    # WACC — all values stored as decimals (0.07, not 7.0).
    # Prefer drivers_raw (always decimal); fall back to flat dict which may
    # store equity_weight as a percentage (70.0 → 0.70).
    def _pct_to_dec(v: Any) -> float | None:
        """Convert a value to decimal: >1 means it's stored as percentage."""
        if v is None:
            return None
        f = float(v)
        return f / 100.0 if f > 1.0 else f

    _dw = drivers_raw.get("debt_weight")
    if _dw is None:
        _eq_pct = r.get("equity_weight")
        _eq_dec = _pct_to_dec(_eq_pct) if _eq_pct is not None else 0.82
        _dw = 1.0 - _eq_dec
    _eq_wt = 1.0 - _dw

    wacc = {
        "wacc": drivers_raw.get("wacc") or _pct_to_dec(r.get("wacc")),
        "cost_of_equity": drivers_raw.get("cost_of_equity") or _pct_to_dec(r.get("cost_of_equity")),
        "cost_of_debt": drivers_raw.get("cost_of_debt"),
        "risk_free_rate": drivers_raw.get("risk_free_rate"),
        "equity_risk_premium": drivers_raw.get("equity_risk_premium"),
        "beta_raw": r.get("beta_raw"),
        "beta_unlevered": r.get("beta_unlevered"),
        "beta_relevered": r.get("beta_relevered"),
        "size_premium": r.get("size_premium") or 0.0,
        "equity_weight": _eq_wt,
        "debt_weight": _dw,
        "peers_used": peers_list,
    }

    # ── valuation ─────────────────────────────────────────────────────────────
    iv_base = r.get("iv_base")
    iv_bear = r.get("iv_bear")
    iv_bull = r.get("iv_bull")

    def _upside(iv: float | None) -> float | None:
        if iv is None or price is None or price <= 0:
            return None
        return round((iv / price - 1.0) * 100.0, 1)

    valuation = {
        "iv_bear": iv_bear,
        "iv_base": iv_base,
        "iv_bull": iv_bull,
        "expected_iv": r.get("expected_iv"),
        "upside_bear_pct": r.get("upside_bear_pct") if r.get("upside_bear_pct") is not None else _upside(iv_bear),
        "upside_base_pct": r.get("upside_base_pct") if r.get("upside_base_pct") is not None else _upside(iv_base),
        "upside_bull_pct": r.get("upside_bull_pct") if r.get("upside_bull_pct") is not None else _upside(iv_bull),
        "expected_upside_pct": r.get("expected_upside_pct"),
        "margin_of_safety": r.get("margin_of_safety"),
        "iv_gordon": r.get("iv_gordon"),
        "iv_exit": r.get("iv_exit"),
        "iv_blended": r.get("iv_blended"),
        "ep_iv_base": r.get("ep_iv_base"),
        "fcfe_iv_base": r.get("fcfe_iv_base"),
        "dcf_ep_gap_pct": r.get("dcf_ep_gap_pct"),
        "comps_iv_ev_ebitda": r.get("comps_iv_ev_ebitda"),
        "comps_iv_ev_ebit": r.get("comps_iv_ev_ebit"),
        "comps_iv_pe": r.get("comps_iv_pe"),
        "comps_iv_base": r.get("comps_iv_base"),
        "implied_growth_pct": r.get("implied_growth_pct"),
        "model_applicability_status": r.get("model_applicability_status"),
    }

    # ── scenarios ─────────────────────────────────────────────────────────────
    scenarios = {
        "bear": {
            "probability": r.get("scenario_prob_bear"),
            "iv": iv_bear,
            "upside_pct": r.get("upside_bear_pct") if r.get("upside_bear_pct") is not None else _upside(iv_bear),
        },
        "base": {
            "probability": r.get("scenario_prob_base"),
            "iv": iv_base,
            "upside_pct": r.get("upside_base_pct") if r.get("upside_base_pct") is not None else _upside(iv_base),
        },
        "bull": {
            "probability": r.get("scenario_prob_bull"),
            "iv": iv_bull,
            "upside_pct": r.get("upside_bull_pct") if r.get("upside_bull_pct") is not None else _upside(iv_bull),
        },
    }

    # ── terminal ──────────────────────────────────────────────────────────────
    terminal = {
        "tv_gordon_mm": r.get("tv_gordon_mm"),
        "tv_exit_mm": r.get("tv_exit_mm"),
        "tv_blended_mm": r.get("tv_blended_mm"),
        "pv_tv_gordon_mm": r.get("pv_tv_gordon_mm"),
        "pv_tv_exit_mm": r.get("pv_tv_exit_mm"),
        "pv_tv_blended_mm": r.get("pv_tv_blended_mm"),
        "tv_pct_of_ev": r.get("tv_pct_of_ev"),
        "terminal_growth_pct": r.get("terminal_growth_pct"),
        "terminal_ronic_pct": r.get("terminal_ronic_pct"),
        "gordon_formula_mode": r.get("gordon_formula_mode"),
        "ev_operations_mm": r.get("ev_operations_mm"),
        "ev_total_mm": r.get("ev_total_mm"),
        "non_operating_assets_mm": r.get("non_operating_assets_mm"),
        "non_equity_claims_mm": r.get("non_equity_claims_mm"),
    }

    # ── health_flags ──────────────────────────────────────────────────────────
    health_flags = {
        "tv_high_flag": r.get("tv_high_flag"),
        "tv_extreme_flag": r.get("health_tv_extreme_flag"),
        "tv_method_fallback_flag": r.get("tv_method_fallback_flag"),
        "roic_consistency_flag": r.get("roic_consistency_flag"),
        "nwc_driver_quality_flag": r.get("nwc_driver_quality_flag"),
        "terminal_growth_guardrail_flag": r.get("health_terminal_growth_guardrail_flag"),
        "terminal_ronic_guardrail_flag": r.get("health_terminal_ronic_guardrail_flag"),
        "terminal_denominator_guardrail_flag": r.get("health_terminal_denominator_guardrail_flag"),
        "fcff_interest_contamination_flag": r.get("health_fcff_interest_contamination_flag"),
        "ep_reconcile_flag": r.get("ep_reconcile_flag"),
    }

    # ── source_lineage ─────────────────────────────────────────────────────────
    source_lineage = {
        "revenue_base": r.get("revenue_source"),
        "revenue_growth_near": r.get("growth_source"),
        "growth_source_detail": r.get("growth_source_detail"),
        "revenue_period_type": r.get("revenue_period_type"),
        "growth_period_type": r.get("growth_period_type"),
        "revenue_alignment_flag": r.get("revenue_alignment_flag"),
        "revenue_data_quality_flag": r.get("revenue_data_quality_flag"),
        "ebit_margin_start": r.get("ebit_margin_source"),
        "capex_pct_start": r.get("capex_source"),
        "da_pct_start": r.get("da_source"),
        "tax_rate_start": r.get("tax_source"),
        "dso_start": r.get("dso_source"),
        "dio_start": r.get("dio_source"),
        "dpo_start": r.get("dpo_source"),
        "exit_multiple": r.get("exit_multiple_source"),
        "net_debt": r.get("net_debt_source"),
        "shares_outstanding": r.get("shares_source"),
        "cost_of_equity": r.get("cost_of_equity_source"),
        "debt_weight": r.get("debt_weight_source"),
        "ronic_terminal": r.get("ronic_terminal_source"),
        "invested_capital_start": r.get("invested_capital_source"),
        "non_operating_assets": r.get("non_operating_assets_source"),
        "minority_interest": r.get("minority_interest_source"),
        "preferred_equity": r.get("preferred_equity_source"),
        "pension_deficit": r.get("pension_deficit_source"),
        "lease_liabilities": r.get("lease_liabilities_source"),
        "options_value": r.get("options_value_source"),
        "convertibles_value": r.get("convertibles_value_source"),
        "story_profile": r.get("story_profile_source"),
    }

    # ── ciq_lineage ───────────────────────────────────────────────────────────
    ciq_lineage = {
        "snapshot_used": r.get("ciq_snapshot_used"),
        "snapshot_run_id": r.get("ciq_run_id"),
        "snapshot_source_file": r.get("ciq_source_file"),
        "snapshot_as_of_date": r.get("ciq_as_of_date"),
        "comps_used": r.get("ciq_comps_used"),
        "comps_run_id": r.get("ciq_comps_run_id"),
        "comps_source_file": r.get("ciq_comps_source_file"),
        "comps_as_of_date": r.get("ciq_comps_as_of_date"),
        "peer_count": r.get("ciq_peer_count"),
    }

    # ── Assemble final structure ──────────────────────────────────────────────
    out: dict[str, Any] = {
        "$schema_version": _SCHEMA_VERSION,
        "generated_at": datetime.utcnow().isoformat(timespec="seconds"),
        "ticker": ticker,
        "company_name": r.get("company_name"),
        "sector": r.get("sector"),
        "industry": r.get("industry"),
        "market": market,
        "assumptions": assumptions,
        "wacc": wacc,
        "valuation": valuation,
        "scenarios": scenarios,
        "terminal": terminal,
        "health_flags": health_flags,
        "forecast_bridge": forecast_bridge,
        "source_lineage": source_lineage,
        "ciq_lineage": ciq_lineage,
        "story_profile": story_profile,
        "story_adjustments": story_adjustments,
        "drivers_raw": drivers_raw,
    }

    if comps_detail is not None:
        out["comps_detail"] = comps_detail

    if comps_analysis is not None:
        out["comps_analysis"] = comps_analysis

    if qoe is not None:
        out["qoe"] = qoe

    return out


# ── File writer ───────────────────────────────────────────────────────────────

def export_ticker_json(
    result: dict,
    qoe: dict | None = None,
    comps_detail: dict | None = None,
    comps_analysis: dict | None = None,
    output_dir: Path | str | None = None,
    date_str: str | None = None,
) -> Path:
    """
    Build nested structure and write two JSON files:
      {output_dir}/{TICKER}_{date_str}.json  — dated archive
      {output_dir}/{TICKER}_latest.json      — stable path for Power Query

    Returns the path of the dated file.
    """
    ticker = str(result.get("ticker") or "UNKNOWN").upper()

    if output_dir is None:
        root = Path(__file__).resolve().parent.parent.parent
        output_dir = root / "data" / "valuations" / "json"
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if date_str is None:
        date_str = datetime.utcnow().strftime("%Y-%m-%d")

    nested = build_nested_structure(
        result,
        qoe=qoe,
        comps_detail=comps_detail,
        comps_analysis=comps_analysis,
    )

    dated_path = output_dir / f"{ticker}_{date_str}.json"
    latest_path = output_dir / f"{ticker}_latest.json"

    payload = json.dumps(nested, indent=2, default=_json_default)
    dated_path.write_text(payload, encoding="utf-8")
    latest_path.write_text(payload, encoding="utf-8")

    return dated_path
