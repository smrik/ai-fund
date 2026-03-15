import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from db.schema import create_tables
import src.stage_00_data.filing_retrieval as fr
from src.stage_00_data.filing_retrieval import FilingChunk


TEN_K_SAMPLE = """
Item 1. Business
The company sells software platforms.

Item 1A. Risk Factors
Competition is increasing.

Item 7. Management's Discussion and Analysis of Financial Condition and Results of Operations
Revenue grew 12% year over year and margins improved.

Item 8. Financial Statements and Supplementary Data
Consolidated Statements of Income
Notes to Consolidated Financial Statements
Note 1. Revenue Recognition
Revenue is recognized as performance obligations are satisfied.

Note 2. Leases
Operating lease liabilities increased after real estate expansion.

Note 3. Restructuring
The company recorded a restructuring charge tied to a workforce reduction.

Note 4. Acquisition
The company completed an acquisition with integration costs.

Item 9. Changes in and Disagreements With Accountants on Accounting and Financial Disclosure
"""

TEN_Q_SAMPLE = """
Part I - Item 1. Financial Statements
Condensed Consolidated Statements of Operations
Notes to Condensed Consolidated Financial Statements
Note 1. Revenue
Deferred revenue increased.

Part I - Item 2. Management's Discussion and Analysis of Financial Condition and Results of Operations
Demand remained solid but margin pressure increased.

Part II - Item 1A. Risk Factors
Macro conditions remain uncertain.
"""


def test_extract_sections_for_10k_and_note_subsections():
    sections = fr._extract_sections_for_filing("10-K", TEN_K_SAMPLE)
    keys = {key for key, _, _ in sections}

    assert "mda" in keys
    assert "notes_to_financials" in keys
    assert "risk_factors" in keys
    assert "note_revenue" in keys
    assert "note_leases" in keys
    assert "note_restructuring" in keys
    assert "note_acquisitions" in keys


def test_extract_sections_for_10q():
    sections = fr._extract_sections_for_filing("10-Q", TEN_Q_SAMPLE)
    keys = {key for key, _, _ in sections}

    assert "financial_statements_q" in keys
    assert "notes_to_financials_q" in keys
    assert "mda_q" in keys
    assert "risk_factors_q" in keys


def test_build_filing_corpus_reports_statement_presence(monkeypatch):
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
                "text": TEN_K_SAMPLE,
            },
            {
                "ticker": "IBM",
                "cik": "0000051143",
                "form_type": "10-Q",
                "accession_no": "0002",
                "doc_name": "ibm-10q.htm",
                "filing_date": "2026-03-31",
                "text": TEN_Q_SAMPLE,
            },
        ],
    )

    corpus = fr.build_filing_corpus("IBM")

    assert corpus["statement_presence"]["financial_statements"] is True
    assert corpus["statement_presence"]["notes_to_financials"] is True
    assert corpus["statement_presence"]["quarterly_notes"] is True
    assert corpus["section_coverage"]["notes_to_financials"] >= 1
    assert corpus["statement_presence_by_filing"]["0001::ibm-10k.htm"]["notes_to_financials"] is True


def test_get_agent_filing_context_falls_back_to_section_priority_without_embeddings(tmp_path, monkeypatch):
    db_path = tmp_path / "alpha_pod.db"
    monkeypatch.setattr(fr, "DB_PATH", db_path)
    conn = sqlite3.connect(db_path)
    create_tables(conn)
    conn.close()

    monkeypatch.setattr(
        fr,
        "build_filing_corpus",
        lambda ticker, include_10k=True, ten_q_limit=2: {
            "ticker": ticker,
            "sources": [{"form_type": "10-K", "accession_no": "a1", "filing_date": "2025-12-31", "doc_name": "annual.htm", "section_keys": ["notes_to_financials", "mda"]}],
            "sections": [],
            "chunks": [
                FilingChunk("10-K", "a1", "2025-12-31", "mda", 0, "MD&A discusses growth.", "mda-0"),
                FilingChunk("10-K", "a1", "2025-12-31", "notes_to_financials", 0, "Notes discuss restructuring and lease liabilities.", "notes-0"),
            ],
            "corpus_hash": "corpus-1",
            "statement_presence": {"financial_statements": True, "notes_to_financials": True, "mda": True, "risk_factors": False, "quarterly_notes": False},
            "section_coverage": {"mda": 1, "notes_to_financials": 1},
            "statement_presence_by_filing": {"a1::annual.htm": {"financial_statements": True, "notes_to_financials": True, "mda": True, "risk_factors": False, "quarterly_notes": False}},
        },
    )
    monkeypatch.setattr(fr, "_encode_texts", lambda texts, model_name: (_ for _ in ()).throw(RuntimeError("embed unavailable")))

    bundle = fr.get_agent_filing_context("IBM", profile_name="qoe", use_cache=False)

    assert bundle.retrieval_summary["fallback_mode"] is True
    assert bundle.retrieval_summary["selected_chunk_count"] == 2
    assert "mda" in bundle.retrieval_summary["skipped_sections"] or bundle.retrieval_summary["skipped_sections"] == []
    assert bundle.selected_chunks[0].section_key == "notes_to_financials"
    assert "[10-K | 2025-12-31 | notes_to_financials | chunk 0]" in bundle.rendered_text


def test_build_filing_update_context_uses_new_summary_fields():
    class _Obj:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    text = fr.build_filing_update_context(
        _Obj(notes_watch_items=["Lease liabilities moved higher"], recent_quarter_updates=["Q2 margin compressed"]),
        _Obj(notes_watch_items=["One-time restructuring"], quarterly_disclosure_changes=["10-Q added litigation disclosure"]),
    )

    assert "Filing note watch items" in text
    assert "Recent quarter updates" in text
    assert "Earnings note watch items" in text
    assert "Quarterly disclosure changes" in text
