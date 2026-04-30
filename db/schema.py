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

    CREATE TABLE IF NOT EXISTS edgar_section_cache (
        ticker          TEXT NOT NULL,
        cik             TEXT NOT NULL,
        form_type       TEXT NOT NULL,
        accession_no    TEXT NOT NULL,
        doc_name        TEXT NOT NULL,
        filing_date     TEXT,
        section_key     TEXT NOT NULL,
        section_label   TEXT NOT NULL,
        section_text    TEXT NOT NULL,
        section_hash    TEXT NOT NULL,
        parser_version  TEXT NOT NULL,
        extracted_at    TEXT NOT NULL,
        PRIMARY KEY (ticker, accession_no, doc_name, section_key, parser_version)
    );

    CREATE TABLE IF NOT EXISTS edgar_chunk_cache (
        ticker          TEXT NOT NULL,
        form_type       TEXT NOT NULL,
        accession_no    TEXT NOT NULL,
        doc_name        TEXT NOT NULL,
        section_key     TEXT NOT NULL,
        chunk_index     INTEGER NOT NULL,
        chunk_text      TEXT NOT NULL,
        chunk_hash      TEXT NOT NULL,
        start_char      INTEGER NOT NULL,
        end_char        INTEGER NOT NULL,
        chunk_version   TEXT NOT NULL,
        created_at      TEXT NOT NULL,
        PRIMARY KEY (ticker, accession_no, doc_name, section_key, chunk_index, chunk_version)
    );

    CREATE TABLE IF NOT EXISTS edgar_chunk_embeddings (
        chunk_hash       TEXT NOT NULL,
        embedding_model  TEXT NOT NULL,
        embedding_dim    INTEGER NOT NULL,
        embedding_blob   TEXT NOT NULL,
        created_at       TEXT NOT NULL,
        PRIMARY KEY (chunk_hash, embedding_model)
    );

    CREATE TABLE IF NOT EXISTS filing_context_cache (
        ticker           TEXT NOT NULL,
        profile_name     TEXT NOT NULL,
        corpus_hash      TEXT NOT NULL,
        query_version    TEXT NOT NULL,
        embedding_model  TEXT NOT NULL,
        context_json     TEXT NOT NULL,
        created_at       TEXT NOT NULL,
        PRIMARY KEY (ticker, profile_name, corpus_hash, query_version, embedding_model)
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

    CREATE TABLE IF NOT EXISTS valuation_override_audit (
        id                           INTEGER PRIMARY KEY AUTOINCREMENT,
        event_ts                     TEXT NOT NULL,
        ticker                       TEXT NOT NULL,
        actor                        TEXT NOT NULL,
        field                        TEXT NOT NULL,
        selection_mode               TEXT NOT NULL,
        baseline_value               REAL,
        baseline_source              TEXT,
        effective_value_before       REAL,
        effective_source_before      TEXT,
        agent_value                  REAL,
        agent_status                 TEXT,
        agent_confidence             TEXT,
        custom_value                 REAL,
        applied_value                REAL,
        prior_ticker_override_value  REAL,
        resulting_ticker_override_value REAL,
        write_action                 TEXT NOT NULL,
        current_iv_json              TEXT,
        proposed_iv_json             TEXT,
        current_iv_base              REAL,
        proposed_iv_base             REAL,
        current_expected_iv          REAL,
        proposed_expected_iv         REAL
    );

    CREATE TABLE IF NOT EXISTS agent_run_cache (
        ticker          TEXT NOT NULL,
        agent_name      TEXT NOT NULL,
        input_hash      TEXT NOT NULL,
        model           TEXT NOT NULL,
        prompt_hash     TEXT NOT NULL,
        output_format   TEXT NOT NULL,
        output_module   TEXT,
        output_class    TEXT,
        output_payload  TEXT NOT NULL,
        output_hash     TEXT NOT NULL,
        created_at      TEXT NOT NULL,
        PRIMARY KEY (ticker, agent_name, input_hash, model, prompt_hash)
    );

    CREATE TABLE IF NOT EXISTS agent_run_log (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        run_ts          TEXT NOT NULL,
        ticker          TEXT NOT NULL,
        agent_name      TEXT NOT NULL,
        status          TEXT NOT NULL,
        cache_hit       INTEGER NOT NULL DEFAULT 0,
        forced_refresh  INTEGER NOT NULL DEFAULT 0,
        input_hash      TEXT,
        output_hash     TEXT,
        model           TEXT,
        prompt_version  TEXT,
        prompt_hash     TEXT,
        started_at      TEXT,
        finished_at     TEXT,
        duration_ms     INTEGER,
        error           TEXT
    );

    CREATE TABLE IF NOT EXISTS agent_run_artifacts (
        id                  INTEGER PRIMARY KEY AUTOINCREMENT,
        run_log_id          INTEGER NOT NULL,
        ticker              TEXT NOT NULL,
        agent_name          TEXT NOT NULL,
        artifact_source     TEXT NOT NULL,
        system_prompt       TEXT,
        user_prompt         TEXT,
        tool_schema_json    TEXT,
        api_trace_json      TEXT,
        raw_final_output    TEXT,
        parsed_output_json  TEXT,
        prompt_tokens       INTEGER,
        completion_tokens   INTEGER,
        total_tokens        INTEGER,
        created_at          TEXT NOT NULL,
        FOREIGN KEY (run_log_id) REFERENCES agent_run_log(id)
    );

    CREATE TABLE IF NOT EXISTS pipeline_report_archive (
        id                    INTEGER PRIMARY KEY AUTOINCREMENT,
        ticker                TEXT NOT NULL,
        created_at            TEXT NOT NULL,
        run_group_ts          TEXT,
        company_name          TEXT,
        sector                TEXT,
        action                TEXT,
        conviction            TEXT,
        current_price         REAL,
        base_iv               REAL,
        memo_json             TEXT NOT NULL,
        dashboard_snapshot_json TEXT,
        run_trace_json        TEXT
    );

    CREATE TABLE IF NOT EXISTS dossier_profiles (
        ticker                        TEXT PRIMARY KEY,
        company_name                  TEXT,
        dossier_root_path             TEXT NOT NULL,
        notes_root_path               TEXT NOT NULL,
        model_root_path               TEXT NOT NULL,
        exports_root_path             TEXT NOT NULL,
        status                        TEXT NOT NULL,
        current_model_version         TEXT,
        current_thesis_version        TEXT,
        current_publishable_memo_version TEXT,
        initialized_at                TEXT NOT NULL,
        updated_at                    TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS dossier_sections (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        ticker          TEXT NOT NULL,
        note_slug       TEXT NOT NULL,
        note_title      TEXT NOT NULL,
        relative_path   TEXT NOT NULL,
        section_kind    TEXT NOT NULL,
        is_private      INTEGER NOT NULL DEFAULT 0,
        last_synced_at  TEXT NOT NULL,
        content_hash    TEXT,
        metadata_json   TEXT,
        UNIQUE (ticker, note_slug)
    );

    CREATE TABLE IF NOT EXISTS dossier_sources (
        id                        INTEGER PRIMARY KEY AUTOINCREMENT,
        ticker                    TEXT NOT NULL,
        source_id                 TEXT NOT NULL,
        title                     TEXT NOT NULL,
        source_type               TEXT NOT NULL,
        source_date               TEXT,
        access_date               TEXT,
        why_it_matters            TEXT,
        file_path                 TEXT,
        external_uri              TEXT,
        zotero_key                TEXT,
        relative_source_note_path TEXT,
        supports_json             TEXT,
        limitations_text          TEXT,
        created_at                TEXT NOT NULL,
        updated_at                TEXT NOT NULL,
        UNIQUE (ticker, source_id)
    );

    CREATE TABLE IF NOT EXISTS dossier_artifacts (
        id                INTEGER PRIMARY KEY AUTOINCREMENT,
        ticker            TEXT NOT NULL,
        artifact_key      TEXT NOT NULL,
        artifact_type     TEXT NOT NULL,
        title             TEXT NOT NULL,
        path_mode         TEXT NOT NULL,
        path_value        TEXT NOT NULL,
        source_id         TEXT,
        linked_note_slug  TEXT,
        linked_snapshot_id INTEGER,
        model_version     TEXT,
        is_private        INTEGER NOT NULL DEFAULT 0,
        created_at        TEXT NOT NULL,
        updated_at        TEXT NOT NULL,
        metadata_json     TEXT,
        UNIQUE (ticker, artifact_key)
    );

    CREATE TABLE IF NOT EXISTS dossier_model_checkpoints (
        id                  INTEGER PRIMARY KEY AUTOINCREMENT,
        ticker              TEXT NOT NULL,
        checkpoint_ts       TEXT NOT NULL,
        model_version       TEXT NOT NULL,
        artifact_key        TEXT,
        snapshot_id         INTEGER,
        valuation_json      TEXT NOT NULL,
        drivers_summary_json TEXT,
        change_reason       TEXT,
        thesis_version      TEXT,
        source_ids_json     TEXT,
        created_by          TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS dossier_tracker_state (
        ticker             TEXT PRIMARY KEY,
        overall_status     TEXT NOT NULL,
        pm_action          TEXT,
        pm_conviction      TEXT,
        summary_note       TEXT,
        pillar_states_json TEXT NOT NULL,
        open_questions_json TEXT,
        last_reviewed_at   TEXT,
        latest_snapshot_id INTEGER,
        metadata_json      TEXT
    );

    CREATE TABLE IF NOT EXISTS dossier_catalysts (
        id                    INTEGER PRIMARY KEY AUTOINCREMENT,
        ticker                TEXT NOT NULL,
        catalyst_key          TEXT NOT NULL,
        title                 TEXT NOT NULL,
        description           TEXT,
        priority              TEXT NOT NULL,
        status                TEXT NOT NULL,
        expected_date         TEXT,
        expected_window_start TEXT,
        expected_window_end   TEXT,
        status_reason         TEXT,
        source_origin         TEXT NOT NULL,
        source_snapshot_id    INTEGER,
        updated_at            TEXT NOT NULL,
        evidence_json         TEXT,
        UNIQUE (ticker, catalyst_key)
    );

    CREATE TABLE IF NOT EXISTS dossier_decision_log (
        id                  INTEGER PRIMARY KEY AUTOINCREMENT,
        ticker              TEXT NOT NULL,
        decision_ts         TEXT NOT NULL,
        decision_title      TEXT NOT NULL,
        action              TEXT NOT NULL,
        conviction          TEXT,
        beliefs_text        TEXT NOT NULL,
        evidence_text       TEXT,
        assumptions_text    TEXT,
        falsifiers_text     TEXT,
        review_due_date     TEXT,
        snapshot_id         INTEGER,
        model_checkpoint_id INTEGER,
        private_notes_text  TEXT,
        created_by          TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS dossier_review_log (
        id                            INTEGER PRIMARY KEY AUTOINCREMENT,
        ticker                        TEXT NOT NULL,
        review_ts                     TEXT NOT NULL,
        review_title                  TEXT NOT NULL,
        period_type                   TEXT NOT NULL,
        expectations_vs_outcomes_text TEXT NOT NULL,
        factual_error_text            TEXT,
        interpretive_error_text       TEXT,
        behavioral_error_text         TEXT,
        thesis_status                 TEXT NOT NULL,
        model_status                  TEXT NOT NULL,
        action_taken_text             TEXT,
        linked_decision_id            INTEGER,
        linked_snapshot_id            INTEGER,
        private_notes_text            TEXT,
        created_by                    TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS dossier_note_blocks (
        id                   INTEGER PRIMARY KEY AUTOINCREMENT,
        ticker               TEXT NOT NULL,
        block_ts             TEXT NOT NULL,
        block_type           TEXT NOT NULL,
        title                TEXT NOT NULL,
        body                 TEXT NOT NULL,
        source_context_json  TEXT NOT NULL,
        linked_snapshot_id   INTEGER,
        linked_sources_json  TEXT,
        linked_artifacts_json TEXT,
        status               TEXT NOT NULL,
        pinned_to_report     INTEGER NOT NULL DEFAULT 0,
        created_by           TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS wacc_methodology_audit (
        id                    INTEGER PRIMARY KEY AUTOINCREMENT,
        event_ts              TEXT NOT NULL,
        ticker                TEXT NOT NULL,
        actor                 TEXT NOT NULL,
        mode                  TEXT NOT NULL,
        selected_method       TEXT,
        weights_json          TEXT,
        effective_wacc        REAL,
        prior_config_json     TEXT,
        resulting_config_json TEXT NOT NULL,
        preview_json          TEXT
    );

    CREATE TABLE IF NOT EXISTS generated_exports (
        export_id            TEXT PRIMARY KEY,
        scope                TEXT NOT NULL,
        ticker               TEXT,
        status               TEXT NOT NULL,
        export_format        TEXT NOT NULL,
        source_mode          TEXT NOT NULL,
        template_strategy    TEXT NOT NULL,
        title                TEXT NOT NULL,
        bundle_dir           TEXT NOT NULL,
        primary_artifact_key TEXT,
        created_by           TEXT NOT NULL,
        snapshot_id          INTEGER,
        created_at           TEXT NOT NULL,
        updated_at           TEXT NOT NULL,
        metadata_json        TEXT
    );

    CREATE TABLE IF NOT EXISTS generated_export_artifacts (
        id                   INTEGER PRIMARY KEY AUTOINCREMENT,
        export_id            TEXT NOT NULL,
        artifact_key         TEXT NOT NULL,
        artifact_role        TEXT NOT NULL,
        title                TEXT NOT NULL,
        path                 TEXT NOT NULL,
        mime_type            TEXT NOT NULL,
        size_bytes           INTEGER,
        is_primary           INTEGER NOT NULL DEFAULT 0,
        created_at           TEXT NOT NULL,
        metadata_json        TEXT,
        UNIQUE (export_id, artifact_key),
        FOREIGN KEY (export_id) REFERENCES generated_exports(export_id)
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
    CREATE INDEX IF NOT EXISTS idx_edgar_section_cache_lookup ON edgar_section_cache(ticker, form_type, filing_date, section_key);
    CREATE INDEX IF NOT EXISTS idx_edgar_chunk_cache_lookup ON edgar_chunk_cache(ticker, form_type, accession_no, section_key);
    CREATE INDEX IF NOT EXISTS idx_edgar_chunk_embeddings_lookup ON edgar_chunk_embeddings(chunk_hash, embedding_model);
    CREATE INDEX IF NOT EXISTS idx_filing_context_cache_lookup ON filing_context_cache(ticker, profile_name, corpus_hash, query_version);
    CREATE INDEX IF NOT EXISTS idx_sec_filing_metrics_lookup ON sec_filing_metrics_snapshot(ticker, as_of_date);
    CREATE INDEX IF NOT EXISTS idx_company_text_lookup ON company_text_cache(ticker, text_type, updated_at);
    CREATE INDEX IF NOT EXISTS idx_peer_similarity_lookup ON peer_similarity_cache(target_ticker, peer_ticker, embedding_model);
    CREATE INDEX IF NOT EXISTS idx_override_audit_ticker_ts ON valuation_override_audit(ticker, event_ts DESC);
    CREATE INDEX IF NOT EXISTS idx_agent_run_log_ticker_ts ON agent_run_log(ticker, run_ts DESC);
    CREATE INDEX IF NOT EXISTS idx_agent_run_cache_lookup ON agent_run_cache(ticker, agent_name, input_hash, model, prompt_hash);
    CREATE INDEX IF NOT EXISTS idx_agent_run_artifacts_ticker_agent_ts ON agent_run_artifacts(ticker, agent_name, created_at DESC);
    CREATE INDEX IF NOT EXISTS idx_agent_run_artifacts_run_log_id ON agent_run_artifacts(run_log_id);
    CREATE INDEX IF NOT EXISTS idx_pipeline_report_archive_ticker_ts ON pipeline_report_archive(ticker, created_at DESC);
    CREATE INDEX IF NOT EXISTS idx_dossier_sections_ticker_slug ON dossier_sections(ticker, note_slug);
    CREATE INDEX IF NOT EXISTS idx_dossier_profiles_status ON dossier_profiles(status, updated_at DESC);
    CREATE INDEX IF NOT EXISTS idx_dossier_sources_ticker_id ON dossier_sources(ticker, source_id);
    CREATE INDEX IF NOT EXISTS idx_dossier_artifacts_ticker_key ON dossier_artifacts(ticker, artifact_key);
    CREATE INDEX IF NOT EXISTS idx_dossier_model_checkpoints_ticker_ts ON dossier_model_checkpoints(ticker, checkpoint_ts DESC);
    CREATE INDEX IF NOT EXISTS idx_dossier_tracker_state_reviewed ON dossier_tracker_state(last_reviewed_at DESC);
    CREATE INDEX IF NOT EXISTS idx_dossier_catalysts_ticker_key ON dossier_catalysts(ticker, catalyst_key);
    CREATE INDEX IF NOT EXISTS idx_dossier_decision_log_ticker_ts ON dossier_decision_log(ticker, decision_ts DESC);
    CREATE INDEX IF NOT EXISTS idx_dossier_review_log_ticker_ts ON dossier_review_log(ticker, review_ts DESC);
    CREATE INDEX IF NOT EXISTS idx_dossier_note_blocks_ticker_type_ts ON dossier_note_blocks(ticker, block_type, block_ts DESC);
    CREATE INDEX IF NOT EXISTS idx_wacc_methodology_audit_ticker_ts ON wacc_methodology_audit(ticker, event_ts DESC);
    CREATE INDEX IF NOT EXISTS idx_generated_exports_scope_ts ON generated_exports(scope, created_at DESC);
    CREATE INDEX IF NOT EXISTS idx_generated_exports_ticker_ts ON generated_exports(ticker, created_at DESC);
    CREATE INDEX IF NOT EXISTS idx_ciq_runs_ticker ON ciq_ingest_runs(ticker, ingest_ts);
    CREATE INDEX IF NOT EXISTS idx_ciq_long_form_lookup ON ciq_long_form(ticker, metric_key, period_date);
    CREATE INDEX IF NOT EXISTS idx_ciq_snapshot_ticker ON ciq_valuation_snapshot(ticker, as_of_date);
    CREATE INDEX IF NOT EXISTS idx_ciq_comps_target ON ciq_comps_snapshot(target_ticker, as_of_date);

    -- FRED macro series cache (daily snapshots)
    CREATE TABLE IF NOT EXISTS macro_series (
        series_id       TEXT NOT NULL,
        series_date     TEXT NOT NULL,
        value           REAL,
        fetched_at      TEXT NOT NULL,
        PRIMARY KEY (series_id, series_date)
    );

    -- Analyst estimate history snapshots (daily)
    CREATE TABLE IF NOT EXISTS estimate_history (
        ticker          TEXT NOT NULL,
        snapshot_date   TEXT NOT NULL,
        fy1_eps         REAL,
        fy2_eps         REAL,
        fy1_revenue     REAL,
        fy2_revenue     REAL,
        num_analysts    INTEGER,
        eps_high        REAL,
        eps_low         REAL,
        revenue_high    REAL,
        revenue_low     REAL,
        pulled_at       TEXT NOT NULL,
        PRIMARY KEY (ticker, snapshot_date)
    );

    -- DCF intrinsic value history (populated by batch_runner each run)
    CREATE TABLE IF NOT EXISTS dcf_valuations (
        ticker          TEXT NOT NULL,
        run_date        TEXT NOT NULL,
        iv_bear         REAL,
        iv_base         REAL,
        iv_bull         REAL,
        iv_expected     REAL,
        current_price   REAL,
        upside_pct      REAL,
        wacc            REAL,
        exit_multiple   REAL,
        net_debt_source TEXT,
        revenue_source  TEXT,
        PRIMARY KEY (ticker, run_date)
    );

    -- Market data cache (TTL-based, avoids duplicate yfinance calls in batch)
    CREATE TABLE IF NOT EXISTS market_data_cache (
        ticker          TEXT NOT NULL,
        data_type       TEXT NOT NULL,
        data_json       TEXT NOT NULL,
        fetched_at      TEXT NOT NULL,
        PRIMARY KEY (ticker, data_type)
    );

    CREATE INDEX IF NOT EXISTS idx_market_data_cache_lookup ON market_data_cache(ticker, data_type, fetched_at DESC);

    CREATE INDEX IF NOT EXISTS idx_macro_series_lookup ON macro_series(series_id, series_date DESC);
    CREATE INDEX IF NOT EXISTS idx_estimate_history_lookup ON estimate_history(ticker, snapshot_date DESC);
    CREATE INDEX IF NOT EXISTS idx_dcf_valuations_lookup ON dcf_valuations(ticker, run_date DESC);

    """)

    agent_run_log_columns = {
        row["name"] if isinstance(row, sqlite3.Row) else row[1]
        for row in conn.execute("PRAGMA table_info(agent_run_log)").fetchall()
    }
    if "prompt_version" not in agent_run_log_columns:
        conn.execute("ALTER TABLE agent_run_log ADD COLUMN prompt_version TEXT")

    conn.commit()
    if close_after:
        conn.close()
        print(f"✓ Database initialized at {DB_PATH}")


if __name__ == "__main__":
    create_tables()
