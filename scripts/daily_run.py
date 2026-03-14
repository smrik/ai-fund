#!/usr/bin/env python3
"""
Alpha Pod — Daily Runner (non-IBKR)

Runs every morning without requiring IBKR TWS.

Usage:
  python scripts/daily_run.py                        # portfolio brief only
  python scripts/daily_run.py --portfolio            # refresh prices + brief
  python scripts/daily_run.py --screen               # batch valuation on universe
  python scripts/daily_run.py --json                 # export JSON files
  python scripts/daily_run.py --macro                # refresh macro_context.md
  python scripts/daily_run.py --all                  # macro + screen + portfolio
  python scripts/daily_run.py --screen --limit 10    # value first 10 tickers
  python scripts/daily_run.py --screen --top 15      # show top 15 from valuation
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import ROOT_DIR, REPORTS_DIR
from src.portfolio.tracker import PortfolioTracker


def _section(title: str) -> None:
    print()
    print("─" * 60)
    print(f"  {title}")
    print("─" * 60)


def run_portfolio_brief(tracker: PortfolioTracker) -> dict:
    """Refresh prices and return risk metrics."""
    _section("PORTFOLIO")
    n = tracker.update_prices()
    print(f"  Refreshed prices for {n} position(s)")
    tracker.print_brief()
    return tracker.get_risk_metrics()


def run_screen(limit: int | None = None, top: int = 20, export_json: bool = False) -> list[dict]:
    """Run batch valuation. Returns results list."""
    from src.stage_02_valuation.batch_runner import run_batch, value_single_ticker
    import csv

    _section("BATCH VALUATION")

    UNIVERSE_CSV = ROOT_DIR / "config" / "universe.csv"
    if not UNIVERSE_CSV.exists():
        print("  ✗ universe.csv not found. Run stage 1 screener first.")
        return []

    with open(UNIVERSE_CSV, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        tickers = [row["ticker"] for row in reader]

    if limit:
        tickers = tickers[:limit]

    results = run_batch(tickers=tickers, top_n=top, export_xlsx=False) or []

    if export_json and results:
        from datetime import datetime as dt
        from src.stage_02_valuation.json_exporter import export_ticker_json
        from src.stage_00_data.ciq_adapter import get_ciq_comps_detail

        today = dt.now().strftime("%Y-%m-%d")
        json_dir = ROOT_DIR / "data" / "valuations" / "json"
        json_dir.mkdir(parents=True, exist_ok=True)
        exported = 0
        for result in results:
            try:
                t = result.get("ticker", "UNKNOWN")
                comps = get_ciq_comps_detail(t)
                export_ticker_json(result, qoe=None, comps_detail=comps,
                                   output_dir=json_dir, date_str=today)
                exported += 1
            except Exception:
                pass
        print(f"\n  ✓ JSON exports: {exported} files → {json_dir}")

    return results


def run_macro_refresh() -> None:
    """Refresh macro_context.md."""
    _section("MACRO REFRESH")
    try:
        from src.stage_03_judgment.macro_agent import MacroAgent, MACRO_OUTPUT_PATH
        agent = MacroAgent()
        agent.refresh()
        print(f"  ✓ Macro context written to {MACRO_OUTPUT_PATH}")
    except Exception as e:
        print(f"  ✗ Macro refresh failed: {e}")


def generate_report(
    risk: dict | None,
    valuation_results: list[dict],
    top_n: int = 10,
) -> str:
    """Build the morning brief as a markdown string."""
    today = datetime.now().strftime("%Y-%m-%d")
    lines = [
        f"# Alpha Pod — Daily Brief — {today}",
        "",
    ]

    # Portfolio snapshot
    if risk:
        lines += [
            "## Portfolio",
            "",
            f"| Metric | Value |",
            f"|--------|-------|",
            f"| NAV | ${risk['nav']:,.0f} |",
            f"| Unrealized P&L | ${risk['unrealized_pnl']:+,.0f} |",
            f"| Realized P&L | ${risk['realized_pnl']:+,.0f} |",
            f"| Gross Exposure | {risk['gross_exposure_pct']:.1f}% |",
            f"| Net Exposure | {risk['net_exposure_pct']:+.1f}% |",
            f"| Positions | {risk['position_count']} |",
            "",
        ]
        if risk.get("alerts"):
            lines.append("### ⚠ Alerts")
            for alert in risk["alerts"]:
                lines.append(f"- {alert}")
            lines.append("")

    # Top opportunities from valuation
    if valuation_results:
        dcf_results = [
            r for r in valuation_results
            if r.get("expected_upside_pct") is not None or r.get("upside_base_pct") is not None
        ]
        dcf_results.sort(
            key=lambda r: r.get("expected_upside_pct") or r.get("upside_base_pct") or -999,
            reverse=True,
        )
        lines += [
            "## Top Opportunities",
            "",
            "| Ticker | Company | Price | IV Base | Upside | WACC |",
            "|--------|---------|-------|---------|--------|------|",
        ]
        for r in dcf_results[:top_n]:
            upside = r.get("expected_upside_pct") or r.get("upside_base_pct") or 0.0
            iv = r.get("expected_iv") or r.get("iv_base") or 0.0
            lines.append(
                f"| {r['ticker']} | {r.get('company_name','')[:25]} | "
                f"${r.get('price', 0):.2f} | ${iv:.2f} | {upside:+.1f}% | {r.get('wacc', 0):.1f}% |"
            )
        lines.append("")

    lines += ["---", f"*Generated {datetime.now().strftime('%Y-%m-%d %H:%M')}*"]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Alpha Pod daily runner")
    parser.add_argument("--portfolio", action="store_true", help="Refresh portfolio prices + brief")
    parser.add_argument("--screen", action="store_true", help="Run batch valuation")
    parser.add_argument("--json", action="store_true", help="Export per-ticker JSON files")
    parser.add_argument("--macro", action="store_true", help="Refresh macro context")
    parser.add_argument("--all", action="store_true", help="Run everything")
    parser.add_argument("--limit", type=int, help="Limit batch to N tickers")
    parser.add_argument("--top", type=int, default=20, help="Show top N from valuation")
    args = parser.parse_args()

    # --all expands to everything
    if args.all:
        args.portfolio = True
        args.screen = True
        args.json = True
        args.macro = True

    # Default: portfolio brief if nothing else specified
    if not any([args.portfolio, args.screen, args.macro]):
        args.portfolio = True

    print("═" * 60)
    print(f"ALPHA POD — Daily Run — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("═" * 60)

    tracker = PortfolioTracker()
    risk_metrics: dict | None = None
    valuation_results: list[dict] = []

    if args.macro:
        run_macro_refresh()

    if args.portfolio:
        risk_metrics = run_portfolio_brief(tracker)

    if args.screen:
        valuation_results = run_screen(
            limit=args.limit,
            top=args.top,
            export_json=args.json,
        )

    # Save markdown report
    report = generate_report(risk_metrics, valuation_results, top_n=args.top)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")
    report_path = REPORTS_DIR / f"daily_{today}.md"
    report_path.write_text(report, encoding="utf-8")

    print()
    print("═" * 60)
    print(f"✓ Report saved: {report_path}")
    print("═" * 60)


if __name__ == "__main__":
    main()
