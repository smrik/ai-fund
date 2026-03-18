from __future__ import annotations

import json
from typing import Any

from db.schema import create_tables, get_connection
from src.stage_04_pipeline.dossier_workspace import read_dossier_note


def _coerce_ticker(ticker: str) -> str:
    value = (ticker or "").strip().upper()
    if not value:
        raise ValueError("ticker is required")
    return value


def _ensure_schema(conn) -> None:
    create_tables(conn)


def _parse_json(value: Any) -> Any:
    if not value:
        return {}
    if isinstance(value, (dict, list)):
        return value
    try:
        parsed = json.loads(value)
        return parsed if parsed is not None else {}
    except Exception:
        return {}


def _normalize_structured_catalysts(memo_payload: dict[str, Any]) -> list[dict[str, Any]]:
    structured = memo_payload.get("structured_catalysts") or []
    if structured:
        return structured
    return [
        {
            "catalyst_key": f"legacy-catalyst-{idx + 1}",
            "title": title,
            "description": "",
            "expected_window": "",
            "importance": "medium",
        }
        for idx, title in enumerate(memo_payload.get("key_catalysts") or [])
        if title
    ]


def _normalize_thesis_pillars(memo_payload: dict[str, Any]) -> list[dict[str, Any]]:
    pillars = memo_payload.get("thesis_pillars") or []
    if pillars:
        return pillars
    fallback_pairs = [
        ("core_thesis", memo_payload.get("one_liner") or ""),
        ("bull_case", memo_payload.get("bull_case") or ""),
        ("base_case", memo_payload.get("base_case") or ""),
    ]
    return [
        {
            "pillar_id": pillar_id,
            "title": pillar_id.replace("_", " ").title(),
            "description": description,
            "falsifier": "",
            "evidence_basis": "",
        }
        for pillar_id, description in fallback_pairs
        if description
    ]


def _load_archive_snapshots(conn, dossier_ticker: str, limit: int = 2) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT id, created_at, action, conviction, base_iv, memo_json
        FROM pipeline_report_archive
        WHERE ticker = ?
        ORDER BY created_at DESC
        LIMIT ?
        """,
        [dossier_ticker, limit],
    ).fetchall()
    snapshots = []
    for row in rows:
        payload = dict(row)
        memo = _parse_json(payload.get("memo_json"))
        payload["memo"] = memo
        payload["thesis_pillars"] = _normalize_thesis_pillars(memo)
        payload["structured_catalysts"] = _normalize_structured_catalysts(memo)
        snapshots.append(payload)
    return snapshots


def build_model_checkpoint_view(ticker: str) -> dict[str, Any]:
    dossier_ticker = _coerce_ticker(ticker)
    with get_connection() as conn:
        _ensure_schema(conn)
        rows = conn.execute(
            """
            SELECT *
            FROM dossier_model_checkpoints
            WHERE ticker = ?
            ORDER BY checkpoint_ts DESC
            """,
            [dossier_ticker],
        ).fetchall()

    checkpoints = [dict(row) for row in rows]
    if not checkpoints:
        return {"ticker": dossier_ticker, "available": False, "checkpoints": [], "latest_checkpoint": None, "prior_checkpoint": None, "diff": {}}

    latest = dict(checkpoints[0])
    latest["valuation"] = _parse_json(latest.get("valuation_json"))
    latest["drivers_summary"] = _parse_json(latest.get("drivers_summary_json"))
    prior = None
    diff: dict[str, Any] = {}
    if len(checkpoints) > 1:
        prior = dict(checkpoints[1])
        prior["valuation"] = _parse_json(prior.get("valuation_json"))
        prior["drivers_summary"] = _parse_json(prior.get("drivers_summary_json"))
        latest_base = latest["valuation"].get("base_iv")
        prior_base = prior["valuation"].get("base_iv")
        if isinstance(latest_base, (int, float)) and isinstance(prior_base, (int, float)):
            diff["base_iv_delta"] = float(latest_base) - float(prior_base)
    return {
        "ticker": dossier_ticker,
        "available": True,
        "checkpoints": checkpoints,
        "latest_checkpoint": latest,
        "prior_checkpoint": prior,
        "diff": diff,
    }


def build_thesis_diff_view(ticker: str) -> dict[str, Any]:
    dossier_ticker = _coerce_ticker(ticker)
    with get_connection() as conn:
        _ensure_schema(conn)
        snapshots = _load_archive_snapshots(conn, dossier_ticker, limit=2)
        tracker_row = conn.execute(
            """
            SELECT *
            FROM dossier_tracker_state
            WHERE ticker = ?
            LIMIT 1
            """,
            [dossier_ticker],
        ).fetchone()
        catalyst_rows = conn.execute(
            """
            SELECT *
            FROM dossier_catalysts
            WHERE ticker = ?
            ORDER BY updated_at DESC
            """,
            [dossier_ticker],
        ).fetchall()

    if not snapshots:
        return {
            "ticker": dossier_ticker,
            "available": False,
            "latest_snapshot": None,
            "prior_snapshot": None,
            "snapshot_diff": {},
            "current_tracker_state": None,
            "catalysts": [],
            "audit_flags": ["no_archived_snapshot"],
        }

    latest = snapshots[0]
    prior = snapshots[1] if len(snapshots) > 1 else None
    latest_titles = [row["title"] for row in latest["structured_catalysts"]]
    prior_titles = [row["title"] for row in (prior["structured_catalysts"] if prior else [])]
    diff: dict[str, Any] = {
        "action_changed": bool(prior and latest.get("action") != prior.get("action")),
        "conviction_changed": bool(prior and latest.get("conviction") != prior.get("conviction")),
        "added_catalysts": [title for title in latest_titles if title not in prior_titles],
        "removed_catalysts": [title for title in prior_titles if title not in latest_titles],
    }
    if prior and isinstance(latest.get("base_iv"), (int, float)) and isinstance(prior.get("base_iv"), (int, float)):
        diff["base_iv_delta"] = float(latest["base_iv"]) - float(prior["base_iv"])

    tracker_state = dict(tracker_row) if tracker_row is not None else None
    catalysts = [dict(row) for row in catalyst_rows]
    if not catalysts:
        catalysts = [
            {
                "ticker": dossier_ticker,
                "catalyst_key": row.get("catalyst_key"),
                "title": row.get("title"),
                "description": row.get("description"),
                "priority": row.get("importance", "medium"),
                "status": "open",
                "expected_date": None,
                "expected_window_start": None,
                "expected_window_end": None,
                "status_reason": "",
                "source_origin": "archive",
                "source_snapshot_id": latest.get("id"),
            }
            for row in latest["structured_catalysts"]
        ]

    return {
        "ticker": dossier_ticker,
        "available": True,
        "latest_snapshot": latest,
        "prior_snapshot": prior,
        "snapshot_diff": diff,
        "current_tracker_state": tracker_state,
        "catalysts": catalysts,
        "audit_flags": [],
    }


def build_publishable_memo_context(ticker: str) -> dict[str, Any]:
    dossier_ticker = _coerce_ticker(ticker)
    with get_connection() as conn:
        _ensure_schema(conn)
        profile_row = conn.execute(
            """
            SELECT *
            FROM dossier_profiles
            WHERE ticker = ?
            LIMIT 1
            """,
            [dossier_ticker],
        ).fetchone()
        source_rows = conn.execute(
            """
            SELECT *
            FROM dossier_sources
            WHERE ticker = ?
            ORDER BY source_id ASC
            """,
            [dossier_ticker],
        ).fetchall()
        artifact_rows = conn.execute(
            """
            SELECT *
            FROM dossier_artifacts
            WHERE ticker = ?
              AND is_private = 0
            ORDER BY artifact_key ASC
            """,
            [dossier_ticker],
        ).fetchall()

    if profile_row is None:
        return {"ticker": dossier_ticker, "available": False, "title": "", "memo_content": "", "sources": [], "artifacts": []}

    try:
        memo_content = read_dossier_note(dossier_ticker, "publishable_memo")
    except Exception:
        memo_content = ""

    return {
        "ticker": dossier_ticker,
        "available": True,
        "title": "Publishable Memo",
        "memo_content": memo_content,
        "sources": [dict(row) for row in source_rows],
        "artifacts": [dict(row) for row in artifact_rows],
        "profile": dict(profile_row),
    }


def build_deep_dive_dossier_view(ticker: str) -> dict[str, Any]:
    return {
        "ticker": _coerce_ticker(ticker),
        "model_checkpoints": build_model_checkpoint_view(ticker),
        "thesis_diff": build_thesis_diff_view(ticker),
        "publishable_memo": build_publishable_memo_context(ticker),
    }
