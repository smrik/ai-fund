"""Deterministic valuation input assembly with source lineage and manual overrides."""
from __future__ import annotations

import functools
from dataclasses import asdict, dataclass, field
from typing import Any

import yaml

from config import ROOT_DIR
from src.stage_00_data import market_data as md_client
from src.stage_00_data.ciq_adapter import get_ciq_comps_detail, get_ciq_comps_valuation, get_ciq_snapshot
from src.stage_00_data.sec_filing_metrics import get_bridge_items_from_xbrl
from src.stage_02_valuation.public_comps_fallback import build_public_market_fallback_comps_detail
from src.stage_02_valuation.story_drivers import apply_story_driver_adjustments, resolve_story_driver_profile
from src.stage_02_valuation.valuation_types import ForecastDrivers
from src.stage_02_valuation.wacc import (
    blend_wacc_results,
    compute_wacc_from_yfinance,
    compute_wacc_methodology_set_for_ticker,
)


OVERRIDES_PATH = ROOT_DIR / "config" / "valuation_overrides.yaml"
QOE_PENDING_PATH = ROOT_DIR / "config" / "qoe_pending.yaml"


SECTOR_DEFAULTS = {
    "Technology": {"growth_near": 0.12, "margin": 0.20, "capex_pct": 0.06, "da_pct": 0.04, "dso": 45.0, "dio": 35.0, "dpo": 38.0, "exit_multiple": 16.0, "ic_turnover": 1.60, "ronic_terminal": 0.15, "growth_fade_ratio": 0.70, "terminal_growth": 0.035},
    "Communication Services": {"growth_near": 0.10, "margin": 0.18, "capex_pct": 0.05, "da_pct": 0.04, "dso": 50.0, "dio": 30.0, "dpo": 42.0, "exit_multiple": 14.0, "ic_turnover": 1.50, "ronic_terminal": 0.14, "growth_fade_ratio": 0.65, "terminal_growth": 0.030},
    "Healthcare": {"growth_near": 0.09, "margin": 0.18, "capex_pct": 0.05, "da_pct": 0.04, "dso": 52.0, "dio": 45.0, "dpo": 40.0, "exit_multiple": 14.0, "ic_turnover": 1.30, "ronic_terminal": 0.13, "growth_fade_ratio": 0.65, "terminal_growth": 0.030},
    "Consumer Cyclical": {"growth_near": 0.08, "margin": 0.14, "capex_pct": 0.05, "da_pct": 0.04, "dso": 42.0, "dio": 55.0, "dpo": 48.0, "exit_multiple": 12.0, "ic_turnover": 1.80, "ronic_terminal": 0.12, "growth_fade_ratio": 0.60, "terminal_growth": 0.025},
    "Consumer Defensive": {"growth_near": 0.06, "margin": 0.14, "capex_pct": 0.04, "da_pct": 0.03, "dso": 40.0, "dio": 58.0, "dpo": 50.0, "exit_multiple": 12.0, "ic_turnover": 2.00, "ronic_terminal": 0.11, "growth_fade_ratio": 0.55, "terminal_growth": 0.025},
    "Industrials": {"growth_near": 0.06, "margin": 0.13, "capex_pct": 0.06, "da_pct": 0.04, "dso": 55.0, "dio": 60.0, "dpo": 50.0, "exit_multiple": 11.0, "ic_turnover": 1.70, "ronic_terminal": 0.11, "growth_fade_ratio": 0.55, "terminal_growth": 0.025},
    "Energy": {"growth_near": 0.05, "margin": 0.12, "capex_pct": 0.08, "da_pct": 0.06, "dso": 38.0, "dio": 45.0, "dpo": 46.0, "exit_multiple": 9.0, "ic_turnover": 1.40, "ronic_terminal": 0.10, "growth_fade_ratio": 0.50, "terminal_growth": 0.020},
    "Basic Materials": {"growth_near": 0.05, "margin": 0.12, "capex_pct": 0.07, "da_pct": 0.05, "dso": 48.0, "dio": 65.0, "dpo": 52.0, "exit_multiple": 9.0, "ic_turnover": 1.30, "ronic_terminal": 0.10, "growth_fade_ratio": 0.50, "terminal_growth": 0.020},
    "Utilities": {"growth_near": 0.04, "margin": 0.15, "capex_pct": 0.09, "da_pct": 0.07, "dso": 42.0, "dio": 20.0, "dpo": 45.0, "exit_multiple": 10.0, "ic_turnover": 1.10, "ronic_terminal": 0.09, "growth_fade_ratio": 0.55, "terminal_growth": 0.025},
    "_default": {"growth_near": 0.06, "margin": 0.14, "capex_pct": 0.05, "da_pct": 0.04, "dso": 50.0, "dio": 50.0, "dpo": 45.0, "exit_multiple": 12.0, "ic_turnover": 1.50, "ronic_terminal": 0.11, "growth_fade_ratio": 0.65, "terminal_growth": 0.030},
}


EXIT_METRIC_BY_SECTOR = {
    "Technology": "ev_ebitda",
    "Communication Services": "ev_ebitda",
    "Healthcare": "ev_ebitda",
    "Consumer Cyclical": "ev_ebitda",
    "Consumer Defensive": "ev_ebitda",
    "Industrials": "ev_ebit",
    "Energy": "ev_ebit",
    "Basic Materials": "ev_ebit",
    "Utilities": "ev_ebit",
}


EXCLUDED_SECTORS = {"Financial Services", "Real Estate"}


@dataclass(slots=True)
class ValuationInputsWithLineage:
    ticker: str
    company_name: str
    sector: str
    industry: str
    current_price: float
    as_of_date: str | None
    model_applicability_status: str
    drivers: ForecastDrivers
    source_lineage: dict[str, str]
    ciq_lineage: dict[str, Any]
    wacc_inputs: dict[str, Any]
    story_profile: dict[str, Any] | None = None
    story_adjustments: dict[str, Any] | None = None
    wacc_method_spread_high: bool = False
    default_resolution: dict[str, Any] = field(default_factory=dict)


def _mm(v: float | None) -> float | None:
    """Convert raw dollar value to millions."""
    return v / 1e6 if v is not None else None


def _net_debt_from_components(data: dict[str, Any] | None) -> float | None:
    if not data:
        return None
    debt = data.get("total_debt")
    cash = data.get("cash")
    if debt is None or cash is None:
        return None
    return float(debt) - float(cash)


def _bounded(value: float | None, low: float, high: float, default: float) -> float:
    if value is None:
        return default
    return max(low, min(high, float(value)))


def _pick(values: list[tuple[Any, str]], default_value: Any, default_source: str) -> tuple[Any, str]:
    for value, source in values:
        if value is not None:
            return value, source
    return default_value, default_source


def _detail_median(comps_detail: dict[str, Any] | None, metric: str) -> Any:
    medians = (comps_detail or {}).get("medians") or {}
    return medians.get(metric)


def _detail_source(comps_detail: dict[str, Any] | None, metric: str) -> str:
    source_lineage = (comps_detail or {}).get("source_lineage") or {}
    source = source_lineage.get("source") or source_lineage.get("source_file") or "comps_detail"
    return f"{source}_{metric}"


def _public_comps_fallback_enabled(ticker: str, sector: str) -> bool:
    overrides = load_valuation_overrides()
    ticker_blob = overrides.get("tickers", {}).get(ticker.upper(), {}) or {}
    sector_blob = overrides.get("sectors", {}).get(sector, {}) or {}
    global_blob = overrides.get("global", {}) or {}
    return bool(
        ticker_blob.get("public_comps_fallback")
        or ticker_blob.get("peers")
        or sector_blob.get("public_comps_fallback")
        or global_blob.get("public_comps_fallback")
    )


def _public_comps_fallback_peers(ticker: str) -> list[str] | None:
    overrides = load_valuation_overrides()
    ticker_blob = overrides.get("tickers", {}).get(ticker.upper(), {}) or {}
    peers = ticker_blob.get("peers")
    return [str(peer).upper() for peer in peers] if peers is not None else None


def _build_public_market_fallback_comps_detail(ticker: str, sector: str, market: dict[str, Any]) -> dict[str, Any] | None:
    if not _public_comps_fallback_enabled(ticker, sector):
        return None
    comps_detail = build_public_market_fallback_comps_detail(
        ticker,
        market=market,
        sector=sector,
        explicit_peers=_public_comps_fallback_peers(ticker),
        market_data_client=md_client,
    )
    return comps_detail


def _classify_source(source: Any) -> str:
    text = str(source or "").lower()
    if not text:
        return "missing"
    if "override" in text or "approved" in text:
        return "pm_override"
    if "ciq" in text:
        return "ciq"
    if "edgar" in text or "xbrl" in text:
        return "filing"
    if "yfinance" in text:
        return "public_market"
    if "comps" in text or "peer" in text:
        return "peer_prior"
    if "story" in text:
        return "story_prior"
    if "default" in text:
        return "missing_default"
    return "other"


def _default_resolution_report(
    *,
    drivers: ForecastDrivers,
    source_lineage: dict[str, str],
    defaults: dict[str, float],
    ciq_comps_detail: dict[str, Any] | None,
) -> dict[str, Any]:
    field_specs: dict[str, dict[str, Any]] = {
        "exit_multiple": {
            "value": drivers.exit_multiple,
            "fallback_value": defaults["exit_multiple"],
            "severity": "high",
            "preferred_sources": ["ciq_comps_forward", "ciq_comps_ltm", "comps_detail_median", "pm_override"],
            "why_it_matters": "Directly affects terminal value and equity value.",
        },
        "ebit_margin_target": {
            "value": drivers.ebit_margin_target,
            "fallback_value": defaults["margin"],
            "severity": "high",
            "preferred_sources": ["approved_company_driver", "sector_policy", "pm_override"],
            "why_it_matters": "The terminal margin path can dominate enterprise value.",
        },
        "net_debt": {
            "value": drivers.net_debt,
            "fallback_value": 0.0,
            "severity": "high",
            "preferred_sources": ["ciq_direct_net_debt", "complete_debt_cash_components", "pm_override"],
            "why_it_matters": "Net debt is a load-bearing enterprise-to-equity bridge input.",
        },
        "dso_start": {
            "value": drivers.dso_start,
            "fallback_value": defaults["dso"],
            "severity": "medium",
            "preferred_sources": ["ciq", "statement_derived", "yfinance", "peer_prior"],
            "why_it_matters": "Affects working-capital cash drag.",
        },
        "dio_start": {
            "value": drivers.dio_start,
            "fallback_value": defaults["dio"],
            "severity": "medium",
            "preferred_sources": ["ciq", "statement_derived", "yfinance", "peer_prior", "not_applicable"],
            "why_it_matters": "Affects inventory investment and working-capital cash drag.",
        },
        "dpo_start": {
            "value": drivers.dpo_start,
            "fallback_value": defaults["dpo"],
            "severity": "medium",
            "preferred_sources": ["ciq", "statement_derived", "yfinance", "peer_prior"],
            "why_it_matters": "Affects supplier financing and working-capital cash drag.",
        },
        "pension_deficit": {
            "value": drivers.pension_deficit,
            "fallback_value": 0.0,
            "severity": "medium",
            "preferred_sources": ["ciq", "edgar_xbrl", "explicit_structural_zero"],
            "why_it_matters": "Can be a non-equity claim in the equity bridge.",
        },
        "minority_interest": {
            "value": drivers.minority_interest,
            "fallback_value": 0.0,
            "severity": "low",
            "preferred_sources": ["ciq", "yfinance", "edgar_xbrl", "explicit_structural_zero"],
            "why_it_matters": "Can be a non-equity claim in the equity bridge.",
        },
        "preferred_equity": {
            "value": drivers.preferred_equity,
            "fallback_value": 0.0,
            "severity": "low",
            "preferred_sources": ["ciq", "yfinance", "edgar_xbrl", "explicit_structural_zero"],
            "why_it_matters": "Can be a non-equity claim in the equity bridge.",
        },
    }

    fields: list[dict[str, Any]] = []
    counts = {"resolved": 0, "review_required": 0}
    high_review = 0
    fallback_medians = (ciq_comps_detail or {}).get("medians") or {}
    for name, spec in field_specs.items():
        source = source_lineage.get(name)
        source_class = _classify_source(source)
        source_text = str(source or "")
        is_default = source_class == "missing_default" or "default" in source_text.lower()
        is_story_only = source_class == "story_prior" and name in {"exit_multiple"}
        needs_review = bool(is_default or is_story_only)
        if source_text == "default" and spec["fallback_value"] == 0.0 and float(spec["value"] or 0.0) == 0.0:
            source_class = "unproven_zero"
        if needs_review and spec["severity"] == "high":
            high_review += 1
        counts["review_required" if needs_review else "resolved"] += 1
        fields.append(
            {
                "field": name,
                "value": spec["value"],
                "source": source,
                "source_class": source_class,
                "fallback_value": spec["fallback_value"],
                "severity": spec["severity"],
                "needs_pm_review": needs_review,
                "preferred_sources": spec["preferred_sources"],
                "why_it_matters": spec["why_it_matters"],
                "available_comps_medians": fallback_medians if name == "exit_multiple" and fallback_medians else None,
            }
        )

    status = "ok"
    if high_review:
        status = "review_required_high"
    elif counts["review_required"]:
        status = "review_required"
    return {
        "status": status,
        "counts": counts,
        "fields": fields,
    }


def _canonical_source(source_detail: str) -> str:
    if source_detail.startswith("ciq"):
        return "ciq"
    if source_detail.startswith("yfinance"):
        return "yfinance"
    return source_detail


def _get_market_data_cached(ticker: str) -> dict[str, Any]:
    try:
        try:
            return md_client.get_market_data(ticker, use_cache=True) or {}
        except TypeError:
            return md_client.get_market_data(ticker) or {}
    except Exception:
        return {}


def _get_historical_financials_cached(ticker: str) -> dict[str, Any]:
    try:
        try:
            return md_client.get_historical_financials(ticker, use_cache=True) or {}
        except TypeError:
            return md_client.get_historical_financials(ticker) or {}
    except Exception:
        return {}


def _market_data_from_ciq_comps(ticker: str, comps_detail: dict[str, Any] | None) -> dict[str, Any]:
    target = (comps_detail or {}).get("target") or {}

    def _mm(field: str) -> float | None:
        value = target.get(field)
        return float(value) * 1_000_000.0 if value is not None else None

    return {
        "ticker": ticker,
        "name": target.get("company_name") or ticker,
        "current_price": target.get("stock_price"),
        "market_cap": _mm("market_cap_mm"),
        "enterprise_value": _mm("tev_mm"),
        "shares_outstanding": _mm("shares_out_mm"),
        "cash": _mm("cash_mm"),
        "total_debt": _mm("debt_mm"),
        "revenue_ttm": _mm("revenue_ltm_mm"),
    }


def _growth_period_type(source_detail: str) -> str:
    if source_detail == "ciq_consensus":
        return "consensus_fy1"
    if source_detail in {"ciq_cagr_3yr", "yfinance_cagr_3yr"}:
        return "cagr_3yr"
    if source_detail == "yfinance_ttm_yoy":
        return "ttm_yoy"
    if source_detail == "default":
        return "default"
    return "unknown"


def select_exit_metric_for_sector(sector: str) -> str:
    return EXIT_METRIC_BY_SECTOR.get(sector, "ev_ebitda")


def determine_model_applicability(sector: str, industry: str) -> str:
    if sector in EXCLUDED_SECTORS:
        return "alt_model_required"
    if "REIT" in (industry or "").upper():
        return "alt_model_required"
    return "dcf_applicable"


def clear_valuation_overrides_cache() -> None:
    """Invalidate the lru_cache on load_valuation_overrides so a re-run picks up new writes."""
    load_valuation_overrides.cache_clear()


@functools.lru_cache(maxsize=1)
def load_valuation_overrides() -> dict[str, Any]:
    if not OVERRIDES_PATH.exists():
        return {"global": {}, "sectors": {}, "tickers": {}}
    with OVERRIDES_PATH.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    data.setdefault("global", {})
    data.setdefault("sectors", {})
    data.setdefault("tickers", {})
    return data


def _apply_overrides(
    drivers: ForecastDrivers,
    source_lineage: dict[str, str],
    ticker: str,
    sector: str,
) -> None:
    overrides = load_valuation_overrides()

    def _apply(blob: dict[str, Any], source: str) -> None:
        for key, value in blob.items():
            if hasattr(drivers, key):
                setattr(drivers, key, value)
                source_lineage[key] = source

    _apply(overrides.get("global", {}), "override_global")
    _apply(overrides.get("sectors", {}).get(sector, {}), "override_sector")
    _apply(overrides.get("tickers", {}).get(ticker.upper(), {}), "override_ticker")

    # ── QoE LLM approved overrides ───────────────────────────────────────────
    # PM sets status → 'approved' in config/qoe_pending.yaml to activate.
    # override_ticker entries still take final precedence if also set.
    if QOE_PENDING_PATH.exists():
        with QOE_PENDING_PATH.open("r", encoding="utf-8") as f:
            qoe_pending = yaml.safe_load(f) or {}
        entry = qoe_pending.get(ticker.upper(), {})
        if entry.get("status") == "approved":
            _apply(entry.get("suggested_override") or {}, "qoe_llm_approved")

    try:
        from db.loader import get_approved_assumption_overrides

        approved_register_entries = get_approved_assumption_overrides(ticker)
    except Exception:
        approved_register_entries = {}
    _apply(approved_register_entries, "approved_assumption_register")


def _load_wacc_methodology_override(ticker: str) -> dict[str, Any] | None:
    overrides = load_valuation_overrides()
    ticker_blob = overrides.get("tickers", {}).get(ticker.upper(), {})
    method_blob = ticker_blob.get("wacc_methodology")
    if not isinstance(method_blob, dict):
        return None
    mode = str(method_blob.get("mode") or "").strip()
    if mode not in {"single_method", "blended"}:
        return None
    selected_method = method_blob.get("selected_method")
    weights = method_blob.get("weights") if isinstance(method_blob.get("weights"), dict) else None
    return {
        "mode": mode,
        "selected_method": selected_method,
        "weights": weights or {},
    }


def _derive_invested_capital_start(
    revenue_base: float,
    tax_start: float,
    ciq: dict[str, Any] | None,
    defaults: dict[str, float],
    hist: dict[str, Any] | None = None,
) -> tuple[float, str]:
    ciq_roic = (ciq or {}).get("roic")
    ciq_ebit = (ciq or {}).get("operating_income_ttm")
    ciq_ic_from_roic = None
    if ciq_roic and ciq_roic > 0.03 and ciq_ebit is not None:
        ciq_ic_from_roic = float(ciq_ebit) * (1.0 - tax_start) / float(ciq_roic)

    raw, source = _pick(
        [
            ((ciq or {}).get("invested_capital"), "ciq"),
            (ciq_ic_from_roic, "ciq_derived_nopat_over_roic"),
            # Gap 4: IC from yfinance balance sheet (Total Assets - Current Liabilities - Cash)
            ((hist or {}).get("invested_capital_derived"), "yfinance_derived"),
        ],
        revenue_base / defaults["ic_turnover"],
        "default",
    )
    value = _bounded(raw, revenue_base * 0.15, revenue_base * 4.0, revenue_base / defaults["ic_turnover"])
    return float(value), source


def _derive_non_operating_assets(revenue_base: float, ciq: dict[str, Any] | None, mkt: dict[str, Any]) -> tuple[float, str]:
    cash = (ciq or {}).get("cash")
    source = "ciq_cash_excess"
    if cash is None:
        cash = mkt.get("cash")
        source = "yfinance_cash_excess"

    if cash is None:
        return 0.0, "default"

    operating_cash_buffer = 0.02 * revenue_base
    excess_cash = max(float(cash) - operating_cash_buffer, 0.0)
    return excess_cash, source


def build_valuation_inputs(
    ticker: str,
    as_of_date: str | None = None,
    apply_overrides: bool = True,
) -> ValuationInputsWithLineage | None:
    ticker = ticker.upper().strip()
    mkt = _get_market_data_cached(ticker)
    hist = _get_historical_financials_cached(ticker)
    ciq = get_ciq_snapshot(ticker, as_of_date=as_of_date)
    ciq_comps = get_ciq_comps_valuation(ticker, as_of_date=as_of_date)
    ciq_comps_detail = get_ciq_comps_detail(ticker, as_of_date=as_of_date)
    edgar_bridge = get_bridge_items_from_xbrl(ticker)

    cached_price_available = bool(mkt.get("current_price"))
    cached_market_cap_available = bool(mkt.get("market_cap"))
    ciq_market = _market_data_from_ciq_comps(ticker, ciq_comps_detail)
    for field, value in ciq_market.items():
        placeholder_name = field == "name" and str(mkt.get(field) or "").upper() == ticker
        if (not mkt.get(field) or placeholder_name) and value is not None:
            mkt[field] = value
    current_price_source = "market_cache" if cached_price_available else "ciq_comps"
    market_cap_source = "market_cache" if cached_market_cap_available else "ciq_comps"

    price = float(mkt.get("current_price") or 0)
    sector = mkt.get("sector", "") or ""
    industry = mkt.get("industry", "") or ""
    defaults = SECTOR_DEFAULTS.get(sector, SECTOR_DEFAULTS["_default"])
    public_comps_fallback_used = False
    if not ciq_comps and not ciq_comps_detail:
        ciq_comps_detail = _build_public_market_fallback_comps_detail(ticker, sector, mkt)
        public_comps_fallback_used = bool(ciq_comps_detail)

    # FRED live Rf override (best-effort — falls back to config if unavailable)
    _fred_rf: float | None = None
    try:
        from src.stage_00_data.fred_client import get_macro_snapshot
        _snap = get_macro_snapshot(lookback_days=5)
        if _snap.get("available"):
            _dgs10_series = _snap.get("series", {}).get("DGS10", {})
            _fred_rf = _dgs10_series.get("latest_value")
            if _fred_rf is not None:
                _fred_rf = _fred_rf / 100.0  # FRED returns as percent
    except Exception:
        pass

    try:
        from db.loader import get_valuation_policy_rf_erp, get_valuation_policy_sector_defaults

        policy_rf, policy_erp = get_valuation_policy_rf_erp()
        saved_sector = get_valuation_policy_sector_defaults(sector)
        if saved_sector:
            defaults = {**defaults, **saved_sector}
    except Exception:
        policy_rf = 0.045
        policy_erp = 0.05

    # Use FRED live 10Y rate if available, else the editable valuation policy.
    rf_override = _fred_rf if _fred_rf is not None else policy_rf

    if price <= 0:
        return None

    revenue_base, revenue_source = _pick(
        [
            ((ciq or {}).get("revenue_ttm"), "ciq"),
            (mkt.get("revenue_ttm"), "yfinance"),
        ],
        None,
        "missing",
    )
    if not revenue_base or revenue_base <= 0:
        return None

    ciq_rev_fy1 = (ciq or {}).get("revenue_fy1")
    ciq_rev_ltm = (ciq or {}).get("revenue_ttm")
    consensus_growth = None
    if ciq_rev_fy1 and ciq_rev_ltm and float(ciq_rev_ltm) > 0:
        consensus_growth = (float(ciq_rev_fy1) / float(ciq_rev_ltm)) - 1

    growth_near_raw, growth_source_detail = _pick(
        [
            (consensus_growth, "ciq_consensus"),
            ((ciq or {}).get("revenue_cagr_3yr"), "ciq_cagr_3yr"),
            (hist.get("revenue_cagr_3yr"), "yfinance_cagr_3yr"),
            (mkt.get("revenue_growth"), "yfinance_ttm_yoy"),
        ],
        defaults["growth_near"],
        "default",
    )
    growth_source = _canonical_source(growth_source_detail)
    growth_period_type = _growth_period_type(growth_source_detail)
    revenue_period_type = "ttm" if revenue_source in {"ciq", "yfinance"} else "unknown"

    if revenue_period_type == "ttm" and growth_period_type == "consensus_fy1":
        revenue_alignment_flag = "aligned_consensus"
    elif revenue_period_type == "ttm" and growth_period_type == "ttm_yoy":
        revenue_alignment_flag = "aligned_ttm"
    elif revenue_period_type == "ttm" and growth_period_type == "cagr_3yr":
        revenue_alignment_flag = "mixed_ttm_vs_cagr"
    elif growth_period_type == "default":
        revenue_alignment_flag = "default_growth"
    else:
        revenue_alignment_flag = "unknown"

    if revenue_source == "default" or growth_source == "default":
        revenue_data_quality_flag = "low_quality"
    elif revenue_alignment_flag in {"aligned_consensus", "aligned_ttm"}:
        revenue_data_quality_flag = "ok"
    elif revenue_alignment_flag == "mixed_ttm_vs_cagr":
        revenue_data_quality_flag = "needs_review"
    else:
        revenue_data_quality_flag = "needs_review"

    growth_near = _bounded(growth_near_raw, -0.10, 0.35, defaults["growth_near"])

    # Revision momentum bias (bounded ±2%)
    try:
        from src.stage_02_valuation.revision_signals import get_revision_growth_bias
        _rev_bias, _rev_source = get_revision_growth_bias(ticker)
        if abs(_rev_bias) > 0.001:
            growth_near = max(0.0, min(0.40, growth_near + _rev_bias))
            growth_source_detail = growth_source_detail + f"|{_rev_source}"
    except Exception:
        pass

    fade = defaults.get("growth_fade_ratio", 0.65)
    growth_mid = _bounded(growth_near * fade, -0.08, 0.25, defaults["growth_near"] * fade)

    margin_start_raw, margin_source = _pick(
        [
            ((ciq or {}).get("op_margin_avg_3yr") or (ciq or {}).get("ebit_margin"), "ciq"),
            (hist.get("op_margin_avg_3yr"), "yfinance"),
            (mkt.get("operating_margin"), "yfinance"),
        ],
        defaults["margin"],
        "default",
    )
    margin_start = _bounded(margin_start_raw, 0.02, 0.60, defaults["margin"])
    # #3: Blend company margin with sector default — halves reversion speed for outliers
    margin_target = _bounded(0.5 * margin_start + 0.5 * defaults["margin"], 0.03, 0.65, defaults["margin"])

    tax_start_raw, tax_source = _pick(
        [
            ((ciq or {}).get("effective_tax_rate_avg"), "ciq"),
            (hist.get("effective_tax_rate_avg"), "yfinance"),
        ],
        0.21,
        "default",
    )
    tax_start = _bounded(tax_start_raw, 0.05, 0.40, 0.21)
    tax_target = _bounded(tax_start, 0.15, 0.30, 0.23)

    capex_raw, capex_source = _pick(
        [
            ((ciq or {}).get("capex_pct_avg_3yr"), "ciq"),
            (hist.get("capex_pct_avg_3yr"), "yfinance"),
        ],
        defaults["capex_pct"],
        "default",
    )
    capex_start = _bounded(capex_raw, 0.01, 0.25, defaults["capex_pct"])
    capex_target = _bounded(max(0.005, capex_start * 0.95), 0.005, 0.25, capex_start)

    da_raw, da_source = _pick(
        [
            ((ciq or {}).get("da_pct_avg_3yr"), "ciq"),
            (hist.get("da_pct_avg_3yr"), "yfinance"),
        ],
        defaults["da_pct"],
        "default",
    )
    da_start = _bounded(da_raw, 0.005, 0.20, defaults["da_pct"])
    da_target = _bounded(max(0.003, da_start * 0.95), 0.003, 0.20, da_start)

    peer_tickers = [
        str(peer.get("ticker") or "").upper()
        for peer in (ciq_comps_detail or {}).get("peers", [])
        if peer.get("ticker")
    ]
    if getattr(compute_wacc_from_yfinance, "__module__", "") != "src.stage_02_valuation.wacc":
        # Compatibility seam for older tests/callers that monkeypatch the
        # single-method helper instead of the newer methodology set.
        wacc_result = compute_wacc_from_yfinance(ticker, hist=hist)
        wacc_method_results = {"peer_bottom_up": wacc_result}
    else:
        wacc_method_results = compute_wacc_methodology_set_for_ticker(
            ticker,
            peer_tickers=peer_tickers,
            hist=hist,
            market_data=mkt,
            risk_free_rate=rf_override,
            equity_risk_premium=policy_erp,
        )
        wacc_result = wacc_method_results["peer_bottom_up"]
    _wacc_meta = wacc_method_results.get("_meta") or {}
    _wacc_spread_high = bool(_wacc_meta.get("wacc_method_spread_high", False))
    wacc = _bounded(getattr(wacc_result, "wacc", 0.09), 0.04, 0.20, 0.09)
    cost_of_equity = _bounded(getattr(wacc_result, "cost_of_equity", None), 0.04, 0.30, max(0.06, wacc + 0.015))
    equity_weight = getattr(wacc_result, "equity_weight", None)
    debt_weight_raw = (1.0 - equity_weight) if equity_weight is not None else getattr(wacc_result, "debt_weight", None)
    debt_weight = _bounded(debt_weight_raw, 0.00, 0.80, 0.20)

    exit_metric = select_exit_metric_for_sector(sector)
    if exit_metric == "ev_ebit":
        exit_multiple_raw, exit_source = _pick(
            [
                ((ciq_comps or {}).get("peer_median_tev_ebit_fwd"), "ciq_comps_tev_ebit_fwd"),
                ((ciq_comps or {}).get("peer_median_tev_ebit_ltm"), "ciq_comps_tev_ebit_ltm"),
                (_detail_median(ciq_comps_detail, "tev_ebit_fwd"), _detail_source(ciq_comps_detail, "tev_ebit_fwd")),
                (_detail_median(ciq_comps_detail, "tev_ebit_ltm"), _detail_source(ciq_comps_detail, "tev_ebit_ltm")),
                ((ciq_comps or {}).get("peer_median_tev_ebitda_fwd"), "ciq_comps_tev_ebitda_fwd_fallback"),
                ((ciq_comps or {}).get("peer_median_tev_ebitda_ltm"), "ciq_comps_tev_ebitda_fallback"),
                (_detail_median(ciq_comps_detail, "tev_ebitda_fwd"), _detail_source(ciq_comps_detail, "tev_ebitda_fwd_fallback")),
                (_detail_median(ciq_comps_detail, "tev_ebitda_ltm"), _detail_source(ciq_comps_detail, "tev_ebitda_ltm_fallback")),
            ],
            defaults["exit_multiple"],
            "default",
        )
    else:
        exit_multiple_raw, exit_source = _pick(
            [
                ((ciq_comps or {}).get("peer_median_tev_ebitda_fwd"), "ciq_comps_tev_ebitda_fwd"),
                ((ciq_comps or {}).get("peer_median_tev_ebitda_ltm"), "ciq_comps_tev_ebitda_ltm"),
                (_detail_median(ciq_comps_detail, "tev_ebitda_fwd"), _detail_source(ciq_comps_detail, "tev_ebitda_fwd")),
                (_detail_median(ciq_comps_detail, "tev_ebitda_ltm"), _detail_source(ciq_comps_detail, "tev_ebitda_ltm")),
                ((ciq_comps or {}).get("peer_median_tev_ebit_fwd"), "ciq_comps_tev_ebit_fwd_fallback"),
                ((ciq_comps or {}).get("peer_median_tev_ebit_ltm"), "ciq_comps_tev_ebit_fallback"),
                (_detail_median(ciq_comps_detail, "tev_ebit_fwd"), _detail_source(ciq_comps_detail, "tev_ebit_fwd_fallback")),
                (_detail_median(ciq_comps_detail, "tev_ebit_ltm"), _detail_source(ciq_comps_detail, "tev_ebit_ltm_fallback")),
            ],
            defaults["exit_multiple"],
            "default",
        )
    exit_multiple = _bounded(exit_multiple_raw, 4.0, 30.0, defaults["exit_multiple"])

    comps_net_debt = (ciq_comps or {}).get("target_net_debt")
    net_debt_raw, net_debt_source = _pick(
        [
            (float(comps_net_debt) * 1_000_000.0 if comps_net_debt is not None else None, "ciq_comps_net_debt"),
            (_net_debt_from_components(ciq), "ciq"),
            (_net_debt_from_components(mkt), "yfinance"),
        ],
        0.0,
        "default",
    )
    comps_shares = (ciq_comps or {}).get("target_shares_out")
    shares_raw, shares_source = _pick(
        [
            (float(comps_shares) * 1_000_000.0 if comps_shares is not None else None, "ciq_current_shares"),
            ((ciq or {}).get("shares_outstanding"), "ciq_weighted_average_shares"),
            (hist.get("diluted_shares"), "yfinance_diluted"),
            (mkt.get("shares_outstanding"), "yfinance_basic"),
        ],
        1.0,
        "default",
    )

    dso_raw, dso_source = _pick(
        [
            ((ciq or {}).get("dso"), "ciq"),
            (hist.get("dso_derived"), "yfinance"),
        ],
        defaults["dso"],
        "default",
    )
    dso_start = _bounded(dso_raw, 5.0, 180.0, defaults["dso"])
    if dso_source != "default":
        dso_target = _bounded(defaults["dso"] * 0.7 + dso_start * 0.3, 5.0, 180.0, defaults["dso"])
        dso_target_source = f"{dso_source}_blend"
    else:
        dso_target = _bounded(defaults["dso"], 5.0, 180.0, defaults["dso"])
        dso_target_source = "default"

    dio_raw, dio_source = _pick(
        [
            ((ciq or {}).get("dio"), "ciq"),
            (hist.get("dio_derived"), "yfinance"),
        ],
        defaults["dio"],
        "default",
    )
    dio_lower_bound = 0.1 if dio_source == "ciq" else 5.0
    dio_start = _bounded(dio_raw, dio_lower_bound, 220.0, defaults["dio"])
    if dio_source != "default":
        dio_target = _bounded(
            defaults["dio"] * 0.7 + dio_start * 0.3,
            dio_lower_bound,
            220.0,
            defaults["dio"],
        )
        dio_target_source = f"{dio_source}_blend"
    else:
        dio_target = _bounded(defaults["dio"], dio_lower_bound, 220.0, defaults["dio"])
        dio_target_source = "default"

    dpo_raw, dpo_source = _pick(
        [
            ((ciq or {}).get("dpo"), "ciq"),
            (hist.get("dpo_derived"), "yfinance"),
        ],
        defaults["dpo"],
        "default",
    )
    dpo_start = _bounded(dpo_raw, 5.0, 180.0, defaults["dpo"])
    if dpo_source != "default":
        dpo_target = _bounded(defaults["dpo"] * 0.7 + dpo_start * 0.3, 5.0, 180.0, defaults["dpo"])
        dpo_target_source = f"{dpo_source}_blend"
    else:
        dpo_target = _bounded(defaults["dpo"], 5.0, 180.0, defaults["dpo"])
        dpo_target_source = "default"

    invested_capital_start, invested_capital_source = _derive_invested_capital_start(
        revenue_base=float(revenue_base),
        tax_start=float(tax_start),
        ciq=ciq,
        defaults=defaults,
        hist=hist,
    )

    ronic_terminal_raw, ronic_terminal_source = _pick(
        [
            ((ciq or {}).get("roic"), "ciq_roic"),
        ],
        defaults["ronic_terminal"],
        "default",
    )
    ronic_terminal = _bounded(ronic_terminal_raw, 0.06, 0.30, defaults["ronic_terminal"])

    if net_debt_source != "default":
        non_operating_assets, non_operating_assets_source = 0.0, "included_in_net_debt"
    else:
        non_operating_assets, non_operating_assets_source = _derive_non_operating_assets(
            float(revenue_base), ciq=ciq, mkt=mkt
        )

    minority_interest_raw, minority_interest_source = _pick(
        [
            ((ciq or {}).get("minority_interest"), "ciq"),
            (hist.get("minority_interest_bs"), "yfinance"),
            (edgar_bridge.get("minority_interest"), "edgar_xbrl"),
        ],
        0.0,
        "default",
    )
    preferred_equity_raw, preferred_equity_source = _pick(
        [
            ((ciq or {}).get("preferred_equity"), "ciq"),
            (hist.get("preferred_equity_bs"), "yfinance"),
            (edgar_bridge.get("preferred_equity"), "edgar_xbrl"),
        ],
        0.0,
        "default",
    )
    pension_deficit_raw, pension_deficit_source = _pick(
        [
            ((ciq or {}).get("pension_deficit"), "ciq"),
            (edgar_bridge.get("pension_deficit"), "edgar_xbrl"),
        ],
        0.0,
        "default",
    )
    lease_liabilities_raw, lease_liabilities_source = _pick(
        [
            ((ciq or {}).get("lease_liabilities"), "ciq"),
            (hist.get("lease_liabilities_bs"), "yfinance"),
            (edgar_bridge.get("lease_liabilities"), "edgar_xbrl"),
        ],
        0.0,
        "default",
    )
    # #1: Add lease liabilities into net debt when yfinance is the source.
    # yfinance total_debt often excludes operating leases; CIQ already includes them.
    if net_debt_source == "yfinance" and lease_liabilities_raw > 0:
        net_debt_raw = net_debt_raw + lease_liabilities_raw
        net_debt_source = "yfinance+leases"
        # P0: zero out standalone field — already folded into net_debt, prevent double-count in _claims_total()
        lease_liabilities_raw = 0.0
        lease_liabilities_source = "folded_into_net_debt"

    _sbc_raw = hist.get("sbc") or edgar_bridge.get("sbc")
    _options_proxy = _sbc_raw * 3.0 if _sbc_raw else None
    options_value_raw, options_value_source = _pick(
        [
            ((ciq or {}).get("options_value"), "ciq"),
            (_options_proxy, "sbc_proxy"),
        ],
        0.0,
        "default",
    )
    convertibles_value_raw, convertibles_value_source = _pick(
        [
            ((ciq or {}).get("convertibles_value"), "ciq"),
        ],
        0.0,
        "default",
    )

    terminal_growth = float(defaults.get("terminal_growth", 0.030))

    # Gap 1: COGS ratio for accurate DIO/DPO projection (denominator fix)
    cogs_pct_raw, cogs_pct_source = _pick(
        [
            ((ciq or {}).get("cogs_pct_of_revenue"), "ciq"),
            (hist.get("cogs_pct_of_revenue"), "yfinance"),
        ],
        0.60,
        "default",
    )
    cogs_pct_of_revenue = _bounded(cogs_pct_raw, 0.10, 0.95, 0.60)

    drivers = ForecastDrivers(
        revenue_base=float(revenue_base),
        revenue_growth_near=float(growth_near),
        revenue_growth_mid=float(growth_mid),
        revenue_growth_terminal=terminal_growth,
        ebit_margin_start=float(margin_start),
        ebit_margin_target=float(margin_target),
        tax_rate_start=float(tax_start),
        tax_rate_target=float(tax_target),
        capex_pct_start=float(capex_start),
        capex_pct_target=float(capex_target),
        da_pct_start=float(da_start),
        da_pct_target=float(da_target),
        dso_start=float(dso_start),
        dso_target=float(dso_target),
        dio_start=float(dio_start),
        dio_target=float(dio_target),
        dpo_start=float(dpo_start),
        dpo_target=float(dpo_target),
        wacc=float(wacc),
        exit_multiple=float(exit_multiple),
        exit_metric=exit_metric,
        net_debt=float(net_debt_raw),
        shares_outstanding=float(max(shares_raw, 1.0)),
        terminal_blend_gordon_weight=0.60,
        terminal_blend_exit_weight=0.40,
        invested_capital_start=float(invested_capital_start),
        ronic_terminal=float(ronic_terminal),
        non_operating_assets=float(non_operating_assets),
        minority_interest=float(_bounded(minority_interest_raw, 0.0, float(revenue_base) * 2.0, 0.0)),
        preferred_equity=float(_bounded(preferred_equity_raw, 0.0, float(revenue_base) * 2.0, 0.0)),
        pension_deficit=float(_bounded(pension_deficit_raw, 0.0, float(revenue_base) * 2.0, 0.0)),
        lease_liabilities=float(_bounded(lease_liabilities_raw, 0.0, float(revenue_base) * 2.0, 0.0)),
        options_value=float(_bounded(options_value_raw, 0.0, float(revenue_base) * 2.0, 0.0)),
        convertibles_value=float(_bounded(convertibles_value_raw, 0.0, float(revenue_base) * 2.0, 0.0)),
        cost_of_equity=float(cost_of_equity),
        debt_weight=float(debt_weight),
        cogs_pct_of_revenue=float(cogs_pct_of_revenue),
    )

    wacc_quality_status = getattr(wacc_result, "quality_status", "source_backed")
    if wacc_quality_status == "degraded_fallback":
        wacc_source = f"{market_cap_source}|market_beta_assumption"
    else:
        wacc_source = "yfinance_capm"

    source_lineage = {
        "current_price": current_price_source,
        "market_cap": market_cap_source,
        "revenue_base": revenue_source,
        "revenue_growth_near": growth_source,
        "revenue_growth_mid": growth_source,
        "revenue_growth_terminal": "default",
        "growth_source_detail": growth_source_detail,
        "revenue_period_type": revenue_period_type,
        "growth_period_type": growth_period_type,
        "revenue_alignment_flag": revenue_alignment_flag,
        "revenue_data_quality_flag": revenue_data_quality_flag,
        "ebit_margin_start": margin_source,
        "ebit_margin_target": "default",
        "tax_rate_start": tax_source,
        "tax_rate_target": tax_source,
        "capex_pct_start": capex_source,
        "capex_pct_target": capex_source,
        "da_pct_start": da_source,
        "da_pct_target": da_source,
        "dso_start": dso_source,
        "dso_target": dso_target_source,
        "dio_start": dio_source,
        "dio_target": dio_target_source,
        "dpo_start": dpo_source,
        "dpo_target": dpo_target_source,
        "wacc": wacc_source,
        "cost_of_equity": wacc_source,
        "debt_weight": wacc_source,
        "exit_multiple": exit_source,
        "exit_metric": "sector_policy",
        "net_debt": net_debt_source,
        "shares_outstanding": shares_source,
        "invested_capital_start": invested_capital_source,
        "ronic_terminal": ronic_terminal_source,
        "non_operating_assets": non_operating_assets_source,
        "minority_interest": minority_interest_source,
        "preferred_equity": preferred_equity_source,
        "pension_deficit": pension_deficit_source,
        "lease_liabilities": lease_liabilities_source,
        "options_value": options_value_source,
        "convertibles_value": convertibles_value_source,
        "cogs_pct_of_revenue": cogs_pct_source,
        "risk_free_rate": f"fred_live:{rf_override:.4f}" if _fred_rf is not None else f"valuation_policy:{rf_override:.4f}",
        "equity_risk_premium": f"valuation_policy:{policy_erp:.4f}",
    }

    story_profile, story_profile_source = resolve_story_driver_profile(ticker=ticker, sector=sector)
    story_adjustments = apply_story_driver_adjustments(drivers, story_profile) if apply_overrides else None
    effective_story_adjustments = story_adjustments or {}
    source_lineage["story_profile"] = (
        story_profile_source if apply_overrides else f"{story_profile_source}|advisory_not_applied"
    )

    # Only stamp story as driver source when there is an applied adjustment.
    growth_story_active = abs(float(effective_story_adjustments.get("growth_add", 0.0))) > 1e-12 or abs(float(effective_story_adjustments.get("cyclicality_growth_multiplier", 1.0)) - 1.0) > 1e-12
    if growth_story_active:
        source_lineage["revenue_growth_near"] = f"{source_lineage['revenue_growth_near']}|{story_profile_source}"
        source_lineage["revenue_growth_mid"] = f"{source_lineage['revenue_growth_mid']}|{story_profile_source}"

    margin_story_active = abs(float(effective_story_adjustments.get("margin_add", 0.0))) > 1e-12
    if margin_story_active:
        source_lineage["ebit_margin_target"] = story_profile_source

    wacc_story_active = abs(float(effective_story_adjustments.get("cyclicality_wacc_add", 0.0)) + float(effective_story_adjustments.get("governance_wacc_add", 0.0))) > 1e-12
    if wacc_story_active:
        source_lineage["wacc"] = f"{source_lineage['wacc']}|{story_profile_source}"
        source_lineage["cost_of_equity"] = f"{source_lineage['cost_of_equity']}|{story_profile_source}"

    capex_story_active = abs(float(effective_story_adjustments.get("capex_target_add", 0.0))) > 1e-12
    da_story_active = abs(float(effective_story_adjustments.get("da_target_add", 0.0))) > 1e-12
    if capex_story_active:
        source_lineage["capex_pct_target"] = story_profile_source
    if da_story_active:
        source_lineage["da_pct_target"] = story_profile_source

    exit_cyc_mult = float(effective_story_adjustments.get("exit_multiple_cyclicality_multiplier", 1.0))
    exit_gov_mult = float(effective_story_adjustments.get("exit_multiple_governance_multiplier", 1.0))
    exit_mult_story_active = abs(exit_cyc_mult * exit_gov_mult - 1.0) > 1e-12
    if exit_mult_story_active:
        source_lineage["exit_multiple"] = f"{source_lineage['exit_multiple']}|{story_profile_source}"

    if apply_overrides:
        _apply_overrides(drivers, source_lineage, ticker=ticker, sector=sector)
        method_override = _load_wacc_methodology_override(ticker)
        if method_override:
            mode = method_override["mode"]
            selected_method = method_override.get("selected_method")
            weights = method_override.get("weights") or {}
            try:
                if mode == "single_method" and selected_method in wacc_method_results:
                    selected_wacc_result = wacc_method_results[selected_method]
                    selected_label = selected_method
                elif mode == "blended":
                    selected_wacc_result = blend_wacc_results(wacc_method_results, weights)
                    selected_label = "blended"
                else:
                    selected_wacc_result = None
                    selected_label = None
                if selected_wacc_result is not None:
                    drivers.wacc = float(
                        _bounded(getattr(selected_wacc_result, "wacc", 0.09), 0.04, 0.20, float(drivers.wacc))
                    )
                    drivers.cost_of_equity = float(
                        _bounded(
                            getattr(selected_wacc_result, "cost_of_equity", None),
                            0.04,
                            0.30,
                            float(getattr(drivers, "cost_of_equity", drivers.wacc + 0.015)),
                        )
                    )
                    selected_equity_weight = getattr(selected_wacc_result, "equity_weight", None)
                    selected_debt_weight = getattr(selected_wacc_result, "debt_weight", None)
                    if selected_debt_weight is None and selected_equity_weight is not None:
                        selected_debt_weight = 1.0 - selected_equity_weight
                    drivers.debt_weight = float(
                        _bounded(selected_debt_weight, 0.00, 0.80, float(getattr(drivers, "debt_weight", 0.20)))
                    )
                    source_lineage["wacc"] = f"wacc_methodology:{selected_label}"
                    source_lineage["cost_of_equity"] = f"wacc_methodology:{selected_label}"
                    source_lineage["debt_weight"] = f"wacc_methodology:{selected_label}"
                    wacc_result = selected_wacc_result
            except Exception:
                pass

    default_resolution = _default_resolution_report(
        drivers=drivers,
        source_lineage=source_lineage,
        defaults=defaults,
        ciq_comps_detail=ciq_comps_detail,
    )
    source_lineage["default_resolution_status"] = default_resolution["status"]

    return ValuationInputsWithLineage(
        ticker=ticker,
        company_name=mkt.get("name", ""),
        sector=sector,
        industry=industry,
        current_price=price,
        as_of_date=(ciq or {}).get("as_of_date") if ciq else as_of_date,
        model_applicability_status=determine_model_applicability(sector, industry),
        drivers=drivers,
        source_lineage=source_lineage,
        ciq_lineage={
            "snapshot_used": bool(ciq),
            "snapshot_run_id": (ciq or {}).get("run_id") if ciq else None,
            "snapshot_source_file": (ciq or {}).get("source_file") if ciq else None,
            "snapshot_as_of_date": (ciq or {}).get("as_of_date") if ciq else None,
            "comps_used": bool(ciq_comps),
            "comps_run_id": (ciq_comps or {}).get("run_id") if ciq_comps else None,
            "comps_source_file": (ciq_comps or {}).get("source_file") if ciq_comps else None,
            "comps_as_of_date": (ciq_comps or {}).get("as_of_date") if ciq_comps else None,
            "peer_count": (ciq_comps or {}).get("peer_count") if ciq_comps else None,
            "peer_median_tev_ebitda_ltm": (ciq_comps or {}).get("peer_median_tev_ebitda_ltm") if ciq_comps else None,
            "peer_median_tev_ebit_ltm": (ciq_comps or {}).get("peer_median_tev_ebit_ltm") if ciq_comps else None,
            "peer_median_pe_ltm": (ciq_comps or {}).get("peer_median_pe_ltm") if ciq_comps else None,
            "comps_iv_ev_ebitda": (ciq_comps or {}).get("implied_price_ev_ebitda") if ciq_comps else None,
            "comps_iv_ev_ebit": (ciq_comps or {}).get("implied_price_ev_ebit") if ciq_comps else None,
            "comps_iv_pe": (ciq_comps or {}).get("implied_price_pe") if ciq_comps else None,
            "comps_iv_base": (ciq_comps or {}).get("implied_price_base") if ciq_comps else None,
            "public_comps_fallback_used": public_comps_fallback_used,
            "public_comps_fallback_source_file": ((ciq_comps_detail or {}).get("source_lineage") or {}).get("source_file") if public_comps_fallback_used else None,
            "public_comps_fallback_peer_count": len((ciq_comps_detail or {}).get("peers") or []) if public_comps_fallback_used else None,
        },
        wacc_inputs={
            # Top-level WACC values are the effective drivers used by DCF after
            # story adjustments, PM overrides, or methodology selection.
            "wacc": drivers.wacc,
            "cost_of_equity": drivers.cost_of_equity,
            "cost_of_debt_after_tax": getattr(wacc_result, "cost_of_debt_after_tax", None),
            "beta_relevered": getattr(wacc_result, "beta_relevered", None),
            "beta_unlevered_median": getattr(wacc_result, "beta_unlevered_median", None),
            "size_premium": getattr(wacc_result, "size_premium", None),
            "equity_weight": getattr(wacc_result, "equity_weight", None),
            "debt_weight": drivers.debt_weight,
            "peers_used": getattr(wacc_result, "peers_used", None),
            "risk_free_rate": rf_override,
            "equity_risk_premium": policy_erp,
            "selected_method_wacc": getattr(wacc_result, "wacc", None),
            "selected_method_cost_of_equity": getattr(wacc_result, "cost_of_equity", None),
            "quality_status": getattr(wacc_result, "quality_status", "source_backed"),
            "missing_inputs": getattr(wacc_result, "missing_inputs", []),
            "beta_source": getattr(wacc_result, "beta_source", None),
            "market_cap_source": market_cap_source,
            "method_results": {
                method: {
                    "wacc": getattr(result, "wacc", None),
                    "cost_of_equity": getattr(result, "cost_of_equity", None),
                    "beta_relevered": getattr(result, "beta_relevered", None),
                    "equity_weight": getattr(result, "equity_weight", None),
                    "debt_weight": getattr(result, "debt_weight", None),
                    "peers_used": getattr(result, "peers_used", None),
                }
                for method, result in wacc_method_results.items()
            },
            "selected_methodology": _load_wacc_methodology_override(ticker) if apply_overrides else None,
        },
        story_profile=asdict(story_profile),
        story_adjustments=story_adjustments,
        wacc_method_spread_high=_wacc_spread_high,
        default_resolution=default_resolution,
    )
