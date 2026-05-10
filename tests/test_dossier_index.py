from __future__ import annotations

import sqlite3
from pathlib import Path

from db.schema import create_tables


def _temp_conn_factory(db_path: Path):
    def _factory():
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        create_tables(conn)
        return conn

    return _factory


def test_dossier_index_round_trip_for_profile_and_sections(monkeypatch, tmp_path):
    from src.stage_04_pipeline import dossier_index

    db_path = tmp_path / "dossier.db"
    monkeypatch.setattr(dossier_index, "get_connection", _temp_conn_factory(db_path))

    dossier_index.upsert_dossier_profile(
        {
            "ticker": "IBM",
            "company_name": "International Business Machines",
            "dossier_root_path": "data/dossiers/IBM International Business Machines",
            "notes_root_path": "data/dossiers/IBM International Business Machines/Notes",
            "model_root_path": "data/dossiers/IBM International Business Machines/Model",
            "exports_root_path": "data/dossiers/IBM International Business Machines/Exports",
            "status": "active",
            "current_model_version": None,
            "current_thesis_version": None,
            "current_publishable_memo_version": None,
        }
    )
    dossier_index.upsert_dossier_section_index(
        {
            "ticker": "IBM",
            "note_slug": "company_hub",
            "note_title": "00 Company Hub",
            "relative_path": "Notes/00 Company Hub.md",
            "section_kind": "hub",
            "is_private": 0,
            "content_hash": "abc123",
            "metadata_json": '{"seeded": true}',
        }
    )

    profile = dossier_index.load_dossier_profile("IBM")
    sections = dossier_index.list_dossier_sections("IBM")

    assert profile is not None
    assert profile["ticker"] == "IBM"
    assert profile["company_name"] == "International Business Machines"
    assert profile["status"] == "active"

    assert len(sections) == 1
    assert sections[0]["note_slug"] == "company_hub"
    assert sections[0]["relative_path"] == "Notes/00 Company Hub.md"


def test_dossier_schema_creates_foundation_tables(tmp_path):
    db_path = tmp_path / "schema.db"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    create_tables(conn)

    names = {
        row["name"]
        for row in conn.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
            """
        ).fetchall()
    }

    assert "dossier_profiles" in names
    assert "dossier_sections" in names
