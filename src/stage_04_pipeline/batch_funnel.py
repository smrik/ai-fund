"""Dashboard-facing helpers for deterministic batch valuation funnels."""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Iterable
from typing import Any

from db.schema import create_tables, get_connection

logger = logging.getLogger(__name__)

DEFAULT_SHORTLIST_SIZE = 10


def _safe_float(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) else None


def _score_row(row: dict[str, Any]) -> tuple[int, int, float, float, str]:
    expected_upside = _safe_float(row.get("expected_upside_pct"))
    fallback_upside = _safe_float(row.get("upside_base_pct"))
    margin_of_safety = _safe_float(row.get("margin_of_safety")) or float("-inf")
    ranking_metric = "expected_upside_pct" if expected_upside is not None else "upside_base_pct"
    score = expected_upside if expected_upside is not None else fallback_upside
    return (
        1 if score is not None else 0,
        1 if expected_upside is not None else 0,
        score if score is not None else float("-inf"),
        margin_of_safety,
        ranking_metric,
    )


def _is_dcf_applicable(row: dict[str, Any]) -> bool:
    return (row.get("model_applicability_status") or "").strip().lower() == "dcf_applicable"


def _watchlist_sort_key(row: dict[str, Any]) -> tuple[int, int, int, float, float, str]:
    score_present, expected_present, score, margin_of_safety, _ranking_metric = _score_row(row)
    return (
        1 if _is_dcf_applicable(row) else 0,
        score_present,
        expected_present,
        score if score != float("-inf") else float("-inf"),
        margin_of_safety,
        str(row.get("ticker") or ""),
    )


def _rank_watchlist_rows(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    ranked_rows = [dict(row) for row in rows]
    ranked_rows.sort(key=_watchlist_sort_key, reverse=True)
    return ranked_rows


def select_top_candidates(results: Iterable[dict[str, Any]], shortlist_size: int = DEFAULT_SHORTLIST_SIZE) -> list[dict[str, Any]]:
    eligible_rows = [
        dict(row)
        for row in results
        if _is_dcf_applicable(row)
    ]
    eligible_rows.sort(key=_score_row, reverse=True)

    shortlist: list[dict[str, Any]] = []
    for row in eligible_rows[: max(int(shortlist_size), 1)]:
        ranked = dict(row)
        _present, _expected_present, score, _mos, ranking_metric = _score_row(ranked)
        ranked["ranking_metric"] = ranking_metric
        ranked["ranking_value"] = None if score == float("-inf") else score
        shortlist.append(ranked)
    return shortlist


def _load_batch_snapshot_rows(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    try:
        rows = conn.execute(
            """
            SELECT *
            FROM batch_valuations_latest
            """
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    return [dict(row) for row in rows]


def _load_latest_archive_rows(conn: sqlite3.Connection) -> dict[str, dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT
            archive.ticker,
            archive.action,
            archive.conviction,
            archive.created_at
        FROM pipeline_report_archive AS archive
        INNER JOIN (
            SELECT ticker, MAX(created_at) AS latest_created_at
            FROM pipeline_report_archive
            GROUP BY ticker
        ) AS latest
            ON archive.ticker = latest.ticker
           AND archive.created_at = latest.latest_created_at
        ORDER BY archive.ticker ASC, archive.created_at DESC, archive.id DESC
        """
    ).fetchall()
    latest_by_ticker: dict[str, dict[str, Any]] = {}
    for row in rows:
        ticker = str(row["ticker"] or "").upper()
        if ticker and ticker not in latest_by_ticker:
            latest_by_ticker[ticker] = dict(row)
    return latest_by_ticker


def _decorate_watchlist_row(row: dict[str, Any], latest_archives: dict[str, dict[str, Any]]) -> dict[str, Any]:
    ticker = str(row.get("ticker") or "").upper()
    latest = latest_archives.get(ticker) or {}
    score_present, expected_present, score, _margin_of_safety, ranking_metric = _score_row(row)
    decorated = dict(row)
    decorated["ticker"] = ticker
    decorated["latest_action"] = latest.get("action")
    decorated["latest_conviction"] = latest.get("conviction")
    decorated["latest_snapshot_date"] = latest.get("created_at")
    decorated["latest_snapshot_created_at"] = latest.get("created_at")
    decorated["ranking_metric"] = ranking_metric if score_present else None
    decorated["ranking_value"] = score if score_present else None
    decorated["has_expected_upside"] = bool(expected_present)
    return decorated


def load_saved_watchlist(shortlist_size: int = DEFAULT_SHORTLIST_SIZE) -> dict[str, Any]:
    shortlist_size = max(int(shortlist_size), 1)
    with get_connection() as conn:
        create_tables(conn)
        snapshot_rows = _load_batch_snapshot_rows(conn)
        if not snapshot_rows:
            return {
                "rows": [],
                "shortlist": [],
                "shortlist_size": shortlist_size,
                "saved_row_count": 0,
                "universe_row_count": 0,
                "scored_count": 0,
                "selected_tickers": [],
                "default_focus_ticker": None,
                "last_updated": None,
                "results": [],
            }

        latest_archives = _load_latest_archive_rows(conn)

    rows = _rank_watchlist_rows(_decorate_watchlist_row(row, latest_archives) for row in snapshot_rows)
    shortlist = select_top_candidates(rows, shortlist_size=shortlist_size)
    last_updated = max(
        (
            row.get("snapshot_date")
            or row.get("date")
            or row.get("ciq_as_of_date")
            or row.get("ciq_comps_as_of_date")
            for row in rows
            if row.get("snapshot_date") or row.get("date") or row.get("ciq_as_of_date") or row.get("ciq_comps_as_of_date")
        ),
        default=None,
    )
    metadata = {
        "last_updated": last_updated,
        "universe_row_count": len(rows),
        "saved_row_count": len(rows),
        "default_focus_ticker": rows[0].get("ticker") if rows else None,
        "ranked_row_count": len(rows),
        "scored_row_count": len(shortlist),
    }

    return {
        "rows": rows,
        "results": rows,
        "shortlist": shortlist,
        "shortlist_size": shortlist_size,
        "saved_row_count": len(rows),
        "universe_row_count": len(rows),
        "scored_count": len(shortlist),
        "selected_tickers": [row["ticker"] for row in shortlist],
        "default_focus_ticker": rows[0].get("ticker") if rows else None,
        "last_updated": last_updated,
        "metadata": metadata,
    }


def run_deterministic_batch(
    *,
    tickers: list[str] | None = None,
    shortlist_size: int = DEFAULT_SHORTLIST_SIZE,
    export_xlsx: bool = False,
    progress_callback=None,
) -> dict[str, Any]:
    from src.stage_02_valuation.batch_runner import run_batch

    results = run_batch(
        tickers=tickers,
        top_n=max(int(shortlist_size), 1),
        export_xlsx=export_xlsx,
        progress_callback=progress_callback,
    ) or []
    shortlist = select_top_candidates(results, shortlist_size=shortlist_size)
    return {
        "results": results,
        "shortlist": shortlist,
        "shortlist_size": max(int(shortlist_size), 1),
        "universe_size": len(tickers) if tickers is not None else len(results),
        "scored_count": len(shortlist),
        "selected_tickers": [row["ticker"] for row in shortlist],
    }


def load_latest_snapshot_for_ticker(ticker: str) -> dict[str, Any] | None:
    from src.stage_04_pipeline.report_archive import list_report_snapshots, load_report_snapshot

    snapshots = list_report_snapshots(ticker, limit=1)
    if not snapshots:
        return None
    return load_report_snapshot(int(snapshots[0]["id"]))


def _memo_risk_output(memo: Any) -> Any | None:
    if isinstance(memo, dict):
        return memo.get("risk_impact")
    return getattr(memo, "risk_impact", None)


def run_deep_analysis_for_tickers(
    tickers: Iterable[str],
    *,
    use_cache: bool = True,
    force_refresh_agents: Iterable[str] | None = None,
) -> list[dict[str, Any]]:
    from src.stage_04_pipeline.comps_dashboard import build_comps_dashboard_view
    from src.stage_04_pipeline.dcf_audit import build_dcf_audit_view
    from src.stage_04_pipeline.filings_browser import build_filings_browser_view
    from src.stage_04_pipeline.news_materiality import build_news_materiality_view
    from src.stage_04_pipeline.orchestrator import PipelineOrchestrator
    from src.stage_04_pipeline.recommendations import write_recommendations
    from src.stage_04_pipeline.report_archive import save_report_snapshot

    selected = [str(ticker).upper().strip() for ticker in tickers if str(ticker).strip()]
    forced = {item.strip() for item in (force_refresh_agents or []) if item and item.strip()}
    run_rows: list[dict[str, Any]] = []

    for ticker in selected:
        orchestrator = PipelineOrchestrator()
        try:
            memo = orchestrator.run(ticker, use_cache=use_cache, force_refresh_agents=forced)
            recommendations = orchestrator.collect_recommendations(ticker)
            write_recommendations(recommendations)

            dcf_audit_view = build_dcf_audit_view(ticker, risk_output=_memo_risk_output(memo))
            filings_browser_view = build_filings_browser_view(ticker)
            comps_view = build_comps_dashboard_view(ticker)
            market_intel_view = build_news_materiality_view(ticker)
            snapshot_id = save_report_snapshot(
                ticker,
                memo,
                dcf_audit=dcf_audit_view,
                comps_view=comps_view,
                market_intel_view=market_intel_view,
                filings_browser_view=filings_browser_view,
                run_trace=orchestrator.last_run_trace,
            )
            run_rows.append(
                {
                    "ticker": ticker,
                    "status": "ok",
                    "snapshot_id": snapshot_id,
                    "run_trace_steps": len(orchestrator.last_run_trace),
                    "recommendations": recommendations,
                }
            )
        except Exception as exc:
            logger.exception("Deep analysis failed for %s", ticker, extra={"ticker": ticker, "step": "batch_funnel"})
            run_rows.append(
                {
                    "ticker": ticker,
                    "status": "error",
                    "snapshot_id": None,
                    "run_trace_steps": len(orchestrator.last_run_trace),
                    "error": str(exc),
                }
            )
    return run_rows
