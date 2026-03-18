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


def test_dossier_decision_log_round_trip(monkeypatch, tmp_path):
    from src.stage_04_pipeline import dossier_index

    db_path = tmp_path / "decision.db"
    monkeypatch.setattr(dossier_index, "get_connection", _temp_conn_factory(db_path))

    entry_id = dossier_index.insert_decision_log_entry(
        {
            "ticker": "IBM",
            "decision_ts": "2026-03-18T22:00:00Z",
            "decision_title": "Initial long thesis",
            "action": "BUY",
            "conviction": "medium",
            "beliefs_text": "Software mix can stabilize margins.",
            "evidence_text": "Latest filings and revisions improved.",
            "assumptions_text": "Consulting stops worsening.",
            "falsifiers_text": "Another two weak quarters in services.",
            "review_due_date": "2026-05-01",
            "snapshot_id": 21,
            "model_checkpoint_id": 8,
            "private_notes_text": "Watch execution quality.",
            "created_by": "pm",
        }
    )

    entries = dossier_index.list_decision_log("IBM")

    assert entry_id > 0
    assert len(entries) == 1
    assert entries[0]["decision_title"] == "Initial long thesis"
    assert entries[0]["action"] == "BUY"
    assert entries[0]["review_due_date"] == "2026-05-01"

