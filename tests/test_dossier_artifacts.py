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


def test_normalize_linked_artifact_path_supports_absolute_and_repo_relative(tmp_path):
    from src.stage_04_pipeline import dossier_workspace

    workbook_path = tmp_path / "IBM Model.xlsx"
    workbook_path.write_text("stub", encoding="utf-8")

    absolute = dossier_workspace.normalize_linked_artifact_path(workbook_path, path_mode="absolute")
    repo_relative = dossier_workspace.normalize_linked_artifact_path("data/models/IBM Model.xlsx", path_mode="repo_relative")

    assert absolute["path_mode"] == "absolute"
    assert absolute["path_value"] == str(workbook_path.resolve())
    assert repo_relative["path_mode"] == "repo_relative"
    assert repo_relative["path_value"] == "data/models/IBM Model.xlsx"


def test_dossier_artifacts_round_trip(monkeypatch, tmp_path):
    from src.stage_04_pipeline import dossier_index

    db_path = tmp_path / "artifacts.db"
    monkeypatch.setattr(dossier_index, "get_connection", _temp_conn_factory(db_path))

    dossier_index.upsert_dossier_artifact(
        {
            "ticker": "IBM",
            "artifact_key": "excel_model_main",
            "artifact_type": "excel_model",
            "title": "IBM Main Model",
            "path_mode": "absolute",
            "path_value": "C:/Research/IBM/Model/IBM Model.xlsx",
            "source_id": None,
            "linked_note_slug": "valuation",
            "linked_snapshot_id": None,
            "model_version": "v01",
            "is_private": 0,
            "metadata_json": '{"owner": "pm"}',
        }
    )

    artifacts = dossier_index.list_dossier_artifacts("IBM")

    assert len(artifacts) == 1
    assert artifacts[0]["artifact_key"] == "excel_model_main"
    assert artifacts[0]["artifact_type"] == "excel_model"
    assert artifacts[0]["linked_note_slug"] == "valuation"
