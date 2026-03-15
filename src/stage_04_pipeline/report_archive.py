"""Full report archive persistence for reopening prior dashboard states."""
from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from typing import Any

from db.loader import insert_pipeline_report_archive
from db.schema import create_tables, get_connection


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _ensure_schema(conn) -> None:
    create_tables(conn)


def _serialize(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="python")
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, dict):
        return {key: _serialize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_serialize(item) for item in value]
    return value


def _coerce_ticker(value: str) -> str:
    ticker = (value or "").strip().upper()
    if not ticker:
        raise ValueError("ticker is required")
    return ticker


def _extract_base_iv(memo_payload: dict[str, Any]) -> float | None:
    valuation = memo_payload.get("valuation") or {}
    if not isinstance(valuation, dict):
        return None
    base_value = valuation.get("base")
    return float(base_value) if isinstance(base_value, (int, float)) else None


def _extract_current_price(memo_payload: dict[str, Any]) -> float | None:
    valuation = memo_payload.get("valuation") or {}
    if not isinstance(valuation, dict):
        return None
    current_price = valuation.get("current_price")
    return float(current_price) if isinstance(current_price, (int, float)) else None


def _extract_run_group_ts(run_trace: list[dict[str, Any]]) -> str | None:
    if not run_trace:
        return None
    for event in reversed(run_trace):
        if not isinstance(event, dict):
            continue
        for key in ("finished_at", "completed_at", "run_ts", "started_at"):
            value = event.get(key)
            if value:
                return str(value)
    return None


def _build_dashboard_snapshot(
    *,
    dcf_audit: dict | None,
    comps_view: dict | None,
    market_intel_view: dict | None,
    filings_browser_view: dict | None,
) -> dict[str, Any]:
    return {
        "dcf_audit": _serialize(dcf_audit) if dcf_audit is not None else None,
        "comps_view": _serialize(comps_view) if comps_view is not None else None,
        "market_intel_view": _serialize(market_intel_view) if market_intel_view is not None else None,
        "filings_browser_view": _serialize(filings_browser_view) if filings_browser_view is not None else None,
    }


def save_report_snapshot(
    ticker: str,
    memo,
    *,
    dcf_audit: dict | None,
    comps_view: dict | None,
    market_intel_view: dict | None,
    filings_browser_view: dict | None,
    run_trace: list[dict] | None,
) -> int:
    archive_ticker = _coerce_ticker(ticker)
    memo_payload = _serialize(memo)
    dashboard_snapshot = _build_dashboard_snapshot(
        dcf_audit=dcf_audit,
        comps_view=comps_view,
        market_intel_view=market_intel_view,
        filings_browser_view=filings_browser_view,
    )
    trace_payload = _serialize(run_trace or [])
    with get_connection() as conn:
        _ensure_schema(conn)
        return insert_pipeline_report_archive(
            conn,
            {
                "ticker": archive_ticker,
                "created_at": _now(),
                "run_group_ts": _extract_run_group_ts(trace_payload),
                "company_name": memo_payload.get("company_name"),
                "sector": memo_payload.get("sector"),
                "action": memo_payload.get("action"),
                "conviction": memo_payload.get("conviction"),
                "current_price": _extract_current_price(memo_payload),
                "base_iv": _extract_base_iv(memo_payload),
                "memo_json": json.dumps(memo_payload, sort_keys=True),
                "dashboard_snapshot_json": json.dumps(dashboard_snapshot, sort_keys=True),
                "run_trace_json": json.dumps(trace_payload, sort_keys=True),
            },
        )


def list_report_snapshots(ticker: str, limit: int = 50) -> list[dict]:
    archive_ticker = _coerce_ticker(ticker)
    query_limit = max(int(limit), 1)
    with get_connection() as conn:
        _ensure_schema(conn)
        rows = conn.execute(
            """
            SELECT
                id,
                ticker,
                created_at,
                run_group_ts,
                company_name,
                sector,
                action,
                conviction,
                current_price,
                base_iv
            FROM pipeline_report_archive
            WHERE ticker = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            [archive_ticker, query_limit],
        ).fetchall()
    return [dict(row) for row in rows]


def load_report_snapshot(snapshot_id: int) -> dict | None:
    with get_connection() as conn:
        _ensure_schema(conn)
        row = conn.execute(
            """
            SELECT *
            FROM pipeline_report_archive
            WHERE id = ?
            LIMIT 1
            """,
            [snapshot_id],
        ).fetchone()
    if row is None:
        return None
    payload = dict(row)
    return {
        "id": payload["id"],
        "ticker": payload["ticker"],
        "created_at": payload["created_at"],
        "run_group_ts": payload["run_group_ts"],
        "company_name": payload["company_name"],
        "sector": payload["sector"],
        "action": payload["action"],
        "conviction": payload["conviction"],
        "current_price": payload["current_price"],
        "base_iv": payload["base_iv"],
        "memo": json.loads(payload["memo_json"]),
        "dashboard_snapshot": json.loads(payload["dashboard_snapshot_json"]) if payload.get("dashboard_snapshot_json") else {},
        "run_trace": json.loads(payload["run_trace_json"]) if payload.get("run_trace_json") else [],
    }
