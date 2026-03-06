"""
Batch Valuation Runner — ranks Stage 1 survivors by DCF upside.

Runs a deterministic WACC + DCF on every ticker in the universe.
No LLM — all assumptions derived from financial data.

Output:
  1. Excel workbook (data/valuations/batch_valuation_YYYY-MM-DD.xlsx)
     - Summary tab: ranked by upside, filterable
     - WACC tab: full CAPM audit trail for each ticker
     - DCF tab: assumption details and sensitivity
  2. Terminal: top 30 ranked by base-case upside

Usage:
    python -m src.valuation.batch_runner
    python -m src.valuation.batch_runner --top 50
    python -m src.valuation.batch_runner --ticker HALO   # Single ticker deep dive
"""

import sys
import csv
import time
import json
from pathlib import Path
from datetime import datetime
from dataclasses import asdict

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from src.data import market_data as md_client
from src.valuation.wacc import compute_wacc_from_yfinance, PeerData, WACCResult
from src.templates.dcf_model import DCFAssumptions, run_dcf, run_scenario_dcf


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


def value_single_ticker(ticker: str) -> dict | None:
    """
    Run full WACC + DCF valuation for a single ticker.
    Returns dict with all valuation data, or None if data insufficient.
    """
    try:
        # 1. Fetch market data
        mkt = md_client.get_market_data(ticker)
        price = mkt.get("current_price")
        rev = mkt.get("revenue_ttm")
        if not price or not rev or rev <= 0:
            return None

        sector = mkt.get("sector", "")
        defaults = _get_sector_defaults(sector)

        # 1b. Fetch historical financials (3yr)
        hist = md_client.get_historical_financials(ticker)

        # 2. Compute WACC (falls back to own beta if no peers) — pass hist to avoid double fetch
        wacc_result = compute_wacc_from_yfinance(ticker, hist=hist)

        # 3. Derive assumptions from actual financials
        op_margin = mkt.get("operating_margin")
        rev_growth = mkt.get("revenue_growth")

        # EBIT margin — prefer 3yr avg, fallback to TTM, then sector default
        op_margin_3yr = hist.get("op_margin_avg_3yr")
        if op_margin_3yr and op_margin_3yr > 0:
            ebit_margin = op_margin_3yr
            ebit_margin_source = "3yr_avg"
        elif op_margin and op_margin > 0:
            ebit_margin = op_margin
            ebit_margin_source = "ttm"
        else:
            ebit_margin = defaults["ebit_margin_override"] or 0.15
            ebit_margin_source = "sector_default"

        # Revenue growth — prefer 3yr CAGR, fallback to TTM, then sector default
        rev_cagr_3yr = hist.get("revenue_cagr_3yr")
        if rev_cagr_3yr is not None and rev_cagr_3yr > -0.10:
            growth_near = max(min(rev_cagr_3yr, 0.30), 0.02)
            growth_source = "3yr_cagr"
        elif rev_growth and rev_growth > -0.10:
            growth_near = max(min(rev_growth, 0.30), 0.02)
            growth_source = "ttm"
        else:
            growth_near = defaults["revenue_growth_near"]
            growth_source = "sector_default"
        growth_mid = growth_near * 0.65

        # Capex % revenue — prefer 3yr avg, else sector default
        capex_pct_3yr = hist.get("capex_pct_avg_3yr")
        if capex_pct_3yr and 0.01 <= capex_pct_3yr <= 0.25:
            capex_pct = capex_pct_3yr
            capex_source = "3yr_avg"
        else:
            capex_pct = defaults["capex_pct"]
            capex_source = "sector_default"

        # D&A % revenue — prefer 3yr avg, else sector default
        da_pct_3yr = hist.get("da_pct_avg_3yr")
        if da_pct_3yr and 0.005 <= da_pct_3yr <= 0.20:
            da_pct = da_pct_3yr
            da_source = "3yr_avg"
        else:
            da_pct = defaults["da_pct"]
            da_source = "sector_default"

        # Tax rate — prefer 3yr avg, else US default
        tax_rate_hist = hist.get("effective_tax_rate_avg")
        if tax_rate_hist and 0.05 <= tax_rate_hist <= 0.40:
            tax_rate = tax_rate_hist
            tax_source = "3yr_avg"
        else:
            tax_rate = 0.21
            tax_source = "us_default"

        # Net debt and shares
        net_debt = (mkt.get("total_debt") or 0) - (mkt.get("cash") or 0)
        shares = mkt.get("shares_outstanding") or 1

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
            "op_margin": round(op_margin * 100, 1) if op_margin else None,
            "profit_margin": round((mkt.get("profit_margin") or 0) * 100, 1),
            "rev_growth": round((rev_growth or 0) * 100, 1),
            "fcf_mm": round((mkt.get("free_cashflow") or 0) / 1e6, 0),
            "net_debt_mm": round(net_debt / 1e6, 0),
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

            # Assumptions used (for review) — with source audit trail
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
        ]
        df_dcf = df[[c for c in dcf_cols if c in df.columns]].copy()
        df_dcf.sort_values("upside_base_pct", ascending=False, inplace=True)
        df_dcf.to_excel(writer, sheet_name="DCF Assumptions", index=False)

        # Tab 4: Full data dump
        df.to_excel(writer, sheet_name="All Data", index=False)

    print(f"✓ Saved to {output_path}")


def run_batch(tickers: list[str] = None, top_n: int = 30):
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
        pct = i / len(tickers) * 100
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

    # CSV: latest.csv (Power Query reads this) + dated backup
    latest_csv = OUTPUT_DIR / "latest.csv"
    dated_csv = OUTPUT_DIR / f"batch_{today}.csv"
    df.to_csv(latest_csv, index=False)
    df.to_csv(dated_csv, index=False)
    print(f"✓ CSV: {latest_csv}")
    print(f"  Backup: {dated_csv}")

    # Excel: dated snapshot
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
    print(f"Excel: {xlsx_path}")
    print(f"CSV (for Power Query): {latest_csv}")
    print()
    print("To connect your Excel template: Data → Get Data → From Text/CSV → select latest.csv")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Batch valuation runner")
    parser.add_argument("--top", type=int, default=30, help="Show top N results")
    parser.add_argument("--ticker", type=str, help="Run single ticker deep dive")
    parser.add_argument("--limit", type=int, help="Limit number of tickers to value")
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
                tickers = [row["ticker"] for row in reader][:args.limit]
        run_batch(tickers=tickers, top_n=args.top)
