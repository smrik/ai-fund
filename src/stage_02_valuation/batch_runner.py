"""
Batch Valuation Runner — ranks Stage 1 survivors by DCF upside.

Runs a deterministic WACC + DCF on every ticker in the universe.
No LLM — all assumptions derived from financial data.

Output:
  1. SQLite snapshot (data/alpha_pod.db, table: batch_valuations_latest)
  2. CSV file (data/valuations/latest.csv) for Excel/Power Query
  3. Optional Excel workbook (data/valuations/batch_valuation_YYYY-MM-DD.xlsx)
     - Summary tab: ranked by upside, filterable
     - WACC tab: full CAPM audit trail for each ticker
     - DCF tab: assumption details and sensitivity
  4. Terminal: top 30 ranked by base-case upside

Usage:
    python -m src.stage_02_valuation.batch_runner
    python -m src.stage_02_valuation.batch_runner --top 50
    python -m src.stage_02_valuation.batch_runner --xlsx
    python -m src.stage_02_valuation.batch_runner --ticker HALO   # Single ticker deep dive
"""

from __future__ import annotations

import sys
import csv
import time
import json
import sqlite3
from pathlib import Path
from datetime import datetime

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from config import DB_PATH
from src.stage_00_data import market_data as md_client
from src.stage_00_data.ciq_adapter import get_ciq_snapshot
from src.stage_02_valuation.wacc import compute_wacc_from_yfinance
from src.stage_02_valuation.templates.dcf_model import DCFAssumptions, run_dcf, run_scenario_dcf


# ── Paths ──────────────────────────────────────────────
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
UNIVERSE_CSV = ROOT_DIR / "config" / "universe.csv"
OUTPUT_DIR = ROOT_DIR / "data" / "valuations"
CACHE_DIR = ROOT_DIR / "data" / "cache"


# ── Sector-based assumption defaults ──────────────────
# These are starting points — the whole point is to review and adjust
SECTOR_ASSUMPTIONS = {
    "Technology": {
        "revenue_growth_near": 0.15,
        "revenue_growth_mid": 0.10,
        "ebit_margin_override": None,  # Use actual if available
        "exit_multiple": 20.0,
        "capex_pct": 0.06,
        "da_pct": 0.04,
    },
    "Healthcare": {
        "revenue_growth_near": 0.12,
        "revenue_growth_mid": 0.08,
        "ebit_margin_override": None,
        "exit_multiple": 18.0,
        "capex_pct": 0.05,
        "da_pct": 0.04,
    },
    "Industrials": {
        "revenue_growth_near": 0.08,
        "revenue_growth_mid": 0.05,
        "ebit_margin_override": None,
        "exit_multiple": 14.0,
        "capex_pct": 0.05,
        "da_pct": 0.04,
    },
    "Consumer Cyclical": {
        "revenue_growth_near": 0.10,
        "revenue_growth_mid": 0.06,
        "ebit_margin_override": None,
        "exit_multiple": 14.0,
        "capex_pct": 0.04,
        "da_pct": 0.03,
    },
    "Consumer Defensive": {
        "revenue_growth_near": 0.06,
        "revenue_growth_mid": 0.04,
        "ebit_margin_override": None,
        "exit_multiple": 15.0,
        "capex_pct": 0.04,
        "da_pct": 0.03,
    },
    "Energy": {
        "revenue_growth_near": 0.05,
        "revenue_growth_mid": 0.03,
        "ebit_margin_override": None,
        "exit_multiple": 10.0,
        "capex_pct": 0.08,
        "da_pct": 0.06,
    },
    "Basic Materials": {
        "revenue_growth_near": 0.06,
        "revenue_growth_mid": 0.04,
        "ebit_margin_override": None,
        "exit_multiple": 11.0,
        "capex_pct": 0.06,
        "da_pct": 0.05,
    },
    "Communication Services": {
        "revenue_growth_near": 0.10,
        "revenue_growth_mid": 0.06,
        "ebit_margin_override": None,
        "exit_multiple": 16.0,
        "capex_pct": 0.05,
        "da_pct": 0.04,
    },
    "_default": {
        "revenue_growth_near": 0.08,
        "revenue_growth_mid": 0.05,
        "ebit_margin_override": None,
        "exit_multiple": 14.0,
        "capex_pct": 0.05,
        "da_pct": 0.04,
    },
}


def _get_sector_defaults(sector: str) -> dict:
    """Get sector-specific assumption defaults."""
    return SECTOR_ASSUMPTIONS.get(sector, SECTOR_ASSUMPTIONS["_default"])


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
    """
    Binary search for the near-term revenue growth rate that makes
    base-case intrinsic value equal to target_price.

    Returns the implied growth rate, or None if it falls outside [low, high].
    """

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

    # Check if target is achievable within [low, high]
    try:
        iv_low = _iv(low)
        iv_high = _iv(high)
    except Exception:
        return None

    if target_price < iv_low or target_price > iv_high:
        return None  # Out of search range

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


def value_single_ticker(ticker: str) -> dict | None:
    """
    Run full WACC + DCF valuation for a single ticker.
    Returns dict with all valuation data, or None if data insufficient.
    """
    try:
        # 1. Fetch market data + CIQ snapshot (if available)
        mkt = md_client.get_market_data(ticker)
        hist = md_client.get_historical_financials(ticker)
        ciq = get_ciq_snapshot(ticker)

        price = mkt.get("current_price")
        if not price or price <= 0:
            return None

        # Revenue base for DCF: CIQ first, then yfinance
        rev_ciq = ciq.get("revenue_ttm") if ciq else None
        rev_yf = mkt.get("revenue_ttm")
        if rev_ciq and rev_ciq > 0:
            rev = rev_ciq
            revenue_source = "ciq"
        elif rev_yf and rev_yf > 0:
            rev = rev_yf
            revenue_source = "yfinance"
        else:
            return None

        sector = mkt.get("sector", "")
        defaults = _get_sector_defaults(sector)

        # 2. Compute WACC (deterministic yfinance pipeline)
        wacc_result = compute_wacc_from_yfinance(ticker, hist=hist)

        # 3. Derive assumptions with CIQ precedence and deterministic fallbacks
        op_margin_ttm = mkt.get("operating_margin")
        ciq_op_margin = None
        if ciq:
            ciq_op_margin = ciq.get("op_margin_avg_3yr") or ciq.get("ebit_margin")

        if ciq_op_margin and 0 < ciq_op_margin < 0.8:
            ebit_margin = ciq_op_margin
            ebit_margin_source = "ciq"
        elif hist.get("op_margin_avg_3yr") and hist["op_margin_avg_3yr"] > 0:
            ebit_margin = hist["op_margin_avg_3yr"]
            ebit_margin_source = "yfinance"
        elif op_margin_ttm and op_margin_ttm > 0:
            ebit_margin = op_margin_ttm
            ebit_margin_source = "yfinance"
        else:
            ebit_margin = defaults["ebit_margin_override"] or 0.15
            ebit_margin_source = "default"

        rev_growth_ciq = ciq.get("revenue_cagr_3yr") if ciq else None
        rev_growth_hist = hist.get("revenue_cagr_3yr")
        rev_growth_ttm = mkt.get("revenue_growth")
        if rev_growth_ciq is not None and rev_growth_ciq > -0.10:
            growth_near = max(min(rev_growth_ciq, 0.30), 0.02)
            growth_source = "ciq"
        elif rev_growth_hist is not None and rev_growth_hist > -0.10:
            growth_near = max(min(rev_growth_hist, 0.30), 0.02)
            growth_source = "yfinance"
        elif rev_growth_ttm and rev_growth_ttm > -0.10:
            growth_near = max(min(rev_growth_ttm, 0.30), 0.02)
            growth_source = "yfinance"
        else:
            growth_near = defaults["revenue_growth_near"]
            growth_source = "default"
        growth_mid = growth_near * 0.65

        capex_pct_ciq = ciq.get("capex_pct_avg_3yr") if ciq else None
        capex_pct_hist = hist.get("capex_pct_avg_3yr")
        if capex_pct_ciq and 0.01 <= capex_pct_ciq <= 0.25:
            capex_pct = capex_pct_ciq
            capex_source = "ciq"
        elif capex_pct_hist and 0.01 <= capex_pct_hist <= 0.25:
            capex_pct = capex_pct_hist
            capex_source = "yfinance"
        else:
            capex_pct = defaults["capex_pct"]
            capex_source = "default"

        da_pct_ciq = ciq.get("da_pct_avg_3yr") if ciq else None
        da_pct_hist = hist.get("da_pct_avg_3yr")
        if da_pct_ciq and 0.005 <= da_pct_ciq <= 0.20:
            da_pct = da_pct_ciq
            da_source = "ciq"
        elif da_pct_hist and 0.005 <= da_pct_hist <= 0.20:
            da_pct = da_pct_hist
            da_source = "yfinance"
        else:
            da_pct = defaults["da_pct"]
            da_source = "default"

        tax_rate_ciq = ciq.get("effective_tax_rate_avg") if ciq else None
        tax_rate_hist = hist.get("effective_tax_rate_avg")
        if tax_rate_ciq and 0.05 <= tax_rate_ciq <= 0.40:
            tax_rate = tax_rate_ciq
            tax_source = "ciq"
        elif tax_rate_hist and 0.05 <= tax_rate_hist <= 0.40:
            tax_rate = tax_rate_hist
            tax_source = "yfinance"
        else:
            tax_rate = 0.21
            tax_source = "default"

        # Net debt and shares with CIQ precedence
        ciq_debt = ciq.get("total_debt") if ciq else None
        ciq_cash = ciq.get("cash") if ciq else None
        if ciq_debt is not None or ciq_cash is not None:
            net_debt = (ciq_debt or 0) - (ciq_cash or 0)
            net_debt_source = "ciq"
        else:
            net_debt = (mkt.get("total_debt") or 0) - (mkt.get("cash") or 0)
            net_debt_source = "yfinance"

        if ciq and ciq.get("shares_outstanding") and ciq.get("shares_outstanding") > 0:
            shares = ciq["shares_outstanding"]
            shares_source = "ciq"
        else:
            shares = mkt.get("shares_outstanding") or 1
            shares_source = "yfinance"

        # 4. Run DCF
        assumptions = DCFAssumptions(
            revenue_growth_near=growth_near,
            revenue_growth_mid=growth_mid,
            revenue_growth_terminal=0.03,
            ebit_margin=ebit_margin,
            tax_rate=tax_rate,
            capex_pct_revenue=capex_pct,
            da_pct_revenue=da_pct,
            nwc_change_pct_revenue=0.01,
            wacc=wacc_result.wacc,
            exit_multiple=defaults["exit_multiple"],
            net_debt=net_debt,
            shares_outstanding=shares,
        )

        scenarios = run_scenario_dcf(rev, assumptions)

        base_iv = scenarios["base"].intrinsic_value_per_share
        bear_iv = scenarios["bear"].intrinsic_value_per_share
        bull_iv = scenarios["bull"].intrinsic_value_per_share
        upside_base = (base_iv / price - 1) if price else 0

        implied_growth = reverse_dcf(
            revenue=rev,
            assumptions=assumptions,
            target_price=price,
            shares=shares,
            net_debt=net_debt,
        )

        display_op_margin = ciq_op_margin or op_margin_ttm
        display_rev_growth = rev_growth_ciq if rev_growth_ciq is not None else rev_growth_ttm

        return {
            # Identity
            "ticker": ticker,
            "company_name": mkt.get("name", ""),
            "sector": sector,
            "industry": mkt.get("industry", ""),

            # Market data
            "price": round(price, 2),
            "market_cap_mm": round(mkt.get("market_cap", 0) / 1e6, 0),
            "ev_mm": round((mkt.get("enterprise_value") or 0) / 1e6, 0),
            "pe_trailing": mkt.get("pe_trailing"),
            "pe_forward": mkt.get("pe_forward"),
            "ev_ebitda": mkt.get("ev_ebitda"),

            # Financials
            "revenue_mm": round(rev / 1e6, 0),
            "revenue_source": revenue_source,
            "op_margin": round(display_op_margin * 100, 1) if display_op_margin is not None else None,
            "profit_margin": round((mkt.get("profit_margin") or 0) * 100, 1),
            "rev_growth": round((display_rev_growth or 0) * 100, 1),
            "fcf_mm": round((mkt.get("free_cashflow") or 0) / 1e6, 0),
            "net_debt_mm": round(net_debt / 1e6, 0),
            "net_debt_source": net_debt_source,
            "shares_source": shares_source,
            "beta_raw": mkt.get("beta"),

            # WACC
            "wacc": round(wacc_result.wacc * 100, 2),
            "cost_of_equity": round(wacc_result.cost_of_equity * 100, 2),
            "beta_relevered": round(wacc_result.beta_relevered, 2),
            "beta_unlevered": round(wacc_result.beta_unlevered_median, 2),
            "size_premium": round(wacc_result.size_premium * 100, 1),
            "equity_weight": round(wacc_result.equity_weight * 100, 0),
            "peers_used": ", ".join(wacc_result.peers_used),

            # DCF results
            "iv_bear": round(bear_iv, 2),
            "iv_base": round(base_iv, 2),
            "iv_bull": round(bull_iv, 2),
            "upside_base_pct": round(upside_base * 100, 1),
            "upside_bear_pct": round((bear_iv / price - 1) * 100, 1) if price else 0,
            "upside_bull_pct": round((bull_iv / price - 1) * 100, 1) if price else 0,
            "margin_of_safety": round((1 - price / base_iv) * 100, 1) if base_iv > 0 else None,

            # Assumptions used (source flags: ciq/yfinance/default)
            "growth_near": round(growth_near * 100, 1),
            "growth_mid": round(growth_mid * 100, 1),
            "growth_source": growth_source,
            "ebit_margin_used": round(ebit_margin * 100, 1),
            "ebit_margin_source": ebit_margin_source,
            "capex_pct_used": round(capex_pct * 100, 2),
            "capex_source": capex_source,
            "da_pct_used": round(da_pct * 100, 2),
            "da_source": da_source,
            "tax_rate_used": round(tax_rate * 100, 1),
            "tax_source": tax_source,
            "exit_multiple_used": defaults["exit_multiple"],
            "tv_pct_of_ev": round(
                scenarios["base"].terminal_value / scenarios["base"].enterprise_value * 100, 0
            ) if scenarios["base"].enterprise_value else None,
            "implied_growth_pct": round(implied_growth * 100, 1) if implied_growth is not None else None,
            "tv_high_flag": (
                True
                if scenarios["base"].enterprise_value and
                   scenarios["base"].terminal_value / scenarios["base"].enterprise_value > 0.75
                else False
            ),

            # CIQ lineage
            "ciq_snapshot_used": bool(ciq),
            "ciq_run_id": ciq.get("run_id") if ciq else None,
            "ciq_source_file": ciq.get("source_file") if ciq else None,
            "ciq_as_of_date": ciq.get("as_of_date") if ciq else None,

            # Analyst comparison
            "analyst_target": mkt.get("analyst_target_mean"),
            "analyst_recommendation": mkt.get("analyst_recommendation"),
            "num_analysts": mkt.get("number_of_analysts"),
        }

    except Exception as e:
        print(f"  ✗ {ticker}: {e}")
        return None


def export_to_excel(results: list[dict], output_path: Path):
    """
    Export valuation results to an Excel workbook with multiple tabs.
    """
    df = pd.DataFrame(results)

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        # Tab 1: Summary — the main review sheet
        summary_cols = [
            "ticker", "company_name", "sector", "price",
            "iv_bear", "iv_base", "iv_bull",
            "upside_base_pct", "margin_of_safety",
            "market_cap_mm", "pe_trailing", "ev_ebitda",
            "rev_growth", "op_margin", "wacc",
            "analyst_target", "analyst_recommendation",
        ]
        df_summary = df[[c for c in summary_cols if c in df.columns]].copy()
        df_summary.sort_values("upside_base_pct", ascending=False, inplace=True)
        df_summary.to_excel(writer, sheet_name="Summary", index=False)

        # Tab 2: WACC details
        wacc_cols = [
            "ticker", "sector", "price", "market_cap_mm",
            "wacc", "cost_of_equity", "beta_raw", "beta_unlevered",
            "beta_relevered", "size_premium", "equity_weight",
            "net_debt_mm", "peers_used",
        ]
        df_wacc = df[[c for c in wacc_cols if c in df.columns]].copy()
        df_wacc.sort_values("ticker", inplace=True)
        df_wacc.to_excel(writer, sheet_name="WACC Detail", index=False)

        # Tab 3: DCF assumptions — for review and adjustment
        dcf_cols = [
            "ticker", "sector", "revenue_mm",
            "growth_near", "growth_mid", "growth_source",
            "ebit_margin_used", "ebit_margin_source",
            "capex_pct_used", "capex_source",
            "da_pct_used", "da_source",
            "tax_rate_used", "tax_source",
            "exit_multiple_used", "wacc",
            "iv_bear", "iv_base", "iv_bull", "price",
            "upside_base_pct", "tv_pct_of_ev",
            "implied_growth_pct", "tv_high_flag",
            "ciq_snapshot_used", "ciq_run_id", "ciq_source_file", "ciq_as_of_date",
        ]
        df_dcf = df[[c for c in dcf_cols if c in df.columns]].copy()
        df_dcf.sort_values("upside_base_pct", ascending=False, inplace=True)
        df_dcf.to_excel(writer, sheet_name="DCF Assumptions", index=False)

        # Tab 4: Full data dump
        df.to_excel(writer, sheet_name="All Data", index=False)

    print(f"✓ Saved to {output_path}")


def _safe_float(value):
    """Convert values to float where possible, preserving None for nulls."""
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


def persist_results_to_db(df: pd.DataFrame, snapshot_date: str) -> tuple[int, int]:
    """
    Persist valuation output to SQLite.

    1) Replace full snapshot table: batch_valuations_latest
    2) Upsert normalized valuation history into valuations table
    """
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
    """
    Run batch valuation across universe and export results.
    """
    print("=" * 64)
    print("ALPHA POD — Batch Valuation Runner")
    print("=" * 64)
    print()

    # Load universe
    if tickers is None:
        if not UNIVERSE_CSV.exists():
            print("✗ No universe.csv found. Run Stage 1 screener first.")
            return
        with open(UNIVERSE_CSV) as f:
            reader = csv.DictReader(f)
            tickers = [row["ticker"] for row in reader]
        print(f"Loaded {len(tickers)} tickers from universe.csv")
    else:
        print(f"Running on {len(tickers)} tickers")
    print()

    # Run valuations
    results = []
    errors = 0
    for i, ticker in enumerate(tickers, 1):
        print(f"  [{i:>3}/{len(tickers)}] {ticker:<8} ", end="", flush=True)

        result = value_single_ticker(ticker)
        if result:
            results.append(result)
            upside = result["upside_base_pct"]
            flag = "★" if upside > 20 else "·"
            print(f"${result['price']:>8.2f} → ${result['iv_base']:>8.2f}  ({upside:>+6.1f}%)  WACC {result['wacc']:.1f}%  {flag}")
        else:
            errors += 1
            print("skipped (insufficient data)")

        time.sleep(0.3)  # Rate limiting

    print()
    print(f"  Completed: {len(results)} valued, {errors} skipped")
    print()

    if not results:
        print("No results to export.")
        return

    # Sort by upside
    results.sort(key=lambda r: r["upside_base_pct"], reverse=True)

    # Export
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")
    df = pd.DataFrame(results)

    # CSV: latest.csv (Power Query reads this)
    latest_csv = OUTPUT_DIR / "latest.csv"
    df.to_csv(latest_csv, index=False)
    print(f"✓ CSV: {latest_csv}")

    # SQLite: canonical persistence
    latest_rows, valuation_rows = persist_results_to_db(df, snapshot_date=today)
    print(f"✓ SQLite: {DB_PATH}")
    print(f"  batch_valuations_latest={latest_rows}, valuations={valuation_rows}")

    xlsx_path = None
    if export_xlsx:
        xlsx_path = OUTPUT_DIR / f"batch_valuation_{today}.xlsx"
        export_to_excel(results, xlsx_path)

    # Terminal summary
    print()
    print("=" * 64)
    print(f"TOP {min(top_n, len(results))} BY BASE-CASE UPSIDE")
    print("=" * 64)
    print(f"{'Ticker':<8} {'Company':<30} {'Price':>8} {'Base IV':>8} {'Upside':>8} {'WACC':>6} {'PE':>6} {'Sector'}")
    print("-" * 100)

    for r in results[:top_n]:
        pe_str = f"{r['pe_trailing']:.0f}" if r.get("pe_trailing") else "N/A"
        print(
            f"{r['ticker']:<8} {r['company_name'][:29]:<30} "
            f"${r['price']:>7.2f} ${r['iv_base']:>7.2f} "
            f"{r['upside_base_pct']:>+7.1f}% "
            f"{r['wacc']:>5.1f}% "
            f"{pe_str:>5} "
            f"{r['sector'][:15]}"
        )

    print()
    if xlsx_path:
        print(f"Excel: {xlsx_path}")
    else:
        print("Excel: skipped (pass --xlsx to export workbook)")
    print(f"CSV (for Power Query): {latest_csv}")
    print()
    print("To connect your Excel template: Data → Get Data → From Text/CSV → select latest.csv")


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
            with open(UNIVERSE_CSV) as f:
                reader = csv.DictReader(f)
                tickers = [row["ticker"] for row in reader][: args.limit]
        run_batch(tickers=tickers, top_n=args.top, export_xlsx=args.xlsx)
