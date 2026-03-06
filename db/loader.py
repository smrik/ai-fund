"""
Alpha Pod — Database Loader
Insert/update functions for all tables. All operations are idempotent (upsert).
"""
import sqlite3
from datetime import datetime
from typing import Any

from db.schema import get_connection


def _now() -> str:
    return datetime.utcnow().isoformat() + "Z"


def upsert_universe(conn: sqlite3.Connection, rows: list[dict]):
    """Insert or update universe entries."""
    for row in rows:
        conn.execute("""
            INSERT INTO universe (ticker, company_name, ciq_id, sector, industry,
                                  market_cap_mm, country, status, added_date, notes)
            VALUES (:ticker, :company_name, :ciq_id, :sector, :industry,
                    :market_cap_mm, :country, :status, :added_date, :notes)
            ON CONFLICT(ticker) DO UPDATE SET
                company_name = excluded.company_name,
                ciq_id = excluded.ciq_id,
                sector = excluded.sector,
                industry = excluded.industry,
                market_cap_mm = excluded.market_cap_mm,
                notes = excluded.notes
        """, row)
    conn.commit()


def upsert_financials(conn: sqlite3.Connection, rows: list[dict]):
    """Insert or update financial data. Each row = one ticker-period."""
    for row in rows:
        row.setdefault("source", "ciq")
        row.setdefault("pulled_at", _now())
        conn.execute("""
            INSERT INTO financials (
                ticker, period, period_end_date, revenue_mm, gross_profit_mm,
                ebitda_mm, ebit_mm, net_income_mm, eps_diluted, fcf_mm,
                total_debt_mm, net_debt_mm, total_equity_mm, total_assets_mm,
                capex_mm, shares_out_mm, gross_margin, ebitda_margin, net_margin,
                roic, roe, debt_to_ebitda, source, pulled_at
            ) VALUES (
                :ticker, :period, :period_end_date, :revenue_mm, :gross_profit_mm,
                :ebitda_mm, :ebit_mm, :net_income_mm, :eps_diluted, :fcf_mm,
                :total_debt_mm, :net_debt_mm, :total_equity_mm, :total_assets_mm,
                :capex_mm, :shares_out_mm, :gross_margin, :ebitda_margin, :net_margin,
                :roic, :roe, :debt_to_ebitda, :source, :pulled_at
            )
            ON CONFLICT(ticker, period) DO UPDATE SET
                revenue_mm = excluded.revenue_mm,
                gross_profit_mm = excluded.gross_profit_mm,
                ebitda_mm = excluded.ebitda_mm,
                ebit_mm = excluded.ebit_mm,
                net_income_mm = excluded.net_income_mm,
                eps_diluted = excluded.eps_diluted,
                fcf_mm = excluded.fcf_mm,
                total_debt_mm = excluded.total_debt_mm,
                net_debt_mm = excluded.net_debt_mm,
                total_equity_mm = excluded.total_equity_mm,
                total_assets_mm = excluded.total_assets_mm,
                capex_mm = excluded.capex_mm,
                shares_out_mm = excluded.shares_out_mm,
                gross_margin = excluded.gross_margin,
                ebitda_margin = excluded.ebitda_margin,
                net_margin = excluded.net_margin,
                roic = excluded.roic,
                roe = excluded.roe,
                debt_to_ebitda = excluded.debt_to_ebitda,
                pulled_at = excluded.pulled_at
        """, row)
    conn.commit()


def upsert_prices(conn: sqlite3.Connection, rows: list[dict]):
    """Insert or update daily price data."""
    conn.executemany("""
        INSERT INTO prices (ticker, date, open, high, low, close, volume, avg_volume_20d)
        VALUES (:ticker, :date, :open, :high, :low, :close, :volume, :avg_volume_20d)
        ON CONFLICT(ticker, date) DO UPDATE SET
            open = excluded.open,
            high = excluded.high,
            low = excluded.low,
            close = excluded.close,
            volume = excluded.volume,
            avg_volume_20d = excluded.avg_volume_20d
    """, rows)
    conn.commit()


def upsert_estimates(conn: sqlite3.Connection, rows: list[dict]):
    """Insert or update consensus estimates."""
    for row in rows:
        row.setdefault("pulled_at", _now())
        conn.execute("""
            INSERT INTO estimates (
                ticker, period, metric, consensus_mean, consensus_high,
                consensus_low, num_analysts, prior_mean_30d, revision_pct, pulled_at
            ) VALUES (
                :ticker, :period, :metric, :consensus_mean, :consensus_high,
                :consensus_low, :num_analysts, :prior_mean_30d, :revision_pct, :pulled_at
            )
            ON CONFLICT(ticker, period, metric) DO UPDATE SET
                prior_mean_30d = estimates.consensus_mean,
                consensus_mean = excluded.consensus_mean,
                consensus_high = excluded.consensus_high,
                consensus_low = excluded.consensus_low,
                num_analysts = excluded.num_analysts,
                revision_pct = CASE
                    WHEN estimates.consensus_mean IS NOT NULL AND estimates.consensus_mean != 0
                    THEN (excluded.consensus_mean - estimates.consensus_mean) / ABS(estimates.consensus_mean)
                    ELSE NULL
                END,
                pulled_at = excluded.pulled_at
        """, row)
    conn.commit()


def upsert_positions(conn: sqlite3.Connection, rows: list[dict]):
    """Insert or update portfolio positions."""
    for row in rows:
        row.setdefault("updated_at", _now())
        conn.execute("""
            INSERT INTO positions (
                ticker, direction, shares, avg_cost, current_price,
                market_value, unrealized_pnl, pnl_pct, weight_pct,
                entry_date, thesis_link, updated_at
            ) VALUES (
                :ticker, :direction, :shares, :avg_cost, :current_price,
                :market_value, :unrealized_pnl, :pnl_pct, :weight_pct,
                :entry_date, :thesis_link, :updated_at
            )
            ON CONFLICT(ticker) DO UPDATE SET
                shares = excluded.shares,
                current_price = excluded.current_price,
                market_value = excluded.market_value,
                unrealized_pnl = excluded.unrealized_pnl,
                pnl_pct = excluded.pnl_pct,
                weight_pct = excluded.weight_pct,
                updated_at = excluded.updated_at
        """, row)
    conn.commit()


def insert_risk_snapshot(conn: sqlite3.Connection, snapshot: dict):
    """Insert daily risk snapshot."""
    conn.execute("""
        INSERT OR REPLACE INTO risk_daily (
            date, nav, gross_exposure, net_exposure, long_exposure,
            short_exposure, top_position_pct, sector_max_pct, sector_max_name,
            daily_pnl, daily_pnl_pct, drawdown_from_hw, margin_used_pct
        ) VALUES (
            :date, :nav, :gross_exposure, :net_exposure, :long_exposure,
            :short_exposure, :top_position_pct, :sector_max_pct, :sector_max_name,
            :daily_pnl, :daily_pnl_pct, :drawdown_from_hw, :margin_used_pct
        )
    """, snapshot)
    conn.commit()


def log_pipeline_run(conn: sqlite3.Connection, pipeline: str, status: str,
                     details: str = None, duration_sec: float = None):
    """Log a pipeline execution for audit trail."""
    conn.execute("""
        INSERT INTO pipeline_log (timestamp, pipeline, status, details, duration_sec)
        VALUES (?, ?, ?, ?, ?)
    """, (_now(), pipeline, status, details, duration_sec))
    conn.commit()
