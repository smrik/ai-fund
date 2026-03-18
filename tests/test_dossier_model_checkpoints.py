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


def test_model_checkpoints_round_trip_and_diff(monkeypatch, tmp_path):
    from src.stage_04_pipeline import dossier_index, dossier_view

    db_path = tmp_path / "checkpoints.db"
    factory = _temp_conn_factory(db_path)
    monkeypatch.setattr(dossier_index, "get_connection", factory)
    monkeypatch.setattr(dossier_view, "get_connection", factory)

    dossier_index.insert_model_checkpoint(
        {
            "ticker": "IBM",
            "checkpoint_ts": "2026-03-18T20:00:00Z",
            "model_version": "v01",
            "artifact_key": "excel_model_main",
            "snapshot_id": 11,
            "valuation_json": '{"base_iv": 110.0, "current_price": 100.0, "upside_pct": 0.10}',
            "drivers_summary_json": '{"wacc": 0.09}',
            "change_reason": "Initial dossier checkpoint",
            "thesis_version": "t01",
            "source_ids_json": '["S-001"]',
            "created_by": "pm",
        }
    )
    dossier_index.insert_model_checkpoint(
        {
            "ticker": "IBM",
            "checkpoint_ts": "2026-03-18T21:00:00Z",
            "model_version": "v02",
            "artifact_key": "excel_model_main",
            "snapshot_id": 12,
            "valuation_json": '{"base_iv": 125.0, "current_price": 103.0, "upside_pct": 0.21}',
            "drivers_summary_json": '{"wacc": 0.088}',
            "change_reason": "Updated after revisions",
            "thesis_version": "t02",
            "source_ids_json": '["S-001", "S-002"]',
            "created_by": "pm",
        }
    )

    checkpoints = dossier_index.list_model_checkpoints("IBM")
    checkpoint_view = dossier_view.build_model_checkpoint_view("IBM")

    assert len(checkpoints) == 2
    assert checkpoints[0]["model_version"] == "v02"
    assert checkpoints[1]["model_version"] == "v01"

    assert checkpoint_view["available"] is True
    assert checkpoint_view["latest_checkpoint"]["model_version"] == "v02"
    assert checkpoint_view["prior_checkpoint"]["model_version"] == "v01"
    assert checkpoint_view["diff"]["base_iv_delta"] == 15.0
