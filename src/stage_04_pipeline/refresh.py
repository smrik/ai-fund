"""
Alpha Pod — Data Freshness Orchestrator
Unified command to refresh market data, estimates, and macro in one shot.

Usage:
    python -m src.stage_04_pipeline.refresh [--tickers AAPL,MSFT] [--macro-only]
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from config import DB_PATH
from db.schema import create_tables


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _log(conn: sqlite3.Connection, pipeline: str, status: str, details: str = "", duration_sec: float = 0.0) -> None:
    conn.execute(
        "INSERT INTO pipeline_log (timestamp, pipeline, status, details, duration_sec) VALUES (?, ?, ?, ?, ?)",
        [_now(), pipeline, status, details, duration_sec],
    )
    conn.commit()


def _get_universe_tickers() -> list[str]:
    """Load tickers from universe.csv or the universe DB table."""
    universe_csv = Path("data/universe.csv")
    if universe_csv.exists():
        import csv
        with open(universe_csv, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            return [row["ticker"].strip().upper() for row in reader if row.get("ticker")]
    try:
        conn = sqlite3.connect(str(DB_PATH))
        rows = conn.execute("SELECT ticker FROM universe WHERE status != 'dropped'").fetchall()
        conn.close()
        return [r[0] for r in rows]
    except Exception:
        return []


def refresh_market_data(universe: list[str], *, verbose: bool = True) -> dict:
    """
    Refresh market data snapshot + historical financials for each ticker.
    Results are cached in market_data_cache (TTL 4h) — subsequent reads will be instant.
    """
    from src.stage_00_data.market_data import get_market_data, get_historical_financials, _TICKER_CACHE

    results: dict[str, str] = {}
    for ticker in universe:
        try:
            # Force fresh fetch (bypass cache) so this refresh actually hits yfinance
            get_market_data(ticker, use_cache=False)
            get_historical_financials(ticker, use_cache=False)
            results[ticker] = "ok"
            if verbose:
                print(f"  ✓ {ticker} market data refreshed")
        except Exception as e:
            results[ticker] = f"error: {e}"
            if verbose:
                print(f"  ✗ {ticker} market data error: {e}")

    # Clear in-process cache so next callers get the DB-cached (fresh) version
    _TICKER_CACHE.clear()
    return results


def refresh_estimates(universe: list[str], *, verbose: bool = True) -> dict:
    """Snapshot analyst estimates for each ticker into estimate_history table."""
    try:
        from src.stage_00_data.estimate_tracker import snapshot_estimates
    except ImportError:
        if verbose:
            print("  ! estimate_tracker not available — skipping")
        return {}

    results: dict[str, str] = {}
    for ticker in universe:
        try:
            snapshot_estimates(ticker)
            results[ticker] = "ok"
            if verbose:
                print(f"  ✓ {ticker} estimates snapshotted")
        except Exception as e:
            results[ticker] = f"error: {e}"
            if verbose:
                print(f"  ✗ {ticker} estimates error: {e}")
    return results


def refresh_macro(*, verbose: bool = True) -> dict:
    """Refresh FRED macro snapshot (requires FRED_API_KEY)."""
    try:
        from src.stage_00_data.fred_client import get_macro_snapshot
    except ImportError:
        if verbose:
            print("  ! fred_client not available — skipping macro")
        return {"status": "skipped"}

    try:
        snapshot = get_macro_snapshot()
        if verbose:
            print(f"  ✓ Macro snapshot refreshed ({len(snapshot)} series)")
        return {"status": "ok", "series_count": len(snapshot)}
    except Exception as e:
        if verbose:
            print(f"  ✗ Macro refresh error: {e}")
        return {"status": f"error: {e}"}


def refresh_all(universe: list[str] | None = None, *, verbose: bool = True) -> dict:
    """
    Run all refresh tasks: market data, estimates, macro.
    Logs a summary record to pipeline_log.
    """
    import time

    if universe is None:
        universe = _get_universe_tickers()
    if not universe:
        if verbose:
            print("No universe defined. Pass --tickers or create data/universe.csv")
        return {"status": "no_universe"}

    conn = sqlite3.connect(str(DB_PATH))
    create_tables(conn)

    t0 = time.time()
    if verbose:
        print(f"\n── Market Data ({len(universe)} tickers) ──────────────────────────")
    md_results = refresh_market_data(universe, verbose=verbose)

    if verbose:
        print(f"\n── Estimates ({len(universe)} tickers) ──────────────────────────")
    est_results = refresh_estimates(universe, verbose=verbose)

    if verbose:
        print(f"\n── Macro ────────────────────────────────────────────────────────")
    macro_result = refresh_macro(verbose=verbose)

    duration = round(time.time() - t0, 1)
    md_ok = sum(1 for v in md_results.values() if v == "ok")
    est_ok = sum(1 for v in est_results.values() if v == "ok")

    summary = {
        "status": "ok",
        "universe_count": len(universe),
        "market_data_ok": md_ok,
        "estimates_ok": est_ok,
        "macro": macro_result.get("status"),
        "duration_sec": duration,
    }
    _log(conn, "refresh_all", "ok",
         f"md:{md_ok}/{len(universe)} est:{est_ok}/{len(universe)} macro:{macro_result.get('status')}",
         duration)
    conn.close()

    if verbose:
        print(f"\n✓ Refresh complete in {duration}s — market_data:{md_ok}/{len(universe)} "
              f"estimates:{est_ok}/{len(universe)} macro:{macro_result.get('status')}")
    return summary


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Alpha Pod data refresh orchestrator")
    parser.add_argument("--tickers", type=str, default=None,
                        help="Comma-separated list of tickers to refresh (default: full universe)")
    parser.add_argument("--macro-only", action="store_true",
                        help="Only refresh macro data (skip per-ticker market data + estimates)")
    args = parser.parse_args(argv)

    universe: list[str] | None = None
    if args.tickers:
        universe = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]

    if args.macro_only:
        refresh_macro(verbose=True)
    else:
        refresh_all(universe, verbose=True)


if __name__ == "__main__":
    main()
