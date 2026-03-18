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


def test_dossier_sources_create_source_note_and_round_trip(monkeypatch, tmp_path):
    from src.stage_04_pipeline import dossier_index, dossier_workspace

    db_path = tmp_path / "sources.db"
    monkeypatch.setattr(dossier_index, "get_connection", _temp_conn_factory(db_path))
    monkeypatch.setattr(dossier_workspace, "DOSSIER_ROOT", tmp_path / "dossiers")

    workspace = dossier_workspace.ensure_dossier_workspace("IBM", "International Business Machines")
    root_path = Path(workspace["root_path"])
    source_note_path = dossier_workspace.ensure_dossier_source_note("IBM", "S-001", "2025 10-K")

    dossier_index.upsert_dossier_source(
        {
            "ticker": "IBM",
            "source_id": "S-001",
            "title": "2025 10-K",
            "source_type": "10-K",
            "source_date": "2025-12-31",
            "access_date": "2026-03-18",
            "why_it_matters": "Primary reported financials and risk disclosures.",
            "file_path": str(root_path / "Filings" / "ibm-10k.pdf"),
            "external_uri": None,
            "zotero_key": None,
            "relative_source_note_path": source_note_path.relative_to(root_path).as_posix(),
            "supports_json": '{"used_in": ["thesis", "valuation"]}',
            "limitations_text": "",
        }
    )

    sources = dossier_index.list_dossier_sources("IBM")

    assert len(sources) == 1
    assert sources[0]["source_id"] == "S-001"
    assert sources[0]["title"] == "2025 10-K"
    assert source_note_path.exists()
    assert "source_id: S-001" in source_note_path.read_text(encoding="utf-8")

