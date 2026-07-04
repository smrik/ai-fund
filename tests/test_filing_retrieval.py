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

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "filings"


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


def test_extract_sections_for_real_msft_10k_multiline_headings():
    text = (FIXTURES_DIR / "msft_2025_10k_multiline_items.txt").read_text(encoding="utf-8")
    sections = {key: section_text for key, _, section_text in fr._extract_sections_for_filing("10-K", text)}

    assert "business" in sections
    assert "risk_factors" in sections
    assert "mda" in sections
    assert "financial_statements" in sections
    assert "Cloud provides integration" in sections["business"]
    assert "Competition in cloud services" in sections["risk_factors"]
    assert "Revenue increased due to cloud services growth" in sections["mda"]
    assert "Consolidated statements" in sections["financial_statements"]
    assert "INDEX" not in sections["business"]


def test_extract_sections_for_real_msft_10q_multiline_headings():
    text = (FIXTURES_DIR / "msft_2026_10q_multiline_items.txt").read_text(encoding="utf-8")
    sections = {key: section_text for key, _, section_text in fr._extract_sections_for_filing("10-Q", text)}

    assert "financial_statements_q" in sections
    assert "notes_to_financials_q" in sections
    assert "mda_q" in sections
    assert "risk_factors_q" in sections
    assert "Condensed consolidated statements" in sections["financial_statements_q"]
    assert "Cloud revenue increased" in sections["mda_q"]
    assert "no material changes to the risk factors" in sections["risk_factors_q"]


def test_extract_sections_for_real_iesc_standard_headings():
    text = (FIXTURES_DIR / "iesc_2025_10k_standard_items.txt").read_text(encoding="utf-8")
    sections = {key: section_text for key, _, section_text in fr._extract_sections_for_filing("10-K", text)}

    assert "business" in sections
    assert "risk_factors" in sections
    assert "mda" in sections
    assert "notes_to_financials" in sections
    assert "electrical contracting" in sections["business"]
    assert "project execution" in sections["mda"]


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
    monkeypatch.setenv("ALPHA_POD_DB_PATH", str(db_path))
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


def test_build_filing_corpus_writes_section_cache_to_env_db_path(tmp_path, monkeypatch):
    db_path = tmp_path / "alpha_pod.db"
    monkeypatch.setenv("ALPHA_POD_DB_PATH", str(db_path))
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
            }
        ],
    )

    corpus = fr.build_filing_corpus("IBM")

    assert corpus["section_coverage"]["total_sections"] > 0
    with sqlite3.connect(db_path) as conn:
        section_count = conn.execute("SELECT COUNT(*) FROM edgar_section_cache").fetchone()[0]
        chunk_count = conn.execute("SELECT COUNT(*) FROM edgar_chunk_cache").fetchone()[0]
    assert section_count > 0
    assert chunk_count > 0


def _synthetic_context_corpus(ticker, include_10k=True, ten_q_limit=2):
    return {
        "ticker": ticker,
        "sources": [
            {
                "form_type": "10-K",
                "accession_no": "a1",
                "filing_date": "2025-12-31",
                "doc_name": "annual.htm",
                "section_keys": ["notes_to_financials", "mda"],
            }
        ],
        "sections": [],
        "chunks": [
            FilingChunk("10-K", "a1", "2025-12-31", "mda", 0, "MD&A discusses growth.", "mda-0"),
            FilingChunk(
                "10-K",
                "a1",
                "2025-12-31",
                "notes_to_financials",
                0,
                "Notes discuss restructuring and lease liabilities.",
                "notes-0",
            ),
        ],
        "corpus_hash": "corpus-1",
        "statement_presence": {
            "financial_statements": True,
            "notes_to_financials": True,
            "mda": True,
            "risk_factors": False,
            "quarterly_notes": False,
        },
        "section_coverage": {"mda": 1, "notes_to_financials": 1},
        "statement_presence_by_filing": {
            "a1::annual.htm": {
                "financial_statements": True,
                "notes_to_financials": True,
                "mda": True,
                "risk_factors": False,
                "quarterly_notes": False,
            }
        },
    }


def _context_cache_count(db_path: Path) -> int:
    with sqlite3.connect(db_path) as conn:
        return conn.execute("SELECT COUNT(*) FROM filing_context_cache").fetchone()[0]


def test_fallback_scored_context_does_not_write_semantic_cache(tmp_path, monkeypatch):
    db_path = tmp_path / "alpha_pod.db"
    monkeypatch.setenv("ALPHA_POD_DB_PATH", str(db_path))
    monkeypatch.setenv("ALPHA_POD_EDGAR_CACHE_ONLY", "1")
    monkeypatch.setattr(fr, "build_filing_corpus", _synthetic_context_corpus)

    bundle = fr.get_agent_filing_context("IBM", profile_name="qoe", use_cache=True)

    assert bundle.retrieval_summary["fallback_mode"] is True
    assert _context_cache_count(db_path) == 0


def test_embedding_scored_context_still_writes_semantic_cache(tmp_path, monkeypatch):
    db_path = tmp_path / "alpha_pod.db"
    monkeypatch.setenv("ALPHA_POD_DB_PATH", str(db_path))
    monkeypatch.delenv("ALPHA_POD_EDGAR_CACHE_ONLY", raising=False)
    monkeypatch.setattr(fr, "build_filing_corpus", _synthetic_context_corpus)
    monkeypatch.setattr(fr, "_encode_texts", lambda texts, model_name: [[1.0, 0.0] for _ in texts])

    bundle = fr.get_agent_filing_context("IBM", profile_name="qoe", use_cache=True)

    assert bundle.retrieval_summary["fallback_mode"] is False
    assert bundle.retrieval_summary["used_embeddings"] is True
    assert _context_cache_count(db_path) == 1


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
