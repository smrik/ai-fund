from __future__ import annotations

import sqlite3
from pathlib import Path

from db.schema import create_tables
import src.stage_00_data.filing_retrieval as fr
from src.stage_00_data.filing_retrieval import FilingChunk, FilingSection


def test_build_filing_corpus_includes_statement_presence_and_section_coverage(tmp_path, monkeypatch):
    db_path = tmp_path / "alpha_pod.db"
    monkeypatch.setattr(fr, "DB_PATH", db_path)

    conn = sqlite3.connect(db_path)
    create_tables(conn)
    conn.close()

    monkeypatch.setattr(
        fr,
        "_load_filing_payloads",
        lambda ticker, include_10k=True, ten_q_limit=2: [
            {
                "ticker": "IBM",
                "cik": "0000051143",
                "form_type": "10-K",
                "accession_no": "0001",
                "doc_name": "ibm-10k.htm",
                "filing_date": "2025-12-31",
                "text": "unused",
            }
        ],
    )
    monkeypatch.setattr(
        fr,
        "_build_sections_and_chunks",
        lambda conn, filing: (
            [
                FilingSection("10-K", "0001", "2025-12-31", "financial_statements", "Financial Statements", "stmt", "h1"),
                FilingSection("10-K", "0001", "2025-12-31", "notes_to_financials", "Notes", "notes", "h2"),
                FilingSection("10-K", "0001", "2025-12-31", "mda", "MD&A", "mda", "h3"),
            ],
            [
                FilingChunk("10-K", "0001", "2025-12-31", "notes_to_financials", 0, "chunk", "c1"),
            ],
        ),
    )

    corpus = fr.build_filing_corpus("IBM")

    assert corpus["statement_presence"]["financial_statements"] is True
    assert corpus["statement_presence"]["notes_to_financials"] is True
    assert corpus["statement_presence"]["quarterly_notes"] is False
    assert corpus["section_coverage"]["by_section_key"]["notes_to_financials"] == 1
    assert corpus["sources"][0]["statement_presence"]["notes_to_financials"] is True


def test_get_agent_filing_context_reports_selected_counts_and_skipped_sections(monkeypatch):
    monkeypatch.setattr(
        fr,
        "build_filing_corpus",
        lambda ticker, include_10k=True, ten_q_limit=2: {
            "ticker": ticker,
            "sources": [{"form_type": "10-K", "accession_no": "a1", "filing_date": "2025-12-31", "doc_name": "annual.htm"}],
            "sections": [],
            "chunks": [
                FilingChunk("10-K", "a1", "2025-12-31", "notes_to_financials", 0, "notes", "notes-0"),
                FilingChunk("10-K", "a1", "2025-12-31", "mda", 1, "mda", "mda-1"),
                FilingChunk("10-K", "a1", "2025-12-31", "business", 2, "biz", "biz-2"),
            ],
            "corpus_hash": "corpus-1",
            "statement_presence": {"financial_statements": True, "notes_to_financials": True, "mda": True, "risk_factors": False, "quarterly_notes": False},
            "section_coverage": {"by_section_key": {"notes_to_financials": 1, "mda": 1, "business": 1}},
        },
    )
    monkeypatch.setattr(fr, "_encode_texts", lambda texts, model_name: (_ for _ in ()).throw(RuntimeError("embed unavailable")))

    bundle = fr.get_agent_filing_context("IBM", profile_name="qoe", use_cache=False)

    assert bundle.retrieval_summary["selected_chunk_count"] == 2
    assert "business" in bundle.retrieval_summary["skipped_sections"]
    assert bundle.retrieval_summary["corpus_hash"] == "corpus-1"
    assert bundle.retrieval_summary["excluded_section_keys"] == ["business"]
