from __future__ import annotations

import json
import re
from datetime import date
from typing import Any

from db.schema import create_tables, get_connection
from src.stage_04_pipeline.dossier_index import (
    list_decision_log,
    list_review_log,
    list_tracked_catalysts,
    load_tracker_state,
)
from src.stage_04_pipeline.dossier_workspace import read_dossier_note


def _coerce_ticker(ticker: str) -> str:
    value = (ticker or "").strip().upper()
    if not value:
        raise ValueError("ticker is required")
    return value


def _ensure_schema(conn) -> None:
    create_tables(conn)


def _parse_json(value: Any, *, fallback: Any) -> Any:
    if value in (None, "", []):
        return fallback
    if isinstance(value, (dict, list)):
        return value
    try:
        parsed = json.loads(value)
    except Exception:
        return fallback
    return fallback if parsed is None else parsed


def _normalize_structured_catalysts(memo_payload: dict[str, Any]) -> tuple[list[dict[str, Any]], bool]:
    structured = memo_payload.get("structured_catalysts") or []
    if structured:
        return [
            {
                **dict(row),
                "catalyst_key": dict(row).get("catalyst_key") or f"catalyst-{_stable_slug(dict(row).get('title') or str(idx + 1))}",
            }
            for idx, row in enumerate(structured)
        ], False
    return (
        [
            {
                "catalyst_key": f"legacy-catalyst-{_stable_slug(title)}",
                "title": title,
                "description": "",
                "expected_window": "",
                "importance": "medium",
            }
            for idx, title in enumerate(memo_payload.get("key_catalysts") or [])
            if title
        ],
        True,
    )


def _normalize_thesis_pillars(memo_payload: dict[str, Any]) -> tuple[list[dict[str, Any]], bool]:
    pillars = memo_payload.get("thesis_pillars") or []
    if pillars:
        return [
            {
                **dict(row),
                "pillar_id": dict(row).get("pillar_id") or f"pillar-{_stable_slug(dict(row).get('title') or str(idx + 1))}",
            }
            for idx, row in enumerate(pillars)
        ], False
    fallback_pairs = [
        ("core_thesis", memo_payload.get("one_liner") or ""),
        ("bull_case", memo_payload.get("bull_case") or ""),
        ("base_case", memo_payload.get("base_case") or ""),
    ]
    return (
        [
            {
                "pillar_id": f"legacy-pillar-{_stable_slug(pillar_id.replace('_', ' '))}",
                "title": pillar_id.replace("_", " ").title(),
                "description": description,
                "falsifier": "",
                "evidence_basis": "",
            }
            for pillar_id, description in fallback_pairs
            if description
        ],
        True,
    )


def _stable_slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (value or "").strip().lower()).strip("-")
    return slug or "item"


def _coerce_float(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    return None


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
    snapshots: list[dict[str, Any]] = []
    for row in rows:
        payload = dict(row)
        memo = _parse_json(payload.get("memo_json"), fallback={})
        valuation = _parse_json(memo.get("valuation"), fallback={})
        pillars, used_legacy_pillars = _normalize_thesis_pillars(memo)
        catalysts, used_legacy_catalysts = _normalize_structured_catalysts(memo)
        payload["memo"] = memo
        payload["valuation"] = valuation
        payload["current_price"] = _coerce_float(valuation.get("current_price"))
        payload["upside_pct"] = _coerce_float(valuation.get("upside_pct_base"))
        payload["key_risks"] = [row for row in (memo.get("key_risks") or []) if row]
        payload["open_questions"] = [row for row in (memo.get("open_questions") or []) if row]
        payload["thesis_pillars"] = pillars
        payload["structured_catalysts"] = catalysts
        payload["used_legacy_pillars"] = used_legacy_pillars
        payload["used_legacy_catalysts"] = used_legacy_catalysts
        snapshots.append(payload)
    return snapshots


def _normalize_pillar_row(row: dict[str, Any], *, index: int) -> dict[str, Any]:
    title = row.get("title") or f"Pillar {index + 1}"
    pillar_id = row.get("pillar_id") or f"{_stable_slug(title)}-{index + 1}"
    return {
        "pillar_id": pillar_id,
        "title": title,
        "description": row.get("description") or "",
        "falsifier": row.get("falsifier") or "",
        "evidence_basis": row.get("evidence_basis") or "",
    }


def _normalize_catalyst_row(row: dict[str, Any], *, index: int, latest_snapshot_id: int | None) -> dict[str, Any]:
    title = row.get("title") or f"Catalyst {index + 1}"
    catalyst_key = row.get("catalyst_key") or f"{_stable_slug(title)}-{index + 1}"
    return {
        "catalyst_key": catalyst_key,
        "title": title,
        "description": row.get("description") or "",
        "priority": row.get("priority") or row.get("importance") or "medium",
        "status": row.get("status") or "open",
        "expected_date": row.get("expected_date"),
        "expected_window_start": row.get("expected_window_start"),
        "expected_window_end": row.get("expected_window_end"),
        "expected_window": row.get("expected_window") or "",
        "status_reason": row.get("status_reason") or "",
        "source_origin": row.get("source_origin") or "archive",
        "source_snapshot_id": row.get("source_snapshot_id") or latest_snapshot_id,
        "evidence_json": _parse_json(row.get("evidence_json"), fallback={}),
        "updated_at": row.get("updated_at"),
    }


def _sort_catalysts(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    priority_rank = {"high": 0, "medium": 1, "low": 2}
    sentinel = "9999-12-31"
    return sorted(
        rows,
        key=lambda row: (
            0 if row.get("expected_date") else 1,
            row.get("expected_date") or sentinel,
            priority_rank.get((row.get("priority") or "medium").lower(), 1),
            row.get("title") or "",
        ),
    )


def _build_catalyst_board(
    latest_snapshot: dict[str, Any],
    tracked_catalysts: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    archive_rows: dict[str, dict[str, Any]] = {}
    for idx, row in enumerate(latest_snapshot.get("structured_catalysts") or []):
        normalized = _normalize_catalyst_row(row, index=idx, latest_snapshot_id=latest_snapshot.get("id"))
        archive_rows[normalized["catalyst_key"]] = normalized

    for idx, row in enumerate(tracked_catalysts):
        normalized = _normalize_catalyst_row(row, index=idx, latest_snapshot_id=latest_snapshot.get("id"))
        existing = archive_rows.get(normalized["catalyst_key"])
        if existing is None:
            normalized_title_slug = _stable_slug(normalized.get("title") or "")
            existing = next(
                (candidate for candidate in archive_rows.values() if _stable_slug(candidate.get("title") or "") == normalized_title_slug),
                {},
            )
        existing.update({k: v for k, v in normalized.items() if v not in (None, "")})
        archive_rows[normalized["catalyst_key"]] = existing

    board = {"urgent_open": [], "watching": [], "resolved": []}
    for row in archive_rows.values():
        status = (row.get("status") or "open").lower()
        row["latest_evidence_cue"] = row.get("status_reason") or row.get("description") or row.get("expected_window") or ""
        if status in {"watching"}:
            board["watching"].append(row)
        elif status in {"hit", "missed", "killed", "resolved"}:
            board["resolved"].append(row)
        else:
            board["urgent_open"].append(row)

    board["urgent_open"] = _sort_catalysts(board["urgent_open"])
    board["watching"] = _sort_catalysts(board["watching"])
    board["resolved"] = sorted(board["resolved"], key=lambda row: (row.get("updated_at") or "", row.get("title") or ""), reverse=True)
    return board


def _build_pillar_board(latest_snapshot: dict[str, Any], tracker_state: dict[str, Any] | None) -> list[dict[str, Any]]:
    pillar_states = _parse_json((tracker_state or {}).get("pillar_states_json"), fallback={})
    board = []
    for idx, raw_row in enumerate(latest_snapshot.get("thesis_pillars") or []):
        row = _normalize_pillar_row(raw_row, index=idx)
        state = {}
        if isinstance(pillar_states, dict):
            state = pillar_states.get(row["pillar_id"], {})
            if not state:
                row_title_slug = _stable_slug(row["title"])
                state = next(
                    (
                        candidate
                        for key, candidate in pillar_states.items()
                        if _stable_slug((candidate or {}).get("title_slug") or key.replace("_", " ").replace("-", " ")) == row_title_slug
                    ),
                    {},
                )
        board.append(
            {
                **row,
                "pm_status": state.get("status") or "unknown",
                "pm_note": state.get("note") or "",
                "latest_evidence_cue": row["evidence_basis"] or row["description"],
            }
        )
    return board


def _list_delta(latest_items: list[str], prior_items: list[str]) -> tuple[list[str], list[str]]:
    return (
        [item for item in latest_items if item not in prior_items],
        [item for item in prior_items if item not in latest_items],
    )


def _build_what_changed(latest: dict[str, Any], prior: dict[str, Any] | None) -> dict[str, Any]:
    if prior is None:
        return {
            "action_delta": {"from": None, "to": latest.get("action")},
            "conviction_delta": {"from": None, "to": latest.get("conviction")},
            "base_iv_delta": None,
            "upside_delta": None,
            "catalysts_added": [row.get("title") for row in latest.get("structured_catalysts") or [] if row.get("title")],
            "catalysts_removed": [],
            "risks_added": latest.get("key_risks") or [],
            "risks_removed": [],
            "open_questions_added": latest.get("open_questions") or [],
            "open_questions_closed": [],
            "pillars_added": [row.get("title") for row in latest.get("thesis_pillars") or [] if row.get("title")],
            "pillars_removed": [],
        }

    latest_catalysts = [row.get("title") for row in latest.get("structured_catalysts") or [] if row.get("title")]
    prior_catalysts = [row.get("title") for row in prior.get("structured_catalysts") or [] if row.get("title")]
    catalysts_added, catalysts_removed = _list_delta(latest_catalysts, prior_catalysts)
    risks_added, risks_removed = _list_delta(latest.get("key_risks") or [], prior.get("key_risks") or [])
    questions_added, questions_closed = _list_delta(latest.get("open_questions") or [], prior.get("open_questions") or [])
    latest_pillars = [row.get("title") for row in latest.get("thesis_pillars") or [] if row.get("title")]
    prior_pillars = [row.get("title") for row in prior.get("thesis_pillars") or [] if row.get("title")]
    pillars_added, pillars_removed = _list_delta(latest_pillars, prior_pillars)
    latest_upside = _coerce_float(latest.get("upside_pct"))
    prior_upside = _coerce_float(prior.get("upside_pct"))

    return {
        "action_delta": {"from": prior.get("action"), "to": latest.get("action")},
        "conviction_delta": {"from": prior.get("conviction"), "to": latest.get("conviction")},
        "base_iv_delta": (
            float(latest["base_iv"]) - float(prior["base_iv"])
            if isinstance(latest.get("base_iv"), (int, float)) and isinstance(prior.get("base_iv"), (int, float))
            else None
        ),
        "upside_delta": latest_upside - prior_upside if latest_upside is not None and prior_upside is not None else None,
        "catalysts_added": catalysts_added,
        "catalysts_removed": catalysts_removed,
        "risks_added": risks_added,
        "risks_removed": risks_removed,
        "open_questions_added": questions_added,
        "open_questions_closed": questions_closed,
        "pillars_added": pillars_added,
        "pillars_removed": pillars_removed,
    }


def _review_due_bucket(review_due_date: str | None) -> str | None:
    if not review_due_date:
        return None
    try:
        due_date = date.fromisoformat(review_due_date[:10])
    except Exception:
        return "scheduled"
    return "overdue" if due_date < date.today() else "scheduled"


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
    latest["valuation"] = _parse_json(latest.get("valuation_json"), fallback={})
    latest["drivers_summary"] = _parse_json(latest.get("drivers_summary_json"), fallback={})
    prior = None
    diff: dict[str, Any] = {}
    if len(checkpoints) > 1:
        prior = dict(checkpoints[1])
        prior["valuation"] = _parse_json(prior.get("valuation_json"), fallback={})
        prior["drivers_summary"] = _parse_json(prior.get("drivers_summary_json"), fallback={})
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


def build_thesis_tracker_view(ticker: str) -> dict[str, Any]:
    dossier_ticker = _coerce_ticker(ticker)
    with get_connection() as conn:
        _ensure_schema(conn)
        snapshots = _load_archive_snapshots(conn, dossier_ticker, limit=2)

    if not snapshots:
        return {
            "ticker": dossier_ticker,
            "available": False,
            "latest_snapshot": None,
            "prior_snapshot": None,
            "stance": {},
            "what_changed": {},
            "pillar_board": [],
            "catalyst_board": {"urgent_open": [], "watching": [], "resolved": []},
            "continuity": {},
            "next_queue": {},
            "audit_flags": ["no_archived_snapshot"],
        }

    latest = snapshots[0]
    prior = snapshots[1] if len(snapshots) > 1 else None
    tracker_state = load_tracker_state(dossier_ticker) or {}
    tracked_catalysts = list_tracked_catalysts(dossier_ticker)
    checkpoint_view = build_model_checkpoint_view(dossier_ticker)
    decisions = list_decision_log(dossier_ticker)
    reviews = list_review_log(dossier_ticker)

    pillar_board = _build_pillar_board(latest, tracker_state)
    catalyst_board = _build_catalyst_board(latest, tracked_catalysts)
    what_changed = _build_what_changed(latest, prior)
    review_due_bucket = _review_due_bucket((decisions[0] if decisions else {}).get("review_due_date"))
    checkpoint_latest = checkpoint_view.get("latest_checkpoint") if checkpoint_view.get("available") else None
    checkpoint_valuation = (checkpoint_latest or {}).get("valuation") or {}

    next_catalyst = None
    if catalyst_board["urgent_open"]:
        next_catalyst = catalyst_board["urgent_open"][0]
    elif catalyst_board["watching"]:
        next_catalyst = catalyst_board["watching"][0]

    archived_open_questions = latest.get("open_questions") or []
    tracker_open_questions = _parse_json(tracker_state.get("open_questions_json"), fallback=archived_open_questions)
    if not isinstance(tracker_open_questions, list):
        tracker_open_questions = archived_open_questions
    audit_flags = []
    if latest.get("used_legacy_pillars"):
        audit_flags.append("legacy_pillar_fallback")
    if latest.get("used_legacy_catalysts"):
        audit_flags.append("legacy_catalyst_fallback")
    if prior is None:
        audit_flags.append("no_prior_snapshot")
    if not pillar_board:
        audit_flags.append("no_pillars")
    if not any(catalyst_board.values()):
        audit_flags.append("no_catalysts")

    stance = {
        "pm_action": tracker_state.get("pm_action") or latest.get("action"),
        "pm_conviction": tracker_state.get("pm_conviction") or latest.get("conviction"),
        "overall_status": tracker_state.get("overall_status") or "unknown",
        "summary_note": tracker_state.get("summary_note") or "",
        "last_reviewed_at": tracker_state.get("last_reviewed_at"),
        "latest_archived_action": latest.get("action"),
        "latest_archived_conviction": latest.get("conviction"),
        "base_iv": checkpoint_valuation.get("base_iv", latest.get("base_iv")),
        "current_price": checkpoint_valuation.get("current_price", latest.get("current_price")),
        "upside_pct": checkpoint_valuation.get("upside_pct", latest.get("upside_pct")),
        "next_catalyst": next_catalyst,
    }

    continuity = {
        "latest_decision": decisions[0] if decisions else None,
        "latest_review": reviews[0] if reviews else None,
        "latest_checkpoint": checkpoint_latest,
        "snapshot_refs": {
            "latest_snapshot_id": latest.get("id"),
            "prior_snapshot_id": prior.get("id") if prior else None,
            "latest_snapshot_created_at": latest.get("created_at"),
            "prior_snapshot_created_at": prior.get("created_at") if prior else None,
        },
    }

    next_queue = {
        "open_questions": tracker_open_questions,
        "upcoming_catalysts": catalyst_board["urgent_open"][:3] + catalyst_board["watching"][:2],
        "review_status": review_due_bucket,
        "missing_evidence_flags": [flag for flag in audit_flags if flag in {"legacy_pillar_fallback", "legacy_catalyst_fallback", "no_pillars", "no_catalysts"}],
    }

    return {
        "ticker": dossier_ticker,
        "available": True,
        "latest_snapshot": latest,
        "prior_snapshot": prior,
        "tracker_state": tracker_state,
        "stance": stance,
        "what_changed": what_changed,
        "pillar_board": pillar_board,
        "catalyst_board": catalyst_board,
        "continuity": continuity,
        "next_queue": next_queue,
        "audit_flags": audit_flags,
    }


def build_thesis_diff_view(ticker: str) -> dict[str, Any]:
    tracker_view = build_thesis_tracker_view(ticker)
    if not tracker_view.get("available"):
        return {
            "ticker": tracker_view["ticker"],
            "available": False,
            "latest_snapshot": None,
            "prior_snapshot": None,
            "snapshot_diff": {},
            "current_tracker_state": None,
            "catalysts": [],
            "audit_flags": tracker_view.get("audit_flags", []),
        }

    what_changed = tracker_view.get("what_changed", {})
    catalyst_rows = (
        tracker_view.get("catalyst_board", {}).get("urgent_open", [])
        + tracker_view.get("catalyst_board", {}).get("watching", [])
        + tracker_view.get("catalyst_board", {}).get("resolved", [])
    )
    stance = tracker_view.get("stance", {})
    has_prior_snapshot = tracker_view.get("prior_snapshot") is not None
    return {
        "ticker": tracker_view["ticker"],
        "available": True,
        "latest_snapshot": tracker_view.get("latest_snapshot"),
        "prior_snapshot": tracker_view.get("prior_snapshot"),
        "snapshot_diff": {
            "action_changed": bool(
                has_prior_snapshot and what_changed.get("action_delta", {}).get("from") != what_changed.get("action_delta", {}).get("to")
            ),
            "conviction_changed": bool(
                has_prior_snapshot and what_changed.get("conviction_delta", {}).get("from") != what_changed.get("conviction_delta", {}).get("to")
            ),
            "added_catalysts": what_changed.get("catalysts_added", []),
            "removed_catalysts": what_changed.get("catalysts_removed", []),
            "base_iv_delta": what_changed.get("base_iv_delta"),
        },
        "current_tracker_state": {
            "overall_status": stance.get("overall_status"),
            "pm_action": stance.get("pm_action"),
            "pm_conviction": stance.get("pm_conviction"),
            "summary_note": stance.get("summary_note"),
            "last_reviewed_at": stance.get("last_reviewed_at"),
        },
        "catalysts": catalyst_rows,
        "audit_flags": tracker_view.get("audit_flags", []),
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
        "thesis_tracker": build_thesis_tracker_view(ticker),
        "thesis_diff": build_thesis_diff_view(ticker),
        "publishable_memo": build_publishable_memo_context(ticker),
    }
