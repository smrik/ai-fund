import sqlite3

import pytest

from db.schema import create_tables
from scripts.manual import inspect_classification as inspector


def test_stage0_reports_current_parser_inventory_without_stale_rows(tmp_path, monkeypatch, capsys):
    db_path = tmp_path / "alpha_pod.db"
    conn = sqlite3.connect(db_path)
    create_tables(conn)
    conn.executemany(
        """
        insert into edgar_filing_cache (
            ticker, cik, form_type, accession_no, filing_date, doc_name,
            parser_version, fetched_at, cleaned_at
        ) values (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            ("MSFT", "789019", "10-K", "annual-2025", "2025-07-30", "annual.txt", "source_v1", "now", "now"),
            ("MSFT", "789019", "10-Q", "quarter-2026", "2026-04-29", "quarter.txt", "source_v1", "now", "now"),
        ],
    )
    conn.executemany(
        """
        insert into edgar_section_cache (
            ticker, cik, form_type, accession_no, doc_name, filing_date,
            section_key, section_label, section_text, section_hash,
            parser_version, extracted_at
        ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                "MSFT",
                "789019",
                "10-K",
                "annual-2025",
                "annual.txt",
                "2025-07-30",
                "note_legacy",
                "Legacy",
                "stale",
                "legacy-hash",
                "old_parser",
                "then",
            ),
            (
                "MSFT",
                "789019",
                "10-K",
                "annual-2025",
                "annual.txt",
                "2025-07-30",
                "note_001",
                "Note 1",
                "raw note",
                "raw-hash",
                "test_parser_v6",
                "now",
            ),
            (
                "MSFT",
                "789019",
                "10-K",
                "annual-2025",
                "annual.txt",
                "2025-07-30",
                "note_revenue",
                "Revenue",
                "topic alias",
                "topic-hash",
                "test_parser_v6",
                "now",
            ),
        ],
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr(inspector, "DB_PATH", db_path)
    monkeypatch.setattr(inspector, "SECTION_PARSER_VERSION", "test_parser_v6", raising=False)

    available_sections = inspector.stage0_evidence("MSFT")
    output = capsys.readouterr().out

    assert "cached filings: 2" in output
    assert "accounting filings parsed: 1/2" in output
    assert "required accounting filing was not parsed" in output
    assert "current parsed sections: 2" in output
    assert "sections=2 raw_notes=1" in output
    assert "raw numbered note keys (1): ['note_001']" in output
    assert "topic note aliases (1): ['note_revenue']" in output
    assert "note_legacy" not in output
    assert available_sections == {"note_001", "note_revenue"}

    with pytest.raises(RuntimeError, match="parsed 1/2 required accounting filings"):
        inspector.stage0_evidence("MSFT", require_complete=True)
