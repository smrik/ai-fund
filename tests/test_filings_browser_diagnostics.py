from __future__ import annotations

import sqlite3
from pathlib import Path

from db.schema import create_tables
from src.stage_00_data.filing_retrieval import FilingContextBundle, FilingChunk


def _temp_db(db_path: Path):
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    create_tables(conn)
    return conn


def test_filings_browser_includes_statement_presence_and_retrieval_profiles(monkeypatch, tmp_path):
    from src.stage_04_pipeline import filings_browser

    db_path = tmp_path / "filings.db"
    conn = _temp_db(db_path)
    conn.execute(
        """
        INSERT INTO edgar_filing_cache (
            ticker, cik, form_type, accession_no, filing_date, doc_name,
            source_url, raw_path, clean_path, raw_text_hash, clean_text_hash,
            parser_version, fetched_at, cleaned_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            "IBM", "0000051143", "10-K", "0001", "2025-12-31", "ibm-10k.htm",
            "https://sec.example/ibm-10k", None, None, "raw", "clean",
            "v1", "2026-03-15T00:00:00Z", "2026-03-15T00:00:00Z",
        ],
    )
    conn.execute(
        """
        INSERT INTO edgar_section_cache (
            ticker, cik, form_type, accession_no, doc_name, filing_date, section_key,
            section_label, section_text, section_hash, parser_version, extracted_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ["IBM", "0000051143", "10-K", "0001", "ibm-10k.htm", "2025-12-31", "notes_to_financials", "Notes", "notes", "h1", "v1", "2026-03-15T00:00:00Z"],
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr(filings_browser, "DB_PATH", db_path)
    monkeypatch.setattr(
        filings_browser.filing_retrieval,
        "build_filing_corpus",
        lambda ticker, include_10k=True, ten_q_limit=2: {
            "ticker": ticker,
            "statement_presence": {"financial_statements": False, "notes_to_financials": True, "mda": False, "risk_factors": False, "quarterly_notes": False},
            "section_coverage": {"by_section_key": {"notes_to_financials": 1}},
        },
    )
    monkeypatch.setattr(
        filings_browser.filing_retrieval,
        "get_agent_filing_context",
        lambda ticker, profile_name, include_10k=True, ten_q_limit=2, use_cache=True: FilingContextBundle(
            ticker=ticker,
            profile_name=profile_name,
            corpus_hash="hash",
            sources=[],
            selected_chunks=[FilingChunk("10-K", "0001", "2025-12-31", "notes_to_financials", 0, "notes", "c1", score=0.8)],
            rendered_text="",
            retrieval_summary={
                "profile_name": profile_name,
                "selected_chunk_count": 1,
                "skipped_sections": ["business"],
                "fallback_mode": True,
                "corpus_hash": "hash",
            },
        ),
    )

    view = filings_browser.build_filings_browser_view("IBM")

    assert view["coverage_summary"]["statement_presence"]["notes_to_financials"] is True
    assert view["coverage_summary"]["statement_presence"]["financial_statements"] is False
    assert view["statement_presence_by_filing"]["0001::ibm-10k.htm"]["notes_to_financials"] is True
    assert view["retrieval_profiles"]["filings"]["selected_chunk_count"] == 1
    assert view["retrieval_profiles"]["filings"]["fallback_mode"] is True
