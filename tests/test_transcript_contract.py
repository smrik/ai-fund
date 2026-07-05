from __future__ import annotations

import json
from pathlib import Path

from db.schema import get_connection
from scripts.manual.import_transcript import main as import_transcript_main
from src.contracts.transcript import TranscriptDocument

FIXTURE_PATH = Path("tests/fixtures/transcripts/msft_q3_fy26_sample.json")


def test_transcript_document_round_trips_json() -> None:
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

    doc = TranscriptDocument.model_validate(payload)
    restored = TranscriptDocument.model_validate_json(doc.model_dump_json())

    assert restored == doc
    assert restored.ticker == "MSFT"
    assert restored.paragraphs[0].speaker_name == "Satya Nadella"
    assert restored.paragraphs[2].speaker_role == "Analyst, JPMorgan"


def test_import_transcript_upsert_is_idempotent(tmp_path, monkeypatch, capsys) -> None:
    db_path = tmp_path / "alpha_pod.db"
    monkeypatch.setenv("ALPHA_POD_DB_PATH", str(db_path))

    first_exit = import_transcript_main(["--file", str(FIXTURE_PATH)])
    second_exit = import_transcript_main(["--file", str(FIXTURE_PATH)])
    output = capsys.readouterr().out

    assert first_exit == 0
    assert second_exit == 0
    assert "Imported transcript msft-q3-fy26-sample for MSFT" in output

    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT ticker, event_date, fiscal_label, source, document_id, payload
            FROM transcript_cache
            """
        ).fetchall()

    assert len(rows) == 1
    row = rows[0]
    assert row["ticker"] == "MSFT"
    assert row["event_date"] == "2025-05-01"
    assert row["fiscal_label"] == "Q3 FY2026"
    assert row["source"] == "quartr"
    assert row["document_id"] == "msft-q3-fy26-sample"
    assert TranscriptDocument.model_validate_json(row["payload"]).document_id == "msft-q3-fy26-sample"


def test_import_transcript_returns_one_on_validation_error(tmp_path, capsys) -> None:
    invalid_path = tmp_path / "invalid.json"
    invalid_path.write_text('{"ticker": "MSFT"}', encoding="utf-8")

    exit_code = import_transcript_main(["--file", str(invalid_path)])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "Transcript validation failed" in captured.err
