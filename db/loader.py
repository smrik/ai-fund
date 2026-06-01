"""
Alpha Pod — Database Loader
Insert/update functions for all tables. All operations are idempotent (upsert).
"""
import sqlite3
import json
from typing import Any

from src.utils import utc_now_iso


def _now() -> str:
    return utc_now_iso()


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


def upsert_edgar_section_cache(conn: sqlite3.Connection, rows: list[dict[str, Any]]):
    """Upsert extracted filing sections keyed by filing accession and parser version."""
    if not rows:
        return
    conn.executemany(
        """
        INSERT INTO edgar_section_cache (
            ticker, cik, form_type, accession_no, doc_name, filing_date,
            section_key, section_label, section_text, section_hash,
            parser_version, extracted_at
        ) VALUES (
            :ticker, :cik, :form_type, :accession_no, :doc_name, :filing_date,
            :section_key, :section_label, :section_text, :section_hash,
            :parser_version, :extracted_at
        )
        ON CONFLICT(ticker, accession_no, doc_name, section_key, parser_version) DO UPDATE SET
            cik = excluded.cik,
            form_type = excluded.form_type,
            filing_date = excluded.filing_date,
            section_label = excluded.section_label,
            section_text = excluded.section_text,
            section_hash = excluded.section_hash,
            extracted_at = excluded.extracted_at
        """,
        rows,
    )
    conn.commit()


def upsert_edgar_chunk_cache(conn: sqlite3.Connection, rows: list[dict[str, Any]]):
    """Upsert filing chunks keyed by section/chunk version."""
    if not rows:
        return
    conn.executemany(
        """
        INSERT INTO edgar_chunk_cache (
            ticker, form_type, accession_no, doc_name, section_key,
            chunk_index, chunk_text, chunk_hash, start_char, end_char,
            chunk_version, created_at
        ) VALUES (
            :ticker, :form_type, :accession_no, :doc_name, :section_key,
            :chunk_index, :chunk_text, :chunk_hash, :start_char, :end_char,
            :chunk_version, :created_at
        )
        ON CONFLICT(ticker, accession_no, doc_name, section_key, chunk_index, chunk_version)
        DO UPDATE SET
            chunk_text = excluded.chunk_text,
            chunk_hash = excluded.chunk_hash,
            start_char = excluded.start_char,
            end_char = excluded.end_char,
            created_at = excluded.created_at
        """,
        rows,
    )
    conn.commit()


def upsert_edgar_chunk_embedding(conn: sqlite3.Connection, row: dict[str, Any]):
    """Upsert cached local embedding for a filing chunk."""
    conn.execute(
        """
        INSERT INTO edgar_chunk_embeddings (
            chunk_hash, embedding_model, embedding_dim, embedding_blob, created_at
        ) VALUES (
            :chunk_hash, :embedding_model, :embedding_dim, :embedding_blob, :created_at
        )
        ON CONFLICT(chunk_hash, embedding_model) DO UPDATE SET
            embedding_dim = excluded.embedding_dim,
            embedding_blob = excluded.embedding_blob,
            created_at = excluded.created_at
        """,
        row,
    )
    conn.commit()


def upsert_filing_context_cache(conn: sqlite3.Connection, row: dict[str, Any]):
    """Upsert rendered filing context bundle cache."""
    conn.execute(
        """
        INSERT INTO filing_context_cache (
            ticker, profile_name, corpus_hash, query_version,
            embedding_model, context_json, created_at
        ) VALUES (
            :ticker, :profile_name, :corpus_hash, :query_version,
            :embedding_model, :context_json, :created_at
        )
        ON CONFLICT(ticker, profile_name, corpus_hash, query_version, embedding_model)
        DO UPDATE SET
            context_json = excluded.context_json,
            created_at = excluded.created_at
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


def _split_assumption_register_diff(row: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    prior: dict[str, Any] = {}
    new: dict[str, Any] = {}
    for field, change in (row.get("changed_fields") or {}).items():
        if not isinstance(change, dict):
            continue
        prior[field] = change.get("prior")
        new[field] = change.get("new")
    return prior, new


def insert_assumption_register_audit(conn: sqlite3.Connection, rows: list[dict[str, Any]]) -> None:
    """Append review-relevant Assumption Register audit events."""
    if not rows:
        return

    payload: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        prior, new = _split_assumption_register_diff(item)
        item["ticker"] = str(item["ticker"]).upper()
        item["entity_type"] = (
            item["entity_type"].value
            if hasattr(item.get("entity_type"), "value")
            else str(item.get("entity_type"))
        )
        item["prior_diff_json"] = json.dumps(prior, separators=(",", ":"))
        item["new_diff_json"] = json.dumps(new, separators=(",", ":"))
        item["changed_fields_json"] = json.dumps(item.get("changed_fields") or {}, separators=(",", ":"))
        item["valuation_impact_json"] = (
            json.dumps(item.get("valuation_impact"), separators=(",", ":"))
            if item.get("valuation_impact") is not None
            else None
        )
        payload.append(item)

    conn.executemany(
        """
        INSERT INTO assumption_register_audit (
            event_ts, actor, actor_type, entity_type, entity_id, ticker,
            assumption_name, scope, event_type, prior_diff_json, new_diff_json,
            changed_fields_json, valuation_impact_json, reason
        ) VALUES (
            :event_ts, :actor, :actor_type, :entity_type, :entity_id, :ticker,
            :assumption_name, :scope, :event_type, :prior_diff_json, :new_diff_json,
            :changed_fields_json, :valuation_impact_json, :reason
        )
        """,
        payload,
    )
    conn.commit()


def load_assumption_register_audit_history(
    conn: sqlite3.Connection,
    ticker: str,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Load Assumption Register audit history separately from PM override audit."""
    rows = conn.execute(
        """
        SELECT event_ts, actor, actor_type, entity_type, entity_id, ticker,
               assumption_name, scope, event_type, prior_diff_json, new_diff_json,
               changed_fields_json, valuation_impact_json, reason
        FROM assumption_register_audit
        WHERE ticker = ?
        ORDER BY event_ts DESC, id DESC
        LIMIT ?
        """,
        [str(ticker).upper(), max(1, int(limit))],
    ).fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        item["prior_diff"] = json.loads(item["prior_diff_json"] or "{}")
        item["new_diff"] = json.loads(item["new_diff_json"] or "{}")
        item["changed_fields"] = json.loads(item["changed_fields_json"] or "{}")
        item["valuation_impact"] = (
            json.loads(item["valuation_impact_json"])
            if item.get("valuation_impact_json")
            else None
        )
        out.append(item)
    return out


def insert_valuation_policy_version(conn: sqlite3.Connection, row: dict[str, Any]) -> int:
    """Append a PM-editable valuation policy version and return its id."""
    cursor = conn.execute(
        """
        INSERT INTO valuation_policy_versions (
            created_at, actor, global_defaults_json, sector_defaults_json, source_ref, notes
        ) VALUES (
            :created_at, :actor, :global_defaults_json, :sector_defaults_json, :source_ref, :notes
        )
        """,
        row,
    )
    conn.commit()
    return int(cursor.lastrowid)


def load_latest_valuation_policy_version(conn: sqlite3.Connection) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT id, created_at, actor, global_defaults_json, sector_defaults_json, source_ref, notes
        FROM valuation_policy_versions
        ORDER BY id DESC
        LIMIT 1
        """
    ).fetchone()
    if row is None:
        return None
    item = dict(row)
    item["global_defaults"] = json.loads(item.pop("global_defaults_json") or "{}")
    item["sector_defaults"] = json.loads(item.pop("sector_defaults_json") or "{}")
    return item


def upsert_damodaran_policy_drafts(conn: sqlite3.Connection, rows: list[dict[str, Any]]) -> int:
    """Upsert parsed Damodaran drop-folder rows as reviewable drafts."""
    if not rows:
        return 0
    payload: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        item["raw_json"] = json.dumps(item.get("raw") or {}, separators=(",", ":"))
        payload.append(item)
    conn.executemany(
        """
        INSERT INTO damodaran_policy_drafts (
            created_at, source_file, source_kind, row_key, field, value, unit,
            source_date, status, raw_json
        ) VALUES (
            :created_at, :source_file, :source_kind, :row_key, :field, :value, :unit,
            :source_date, :status, :raw_json
        )
        ON CONFLICT(source_file, row_key, field) DO UPDATE SET
            created_at = excluded.created_at,
            source_kind = excluded.source_kind,
            value = excluded.value,
            unit = excluded.unit,
            source_date = excluded.source_date,
            raw_json = excluded.raw_json
        """,
        payload,
    )
    conn.commit()
    return len(payload)


def load_damodaran_policy_drafts(
    conn: sqlite3.Connection,
    status: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    where = "WHERE status = ?" if status else ""
    params: list[Any] = [status] if status else []
    params.append(max(1, int(limit)))
    rows = conn.execute(
        f"""
        SELECT id, created_at, source_file, source_kind, row_key, field, value,
               unit, source_date, status, raw_json
        FROM damodaran_policy_drafts
        {where}
        ORDER BY created_at DESC, id DESC
        LIMIT ?
        """,
        params,
    ).fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        item["raw"] = json.loads(item.pop("raw_json") or "{}")
        out.append(item)
    return out


def insert_evidence_packet(conn: sqlite3.Connection, row: dict[str, Any]) -> int:
    item = dict(row)
    item["ticker"] = str(item["ticker"]).upper()
    item["source_refs_json"] = json.dumps(item.get("source_refs") or [], separators=(",", ":"))
    item["facts_json"] = json.dumps(item.get("facts") or [], separators=(",", ":"))
    item["snippets_json"] = json.dumps(item.get("snippets") or [], separators=(",", ":"))
    item["observations_json"] = json.dumps(item.get("observations") or [], separators=(",", ":"))
    item["run_metadata_json"] = json.dumps(item.get("run_metadata") or {}, separators=(",", ":"))
    cursor = conn.execute(
        """
        INSERT INTO evidence_packets (
            created_at, updated_at, ticker, profile_name, packet_kind, bundle_id, generated_at,
            source_refs_json, facts_json, snippets_json, observations_json, run_metadata_json
        ) VALUES (
            :created_at, :updated_at, :ticker, :profile_name, :packet_kind, :bundle_id, :generated_at,
            :source_refs_json, :facts_json, :snippets_json, :observations_json, :run_metadata_json
        )
        """,
        item,
    )
    conn.commit()
    return int(cursor.lastrowid)


def load_evidence_packet(conn: sqlite3.Connection, packet_id: int) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT id, created_at, updated_at, ticker, profile_name, packet_kind, bundle_id, generated_at,
               source_refs_json, facts_json, snippets_json, observations_json, run_metadata_json
        FROM evidence_packets
        WHERE id = ?
        """,
        [int(packet_id)],
    ).fetchone()
    if row is None:
        return None
    item = dict(row)
    item["packet_id"] = item.pop("id")
    item["source_refs"] = json.loads(item.pop("source_refs_json") or "[]")
    item["facts"] = json.loads(item.pop("facts_json") or "[]")
    item["snippets"] = json.loads(item.pop("snippets_json") or "[]")
    item["observations"] = json.loads(item.pop("observations_json") or "[]")
    item["run_metadata"] = json.loads(item.pop("run_metadata_json") or "{}")
    return item


def update_evidence_packet_run(
    conn: sqlite3.Connection,
    packet_id: int,
    *,
    updated_at: str,
    observations: list[dict[str, Any]] | None = None,
    run_metadata_updates: dict[str, Any] | None = None,
) -> dict[str, Any]:
    existing = load_evidence_packet(conn, packet_id)
    if existing is None:
        raise ValueError(f"evidence packet not found: {packet_id}")

    next_observations = observations if observations is not None else list(existing.get("observations") or [])
    next_run_metadata = dict(existing.get("run_metadata") or {})
    next_run_metadata.update(run_metadata_updates or {})

    conn.execute(
        """
        UPDATE evidence_packets
        SET updated_at = ?, observations_json = ?, run_metadata_json = ?
        WHERE id = ?
        """,
        [
            updated_at,
            json.dumps(next_observations, separators=(",", ":")),
            json.dumps(next_run_metadata, separators=(",", ":")),
            int(packet_id),
        ],
    )
    conn.commit()
    updated = load_evidence_packet(conn, packet_id)
    if updated is None:
        raise ValueError(f"evidence packet not found after update: {packet_id}")
    return updated


def list_evidence_packets(
    conn: sqlite3.Connection,
    *,
    ticker: str,
    packet_kind: str | None = None,
) -> list[dict[str, Any]]:
    params: list[Any] = [str(ticker).upper()]
    where = "WHERE ticker = ?"
    if packet_kind:
        where += " AND packet_kind = ?"
        params.append(packet_kind)
    rows = conn.execute(
        f"""
        SELECT id, created_at, updated_at, ticker, profile_name, packet_kind, bundle_id, generated_at,
               source_refs_json, facts_json, snippets_json, observations_json, run_metadata_json
        FROM evidence_packets
        {where}
        ORDER BY generated_at DESC, id DESC
        """,
        params,
    ).fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        item["packet_id"] = item.pop("id")
        item["source_refs"] = json.loads(item.pop("source_refs_json") or "[]")
        item["facts"] = json.loads(item.pop("facts_json") or "[]")
        item["snippets"] = json.loads(item.pop("snippets_json") or "[]")
        item["observations"] = json.loads(item.pop("observations_json") or "[]")
        item["run_metadata"] = json.loads(item.pop("run_metadata_json") or "{}")
        out.append(item)
    return out


def _pm_queue_row_to_dict(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    item = dict(row)
    item["item_id"] = item.pop("id")
    item["evidence_anchor_ids"] = json.loads(item.pop("evidence_anchor_ids_json") or "[]")
    item["evidence_packet_ids"] = json.loads(item.pop("evidence_packet_ids_json") or "[]")
    item["proposal_pack"] = (
        json.loads(item.pop("proposal_pack_json"))
        if item.get("proposal_pack_json")
        else None
    )
    item["pm_edited_proposal_pack"] = (
        json.loads(item.pop("pm_edited_proposal_pack_json"))
        if item.get("pm_edited_proposal_pack_json")
        else None
    )
    item["approved_proposal_pack"] = (
        json.loads(item.pop("approved_proposal_pack_json"))
        if item.get("approved_proposal_pack_json")
        else None
    )
    item["valuation_impact"] = (
        json.loads(item.pop("valuation_impact_json"))
        if item.get("valuation_impact_json")
        else None
    )
    item["adapter_links"] = json.loads(item.pop("adapter_links_json") or "{}")
    item["decision_history"] = json.loads(item.pop("decision_history_json") or "[]")
    item["metadata"] = json.loads(item.pop("metadata_json") or "{}")
    return item


def _find_duplicate_pm_queue_item(conn: sqlite3.Connection, item: dict[str, Any]) -> dict[str, Any] | None:
    observation_id = str((item.get("metadata") or {}).get("observation_id") or "").strip()
    packet_ids = {str(value) for value in (item.get("evidence_packet_ids") or []) if str(value).strip()}
    if not observation_id or not packet_ids:
        return None
    rows = conn.execute(
        """
        SELECT id, created_at, updated_at, ticker, profile_name, item_type, status,
               qualitative_importance, valuation_impact_bucket, title, summary,
               evidence_anchor_ids_json, evidence_packet_ids_json, proposal_pack_json,
               pm_edited_proposal_pack_json, approved_proposal_pack_json,
               agent_confidence, translator_confidence, pm_confidence, valuation_impact_json,
               adapter_links_json, decision_history_json, metadata_json
        FROM pm_decision_queue_items
        WHERE ticker = ?
        ORDER BY id DESC
        """,
        [str(item.get("ticker") or "").upper()],
    ).fetchall()
    for row in rows:
        existing = _pm_queue_row_to_dict(row)
        existing_observation_id = str((existing.get("metadata") or {}).get("observation_id") or "").strip()
        existing_packet_ids = {
            str(value) for value in (existing.get("evidence_packet_ids") or []) if str(value).strip()
        }
        if existing_observation_id == observation_id and packet_ids.intersection(existing_packet_ids):
            return existing
    return None


def insert_pm_decision_queue_item(conn: sqlite3.Connection, row: dict[str, Any]) -> int:
    item = dict(row)
    item["ticker"] = str(item["ticker"]).upper()
    duplicate = _find_duplicate_pm_queue_item(conn, item)
    if duplicate is not None:
        return int(duplicate["item_id"])
    item["evidence_anchor_ids_json"] = json.dumps(item.get("evidence_anchor_ids") or [], separators=(",", ":"))
    item["evidence_packet_ids_json"] = json.dumps(item.get("evidence_packet_ids") or [], separators=(",", ":"))
    item["proposal_pack_json"] = (
        json.dumps(item.get("proposal_pack"), separators=(",", ":"))
        if item.get("proposal_pack") is not None
        else None
    )
    item["pm_edited_proposal_pack_json"] = (
        json.dumps(item.get("pm_edited_proposal_pack"), separators=(",", ":"))
        if item.get("pm_edited_proposal_pack") is not None
        else None
    )
    item["approved_proposal_pack_json"] = (
        json.dumps(item.get("approved_proposal_pack"), separators=(",", ":"))
        if item.get("approved_proposal_pack") is not None
        else None
    )
    item["valuation_impact_json"] = (
        json.dumps(item.get("valuation_impact"), separators=(",", ":"))
        if item.get("valuation_impact") is not None
        else None
    )
    item["adapter_links_json"] = json.dumps(item.get("adapter_links") or {}, separators=(",", ":"))
    item["decision_history_json"] = json.dumps(item.get("decision_history") or [], separators=(",", ":"))
    item["metadata_json"] = json.dumps(item.get("metadata") or {}, separators=(",", ":"))
    cursor = conn.execute(
        """
        INSERT INTO pm_decision_queue_items (
            created_at, updated_at, ticker, profile_name, item_type, status,
            qualitative_importance, valuation_impact_bucket, title, summary,
            evidence_anchor_ids_json, evidence_packet_ids_json, proposal_pack_json,
            pm_edited_proposal_pack_json, approved_proposal_pack_json,
            agent_confidence, translator_confidence, pm_confidence, valuation_impact_json,
            adapter_links_json, decision_history_json, metadata_json
        ) VALUES (
            :created_at, :updated_at, :ticker, :profile_name, :item_type, :status,
            :qualitative_importance, :valuation_impact_bucket, :title, :summary,
            :evidence_anchor_ids_json, :evidence_packet_ids_json, :proposal_pack_json,
            :pm_edited_proposal_pack_json, :approved_proposal_pack_json,
            :agent_confidence, :translator_confidence, :pm_confidence, :valuation_impact_json,
            :adapter_links_json, :decision_history_json, :metadata_json
        )
        """,
        item,
    )
    conn.commit()
    return int(cursor.lastrowid)


def list_pm_decision_queue_items(
    conn: sqlite3.Connection,
    *,
    ticker: str | None = None,
    status: str | None = None,
    item_type: str | None = None,
    qualitative_importance: str | None = None,
    valuation_impact_bucket: str | None = None,
) -> list[dict[str, Any]]:
    where_clauses: list[str] = []
    params: list[Any] = []
    if ticker:
        where_clauses.append("ticker = ?")
        params.append(str(ticker).upper())
    if status:
        where_clauses.append("status = ?")
        params.append(status)
    if item_type:
        where_clauses.append("item_type = ?")
        params.append(item_type)
    if qualitative_importance:
        where_clauses.append("qualitative_importance = ?")
        params.append(qualitative_importance)
    if valuation_impact_bucket:
        where_clauses.append("valuation_impact_bucket = ?")
        params.append(valuation_impact_bucket)
    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
    rows = conn.execute(
        f"""
        SELECT id, created_at, updated_at, ticker, profile_name, item_type, status,
               qualitative_importance, valuation_impact_bucket, title, summary,
               evidence_anchor_ids_json, evidence_packet_ids_json, proposal_pack_json,
               pm_edited_proposal_pack_json, approved_proposal_pack_json,
               agent_confidence, translator_confidence, pm_confidence, valuation_impact_json,
               adapter_links_json, decision_history_json, metadata_json
        FROM pm_decision_queue_items
        {where_sql}
        ORDER BY
            CASE qualitative_importance
                WHEN 'high' THEN 0
                WHEN 'medium' THEN 1
                WHEN 'low' THEN 2
                ELSE 3
            END ASC,
            updated_at DESC,
            id DESC
        """,
        params,
    ).fetchall()
    return [_pm_queue_row_to_dict(row) for row in rows]


def update_pm_decision_queue_item(
    conn: sqlite3.Connection,
    *,
    item_id: int,
    updates: dict[str, Any],
) -> dict[str, Any]:
    if not updates:
        row = conn.execute(
            "SELECT * FROM pm_decision_queue_items WHERE id = ?",
            [int(item_id)],
        ).fetchone()
        if row is None:
            raise ValueError(f"queue item not found: {item_id}")
        return _pm_queue_row_to_dict(row)

    column_map: dict[str, str] = {
        "updated_at": "updated_at",
        "status": "status",
        "qualitative_importance": "qualitative_importance",
        "valuation_impact_bucket": "valuation_impact_bucket",
        "title": "title",
        "summary": "summary",
        "agent_confidence": "agent_confidence",
        "translator_confidence": "translator_confidence",
        "pm_confidence": "pm_confidence",
    }
    json_column_map: dict[str, str] = {
        "evidence_anchor_ids": "evidence_anchor_ids_json",
        "evidence_packet_ids": "evidence_packet_ids_json",
        "proposal_pack": "proposal_pack_json",
        "pm_edited_proposal_pack": "pm_edited_proposal_pack_json",
        "approved_proposal_pack": "approved_proposal_pack_json",
        "valuation_impact": "valuation_impact_json",
        "adapter_links": "adapter_links_json",
        "decision_history": "decision_history_json",
        "metadata": "metadata_json",
    }
    set_clauses: list[str] = []
    params: list[Any] = []
    for key, value in updates.items():
        if key in column_map:
            set_clauses.append(f"{column_map[key]} = ?")
            params.append(value)
        elif key in json_column_map:
            set_clauses.append(f"{json_column_map[key]} = ?")
            if value is None and key in {"proposal_pack", "pm_edited_proposal_pack", "approved_proposal_pack", "valuation_impact"}:
                params.append(None)
            else:
                default_value: Any = {} if key in {"adapter_links", "metadata"} else []
                params.append(json.dumps(value if value is not None else default_value, separators=(",", ":")))
    if "updated_at" not in updates:
        set_clauses.append("updated_at = ?")
        params.append(_now())
    if not set_clauses:
        raise ValueError("no supported fields in updates")
    params.append(int(item_id))
    conn.execute(
        f"""
        UPDATE pm_decision_queue_items
        SET {", ".join(set_clauses)}
        WHERE id = ?
        """,
        params,
    )
    conn.commit()
    row = conn.execute(
        "SELECT * FROM pm_decision_queue_items WHERE id = ?",
        [int(item_id)],
    ).fetchone()
    if row is None:
        raise ValueError(f"queue item not found: {item_id}")
    return _pm_queue_row_to_dict(row)


def insert_pm_decision_queue_event(conn: sqlite3.Connection, row: dict[str, Any]) -> int:
    item = dict(row)
    item["ticker"] = str(item["ticker"]).upper()
    item["payload_json"] = json.dumps(item.get("payload") or {}, separators=(",", ":"))
    cursor = conn.execute(
        """
        INSERT INTO pm_decision_queue_events (
            created_at, item_id, ticker, event_type, actor, payload_json
        ) VALUES (
            :created_at, :item_id, :ticker, :event_type, :actor, :payload_json
        )
        """,
        item,
    )
    conn.commit()
    return int(cursor.lastrowid)


def insert_pending_assumption_change(conn: sqlite3.Connection, row: dict[str, Any]) -> int:
    item = dict(row)
    item["ticker"] = str(item["ticker"]).upper()
    item["metadata_json"] = json.dumps(item.get("metadata") or {}, separators=(",", ":"))
    cursor = conn.execute(
        """
        INSERT INTO pending_assumption_changes (
            created_at, updated_at, ticker, assumption_name, current_value, proposed_value,
            source_type, source_ref, confidence, rationale, citation, status,
            approval_ref, applied_at, metadata_json
        ) VALUES (
            :created_at, :updated_at, :ticker, :assumption_name, :current_value, :proposed_value,
            :source_type, :source_ref, :confidence, :rationale, :citation, :status,
            :approval_ref, :applied_at, :metadata_json
        )
        """,
        item,
    )
    conn.commit()
    return int(cursor.lastrowid)


def load_pending_assumption_changes(
    conn: sqlite3.Connection,
    ticker: str,
    status: str | None = "pending",
) -> list[dict[str, Any]]:
    params: list[Any] = [str(ticker).upper()]
    where = "WHERE ticker = ?"
    if status:
        where += " AND status = ?"
        params.append(status)
    rows = conn.execute(
        f"""
        SELECT id, created_at, updated_at, ticker, assumption_name, current_value,
               proposed_value, source_type, source_ref, confidence, rationale,
               citation, status, approval_ref, applied_at, metadata_json
        FROM pending_assumption_changes
        {where}
        ORDER BY updated_at DESC, id DESC
        """,
        params,
    ).fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        item["metadata"] = json.loads(item.pop("metadata_json") or "{}")
        item["change_id"] = item.pop("id")
        out.append(item)
    return out


def approve_pending_assumption_changes(
    conn: sqlite3.Connection,
    *,
    ticker: str,
    change_ids: list[int],
    actor: str,
    applied_at: str,
    approval_ref: str,
) -> list[dict[str, Any]]:
    """Mark selected pending changes as approved without mutating active assumptions."""
    if not change_ids:
        return []
    ticker = str(ticker).upper()
    placeholders = ",".join("?" for _ in change_ids)
    rows = conn.execute(
        f"""
        SELECT id, ticker, assumption_name, proposed_value, source_type, source_ref, metadata_json
        FROM pending_assumption_changes
        WHERE ticker = ? AND status = 'pending' AND id IN ({placeholders})
        ORDER BY id
        """,
        [ticker, *change_ids],
    ).fetchall()
    approved = [dict(row) for row in rows]
    if not approved:
        return []
    with conn:
        for row in approved:
            conn.execute(
                """
                UPDATE pending_assumption_changes
                SET status = 'approved', updated_at = ?, approval_ref = ?
                WHERE id = ?
                """,
                [applied_at, approval_ref, row["id"]],
            )
    for row in approved:
        row["metadata"] = json.loads(row.pop("metadata_json") or "{}")
        row["change_id"] = row.pop("id")
        row["approval_ref"] = approval_ref
        row["applied_at"] = None
    return approved


def apply_approved_assumption_changes(
    conn: sqlite3.Connection,
    *,
    ticker: str,
    change_ids: list[int],
    actor: str,
    applied_at: str,
) -> list[dict[str, Any]]:
    if not change_ids:
        return []
    ticker = str(ticker).upper()
    placeholders = ",".join("?" for _ in change_ids)
    rows = conn.execute(
        f"""
        SELECT id, ticker, assumption_name, proposed_value, source_type, source_ref, metadata_json, approval_ref
        FROM pending_assumption_changes
        WHERE ticker = ? AND status = 'approved' AND id IN ({placeholders})
        ORDER BY id
        """,
        [ticker, *change_ids],
    ).fetchall()
    approved = [dict(row) for row in rows]
    if not approved:
        return []
    with conn:
        for row in approved:
            conn.execute(
                """
                UPDATE approved_assumption_entries
                SET active = 0
                WHERE ticker = ? AND assumption_name = ? AND active = 1
                """,
                [ticker, row["assumption_name"]],
            )
            conn.execute(
                """
                INSERT INTO approved_assumption_entries (
                    applied_at, ticker, assumption_name, value, source_type,
                    source_ref, approval_ref, actor, metadata_json, active
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                """,
                [
                    applied_at,
                    ticker,
                    row["assumption_name"],
                    row["proposed_value"],
                    row["source_type"],
                    row["source_ref"],
                    row.get("approval_ref"),
                    actor,
                    row["metadata_json"] or "{}",
                ],
            )
            conn.execute(
                """
                UPDATE pending_assumption_changes
                SET status = 'applied', updated_at = ?, applied_at = ?
                WHERE id = ? AND status = 'approved'
                """,
                [applied_at, applied_at, row["id"]],
            )
    for row in approved:
        row["metadata"] = json.loads(row.pop("metadata_json") or "{}")
        row["change_id"] = row.pop("id")
        row["applied_at"] = applied_at
    return approved


def reject_pending_assumption_changes(
    conn: sqlite3.Connection,
    *,
    ticker: str,
    change_ids: list[int],
    actor: str,
    rejected_at: str,
) -> int:
    if not change_ids:
        return 0
    placeholders = ",".join("?" for _ in change_ids)
    cursor = conn.execute(
        f"""
        UPDATE pending_assumption_changes
        SET status = 'rejected', updated_at = ?
        WHERE ticker = ? AND status = 'pending' AND id IN ({placeholders})
        """,
        [rejected_at, str(ticker).upper(), *change_ids],
    )
    conn.commit()
    return int(cursor.rowcount or 0)


def defer_pending_assumption_changes(
    conn: sqlite3.Connection,
    *,
    ticker: str,
    change_ids: list[int],
    deferred_at: str,
) -> int:
    if not change_ids:
        return 0
    placeholders = ",".join("?" for _ in change_ids)
    cursor = conn.execute(
        f"""
        UPDATE pending_assumption_changes
        SET status = 'deferred', updated_at = ?
        WHERE ticker = ? AND status = 'pending' AND id IN ({placeholders})
        """,
        [deferred_at, str(ticker).upper(), *change_ids],
    )
    conn.commit()
    return int(cursor.rowcount or 0)


def load_approved_assumption_entries(conn: sqlite3.Connection, ticker: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT id, applied_at, ticker, assumption_name, value, source_type, source_ref,
               approval_ref, actor, metadata_json
        FROM approved_assumption_entries
        WHERE ticker = ? AND active = 1
        ORDER BY applied_at DESC, id DESC
        """,
        [str(ticker).upper()],
    ).fetchall()
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        item = dict(row)
        if item["assumption_name"] in seen:
            continue
        seen.add(item["assumption_name"])
        item["metadata"] = json.loads(item.pop("metadata_json") or "{}")
        out.append(item)
    return out


def insert_pipeline_report_archive(conn: sqlite3.Connection, row: dict[str, Any]) -> int:
    """Append a dashboard report snapshot and return its row id."""
    cursor = conn.execute(
        """
        INSERT INTO pipeline_report_archive (
            ticker,
            created_at,
            run_group_ts,
            company_name,
            sector,
            action,
            conviction,
            current_price,
            base_iv,
            memo_json,
            dashboard_snapshot_json,
            run_trace_json
        ) VALUES (
            :ticker,
            :created_at,
            :run_group_ts,
            :company_name,
            :sector,
            :action,
            :conviction,
            :current_price,
            :base_iv,
            :memo_json,
            :dashboard_snapshot_json,
            :run_trace_json
        )
        """,
        row,
    )
    conn.commit()
    return int(cursor.lastrowid)


def upsert_dossier_profile(conn: sqlite3.Connection, row: dict[str, Any]) -> None:
    """Insert or update dossier profile metadata for a ticker."""
    row = dict(row)
    row["ticker"] = str(row["ticker"]).upper()
    row.setdefault("initialized_at", _now())
    row.setdefault("updated_at", _now())
    conn.execute(
        """
        INSERT INTO dossier_profiles (
            ticker,
            company_name,
            dossier_root_path,
            notes_root_path,
            model_root_path,
            exports_root_path,
            status,
            current_model_version,
            current_thesis_version,
            current_publishable_memo_version,
            initialized_at,
            updated_at
        ) VALUES (
            :ticker,
            :company_name,
            :dossier_root_path,
            :notes_root_path,
            :model_root_path,
            :exports_root_path,
            :status,
            :current_model_version,
            :current_thesis_version,
            :current_publishable_memo_version,
            :initialized_at,
            :updated_at
        )
        ON CONFLICT(ticker) DO UPDATE SET
            company_name = excluded.company_name,
            dossier_root_path = excluded.dossier_root_path,
            notes_root_path = excluded.notes_root_path,
            model_root_path = excluded.model_root_path,
            exports_root_path = excluded.exports_root_path,
            status = excluded.status,
            current_model_version = excluded.current_model_version,
            current_thesis_version = excluded.current_thesis_version,
            current_publishable_memo_version = excluded.current_publishable_memo_version,
            updated_at = excluded.updated_at
        """,
        row,
    )
    conn.commit()


def upsert_dossier_section_index(conn: sqlite3.Connection, row: dict[str, Any]) -> None:
    """Insert or update dossier note index metadata."""
    row = dict(row)
    row["ticker"] = str(row["ticker"]).upper()
    row.setdefault("is_private", 0)
    row.setdefault("last_synced_at", _now())
    conn.execute(
        """
        INSERT INTO dossier_sections (
            ticker,
            note_slug,
            note_title,
            relative_path,
            section_kind,
            is_private,
            last_synced_at,
            content_hash,
            metadata_json
        ) VALUES (
            :ticker,
            :note_slug,
            :note_title,
            :relative_path,
            :section_kind,
            :is_private,
            :last_synced_at,
            :content_hash,
            :metadata_json
        )
        ON CONFLICT(ticker, note_slug) DO UPDATE SET
            note_title = excluded.note_title,
            relative_path = excluded.relative_path,
            section_kind = excluded.section_kind,
            is_private = excluded.is_private,
            last_synced_at = excluded.last_synced_at,
            content_hash = excluded.content_hash,
            metadata_json = excluded.metadata_json
        """,
        row,
    )
    conn.commit()


def upsert_dossier_source(conn: sqlite3.Connection, row: dict[str, Any]) -> None:
    """Insert or update dossier source metadata."""
    row = dict(row)
    row["ticker"] = str(row["ticker"]).upper()
    row.setdefault("created_at", _now())
    row.setdefault("updated_at", _now())
    conn.execute(
        """
        INSERT INTO dossier_sources (
            ticker,
            source_id,
            title,
            source_type,
            source_date,
            access_date,
            why_it_matters,
            file_path,
            external_uri,
            zotero_key,
            relative_source_note_path,
            supports_json,
            limitations_text,
            created_at,
            updated_at
        ) VALUES (
            :ticker,
            :source_id,
            :title,
            :source_type,
            :source_date,
            :access_date,
            :why_it_matters,
            :file_path,
            :external_uri,
            :zotero_key,
            :relative_source_note_path,
            :supports_json,
            :limitations_text,
            :created_at,
            :updated_at
        )
        ON CONFLICT(ticker, source_id) DO UPDATE SET
            title = excluded.title,
            source_type = excluded.source_type,
            source_date = excluded.source_date,
            access_date = excluded.access_date,
            why_it_matters = excluded.why_it_matters,
            file_path = excluded.file_path,
            external_uri = excluded.external_uri,
            zotero_key = excluded.zotero_key,
            relative_source_note_path = excluded.relative_source_note_path,
            supports_json = excluded.supports_json,
            limitations_text = excluded.limitations_text,
            updated_at = excluded.updated_at
        """,
        row,
    )
    conn.commit()


def upsert_dossier_artifact(conn: sqlite3.Connection, row: dict[str, Any]) -> None:
    """Insert or update linked dossier artifact metadata."""
    row = dict(row)
    row["ticker"] = str(row["ticker"]).upper()
    row.setdefault("is_private", 0)
    row.setdefault("created_at", _now())
    row.setdefault("updated_at", _now())
    conn.execute(
        """
        INSERT INTO dossier_artifacts (
            ticker,
            artifact_key,
            artifact_type,
            title,
            path_mode,
            path_value,
            source_id,
            linked_note_slug,
            linked_snapshot_id,
            model_version,
            is_private,
            created_at,
            updated_at,
            metadata_json
        ) VALUES (
            :ticker,
            :artifact_key,
            :artifact_type,
            :title,
            :path_mode,
            :path_value,
            :source_id,
            :linked_note_slug,
            :linked_snapshot_id,
            :model_version,
            :is_private,
            :created_at,
            :updated_at,
            :metadata_json
        )
        ON CONFLICT(ticker, artifact_key) DO UPDATE SET
            artifact_type = excluded.artifact_type,
            title = excluded.title,
            path_mode = excluded.path_mode,
            path_value = excluded.path_value,
            source_id = excluded.source_id,
            linked_note_slug = excluded.linked_note_slug,
            linked_snapshot_id = excluded.linked_snapshot_id,
            model_version = excluded.model_version,
            is_private = excluded.is_private,
            updated_at = excluded.updated_at,
            metadata_json = excluded.metadata_json
        """,
        row,
    )
    conn.commit()


def insert_model_checkpoint(conn: sqlite3.Connection, row: dict[str, Any]) -> int:
    """Append a dossier model checkpoint and return its row id."""
    row = dict(row)
    row["ticker"] = str(row["ticker"]).upper()
    cursor = conn.execute(
        """
        INSERT INTO dossier_model_checkpoints (
            ticker,
            checkpoint_ts,
            model_version,
            artifact_key,
            snapshot_id,
            valuation_json,
            drivers_summary_json,
            change_reason,
            thesis_version,
            source_ids_json,
            created_by
        ) VALUES (
            :ticker,
            :checkpoint_ts,
            :model_version,
            :artifact_key,
            :snapshot_id,
            :valuation_json,
            :drivers_summary_json,
            :change_reason,
            :thesis_version,
            :source_ids_json,
            :created_by
        )
        """,
        row,
    )
    conn.commit()
    return int(cursor.lastrowid)


def upsert_tracker_state(conn: sqlite3.Connection, row: dict[str, Any]) -> None:
    """Insert or update current dossier tracker state."""
    row = dict(row)
    row["ticker"] = str(row["ticker"]).upper()
    conn.execute(
        """
        INSERT INTO dossier_tracker_state (
            ticker,
            overall_status,
            pm_action,
            pm_conviction,
            summary_note,
            pillar_states_json,
            open_questions_json,
            last_reviewed_at,
            latest_snapshot_id,
            metadata_json
        ) VALUES (
            :ticker,
            :overall_status,
            :pm_action,
            :pm_conviction,
            :summary_note,
            :pillar_states_json,
            :open_questions_json,
            :last_reviewed_at,
            :latest_snapshot_id,
            :metadata_json
        )
        ON CONFLICT(ticker) DO UPDATE SET
            overall_status = excluded.overall_status,
            pm_action = excluded.pm_action,
            pm_conviction = excluded.pm_conviction,
            summary_note = excluded.summary_note,
            pillar_states_json = excluded.pillar_states_json,
            open_questions_json = excluded.open_questions_json,
            last_reviewed_at = excluded.last_reviewed_at,
            latest_snapshot_id = excluded.latest_snapshot_id,
            metadata_json = excluded.metadata_json
        """,
        row,
    )
    conn.commit()


def upsert_tracked_catalyst(conn: sqlite3.Connection, row: dict[str, Any]) -> None:
    """Insert or update dossier catalyst state."""
    row = dict(row)
    row["ticker"] = str(row["ticker"]).upper()
    row.setdefault("updated_at", _now())
    conn.execute(
        """
        INSERT INTO dossier_catalysts (
            ticker,
            catalyst_key,
            title,
            description,
            priority,
            status,
            expected_date,
            expected_window_start,
            expected_window_end,
            status_reason,
            source_origin,
            source_snapshot_id,
            updated_at,
            evidence_json
        ) VALUES (
            :ticker,
            :catalyst_key,
            :title,
            :description,
            :priority,
            :status,
            :expected_date,
            :expected_window_start,
            :expected_window_end,
            :status_reason,
            :source_origin,
            :source_snapshot_id,
            :updated_at,
            :evidence_json
        )
        ON CONFLICT(ticker, catalyst_key) DO UPDATE SET
            title = excluded.title,
            description = excluded.description,
            priority = excluded.priority,
            status = excluded.status,
            expected_date = excluded.expected_date,
            expected_window_start = excluded.expected_window_start,
            expected_window_end = excluded.expected_window_end,
            status_reason = excluded.status_reason,
            source_origin = excluded.source_origin,
            source_snapshot_id = excluded.source_snapshot_id,
            updated_at = excluded.updated_at,
            evidence_json = excluded.evidence_json
        """,
        row,
    )
    conn.commit()


def insert_decision_log_entry(conn: sqlite3.Connection, row: dict[str, Any]) -> int:
    """Append a dossier decision-log entry."""
    row = dict(row)
    row["ticker"] = str(row["ticker"]).upper()
    cursor = conn.execute(
        """
        INSERT INTO dossier_decision_log (
            ticker,
            decision_ts,
            decision_title,
            action,
            conviction,
            beliefs_text,
            evidence_text,
            assumptions_text,
            falsifiers_text,
            review_due_date,
            snapshot_id,
            model_checkpoint_id,
            private_notes_text,
            created_by
        ) VALUES (
            :ticker,
            :decision_ts,
            :decision_title,
            :action,
            :conviction,
            :beliefs_text,
            :evidence_text,
            :assumptions_text,
            :falsifiers_text,
            :review_due_date,
            :snapshot_id,
            :model_checkpoint_id,
            :private_notes_text,
            :created_by
        )
        """,
        row,
    )
    conn.commit()
    return int(cursor.lastrowid)


def insert_review_log_entry(conn: sqlite3.Connection, row: dict[str, Any]) -> int:
    """Append a dossier review-log entry."""
    row = dict(row)
    row["ticker"] = str(row["ticker"]).upper()
    cursor = conn.execute(
        """
        INSERT INTO dossier_review_log (
            ticker,
            review_ts,
            review_title,
            period_type,
            expectations_vs_outcomes_text,
            factual_error_text,
            interpretive_error_text,
            behavioral_error_text,
            thesis_status,
            model_status,
            action_taken_text,
            linked_decision_id,
            linked_snapshot_id,
            private_notes_text,
            created_by
        ) VALUES (
            :ticker,
            :review_ts,
            :review_title,
            :period_type,
            :expectations_vs_outcomes_text,
            :factual_error_text,
            :interpretive_error_text,
            :behavioral_error_text,
            :thesis_status,
            :model_status,
            :action_taken_text,
            :linked_decision_id,
            :linked_snapshot_id,
            :private_notes_text,
            :created_by
        )
        """,
        row,
    )
    conn.commit()
    return int(cursor.lastrowid)


def insert_dossier_note_block(conn: sqlite3.Connection, row: dict[str, Any]) -> int:
    """Append a durable dossier note block."""
    row = dict(row)
    row["ticker"] = str(row["ticker"]).upper()
    row.setdefault("linked_sources_json", "[]")
    row.setdefault("linked_artifacts_json", "[]")
    row.setdefault("status", "active")
    row.setdefault("pinned_to_report", 0)
    cursor = conn.execute(
        """
        INSERT INTO dossier_note_blocks (
            ticker,
            block_ts,
            block_type,
            title,
            body,
            source_context_json,
            linked_snapshot_id,
            linked_sources_json,
            linked_artifacts_json,
            status,
            pinned_to_report,
            created_by
        ) VALUES (
            :ticker,
            :block_ts,
            :block_type,
            :title,
            :body,
            :source_context_json,
            :linked_snapshot_id,
            :linked_sources_json,
            :linked_artifacts_json,
            :status,
            :pinned_to_report,
            :created_by
        )
        """,
        row,
    )
    conn.commit()
    return int(cursor.lastrowid)


# ---------------------------------------------------------------------------
# Convenience helpers — used by valuation layer (stage_02) to avoid importing
# stage_04 pipeline modules.
# ---------------------------------------------------------------------------

def get_valuation_policy_rf_erp() -> tuple[float, float]:
    """Return (risk_free_rate, equity_risk_premium) from the latest saved policy.

    Falls back to (0.045, 0.05) if no policy has been saved yet.
    """
    try:
        from db.schema import create_tables, get_connection
        with get_connection() as conn:
            create_tables(conn)
            row = load_latest_valuation_policy_version(conn)
    except Exception:
        row = None
    if not row:
        return 0.045, 0.05
    g = row.get("global_defaults") or {}
    rf = float(g.get("risk_free_rate", 0.045))
    erp = float(g.get("equity_risk_premium", 0.05))
    return rf, erp


def get_valuation_policy_sector_defaults(sector: str) -> dict[str, float]:
    """Return saved sector-level defaults for *sector*, or {} if none saved."""
    try:
        from db.schema import create_tables, get_connection
        with get_connection() as conn:
            create_tables(conn)
            row = load_latest_valuation_policy_version(conn)
    except Exception:
        row = None
    if not row:
        return {}
    sector_map: dict[str, dict[str, float]] = row.get("sector_defaults") or {}
    return dict(sector_map.get(sector) or {})


def get_approved_assumption_overrides(ticker: str) -> dict[str, float]:
    """Return active approved assumption overrides for *ticker* as {name: value}."""
    try:
        from db.schema import create_tables, get_connection
        with get_connection() as conn:
            create_tables(conn)
            rows = load_approved_assumption_entries(conn, ticker)
    except Exception:
        return {}
    return {row["assumption_name"]: float(row["value"]) for row in rows}
