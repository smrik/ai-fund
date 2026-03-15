from __future__ import annotations

from pathlib import Path
import sqlite3

from config import DB_PATH
from db.schema import create_tables
from src.stage_00_data import filing_retrieval


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    create_tables(conn)
    return conn


def _filing_key(accession_no: str, doc_name: str) -> str:
    return f"{accession_no}::{doc_name}"


def _read_text(path_str: str | None) -> str:
    if not path_str:
        return ""
    path = Path(path_str)
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def _statement_presence_from_sections(section_rows: list[dict]) -> dict[str, bool]:
    section_keys = {row.get("section_key") for row in section_rows if row.get("section_key")}
    return filing_retrieval._statement_presence_from_keys(section_keys)  # type: ignore[attr-defined]


def _coverage_summary(corpus: dict) -> dict:
    statement_presence = dict(corpus.get("statement_presence") or {})
    section_coverage = corpus.get("section_coverage") or {}
    if isinstance(section_coverage, dict):
        if isinstance(section_coverage.get("by_section_key"), dict):
            by_section_key = dict(section_coverage.get("by_section_key") or {})
        else:
            by_section_key = {
                str(key): int(value)
                for key, value in section_coverage.items()
                if isinstance(value, (int, float))
            }
    else:
        by_section_key = {}
    summary = {
        "statement_presence": statement_presence,
        "section_coverage": section_coverage,
        "by_section_key": by_section_key,
    }
    # Preserve the older direct count lookup style for existing tests/callers.
    summary.update(by_section_key)
    return summary


def build_filings_browser_view(
    ticker: str,
    *,
    forms: tuple[str, ...] = ("10-K", "10-Q"),
    max_filings_per_form: int = 3,
) -> dict:
    ticker = ticker.upper().strip()
    corpus = filing_retrieval.build_filing_corpus(
        ticker,
        include_10k="10-K" in forms,
        ten_q_limit=max_filings_per_form if "10-Q" in forms else 0,
    )

    with _connect() as conn:
        filings: list[dict] = []
        for form_type in forms:
            rows = conn.execute(
                """
                SELECT ticker, cik, form_type, accession_no, filing_date, doc_name,
                       source_url, raw_path, clean_path
                FROM edgar_filing_cache
                WHERE ticker = ? AND form_type = ?
                ORDER BY filing_date DESC, accession_no DESC
                LIMIT ?
                """,
                [ticker, form_type, int(max_filings_per_form)],
            ).fetchall()
            filings.extend(dict(row) for row in rows)

        selected_keys = {_filing_key(f["accession_no"], f["doc_name"]) for f in filings}
        sections_rows = conn.execute(
            """
            SELECT accession_no, doc_name, filing_date, section_key, section_label, section_text
            FROM edgar_section_cache
            WHERE ticker = ?
            ORDER BY filing_date DESC, accession_no DESC, section_key ASC
            """,
            [ticker],
        ).fetchall()
        chunks_rows = conn.execute(
            """
            SELECT accession_no, doc_name, section_key, chunk_index, chunk_text, chunk_hash
            FROM edgar_chunk_cache
            WHERE ticker = ?
            ORDER BY accession_no DESC, section_key ASC, chunk_index ASC
            """,
            [ticker],
        ).fetchall()

    sections_by_filing: dict[str, list[dict]] = {key: [] for key in selected_keys}
    chunks_by_filing: dict[str, list[dict]] = {key: [] for key in selected_keys}
    for row in sections_rows:
        key = _filing_key(row["accession_no"], row["doc_name"])
        if key in sections_by_filing:
            sections_by_filing[key].append(dict(row))
    for row in chunks_rows:
        key = _filing_key(row["accession_no"], row["doc_name"])
        if key in chunks_by_filing:
            chunks_by_filing[key].append(dict(row))

    filing_by_accession: dict[str, dict] = {}
    for filing in filings:
        filing["filing_key"] = _filing_key(filing["accession_no"], filing["doc_name"])
        filing["raw_available"] = bool(filing.get("raw_path")) and Path(filing["raw_path"]).exists()
        filing["clean_available"] = bool(filing.get("clean_path")) and Path(filing["clean_path"]).exists()
        filing["raw_html"] = _read_text(filing.get("raw_path"))
        filing["clean_text"] = _read_text(filing.get("clean_path"))
        sections_by_filing.setdefault(filing["accession_no"], sections_by_filing.get(filing["filing_key"], []))
        chunks_by_filing.setdefault(filing["accession_no"], chunks_by_filing.get(filing["filing_key"], []))
        filing_by_accession[filing["accession_no"]] = filing

    statement_presence_by_filing = dict(corpus.get("statement_presence_by_filing") or {})
    for filing in filings:
        filing_key = filing["filing_key"]
        if filing_key not in statement_presence_by_filing:
            statement_presence_by_filing[filing_key] = _statement_presence_from_sections(
                sections_by_filing.get(filing_key, [])
            )

    agent_usage: dict[str, list[dict]] = {}
    retrieval_profiles: dict[str, dict] = {}
    for profile_name in ("filings", "earnings", "qoe", "accounting_recast"):
        try:
            bundle = filing_retrieval.get_agent_filing_context(
                ticker,
                profile_name=profile_name,
                include_10k="10-K" in forms,
                ten_q_limit=max_filings_per_form if "10-Q" in forms else 0,
                use_cache=True,
            )
        except Exception:
            agent_usage[profile_name] = []
            retrieval_profiles[profile_name] = {
                "fallback_mode": True,
                "selected_chunk_count": 0,
                "skipped_sections": [],
            }
            continue

        used_chunks: list[dict] = []
        source_doc_names = {
            source.get("accession_no"): source.get("doc_name")
            for source in getattr(bundle, "sources", [])
            if source.get("accession_no")
        }
        for chunk in bundle.selected_chunks:
            filing = filing_by_accession.get(chunk.accession_no)
            doc_name = source_doc_names.get(chunk.accession_no)
            if doc_name is None and filing is not None:
                doc_name = filing.get("doc_name")
            used_chunks.append(
                {
                    "filing_key": _filing_key(chunk.accession_no, doc_name or ""),
                    "accession_no": chunk.accession_no,
                    "doc_name": doc_name,
                    "form_type": chunk.form_type,
                    "filing_date": chunk.filing_date,
                    "section_key": chunk.section_key,
                    "chunk_index": chunk.chunk_index,
                    "chunk_hash": chunk.chunk_hash,
                    "score": chunk.score,
                    "text": chunk.text,
                }
            )
        agent_usage[profile_name] = used_chunks
        retrieval_profiles[profile_name] = bundle.retrieval_summary

    return {
        "ticker": ticker,
        "available": bool(filings),
        "filings": filings,
        "sections_by_filing": sections_by_filing,
        "chunks_by_filing": chunks_by_filing,
        "agent_usage": agent_usage,
        "coverage_summary": _coverage_summary(corpus),
        "statement_presence_by_filing": statement_presence_by_filing,
        "retrieval_profiles": retrieval_profiles,
    }
