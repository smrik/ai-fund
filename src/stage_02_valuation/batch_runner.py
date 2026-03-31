"""
Batch Valuation Runner — deterministic professional DCF with lineage and audit exports.
"""

from __future__ import annotations

import csv
import json
import logging
import sqlite3
import sys
import time
from collections.abc import Callable
from dataclasses import asdict, replace
from datetime import datetime
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from config import DB_PATH, PEER_SIMILARITY_ENABLED, PEER_SIMILARITY_MODEL
from src.logging_config import configure_logging
from src.stage_00_data import market_data as md_client
from src.stage_00_data.ciq_adapter import get_ciq_comps_detail
from src.stage_02_valuation.comps_model import build_comps_detail_from_yfinance
from src.stage_00_data.peer_similarity import score_peer_similarity
from src.stage_02_valuation.comps_model import run_comps_model
from src.stage_02_valuation.input_assembler import build_valuation_inputs, load_valuation_overrides
from src.stage_02_valuation.json_exporter import export_ticker_json
from src.stage_04_pipeline.comps_dashboard import build_comps_dashboard_view
from src.stage_02_valuation.professional_dcf import (
    ForecastDrivers,
    ScenarioSpec,
    default_scenario_specs,
    reverse_dcf_professional,
    run_dcf_professional,
    run_probabilistic_valuation,
)


ROOT_DIR = Path(__file__).resolve().parent.parent.parent
UNIVERSE_CSV = ROOT_DIR / "config" / "universe.csv"
OUTPUT_DIR = ROOT_DIR / "data" / "valuations"
logger = logging.getLogger(__name__)


def _safe_float(value):
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except TypeError:
        pass
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _mm(value: float | None) -> float | None:
    if value is None:
        return None
    return round(value / 1e6, 0)


def _pct(value: float | None, digits: int = 1) -> float | None:
    if value is None:
        return None
    return round(value * 100.0, digits)


def _flag(value: bool | None) -> bool | None:
    if value is None:
        return None
    return bool(value)


def _scenario_by_name(results: dict, name: str):
    if name in results:
        return results[name]
    if not results:
        return None
    return next(iter(results.values()))


def _drivers_from_json(value: str) -> ForecastDrivers | None:
    if not value:
        return None
    try:
        payload = json.loads(value)
        return ForecastDrivers(**payload)
    except Exception:
        return None


def _sensitivity_rows(ticker: str, drivers: ForecastDrivers) -> list[dict]:
    rows: list[dict] = []
    base = ScenarioSpec(name="base", probability=1.0)

    for dw in (-0.01, 0.0, 0.01):
        for dg in (-0.005, 0.0, 0.005):
            d = replace(
                drivers,
                wacc=max(0.03, min(0.20, drivers.wacc + dw)),
                revenue_growth_terminal=max(0.0, min(0.05, drivers.revenue_growth_terminal + dg)),
            )
            result = run_dcf_professional(d, base)
            rows.append(
                {
                    "ticker": ticker,
                    "grid": "wacc_x_terminal_growth",
                    "wacc": d.wacc,
                    "terminal_growth": d.revenue_growth_terminal,
                    "exit_multiple": d.exit_multiple,
                    "iv": round(result.intrinsic_value_per_share, 4),
                }
            )

    for dw in (-0.01, 0.0, 0.01):
        for mult in (0.9, 1.0, 1.1):
            d = replace(
                drivers,
                wacc=max(0.03, min(0.20, drivers.wacc + dw)),
                exit_multiple=max(2.0, min(40.0, drivers.exit_multiple * mult)),
            )
            result = run_dcf_professional(d, base)
            rows.append(
                {
                    "ticker": ticker,
                    "grid": "wacc_x_exit_multiple",
                    "wacc": d.wacc,
                    "terminal_growth": d.revenue_growth_terminal,
                    "exit_multiple": d.exit_multiple,
                    "iv": round(result.intrinsic_value_per_share, 4),
                }
            )

    return rows


def _run_qoe_llm(ticker: str, valuation_result: dict) -> None:
    """
    Run QoEAgent (LLM layer) for a ticker and write pending override to
    config/qoe_pending.yaml.  PM sets status → 'approved' to apply on next run.
    """
    from src.stage_03_judgment.qoe_agent import QoEAgent, write_qoe_pending_override

    ticker = ticker.upper().strip()
    revenue_mm = valuation_result.get("revenue_mm") or 0.0
    ebit_margin = valuation_result.get("ebit_margin_used") or 0.0
    reported_ebit = (ebit_margin / 100.0 if ebit_margin > 1 else ebit_margin) * revenue_mm * 1_000_000

    logger.info(
        "\n%s\nQoE LLM analysis — %s\n  Reported EBIT: $%smm  (%s%% margin on $%smm revenue)\n%s",
        "=" * 60,
        ticker,
        f"{reported_ebit / 1e6:,.1f}",
        f"{ebit_margin:.1f}",
        f"{revenue_mm:,.0f}",
        "=" * 60,
        extra={"ticker": ticker, "step": "qoe_llm"},
    )

    try:
        agent = QoEAgent()
        qoe = agent.analyze(ticker=ticker, reported_ebit=reported_ebit)

        llm = qoe.get("llm", {})
        haircut = llm.get("ebit_haircut_pct")
        norm_ebit = llm.get("normalized_ebit")
        pending = llm.get("dcf_ebit_override_pending", False)

        logger.info(
            "\n  QoE score : %s/5  (%s)",
            qoe.get("qoe_score"),
            qoe.get("qoe_flag", "").upper(),
            extra={"ticker": ticker, "step": "qoe_llm"},
        )
        logger.info(
            "  Confidence: %s",
            llm.get("llm_confidence", "low"),
            extra={"ticker": ticker, "step": "qoe_llm"},
        )
        if haircut is not None:
            logger.info(
                "  EBIT haircut : %+0.1f%%  ($%smm normalised)",
                haircut,
                f"{norm_ebit / 1e6:,.1f}",
                extra={"ticker": ticker, "step": "qoe_llm"},
            )
        if qoe.get("pm_summary"):
            logger.info(
                "\n  PM Summary: %s",
                qoe["pm_summary"],
                extra={"ticker": ticker, "step": "qoe_llm"},
            )

        if llm.get("ebit_adjustments"):
            logger.info("\n  Adjustments:", extra={"ticker": ticker, "step": "qoe_llm"})
            for adj in llm["ebit_adjustments"]:
                logger.info(
                    "    %s $%.1fmm  %s",
                    adj["direction"],
                    adj["amount"] / 1e6,
                    adj["item"],
                    extra={"ticker": ticker, "step": "qoe_llm"},
                )
                logger.info(
                    "      → %s",
                    adj["rationale"],
                    extra={"ticker": ticker, "step": "qoe_llm"},
                )

        path = write_qoe_pending_override(ticker, qoe, revenue_mm)

        if pending:
            logger.warning(
                "\n  Override warranted (haircut >%s%% > 10%% threshold)\n  → Review config/qoe_pending.yaml\n  → Set status: approved  to apply on next --json run",
                f"{abs(haircut):.0f}",
                extra={"ticker": ticker, "step": "qoe_llm"},
            )
        else:
            logger.info(
                "\n  Haircut below 10%% threshold — no override needed\n  → Logged to %s (status: pending)",
                path,
                extra={"ticker": ticker, "step": "qoe_llm"},
            )

    except Exception as exc:
        logger.error("\n  QoE LLM failed: %s", exc, extra={"ticker": ticker, "step": "qoe_llm"})


def _compute_qoe_for_ticker(ticker: str) -> dict | None:
    """Fetch all QoE inputs and return compute_qoe_signals() output, or None on failure."""
    try:
        from src.stage_00_data.ciq_adapter import get_ciq_snapshot, get_ciq_nwc_history
        from src.stage_03_judgment.qoe_signals import compute_qoe_signals

        mkt = md_client.get_market_data(ticker)
        hist = md_client.get_historical_financials(ticker)
        ciq_snap = get_ciq_snapshot(ticker)
        ciq_nwc = get_ciq_nwc_history(ticker)
        sector = mkt.get("sector") or "Unknown"
        return compute_qoe_signals(ticker, sector, ciq_snap, ciq_nwc, hist, mkt)
    except Exception as exc:
        logger.warning("  QoE failed for %s: %s", ticker, exc, extra={"ticker": ticker, "step": "qoe"})
        return None


def value_single_ticker(ticker: str) -> dict | None:
    try:
        ticker = ticker.upper().strip()
        inputs = build_valuation_inputs(ticker)
        if inputs is None:
            return None

        mkt = md_client.get_market_data(ticker)
        price = inputs.current_price
        lineage = inputs.source_lineage
        ciq = inputs.ciq_lineage
        wacc_inputs = inputs.wacc_inputs

        row = {
            "ticker": ticker,
            "company_name": inputs.company_name,
            "sector": inputs.sector,
            "industry": inputs.industry,
            "price": round(price, 2),
            "market_cap_mm": round((mkt.get("market_cap") or 0) / 1e6, 0),
            "ev_mm": round((mkt.get("enterprise_value") or 0) / 1e6, 0),
            "pe_trailing": mkt.get("pe_trailing"),
            "pe_forward": mkt.get("pe_forward"),
            "ev_ebitda": mkt.get("ev_ebitda"),
            "revenue_mm": round(inputs.drivers.revenue_base / 1e6, 0),
            "revenue_source": lineage.get("revenue_base", "default"),
            "op_margin": round(inputs.drivers.ebit_margin_start * 100, 1),
            "profit_margin": round((mkt.get("profit_margin") or 0) * 100, 1),
            "rev_growth": round(inputs.drivers.revenue_growth_near * 100, 1),
            "fcf_mm": round((mkt.get("free_cashflow") or 0) / 1e6, 0),
            "net_debt_mm": round(inputs.drivers.net_debt / 1e6, 0),
            "net_debt_source": lineage.get("net_debt", "default"),
            "shares_source": lineage.get("shares_outstanding", "default"),
            "beta_raw": mkt.get("beta"),
            "wacc": round((wacc_inputs.get("wacc") or inputs.drivers.wacc) * 100, 2),
            "cost_of_equity": round((wacc_inputs.get("cost_of_equity") or 0) * 100, 2) if wacc_inputs.get("cost_of_equity") is not None else None,
            "cost_of_equity_source": lineage.get("cost_of_equity", "yfinance_capm"),
            "beta_relevered": round((wacc_inputs.get("beta_relevered") or 0), 2) if wacc_inputs.get("beta_relevered") is not None else None,
            "beta_unlevered": round((wacc_inputs.get("beta_unlevered_median") or 0), 2) if wacc_inputs.get("beta_unlevered_median") is not None else None,
            "size_premium": round((wacc_inputs.get("size_premium") or 0) * 100, 1) if wacc_inputs.get("size_premium") is not None else None,
            "equity_weight": round((wacc_inputs.get("equity_weight") or 0) * 100, 0) if wacc_inputs.get("equity_weight") is not None else None,
            "debt_weight_source": lineage.get("debt_weight", "yfinance_capm"),
            "peers_used": ", ".join(wacc_inputs.get("peers_used") or []),
            "growth_near": round(inputs.drivers.revenue_growth_near * 100, 1),
            "growth_mid": round(inputs.drivers.revenue_growth_mid * 100, 1),
            "growth_source": lineage.get("revenue_growth_near", "default"),
            "growth_source_detail": lineage.get("growth_source_detail", "unknown"),
            "revenue_period_type": lineage.get("revenue_period_type", "unknown"),
            "growth_period_type": lineage.get("growth_period_type", "unknown"),
            "revenue_alignment_flag": lineage.get("revenue_alignment_flag", "unknown"),
            "revenue_data_quality_flag": lineage.get("revenue_data_quality_flag", "needs_review"),
            "ebit_margin_used": round(inputs.drivers.ebit_margin_start * 100, 1),
            "ebit_margin_source": lineage.get("ebit_margin_start", "default"),
            "capex_pct_used": round(inputs.drivers.capex_pct_start * 100, 2),
            "capex_source": lineage.get("capex_pct_start", "default"),
            "da_pct_used": round(inputs.drivers.da_pct_start * 100, 2),
            "da_source": lineage.get("da_pct_start", "default"),
            "tax_rate_used": round(inputs.drivers.tax_rate_start * 100, 1),
            "tax_source": lineage.get("tax_rate_start", "default"),
            "dso_used": round(inputs.drivers.dso_start, 1),
            "dso_source": lineage.get("dso_start", "default"),
            "dio_used": round(inputs.drivers.dio_start, 1),
            "dio_source": lineage.get("dio_start", "default"),
            "dpo_used": round(inputs.drivers.dpo_start, 1),
            "dpo_source": lineage.get("dpo_start", "default"),
            "ronic_terminal_used": _pct(inputs.drivers.ronic_terminal, 2),
            "ronic_terminal_source": lineage.get("ronic_terminal", "default"),
            "invested_capital_source": lineage.get("invested_capital_start", "default"),
            "non_operating_assets_used_mm": _mm(inputs.drivers.non_operating_assets),
            "non_operating_assets_source": lineage.get("non_operating_assets", "default"),
            "minority_interest_used_mm": _mm(inputs.drivers.minority_interest),
            "minority_interest_source": lineage.get("minority_interest", "default"),
            "preferred_equity_used_mm": _mm(inputs.drivers.preferred_equity),
            "preferred_equity_source": lineage.get("preferred_equity", "default"),
            "pension_deficit_used_mm": _mm(inputs.drivers.pension_deficit),
            "pension_deficit_source": lineage.get("pension_deficit", "default"),
            "lease_liabilities_used_mm": _mm(inputs.drivers.lease_liabilities),
            "lease_liabilities_source": lineage.get("lease_liabilities", "default"),
            "options_value_used_mm": _mm(inputs.drivers.options_value),
            "options_value_source": lineage.get("options_value", "default"),
            "convertibles_value_used_mm": _mm(inputs.drivers.convertibles_value),
            "convertibles_value_source": lineage.get("convertibles_value", "default"),
            "exit_multiple_used": round(inputs.drivers.exit_multiple, 2),
            "exit_multiple_source": lineage.get("exit_multiple", "default"),
            "exit_metric_used": inputs.drivers.exit_metric,
            "model_applicability_status": inputs.model_applicability_status,
            "story_profile_source": lineage.get("story_profile", "default"),
            "story_profile_json": json.dumps(getattr(inputs, "story_profile", {}) or {}, separators=(",", ":")),
            "story_adjustments_json": json.dumps(getattr(inputs, "story_adjustments", {}) or {}, separators=(",", ":")),
            "ciq_snapshot_used": bool(ciq.get("snapshot_used")),
            "ciq_run_id": ciq.get("snapshot_run_id"),
            "ciq_source_file": ciq.get("snapshot_source_file"),
            "ciq_as_of_date": ciq.get("snapshot_as_of_date"),
            "ciq_comps_used": bool(ciq.get("comps_used")),
            "ciq_comps_run_id": ciq.get("comps_run_id"),
            "ciq_comps_source_file": ciq.get("comps_source_file"),
            "ciq_comps_as_of_date": ciq.get("comps_as_of_date"),
            "ciq_peer_count": ciq.get("peer_count"),
            "peer_median_tev_ebitda_ltm": ciq.get("peer_median_tev_ebitda_ltm"),
            "peer_median_tev_ebit_ltm": ciq.get("peer_median_tev_ebit_ltm"),
            "peer_median_pe_ltm": ciq.get("peer_median_pe_ltm"),
            "comps_iv_ev_ebitda": ciq.get("comps_iv_ev_ebitda"),
            "comps_iv_ev_ebit": ciq.get("comps_iv_ev_ebit"),
            "comps_iv_pe": ciq.get("comps_iv_pe"),
            "comps_iv_base": ciq.get("comps_iv_base"),
            "comps_upside_pct": (
                round(((ciq.get("comps_iv_base") / price) - 1.0) * 100, 1)
                if ciq.get("comps_iv_base") is not None and price > 0
                else None
            ),
            # Comps model (IQR-cleaned, similarity-weighted) — populated below
            "comps_model_bear": None,
            "comps_model_base": None,
            "comps_model_bull": None,
            "comps_model_blended_base": None,
            "comps_model_primary_metric": None,
            "comps_model_peer_count_clean": None,
            "comps_model_upside_pct": None,
            "comps_similarity_method": None,
            "comps_similarity_model": None,
            "comps_similarity_weighted_flag": None,
            "analyst_target": mkt.get("analyst_target_mean"),
            "analyst_recommendation": mkt.get("analyst_recommendation"),
            "num_analysts": mkt.get("number_of_analysts"),
            "drivers_json": json.dumps(asdict(inputs.drivers), separators=(",", ":")),
        }

        # ── Comps model (IQR-cleaned, similarity-weighted) ───────────────────
        try:
            comps_detail_raw = get_ciq_comps_detail(ticker)
            # yfinance peer fallback when CIQ comps are unavailable
            if not comps_detail_raw:
                _overrides = load_valuation_overrides()
                _peer_list = (_overrides.get("tickers", {}).get(ticker, {}) or {}).get("peers")
                if _peer_list:
                    _peer_data = md_client.get_peer_multiples(_peer_list)
                    # Gap 8: enrich target dict with EBIT and EPS for EV/EBIT and P/E comps
                    _ebit_mm = inputs.drivers.ebit_margin_start * inputs.drivers.revenue_base / 1e6
                    _pe = mkt.get("pe_trailing")
                    _eps = (price / _pe) if (_pe and _pe > 0 and price > 0) else None
                    _mkt_enriched = {**mkt, "ebit_ltm_mm": _ebit_mm, "eps_ltm": _eps}
                    comps_detail_raw = build_comps_detail_from_yfinance(ticker, _peer_data, _mkt_enriched)
                    if comps_detail_raw:
                        row["comps_similarity_method"] = "yfinance_fallback"
            if comps_detail_raw:
                similarity_scores = None
                if PEER_SIMILARITY_ENABLED:
                    similarity_scores = score_peer_similarity(
                        ticker,
                        comps_detail_raw.get("peers") or [],
                        PEER_SIMILARITY_MODEL,
                    )
                comps_model_result = run_comps_model(
                    comps_detail_raw,
                    net_debt_mm=inputs.drivers.net_debt / 1e6,
                    shares_mm=inputs.drivers.shares_outstanding / 1e6,
                    similarity_scores=similarity_scores,
                )
                if comps_model_result:
                    row["comps_model_bear"] = comps_model_result.bear_iv
                    row["comps_model_base"] = comps_model_result.base_iv
                    row["comps_model_bull"] = comps_model_result.bull_iv
                    row["comps_model_blended_base"] = comps_model_result.blended_base_iv
                    row["comps_model_primary_metric"] = comps_model_result.primary_metric
                    row["comps_model_peer_count_clean"] = comps_model_result.peer_count_clean
                    row["comps_similarity_method"] = comps_model_result.similarity_method
                    row["comps_similarity_model"] = comps_model_result.similarity_model
                    row["comps_similarity_weighted_flag"] = comps_model_result.similarity_weighted
                    if comps_model_result.base_iv is not None and price > 0:
                        row["comps_model_upside_pct"] = round(
                            (comps_model_result.base_iv / price - 1.0) * 100, 1
                        )
        except Exception:
            pass  # comps model is supplementary; never block DCF

        if inputs.model_applicability_status != "dcf_applicable":
            row.update(
                {
                    "iv_bear": None,
                    "iv_base": None,
                    "iv_bull": None,
                    "expected_iv": None,
                    "expected_upside_pct": None,
                    "upside_base_pct": None,
                    "upside_bear_pct": None,
                    "upside_bull_pct": None,
                    "margin_of_safety": None,
                    "tv_pct_of_ev": None,
                    "implied_growth_pct": None,
                    "tv_high_flag": None,
                    "iv_gordon": None,
                    "iv_exit": None,
                    "iv_blended": None,
                    "tv_method_fallback_flag": None,
                    "roic_consistency_flag": None,
                    "nwc_driver_quality_flag": None,
                    "ev_operations_mm": None,
                    "ev_total_mm": None,
                    "non_operating_assets_mm": None,
                    "non_equity_claims_mm": None,
                    "ep_ev_operations_mm": None,
                    "ep_iv_base": None,
                    "dcf_ep_gap_pct": None,
                    "ep_reconcile_flag": None,
                    "fcfe_iv_base": None,
                    "fcfe_equity_mm": None,
                    "fcfe_pv_sum_mm": None,
                    "fcfe_terminal_value_mm": None,
                    "cost_of_equity_model": None,
                    "tv_gordon_mm": None,
                    "tv_exit_mm": None,
                    "tv_blended_mm": None,
                    "pv_tv_gordon_mm": None,
                    "pv_tv_exit_mm": None,
                    "pv_tv_blended_mm": None,
                    "terminal_growth_pct": None,
                    "terminal_ronic_pct": None,
                    "terminal_fcff_11_bridge_mm": None,
                    "terminal_fcff_11_value_driver_mm": None,
                    "gordon_formula_mode": None,
                    "health_tv_extreme_flag": None,
                    "health_terminal_growth_guardrail_flag": None,
                    "health_terminal_ronic_guardrail_flag": None,
                    "health_terminal_denominator_guardrail_flag": None,
                    "health_fcff_interest_contamination_flag": None,
                    "scenario_prob_bear": 0.20,
                    "scenario_prob_base": 0.60,
                    "scenario_prob_bull": 0.20,
                    "forecast_bridge_json": "[]",
                }
            )
            return row

        scenario_specs = default_scenario_specs()
        try:
            from src.stage_02_valuation.regime_model import detect_current_regime, get_scenario_weights
            regime = detect_current_regime()
            if regime.available:
                weights = get_scenario_weights(regime)
                scenario_specs = [
                    ScenarioSpec("bear", weights.bear, growth_multiplier=0.8, margin_shift=-0.02, wacc_shift=0.01, exit_multiple_multiplier=0.9),
                    ScenarioSpec("base", weights.base),
                    ScenarioSpec("bull", weights.bull, growth_multiplier=1.2, margin_shift=0.02, wacc_shift=-0.01, exit_multiple_multiplier=1.1),
                ]
        except Exception:
            pass
        probabilistic = run_probabilistic_valuation(inputs.drivers, scenario_specs, current_price=price)

        bear = _scenario_by_name(probabilistic.scenario_results, "bear")
        base = _scenario_by_name(probabilistic.scenario_results, "base")
        bull = _scenario_by_name(probabilistic.scenario_results, "bull")

        base_iv = base.intrinsic_value_per_share if base else None
        bear_iv = bear.intrinsic_value_per_share if bear else None
        bull_iv = bull.intrinsic_value_per_share if bull else None

        upside_base = (base_iv / price - 1) if base_iv is not None and price > 0 else None
        upside_bear = (bear_iv / price - 1) if bear_iv is not None and price > 0 else None
        upside_bull = (bull_iv / price - 1) if bull_iv is not None and price > 0 else None

        implied_growth = reverse_dcf_professional(
            drivers=inputs.drivers,
            target_price=price,
            scenario="base",
        )

        health = (base.health_flags or {}) if base else {}
        terminal = base.terminal_breakdown if base else None

        row.update(
            {
                "iv_bear": round(bear_iv, 2) if bear_iv is not None else None,
                "iv_base": round(base_iv, 2) if base_iv is not None else None,
                "iv_bull": round(bull_iv, 2) if bull_iv is not None else None,
                "upside_base_pct": _pct(upside_base),
                "upside_bear_pct": _pct(upside_bear),
                "upside_bull_pct": _pct(upside_bull),
                "margin_of_safety": round((1.0 - price / base_iv) * 100, 1) if base_iv and base_iv > 0 else None,
                "expected_iv": round(probabilistic.expected_iv, 2),
                "expected_upside_pct": _pct(probabilistic.expected_upside_pct),
                "tv_pct_of_ev": _pct(base.tv_pct_of_ev) if base and base.tv_pct_of_ev is not None else None,
                "tv_high_flag": _flag(base.tv_pct_of_ev > 0.75) if base and base.tv_pct_of_ev is not None else None,
                "implied_growth_pct": _pct(implied_growth),
                "iv_gordon": round(base.iv_gordon, 2) if base and base.iv_gordon is not None else None,
                "iv_exit": round(base.iv_exit, 2) if base and base.iv_exit is not None else None,
                "iv_blended": round(base.iv_blended, 2) if base else None,
                "tv_method_fallback_flag": _flag(base.tv_method_fallback_flag) if base else None,
                "roic_consistency_flag": _flag(base.roic_consistency_flag) if base else None,
                "nwc_driver_quality_flag": _flag(base.nwc_driver_quality_flag) if base else None,
                "ev_operations_mm": _mm(base.enterprise_value_operations) if base else None,
                "ev_total_mm": _mm(base.enterprise_value_total) if base else None,
                "non_operating_assets_mm": _mm(base.non_operating_assets) if base else None,
                "non_equity_claims_mm": _mm(base.non_equity_claims) if base else None,
                "ep_ev_operations_mm": _mm(base.ep_enterprise_value) if base else None,
                "ep_iv_base": round(base.ep_intrinsic_value_per_share, 2) if base and base.ep_intrinsic_value_per_share is not None else None,
                "dcf_ep_gap_pct": _pct(base.dcf_ep_gap_pct, 2) if base and base.dcf_ep_gap_pct is not None else None,
                "ep_reconcile_flag": _flag(base.ep_reconcile_flag) if base else None,
                "fcfe_iv_base": round(base.fcfe_intrinsic_value_per_share, 2) if base and base.fcfe_intrinsic_value_per_share is not None else None,
                "fcfe_equity_mm": _mm(base.fcfe_equity_value) if base else None,
                "fcfe_pv_sum_mm": _mm(base.fcfe_pv_sum) if base else None,
                "fcfe_terminal_value_mm": _mm(base.fcfe_terminal_value) if base else None,
                "cost_of_equity_model": _pct(base.cost_of_equity_used, 2) if base and base.cost_of_equity_used is not None else None,
                "tv_gordon_mm": _mm(terminal.tv_gordon) if terminal else None,
                "tv_exit_mm": _mm(terminal.tv_exit) if terminal else None,
                "tv_blended_mm": _mm(terminal.tv_blended) if terminal else None,
                "pv_tv_gordon_mm": _mm(terminal.pv_tv_gordon) if terminal else None,
                "pv_tv_exit_mm": _mm(terminal.pv_tv_exit) if terminal else None,
                "pv_tv_blended_mm": _mm(terminal.pv_tv_blended) if terminal else None,
                "terminal_growth_pct": _pct(terminal.terminal_growth, 2) if terminal else None,
                "terminal_ronic_pct": _pct(terminal.ronic_terminal, 2) if terminal and terminal.ronic_terminal is not None else None,
                "terminal_fcff_11_bridge_mm": _mm(terminal.fcff_11_bridge) if terminal else None,
                "terminal_fcff_11_value_driver_mm": _mm(terminal.fcff_11_value_driver) if terminal else None,
                "gordon_formula_mode": terminal.gordon_formula_mode if terminal else None,
                "health_tv_extreme_flag": _flag(health.get("tv_extreme_flag")),
                "health_terminal_growth_guardrail_flag": _flag(health.get("terminal_growth_guardrail_flag")),
                "health_terminal_ronic_guardrail_flag": _flag(health.get("terminal_ronic_guardrail_flag")),
                "health_terminal_denominator_guardrail_flag": _flag(health.get("terminal_denominator_guardrail_flag")),
                "health_fcff_interest_contamination_flag": _flag(health.get("fcff_interest_contamination_flag")),
                "scenario_prob_bear": next((s.probability for s in scenario_specs if s.name == "bear"), None),
                "scenario_prob_base": next((s.probability for s in scenario_specs if s.name == "base"), None),
                "scenario_prob_bull": next((s.probability for s in scenario_specs if s.name == "bull"), None),
                "forecast_bridge_json": json.dumps([asdict(p) for p in (base.projections if base else [])], separators=(",", ":")),
            }
        )

        return row

    except Exception as exc:
        logger.warning("  Failed to value %s: %s", ticker, exc, extra={"ticker": ticker, "step": "valuation"})
        return None


def export_to_excel(results: list[dict], output_path: Path):
    df = pd.DataFrame(results)

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        sort_col = "expected_upside_pct" if "expected_upside_pct" in df.columns else "upside_base_pct"

        summary_cols = [
            "ticker",
            "company_name",
            "sector",
            "price",
            "iv_bear",
            "iv_base",
            "iv_bull",
            "expected_iv",
            "ep_iv_base",
            "fcfe_iv_base",
            "upside_base_pct",
            "expected_upside_pct",
            "wacc",
            "model_applicability_status",
        ]
        df_summary = df[[c for c in summary_cols if c in df.columns]].copy()
        df_summary.sort_values(sort_col, ascending=False, inplace=True, na_position="last")
        df_summary.to_excel(writer, sheet_name="Summary", index=False)

        assumptions_cols = [
            "ticker",
            "growth_near",
            "growth_mid",
            "growth_source",
            "growth_source_detail",
            "revenue_period_type",
            "growth_period_type",
            "revenue_alignment_flag",
            "revenue_data_quality_flag",
            "ebit_margin_used",
            "ebit_margin_source",
            "capex_pct_used",
            "capex_source",
            "da_pct_used",
            "da_source",
            "tax_rate_used",
            "tax_source",
            "dso_used",
            "dso_source",
            "dio_used",
            "dio_source",
            "dpo_used",
            "dpo_source",
            "ronic_terminal_used",
            "ronic_terminal_source",
            "invested_capital_source",
            "non_operating_assets_used_mm",
            "non_operating_assets_source",
            "minority_interest_used_mm",
            "minority_interest_source",
            "preferred_equity_used_mm",
            "preferred_equity_source",
            "pension_deficit_used_mm",
            "pension_deficit_source",
            "lease_liabilities_used_mm",
            "lease_liabilities_source",
            "options_value_used_mm",
            "options_value_source",
            "convertibles_value_used_mm",
            "convertibles_value_source",
            "exit_multiple_used",
            "exit_multiple_source",
            "exit_metric_used",
            "revenue_source",
            "net_debt_source",
            "shares_source",
            "cost_of_equity_source",
            "debt_weight_source",
            "story_profile_source",
            "ciq_run_id",
            "ciq_source_file",
            "ciq_as_of_date",
            "ciq_comps_run_id",
            "ciq_comps_source_file",
            "ciq_comps_as_of_date",
        ]
        df_assumptions = df[[c for c in assumptions_cols if c in df.columns]].copy()
        df_assumptions.to_excel(writer, sheet_name="Assumptions & Sources", index=False)

        bridge_rows: list[dict] = []
        for _, row in df.iterrows():
            ticker = row.get("ticker")
            payload = row.get("forecast_bridge_json")
            if not payload:
                continue
            try:
                points = json.loads(payload)
            except Exception:
                continue
            for point in points:
                bridge_rows.append({"ticker": ticker, **point})
        pd.DataFrame(bridge_rows).to_excel(writer, sheet_name="Forecast Bridge (Y1-Y10)", index=False)

        wacc_cols = [
            "ticker",
            "wacc",
            "cost_of_equity",
            "beta_relevered",
            "beta_unlevered",
            "size_premium",
            "equity_weight",
            "peers_used",
        ]
        df_wacc = df[[c for c in wacc_cols if c in df.columns]].copy()
        df_wacc.to_excel(writer, sheet_name="WACC", index=False)

        terminal_cols = [
            "ticker",
            "ev_operations_mm",
            "ev_total_mm",
            "non_operating_assets_mm",
            "non_equity_claims_mm",
            "iv_gordon",
            "iv_exit",
            "iv_blended",
            "ep_iv_base",
            "fcfe_iv_base",
            "tv_gordon_mm",
            "tv_exit_mm",
            "tv_blended_mm",
            "pv_tv_gordon_mm",
            "pv_tv_exit_mm",
            "pv_tv_blended_mm",
            "terminal_growth_pct",
            "terminal_ronic_pct",
            "terminal_fcff_11_bridge_mm",
            "terminal_fcff_11_value_driver_mm",
            "gordon_formula_mode",
            "tv_pct_of_ev",
            "tv_method_fallback_flag",
            "tv_high_flag",
            "roic_consistency_flag",
            "nwc_driver_quality_flag",
            "health_tv_extreme_flag",
            "health_terminal_growth_guardrail_flag",
            "health_terminal_ronic_guardrail_flag",
            "health_terminal_denominator_guardrail_flag",
            "health_fcff_interest_contamination_flag",
            "ep_ev_operations_mm",
            "dcf_ep_gap_pct",
            "ep_reconcile_flag",
            "fcfe_equity_mm",
            "fcfe_pv_sum_mm",
            "fcfe_terminal_value_mm",
            "cost_of_equity_model",
        ]
        df_terminal = df[[c for c in terminal_cols if c in df.columns]].copy()
        df_terminal.to_excel(writer, sheet_name="Terminal Bridge (Gordon vs Exit vs Blend)", index=False)

        scenario_cols = [
            "ticker",
            "scenario_prob_bear",
            "scenario_prob_base",
            "scenario_prob_bull",
            "iv_bear",
            "iv_base",
            "iv_bull",
            "expected_iv",
            "expected_upside_pct",
            "ep_iv_base",
            "fcfe_iv_base",
        ]
        df_scenarios = df[[c for c in scenario_cols if c in df.columns]].copy()
        df_scenarios.to_excel(writer, sheet_name="Scenarios (with probabilities)", index=False)

        sensitivity_rows: list[dict] = []
        top_for_sensitivity = (
            df.sort_values(sort_col, ascending=False, na_position="last").head(25)
            if sort_col in df.columns
            else df.head(25)
        )
        for _, row in top_for_sensitivity.iterrows():
            drivers = _drivers_from_json(row.get("drivers_json"))
            if drivers is None:
                continue
            sensitivity_rows.extend(_sensitivity_rows(str(row.get("ticker")), drivers))
        pd.DataFrame(sensitivity_rows).to_excel(
            writer,
            sheet_name="Sensitivity (2D WACCxGrowth WACCxMultiple)",
            index=False,
        )

        df.to_excel(writer, sheet_name="All Data", index=False)

    logger.info("Saved Excel workbook to %s", output_path, extra={"step": "excel_export"})


def persist_results_to_db(df: pd.DataFrame, snapshot_date: str) -> tuple[int, int, int]:
    from db.schema import create_tables
    conn = sqlite3.connect(str(DB_PATH))
    create_tables(conn)
    try:
        latest_df = df.copy()
        latest_df["snapshot_date"] = snapshot_date
        latest_df.to_sql("batch_valuations_latest", conn, if_exists="replace", index=False)

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS valuations (
                ticker          TEXT NOT NULL,
                date            TEXT NOT NULL,
                market_cap_mm   REAL,
                ev_mm           REAL,
                pe_ttm          REAL,
                pe_fwd          REAL,
                ev_ebitda_ttm   REAL,
                ev_ebitda_fwd   REAL,
                ps_ttm          REAL,
                pfcf_ttm        REAL,
                dividend_yield  REAL,
                pe_5yr_avg      REAL,
                pe_vs_5yr_avg   REAL,
                PRIMARY KEY (ticker, date)
            )
            """
        )

        valuation_rows = []
        for _, row in df.iterrows():
            valuation_rows.append(
                (
                    row.get("ticker"),
                    snapshot_date,
                    _safe_float(row.get("market_cap_mm")),
                    _safe_float(row.get("ev_mm")),
                    _safe_float(row.get("pe_trailing")),
                    _safe_float(row.get("pe_forward")),
                    _safe_float(row.get("ev_ebitda")),
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                )
            )

        conn.executemany(
            """
            INSERT OR REPLACE INTO valuations (
                ticker, date, market_cap_mm, ev_mm, pe_ttm, pe_fwd,
                ev_ebitda_ttm, ev_ebitda_fwd, ps_ttm, pfcf_ttm,
                dividend_yield, pe_5yr_avg, pe_vs_5yr_avg
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            valuation_rows,
        )

        # Gap 7: DCF IV history — table defined in db/schema.py, created via create_tables()
        dcf_iv_rows = []
        for _, row in df.iterrows():
            if row.get("iv_base") is not None:
                dcf_iv_rows.append(
                    (
                        row.get("ticker"),
                        snapshot_date,
                        _safe_float(row.get("iv_bear")),
                        _safe_float(row.get("iv_base")),
                        _safe_float(row.get("iv_bull")),
                        _safe_float(row.get("expected_iv")),
                        _safe_float(row.get("price")),
                        _safe_float(row.get("expected_upside_pct")),
                        _safe_float(row.get("wacc")),
                        _safe_float(row.get("exit_multiple_used")),
                        row.get("net_debt_source"),
                        row.get("revenue_source"),
                    )
                )
        if dcf_iv_rows:
            conn.executemany(
                """
                INSERT OR REPLACE INTO dcf_valuations (
                    ticker, run_date, iv_bear, iv_base, iv_bull, iv_expected,
                    current_price, upside_pct, wacc, exit_multiple,
                    net_debt_source, revenue_source
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                dcf_iv_rows,
            )
        conn.commit()
        return len(latest_df), len(valuation_rows), len(dcf_iv_rows)
    finally:
        conn.close()


def run_batch(
    tickers: list[str] = None,
    top_n: int = 30,
    export_xlsx: bool = False,
    progress_callback: Callable[[dict], None] | None = None,
):
    logger.info("\n%s\nALPHA POD — Batch Valuation Runner\n%s\n", "=" * 64, "=" * 64, extra={"step": "run_batch"})

    if tickers is None:
        if not UNIVERSE_CSV.exists():
            logger.error("No universe.csv found. Run Stage 1 screener first.", extra={"step": "load_universe"})
            return
        with open(UNIVERSE_CSV, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            tickers = [row["ticker"] for row in reader]
        logger.info("Loaded %s tickers from universe.csv", len(tickers), extra={"step": "load_universe"})
    else:
        logger.info("Running on %s tickers", len(tickers), extra={"step": "load_universe"})

    if progress_callback is not None:
        progress_callback({"completed": 0, "total": len(tickers), "ticker": None, "status": "starting"})

    results = []
    failed_tickers: list[str] = []
    for i, ticker in enumerate(tickers, 1):
        result = value_single_ticker(ticker)
        if result:
            results.append(result)
            iv = result.get("expected_iv") if result.get("expected_iv") is not None else result.get("iv_base")
            upside = result.get("expected_upside_pct")
            if upside is None:
                upside = result.get("upside_base_pct")
            if iv is None:
                summary = f"${result['price']:>8.2f}  alt-model"
            else:
                summary = (
                    f"${result['price']:>8.2f} → ${iv:>8.2f}  "
                    f"({upside:>+6.1f}%)  WACC {result['wacc']:.1f}%"
                )
            logger.info(
                "  [%3d/%d] %-8s %s",
                i,
                len(tickers),
                ticker,
                summary,
                extra={"ticker": ticker, "step": "run_batch"},
            )
        else:
            failed_tickers.append(ticker)
            logger.warning(
                "  [%3d/%d] %-8s skipped (insufficient data)",
                i,
                len(tickers),
                ticker,
                extra={"ticker": ticker, "step": "run_batch"},
            )

        if progress_callback is not None:
            progress_callback(
                {
                    "completed": i,
                    "total": len(tickers),
                    "ticker": ticker,
                    "status": "valued" if result else "skipped",
                }
            )

        time.sleep(0.3)

    logger.info(
        "\n  Completed: %s valued, %s skipped",
        len(results),
        len(failed_tickers),
        extra={"step": "run_batch"},
    )
    if failed_tickers:
        logger.warning("  Failed tickers: %s", ", ".join(failed_tickers), extra={"step": "run_batch"})

    if not results:
        logger.warning("No results to export.", extra={"step": "run_batch"})
        return

    sort_col = "expected_upside_pct" if any(r.get("expected_upside_pct") is not None for r in results) else "upside_base_pct"
    results.sort(key=lambda r: (r.get(sort_col) is not None, r.get(sort_col) if r.get(sort_col) is not None else -1e9), reverse=True)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")
    df = pd.DataFrame(results)

    latest_csv = OUTPUT_DIR / "latest.csv"
    df.to_csv(latest_csv, index=False)
    logger.info("CSV export written to %s", latest_csv, extra={"step": "run_batch"})

    # Gap 6: write batch_errors.json alongside CSV when failures occurred
    if failed_tickers:
        errors_path = OUTPUT_DIR / "batch_errors.json"
        with errors_path.open("w", encoding="utf-8") as _ef:
            json.dump({"run_date": today, "failed": failed_tickers}, _ef, indent=2)
        logger.warning(
            "Error summary written to %s (%s failed)",
            errors_path,
            len(failed_tickers),
            extra={"step": "run_batch"},
        )

    latest_rows, valuation_rows, dcf_rows = persist_results_to_db(df, snapshot_date=today)
    logger.info("SQLite snapshot written to %s", DB_PATH, extra={"step": "run_batch"})
    logger.info(
        "  batch_valuations_latest=%s, valuations=%s, dcf_valuations=%s",
        latest_rows,
        valuation_rows,
        dcf_rows,
        extra={"step": "run_batch"},
    )

    xlsx_path = None
    if export_xlsx:
        xlsx_path = OUTPUT_DIR / f"batch_valuation_{today}.xlsx"
        export_to_excel(results, xlsx_path)

    lines = [
        "",
        "=" * 64,
        f"TOP {min(top_n, len(results))} BY {sort_col.upper()}",
        "=" * 64,
        f"{'Ticker':<8} {'Company':<30} {'Price':>8} {'Exp IV':>8} {'Exp Up':>8} {'Base IV':>8} {'WACC':>6} {'Status'}",
        "-" * 116,
    ]

    for r in results[:top_n]:
        exp_iv = r.get("expected_iv")
        exp_up = r.get("expected_upside_pct")
        lines.append(
            f"{r['ticker']:<8} {r['company_name'][:29]:<30} "
            f"${r['price']:>7.2f} "
            f"{('$' + format(exp_iv, '7.2f')) if exp_iv is not None else '    N/A ':>8} "
            f"{(format(exp_up, '+7.1f') + '%') if exp_up is not None else '   N/A ':>8} "
            f"{('$' + format(r.get('iv_base'), '7.2f')) if r.get('iv_base') is not None else '    N/A ':>8} "
            f"{r['wacc']:>5.1f}% "
            f"{r.get('model_applicability_status', '')}"
        )
    logger.info("\n".join(lines), extra={"step": "run_batch"})

    if xlsx_path:
        logger.info("Excel workbook: %s", xlsx_path, extra={"step": "run_batch"})
    else:
        logger.info("Excel: skipped (pass --xlsx to export workbook)", extra={"step": "run_batch"})
    logger.info("CSV (for Power Query): %s", latest_csv, extra={"step": "run_batch"})

    if progress_callback is not None:
        progress_callback({"completed": len(tickers), "total": len(tickers), "ticker": None, "status": "complete"})

    return results


def _print_ic_memo(memo) -> None:
    """Print a Rich summary panel of the IC memo from the orchestrator."""
    try:
        from rich.console import Console
        from rich.panel import Panel
        from rich.table import Table

        console = Console()

        # Valuation row
        v = memo.valuation
        bear = getattr(v, "bear", None)
        base = getattr(v, "base", None)
        bull = getattr(v, "bull", None)
        price = getattr(v, "current_price", None)
        upside = ((base / price) - 1) * 100 if base and price else None

        # Risk row
        r = memo.risk
        conviction = getattr(r, "conviction", "?").upper()
        pos_size = getattr(r, "position_size_usd", None)
        stop = getattr(r, "suggested_stop_loss_pct", None)

        t = Table(show_header=False, box=None, padding=(0, 2))
        t.add_column(style="bold cyan", no_wrap=True)
        t.add_column()

        t.add_row("Action", f"[bold]{getattr(memo, 'action', '?')}[/bold]  ({conviction} conviction)")
        t.add_row("Thesis", getattr(memo, "one_liner", ""))
        if bear is not None:
            t.add_row(
                "Valuation",
                f"Bear ${bear:,.0f}  |  Base ${base:,.0f}  |  Bull ${bull:,.0f}"
                + (f"  |  Upside {upside:+.1f}%" if upside is not None else ""),
            )
        if pos_size is not None:
            t.add_row(
                "Sizing",
                f"${pos_size:,.0f}"
                + (f"  |  Stop {stop*100:.0f}%" if stop else ""),
            )
        accounting_recast = getattr(memo, "accounting_recast", {}) or {}
        if accounting_recast:
            adjustments = len(accounting_recast.get("income_statement_adjustments") or [])
            reclasses = len(accounting_recast.get("balance_sheet_reclassifications") or [])
            confidence = accounting_recast.get("confidence", "low")
            t.add_row(
                "Accounting recast",
                f"{confidence} confidence  |  {adjustments} adj  |  {reclasses} reclasses  |  approval required",
            )
        t.add_row("Filings", getattr(memo.filings, "revenue_trend", "") or "")
        t.add_row("Earnings", getattr(memo.earnings, "guidance_trend", "") or "")
        t.add_row("Sentiment", getattr(memo.sentiment, "direction", "") or "")
        t.add_row("Variant thesis", getattr(memo, "variant_thesis_prompt", "") or "")

        console.print()
        console.print(Panel(
            t,
            title=f"[bold blue]IC MEMO — {memo.ticker}  {memo.company_name}[/bold blue]",
            border_style="blue",
        ))
    except Exception as e:
        logger.warning("\n[IC Memo] Could not render Rich panel: %s", e, extra={"step": "ic_memo"})
        logger.info("  Action: %s", getattr(memo, "action", "?"), extra={"step": "ic_memo"})
        logger.info("  Thesis: %s", getattr(memo, "one_liner", "?"), extra={"step": "ic_memo"})


def _print_recommendations(recs) -> None:
    """Print a compact summary of agent recommendations to console."""
    if not recs or not recs.recommendations:
        logger.info(
            "\n  No agent recommendations generated for %s.",
            getattr(recs, "ticker", "?"),
            extra={"step": "recommendations"},
        )
        return

    try:
        from rich.console import Console
        from rich.table import Table
        from rich.panel import Panel

        console = Console()
        table = Table(show_header=True, box=None, padding=(0, 2))
        table.add_column("#", style="dim", width=3)
        table.add_column("Agent", style="bold cyan", width=18)
        table.add_column("Field", width=22)
        table.add_column("Current", justify="right", width=10)
        table.add_column("Proposed", justify="right", width=10)
        table.add_column("Conf", width=8)
        table.add_column("Status", width=10)

        for i, rec in enumerate(recs.recommendations):
            cur_str = f"{rec.current_value:.4f}" if rec.current_value is not None else "—"
            prop_str = (
                f"{rec.proposed_value:.4f}"
                if isinstance(rec.proposed_value, float)
                else str(rec.proposed_value)
            )
            status_style = {
                "approved": "[bold green]approved[/bold green]",
                "rejected": "[red]rejected[/red]",
                "pending": "[yellow]pending[/yellow]",
            }.get(rec.status, rec.status)
            table.add_row(
                str(i), f"{rec.agent}", rec.field,
                cur_str, prop_str, rec.confidence, status_style,
            )

        iv_str = f"  Current base IV: ${recs.current_iv_base:,.2f}" if recs.current_iv_base else ""
        console.print()
        console.print(Panel(
            table,
            title=f"[bold blue]Agent Recommendations — {recs.ticker}[/bold blue]{iv_str}",
            border_style="blue",
        ))
        pending_count = sum(1 for r in recs.recommendations if r.status == "pending")
        if pending_count:
            console.print(f"  [yellow]{pending_count} pending item(s)[/yellow] — run [bold]--approve {recs.ticker}[/bold] to review")
    except Exception as e:
        logger.warning(
            "\nAgent Recommendations — %s (Rich render failed: %s):",
            getattr(recs, "ticker", "?"),
            e,
            extra={"step": "recommendations"},
        )
        for i, rec in enumerate(recs.recommendations):
            prop = f"{rec.proposed_value:.4f}" if isinstance(rec.proposed_value, float) else str(rec.proposed_value)
            logger.info(
                "  [%s] %s.%s: %s → %s [%s] %s",
                i,
                rec.agent,
                rec.field,
                rec.current_value,
                prop,
                rec.confidence,
                rec.status,
                extra={"step": "recommendations"},
            )


if __name__ == "__main__":
    import argparse

    configure_logging(force=True)

    parser = argparse.ArgumentParser(description="Batch valuation runner")
    parser.add_argument("--top", type=int, default=30, help="Show top N results")
    parser.add_argument("--ticker", type=str, help="Run single ticker deep dive")
    parser.add_argument("--limit", type=int, help="Limit number of tickers to value")
    parser.add_argument("--xlsx", action="store_true", help="Export dated Excel workbook")
    parser.add_argument("--json", action="store_true", help="Export per-ticker JSON files")
    parser.add_argument("--qoe", action="store_true", help="Include QoE signals in JSON (requires --json)")
    parser.add_argument("--qoe-llm", action="store_true",
                        help="Run QoE LLM normalisation and write pending override to config/qoe_pending.yaml (requires --ticker)")
    parser.add_argument("--full", action="store_true",
                        help="Run full research pipeline (requires --ticker and LLM API credentials)")
    parser.add_argument("--story-profile", action="store_true",
                        help="Generate LLM story driver profile and write to config/story_drivers_pending.yaml (requires --ticker)")
    parser.add_argument("--macro", action="store_true",
                        help="Refresh data/macro_context.md from web search (needs an LLM provider key plus PERPLEXITY_API_KEY)")
    parser.add_argument("--review", action="store_true",
                        help="Display pending agent recommendations for --ticker")
    parser.add_argument("--approve", action="store_true",
                        help="Interactive approval of pending recommendations for --ticker; applies approved items to valuation_overrides.yaml and re-runs valuation")
    args = parser.parse_args()

    # ── --macro: refresh macro context file ──────────────────────────────────
    if args.macro:
        from src.stage_03_judgment.macro_agent import MacroAgent, MACRO_OUTPUT_PATH
        logger.info("Refreshing macro context...", extra={"step": "macro"})
        macro = MacroAgent()
        macro.refresh()
        logger.info("Macro context written to %s", MACRO_OUTPUT_PATH, extra={"step": "macro"})
        if not args.ticker and not args.full:
            sys.exit(0)

    if args.ticker:
        # ── --full: run 9-agent pipeline + collect recommendations ─────────────
        if args.full:
            from src.stage_04_pipeline.orchestrator import PipelineOrchestrator
            from src.stage_04_pipeline.recommendations import write_recommendations
            orch = PipelineOrchestrator()
            memo = orch.run(args.ticker)
            _print_ic_memo(memo)
            recs = orch.collect_recommendations(args.ticker)
            rec_path = write_recommendations(recs)
            _print_recommendations(recs)
            logger.info(
                "\n  → Recommendations written to %s\n  → Run --review %s to see pending items\n  → Run --approve %s to approve interactively",
                rec_path,
                args.ticker,
                args.ticker,
                extra={"ticker": args.ticker.upper(), "step": "recommendations"},
            )
            sys.exit(0)

        # ── --review: display pending recommendations ─────────────────────────
        if args.review:
            from src.stage_04_pipeline.recommendations import load_recommendations
            recs = load_recommendations(args.ticker)
            if recs is None:
                logger.error(
                    "No recommendations found for %s. Run --full first.",
                    args.ticker.upper(),
                    extra={"ticker": args.ticker.upper(), "step": "recommendations"},
                )
                sys.exit(1)
            _print_recommendations(recs)
            sys.exit(0)

        # ── --approve: interactive approval ───────────────────────────────────
        if args.approve:
            from src.stage_04_pipeline.recommendations import (
                load_recommendations,
                write_recommendations,
                apply_approved_to_overrides,
            )
            from src.stage_02_valuation.input_assembler import clear_valuation_overrides_cache

            recs = load_recommendations(args.ticker)
            if recs is None:
                logger.error(
                    "No recommendations found for %s. Run --full first.",
                    args.ticker.upper(),
                    extra={"ticker": args.ticker.upper(), "step": "approve"},
                )
                sys.exit(1)

            pending = [r for r in recs.recommendations if r.status == "pending"]
            if not pending:
                logger.info(
                    "No pending recommendations for %s.",
                    args.ticker.upper(),
                    extra={"ticker": args.ticker.upper(), "step": "approve"},
                )
                _print_recommendations(recs)
                sys.exit(0)

            lines = [f"\nPending recommendations for {args.ticker.upper()}:", "─" * 60]
            for i, rec in enumerate(pending):
                cur_str = f"{rec.current_value:.4f}" if rec.current_value is not None else "none"
                prop_str = (
                    f"{rec.proposed_value:.4f}"
                    if isinstance(rec.proposed_value, float)
                    else str(rec.proposed_value)
                )
                lines.append(f"  [{i}] [{rec.confidence.upper()}] {rec.agent}.{rec.field}")
                lines.append(f"        {cur_str}  →  {prop_str}")
                lines.append(f"        {rec.rationale}")
                if rec.citation:
                    lines.append(f"        Citation: {rec.citation[:120]}")
                lines.append("")

            logger.info(
                "\n".join(lines),
                extra={"ticker": args.ticker.upper(), "step": "approve"},
            )
            raw_input = input("Enter indices to approve (space-separated), or 'all', or blank to skip:\n> ").strip().lower()

            if raw_input == "all":
                indices = list(range(len(pending)))
            elif raw_input == "":
                logger.info("No items approved.", extra={"ticker": args.ticker.upper(), "step": "approve"})
                sys.exit(0)
            else:
                indices = []
                for tok in raw_input.split():
                    try:
                        idx = int(tok)
                        if 0 <= idx < len(pending):
                            indices.append(idx)
                    except ValueError:
                        pass

            # Update statuses in the full recommendations list
            approved_fields = []
            pending_by_key = {f"{r.agent}:{r.field}": r for r in recs.recommendations if r.status == "pending"}
            for i in indices:
                rec = pending[i]
                key = f"{rec.agent}:{rec.field}"
                if key in pending_by_key:
                    pending_by_key[key].status = "approved"
                    approved_fields.append(rec.field)

            write_recommendations(recs)

            count = apply_approved_to_overrides(args.ticker)
            clear_valuation_overrides_cache()
            logger.info(
                "\n%s override(s) written to config/valuation_overrides.yaml",
                count,
                extra={"ticker": args.ticker.upper(), "step": "approve"},
            )

            if count > 0:
                logger.info(
                    "\nRe-running valuation for %s...",
                    args.ticker.upper(),
                    extra={"ticker": args.ticker.upper(), "step": "approve"},
                )
                from src.stage_04_pipeline.recommendations import preview_with_approvals
                preview = preview_with_approvals(args.ticker, approved_fields)
                if preview:
                    cur = preview.get("current_iv", {})
                    prop = preview.get("proposed_iv", {})
                    dlt = preview.get("delta_pct", {})
                    lines = [
                        "",
                        f"  {'Scenario':<10}  {'Current IV':>12}  {'Proposed IV':>12}  {'Delta':>8}",
                        f"  {'-'*10}  {'-'*12}  {'-'*12}  {'-'*8}",
                    ]
                    for scenario in ("bear", "base", "bull"):
                        c = cur.get(scenario)
                        p = prop.get(scenario)
                        d = dlt.get(scenario)
                        c_str = f"${c:,.2f}" if c is not None else "—"
                        p_str = f"${p:,.2f}" if p is not None else "—"
                        d_str = f"{d:+.1f}%" if d is not None else "—"
                        lines.append(f"  {scenario.capitalize():<10}  {c_str:>12}  {p_str:>12}  {d_str:>8}")
                    logger.info(
                        "\n".join(lines),
                        extra={"ticker": args.ticker.upper(), "step": "approve"},
                    )
            sys.exit(0)

        # ── --story-profile: generate LLM story driver profile ────────────────
        if getattr(args, "story_profile", False):
            from src.stage_03_judgment.thesis_agent import ThesisAgent, write_story_driver_pending
            from src.stage_02_valuation.templates.ic_memo import FilingsSummary, EarningsSummary
            logger.info(
                "\n%s\nStory Profile Generation — %s\n%s",
                "=" * 60,
                args.ticker.upper(),
                "=" * 60,
                extra={"ticker": args.ticker.upper(), "step": "story_profile"},
            )
            try:
                agent = ThesisAgent()
                # Use lightweight stubs so we don't need a full pipeline run
                filings = FilingsSummary(raw_summary="No filings context — direct story profile run")
                earnings = EarningsSummary(raw_summary="No earnings context — direct story profile run")
                mkt = __import__("src.stage_00_data.market_data", fromlist=["get_market_data"]).get_market_data(args.ticker)
                profile = agent.generate_story_profile(
                    ticker=args.ticker,
                    company_name=mkt.get("name") or args.ticker,
                    sector=mkt.get("sector") or "Unknown",
                    filings=filings,
                    earnings=earnings,
                )
                if profile:
                    path = write_story_driver_pending(args.ticker, profile)
                    logger.info(
                        "\n  Moat:          %s/5\n  Pricing power: %s/5\n  Cyclicality:   %s\n  Cap intensity: %s\n  Gov risk:      %s\n  Moat years:    %s",
                        profile.get("moat_strength"),
                        profile.get("pricing_power"),
                        profile.get("cyclicality"),
                        profile.get("capital_intensity"),
                        profile.get("governance_risk"),
                        profile.get("competitive_advantage_years"),
                        extra={"ticker": args.ticker.upper(), "step": "story_profile"},
                    )
                    if profile.get("rationale"):
                        logger.info(
                            "\n  Rationale: %s",
                            profile["rationale"],
                            extra={"ticker": args.ticker.upper(), "step": "story_profile"},
                        )
                    logger.info(
                        "\n  → Written to %s\n  → Set status: approved to apply on next valuation run",
                        path,
                        extra={"ticker": args.ticker.upper(), "step": "story_profile"},
                    )
                else:
                    logger.error(
                        "  Story profile generation failed",
                        extra={"ticker": args.ticker.upper(), "step": "story_profile"},
                    )
            except Exception as exc:
                logger.error(
                    "  Story profile error: %s",
                    exc,
                    extra={"ticker": args.ticker.upper(), "step": "story_profile"},
                )
            if not args.json and not args.qoe_llm:
                sys.exit(0)

        # ── deterministic valuation (default) ────────────────────────────────
        result = value_single_ticker(args.ticker)
        if result:
            sys.stdout.write(f"{json.dumps(result, indent=2)}\n")

            # ── --qoe-llm: LLM normalisation + write pending override ─────────
            if getattr(args, "qoe_llm", False):
                _run_qoe_llm(args.ticker, result)

            if args.json:
                today = datetime.now().strftime("%Y-%m-%d")
                json_dir = OUTPUT_DIR / "json"
                qoe_data = _compute_qoe_for_ticker(args.ticker) if args.qoe else None
                comps_data = get_ciq_comps_detail(args.ticker)
                comps_analysis = build_comps_dashboard_view(args.ticker)
                out_path = export_ticker_json(
                    result,
                    qoe=qoe_data,
                    comps_detail=comps_data,
                    comps_analysis=comps_analysis,
                    output_dir=json_dir, date_str=today,
                )
                logger.info(
                    "\nJSON export written to %s\nJSON latest written to %s",
                    out_path,
                    json_dir / (args.ticker.upper() + "_latest.json"),
                    extra={"ticker": args.ticker.upper(), "step": "json_export"},
                )
        else:
            logger.error("Could not value %s", args.ticker, extra={"ticker": args.ticker.upper(), "step": "valuation"})
    else:
        if args.full:
            logger.error("--full requires --ticker", extra={"step": "cli"})
            sys.exit(1)
        tickers = None
        if args.limit:
            with open(UNIVERSE_CSV, encoding="utf-8") as f:
                reader = csv.DictReader(f)
                tickers = [row["ticker"] for row in reader][: args.limit]
        results = run_batch(tickers=tickers, top_n=args.top, export_xlsx=args.xlsx)
        if args.json and results:
            today = datetime.now().strftime("%Y-%m-%d")
            json_dir = OUTPUT_DIR / "json"
            json_dir.mkdir(parents=True, exist_ok=True)
            for result in results:
                t = result.get("ticker", "UNKNOWN")
                qoe_data = _compute_qoe_for_ticker(t) if args.qoe else None
                comps_data = get_ciq_comps_detail(t)
                comps_analysis = build_comps_dashboard_view(t)
                export_ticker_json(
                    result,
                    qoe=qoe_data,
                    comps_detail=comps_data,
                    comps_analysis=comps_analysis,
                    output_dir=json_dir, date_str=today,
                )
            logger.info("\nJSON exports written to %s", json_dir, extra={"step": "json_export"})
