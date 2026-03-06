"""
Alpha Pod — Database Queries
Reusable read functions. All return lists of dicts or single values.
"""
import sqlite3
import pandas as pd
from db.schema import get_connection


def _rows_to_dicts(cursor: sqlite3.Cursor) -> list[dict]:
    """Convert cursor results to list of dicts."""
    return [dict(row) for row in cursor.fetchall()]


# ── Universe ───────────────────────────────────────────

def get_universe(conn: sqlite3.Connection, status: str = None) -> pd.DataFrame:
    """Get universe, optionally filtered by status."""
    if status:
        df = pd.read_sql("SELECT * FROM universe WHERE status = ?", conn, params=[status])
    else:
        df = pd.read_sql("SELECT * FROM universe", conn)
    return df


def get_tickers(conn: sqlite3.Connection, status: str = None) -> list[str]:
    """Get list of tickers."""
    df = get_universe(conn, status)
    return df["ticker"].tolist()


# ── Financials ─────────────────────────────────────────

def get_financials(conn: sqlite3.Connection, ticker: str,
                   periods: int = 8) -> pd.DataFrame:
    """Get most recent N periods of financials for a ticker."""
    return pd.read_sql("""
        SELECT * FROM financials
        WHERE ticker = ?
        ORDER BY period DESC
        LIMIT ?
    """, conn, params=[ticker, periods])


def get_latest_financials(conn: sqlite3.Connection, ticker: str) -> dict | None:
    """Get most recent period financials for a ticker."""
    cur = conn.execute("""
        SELECT * FROM financials
        WHERE ticker = ?
        ORDER BY period DESC
        LIMIT 1
    """, [ticker])
    row = cur.fetchone()
    return dict(row) if row else None


def get_roic_history(conn: sqlite3.Connection, ticker: str) -> list[dict]:
    """Get ROIC history for screening (is it consistently above threshold?)."""
    cur = conn.execute("""
        SELECT period, roic FROM financials
        WHERE ticker = ? AND roic IS NOT NULL
        ORDER BY period DESC
    """, [ticker])
    return _rows_to_dicts(cur)


# ── Prices ─────────────────────────────────────────────

def get_latest_price(conn: sqlite3.Connection, ticker: str) -> dict | None:
    """Get most recent price for a ticker."""
    cur = conn.execute("""
        SELECT * FROM prices
        WHERE ticker = ?
        ORDER BY date DESC
        LIMIT 1
    """, [ticker])
    row = cur.fetchone()
    return dict(row) if row else None


def get_price_history(conn: sqlite3.Connection, ticker: str,
                      days: int = 252) -> pd.DataFrame:
    """Get price history (default 1 year of trading days)."""
    return pd.read_sql("""
        SELECT * FROM prices
        WHERE ticker = ?
        ORDER BY date DESC
        LIMIT ?
    """, conn, params=[ticker, days])


# ── Valuations ─────────────────────────────────────────

def get_latest_valuation(conn: sqlite3.Connection, ticker: str) -> dict | None:
    """Get most recent valuation multiples."""
    cur = conn.execute("""
        SELECT * FROM valuations
        WHERE ticker = ?
        ORDER BY date DESC
        LIMIT 1
    """, [ticker])
    row = cur.fetchone()
    return dict(row) if row else None


# ── Estimates ──────────────────────────────────────────

def get_estimates(conn: sqlite3.Connection, ticker: str) -> pd.DataFrame:
    """Get all consensus estimates for a ticker."""
    return pd.read_sql("""
        SELECT * FROM estimates
        WHERE ticker = ?
        ORDER BY period, metric
    """, conn, params=[ticker])


def get_estimate_revisions(conn: sqlite3.Connection, ticker: str) -> list[dict]:
    """Get estimates with revision data (for screening)."""
    cur = conn.execute("""
        SELECT period, metric, consensus_mean, prior_mean_30d, revision_pct
        FROM estimates
        WHERE ticker = ? AND revision_pct IS NOT NULL
        ORDER BY period, metric
    """, [ticker])
    return _rows_to_dicts(cur)


# ── Portfolio & Risk ───────────────────────────────────

def get_positions(conn: sqlite3.Connection) -> pd.DataFrame:
    """Get all current positions."""
    return pd.read_sql("SELECT * FROM positions ORDER BY weight_pct DESC", conn)


def get_risk_snapshot(conn: sqlite3.Connection, date: str = None) -> dict | None:
    """Get risk snapshot for a date (default: most recent)."""
    if date:
        cur = conn.execute("SELECT * FROM risk_daily WHERE date = ?", [date])
    else:
        cur = conn.execute("SELECT * FROM risk_daily ORDER BY date DESC LIMIT 1")
    row = cur.fetchone()
    return dict(row) if row else None


def get_nav_history(conn: sqlite3.Connection, days: int = 252) -> pd.DataFrame:
    """Get NAV history for performance tracking."""
    return pd.read_sql("""
        SELECT date, nav, daily_pnl_pct, drawdown_from_hw
        FROM risk_daily
        ORDER BY date DESC
        LIMIT ?
    """, conn, params=[days])


# ── Screening Helpers ──────────────────────────────────

def get_screening_data(conn: sqlite3.Connection) -> pd.DataFrame:
    """
    Pull a wide table with latest financials, prices, and estimates
    joined together — the input to the screener.
    """
    return pd.read_sql("""
        SELECT
            u.ticker,
            u.company_name,
            u.sector,
            u.industry,
            u.market_cap_mm,
            u.status,
            f.revenue_mm,
            f.ebitda_mm,
            f.net_income_mm,
            f.roic,
            f.roe,
            f.gross_margin,
            f.ebitda_margin,
            f.debt_to_ebitda,
            f.fcf_mm,
            p.close AS last_price,
            p.volume AS last_volume,
            p.avg_volume_20d,
            v.pe_ttm,
            v.pe_fwd,
            v.ev_ebitda_ttm,
            v.pe_vs_5yr_avg
        FROM universe u
        LEFT JOIN (
            SELECT *, ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY period DESC) as rn
            FROM financials
        ) f ON u.ticker = f.ticker AND f.rn = 1
        LEFT JOIN (
            SELECT *, ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY date DESC) as rn
            FROM prices
        ) p ON u.ticker = p.ticker AND p.rn = 1
        LEFT JOIN (
            SELECT *, ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY date DESC) as rn
            FROM valuations
        ) v ON u.ticker = v.ticker AND v.rn = 1
    """, conn)


# ── Pipeline Log ───────────────────────────────────────

def get_last_pipeline_run(conn: sqlite3.Connection, pipeline: str) -> dict | None:
    """Check when a pipeline last ran successfully."""
    cur = conn.execute("""
        SELECT * FROM pipeline_log
        WHERE pipeline = ? AND status = 'completed'
        ORDER BY timestamp DESC
        LIMIT 1
    """, [pipeline])
    row = cur.fetchone()
    return dict(row) if row else None


def get_ciq_snapshot(conn: sqlite3.Connection, ticker: str, as_of_date: str = None) -> dict | None:
    """Get CIQ valuation snapshot for a ticker."""
    if as_of_date:
        cur = conn.execute(
            """
            SELECT * FROM ciq_valuation_snapshot
            WHERE ticker = ? AND as_of_date = ?
            LIMIT 1
            """,
            [ticker.upper(), as_of_date],
        )
    else:
        cur = conn.execute(
            """
            SELECT * FROM ciq_valuation_snapshot
            WHERE ticker = ?
            ORDER BY as_of_date DESC, run_id DESC
            LIMIT 1
            """,
            [ticker.upper()],
        )
    row = cur.fetchone()
    return dict(row) if row else None


def get_latest_ciq_as_of_date(conn: sqlite3.Connection) -> str | None:
    """Return most recent as_of_date in CIQ valuation snapshot."""
    cur = conn.execute("SELECT MAX(as_of_date) AS as_of_date FROM ciq_valuation_snapshot")
    row = cur.fetchone()
    return row["as_of_date"] if row and row["as_of_date"] else None


def get_ciq_metric_history(conn: sqlite3.Connection, ticker: str, metric_key: str, limit: int = 5) -> list[dict]:
    """Get metric history from CIQ long-form table (latest periods first)."""
    cur = conn.execute(
        """
        SELECT period_date, value_num, unit
        FROM ciq_long_form
        WHERE ticker = ? AND metric_key = ? AND period_date IS NOT NULL AND value_num IS NOT NULL
        ORDER BY period_date DESC
        LIMIT ?
        """,
        [ticker.upper(), metric_key, limit],
    )
    return _rows_to_dicts(cur)
