"""Analyst estimate revision tracker — snapshots and computes revision signals."""

import json
import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import yfinance as yf

from db.schema import get_connection

logger = logging.getLogger(__name__)


@dataclass
class RevisionSignals:
    ticker: str
    revision_breadth_30d: float | None  # (up - down) / total estimates
    eps_revision_30d_pct: float | None  # % change in FY1 EPS consensus over 30d
    revenue_revision_30d_pct: float | None  # % change in FY1 revenue consensus over 30d
    eps_revision_90d_pct: float | None
    revenue_revision_90d_pct: float | None
    estimate_dispersion: float | None  # std/mean of analyst EPS estimates
    revision_momentum: str  # "strong_positive"|"positive"|"neutral"|"negative"|"strong_negative"|"unavailable"
    num_analysts: int | None
    as_of_date: str
    available: bool
    error: str | None


def _ensure_estimate_history_table(conn: sqlite3.Connection) -> None:
    """Create estimate_history table if it does not yet exist."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS estimate_history (
            ticker          TEXT NOT NULL,
            snapshot_date   TEXT NOT NULL,
            fy1_eps         REAL,
            fy2_eps         REAL,
            fy1_revenue     REAL,
            num_analysts    INTEGER,
            eps_high        REAL,
            eps_low         REAL,
            stored_at       TEXT,
            PRIMARY KEY (ticker, snapshot_date)
        )
    """)
    conn.commit()


def snapshot_estimates(ticker: str) -> dict:
    """
    Fetch current analyst estimates for ticker via yfinance and store to SQLite.

    Returns a dict with keys: ticker, snapshot_date, fy1_eps, fy2_eps,
    fy1_revenue, num_analysts, eps_high, eps_low, available, error.
    Never raises.
    """
    today = datetime.now(timezone.utc).date().isoformat()
    result: dict = {
        "ticker": ticker,
        "snapshot_date": today,
        "fy1_eps": None,
        "fy2_eps": None,
        "fy1_revenue": None,
        "num_analysts": None,
        "eps_high": None,
        "eps_low": None,
        "available": False,
        "error": None,
    }

    try:
        t = yf.Ticker(ticker)

        # ── EPS estimates ──────────────────────────────────────────────────────
        fy1_eps: float | None = None
        fy2_eps: float | None = None
        eps_high: float | None = None
        eps_low: float | None = None
        num_analysts: int | None = None

        try:
            ee = t.earnings_estimate  # DataFrame
            if ee is not None and not ee.empty:
                cols = list(ee.columns)
                # Prefer "+1y" column; fall back to last available
                if "+1y" in cols:
                    fy1_eps = _safe_float(ee["+1y"].get("avg"))
                    eps_high = _safe_float(ee["+1y"].get("high"))
                    eps_low = _safe_float(ee["+1y"].get("low"))
                    num_analysts = _safe_int(ee["+1y"].get("numberOfAnalysts"))
                if "+2y" in cols:
                    fy2_eps = _safe_float(ee["+2y"].get("avg"))
        except Exception as exc:
            logger.debug("earnings_estimate fetch failed for %s: %s", ticker, exc)

        # ── Revenue estimates ──────────────────────────────────────────────────
        fy1_revenue: float | None = None
        try:
            re = t.revenue_estimate  # DataFrame
            if re is not None and not re.empty:
                cols = list(re.columns)
                if "+1y" in cols:
                    raw_rev = _safe_float(re["+1y"].get("avg"))
                    if raw_rev is not None:
                        # Convert to millions if value looks like raw dollars
                        fy1_revenue = raw_rev / 1e6 if raw_rev > 1e7 else raw_rev
        except Exception as exc:
            logger.debug("revenue_estimate fetch failed for %s: %s", ticker, exc)

        # ── Fall back to info for analyst count ────────────────────────────────
        if num_analysts is None:
            try:
                info = t.info or {}
                num_analysts = _safe_int(info.get("numberOfAnalystOpinions"))
            except Exception:
                pass

        result.update(
            {
                "fy1_eps": fy1_eps,
                "fy2_eps": fy2_eps,
                "fy1_revenue": fy1_revenue,
                "num_analysts": num_analysts,
                "eps_high": eps_high,
                "eps_low": eps_low,
                "available": any(
                    v is not None for v in [fy1_eps, fy1_revenue]
                ),
            }
        )

        # ── Persist to SQLite ──────────────────────────────────────────────────
        conn = get_connection()
        try:
            _ensure_estimate_history_table(conn)
            conn.execute(
                """
                INSERT OR REPLACE INTO estimate_history
                    (ticker, snapshot_date, fy1_eps, fy2_eps, fy1_revenue,
                     num_analysts, eps_high, eps_low, stored_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ticker,
                    today,
                    fy1_eps,
                    fy2_eps,
                    fy1_revenue,
                    num_analysts,
                    eps_high,
                    eps_low,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            conn.commit()
        finally:
            conn.close()

    except Exception as exc:
        result["error"] = str(exc)
        logger.warning("snapshot_estimates failed for %s: %s", ticker, exc)

    return result


def get_revision_signals(
    ticker: str, lookback_days: int = 90
) -> RevisionSignals:
    """
    Compute analyst estimate revision signals for ticker from historical snapshots.

    Queries estimate_history for the past lookback_days, then calculates
    30-day and full-lookback revision percentages plus dispersion and momentum.
    Never raises.
    """
    today = datetime.now(timezone.utc).date()
    as_of_date = today.isoformat()
    _unavailable = RevisionSignals(
        ticker=ticker,
        revision_breadth_30d=None,
        eps_revision_30d_pct=None,
        revenue_revision_30d_pct=None,
        eps_revision_90d_pct=None,
        revenue_revision_90d_pct=None,
        estimate_dispersion=None,
        revision_momentum="unavailable",
        num_analysts=None,
        as_of_date=as_of_date,
        available=False,
        error=None,
    )

    try:
        cutoff = (today - timedelta(days=lookback_days)).isoformat()

        conn = get_connection()
        try:
            _ensure_estimate_history_table(conn)
            rows = conn.execute(
                """
                SELECT snapshot_date, fy1_eps, fy1_revenue, eps_high, eps_low,
                       num_analysts
                FROM   estimate_history
                WHERE  ticker = ?
                  AND  snapshot_date >= ?
                ORDER BY snapshot_date DESC
                """,
                (ticker, cutoff),
            ).fetchall()
        finally:
            conn.close()

        if len(rows) < 2:
            return _unavailable

        # Most-recent snapshot
        latest = rows[0]
        fy1_eps_latest = latest["fy1_eps"]
        fy1_rev_latest = latest["fy1_revenue"]
        num_analysts = latest["num_analysts"]
        eps_high = latest["eps_high"]
        eps_low = latest["eps_low"]

        # Oldest snapshot in lookback window (90d)
        oldest = rows[-1]
        fy1_eps_oldest = oldest["fy1_eps"]
        fy1_rev_oldest = oldest["fy1_revenue"]

        # Find nearest snapshot to 30d ago
        cutoff_30d = (today - timedelta(days=30)).isoformat()
        row_30d = None
        for r in reversed(rows):  # rows are DESC — reversed = oldest first
            if r["snapshot_date"] <= cutoff_30d:
                row_30d = r
                break
        if row_30d is None:
            # Fall back to oldest available if nothing is >=30d old
            row_30d = rows[-1] if len(rows) >= 2 else None

        fy1_eps_30d = row_30d["fy1_eps"] if row_30d else None
        fy1_rev_30d = row_30d["fy1_revenue"] if row_30d else None

        # ── Revision pct helpers ───────────────────────────────────────────────
        eps_revision_30d = _revision_pct(fy1_eps_latest, fy1_eps_30d)
        rev_revision_30d = _revision_pct(fy1_rev_latest, fy1_rev_30d)
        eps_revision_90d = _revision_pct(fy1_eps_latest, fy1_eps_oldest)
        rev_revision_90d = _revision_pct(fy1_rev_latest, fy1_rev_oldest)

        # ── Estimate dispersion ────────────────────────────────────────────────
        estimate_dispersion: float | None = None
        if (
            eps_high is not None
            and eps_low is not None
            and fy1_eps_latest is not None
            and abs(fy1_eps_latest) > 1e-9
        ):
            estimate_dispersion = (eps_high - eps_low) / abs(fy1_eps_latest)

        # ── Revision momentum ──────────────────────────────────────────────────
        revision_momentum = _classify_momentum(eps_revision_30d)

        return RevisionSignals(
            ticker=ticker,
            revision_breadth_30d=None,  # requires count data not stored
            eps_revision_30d_pct=eps_revision_30d,
            revenue_revision_30d_pct=rev_revision_30d,
            eps_revision_90d_pct=eps_revision_90d,
            revenue_revision_90d_pct=rev_revision_90d,
            estimate_dispersion=estimate_dispersion,
            revision_momentum=revision_momentum,
            num_analysts=num_analysts,
            as_of_date=as_of_date,
            available=True,
            error=None,
        )

    except Exception as exc:
        logger.warning("get_revision_signals failed for %s: %s", ticker, exc)
        err = _unavailable
        err.error = str(exc)
        return err


def run_estimate_snapshot_job(tickers: list[str]) -> dict:
    """
    Run snapshot_estimates for each ticker in the list.

    Returns:
        {
            "completed": int,
            "failed": int,
            "errors": {ticker: error_str, ...},
        }
    """
    completed = 0
    failed = 0
    errors: dict[str, str] = {}

    for ticker in tickers:
        try:
            result = snapshot_estimates(ticker)
            if result.get("error"):
                failed += 1
                errors[ticker] = result["error"]
            else:
                completed += 1
        except Exception as exc:
            failed += 1
            errors[ticker] = str(exc)
            logger.warning("Snapshot job failed for %s: %s", ticker, exc)

    return {"completed": completed, "failed": failed, "errors": errors}


# ── Internal helpers ───────────────────────────────────────────────────────────

def _safe_float(value) -> float | None:
    """Convert value to float, returning None on failure."""
    if value is None:
        return None
    try:
        f = float(value)
        import math
        return None if math.isnan(f) or math.isinf(f) else f
    except (TypeError, ValueError):
        return None


def _safe_int(value) -> int | None:
    """Convert value to int, returning None on failure."""
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _revision_pct(current: float | None, prior: float | None) -> float | None:
    """
    Compute % change from prior to current only when signs are consistent
    (avoids misleading sign flips from negative to positive EPS).
    Returns None if data is unavailable or signs differ.
    """
    if current is None or prior is None:
        return None
    if abs(prior) < 1e-9:
        return None
    if (current >= 0) != (prior >= 0):
        # Sign flip — not a meaningful revision signal
        return None
    return (current - prior) / abs(prior)


def _classify_momentum(eps_30d_pct: float | None) -> str:
    """Map 30-day EPS revision % to a momentum label."""
    if eps_30d_pct is None:
        return "unavailable"
    if eps_30d_pct > 0.05:
        return "strong_positive"
    if eps_30d_pct > 0.01:
        return "positive"
    if eps_30d_pct >= -0.01:
        return "neutral"
    if eps_30d_pct >= -0.05:
        return "negative"
    return "strong_negative"
