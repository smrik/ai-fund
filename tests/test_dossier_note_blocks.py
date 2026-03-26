from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
import sqlite3

from db.schema import create_tables


@contextmanager
def _db_factory():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    create_tables(conn)

    def _factory():
        return conn

    try:
        yield _factory
    finally:
        conn.close()


def test_dossier_note_blocks_round_trip_and_sort_desc(monkeypatch):
    from src.stage_04_pipeline import dossier_index

    with _db_factory() as factory:
        monkeypatch.setattr(dossier_index, "get_connection", factory)

        dossier_index.insert_dossier_note_block(
            {
                "ticker": "IBM",
                "block_ts": "2026-03-23T12:00:00+00:00",
                "block_type": "thesis",
                "title": "Services mix still weak",
                "body": "Need more evidence that consulting can stabilize.",
                "source_context_json": '{"page":"Market","subpage":"News & Revisions"}',
                "linked_snapshot_id": 12,
                "linked_sources_json": '["S-001"]',
                "linked_artifacts_json": "[]",
                "status": "active",
                "pinned_to_report": 0,
                "created_by": "pm",
            }
        )
        dossier_index.insert_dossier_note_block(
            {
                "ticker": "IBM",
                "block_ts": "2026-03-23T13:00:00+00:00",
                "block_type": "thesis",
                "title": "Software margin still intact",
                "body": "Higher-value mix still supports thesis.",
                "source_context_json": '{"page":"Overview","subpage":"Overview"}',
                "linked_snapshot_id": 13,
                "linked_sources_json": "[]",
                "linked_artifacts_json": "[]",
                "status": "active",
                "pinned_to_report": 1,
                "created_by": "pm",
            }
        )

        rows = dossier_index.list_dossier_note_blocks("IBM", block_type="thesis")

    assert len(rows) == 2
    assert rows[0]["title"] == "Software margin still intact"
    assert rows[1]["title"] == "Services mix still weak"


def test_build_dossier_notebook_view_groups_by_type_and_tracks_pinned(monkeypatch):
    from src.stage_04_pipeline import dossier_index, dossier_view

    with _db_factory() as factory:
        monkeypatch.setattr(dossier_index, "get_connection", factory)
        monkeypatch.setattr(dossier_view, "get_connection", factory)

        dossier_index.insert_dossier_note_block(
            {
                "ticker": "IBM",
                "block_ts": "2026-03-23T10:00:00+00:00",
                "block_type": "risk",
                "title": "Execution risk remains",
                "body": "Consulting stabilization still uncertain.",
                "source_context_json": '{"page":"Research","subpage":"Board"}',
                "linked_snapshot_id": 11,
                "linked_sources_json": "[]",
                "linked_artifacts_json": "[]",
                "status": "active",
                "pinned_to_report": 0,
                "created_by": "pm",
            }
        )
        dossier_index.insert_dossier_note_block(
            {
                "ticker": "IBM",
                "block_ts": "2026-03-23T11:00:00+00:00",
                "block_type": "decision",
                "title": "Hold sizing steady",
                "body": "Need another quarter before adding.",
                "source_context_json": '{"page":"Overview","subpage":"Overview"}',
                "linked_snapshot_id": 11,
                "linked_sources_json": "[]",
                "linked_artifacts_json": "[]",
                "status": "active",
                "pinned_to_report": 1,
                "created_by": "pm",
            }
        )

        notebook = dossier_view.build_dossier_notebook_view("IBM")

    assert notebook["available"] is True
    assert notebook["counts"]["risk"] == 1
    assert notebook["counts"]["decision"] == 1
    assert notebook["counts"]["all"] == 2
    assert notebook["pinned_count"] == 1
    assert notebook["blocks_by_type"]["decision"][0]["title"] == "Hold sizing steady"


def test_note_block_timestamp_helper_returns_iso8601_utc():
    from dashboard.dossier_companion import _current_note_block_ts

    value = _current_note_block_ts()

    parsed = datetime.fromisoformat(value)
    assert parsed.tzinfo is not None
    assert "T" in value
