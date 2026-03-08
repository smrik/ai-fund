"""
Batch Valuation Runner — deterministic professional DCF with lineage and audit exports.
"""

from __future__ import annotations

import csv
import json
import sqlite3
import sys
import time
from dataclasses import asdict, replace
from datetime import datetime
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from config import DB_PATH
from src.stage_00_data import market_data as md_client
from src.stage_02_valuation.input_assembler import build_valuation_inputs
from src.stage_02_valuation.professional_dcf import (
    ForecastDrivers,
    ScenarioSpec,
    default_scenario_specs,
    run_dcf_professional,
    run_probabilistic_valuation,
)
from src.stage_02_valuation.templates.dcf_model import DCFAssumptions, run_dcf


ROOT_DIR = Path(__file__).resolve().parent.parent.parent
UNIVERSE_CSV = ROOT_DIR / "config" / "universe.csv"
OUTPUT_DIR = ROOT_DIR / "data" / "valuations"


def reverse_dcf(
    revenue: float,
    assumptions: "DCFAssumptions",
    target_price: float,
    shares: float,
    net_debt: float,
    low: float = -0.05,
    high: float = 0.50,
    tol: float = 0.001,
    max_iter: int = 50,
) -> float | None:
    """Binary search implied near-term revenue growth for a simple DCF target price."""

    def _iv(g: float) -> float:
        a = DCFAssumptions(
            revenue_growth_near=g,
            revenue_growth_mid=g * 0.65,
            revenue_growth_terminal=assumptions.revenue_growth_terminal,
            ebit_margin=assumptions.ebit_margin,
            tax_rate=assumptions.tax_rate,
            capex_pct_revenue=assumptions.capex_pct_revenue,
            da_pct_revenue=assumptions.da_pct_revenue,
            nwc_change_pct_revenue=assumptions.nwc_change_pct_revenue,
            wacc=assumptions.wacc,
            exit_multiple=assumptions.exit_multiple,
            net_debt=net_debt,
            shares_outstanding=shares,
        )
        return run_dcf(revenue, a).intrinsic_value_per_share

    try:
        iv_low = _iv(low)
        iv_high = _iv(high)
    except Exception:
        return None

    if target_price < iv_low or target_price > iv_high:
        return None

    for _ in range(max_iter):
        mid = (low + high) / 2
        iv_mid = _iv(mid)
        if abs(iv_mid - target_price) / max(abs(target_price), 1) < tol:
            return round(mid, 4)
        if iv_mid < target_price:
            low = mid
        else:
            high = mid

    return round((low + high) / 2, 4)


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
            "beta_relevered": round((wacc_inputs.get("beta_relevered") or 0), 2) if wacc_inputs.get("beta_relevered") is not None else None,
            "beta_unlevered": round((wacc_inputs.get("beta_unlevered_median") or 0), 2) if wacc_inputs.get("beta_unlevered_median") is not None else None,
            "size_premium": round((wacc_inputs.get("size_premium") or 0) * 100, 1) if wacc_inputs.get("size_premium") is not None else None,
            "equity_weight": round((wacc_inputs.get("equity_weight") or 0) * 100, 0) if wacc_inputs.get("equity_weight") is not None else None,
            "peers_used": ", ".join(wacc_inputs.get("peers_used") or []),
            "growth_near": round(inputs.drivers.revenue_growth_near * 100, 1),
            "growth_mid": round(inputs.drivers.revenue_growth_mid * 100, 1),
            "growth_source": lineage.get("revenue_growth_near", "default"),
            "ebit_margin_used": round(inputs.drivers.ebit_margin_start * 100, 1),
            "ebit_margin_source": lineage.get("ebit_margin_start", "default"),
            "capex_pct_used": round(inputs.drivers.capex_pct_start * 100, 2),
            "capex_source": lineage.get("capex_pct_start", "default"),
            "da_pct_used": round(inputs.drivers.da_pct_start * 100, 2),
            "da_source": lineage.get("da_pct_start", "default"),
            "tax_rate_used": round(inputs.drivers.tax_rate_start * 100, 1),
            "tax_source": lineage.get("tax_rate_start", "default"),
            "exit_multiple_used": round(inputs.drivers.exit_multiple, 2),
            "exit_multiple_source": lineage.get("exit_multiple", "default"),
            "exit_metric_used": inputs.drivers.exit_metric,
            "model_applicability_status": inputs.model_applicability_status,
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
            "peer_median_pe_ltm": ciq.get("peer_median_pe_ltm"),
            "comps_iv_ev_ebitda": ciq.get("comps_iv_ev_ebitda"),
            "comps_iv_pe": ciq.get("comps_iv_pe"),
            "comps_iv_base": ciq.get("comps_iv_base"),
            "comps_upside_pct": (
                round(((ciq.get("comps_iv_base") / price) - 1.0) * 100, 1)
                if ciq.get("comps_iv_base") is not None and price > 0
                else None
            ),
            "analyst_target": mkt.get("analyst_target_mean"),
            "analyst_recommendation": mkt.get("analyst_recommendation"),
            "num_analysts": mkt.get("number_of_analysts"),
            "drivers_json": json.dumps(asdict(inputs.drivers), separators=(",", ":")),
        }

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
                    "scenario_prob_bear": 0.20,
                    "scenario_prob_base": 0.60,
                    "scenario_prob_bull": 0.20,
                    "forecast_bridge_json": "[]",
                }
            )
            return row

        scenario_specs = default_scenario_specs()
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

        simple_assumptions = DCFAssumptions(
            revenue_growth_near=inputs.drivers.revenue_growth_near,
            revenue_growth_mid=inputs.drivers.revenue_growth_mid,
            revenue_growth_terminal=inputs.drivers.revenue_growth_terminal,
            ebit_margin=inputs.drivers.ebit_margin_start,
            tax_rate=inputs.drivers.tax_rate_start,
            capex_pct_revenue=inputs.drivers.capex_pct_start,
            da_pct_revenue=inputs.drivers.da_pct_start,
            nwc_change_pct_revenue=0.01,
            wacc=inputs.drivers.wacc,
            exit_multiple=inputs.drivers.exit_multiple,
            net_debt=inputs.drivers.net_debt,
            shares_outstanding=inputs.drivers.shares_outstanding,
        )
        implied_growth = reverse_dcf(
            revenue=inputs.drivers.revenue_base,
            assumptions=simple_assumptions,
            target_price=price,
            shares=inputs.drivers.shares_outstanding,
            net_debt=inputs.drivers.net_debt,
        )

        row.update(
            {
                "iv_bear": round(bear_iv, 2) if bear_iv is not None else None,
                "iv_base": round(base_iv, 2) if base_iv is not None else None,
                "iv_bull": round(bull_iv, 2) if bull_iv is not None else None,
                "upside_base_pct": round(upside_base * 100, 1) if upside_base is not None else None,
                "upside_bear_pct": round(upside_bear * 100, 1) if upside_bear is not None else None,
                "upside_bull_pct": round(upside_bull * 100, 1) if upside_bull is not None else None,
                "margin_of_safety": round((1.0 - price / base_iv) * 100, 1) if base_iv and base_iv > 0 else None,
                "expected_iv": round(probabilistic.expected_iv, 2),
                "expected_upside_pct": round((probabilistic.expected_upside_pct or 0.0) * 100, 1)
                if probabilistic.expected_upside_pct is not None
                else None,
                "tv_pct_of_ev": round((base.tv_pct_of_ev or 0.0) * 100, 1) if base and base.tv_pct_of_ev is not None else None,
                "tv_high_flag": bool(base and base.tv_pct_of_ev is not None and base.tv_pct_of_ev > 0.75),
                "implied_growth_pct": round(implied_growth * 100, 1) if implied_growth is not None else None,
                "iv_gordon": round(base.iv_gordon, 2) if base and base.iv_gordon is not None else None,
                "iv_exit": round(base.iv_exit, 2) if base and base.iv_exit is not None else None,
                "iv_blended": round(base.iv_blended, 2) if base else None,
                "tv_method_fallback_flag": bool(base.tv_method_fallback_flag) if base else None,
                "roic_consistency_flag": bool(base.roic_consistency_flag) if base else None,
                "nwc_driver_quality_flag": bool(base.nwc_driver_quality_flag) if base else None,
                "scenario_prob_bear": next((s.probability for s in scenario_specs if s.name == "bear"), None),
                "scenario_prob_base": next((s.probability for s in scenario_specs if s.name == "base"), None),
                "scenario_prob_bull": next((s.probability for s in scenario_specs if s.name == "bull"), None),
                "forecast_bridge_json": json.dumps([asdict(p) for p in (base.projections if base else [])], separators=(",", ":")),
            }
        )

        return row

    except Exception as exc:
        print(f"  ✗ {ticker}: {exc}")
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
            "ebit_margin_used",
            "ebit_margin_source",
            "capex_pct_used",
            "capex_source",
            "da_pct_used",
            "da_source",
            "tax_rate_used",
            "tax_source",
            "exit_multiple_used",
            "exit_multiple_source",
            "exit_metric_used",
            "revenue_source",
            "net_debt_source",
            "shares_source",
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
            "iv_gordon",
            "iv_exit",
            "iv_blended",
            "tv_pct_of_ev",
            "tv_method_fallback_flag",
            "tv_high_flag",
            "roic_consistency_flag",
            "nwc_driver_quality_flag",
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

    print(f"✓ Saved to {output_path}")


def persist_results_to_db(df: pd.DataFrame, snapshot_date: str) -> tuple[int, int]:
    conn = sqlite3.connect(str(DB_PATH))
    try:
        df.to_sql("batch_valuations_latest", conn, if_exists="replace", index=False)

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
        conn.commit()
        return len(df), len(valuation_rows)
    finally:
        conn.close()


def run_batch(tickers: list[str] = None, top_n: int = 30, export_xlsx: bool = False):
    print("=" * 64)
    print("ALPHA POD — Batch Valuation Runner")
    print("=" * 64)
    print()

    if tickers is None:
        if not UNIVERSE_CSV.exists():
            print("✗ No universe.csv found. Run Stage 1 screener first.")
            return
        with open(UNIVERSE_CSV, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            tickers = [row["ticker"] for row in reader]
        print(f"Loaded {len(tickers)} tickers from universe.csv")
    else:
        print(f"Running on {len(tickers)} tickers")
    print()

    results = []
    errors = 0
    for i, ticker in enumerate(tickers, 1):
        print(f"  [{i:>3}/{len(tickers)}] {ticker:<8} ", end="", flush=True)
        result = value_single_ticker(ticker)
        if result:
            results.append(result)
            iv = result.get("expected_iv") if result.get("expected_iv") is not None else result.get("iv_base")
            upside = result.get("expected_upside_pct")
            if upside is None:
                upside = result.get("upside_base_pct")
            if iv is None:
                print(f"${result['price']:>8.2f}  alt-model")
            else:
                print(f"${result['price']:>8.2f} → ${iv:>8.2f}  ({upside:>+6.1f}%)  WACC {result['wacc']:.1f}%")
        else:
            errors += 1
            print("skipped (insufficient data)")

        time.sleep(0.3)

    print()
    print(f"  Completed: {len(results)} valued, {errors} skipped")
    print()

    if not results:
        print("No results to export.")
        return

    sort_col = "expected_upside_pct" if any(r.get("expected_upside_pct") is not None for r in results) else "upside_base_pct"
    results.sort(key=lambda r: (r.get(sort_col) is not None, r.get(sort_col) if r.get(sort_col) is not None else -1e9), reverse=True)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")
    df = pd.DataFrame(results)

    latest_csv = OUTPUT_DIR / "latest.csv"
    df.to_csv(latest_csv, index=False)
    print(f"✓ CSV: {latest_csv}")

    latest_rows, valuation_rows = persist_results_to_db(df, snapshot_date=today)
    print(f"✓ SQLite: {DB_PATH}")
    print(f"  batch_valuations_latest={latest_rows}, valuations={valuation_rows}")

    xlsx_path = None
    if export_xlsx:
        xlsx_path = OUTPUT_DIR / f"batch_valuation_{today}.xlsx"
        export_to_excel(results, xlsx_path)

    print()
    print("=" * 64)
    print(f"TOP {min(top_n, len(results))} BY {sort_col.upper()}")
    print("=" * 64)
    print(f"{'Ticker':<8} {'Company':<30} {'Price':>8} {'Exp IV':>8} {'Exp Up':>8} {'Base IV':>8} {'WACC':>6} {'Status'}")
    print("-" * 116)

    for r in results[:top_n]:
        exp_iv = r.get("expected_iv")
        exp_up = r.get("expected_upside_pct")
        print(
            f"{r['ticker']:<8} {r['company_name'][:29]:<30} "
            f"${r['price']:>7.2f} "
            f"{('$' + format(exp_iv, '7.2f')) if exp_iv is not None else '    N/A ':>8} "
            f"{(format(exp_up, '+7.1f') + '%') if exp_up is not None else '   N/A ':>8} "
            f"{('$' + format(r.get('iv_base'), '7.2f')) if r.get('iv_base') is not None else '    N/A ':>8} "
            f"{r['wacc']:>5.1f}% "
            f"{r.get('model_applicability_status', '')}"
        )

    print()
    if xlsx_path:
        print(f"Excel: {xlsx_path}")
    else:
        print("Excel: skipped (pass --xlsx to export workbook)")
    print(f"CSV (for Power Query): {latest_csv}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Batch valuation runner")
    parser.add_argument("--top", type=int, default=30, help="Show top N results")
    parser.add_argument("--ticker", type=str, help="Run single ticker deep dive")
    parser.add_argument("--limit", type=int, help="Limit number of tickers to value")
    parser.add_argument("--xlsx", action="store_true", help="Export dated Excel workbook")
    args = parser.parse_args()

    if args.ticker:
        result = value_single_ticker(args.ticker)
        if result:
            print(json.dumps(result, indent=2))
        else:
            print(f"Could not value {args.ticker}")
    else:
        tickers = None
        if args.limit:
            with open(UNIVERSE_CSV, encoding="utf-8") as f:
                reader = csv.DictReader(f)
                tickers = [row["ticker"] for row in reader][: args.limit]
        run_batch(tickers=tickers, top_n=args.top, export_xlsx=args.xlsx)
