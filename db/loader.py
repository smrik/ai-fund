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


def register_ciq_ingest_run(conn: sqlite3.Connection, row: dict) -> tuple[int, bool]:
    """
    Register CIQ ingest run.

    Returns (run_id, is_new). When a run_key already exists, returns existing id
    and is_new=False (idempotent ingest gate).
    """
    existing = conn.execute(
        "SELECT id FROM ciq_ingest_runs WHERE run_key = ?",
        [row["run_key"]],
    ).fetchone()
    if existing:
        return int(existing[0]), False

    cur = conn.execute(
        """
        INSERT INTO ciq_ingest_runs (
            run_key, source_file, file_hash, ticker, parser_version,
            ingest_ts, status, error_message, template_fingerprint,
            rows_parsed, as_of_date
        ) VALUES (
            :run_key, :source_file, :file_hash, :ticker, :parser_version,
            :ingest_ts, :status, :error_message, :template_fingerprint,
            :rows_parsed, :as_of_date
        )
        """,
        row,
    )
    conn.commit()
    return int(cur.lastrowid), True


def finalize_ciq_ingest_run(
    conn: sqlite3.Connection,
    run_id: int,
    status: str,
    error_message: str | None,
    rows_parsed: int,
):
    """Finalize CIQ ingest run status and audit fields."""
    conn.execute(
        """
        UPDATE ciq_ingest_runs
        SET status = ?, error_message = ?, rows_parsed = ?
        WHERE id = ?
        """,
        [status, error_message, rows_parsed, run_id],
    )
    conn.commit()


def insert_ciq_long_form(conn: sqlite3.Connection, run_id: int, rows: list[dict[str, Any]]):
    """Insert CIQ long-form records for a specific ingest run."""
    if not rows:
        return

    payload = []
    for row in rows:
        item = dict(row)
        item["run_id"] = run_id
        payload.append(item)

    conn.executemany(
        """
        INSERT OR REPLACE INTO ciq_long_form (
            run_id, ticker, sheet_name, section_name, row_label,
            metric_key, period_date, calc_type, column_label,
            column_index, value_raw, value_num, unit, scale_factor,
            source_file
        ) VALUES (
            :run_id, :ticker, :sheet_name, :section_name, :row_label,
            :metric_key, :period_date, :calc_type, :column_label,
            :column_index, :value_raw, :value_num, :unit, :scale_factor,
            :source_file
        )
        """,
        payload,
    )
    conn.commit()


def upsert_ciq_valuation_snapshot(conn: sqlite3.Connection, rows: list[dict[str, Any]]):
    """Upsert CIQ valuation snapshots keyed by (ticker, as_of_date)."""
    if not rows:
        return

    conn.executemany(
        """
        INSERT INTO ciq_valuation_snapshot (
            ticker, as_of_date, run_id, source_file,
            revenue_mm, operating_income_mm, capex_mm, da_mm,
            total_debt_mm, cash_mm, shares_out_mm,
            ebit_margin, op_margin_avg_3yr, capex_pct_avg_3yr,
            da_pct_avg_3yr, effective_tax_rate, effective_tax_rate_avg,
            revenue_cagr_3yr, debt_to_ebitda, roic, fcf_yield, pulled_at
        ) VALUES (
            :ticker, :as_of_date, :run_id, :source_file,
            :revenue_mm, :operating_income_mm, :capex_mm, :da_mm,
            :total_debt_mm, :cash_mm, :shares_out_mm,
            :ebit_margin, :op_margin_avg_3yr, :capex_pct_avg_3yr,
            :da_pct_avg_3yr, :effective_tax_rate, :effective_tax_rate_avg,
            :revenue_cagr_3yr, :debt_to_ebitda, :roic, :fcf_yield, :pulled_at
        )
        ON CONFLICT(ticker, as_of_date) DO UPDATE SET
            run_id = excluded.run_id,
            source_file = excluded.source_file,
            revenue_mm = excluded.revenue_mm,
            operating_income_mm = excluded.operating_income_mm,
            capex_mm = excluded.capex_mm,
            da_mm = excluded.da_mm,
            total_debt_mm = excluded.total_debt_mm,
            cash_mm = excluded.cash_mm,
            shares_out_mm = excluded.shares_out_mm,
            ebit_margin = excluded.ebit_margin,
            op_margin_avg_3yr = excluded.op_margin_avg_3yr,
            capex_pct_avg_3yr = excluded.capex_pct_avg_3yr,
            da_pct_avg_3yr = excluded.da_pct_avg_3yr,
            effective_tax_rate = excluded.effective_tax_rate,
            effective_tax_rate_avg = excluded.effective_tax_rate_avg,
            revenue_cagr_3yr = excluded.revenue_cagr_3yr,
            debt_to_ebitda = excluded.debt_to_ebitda,
            roic = excluded.roic,
            fcf_yield = excluded.fcf_yield,
            pulled_at = excluded.pulled_at
        """,
        rows,
    )
    conn.commit()


def upsert_ciq_comps_snapshot(conn: sqlite3.Connection, rows: list[dict[str, Any]]):
    """Upsert CIQ comps snapshot rows keyed by target/peer/date/sheet/metric."""
    if not rows:
        return

    conn.executemany(
        """
        INSERT INTO ciq_comps_snapshot (
            target_ticker, peer_ticker, as_of_date, run_id, source_file,
            source_sheet, peer_name, section_name, metric_key, metric_label,
            value_raw, value_num, unit, is_target
        ) VALUES (
            :target_ticker, :peer_ticker, :as_of_date, :run_id, :source_file,
            :source_sheet, :peer_name, :section_name, :metric_key, :metric_label,
            :value_raw, :value_num, :unit, :is_target
        )
        ON CONFLICT(target_ticker, peer_ticker, as_of_date, source_sheet, metric_key)
        DO UPDATE SET
            run_id = excluded.run_id,
            source_file = excluded.source_file,
            peer_name = excluded.peer_name,
            section_name = excluded.section_name,
            metric_label = excluded.metric_label,
            value_raw = excluded.value_raw,
            value_num = excluded.value_num,
            unit = excluded.unit,
            is_target = excluded.is_target
        """,
        rows,
    )
    conn.commit()


def upsert_edgar_filing_cache(conn: sqlite3.Connection, row: dict[str, Any]):
    """Upsert cached EDGAR filing metadata."""
    conn.execute(
        """
        INSERT INTO edgar_filing_cache (
            ticker, cik, form_type, accession_no, filing_date, doc_name,
            source_url, raw_path, clean_path, raw_text_hash, clean_text_hash,
            parser_version, fetched_at, cleaned_at
        ) VALUES (
            :ticker, :cik, :form_type, :accession_no, :filing_date, :doc_name,
            :source_url, :raw_path, :clean_path, :raw_text_hash, :clean_text_hash,
            :parser_version, :fetched_at, :cleaned_at
        )
        ON CONFLICT(ticker, accession_no, doc_name) DO UPDATE SET
            cik = excluded.cik,
            form_type = excluded.form_type,
            filing_date = excluded.filing_date,
            source_url = excluded.source_url,
            raw_path = excluded.raw_path,
            clean_path = excluded.clean_path,
            raw_text_hash = excluded.raw_text_hash,
            clean_text_hash = excluded.clean_text_hash,
            parser_version = excluded.parser_version,
            fetched_at = excluded.fetched_at,
            cleaned_at = excluded.cleaned_at
        """,
        row,
    )
    conn.commit()


def upsert_sec_filing_metrics_snapshot(conn: sqlite3.Connection, row: dict[str, Any]):
    """Upsert deterministic SEC/XBRL metrics snapshot."""
    conn.execute(
        """
        INSERT INTO sec_filing_metrics_snapshot (
            ticker, cik, as_of_date, source_filing_date, source_form,
            revenue_cagr_3y, ebit_margin_avg_3y, gross_margin_avg_3y,
            net_debt_to_ebitda, fcf_yield, revenue_series_json, ebit_series_json,
            metric_source, pulled_at
        ) VALUES (
            :ticker, :cik, :as_of_date, :source_filing_date, :source_form,
            :revenue_cagr_3y, :ebit_margin_avg_3y, :gross_margin_avg_3y,
            :net_debt_to_ebitda, :fcf_yield, :revenue_series_json, :ebit_series_json,
            :metric_source, :pulled_at
        )
        ON CONFLICT(ticker, as_of_date) DO UPDATE SET
            cik = excluded.cik,
            source_filing_date = excluded.source_filing_date,
            source_form = excluded.source_form,
            revenue_cagr_3y = excluded.revenue_cagr_3y,
            ebit_margin_avg_3y = excluded.ebit_margin_avg_3y,
            gross_margin_avg_3y = excluded.gross_margin_avg_3y,
            net_debt_to_ebitda = excluded.net_debt_to_ebitda,
            fcf_yield = excluded.fcf_yield,
            revenue_series_json = excluded.revenue_series_json,
            ebit_series_json = excluded.ebit_series_json,
            metric_source = excluded.metric_source,
            pulled_at = excluded.pulled_at
        """,
        row,
    )
    conn.commit()


def upsert_company_text_cache(conn: sqlite3.Connection, row: dict[str, Any]):
    """Upsert reusable company text content."""
    conn.execute(
        """
        INSERT INTO company_text_cache (
            ticker, text_type, source, source_as_of_date, text_hash,
            text_content, fetched_at, updated_at
        ) VALUES (
            :ticker, :text_type, :source, :source_as_of_date, :text_hash,
            :text_content, :fetched_at, :updated_at
        )
        ON CONFLICT(ticker, text_type, text_hash) DO UPDATE SET
            source = excluded.source,
            source_as_of_date = excluded.source_as_of_date,
            text_content = excluded.text_content,
            updated_at = excluded.updated_at
        """,
        row,
    )
    conn.commit()


def upsert_company_embedding(conn: sqlite3.Connection, row: dict[str, Any]):
    """Upsert cached local embedding vector."""
    conn.execute(
        """
        INSERT INTO company_embeddings (
            ticker, text_type, text_hash, embedding_model, embedding_dim, embedding_blob, created_at
        ) VALUES (
            :ticker, :text_type, :text_hash, :embedding_model, :embedding_dim, :embedding_blob, :created_at
        )
        ON CONFLICT(ticker, text_type, text_hash, embedding_model) DO UPDATE SET
            embedding_dim = excluded.embedding_dim,
            embedding_blob = excluded.embedding_blob,
            created_at = excluded.created_at
        """,
        row,
    )
    conn.commit()


def upsert_peer_similarity_cache(conn: sqlite3.Connection, row: dict[str, Any]):
    """Upsert cached target/peer similarity score."""
    conn.execute(
        """
        INSERT INTO peer_similarity_cache (
            target_ticker, peer_ticker, text_hash_target, text_hash_peer,
            embedding_model, similarity_score, computed_at
        ) VALUES (
            :target_ticker, :peer_ticker, :text_hash_target, :text_hash_peer,
            :embedding_model, :similarity_score, :computed_at
        )
        ON CONFLICT(target_ticker, peer_ticker, text_hash_target, text_hash_peer, embedding_model)
        DO UPDATE SET
            similarity_score = excluded.similarity_score,
            computed_at = excluded.computed_at
        """,
        row,
    )
    conn.commit()


def insert_valuation_override_audit(conn: sqlite3.Connection, rows: list[dict[str, Any]]):
    """Append valuation override audit events."""
    if not rows:
        return

    conn.executemany(
        """
        INSERT INTO valuation_override_audit (
            event_ts, ticker, actor, field, selection_mode,
            baseline_value, baseline_source, effective_value_before, effective_source_before,
            agent_value, agent_status, agent_confidence, custom_value, applied_value,
            prior_ticker_override_value, resulting_ticker_override_value, write_action,
            current_iv_json, proposed_iv_json, current_iv_base, proposed_iv_base,
            current_expected_iv, proposed_expected_iv
        ) VALUES (
            :event_ts, :ticker, :actor, :field, :selection_mode,
            :baseline_value, :baseline_source, :effective_value_before, :effective_source_before,
            :agent_value, :agent_status, :agent_confidence, :custom_value, :applied_value,
            :prior_ticker_override_value, :resulting_ticker_override_value, :write_action,
            :current_iv_json, :proposed_iv_json, :current_iv_base, :proposed_iv_base,
            :current_expected_iv, :proposed_expected_iv
        )
        """,
        rows,
    )
    conn.commit()
