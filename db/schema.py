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

    CREATE TABLE IF NOT EXISTS edgar_filing_cache (
        ticker          TEXT NOT NULL,
        cik             TEXT NOT NULL,
        form_type       TEXT NOT NULL,
        accession_no    TEXT NOT NULL,
        filing_date     TEXT,
        doc_name        TEXT NOT NULL,
        source_url      TEXT,
        raw_path        TEXT,
        clean_path      TEXT,
        raw_text_hash   TEXT,
        clean_text_hash TEXT,
        parser_version  TEXT NOT NULL,
        fetched_at      TEXT NOT NULL,
        cleaned_at      TEXT NOT NULL,
        PRIMARY KEY (ticker, accession_no, doc_name)
    );

    CREATE TABLE IF NOT EXISTS sec_filing_metrics_snapshot (
        ticker               TEXT NOT NULL,
        cik                  TEXT NOT NULL,
        as_of_date           TEXT NOT NULL,
        source_filing_date   TEXT,
        source_form          TEXT NOT NULL,
        revenue_cagr_3y      REAL,
        ebit_margin_avg_3y   REAL,
        gross_margin_avg_3y  REAL,
        net_debt_to_ebitda   REAL,
        fcf_yield            REAL,
        revenue_series_json  TEXT,
        ebit_series_json     TEXT,
        metric_source        TEXT,
        pulled_at            TEXT NOT NULL,
        PRIMARY KEY (ticker, as_of_date)
    );

    CREATE TABLE IF NOT EXISTS company_text_cache (
        ticker            TEXT NOT NULL,
        text_type         TEXT NOT NULL,
        source            TEXT NOT NULL,
        source_as_of_date TEXT,
        text_hash         TEXT NOT NULL,
        text_content      TEXT NOT NULL,
        fetched_at        TEXT NOT NULL,
        updated_at        TEXT NOT NULL,
        PRIMARY KEY (ticker, text_type, text_hash)
    );

    CREATE TABLE IF NOT EXISTS company_embeddings (
        ticker          TEXT NOT NULL,
        text_type       TEXT NOT NULL,
        text_hash       TEXT NOT NULL,
        embedding_model TEXT NOT NULL,
        embedding_dim   INTEGER NOT NULL,
        embedding_blob  TEXT NOT NULL,
        created_at      TEXT NOT NULL,
        PRIMARY KEY (ticker, text_type, text_hash, embedding_model)
    );

    CREATE TABLE IF NOT EXISTS peer_similarity_cache (
        target_ticker     TEXT NOT NULL,
        peer_ticker       TEXT NOT NULL,
        text_hash_target  TEXT NOT NULL,
        text_hash_peer    TEXT NOT NULL,
        embedding_model   TEXT NOT NULL,
        similarity_score  REAL NOT NULL,
        computed_at       TEXT NOT NULL,
        PRIMARY KEY (target_ticker, peer_ticker, text_hash_target, text_hash_peer, embedding_model)
    );
    -- CIQ ingest run tracking and contract audit
    CREATE TABLE IF NOT EXISTS ciq_ingest_runs (
        id                      INTEGER PRIMARY KEY AUTOINCREMENT,
        run_key                 TEXT NOT NULL UNIQUE,
        source_file             TEXT NOT NULL,
        file_hash               TEXT NOT NULL,
        ticker                  TEXT,
        parser_version          TEXT NOT NULL,
        ingest_ts               TEXT NOT NULL,
        status                  TEXT NOT NULL,
        error_message           TEXT,
        template_fingerprint    TEXT,
        rows_parsed             INTEGER DEFAULT 0,
        as_of_date              TEXT
    );

    -- CIQ long-form normalized data (source-of-truth)
    CREATE TABLE IF NOT EXISTS ciq_long_form (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id          INTEGER NOT NULL,
        ticker          TEXT NOT NULL,
        sheet_name      TEXT NOT NULL,
        section_name    TEXT,
        row_label       TEXT NOT NULL,
        metric_key      TEXT,
        period_date     TEXT,
        calc_type       TEXT,
        column_label    TEXT,
        column_index    INTEGER,
        value_raw       TEXT,
        value_num       REAL,
        unit            TEXT,
        scale_factor    REAL DEFAULT 1.0,
        source_file     TEXT NOT NULL,
        UNIQUE(run_id, sheet_name, row_label, period_date, calc_type, column_index),
        FOREIGN KEY (run_id) REFERENCES ciq_ingest_runs(id)
    );

    -- CIQ compute-ready deterministic snapshot
    CREATE TABLE IF NOT EXISTS ciq_valuation_snapshot (
        ticker                  TEXT NOT NULL,
        as_of_date              TEXT NOT NULL,
        run_id                  INTEGER NOT NULL,
        source_file             TEXT NOT NULL,
        revenue_mm              REAL,
        operating_income_mm     REAL,
        capex_mm                REAL,
        da_mm                   REAL,
        total_debt_mm           REAL,
        cash_mm                 REAL,
        shares_out_mm           REAL,
        ebit_margin             REAL,
        op_margin_avg_3yr       REAL,
        capex_pct_avg_3yr       REAL,
        da_pct_avg_3yr          REAL,
        effective_tax_rate      REAL,
        effective_tax_rate_avg  REAL,
        revenue_cagr_3yr        REAL,
        debt_to_ebitda          REAL,
        roic                    REAL,
        fcf_yield               REAL,
        pulled_at               TEXT,
        PRIMARY KEY (ticker, as_of_date),
        FOREIGN KEY (run_id) REFERENCES ciq_ingest_runs(id)
    );

    -- CIQ comps snapshot for peer analytics
    CREATE TABLE IF NOT EXISTS ciq_comps_snapshot (
        target_ticker    TEXT NOT NULL,
        peer_ticker      TEXT NOT NULL,
        as_of_date       TEXT NOT NULL,
        run_id           INTEGER NOT NULL,
        source_file      TEXT NOT NULL,
        source_sheet     TEXT NOT NULL,
        peer_name        TEXT,
        section_name     TEXT,
        metric_key       TEXT NOT NULL,
        metric_label     TEXT,
        value_raw        TEXT,
        value_num        REAL,
        unit             TEXT,
        is_target        INTEGER DEFAULT 0,
        PRIMARY KEY (target_ticker, peer_ticker, as_of_date, source_sheet, metric_key),
        FOREIGN KEY (run_id) REFERENCES ciq_ingest_runs(id)
    );

    -- Indexes for common queries
    CREATE INDEX IF NOT EXISTS idx_financials_ticker ON financials(ticker);
    CREATE INDEX IF NOT EXISTS idx_prices_ticker ON prices(ticker);
    CREATE INDEX IF NOT EXISTS idx_prices_date ON prices(date);
    CREATE INDEX IF NOT EXISTS idx_estimates_ticker ON estimates(ticker);
    CREATE INDEX IF NOT EXISTS idx_screen_results_date ON screen_results(screen_date);
    CREATE INDEX IF NOT EXISTS idx_insider_ticker ON insider_trades(ticker);
    CREATE INDEX IF NOT EXISTS idx_industry_benchmarks_key ON industry_benchmarks(sector, industry, week_key);
    CREATE INDEX IF NOT EXISTS idx_edgar_filing_cache_lookup ON edgar_filing_cache(ticker, form_type, filing_date);
    CREATE INDEX IF NOT EXISTS idx_sec_filing_metrics_lookup ON sec_filing_metrics_snapshot(ticker, as_of_date);
    CREATE INDEX IF NOT EXISTS idx_company_text_lookup ON company_text_cache(ticker, text_type, updated_at);
    CREATE INDEX IF NOT EXISTS idx_peer_similarity_lookup ON peer_similarity_cache(target_ticker, peer_ticker, embedding_model);
    CREATE INDEX IF NOT EXISTS idx_ciq_runs_ticker ON ciq_ingest_runs(ticker, ingest_ts);
    CREATE INDEX IF NOT EXISTS idx_ciq_long_form_lookup ON ciq_long_form(ticker, metric_key, period_date);
    CREATE INDEX IF NOT EXISTS idx_ciq_snapshot_ticker ON ciq_valuation_snapshot(ticker, as_of_date);
    CREATE INDEX IF NOT EXISTS idx_ciq_comps_target ON ciq_comps_snapshot(target_ticker, as_of_date);

    """)

    conn.commit()
    if close_after:
        conn.close()
        print(f"✓ Database initialized at {DB_PATH}")


if __name__ == "__main__":
    create_tables()

