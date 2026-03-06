"""
Alpha Pod — Database Schema
Creates all tables. Safe to run multiple times (IF NOT EXISTS).
"""
import sqlite3
from config.settings import DB_PATH, DATA_DIR


def get_connection() -> sqlite3.Connection:
    """Get a database connection with row factory enabled."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")  # Better concurrent read performance
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def create_tables(conn: sqlite3.Connection | None = None):
    """Create all tables. Idempotent — safe to call repeatedly."""
    close_after = False
    if conn is None:
        conn = get_connection()
        close_after = True

    cursor = conn.cursor()

    cursor.executescript("""

    -- Master universe
    CREATE TABLE IF NOT EXISTS universe (
        ticker          TEXT PRIMARY KEY,
        company_name    TEXT NOT NULL,
        ciq_id          TEXT,
        sector          TEXT,
        industry        TEXT,
        market_cap_mm   REAL,
        country         TEXT DEFAULT 'US',
        status          TEXT DEFAULT 'watchlist',
        added_date      TEXT,
        notes           TEXT
    );

    -- Quarterly/annual financials
    CREATE TABLE IF NOT EXISTS financials (
        ticker          TEXT NOT NULL,
        period          TEXT NOT NULL,
        period_end_date TEXT,
        revenue_mm      REAL,
        gross_profit_mm REAL,
        ebitda_mm       REAL,
        ebit_mm         REAL,
        net_income_mm   REAL,
        eps_diluted     REAL,
        fcf_mm          REAL,
        total_debt_mm   REAL,
        net_debt_mm     REAL,
        total_equity_mm REAL,
        total_assets_mm REAL,
        capex_mm        REAL,
        shares_out_mm   REAL,
        gross_margin    REAL,
        ebitda_margin   REAL,
        net_margin      REAL,
        roic            REAL,
        roe             REAL,
        debt_to_ebitda  REAL,
        source          TEXT DEFAULT 'ciq',
        pulled_at       TEXT,
        PRIMARY KEY (ticker, period)
    );

    -- Daily prices
    CREATE TABLE IF NOT EXISTS prices (
        ticker          TEXT NOT NULL,
        date            TEXT NOT NULL,
        open            REAL,
        high            REAL,
        low             REAL,
        close           REAL,
        volume          INTEGER,
        avg_volume_20d  REAL,
        PRIMARY KEY (ticker, date)
    );

    -- Valuation multiples
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
    );

    -- Consensus estimates
    CREATE TABLE IF NOT EXISTS estimates (
        ticker          TEXT NOT NULL,
        period          TEXT NOT NULL,
        metric          TEXT NOT NULL,
        consensus_mean  REAL,
        consensus_high  REAL,
        consensus_low   REAL,
        num_analysts    INTEGER,
        prior_mean_30d  REAL,
        revision_pct    REAL,
        pulled_at       TEXT,
        PRIMARY KEY (ticker, period, metric)
    );

    -- Screening results
    CREATE TABLE IF NOT EXISTS screen_results (
        screen_date     TEXT NOT NULL,
        screen_type     TEXT NOT NULL,
        ticker          TEXT NOT NULL,
        score           REAL,
        passing_criteria TEXT,
        failing_criteria TEXT,
        PRIMARY KEY (screen_date, screen_type, ticker)
    );

    -- Insider trades
    CREATE TABLE IF NOT EXISTS insider_trades (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        ticker          TEXT NOT NULL,
        trade_date      TEXT NOT NULL,
        insider_name    TEXT,
        title           TEXT,
        trade_type      TEXT,
        shares          INTEGER,
        price           REAL,
        value_usd       REAL,
        source          TEXT DEFAULT 'ciq'
    );

    -- Portfolio positions
    CREATE TABLE IF NOT EXISTS positions (
        ticker          TEXT PRIMARY KEY,
        direction       TEXT NOT NULL,
        shares          INTEGER,
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

    -- Daily risk snapshot
    CREATE TABLE IF NOT EXISTS risk_daily (
        date            TEXT PRIMARY KEY,
        nav             REAL,
        gross_exposure  REAL,
        net_exposure    REAL,
        long_exposure   REAL,
        short_exposure  REAL,
        top_position_pct REAL,
        sector_max_pct  REAL,
        sector_max_name TEXT,
        daily_pnl       REAL,
        daily_pnl_pct   REAL,
        drawdown_from_hw REAL,
        margin_used_pct REAL
    );

    -- Pipeline audit log
    CREATE TABLE IF NOT EXISTS pipeline_log (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp       TEXT NOT NULL,
        pipeline        TEXT NOT NULL,
        status          TEXT NOT NULL,
        details         TEXT,
        duration_sec    REAL
    );

    -- Weekly sector/industry benchmarks (IndustryAgent cache)
    CREATE TABLE IF NOT EXISTS industry_benchmarks (
        sector                  TEXT NOT NULL,
        industry                TEXT NOT NULL,
        week_key                TEXT NOT NULL,
        consensus_growth_near   REAL,
        consensus_growth_mid    REAL,
        margin_benchmark        REAL,
        valuation_framework     TEXT,
        source                  TEXT,
        notes                   TEXT,
        created_at              TEXT NOT NULL,
        updated_at              TEXT NOT NULL,
        PRIMARY KEY (sector, industry, week_key)
    );

    -- Indexes for common queries
    CREATE INDEX IF NOT EXISTS idx_financials_ticker ON financials(ticker);
    CREATE INDEX IF NOT EXISTS idx_prices_ticker ON prices(ticker);
    CREATE INDEX IF NOT EXISTS idx_prices_date ON prices(date);
    CREATE INDEX IF NOT EXISTS idx_estimates_ticker ON estimates(ticker);
    CREATE INDEX IF NOT EXISTS idx_screen_results_date ON screen_results(screen_date);
    CREATE INDEX IF NOT EXISTS idx_insider_ticker ON insider_trades(ticker);
    CREATE INDEX IF NOT EXISTS idx_industry_benchmarks_key ON industry_benchmarks(sector, industry, week_key);

    """)

    conn.commit()
    if close_after:
        conn.close()

    print(f"✓ Database initialized at {DB_PATH}")


if __name__ == "__main__":
    create_tables()
