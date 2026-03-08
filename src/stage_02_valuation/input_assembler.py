"""Deterministic valuation input assembly with source lineage and manual overrides."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from config import ROOT_DIR
from src.stage_00_data import market_data as md_client
from src.stage_00_data.ciq_adapter import get_ciq_comps_valuation, get_ciq_snapshot
from src.stage_02_valuation.professional_dcf import ForecastDrivers
from src.stage_02_valuation.wacc import compute_wacc_from_yfinance


OVERRIDES_PATH = ROOT_DIR / "config" / "valuation_overrides.yaml"


SECTOR_DEFAULTS = {
    "Technology": {"growth_near": 0.12, "margin": 0.20, "capex_pct": 0.06, "da_pct": 0.04, "dso": 45.0, "dio": 35.0, "dpo": 38.0, "exit_multiple": 16.0},
    "Communication Services": {"growth_near": 0.10, "margin": 0.18, "capex_pct": 0.05, "da_pct": 0.04, "dso": 50.0, "dio": 30.0, "dpo": 42.0, "exit_multiple": 14.0},
    "Healthcare": {"growth_near": 0.09, "margin": 0.18, "capex_pct": 0.05, "da_pct": 0.04, "dso": 52.0, "dio": 45.0, "dpo": 40.0, "exit_multiple": 14.0},
    "Consumer Cyclical": {"growth_near": 0.08, "margin": 0.14, "capex_pct": 0.05, "da_pct": 0.04, "dso": 42.0, "dio": 55.0, "dpo": 48.0, "exit_multiple": 12.0},
    "Consumer Defensive": {"growth_near": 0.06, "margin": 0.14, "capex_pct": 0.04, "da_pct": 0.03, "dso": 40.0, "dio": 58.0, "dpo": 50.0, "exit_multiple": 12.0},
    "Industrials": {"growth_near": 0.06, "margin": 0.13, "capex_pct": 0.06, "da_pct": 0.04, "dso": 55.0, "dio": 60.0, "dpo": 50.0, "exit_multiple": 11.0},
    "Energy": {"growth_near": 0.05, "margin": 0.12, "capex_pct": 0.08, "da_pct": 0.06, "dso": 38.0, "dio": 45.0, "dpo": 46.0, "exit_multiple": 9.0},
    "Basic Materials": {"growth_near": 0.05, "margin": 0.12, "capex_pct": 0.07, "da_pct": 0.05, "dso": 48.0, "dio": 65.0, "dpo": 52.0, "exit_multiple": 9.0},
    "Utilities": {"growth_near": 0.04, "margin": 0.15, "capex_pct": 0.09, "da_pct": 0.07, "dso": 42.0, "dio": 20.0, "dpo": 45.0, "exit_multiple": 10.0},
    "_default": {"growth_near": 0.06, "margin": 0.14, "capex_pct": 0.05, "da_pct": 0.04, "dso": 50.0, "dio": 50.0, "dpo": 45.0, "exit_multiple": 12.0},
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


def _bounded(value: float | None, low: float, high: float, default: float) -> float:
    if value is None:
        return default
    return max(low, min(high, float(value)))


def _pick(values: list[tuple[Any, str]], default_value: Any, default_source: str) -> tuple[Any, str]:
    for value, source in values:
        if value is not None:
            return value, source
    return default_value, default_source


def select_exit_metric_for_sector(sector: str) -> str:
    return EXIT_METRIC_BY_SECTOR.get(sector, "ev_ebitda")


def determine_model_applicability(sector: str, industry: str) -> str:
    if sector in EXCLUDED_SECTORS:
        return "alt_model_required"
    if "REIT" in (industry or "").upper():
        return "alt_model_required"
    return "dcf_applicable"


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


def build_valuation_inputs(ticker: str, as_of_date: str | None = None) -> ValuationInputsWithLineage | None:
    ticker = ticker.upper().strip()
    mkt = md_client.get_market_data(ticker)
    hist = md_client.get_historical_financials(ticker)
    ciq = get_ciq_snapshot(ticker, as_of_date=as_of_date)
    ciq_comps = get_ciq_comps_valuation(ticker, as_of_date=as_of_date)

    price = float(mkt.get("current_price") or 0)
    sector = mkt.get("sector", "") or ""
    industry = mkt.get("industry", "") or ""
    defaults = SECTOR_DEFAULTS.get(sector, SECTOR_DEFAULTS["_default"])

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

    growth_near_raw, growth_source = _pick(
        [
            ((ciq or {}).get("revenue_cagr_3yr"), "ciq"),
            (hist.get("revenue_cagr_3yr"), "yfinance"),
            (mkt.get("revenue_growth"), "yfinance"),
        ],
        defaults["growth_near"],
        "default",
    )
    growth_near = _bounded(growth_near_raw, -0.10, 0.35, defaults["growth_near"])
    growth_mid = _bounded(growth_near * 0.65, -0.08, 0.25, defaults["growth_near"] * 0.65)

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
    margin_target = _bounded(max(margin_start, defaults["margin"]), 0.03, 0.65, defaults["margin"])

    tax_start_raw, tax_source = _pick(
        [
            ((ciq or {}).get("effective_tax_rate_avg"), "ciq"),
            (hist.get("effective_tax_rate_avg"), "yfinance"),
        ],
        0.21,
        "default",
    )
    tax_start = _bounded(tax_start_raw, 0.05, 0.40, 0.21)
    tax_target = 0.23

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

    wacc_result = compute_wacc_from_yfinance(ticker, hist=hist)
    wacc = _bounded(getattr(wacc_result, "wacc", 0.09), 0.04, 0.20, 0.09)

    exit_metric = select_exit_metric_for_sector(sector)
    if exit_metric == "ev_ebit":
        exit_multiple_raw, exit_source = _pick(
            [
                ((ciq_comps or {}).get("peer_median_tev_ebit_ltm"), "ciq_comps_tev_ebit_ltm"),
                ((ciq_comps or {}).get("peer_median_tev_ebitda_ltm"), "ciq_comps_tev_ebitda_fallback"),
            ],
            defaults["exit_multiple"],
            "default",
        )
    else:
        exit_multiple_raw, exit_source = _pick(
            [
                ((ciq_comps or {}).get("peer_median_tev_ebitda_ltm"), "ciq_comps_tev_ebitda_ltm"),
                ((ciq_comps or {}).get("peer_median_tev_ebit_ltm"), "ciq_comps_tev_ebit_fallback"),
            ],
            defaults["exit_multiple"],
            "default",
        )
    exit_multiple = _bounded(exit_multiple_raw, 4.0, 30.0, defaults["exit_multiple"])

    net_debt_raw, net_debt_source = _pick(
        [
            (((ciq or {}).get("total_debt") or 0) - ((ciq or {}).get("cash") or 0) if ciq else None, "ciq"),
            (((mkt.get("total_debt") or 0) - (mkt.get("cash") or 0)), "yfinance"),
        ],
        0.0,
        "default",
    )
    shares_raw, shares_source = _pick(
        [
            ((ciq or {}).get("shares_outstanding"), "ciq"),
            (mkt.get("shares_outstanding"), "yfinance"),
        ],
        1.0,
        "default",
    )

    drivers = ForecastDrivers(
        revenue_base=float(revenue_base),
        revenue_growth_near=float(growth_near),
        revenue_growth_mid=float(growth_mid),
        revenue_growth_terminal=0.03,
        ebit_margin_start=float(margin_start),
        ebit_margin_target=float(margin_target),
        tax_rate_start=float(tax_start),
        tax_rate_target=float(tax_target),
        capex_pct_start=float(capex_start),
        capex_pct_target=float(capex_target),
        da_pct_start=float(da_start),
        da_pct_target=float(da_target),
        dso_start=float(defaults["dso"]),
        dso_target=float(defaults["dso"]),
        dio_start=float(defaults["dio"]),
        dio_target=float(defaults["dio"]),
        dpo_start=float(defaults["dpo"]),
        dpo_target=float(defaults["dpo"]),
        wacc=float(wacc),
        exit_multiple=float(exit_multiple),
        exit_metric=exit_metric,
        net_debt=float(net_debt_raw),
        shares_outstanding=float(max(shares_raw, 1.0)),
        terminal_blend_gordon_weight=0.60,
        terminal_blend_exit_weight=0.40,
    )

    source_lineage = {
        "revenue_base": revenue_source,
        "revenue_growth_near": growth_source,
        "revenue_growth_mid": growth_source,
        "ebit_margin_start": margin_source,
        "ebit_margin_target": margin_source,
        "tax_rate_start": tax_source,
        "tax_rate_target": "default",
        "capex_pct_start": capex_source,
        "capex_pct_target": capex_source,
        "da_pct_start": da_source,
        "da_pct_target": da_source,
        "dso_start": "default",
        "dso_target": "default",
        "dio_start": "default",
        "dio_target": "default",
        "dpo_start": "default",
        "dpo_target": "default",
        "wacc": "yfinance_capm",
        "exit_multiple": exit_source,
        "exit_metric": "sector_policy",
        "net_debt": net_debt_source,
        "shares_outstanding": shares_source,
    }

    _apply_overrides(drivers, source_lineage, ticker=ticker, sector=sector)

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
        },
        wacc_inputs={
            "wacc": getattr(wacc_result, "wacc", None),
            "cost_of_equity": getattr(wacc_result, "cost_of_equity", None),
            "beta_relevered": getattr(wacc_result, "beta_relevered", None),
            "beta_unlevered_median": getattr(wacc_result, "beta_unlevered_median", None),
            "size_premium": getattr(wacc_result, "size_premium", None),
            "equity_weight": getattr(wacc_result, "equity_weight", None),
            "peers_used": getattr(wacc_result, "peers_used", None),
        },
    )




