from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
import re
import sqlite3
from typing import Any

from config import DB_PATH, EDGAR_PARSER_VERSION, PEER_SIMILARITY_MODEL
from db.loader import (
    upsert_edgar_chunk_cache,
    upsert_edgar_chunk_embedding,
    upsert_edgar_section_cache,
    upsert_filing_context_cache,
)
from db.schema import create_tables
from src.stage_00_data import edgar_client

_SECTION_PARSER_VERSION = f"{EDGAR_PARSER_VERSION}_sections_v1"
_CHUNK_VERSION = "v1"
_QUERY_VERSION = "v1"
_EMBEDDING_MODEL = PEER_SIMILARITY_MODEL
_CHUNK_SIZE = 1400
_CHUNK_OVERLAP = 200
_MAX_SELECTED_CHUNKS = 12
_MODEL_CACHE: dict[str, object] = {}

_PROFILE_CONFIGS: dict[str, dict[str, Any]] = {
    "filings": {
        "priorities": [
            "notes_to_financials",
            "mda",
            "mda_q",
            "notes_to_financials_q",
            "risk_factors",
            "risk_factors_q",
        ],
        "queries": [
            "revenue growth drivers pricing volume geography segment",
            "margin expansion contraction profitability cost pressure",
            "balance sheet debt liquidity cash borrowing covenant",
            "accounting risk accrual revenue recognition cash conversion one time",
        ],
    },
    "earnings": {
        "priorities": [
            "notes_to_financials_q",
            "mda_q",
            "notes_to_financials",
            "mda",
        ],
        "queries": [
            "unusual charges restructuring impairment acquisition litigation",
            "non recurring gains losses adjustments segment performance margin pressure",
            "guidance demand pricing backlog headwinds macro",
        ],
    },
    "qoe": {
        "priorities": [
            "notes_to_financials",
            "note_revenue",
            "note_restructuring",
            "note_impairment",
            "note_acquisitions",
            "note_contingencies",
            "notes_to_financials_q",
            "mda",
            "mda_q",
        ],
        "queries": [
            "revenue recognition bill and hold deferred revenue contract asset",
            "restructuring impairment gains on sale litigation settlement acquisition cost",
            "accrual reserve provision working capital dso dio dpo",
            "auditor material weakness going concern internal control",
        ],
    },
    "accounting_recast": {
        "priorities": [
            "notes_to_financials",
            "note_leases",
            "note_pension",
            "note_debt",
            "note_taxes",
            "note_contingencies",
            "note_segments",
            "notes_to_financials_q",
            "mda",
            "mda_q",
        ],
        "queries": [
            "lease liabilities operating lease finance lease right of use",
            "pension obligation postretirement underfunded status",
            "minority interest noncontrolling preferred stock equity investment affiliate",
            "debt contingencies taxes fair value bridge one time ebit adjustment",
        ],
    },
}

_NOTE_TOPIC_PATTERNS: list[tuple[str, str]] = [
    ("note_revenue", r"revenue|contract|customer"),
    ("note_segments", r"segment|geographic"),
    ("note_leases", r"lease|right-of-use|right of use"),
    ("note_restructuring", r"restructuring|reorganization|transformation"),
    ("note_impairment", r"impairment|write-down|write down"),
    ("note_acquisitions", r"acquisition|business combination|purchase accounting"),
    ("note_contingencies", r"contingenc|litigation|legal proceeding|commitment"),
    ("note_pension", r"pension|retirement|postretirement"),
    ("note_taxes", r"income tax|taxation|taxes"),
    ("note_fair_value", r"fair value|level 1|level 2|level 3"),
    ("note_debt", r"debt|borrowings|credit facility|notes payable"),
]


def _statement_presence_from_keys(section_keys: set[str]) -> dict[str, bool]:
    return {
        "financial_statements": bool({"financial_statements", "financial_statements_q"} & section_keys),
        "notes_to_financials": "notes_to_financials" in section_keys,
        "mda": bool({"mda", "mda_q"} & section_keys),
        "risk_factors": bool({"risk_factors", "risk_factors_q"} & section_keys),
        "quarterly_notes": "notes_to_financials_q" in section_keys,
    }


def _section_coverage_payload(
    counts: dict[str, int],
    *,
    total_sections: int,
    total_chunks: int,
    source_count: int,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "by_section_key": dict(counts),
        "total_sections": int(total_sections),
        "total_chunks": int(total_chunks),
        "source_count": int(source_count),
    }
    # Preserve the older flat lookup style used by existing callers/tests.
    payload.update(counts)
    return payload


def _section_count_map(section_coverage: Any) -> dict[str, int]:
    if isinstance(section_coverage, dict):
        nested = section_coverage.get("by_section_key")
        if isinstance(nested, dict):
            return {str(key): int(value) for key, value in nested.items()}
        return {
            str(key): int(value)
            for key, value in section_coverage.items()
            if isinstance(value, (int, float))
        }
    return {}


@dataclass
class FilingSection:
    form_type: str
    accession_no: str
    filing_date: str | None
    section_key: str
    section_label: str
    text: str
    text_hash: str


@dataclass
class FilingChunk:
    form_type: str
    accession_no: str
    filing_date: str | None
    section_key: str
    chunk_index: int
    text: str
    chunk_hash: str
    score: float | None = None


@dataclass
class FilingContextBundle:
    ticker: str
    profile_name: str
    corpus_hash: str
    sources: list[dict]
    selected_chunks: list[FilingChunk]
    rendered_text: str
    retrieval_summary: dict


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    create_tables(conn)
    return conn


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _normalize_heading_text(text: str) -> str:
    return (
        text.replace("\u2019", "'")
        .replace("\u2018", "'")
        .replace("\u2013", "-")
        .replace("\u2014", "-")
        .replace("\u2012", "-")
    )


def _extract_section(text: str, start_patterns: list[str], end_patterns: list[str]) -> str:
    haystack = _normalize_heading_text(text)
    start_match = None
    for pattern in start_patterns:
        match = re.search(pattern, haystack, flags=re.IGNORECASE | re.MULTILINE)
        if match and (start_match is None or match.start() < start_match.start()):
            start_match = match
    if start_match is None:
        return ""

    start = start_match.start()
    end = len(haystack)
    for pattern in end_patterns:
        match = re.search(pattern, haystack[start_match.end() :], flags=re.IGNORECASE | re.MULTILINE)
        if match:
            candidate = start_match.end() + match.start()
            if candidate > start and candidate < end:
                end = candidate
    return haystack[start:end].strip()


def _extract_note_subsections(form_type: str, notes_text: str) -> list[tuple[str, str]]:
    if not notes_text:
        return []
    note_matches = list(
        re.finditer(
            r"(?im)(?:^|\n)\s*(note\s+\d+[a-z]?(?:[\.:\-\s]+)[^\n]{0,140})",
            notes_text,
        )
    )
    if not note_matches:
        return []

    results: list[tuple[str, str]] = []
    seen: set[str] = set()
    for idx, match in enumerate(note_matches):
        start = match.start(1)
        end = note_matches[idx + 1].start(1) if idx + 1 < len(note_matches) else len(notes_text)
        heading = match.group(1).strip()
        block = notes_text[start:end].strip()
        if len(block) < 80:
            continue
        for section_key, pattern in _NOTE_TOPIC_PATTERNS:
            if section_key in seen:
                continue
            if re.search(pattern, heading, flags=re.IGNORECASE):
                label = f"{heading}"
                results.append((section_key, f"{label}\n{block}"))
                seen.add(section_key)
                break
    return results


def _extract_sections_for_filing(form_type: str, text: str) -> list[tuple[str, str, str]]:
    text = _normalize_heading_text(text)
    sections: list[tuple[str, str, str]] = []

    if form_type == "10-K":
        definitions = [
            (
                "business",
                "Business",
                [r"(^|\n)\s*item\s+1\.?\s+business\b"],
                [r"(^|\n)\s*item\s+1a\.?\s+risk\s+factors\b", r"(^|\n)\s*item\s+2\.?\b"],
            ),
            (
                "risk_factors",
                "Risk Factors",
                [r"(^|\n)\s*item\s+1a\.?\s+risk\s+factors\b"],
                [r"(^|\n)\s*item\s+1b\.?\b", r"(^|\n)\s*item\s+2\.?\b", r"(^|\n)\s*item\s+7\.?\b"],
            ),
            (
                "mda",
                "MD&A",
                [
                    r"(^|\n)\s*item\s+7\.?\s+management'?s\s+discussion\s+and\s+analysis\b",
                    r"(^|\n)\s*management'?s\s+discussion\s+and\s+analysis\b",
                ],
                [r"(^|\n)\s*item\s+7a\.?\b", r"(^|\n)\s*item\s+8\.?\s+financial\s+statements\b"],
            ),
            (
                "financial_statements",
                "Financial Statements",
                [r"(^|\n)\s*item\s+8\.?\s+financial\s+statements.*\b"],
                [r"(^|\n)\s*item\s+9\.?\b", r"(^|\n)\s*signatures\b"],
            ),
            (
                "notes_to_financials",
                "Notes to Financial Statements",
                [
                    r"(^|\n)\s*notes\s+to\s+(?:condensed\s+)?consolidated\s+financial\s+statements\b",
                    r"(^|\n)\s*notes\s+to\s+financial\s+statements\b",
                ],
                [r"(^|\n)\s*item\s+9\.?\b", r"(^|\n)\s*signatures\b"],
            ),
        ]
    else:
        definitions = [
            (
                "financial_statements_q",
                "Quarterly Financial Statements",
                [r"(^|\n)\s*part\s+i\s*-?\s*item\s+1\.?\s+financial\s+statements\b"],
                [r"(^|\n)\s*part\s+i\s*-?\s*item\s+2\.?\s+management'?s\s+discussion\b"],
            ),
            (
                "notes_to_financials_q",
                "Quarterly Notes to Financial Statements",
                [
                    r"(^|\n)\s*notes\s+to\s+(?:condensed\s+)?consolidated\s+financial\s+statements\b",
                    r"(^|\n)\s*notes\s+to\s+financial\s+statements\b",
                ],
                [r"(^|\n)\s*part\s+i\s*-?\s*item\s+2\.?\s+management'?s\s+discussion\b"],
            ),
            (
                "mda_q",
                "Quarterly MD&A",
                [r"(^|\n)\s*part\s+i\s*-?\s*item\s+2\.?\s+management'?s\s+discussion\s+and\s+analysis\b"],
                [r"(^|\n)\s*part\s+i\s*-?\s*item\s+3\.?\b", r"(^|\n)\s*part\s+ii\s*-?\s*item\s+1a\.?\b"],
            ),
            (
                "risk_factors_q",
                "Quarterly Risk Factors",
                [r"(^|\n)\s*part\s+ii\s*-?\s*item\s+1a\.?\s+risk\s+factors\b"],
                [r"(^|\n)\s*part\s+ii\s*-?\s*item\s+2\.?\b", r"(^|\n)\s*signatures\b"],
            ),
        ]

    for section_key, label, start_patterns, end_patterns in definitions:
        section_text = _extract_section(text, start_patterns, end_patterns)
        if section_text:
            sections.append((section_key, label, section_text))

    if form_type == "10-K":
        notes_text = next((value for key, _, value in sections if key == "notes_to_financials"), "")
        for note_key, note_text in _extract_note_subsections(form_type, notes_text):
            sections.append((note_key, note_key.replace("_", " ").title(), note_text))

    return sections


def _chunk_text(text: str, *, chunk_size: int = _CHUNK_SIZE, overlap: int = _CHUNK_OVERLAP) -> list[tuple[int, int, str]]:
    cleaned = (text or "").strip()
    if not cleaned:
        return []
    if len(cleaned) <= chunk_size:
        return [(0, len(cleaned), cleaned)]

    chunks: list[tuple[int, int, str]] = []
    start = 0
    while start < len(cleaned):
        end = min(len(cleaned), start + chunk_size)
        chunk = cleaned[start:end].strip()
        if chunk:
            chunks.append((start, end, chunk))
        if end >= len(cleaned):
            break
        start = max(end - overlap, start + 1)
    return chunks


def _encode_texts(texts: list[str], model_name: str) -> list[list[float]]:
    from sentence_transformers import SentenceTransformer  # type: ignore

    model = _MODEL_CACHE.get(model_name)
    if model is None:
        model = SentenceTransformer(model_name)
        _MODEL_CACHE[model_name] = model
    embeddings = model.encode(texts, convert_to_numpy=False, normalize_embeddings=False)
    return [[float(v) for v in vector] for vector in embeddings]


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm <= 0 or right_norm <= 0:
        return 0.0
    return dot / (left_norm * right_norm)


def _normalise_similarity(score: float) -> float:
    return max(0.0, min(1.0, (score + 1.0) / 2.0))


def _load_cached_sections(
    conn: sqlite3.Connection,
    ticker: str,
    accession_no: str,
    doc_name: str,
) -> list[FilingSection]:
    rows = conn.execute(
        """
        SELECT form_type, accession_no, filing_date, section_key, section_label, section_text, section_hash
        FROM edgar_section_cache
        WHERE ticker = ? AND accession_no = ? AND doc_name = ? AND parser_version = ?
        ORDER BY section_key
        """,
        [ticker.upper(), accession_no, doc_name, _SECTION_PARSER_VERSION],
    ).fetchall()
    return [
        FilingSection(
            form_type=row["form_type"],
            accession_no=row["accession_no"],
            filing_date=row["filing_date"],
            section_key=row["section_key"],
            section_label=row["section_label"],
            text=row["section_text"],
            text_hash=row["section_hash"],
        )
        for row in rows
    ]


def _load_cached_chunks(
    conn: sqlite3.Connection,
    ticker: str,
    accession_no: str,
    doc_name: str,
) -> list[FilingChunk]:
    rows = conn.execute(
        """
        SELECT
            c.form_type AS form_type,
            c.accession_no AS accession_no,
            s.filing_date AS filing_date,
            c.section_key AS section_key,
            c.chunk_index AS chunk_index,
            c.chunk_text AS chunk_text,
            c.chunk_hash AS chunk_hash
        FROM edgar_chunk_cache c
        JOIN edgar_section_cache s
          ON s.ticker = c.ticker
         AND s.accession_no = c.accession_no
         AND s.doc_name = c.doc_name
         AND s.section_key = c.section_key
         AND s.parser_version = ?
        WHERE c.ticker = ? AND c.accession_no = ? AND c.doc_name = ? AND c.chunk_version = ?
        ORDER BY c.section_key, c.chunk_index
        """,
        [_SECTION_PARSER_VERSION, ticker.upper(), accession_no, doc_name, _CHUNK_VERSION],
    ).fetchall()
    return [
        FilingChunk(
            form_type=row["form_type"],
            accession_no=row["accession_no"],
            filing_date=row["filing_date"],
            section_key=row["section_key"],
            chunk_index=int(row["chunk_index"]),
            text=row["chunk_text"],
            chunk_hash=row["chunk_hash"],
        )
        for row in rows
    ]


def _load_cached_chunk_embedding(conn: sqlite3.Connection, chunk_hash: str, model_name: str) -> list[float] | None:
    row = conn.execute(
        """
        SELECT embedding_blob
        FROM edgar_chunk_embeddings
        WHERE chunk_hash = ? AND embedding_model = ?
        LIMIT 1
        """,
        [chunk_hash, model_name],
    ).fetchone()
    if row is None:
        return None
    return [float(v) for v in json.loads(row["embedding_blob"])]


def _get_or_create_chunk_embedding(conn: sqlite3.Connection, chunk_hash: str, text: str, model_name: str) -> list[float]:
    cached = _load_cached_chunk_embedding(conn, chunk_hash, model_name)
    if cached is not None:
        return cached
    embedding = _encode_texts([text], model_name)[0]
    upsert_edgar_chunk_embedding(
        conn,
        {
            "chunk_hash": chunk_hash,
            "embedding_model": model_name,
            "embedding_dim": len(embedding),
            "embedding_blob": json.dumps(embedding, separators=(",", ":")),
            "created_at": _now(),
        },
    )
    return embedding


def _section_priority_score(section_key: str, priorities: list[str]) -> float:
    if section_key in priorities:
        index = priorities.index(section_key)
        return max(0.1, 1.0 - (index / max(1, len(priorities))))
    return 0.1


def _context_to_dict(bundle: FilingContextBundle) -> dict[str, Any]:
    return {
        "ticker": bundle.ticker,
        "profile_name": bundle.profile_name,
        "corpus_hash": bundle.corpus_hash,
        "sources": bundle.sources,
        "selected_chunks": [asdict(chunk) for chunk in bundle.selected_chunks],
        "rendered_text": bundle.rendered_text,
        "retrieval_summary": bundle.retrieval_summary,
    }


def _context_from_dict(payload: dict[str, Any]) -> FilingContextBundle:
    return FilingContextBundle(
        ticker=payload["ticker"],
        profile_name=payload["profile_name"],
        corpus_hash=payload["corpus_hash"],
        sources=payload.get("sources", []),
        selected_chunks=[FilingChunk(**chunk) for chunk in payload.get("selected_chunks", [])],
        rendered_text=payload.get("rendered_text", ""),
        retrieval_summary=payload.get("retrieval_summary", {}),
    )


def _load_cached_context(
    conn: sqlite3.Connection,
    ticker: str,
    profile_name: str,
    corpus_hash: str,
    model_name: str,
) -> FilingContextBundle | None:
    row = conn.execute(
        """
        SELECT context_json
        FROM filing_context_cache
        WHERE ticker = ? AND profile_name = ? AND corpus_hash = ? AND query_version = ? AND embedding_model = ?
        LIMIT 1
        """,
        [ticker.upper(), profile_name, corpus_hash, _QUERY_VERSION, model_name],
    ).fetchone()
    if row is None:
        return None
    return _context_from_dict(json.loads(row["context_json"]))


def _store_context_cache(conn: sqlite3.Connection, bundle: FilingContextBundle, model_name: str) -> None:
    upsert_filing_context_cache(
        conn,
        {
            "ticker": bundle.ticker,
            "profile_name": bundle.profile_name,
            "corpus_hash": bundle.corpus_hash,
            "query_version": _QUERY_VERSION,
            "embedding_model": model_name,
            "context_json": json.dumps(_context_to_dict(bundle), separators=(",", ":"), default=str),
            "created_at": _now(),
        },
    )


def _load_filing_payloads(ticker: str, *, include_10k: bool, ten_q_limit: int) -> list[dict[str, Any]]:
    cik = edgar_client.get_cik(ticker)
    filings: list[dict[str, Any]] = []

    if include_10k:
        for meta in edgar_client.get_recent_filing_metadata(ticker, "10-K", limit=1):
            text = edgar_client.get_filing_text_by_accession(ticker, meta["accession_no"], max_chars=250_000)
            if text:
                filings.append(
                    {
                        "ticker": ticker.upper(),
                        "cik": cik,
                        "form_type": "10-K",
                        "accession_no": meta["accession_no"],
                        "doc_name": meta["primary_doc"],
                        "filing_date": meta.get("filing_date"),
                        "text": text,
                    }
                )

    for meta in edgar_client.get_recent_filing_metadata(ticker, "10-Q", limit=ten_q_limit):
        text = edgar_client.get_filing_text_by_accession(ticker, meta["accession_no"], max_chars=180_000)
        if text:
            filings.append(
                {
                    "ticker": ticker.upper(),
                    "cik": cik,
                    "form_type": "10-Q",
                    "accession_no": meta["accession_no"],
                    "doc_name": meta["primary_doc"],
                    "filing_date": meta.get("filing_date"),
                    "text": text,
                }
            )
    return filings


def _build_sections_and_chunks(conn: sqlite3.Connection, filing: dict[str, Any]) -> tuple[list[FilingSection], list[FilingChunk]]:
    cached_sections = _load_cached_sections(conn, filing["ticker"], filing["accession_no"], filing["doc_name"])
    cached_chunks = _load_cached_chunks(conn, filing["ticker"], filing["accession_no"], filing["doc_name"])
    if cached_sections and cached_chunks:
        return cached_sections, cached_chunks

    section_defs = _extract_sections_for_filing(filing["form_type"], filing["text"])
    if not section_defs:
        fallback_key = "notes_to_financials_q" if filing["form_type"] == "10-Q" else "notes_to_financials"
        section_defs = [(fallback_key, fallback_key.replace("_", " ").title(), filing["text"])]

    sections: list[FilingSection] = []
    section_rows: list[dict[str, Any]] = []
    for section_key, section_label, section_text in section_defs:
        section = FilingSection(
            form_type=filing["form_type"],
            accession_no=filing["accession_no"],
            filing_date=filing.get("filing_date"),
            section_key=section_key,
            section_label=section_label,
            text=section_text,
            text_hash=_hash_text(section_text),
        )
        sections.append(section)
        section_rows.append(
            {
                "ticker": filing["ticker"],
                "cik": filing["cik"],
                "form_type": filing["form_type"],
                "accession_no": filing["accession_no"],
                "doc_name": filing["doc_name"],
                "filing_date": filing.get("filing_date"),
                "section_key": section_key,
                "section_label": section_label,
                "section_text": section_text,
                "section_hash": section.text_hash,
                "parser_version": _SECTION_PARSER_VERSION,
                "extracted_at": _now(),
            }
        )
    upsert_edgar_section_cache(conn, section_rows)

    chunks: list[FilingChunk] = []
    chunk_rows: list[dict[str, Any]] = []
    for section in sections:
        for chunk_index, (start_char, end_char, chunk_text) in enumerate(_chunk_text(section.text)):
            chunk = FilingChunk(
                form_type=section.form_type,
                accession_no=section.accession_no,
                filing_date=section.filing_date,
                section_key=section.section_key,
                chunk_index=chunk_index,
                text=chunk_text,
                chunk_hash=_hash_text(
                    f"{filing['ticker']}|{section.form_type}|{section.accession_no}|{section.section_key}|{chunk_index}|{chunk_text}"
                ),
            )
            chunks.append(chunk)
            chunk_rows.append(
                {
                    "ticker": filing["ticker"],
                    "form_type": section.form_type,
                    "accession_no": section.accession_no,
                    "doc_name": filing["doc_name"],
                    "section_key": section.section_key,
                    "chunk_index": chunk_index,
                    "chunk_text": chunk_text,
                    "chunk_hash": chunk.chunk_hash,
                    "start_char": start_char,
                    "end_char": end_char,
                    "chunk_version": _CHUNK_VERSION,
                    "created_at": _now(),
                }
            )
    upsert_edgar_chunk_cache(conn, chunk_rows)
    return sections, chunks


def build_filing_corpus(
    ticker: str,
    *,
    include_10k: bool = True,
    ten_q_limit: int = 2,
) -> dict:
    ticker = ticker.upper().strip()
    filings = _load_filing_payloads(ticker, include_10k=include_10k, ten_q_limit=ten_q_limit)
    conn = _connect()
    try:
        all_sections: list[FilingSection] = []
        all_chunks: list[FilingChunk] = []
        sources: list[dict[str, Any]] = []
        statement_presence_by_filing: dict[str, dict[str, bool]] = {}
        for filing in filings:
            sections, chunks = _build_sections_and_chunks(conn, filing)
            all_sections.extend(sections)
            all_chunks.extend(chunks)
            section_keys = {section.section_key for section in sections}
            filing_key = f"{filing['accession_no']}::{filing['doc_name']}"
            statement_presence = _statement_presence_from_keys(section_keys)
            statement_presence_by_filing[filing_key] = statement_presence
            sources.append(
                {
                    "form_type": filing["form_type"],
                    "accession_no": filing["accession_no"],
                    "filing_date": filing.get("filing_date"),
                    "doc_name": filing["doc_name"],
                    "section_keys": sorted(section_keys),
                    "statement_presence": statement_presence,
                }
            )
        section_coverage_counts: dict[str, int] = {}
        for section in all_sections:
            section_coverage_counts[section.section_key] = section_coverage_counts.get(section.section_key, 0) + 1
        statement_presence = _statement_presence_from_keys(set(section_coverage_counts))
        section_coverage = _section_coverage_payload(
            section_coverage_counts,
            total_sections=len(all_sections),
            total_chunks=len(all_chunks),
            source_count=len(sources),
        )
        corpus_hash = _hash_text(
            json.dumps(
                [
                    {
                        "form_type": chunk.form_type,
                        "accession_no": chunk.accession_no,
                        "section_key": chunk.section_key,
                        "chunk_hash": chunk.chunk_hash,
                    }
                    for chunk in all_chunks
                ],
                sort_keys=True,
            )
        )
        return {
            "ticker": ticker,
            "sources": sources,
            "sections": all_sections,
            "chunks": all_chunks,
            "corpus_hash": corpus_hash,
            "statement_presence": statement_presence,
            "section_coverage": section_coverage,
            "statement_presence_by_filing": statement_presence_by_filing,
        }
    finally:
        conn.close()


def render_filing_context(bundle: FilingContextBundle, max_chars: int) -> str:
    rendered: list[str] = []
    total_chars = 0
    for chunk in bundle.selected_chunks:
        filing_date = chunk.filing_date or "unknown-date"
        header = f"[{chunk.form_type} | {filing_date} | {chunk.section_key} | chunk {chunk.chunk_index}]\n"
        block = header + chunk.text.strip() + "\n"
        if total_chars + len(block) > max_chars:
            remaining = max_chars - total_chars
            if remaining > len(header) + 60:
                trimmed = block[:remaining].rstrip() + "\n"
                rendered.append(trimmed)
            break
        rendered.append(block)
        total_chars += len(block)
    return "\n".join(rendered).strip()


def query_filing_corpus(ticker: str, query_text: str, *, top_k: int = 5, include_10k: bool = True, ten_q_limit: int = 2) -> FilingContextBundle:
    """
    Search the filing corpus for a specific user query using semantic embeddings.
    Used by the Chatbot RAG flow.
    """
    ticker = ticker.upper().strip()
    corpus = build_filing_corpus(ticker, include_10k=include_10k, ten_q_limit=ten_q_limit)

    if not corpus["chunks"]:
        return FilingContextBundle(
            ticker=ticker,
            profile_name="chat_query",
            corpus_hash=corpus["corpus_hash"],
            sources=corpus["sources"],
            selected_chunks=[],
            rendered_text="",
            retrieval_summary={
                "strategy": "empty",
                "selected_chunk_count": 0,
                "error": "No chunks available in corpus",
            },
        )

    conn = _connect()
    try:
        # Embed the query
        try:
            query_embedding = _encode_texts([query_text], _EMBEDDING_MODEL)[0]
            used_embeddings = True
        except Exception as e:
            query_embedding = []
            used_embeddings = False
            return FilingContextBundle(
                ticker=ticker,
                profile_name="chat_query",
                corpus_hash=corpus["corpus_hash"],
                sources=corpus["sources"],
                selected_chunks=[],
                rendered_text="",
                retrieval_summary={
                    "strategy": "fallback_failed",
                    "selected_chunk_count": 0,
                    "error": f"Embeddings unavailable for RAG: {e}",
                },
            )

        # Score chunks
        scored_chunks: list[FilingChunk] = []
        for chunk in corpus["chunks"]:
            chunk_embedding = _load_cached_chunk_embedding(conn, chunk.chunk_hash, _EMBEDDING_MODEL)
            if not chunk_embedding:
                try:
                    chunk_embedding = _get_or_create_chunk_embedding(conn, chunk.chunk_hash, chunk.text, _EMBEDDING_MODEL)
                except Exception:
                    continue

            sim = _cosine_similarity(query_embedding, chunk_embedding)
            score = _normalise_similarity(sim)
            chunk.score = score
            scored_chunks.append(chunk)

        scored_chunks.sort(key=lambda c: c.score or 0.0, reverse=True)
        selected_chunks = scored_chunks[:top_k]

        bundle = FilingContextBundle(
            ticker=ticker,
            profile_name="chat_query",
            corpus_hash=corpus["corpus_hash"],
            sources=corpus["sources"],
            selected_chunks=selected_chunks,
            rendered_text="", # Built below
            retrieval_summary={
                "strategy": "semantic_search",
                "used_embeddings": used_embeddings,
                "selected_chunk_count": len(selected_chunks),
                "top_k_requested": top_k,
            },
        )
        bundle.rendered_text = render_filing_context(bundle, max_chars=100_000)
        return bundle
    finally:
        conn.close()


def get_agent_filing_context(
    ticker: str,
    *,
    profile_name: str,
    include_10k: bool = True,
    ten_q_limit: int = 2,
    use_cache: bool = True,
) -> FilingContextBundle:
    ticker = ticker.upper().strip()
    if profile_name not in _PROFILE_CONFIGS:
        raise ValueError(f"Unknown filing retrieval profile: {profile_name}")

    corpus = build_filing_corpus(ticker, include_10k=include_10k, ten_q_limit=ten_q_limit)
    model_name = _EMBEDDING_MODEL
    conn = _connect()
    try:
        if use_cache:
            cached = _load_cached_context(conn, ticker, profile_name, corpus["corpus_hash"], model_name)
            if cached is not None:
                return cached

        config = _PROFILE_CONFIGS[profile_name]
        priorities: list[str] = config["priorities"]
        section_coverage_counts = _section_count_map(corpus.get("section_coverage", {}))
        corpus_section_keys = set(section_coverage_counts)
        candidate_chunks = [
            chunk for chunk in corpus["chunks"] if chunk.section_key in priorities or chunk.section_key.startswith("note_")
        ]
        if not candidate_chunks:
            candidate_chunks = list(corpus["chunks"])
        candidate_section_keys = {chunk.section_key for chunk in candidate_chunks}

        used_embeddings = False
        fallback_mode = False
        query_embeddings: list[list[float]] = []
        try:
            query_embeddings = _encode_texts(config["queries"], model_name)
            used_embeddings = True
        except Exception:
            fallback_mode = True
            query_embeddings = []

        scored_chunks: list[FilingChunk] = []
        for chunk in candidate_chunks:
            section_score = _section_priority_score(chunk.section_key, priorities)
            semantic_score = 0.0
            if query_embeddings:
                try:
                    chunk_embedding = _get_or_create_chunk_embedding(conn, chunk.chunk_hash, chunk.text, model_name)
                    semantic_score = max(
                        _normalise_similarity(_cosine_similarity(chunk_embedding, query_embedding))
                        for query_embedding in query_embeddings
                    )
                except Exception:
                    fallback_mode = True
                    semantic_score = 0.0
            final_score = 0.60 * semantic_score + 0.40 * section_score
            scored_chunks.append(
                FilingChunk(
                    form_type=chunk.form_type,
                    accession_no=chunk.accession_no,
                    filing_date=chunk.filing_date,
                    section_key=chunk.section_key,
                    chunk_index=chunk.chunk_index,
                    text=chunk.text,
                    chunk_hash=chunk.chunk_hash,
                    score=final_score,
                )
            )

        scored_chunks.sort(key=lambda item: (item.score or 0.0), reverse=True)
        selected_chunks = scored_chunks[:_MAX_SELECTED_CHUNKS]
        selected_section_keys = {chunk.section_key for chunk in selected_chunks}
        excluded_section_keys = sorted(corpus_section_keys - candidate_section_keys)
        skipped_sections = sorted((candidate_section_keys - selected_section_keys) | set(excluded_section_keys))
        bundle = FilingContextBundle(
            ticker=ticker,
            profile_name=profile_name,
            corpus_hash=corpus["corpus_hash"],
            sources=corpus["sources"],
            selected_chunks=selected_chunks,
            rendered_text="",
            retrieval_summary={
                "profile_name": profile_name,
                "query_version": _QUERY_VERSION,
                "embedding_model": model_name,
                "used_embeddings": used_embeddings,
                "fallback_mode": fallback_mode,
                "corpus_hash": corpus["corpus_hash"],
                "selected_chunk_count": len(selected_chunks),
                "candidate_chunk_count": len(candidate_chunks),
                "corpus_chunk_count": len(corpus.get("chunks", [])),
                "section_coverage": corpus.get("section_coverage", {}),
                "statement_presence": corpus.get("statement_presence", {}),
                "eligible_section_keys": sorted(candidate_section_keys),
                "excluded_section_keys": excluded_section_keys,
                "selected_section_keys": [chunk.section_key for chunk in selected_chunks],
                "selected_accessions": [chunk.accession_no for chunk in selected_chunks],
                "skipped_sections": skipped_sections,
            },
        )
        bundle.rendered_text = render_filing_context(bundle, max_chars=30_000)
        _store_context_cache(conn, bundle, model_name)
        return bundle
    finally:
        conn.close()


def build_filing_update_context(filings_summary: Any, earnings_summary: Any) -> str:
    parts: list[str] = []
    filings_notes = getattr(filings_summary, "notes_watch_items", []) or []
    filings_updates = getattr(filings_summary, "recent_quarter_updates", []) or []
    earnings_notes = getattr(earnings_summary, "notes_watch_items", []) or []
    earnings_updates = getattr(earnings_summary, "quarterly_disclosure_changes", []) or []

    if filings_notes:
        parts.append("Filing note watch items: " + "; ".join(filings_notes[:3]))
    if filings_updates:
        parts.append("Recent quarter updates: " + "; ".join(filings_updates[:3]))
    if earnings_notes:
        parts.append("Earnings note watch items: " + "; ".join(earnings_notes[:3]))
    if earnings_updates:
        parts.append("Quarterly disclosure changes: " + "; ".join(earnings_updates[:3]))
    return "\n".join(parts)
