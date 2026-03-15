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


def test_build_filings_browser_view_surfaces_cached_filings_and_agent_usage(monkeypatch, tmp_path):
    from src.stage_04_pipeline import filings_browser

    db_path = tmp_path / "filings.db"
    raw_path = tmp_path / "ibm-10k.html"
    clean_path = tmp_path / "ibm-10k.txt"
    raw_path.write_text("<html>raw filing</html>", encoding="utf-8")
    clean_path.write_text("clean filing text", encoding="utf-8")

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
            "https://sec.example/ibm-10k", str(raw_path), str(clean_path), "raw", "clean",
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
        [
            "IBM", "0000051143", "10-K", "0001", "ibm-10k.htm", "2025-12-31",
            "notes_to_financials", "Notes", "notes section text", "hash-1", "v1", "2026-03-15T00:00:00Z",
        ],
    )
    conn.execute(
        """
        INSERT INTO edgar_chunk_cache (
            ticker, form_type, accession_no, doc_name, section_key, chunk_index,
            chunk_text, chunk_hash, start_char, end_char, chunk_version, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            "IBM", "10-K", "0001", "ibm-10k.htm", "notes_to_financials", 0,
            "chunk text", "chunk-hash", 0, 10, "v1", "2026-03-15T00:00:00Z",
        ],
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr(filings_browser, "DB_PATH", db_path)
    monkeypatch.setattr(
        filings_browser.filing_retrieval,
        "build_filing_corpus",
        lambda ticker, include_10k=True, ten_q_limit=2: {
            "ticker": ticker,
            "statement_presence": {"financial_statements": True, "notes_to_financials": True, "mda": False, "risk_factors": False, "quarterly_notes": False},
            "section_coverage": {"notes_to_financials": 1},
            "statement_presence_by_filing": {"0001::ibm-10k.htm": {"financial_statements": True, "notes_to_financials": True, "mda": False, "risk_factors": False, "quarterly_notes": False}},
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
            selected_chunks=[
                FilingChunk(
                    form_type="10-K",
                    accession_no="0001",
                    filing_date="2025-12-31",
                    section_key="notes_to_financials",
                    chunk_index=0,
                    text=f"{profile_name} chunk",
                    chunk_hash=f"{profile_name}-hash",
                    score=0.9,
                )
            ],
            rendered_text="",
            retrieval_summary={"fallback_mode": False, "selected_chunk_count": 1, "skipped_sections": []},
        ),
    )

    view = filings_browser.build_filings_browser_view("IBM")

    assert len(view["filings"]) == 1
    filing = view["filings"][0]
    assert filing["raw_available"] is True
    assert filing["clean_available"] is True
    assert filing["clean_text"] == "clean filing text"
    assert filing["raw_html"] == "<html>raw filing</html>"
    assert filing["filing_key"] == "0001::ibm-10k.htm"
    assert view["sections_by_filing"]["0001::ibm-10k.htm"][0]["section_key"] == "notes_to_financials"
    assert view["chunks_by_filing"]["0001::ibm-10k.htm"][0]["chunk_hash"] == "chunk-hash"
    assert view["agent_usage"]["filings"][0]["section_key"] == "notes_to_financials"
    assert view["coverage_summary"]["notes_to_financials"] == 1
    assert view["statement_presence_by_filing"]["0001::ibm-10k.htm"]["financial_statements"] is True
    assert view["retrieval_profiles"]["filings"]["selected_chunk_count"] == 1


def test_build_filings_browser_view_marks_unavailable_when_no_cached_filings(monkeypatch, tmp_path):
    from src.stage_04_pipeline import filings_browser

    db_path = tmp_path / "filings.db"
    conn = _temp_db(db_path)
    conn.close()

    monkeypatch.setattr(filings_browser, "DB_PATH", db_path)
    monkeypatch.setattr(
        filings_browser.filing_retrieval,
        "build_filing_corpus",
        lambda ticker, include_10k=True, ten_q_limit=2: {"ticker": ticker, "statement_presence": {}, "section_coverage": {}, "statement_presence_by_filing": {}},
    )
    monkeypatch.setattr(
        filings_browser.filing_retrieval,
        "get_agent_filing_context",
        lambda *args, **kwargs: FilingContextBundle(
            ticker="IBM",
            profile_name="filings",
            corpus_hash="hash",
            sources=[],
            selected_chunks=[],
            rendered_text="",
            retrieval_summary={},
        ),
    )

    view = filings_browser.build_filings_browser_view("IBM")

    assert view["available"] is False
    assert view["filings"] == []
    assert view["sections_by_filing"] == {}
    assert view["chunks_by_filing"] == {}


def test_build_filings_browser_view_includes_doc_name_in_agent_usage(monkeypatch, tmp_path):
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
            "IBM", "0000051143", "10-Q", "0002", "2026-03-31", "ibm-10q.htm",
            "https://sec.example/ibm-10q", None, None, "raw", "clean",
            "v1", "2026-03-15T00:00:00Z", "2026-03-15T00:00:00Z",
        ],
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr(filings_browser, "DB_PATH", db_path)
    monkeypatch.setattr(
        filings_browser.filing_retrieval,
        "build_filing_corpus",
        lambda ticker, include_10k=True, ten_q_limit=2: {"ticker": ticker, "statement_presence": {}, "section_coverage": {}, "statement_presence_by_filing": {}},
    )
    monkeypatch.setattr(
        filings_browser.filing_retrieval,
        "get_agent_filing_context",
        lambda ticker, profile_name, include_10k=True, ten_q_limit=2, use_cache=True: FilingContextBundle(
            ticker=ticker,
            profile_name=profile_name,
            corpus_hash="hash",
            sources=[
                {
                    "form_type": "10-Q",
                    "accession_no": "0002",
                    "filing_date": "2026-03-31",
                    "doc_name": "ibm-10q.htm",
                }
            ],
            selected_chunks=[
                FilingChunk(
                    form_type="10-Q",
                    accession_no="0002",
                    filing_date="2026-03-31",
                    section_key="mda_q",
                    chunk_index=1,
                    text="quarter chunk",
                    chunk_hash="q-hash",
                    score=0.8,
                )
            ],
            rendered_text="",
            retrieval_summary={"fallback_mode": False, "selected_chunk_count": 1, "skipped_sections": []},
        ),
    )

    view = filings_browser.build_filings_browser_view("IBM", forms=("10-Q",), max_filings_per_form=1)

    assert view["agent_usage"]["earnings"][0]["doc_name"] == "ibm-10q.htm"
    assert view["agent_usage"]["earnings"][0]["filing_key"] == "0002::ibm-10q.htm"
