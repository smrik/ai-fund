"""
Deterministic Quality of Earnings signal computation — no LLM involved.

All signals are computed from data already in the pipeline:
  - ciq_snapshot   → get_ciq_snapshot()
  - ciq_nwc_history → get_ciq_nwc_history()
  - hist           → get_historical_financials()
  - mkt            → get_market_data()

Never raises. Returns "unavailable" for any signal where data is missing.
"""
from __future__ import annotations

from typing import Any


# ── Sector-specific accruals thresholds (fraction of revenue) ────────────────
# Higher thresholds for sectors with structurally elevated non-cash charges
# (stock-based comp in Tech, amortisation of intangibles in Healthcare/Comms).
SECTOR_ACCRUALS_THRESHOLDS: dict[str, dict[str, float]] = {
    "Technology":             {"amber": 0.08, "red": 0.15},
    "Communication Services": {"amber": 0.07, "red": 0.13},
    "Healthcare":             {"amber": 0.07, "red": 0.13},
    "Consumer Cyclical":      {"amber": 0.05, "red": 0.10},
    "Consumer Defensive":     {"amber": 0.04, "red": 0.08},
    "Industrials":            {"amber": 0.05, "red": 0.10},
    "Energy":                 {"amber": 0.06, "red": 0.12},
    "Basic Materials":        {"amber": 0.05, "red": 0.10},
    "Utilities":              {"amber": 0.04, "red": 0.08},
    "_default":               {"amber": 0.05, "red": 0.10},
}

# ── Universal thresholds ─────────────────────────────────────────────────────
# Cash conversion: CFFO / EBITDA (TTM). Seasonality handled by using TTM.
CASH_CONVERSION_GREEN = 0.85
CASH_CONVERSION_AMBER = 0.65   # below amber = red

# NWC drift (days): positive = metric increased (worse for DSO/DIO, worse for DPO stretch)
NWC_DRIFT_AMBER = 5.0
NWC_DRIFT_RED = 15.0

# Capex / D&A ratio: below 1.0 = under-investing in asset base
CAPEX_DA_GREEN = 1.0
CAPEX_DA_AMBER = 0.7           # below amber = red


def _to_float(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _score_high_is_bad(value: float | None, amber_threshold: float, red_threshold: float) -> str:
    """Score a signal where higher values signal worse quality (accruals, NWC drift)."""
    if value is None:
        return "unavailable"
    if value < amber_threshold:
        return "green"
    if value < red_threshold:
        return "amber"
    return "red"


def _score_low_is_bad(value: float | None, green_threshold: float, amber_threshold: float) -> str:
    """Score a signal where lower values signal worse quality (cash conversion, Capex/DA)."""
    if value is None:
        return "unavailable"
    if value >= green_threshold:
        return "green"
    if value >= amber_threshold:
        return "amber"
    return "red"


def _nwc_baseline(
    ciq_nwc_history: list[dict],
    key: str,
    sector_default: float,
) -> tuple[float | None, str]:
    """
    Determine the NWC baseline for drift computation.

    Logic (per PM decision 2026-03-08):
    - 2+ CIQ periods: average of periods[1:] (older entries) as baseline
    - 1 CIQ period:   sector default (only have current, no trend comparison)
    - 0 CIQ periods:  unavailable (signal excluded from composite)
    """
    if len(ciq_nwc_history) >= 2:
        older = [p[key] for p in ciq_nwc_history[1:] if p.get(key) is not None]
        if older:
            return round(sum(older) / len(older), 1), "ciq_history"
    if len(ciq_nwc_history) == 1:
        return sector_default, "sector_default"
    return None, "unavailable"


def _composite_score(signal_scores: dict[str, str]) -> tuple[int, str]:
    """
    Convert per-signal scores into composite QoE score (1–5) and flag.

    Rules (per spec §3.7):
      5 : 0 reds, 0 ambers
      4 : 0 reds, 1 amber
      3 : 0 reds 2+ ambers  OR  1 red
      2 : 2 reds             OR  4+ ambers
      1 : 3+ reds

    Flag: score 4-5 → green | score 3 → amber | score 1-2 → red
    Unavailable signals are excluded from red/amber counts.
    """
    countable = {k: v for k, v in signal_scores.items() if v in {"green", "amber", "red"}}
    n_red = sum(1 for v in countable.values() if v == "red")
    n_amber = sum(1 for v in countable.values() if v == "amber")

    if n_red >= 3:
        score = 1
    elif n_red == 2 or n_amber >= 4:
        score = 2
    elif n_red == 1 or n_amber >= 2:
        score = 3
    elif n_amber == 1:
        score = 4
    else:
        score = 5

    flag = "green" if score >= 4 else ("amber" if score == 3 else "red")
    return score, flag


def compute_qoe_signals(
    ticker: str,
    sector: str,
    ciq_snapshot: dict | None,
    ciq_nwc_history: list[dict],
    hist: dict,
    mkt: dict,
) -> dict:
    """
    Compute all deterministic QoE signals. Never raises.

    Parameters
    ----------
    ticker          : company ticker
    sector          : sector string — used for accruals thresholds and NWC defaults
    ciq_snapshot    : output of get_ciq_snapshot() — may be None
    ciq_nwc_history : output of get_ciq_nwc_history() — list newest first
    hist            : output of get_historical_financials()
    mkt             : output of get_market_data()

    Returns a flat dict containing raw values, per-signal scores, composite
    score (1–5), composite flag (green/amber/red), and thresholds used.
    """
    from src.stage_02_valuation.input_assembler import SECTOR_DEFAULTS

    ciq = ciq_snapshot or {}
    sector_def = SECTOR_DEFAULTS.get(sector, SECTOR_DEFAULTS["_default"])
    accruals_thresh = SECTOR_ACCRUALS_THRESHOLDS.get(sector, SECTOR_ACCRUALS_THRESHOLDS["_default"])

    # ── 1. Sloan Accruals Ratio ──────────────────────────────────────────────
    # Operating Accruals = (Net Income − CFFO) / Revenue
    net_income_series: list = hist.get("net_income") or []
    cffo_series: list = hist.get("cffo") or []
    revenue_series: list = hist.get("revenue") or []

    sloan_accruals_ratio: float | None = None
    if net_income_series and cffo_series and revenue_series:
        ni = _to_float(net_income_series[0])
        cffo0 = _to_float(cffo_series[0])
        rev = _to_float(revenue_series[0])
        if ni is not None and cffo0 is not None and rev and rev > 0:
            sloan_accruals_ratio = round((ni - cffo0) / rev, 4)

    accruals_score = _score_high_is_bad(
        sloan_accruals_ratio,
        accruals_thresh["amber"],
        accruals_thresh["red"],
    )

    # ── 2. Cash Conversion (CFFO / EBITDA, TTM) ─────────────────────────────
    # TTM CFFO = most recent annual period from hist
    # EBITDA: prefer CIQ (op_income + D&A), fall back to yfinance ebitda_ttm
    cffo_ttm = _to_float(cffo_series[0]) if cffo_series else None

    ciq_op = _to_float(ciq.get("operating_income_ttm"))
    ciq_da = _to_float(ciq.get("da_ttm"))
    ebitda_ttm = (ciq_op + ciq_da) if (ciq_op is not None and ciq_da is not None) else None
    if ebitda_ttm is None:
        ebitda_ttm = _to_float(mkt.get("ebitda_ttm"))

    cash_conversion: float | None = None
    if cffo_ttm is not None and ebitda_ttm and ebitda_ttm > 0:
        cash_conversion = round(cffo_ttm / ebitda_ttm, 4)

    cash_conversion_score = _score_low_is_bad(cash_conversion, CASH_CONVERSION_GREEN, CASH_CONVERSION_AMBER)

    # ── 3. DSO Drift ─────────────────────────────────────────────────────────
    current_dso = _to_float(ciq.get("dso"))
    dso_baseline, dso_baseline_source = _nwc_baseline(ciq_nwc_history, "dso", sector_def["dso"])
    dso_drift: float | None = None
    if current_dso is not None and dso_baseline is not None:
        dso_drift = round(current_dso - dso_baseline, 1)
    dso_score = "unavailable" if current_dso is None else _score_high_is_bad(dso_drift, NWC_DRIFT_AMBER, NWC_DRIFT_RED)

    # ── 4. DIO Drift ─────────────────────────────────────────────────────────
    current_dio = _to_float(ciq.get("dio"))
    dio_baseline, dio_baseline_source = _nwc_baseline(ciq_nwc_history, "dio", sector_def["dio"])
    dio_drift: float | None = None
    if current_dio is not None and dio_baseline is not None:
        dio_drift = round(current_dio - dio_baseline, 1)
    dio_score = "unavailable" if current_dio is None else _score_high_is_bad(dio_drift, NWC_DRIFT_AMBER, NWC_DRIFT_RED)

    # ── 5. DPO Stretch ───────────────────────────────────────────────────────
    current_dpo = _to_float(ciq.get("dpo"))
    dpo_baseline, dpo_baseline_source = _nwc_baseline(ciq_nwc_history, "dpo", sector_def["dpo"])
    dpo_drift: float | None = None
    if current_dpo is not None and dpo_baseline is not None:
        dpo_drift = round(current_dpo - dpo_baseline, 1)
    dpo_score = "unavailable" if current_dpo is None else _score_high_is_bad(dpo_drift, NWC_DRIFT_AMBER, NWC_DRIFT_RED)

    # ── 6. Capex / D&A ───────────────────────────────────────────────────────
    capex_series: list = hist.get("capex") or []
    da_series: list = hist.get("da") or []
    capex_da_ratio: float | None = None
    if capex_series and da_series:
        capex0 = _to_float(capex_series[0])
        da0 = _to_float(da_series[0])
        if capex0 is not None and da0 and da0 > 0:
            capex_da_ratio = round(capex0 / da0, 4)

    capex_da_score = _score_low_is_bad(capex_da_ratio, CAPEX_DA_GREEN, CAPEX_DA_AMBER)

    # ── Composite ────────────────────────────────────────────────────────────
    signal_scores = {
        "accruals": accruals_score,
        "cash_conversion": cash_conversion_score,
        "dso": dso_score,
        "dio": dio_score,
        "dpo": dpo_score,
        "capex_da": capex_da_score,
    }
    qoe_score, qoe_flag = _composite_score(signal_scores)

    # ── Forensic Scores (M-Score, Z-Score) ───────────────────────────────────
    # Complementary signals — NOT integrated into QoE composite scoring.
    try:
        from src.stage_03_judgment.forensic_scores import compute_forensic_signals
        forensic = compute_forensic_signals(hist, mkt.get("market_cap_mm"), sector)
    except Exception:
        forensic = {"available": False, "error": "forensic_scores unavailable"}

    return {
        "ticker": ticker.upper(),
        "sector": sector,
        "qoe_score": qoe_score,
        "qoe_flag": qoe_flag,
        # Raw metric values
        "sloan_accruals_ratio": sloan_accruals_ratio,
        "cash_conversion": cash_conversion,
        "dso_current": current_dso,
        "dso_baseline": dso_baseline,
        "dso_baseline_source": dso_baseline_source,
        "dso_drift": dso_drift,
        "dio_current": current_dio,
        "dio_baseline": dio_baseline,
        "dio_baseline_source": dio_baseline_source,
        "dio_drift": dio_drift,
        "dpo_current": current_dpo,
        "dpo_baseline": dpo_baseline,
        "dpo_baseline_source": dpo_baseline_source,
        "dpo_drift": dpo_drift,
        "capex_da_ratio": capex_da_ratio,
        # Per-signal scores
        "signal_scores": signal_scores,
        # Thresholds used (for audit trail)
        "accruals_thresholds": accruals_thresh,
        # Forensic scores (M-Score / Z-Score) — complementary, not in composite
        "forensic": forensic,
        "m_score": forensic.get("m_score"),
        "m_score_zone": forensic.get("m_score_zone"),
        "z_score": forensic.get("z_score"),
        "z_score_zone": forensic.get("z_score_zone"),
        "forensic_flag": forensic.get("forensic_flag"),
    }
