"""
Portfolio Tracker — SQLite-backed manual position tracker.

No IBKR dependency. Positions entered manually; prices refreshed from yfinance.

CLI usage:
  python -m src.portfolio.tracker add IBM LONG 100 185.50 [--note "initial position"]
  python -m src.portfolio.tracker add IBM LONG 50  190.00   # adds to position
  python -m src.portfolio.tracker close IBM 100 195.00 [--note "partial exit"]
  python -m src.portfolio.tracker list
  python -m src.portfolio.tracker prices
  python -m src.portfolio.tracker risk
  python -m src.portfolio.tracker export
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import yfinance as yf

from config import ROOT_DIR, PORTFOLIO_SIZE_USD, STOP_LOSS_REVIEW_PCT, MAX_SINGLE_POSITION_PCT

DB_PATH = ROOT_DIR / "data" / "alpha_pod.db"
EXPORT_PATH = ROOT_DIR / "data" / "portfolio" / "positions.csv"

_POSITION_COLS = (
    "ticker", "direction", "shares", "avg_cost", "current_price",
    "market_value", "unrealized_pnl", "pnl_pct", "weight_pct",
    "entry_date", "thesis_link", "updated_at",
)


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _ensure_tables(conn: sqlite3.Connection) -> None:
    """Create tables used by the tracker if they don't exist."""
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS positions (
        ticker          TEXT PRIMARY KEY,
        direction       TEXT NOT NULL,
        shares          REAL NOT NULL DEFAULT 0,
        avg_cost        REAL,
        current_price   REAL,
        market_value    REAL,
        unrealized_pnl  REAL,
        pnl_pct         REAL,
        weight_pct      REAL,
        entry_date      TEXT,
        thesis_link     TEXT,
        updated_at      TEXT
    );

    CREATE TABLE IF NOT EXISTS position_history (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        ticker          TEXT NOT NULL,
        direction       TEXT NOT NULL,
        shares_closed   REAL NOT NULL,
        avg_cost        REAL NOT NULL,
        exit_price      REAL NOT NULL,
        realized_pnl    REAL,
        realized_pnl_pct REAL,
        entry_date      TEXT,
        exit_date       TEXT,
        note            TEXT,
        closed_at       TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS realized_pnl_log (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        date            TEXT NOT NULL,
        ticker          TEXT NOT NULL,
        realized_pnl    REAL NOT NULL,
        note            TEXT
    );
    """)
    conn.commit()


class PortfolioTracker:
    """
    Manual position tracker backed by SQLite.

    All amounts in USD. Shares can be fractional.
    NAV = PORTFOLIO_SIZE_USD + total unrealized P&L + cumulative realized P&L.
    """

    def __init__(self, db_path: Path | str | None = None):
        self._db = Path(db_path) if db_path else DB_PATH
        conn = self._conn()
        _ensure_tables(conn)
        conn.close()

    def _conn(self) -> sqlite3.Connection:
        self._db.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self._db))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    # ── Write operations ──────────────────────────────────────────────────────

    def add_position(
        self,
        ticker: str,
        direction: str,
        shares: float,
        cost_basis: float,
        entry_date: str | None = None,
        note: str | None = None,
    ) -> dict[str, Any]:
        """
        Add or increase a position.

        If the ticker already exists with the same direction, computes new
        weighted average cost and cumulates shares.

        If opposite direction exists, reduces that position (closing trade).
        """
        ticker = ticker.upper().strip()
        direction = direction.upper().strip()
        if direction not in ("LONG", "SHORT"):
            raise ValueError(f"direction must be LONG or SHORT, got {direction!r}")
        if shares <= 0:
            raise ValueError("shares must be > 0")
        if cost_basis <= 0:
            raise ValueError("cost_basis must be > 0")

        entry_date = entry_date or datetime.now().strftime("%Y-%m-%d")
        conn = self._conn()
        _ensure_tables(conn)

        existing = conn.execute(
            "SELECT ticker, direction, shares, avg_cost, entry_date FROM positions WHERE ticker = ?",
            (ticker,),
        ).fetchone()

        if existing is None:
            conn.execute(
                "INSERT INTO positions (ticker, direction, shares, avg_cost, entry_date, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (ticker, direction, shares, cost_basis, entry_date, _now()),
            )
            msg = f"Opened {direction} {shares:.0f} {ticker} @ ${cost_basis:.2f}"
        elif existing["direction"] == direction:
            # Add to existing position — weighted avg cost
            old_shares = float(existing["shares"])
            old_cost = float(existing["avg_cost"])
            new_shares = old_shares + shares
            new_avg = (old_shares * old_cost + shares * cost_basis) / new_shares
            conn.execute(
                "UPDATE positions SET shares = ?, avg_cost = ?, updated_at = ? WHERE ticker = ?",
                (new_shares, new_avg, _now(), ticker),
            )
            msg = f"Added {shares:.0f} {ticker} @ ${cost_basis:.2f}; new avg ${new_avg:.2f}, total {new_shares:.0f}"
        else:
            # Opposite direction — treat as a closing trade
            result = self._reduce_position(conn, ticker, shares, cost_basis, entry_date, note or "direction flip")
            conn.commit()
            conn.close()
            return result

        if note:
            conn.execute(
                "UPDATE positions SET thesis_link = ? WHERE ticker = ?",
                (note, ticker),
            )

        conn.commit()
        conn.close()
        return {"ticker": ticker, "action": "added", "message": msg}

    def close_position(
        self,
        ticker: str,
        shares_to_close: float,
        exit_price: float,
        exit_date: str | None = None,
        note: str | None = None,
    ) -> dict[str, Any]:
        """Close all or part of a position. Logs realized P&L."""
        ticker = ticker.upper().strip()
        exit_date = exit_date or datetime.now().strftime("%Y-%m-%d")

        conn = self._conn()
        _ensure_tables(conn)
        result = self._reduce_position(conn, ticker, shares_to_close, exit_price, exit_date, note)
        conn.commit()
        conn.close()
        return result

    def _reduce_position(
        self,
        conn: sqlite3.Connection,
        ticker: str,
        shares_to_close: float,
        exit_price: float,
        exit_date: str,
        note: str | None,
    ) -> dict[str, Any]:
        existing = conn.execute(
            "SELECT ticker, direction, shares, avg_cost, entry_date FROM positions WHERE ticker = ?",
            (ticker,),
        ).fetchone()
        if existing is None:
            return {"ticker": ticker, "action": "error", "message": f"No open position in {ticker}"}

        direction = existing["direction"]
        old_shares = float(existing["shares"])
        avg_cost = float(existing["avg_cost"])
        close_shares = min(shares_to_close, old_shares)

        if direction == "LONG":
            realized_pnl = close_shares * (exit_price - avg_cost)
        else:  # SHORT
            realized_pnl = close_shares * (avg_cost - exit_price)

        realized_pnl_pct = (realized_pnl / (close_shares * avg_cost)) if avg_cost > 0 else 0.0

        conn.execute(
            """INSERT INTO position_history
               (ticker, direction, shares_closed, avg_cost, exit_price, realized_pnl,
                realized_pnl_pct, entry_date, exit_date, note, closed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (ticker, direction, close_shares, avg_cost, exit_price, realized_pnl,
             realized_pnl_pct, existing["entry_date"], exit_date, note, _now()),
        )

        remaining = old_shares - close_shares
        if remaining <= 0:
            conn.execute("DELETE FROM positions WHERE ticker = ?", (ticker,))
            action = "closed"
        else:
            conn.execute(
                "UPDATE positions SET shares = ?, updated_at = ? WHERE ticker = ?",
                (remaining, _now(), ticker),
            )
            action = "partial_close"

        return {
            "ticker": ticker,
            "action": action,
            "shares_closed": close_shares,
            "exit_price": exit_price,
            "realized_pnl": round(realized_pnl, 2),
            "realized_pnl_pct": round(realized_pnl_pct * 100, 2),
            "message": f"Closed {close_shares:.0f} {ticker} @ ${exit_price:.2f} | Realized P&L: ${realized_pnl:+,.0f} ({realized_pnl_pct*100:+.1f}%)",
        }

    def update_prices(self) -> int:
        """Fetch current prices from yfinance and recompute P&L + weight_pct."""
        conn = self._conn()
        _ensure_tables(conn)
        rows = conn.execute("SELECT ticker, direction, shares, avg_cost FROM positions").fetchall()

        if not rows:
            conn.close()
            return 0

        tickers = [r["ticker"] for r in rows]
        try:
            prices_raw = yf.download(
                " ".join(tickers), period="1d", progress=False, auto_adjust=True
            )
            if hasattr(prices_raw, "columns") and isinstance(prices_raw.columns, pd.MultiIndex):
                close_series = prices_raw["Close"].iloc[-1]
            else:
                if "Close" in prices_raw and len(tickers) == 1:
                    # Single-ticker download: build a Series keyed by ticker
                    last_val = prices_raw["Close"].iloc[-1]
                    close_series = pd.Series({tickers[0]: float(last_val)})
                else:
                    close_series = pd.Series()
        except Exception:
            close_series = pd.Series()

        # Also fetch realized P&L total
        realized = conn.execute("SELECT COALESCE(SUM(realized_pnl), 0) FROM position_history").fetchone()[0] or 0.0

        updated = []
        total_market_value = 0.0
        for row in rows:
            ticker = row["ticker"]
            shares = float(row["shares"])
            avg_cost = float(row["avg_cost"])
            direction = row["direction"]

            # Get price: try multi-ticker format, then single ticker format
            price = None
            if ticker in close_series.index:
                price = float(close_series[ticker])
            elif len(tickers) == 1 and len(close_series) > 0:
                price = float(close_series.iloc[-1])

            if price is None or price <= 0:
                updated.append((None, None, None, None, _now(), ticker))
                continue

            if direction == "LONG":
                market_value = shares * price
                unrealized_pnl = shares * (price - avg_cost)
            else:  # SHORT
                market_value = shares * price  # market exposure (gross)
                unrealized_pnl = shares * (avg_cost - price)

            pnl_pct = unrealized_pnl / (shares * avg_cost) if avg_cost > 0 else 0.0
            total_market_value += market_value
            updated.append((price, market_value, unrealized_pnl, pnl_pct, _now(), ticker))

        # Compute NAV and weight_pct
        total_unrealized = sum(r[2] for r in updated if r[2] is not None)
        nav = PORTFOLIO_SIZE_USD + total_unrealized + realized

        for i, row in enumerate(rows):
            ticker = row["ticker"]
            entry = updated[i]
            price, mkt_val, unreal, pnl_pct, ts, _ = entry
            weight = (mkt_val / nav * 100) if (mkt_val is not None and nav > 0) else None
            conn.execute(
                """UPDATE positions
                   SET current_price=?, market_value=?, unrealized_pnl=?,
                       pnl_pct=?, weight_pct=?, updated_at=?
                   WHERE ticker=?""",
                (price, mkt_val, unreal, pnl_pct, weight, ts, ticker),
            )

        conn.commit()
        conn.close()
        return len(rows)

    # ── Read operations ───────────────────────────────────────────────────────

    def get_positions(self) -> pd.DataFrame:
        conn = self._conn()
        _ensure_tables(conn)
        df = pd.read_sql("SELECT * FROM positions ORDER BY weight_pct DESC NULLS LAST", conn)
        conn.close()
        return df

    def get_position_history(self) -> pd.DataFrame:
        conn = self._conn()
        _ensure_tables(conn)
        df = pd.read_sql("SELECT * FROM position_history ORDER BY closed_at DESC", conn)
        conn.close()
        return df

    def get_risk_metrics(self) -> dict[str, Any]:
        """Compute portfolio-level risk: gross/net exposure, stop-loss alerts."""
        df = self.get_positions()
        if df.empty:
            return {
                "nav": PORTFOLIO_SIZE_USD,
                "long_exposure_usd": 0.0,
                "short_exposure_usd": 0.0,
                "gross_exposure_pct": 0.0,
                "net_exposure_pct": 0.0,
                "top_position_pct": 0.0,
                "top_position_ticker": None,
                "position_count": 0,
                "alerts": [],
            }

        conn = self._conn()
        realized = conn.execute(
            "SELECT COALESCE(SUM(realized_pnl), 0) FROM position_history"
        ).fetchone()[0] or 0.0
        conn.close()

        longs = df[df["direction"] == "LONG"]
        shorts = df[df["direction"] == "SHORT"]

        long_usd = float(longs["market_value"].fillna(0).sum())
        short_usd = float(shorts["market_value"].fillna(0).sum())
        total_unrealized = float(df["unrealized_pnl"].fillna(0).sum())
        nav = PORTFOLIO_SIZE_USD + total_unrealized + realized

        gross_pct = ((long_usd + short_usd) / nav * 100) if nav > 0 else 0.0
        net_pct = ((long_usd - short_usd) / nav * 100) if nav > 0 else 0.0

        top_row = df.nlargest(1, "weight_pct") if "weight_pct" in df.columns else df.head(1)
        top_pct = float(top_row["weight_pct"].iloc[0]) if not top_row.empty else 0.0
        top_ticker = str(top_row["ticker"].iloc[0]) if not top_row.empty else None

        alerts: list[str] = []
        for _, row in df.iterrows():
            pnl_pct = row.get("pnl_pct")
            if pnl_pct is not None and not pd.isna(pnl_pct):
                pnl_pct_float = float(pnl_pct)
                if pnl_pct_float * 100 <= STOP_LOSS_REVIEW_PCT:
                    alerts.append(
                        f"STOP-LOSS {row['ticker']} at {pnl_pct_float*100:+.1f}% "
                        f"(limit {STOP_LOSS_REVIEW_PCT:.0f}%)"
                    )
        if top_pct > MAX_SINGLE_POSITION_PCT:
            alerts.append(
                f"CONCENTRATION {top_ticker} at {top_pct:.1f}% "
                f"(limit {MAX_SINGLE_POSITION_PCT:.0f}%)"
            )

        return {
            "nav": round(nav, 2),
            "realized_pnl": round(realized, 2),
            "unrealized_pnl": round(total_unrealized, 2),
            "long_exposure_usd": round(long_usd, 2),
            "short_exposure_usd": round(short_usd, 2),
            "gross_exposure_pct": round(gross_pct, 1),
            "net_exposure_pct": round(net_pct, 1),
            "top_position_pct": round(top_pct, 1),
            "top_position_ticker": top_ticker,
            "position_count": len(df),
            "alerts": alerts,
        }

    def export_csv(self, path: Path | None = None) -> Path:
        out = Path(path) if path else EXPORT_PATH
        out.parent.mkdir(parents=True, exist_ok=True)
        df = self.get_positions()
        df.to_csv(out, index=False)
        return out

    def print_brief(self) -> None:
        """Print a formatted portfolio snapshot to stdout."""
        self.update_prices()
        df = self.get_positions()
        risk = self.get_risk_metrics()

        today = datetime.now().strftime("%Y-%m-%d")
        print()
        print("═" * 60)
        print(f"PORTFOLIO — {today}")
        print("═" * 60)
        print(f"  NAV:            ${risk['nav']:>12,.0f}")
        print(f"  Unrealized P&L: ${risk['unrealized_pnl']:>+12,.0f}")
        print(f"  Realized P&L:   ${risk['realized_pnl']:>+12,.0f}")
        print(f"  Gross:          {risk['gross_exposure_pct']:>5.1f}%   Net: {risk['net_exposure_pct']:>+5.1f}%")
        print(f"  Positions:      {risk['position_count']}")
        print()

        if df.empty:
            print("  No open positions.")
        else:
            print(f"  {'Ticker':<8} {'Dir':<6} {'Shares':>8} {'Avg Cost':>9} {'Price':>9} {'Wt%':>5} {'P&L%':>7} {'Unreal $':>11}")
            print(f"  {'-'*8} {'-'*6} {'-'*8} {'-'*9} {'-'*9} {'-'*5} {'-'*7} {'-'*11}")
            for _, row in df.iterrows():
                price = row.get("current_price") or 0.0
                pnl_pct = (row.get("pnl_pct") or 0.0) * 100
                unreal = row.get("unrealized_pnl") or 0.0
                wt = row.get("weight_pct") or 0.0
                print(
                    f"  {row['ticker']:<8} {row['direction']:<6} "
                    f"{row['shares']:>8.0f} "
                    f"${row['avg_cost']:>8.2f} "
                    f"${price:>8.2f} "
                    f"{wt:>5.1f}% "
                    f"{pnl_pct:>+6.1f}% "
                    f"${unreal:>+10,.0f}"
                )

        if risk["alerts"]:
            print()
            print("  ALERTS:")
            for alert in risk["alerts"]:
                print(f"    ⚠  {alert}")
        else:
            print()
            print("  ✓ No alerts")

        print("═" * 60)


# ── CLI ───────────────────────────────────────────────────────────────────────

def _cli():
    import argparse

    parser = argparse.ArgumentParser(description="Alpha Pod Portfolio Tracker")
    sub = parser.add_subparsers(dest="cmd")

    # add
    p_add = sub.add_parser("add", help="Add or increase a position")
    p_add.add_argument("ticker")
    p_add.add_argument("direction", choices=["LONG", "SHORT", "long", "short"])
    p_add.add_argument("shares", type=float)
    p_add.add_argument("cost", type=float, help="Cost basis per share")
    p_add.add_argument("--date", help="Entry date YYYY-MM-DD")
    p_add.add_argument("--note", help="Thesis note")

    # close
    p_close = sub.add_parser("close", help="Close all or part of a position")
    p_close.add_argument("ticker")
    p_close.add_argument("shares", type=float)
    p_close.add_argument("price", type=float, help="Exit price")
    p_close.add_argument("--date", help="Exit date YYYY-MM-DD")
    p_close.add_argument("--note", help="Exit rationale")

    # list / prices / risk / export
    sub.add_parser("list", help="List open positions")
    sub.add_parser("prices", help="Refresh prices from yfinance")
    sub.add_parser("risk", help="Show risk metrics")
    sub.add_parser("export", help="Export positions CSV")
    sub.add_parser("history", help="Show closed position history")

    args = parser.parse_args()
    tracker = PortfolioTracker()

    if args.cmd == "add":
        result = tracker.add_position(
            args.ticker, args.direction.upper(), args.shares,
            args.cost, args.date, args.note,
        )
        print(result["message"])

    elif args.cmd == "close":
        result = tracker.close_position(
            args.ticker, args.shares, args.price, args.date, args.note,
        )
        print(result["message"])

    elif args.cmd == "list":
        tracker.update_prices()
        tracker.print_brief()

    elif args.cmd == "prices":
        n = tracker.update_prices()
        print(f"✓ Updated prices for {n} positions")

    elif args.cmd == "risk":
        tracker.update_prices()
        risk = tracker.get_risk_metrics()
        print(f"NAV:          ${risk['nav']:,.0f}")
        print(f"Gross:        {risk['gross_exposure_pct']:.1f}%")
        print(f"Net:          {risk['net_exposure_pct']:+.1f}%")
        print(f"Top position: {risk['top_position_ticker']} @ {risk['top_position_pct']:.1f}%")
        if risk["alerts"]:
            for a in risk["alerts"]:
                print(f"⚠  {a}")

    elif args.cmd == "export":
        path = tracker.export_csv()
        print(f"✓ Exported to {path}")

    elif args.cmd == "history":
        df = tracker.get_position_history()
        if df.empty:
            print("No closed positions.")
        else:
            total_realized = df["realized_pnl"].sum()
            print(df[["ticker", "direction", "shares_closed", "avg_cost", "exit_price",
                        "realized_pnl", "realized_pnl_pct", "exit_date"]].to_string(index=False))
            print(f"\nTotal realized P&L: ${total_realized:+,.0f}")

    else:
        parser.print_help()


if __name__ == "__main__":
    _cli()
