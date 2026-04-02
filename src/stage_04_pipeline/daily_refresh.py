"""
Alpha Pod — Daily Refresh Pipeline
Runs every market morning. Pulls prices, updates positions, checks risk, generates dashboard.

Usage:
    cd alpha-pod
    python -m src.stage_04_pipeline.daily_refresh
"""
import sys
import time
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from config.settings import (
    MAX_SINGLE_POSITION_PCT, MAX_GROSS_EXPOSURE_PCT,
    MAX_NET_EXPOSURE_PCT, STOP_LOSS_REVIEW_PCT,
    REPORTS_DIR,
)
from db.schema import get_connection
from db.loader import upsert_prices, upsert_positions, insert_risk_snapshot, log_pipeline_run
from db.queries import get_tickers, get_positions
from ibkr.connection import IBKRConnection
from ibkr.price_feed import get_batch_prices
from ibkr.account import get_account_summary, get_portfolio_positions, compute_risk_snapshot


def check_risk_alerts(risk: dict, positions_df) -> list[str]:
    """Check risk limits and return list of alert messages."""
    alerts = []

    if risk["gross_exposure"] and risk["gross_exposure"] > MAX_GROSS_EXPOSURE_PCT:
        alerts.append(
            f"🚨 GROSS EXPOSURE {risk['gross_exposure']:.1f}% > limit {MAX_GROSS_EXPOSURE_PCT}%"
        )

    if risk["net_exposure"] and risk["net_exposure"] > MAX_NET_EXPOSURE_PCT:
        alerts.append(
            f"🚨 NET EXPOSURE {risk['net_exposure']:.1f}% > limit {MAX_NET_EXPOSURE_PCT}%"
        )

    if risk["top_position_pct"] and risk["top_position_pct"] > MAX_SINGLE_POSITION_PCT:
        alerts.append(
            f"🚨 TOP POSITION {risk['top_position_pct']:.1f}% > limit {MAX_SINGLE_POSITION_PCT}%"
        )

    # Check individual position stop-loss triggers
    if not positions_df.empty:
        for _, pos in positions_df.iterrows():
            if pos["pnl_pct"] and pos["pnl_pct"] <= STOP_LOSS_REVIEW_PCT:
                alerts.append(
                    f"⚠️  {pos['ticker']} at {pos['pnl_pct']:.1f}% — STOP-LOSS REVIEW TRIGGERED"
                )

    return alerts


def generate_dashboard(risk: dict, positions_df, alerts: list[str]) -> str:
    """Generate the morning dashboard as a formatted string."""
    today = datetime.now().strftime("%Y-%m-%d")
    lines = [
        "═" * 55,
        f"ALPHA POD — Morning Brief — {today}",
        "═" * 55,
        "",
        "PORTFOLIO SNAPSHOT",
    ]

    if risk:
        lines.extend([
            f"  NAV:            ${risk.get('nav', 0):,.0f}",
            f"  Daily P&L:      ${risk.get('daily_pnl', 0):+,.0f} ({risk.get('daily_pnl_pct', 0):+.2f}%)",
            f"  Gross:          {risk.get('gross_exposure', 0):.0f}%    Net: {risk.get('net_exposure', 0):.0f}%",
            f"  Top position:   {risk.get('top_position_pct', 0):.1f}%",
            f"  Margin used:    {risk.get('margin_used_pct', 0):.1f}%",
        ])
    else:
        lines.append("  No risk data yet.")

    lines.append("")

    if alerts:
        lines.append("⚠️  ALERTS")
        for alert in alerts:
            lines.append(f"  {alert}")
    else:
        lines.append("✅ No alerts — all limits within bounds")

    lines.append("")

    if not positions_df.empty:
        lines.append("POSITIONS")
        lines.append(f"  {'Ticker':<8} {'Dir':<6} {'Weight':>7} {'P&L %':>8} {'Unreal P&L':>12}")
        lines.append(f"  {'-'*8} {'-'*6} {'-'*7} {'-'*8} {'-'*12}")
        for _, pos in positions_df.iterrows():
            lines.append(
                f"  {pos['ticker']:<8} {pos['direction']:<6} "
                f"{pos['weight_pct']:>6.1f}% {pos['pnl_pct']:>+7.1f}% "
                f"${pos['unrealized_pnl']:>+10,.0f}"
            )
    else:
        lines.append("POSITIONS: None")

    lines.extend(["", "═" * 55])
    return "\n".join(lines)


def run():
    """Execute the full daily refresh pipeline."""
    start = time.time()
    conn = get_connection()

    print("Starting daily refresh pipeline...")
    log_pipeline_run(conn, "daily_refresh", "started")

    try:
        with IBKRConnection() as ib:
            # Step 1: Pull prices for universe
            print("\n[1/4] Pulling prices...")
            tickers = get_tickers(conn)
            if tickers:
                prices_df = get_batch_prices(ib, tickers, days=5)  # Last 5 days
                if not prices_df.empty:
                    upsert_prices(conn, prices_df.to_dict("records"))
                    print(f"  ✓ {len(prices_df)} price records updated")

            # Step 2: Pull positions
            print("\n[2/4] Pulling positions...")
            positions = get_portfolio_positions(ib)
            if positions:
                upsert_positions(conn, positions)
                print(f"  ✓ {len(positions)} positions updated")
            else:
                print("  No open positions")

            # Step 3: Compute risk snapshot
            print("\n[3/4] Computing risk snapshot...")
            account = get_account_summary(ib)
            risk = compute_risk_snapshot(positions, account)
            insert_risk_snapshot(conn, risk)
            print(f"  ✓ Risk snapshot saved (NAV: ${risk['nav']:,.0f})")

        # Step 4: Generate dashboard
        print("\n[4/4] Generating dashboard...")
        positions_df = get_positions(conn)
        alerts = check_risk_alerts(risk, positions_df)
        dashboard = generate_dashboard(risk, positions_df, alerts)

        # Print to terminal
        print("\n" + dashboard)

        # Save to file
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        today = datetime.now().strftime("%Y-%m-%d")
        report_path = REPORTS_DIR / f"daily_{today}.md"
        report_path.write_text(dashboard)
        print(f"\nSaved to {report_path}")

        duration = time.time() - start
        log_pipeline_run(conn, "daily_refresh", "completed", duration_sec=round(duration, 1))
        print(f"\n✓ Daily refresh complete in {duration:.1f}s")

    except Exception as e:
        duration = time.time() - start
        log_pipeline_run(conn, "daily_refresh", "failed", details=str(e), duration_sec=round(duration, 1))
        print(f"\n✗ Pipeline failed: {e}")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    run()

