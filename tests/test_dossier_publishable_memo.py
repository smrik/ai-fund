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


def test_publishable_memo_context_reads_note_and_filters_private_artifacts(monkeypatch, tmp_path):
    from src.stage_04_pipeline import dossier_index, dossier_view, dossier_workspace

    db_path = tmp_path / "publishable.db"
    factory = _temp_conn_factory(db_path)
    monkeypatch.setattr(dossier_index, "get_connection", factory)
    monkeypatch.setattr(dossier_view, "get_connection", factory)
    monkeypatch.setattr(dossier_workspace, "DOSSIER_ROOT", tmp_path / "dossiers")

    workspace = dossier_workspace.ensure_dossier_workspace("IBM", "International Business Machines")
    dossier_workspace.write_dossier_note("IBM", "publishable_memo", "# Publishable Memo\n\nPublic thesis summary.")
    dossier_index.upsert_dossier_profile(
        {
            "ticker": "IBM",
            "company_name": "International Business Machines",
            "dossier_root_path": workspace["root_path"],
            "notes_root_path": workspace["notes_root_path"],
            "model_root_path": workspace["model_root_path"],
            "exports_root_path": workspace["exports_root_path"],
            "status": "active",
            "current_model_version": "v02",
            "current_thesis_version": "t02",
            "current_publishable_memo_version": "m01",
        }
    )
    dossier_index.upsert_dossier_source(
        {
            "ticker": "IBM",
            "source_id": "S-001",
            "title": "2025 10-K",
            "source_type": "10-K",
            "source_date": "2025-12-31",
            "access_date": "2026-03-18",
            "why_it_matters": "Primary filing",
            "file_path": None,
            "external_uri": None,
            "zotero_key": None,
            "relative_source_note_path": "Notes/Sources/S-001 2025 10-K.md",
            "supports_json": "{}",
            "limitations_text": "",
        }
    )
    dossier_index.upsert_dossier_artifact(
        {
            "ticker": "IBM",
            "artifact_key": "public_chart",
            "artifact_type": "export_png",
            "title": "DCF Summary",
            "path_mode": "dossier_relative",
            "path_value": "Exports/dcf-summary.png",
            "source_id": "S-001",
            "linked_note_slug": "publishable_memo",
            "linked_snapshot_id": None,
            "model_version": "v02",
            "is_private": 0,
            "metadata_json": "{}",
        }
    )
    dossier_index.upsert_dossier_artifact(
        {
            "ticker": "IBM",
            "artifact_key": "private_working_file",
            "artifact_type": "other",
            "title": "Private Notes",
            "path_mode": "dossier_relative",
            "path_value": "Private/private-notes.txt",
            "source_id": None,
            "linked_note_slug": "publishable_memo",
            "linked_snapshot_id": None,
            "model_version": None,
            "is_private": 1,
            "metadata_json": "{}",
        }
    )

    context = dossier_view.build_publishable_memo_context("IBM")

    assert context["available"] is True
    assert "Public thesis summary." in context["memo_content"]
    assert len(context["artifacts"]) == 1
    assert context["artifacts"][0]["artifact_key"] == "public_chart"
    assert context["sources"][0]["source_id"] == "S-001"
