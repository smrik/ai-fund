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


def test_dossier_review_log_round_trip(monkeypatch, tmp_path):
    from src.stage_04_pipeline import dossier_index

    db_path = tmp_path / "review.db"
    monkeypatch.setattr(dossier_index, "get_connection", _temp_conn_factory(db_path))

    entry_id = dossier_index.insert_review_log_entry(
        {
            "ticker": "IBM",
            "review_ts": "2026-04-25T22:00:00Z",
            "review_title": "Q1 review",
            "period_type": "quarterly",
            "expectations_vs_outcomes_text": "Revenue was in line; margins lagged.",
            "factual_error_text": "",
            "interpretive_error_text": "Underestimated consulting weakness.",
            "behavioral_error_text": "",
            "thesis_status": "monitor",
            "model_status": "needs_revision",
            "action_taken_text": "Reduced conviction but kept position.",
            "linked_decision_id": 1,
            "linked_snapshot_id": 22,
            "private_notes_text": "Need better segment tracking.",
            "created_by": "pm",
        }
    )

    entries = dossier_index.list_review_log("IBM")

    assert entry_id > 0
    assert len(entries) == 1
    assert entries[0]["review_title"] == "Q1 review"
    assert entries[0]["period_type"] == "quarterly"
    assert entries[0]["thesis_status"] == "monitor"
