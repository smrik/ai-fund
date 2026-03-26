from __future__ import annotations

from typing import Any

from db.loader import (
    insert_dossier_note_block as _insert_dossier_note_block_row,
    insert_decision_log_entry as _insert_decision_log_entry_row,
    insert_model_checkpoint as _insert_model_checkpoint_row,
    insert_review_log_entry as _insert_review_log_entry_row,
    upsert_tracker_state as _upsert_tracker_state_row,
    upsert_dossier_artifact as _upsert_dossier_artifact_row,
    upsert_dossier_profile as _upsert_dossier_profile_row,
    upsert_dossier_section_index as _upsert_dossier_section_row,
    upsert_dossier_source as _upsert_dossier_source_row,
    upsert_tracked_catalyst as _upsert_tracked_catalyst_row,
)
from db.schema import create_tables, get_connection


def _coerce_ticker(ticker: str) -> str:
    value = (ticker or "").strip().upper()
    if not value:
        raise ValueError("ticker is required")
    return value


def _ensure_schema(conn) -> None:
    create_tables(conn)


def upsert_dossier_profile(row: dict[str, Any]) -> None:
    with get_connection() as conn:
        _ensure_schema(conn)
        _upsert_dossier_profile_row(conn, row)


def load_dossier_profile(ticker: str) -> dict[str, Any] | None:
    dossier_ticker = _coerce_ticker(ticker)
    with get_connection() as conn:
        _ensure_schema(conn)
        row = conn.execute(
            """
            SELECT *
            FROM dossier_profiles
            WHERE ticker = ?
            LIMIT 1
            """,
            [dossier_ticker],
        ).fetchone()
    return dict(row) if row is not None else None


def upsert_dossier_section_index(row: dict[str, Any]) -> None:
    with get_connection() as conn:
        _ensure_schema(conn)
        _upsert_dossier_section_row(conn, row)


def list_dossier_sections(ticker: str) -> list[dict[str, Any]]:
    dossier_ticker = _coerce_ticker(ticker)
    with get_connection() as conn:
        _ensure_schema(conn)
        rows = conn.execute(
            """
            SELECT *
            FROM dossier_sections
            WHERE ticker = ?
            ORDER BY note_slug ASC
            """,
            [dossier_ticker],
        ).fetchall()
    return [dict(row) for row in rows]


def upsert_dossier_source(row: dict[str, Any]) -> None:
    with get_connection() as conn:
        _ensure_schema(conn)
        _upsert_dossier_source_row(conn, row)


def list_dossier_sources(ticker: str) -> list[dict[str, Any]]:
    dossier_ticker = _coerce_ticker(ticker)
    with get_connection() as conn:
        _ensure_schema(conn)
        rows = conn.execute(
            """
            SELECT *
            FROM dossier_sources
            WHERE ticker = ?
            ORDER BY source_id ASC
            """,
            [dossier_ticker],
        ).fetchall()
    return [dict(row) for row in rows]


def upsert_dossier_artifact(row: dict[str, Any]) -> None:
    with get_connection() as conn:
        _ensure_schema(conn)
        _upsert_dossier_artifact_row(conn, row)


def list_dossier_artifacts(ticker: str) -> list[dict[str, Any]]:
    dossier_ticker = _coerce_ticker(ticker)
    with get_connection() as conn:
        _ensure_schema(conn)
        rows = conn.execute(
            """
            SELECT *
            FROM dossier_artifacts
            WHERE ticker = ?
            ORDER BY artifact_key ASC
            """,
            [dossier_ticker],
        ).fetchall()
    return [dict(row) for row in rows]


def insert_model_checkpoint(row: dict[str, Any]) -> int:
    with get_connection() as conn:
        _ensure_schema(conn)
        return _insert_model_checkpoint_row(conn, row)


def list_model_checkpoints(ticker: str) -> list[dict[str, Any]]:
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
    return [dict(row) for row in rows]


def upsert_tracker_state(row: dict[str, Any]) -> None:
    with get_connection() as conn:
        _ensure_schema(conn)
        _upsert_tracker_state_row(conn, row)


def load_tracker_state(ticker: str) -> dict[str, Any] | None:
    dossier_ticker = _coerce_ticker(ticker)
    with get_connection() as conn:
        _ensure_schema(conn)
        row = conn.execute(
            """
            SELECT *
            FROM dossier_tracker_state
            WHERE ticker = ?
            LIMIT 1
            """,
            [dossier_ticker],
        ).fetchone()
    return dict(row) if row is not None else None


def upsert_tracked_catalyst(row: dict[str, Any]) -> None:
    with get_connection() as conn:
        _ensure_schema(conn)
        _upsert_tracked_catalyst_row(conn, row)


def list_tracked_catalysts(ticker: str) -> list[dict[str, Any]]:
    dossier_ticker = _coerce_ticker(ticker)
    with get_connection() as conn:
        _ensure_schema(conn)
        rows = conn.execute(
            """
            SELECT *
            FROM dossier_catalysts
            WHERE ticker = ?
            ORDER BY priority DESC, updated_at DESC
            """,
            [dossier_ticker],
        ).fetchall()
    return [dict(row) for row in rows]


def insert_decision_log_entry(row: dict[str, Any]) -> int:
    with get_connection() as conn:
        _ensure_schema(conn)
        return _insert_decision_log_entry_row(conn, row)


def list_decision_log(ticker: str) -> list[dict[str, Any]]:
    dossier_ticker = _coerce_ticker(ticker)
    with get_connection() as conn:
        _ensure_schema(conn)
        rows = conn.execute(
            """
            SELECT *
            FROM dossier_decision_log
            WHERE ticker = ?
            ORDER BY decision_ts DESC
            """,
            [dossier_ticker],
        ).fetchall()
    return [dict(row) for row in rows]


def insert_review_log_entry(row: dict[str, Any]) -> int:
    with get_connection() as conn:
        _ensure_schema(conn)
        return _insert_review_log_entry_row(conn, row)


def list_review_log(ticker: str) -> list[dict[str, Any]]:
    dossier_ticker = _coerce_ticker(ticker)
    with get_connection() as conn:
        _ensure_schema(conn)
        rows = conn.execute(
            """
            SELECT *
            FROM dossier_review_log
            WHERE ticker = ?
            ORDER BY review_ts DESC
            """,
            [dossier_ticker],
        ).fetchall()
    return [dict(row) for row in rows]


def insert_dossier_note_block(row: dict[str, Any]) -> int:
    with get_connection() as conn:
        _ensure_schema(conn)
        return _insert_dossier_note_block_row(conn, row)


def list_dossier_note_blocks(ticker: str, *, block_type: str | None = None) -> list[dict[str, Any]]:
    dossier_ticker = _coerce_ticker(ticker)
    query = """
        SELECT *
        FROM dossier_note_blocks
        WHERE ticker = ?
    """
    params: list[Any] = [dossier_ticker]
    if block_type:
        query += " AND block_type = ?"
        params.append(block_type)
    query += " ORDER BY block_ts DESC, id DESC"
    with get_connection() as conn:
        _ensure_schema(conn)
        rows = conn.execute(query, params).fetchall()
    return [dict(row) for row in rows]
