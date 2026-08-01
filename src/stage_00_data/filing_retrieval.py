from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import math
import os
import re
import sqlite3
from typing import Any

from config import EDGAR_PARSER_VERSION, PEER_SIMILARITY_MODEL
from db.loader import (
    upsert_edgar_chunk_cache,
    upsert_edgar_chunk_embedding,
    upsert_edgar_section_cache,
    upsert_filing_context_cache,
)
from db.schema import create_tables, get_connection
from src.stage_00_data import edgar_client
from src.utils import utc_now_iso

SECTION_PARSER_VERSION = f"{EDGAR_PARSER_VERSION}_sections_v6"
_CHUNK_VERSION = "v2"
_QUERY_VERSION = "v9"
_EMBEDDING_MODEL = PEER_SIMILARITY_MODEL
_CHUNK_SIZE = 1400
_CHUNK_OVERLAP = 200
_MAX_SELECTED_CHUNKS = 12
_MODEL_CACHE: dict[str, object] = {}

_PROFILE_CONFIGS: dict[str, dict[str, Any]] = {
    "filings": {
        "priorities": [
            "business",
            "mda",
            "mda_q",
            "risk_factors",
            "risk_factors_q",
            "notes_to_financials",
            "notes_to_financials_q",
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
            "note_revenue",
            "note_restructuring",
            "note_impairment",
            "note_acquisitions",
            "note_sbc",
            "note_contingencies",
            "note_fair_value",
            "notes_to_financials",
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
            "notes_to_financials_q",
            "mda",
            "mda_q",
        ],
        "queries": [
            "unusual nonrecurring recurring accounting policy estimate change restatement correction",
            "economic substance operating financing obligation off balance sheet commitment guarantee related party",
            "capitalization expensing useful life impairment reserve contingent deferred noncash",
            "valuation adjustment normalized earnings free cash flow invested capital enterprise equity bridge",
        ],
    },
    "industry": {
        "priorities": [
            "business",
            "mda",
            "mda_q",
            "risk_factors",
            "risk_factors_q",
            "notes_to_financials",
            "notes_to_financials_q",
        ],
        "queries": [
            "industry demand growth drivers market trends competitive position",
            "pricing power competition customer spending macro headwinds tailwinds",
            "segment demand backlog bookings renewal cloud artificial intelligence services",
        ],
    },
    "risk": {
        "priorities": [
            "risk_factors",
            "risk_factors_q",
            "mda",
            "mda_q",
            "note_debt",
            "note_contingencies",
            "notes_to_financials",
        ],
        "queries": [
            "execution risk transformation integration customer demand cyclicality",
            "debt liquidity covenant interest rate refinancing balance sheet risk",
            "litigation regulatory cybersecurity competition operational disruption",
        ],
    },
}

_NOTE_TOPIC_PATTERNS: list[tuple[str, str]] = [
    ("note_revenue", r"revenue|contract|customer"),
    ("note_segments", r"segment|geographic"),
    ("note_leases", r"lease|right-of-use|right of use"),
    ("note_restructuring", r"restructuring|reorganization|transformation"),
    ("note_impairment", r"impairment|write-down|write down|goodwill|intangible assets"),
    ("note_acquisitions", r"acquisition|business combination|purchase accounting"),
    ("note_contingencies", r"contingenc|litigation|legal proceeding|commitment"),
    ("note_pension", r"pension|retirement|postretirement"),
    ("note_taxes", r"income tax|taxation|taxes"),
    ("note_fair_value", r"fair value|level 1|level 2|level 3"),
    ("note_debt", r"debt|borrowings|credit facility|notes payable"),
    ("note_sbc", r"stock[- ]based compensation|share[- ]based compensation|employee stock purchase"),
]

_NOTE_BODY_TOPIC_HEADINGS: tuple[tuple[str, str], ...] = (
    ("note_revenue", r"^(?:revenue recognition|unearned revenue)$"),
    ("note_segments", r"^segment information(?: and geographic data)?$"),
    ("note_leases", r"^(?:leases?|lease commitments)$"),
    ("note_restructuring", r"^restructuring$"),
    ("note_impairment", r"^(?:goodwill|impairment|intangible assets)$"),
    ("note_acquisitions", r"^(?:acquisitions?|business combinations?)$"),
    ("note_contingencies", r"^(?:contingencies|legal and other contingencies|commitments)$"),
    ("note_pension", r"^(?:pension|pensions|postretirement)$"),
    ("note_taxes", r"^(?:income taxes?|taxes)$"),
    ("note_fair_value", r"^(?:fair value measurements?|fair value)$"),
    ("note_debt", r"^(?:debt|borrowings|long-term debt)$"),
    ("note_sbc", r"^(?:stock[- ]based compensation|share[- ]based compensation|employee stock purchase)$"),
)


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
    conn = get_connection()
    create_tables(conn)
    return conn





def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _normalize_heading_text(text: str) -> str:
    normalized = (
        text.replace("\u2019", "'")
        .replace("\u2018", "'")
        .replace("\u2013", "-")
        .replace("\u2014", "-")
        .replace("\u2012", "-")
    )
    # Some SEC HTML-to-text tables split words at column boundaries. Keep the
    # repair deliberately narrow so ordinary prose whitespace is untouched.
    def _repair_financial(match: re.Match[str]) -> str:
        source = match.group(0)
        if source.isupper():
            return "FINANCIAL"
        if source.islower():
            return "financial"
        return "Financial"

    return re.sub(r"(?i)\bfinanci\s+al\b", _repair_financial, normalized)


def _extract_section(
    text: str,
    start_patterns: list[str],
    end_patterns: list[str],
    *,
    prefer_latest: bool = False,
) -> str:
    haystack = _normalize_heading_text(text)
    start_matches: list[re.Match[str]] = []
    for pattern in start_patterns:
        start_matches.extend(re.finditer(pattern, haystack, flags=re.IGNORECASE | re.MULTILINE))
    start_matches.sort(key=lambda match: match.start())
    if not start_matches:
        return ""

    candidates: list[tuple[int, int, str]] = []
    for start_match in start_matches:
        start = start_match.start()
        end = len(haystack)
        for pattern in end_patterns:
            match = re.search(pattern, haystack[start_match.end() :], flags=re.IGNORECASE | re.MULTILINE)
            if match:
                candidate = start_match.end() + match.start()
                if candidate > start and candidate < end:
                    end = candidate
        section_text = haystack[start:end].strip()
        normalized = " ".join(section_text.split())
        if len(normalized) < 40:
            continue
        candidates.append((len(normalized), start, section_text))

    if not candidates:
        return ""
    # SEC filings often contain a table of contents that matches Item headings.
    # The substantive body is usually the longest candidate span between headings.
    # Notes are a special case: a TOC reference can span the entire filing, so
    # callers can prefer the latest body heading instead.
    if prefer_latest:
        candidates.sort(key=lambda item: (item[1], item[0]), reverse=True)
    else:
        candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return candidates[0][2]


def _item_heading_pattern(item: str, label: str | None = None, *, part: str | None = None) -> str:
    item_text = re.escape(item)
    part_prefix = ""
    if part:
        part_text = re.escape(part)
        part_prefix = rf"(?:^|\n)\s*part\s+{part_text}\.?\s*(?:[-—]\s*)?(?:\n\s*){{1,4}}"
    else:
        part_prefix = r"(^|\n)\s*"

    if label:
        label_words = r"\s+".join(re.escape(word) for word in label.split())
        return rf"{part_prefix}item\s+{item_text}\.?\s*(?:\n\s*){{0,4}}(?:{label_words})\b"
    return rf"{part_prefix}item\s+{item_text}\.?\s*(?:\n\s*){{1,4}}"


def _extract_numbered_note_sections(notes_source: str) -> tuple[str, list[tuple[str, str, str]]]:
    matches = list(
        re.finditer(
            r"(?im)(?:^|\n)\s*(?P<heading>note\s+(?P<number>\d+)(?P<suffix>[a-z])?(?:[.:\-\s]+)[^\n]{0,140})",
            notes_source,
        )
    )
    if not matches:
        return "", []

    notes_end = len(notes_source)
    tail = notes_source[matches[-1].end() :]
    for pattern in (
        r"(?im)^\s*report\s+of\s+independent\s+(?:regist\s*ered\s+public\s+accounting\s+firm|auditors?)\b",
        _item_heading_pattern("1", part="i"),
        _item_heading_pattern("2", part="i"),
        _item_heading_pattern("9", part="ii"),
        r"(?im)^\s*item\s+9\.?\b",
        r"(?im)^\s*signatures?\b",
    ):
        tail_match = re.search(pattern, tail, flags=re.IGNORECASE | re.MULTILINE)
        if tail_match:
            notes_end = min(notes_end, matches[-1].end() + tail_match.start())

    numbered_sections: list[tuple[str, str, str]] = []
    for index, match in enumerate(matches):
        start = match.start("heading")
        end = matches[index + 1].start("heading") if index + 1 < len(matches) else notes_end
        if end <= start:
            continue
        number = int(match.group("number"))
        suffix = (match.group("suffix") or "").lower()
        heading = " ".join(match.group("heading").split())
        block = notes_source[start:end].strip()
        numbered_sections.append((f"note_{number:03d}{suffix}", heading, block))

    if not numbered_sections:
        return "", []
    notes_start = matches[0].start("heading")
    heading_matches = list(
        re.finditer(
            r"(?im)^\s*notes\s+to\s+(?:(?:condensed|consolidated)\s+)*financial\s+statements\b[^\n]*",
            notes_source[:notes_start],
        )
    )
    if heading_matches:
        notes_start = heading_matches[-1].start()
    notes_text = notes_source[notes_start:notes_end].strip()
    return notes_text, numbered_sections


def _extract_note_subsections(form_type: str, notes_text: str) -> list[tuple[str, str]]:
    if not notes_text:
        return []
    numbered_matches = list(
        re.finditer(
            r"(?im)(?:^|\n)\s*(note\s+\d+[a-z]?(?:[\.:\-\s]+)[^\n]{0,140})",
            notes_text,
        )
    )

    def _body_topic_key(heading: str) -> str | None:
        normalized = " ".join(heading.split()).strip()
        if not normalized or len(normalized) > 100:
            return None
        for section_key, pattern in _NOTE_BODY_TOPIC_HEADINGS:
            if re.fullmatch(pattern, normalized, flags=re.IGNORECASE):
                return section_key
        return None

    body_matches: list[tuple[re.Match[str], str]] = []
    for match in re.finditer(r"(?im)^(?P<heading>[^\n]{2,100})$", notes_text):
        heading = match.group("heading").strip()
        if heading.lower().startswith("note "):
            continue
        section_key = _body_topic_key(heading)
        if section_key:
            body_matches.append((match, section_key))

    # Topic headings supplement numbered notes, which is necessary for filings
    # whose text extraction drops repeated "NOTE 2 - ..." labels but keeps
    # headings such as "Leases" or "Income Taxes".
    boundaries: list[tuple[int, str, str | None]] = [
        (match.start(1), match.group(1).strip(), None)
        for match in numbered_matches
    ]
    boundaries.extend(
        (match.start("heading"), match.group("heading").strip(), section_key)
        for match, section_key in body_matches
    )
    boundaries.sort(key=lambda item: item[0])
    deduped_boundaries: list[tuple[int, str, str | None]] = []
    seen_starts: set[int] = set()
    for boundary in boundaries:
        if boundary[0] in seen_starts:
            continue
        deduped_boundaries.append(boundary)
        seen_starts.add(boundary[0])

    candidates_by_key: dict[str, list[tuple[int, int, str, str]]] = {}
    for index, (start, heading, explicit_key) in enumerate(deduped_boundaries):
        end = deduped_boundaries[index + 1][0] if index + 1 < len(deduped_boundaries) else len(notes_text)
        block = notes_text[start:end].strip()
        if len(block) < 80:
            continue
        section_key = explicit_key
        if section_key is None:
            for candidate_key, pattern in _NOTE_TOPIC_PATTERNS:
                if re.search(pattern, heading, flags=re.IGNORECASE):
                    section_key = candidate_key
                    break
        if section_key is None:
            continue
        candidates_by_key.setdefault(section_key, []).append((len(block), start, heading, block))

    selected: list[tuple[int, str, str]] = []
    for section_key, candidates in candidates_by_key.items():
        # A topic can appear in both a critical-estimates discussion and its
        # dedicated note. Prefer the most complete occurrence.
        _, start, heading, block = max(candidates, key=lambda item: (item[0], -item[1]))
        selected.append((start, section_key, f"{heading}\n{block}"))
    selected.sort(key=lambda item: item[0])
    return [(section_key, block) for _, section_key, block in selected]


def _extract_sections_for_filing(form_type: str, text: str) -> list[tuple[str, str, str]]:
    text = _normalize_heading_text(text)
    sections: list[tuple[str, str, str]] = []

    if form_type == "10-K":
        definitions = [
            (
                "business",
                "Business",
                [
                    r"(^|\n)\s*item\s+1\.?\s+business\b",
                    _item_heading_pattern("1", part="i"),
                ],
                [r"(^|\n)\s*item\s+1a\.?\s+risk\s+factors\b", r"(^|\n)\s*item\s+2\.?\b"],
            ),
            (
                "risk_factors",
                "Risk Factors",
                [
                    r"(^|\n)\s*item\s+1a\.?\s+risk\s+factors\b",
                    _item_heading_pattern("1A"),
                ],
                [r"(^|\n)\s*item\s+1b\.?\b", r"(^|\n)\s*item\s+2\.?\b", r"(^|\n)\s*item\s+7\.?\b"],
            ),
            (
                "mda",
                "MD&A",
                [
                    r"(^|\n)\s*item\s+7\.?\s+management'?s\s+discussion\s+and\s+analysis\b",
                    _item_heading_pattern("7", "management s discussion and analysis", part="ii"),
                    _item_heading_pattern("7", part="ii"),
                    r"(^|\n)\s*management'?s\s+discussion\s+and\s+analysis\b",
                ],
                [r"(^|\n)\s*item\s+7a\.?\b", r"(^|\n)\s*item\s+8\.?\s+financial\s+statements\b"],
            ),
            (
                "financial_statements",
                "Financial Statements",
                [
                    r"(^|\n)\s*item\s+8\.?\s+financial\s+statements.*\b",
                    _item_heading_pattern("8", "financial statements", part="ii"),
                    _item_heading_pattern("8", part="ii"),
                ],
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
                [
                    r"(^|\n)\s*part\s+i\.?\s*-?\s*item\s+1\.?\s+financial\s+statements\b",
                    _item_heading_pattern("1", "financial statements", part="i"),
                    _item_heading_pattern("1", part="i"),
                ],
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
                [
                    r"(^|\n)\s*part\s+i\.?\s*-?\s*item\s+2\.?\s+management'?s\s+discussion\s+and\s+analysis\b",
                    _item_heading_pattern("2", "management s discussion and analysis", part="i"),
                    _item_heading_pattern("2", part="i"),
                ],
                [r"(^|\n)\s*part\s+i\s*-?\s*item\s+3\.?\b", r"(^|\n)\s*part\s+ii\s*-?\s*item\s+1a\.?\b"],
            ),
            (
                "risk_factors_q",
                "Quarterly Risk Factors",
                [
                    r"(^|\n)\s*part\s+ii\.?\s*-?\s*item\s+1a\.?\s+risk\s+factors\b",
                    _item_heading_pattern("1A", "risk factors", part="ii"),
                    _item_heading_pattern("1A", part="ii"),
                ],
                [r"(^|\n)\s*part\s+ii\s*-?\s*item\s+2\.?\b", r"(^|\n)\s*signatures\b"],
            ),
        ]

    for section_key, label, start_patterns, end_patterns in definitions:
        section_text = _extract_section(
            text,
            start_patterns,
            end_patterns,
            prefer_latest=section_key in {"notes_to_financials", "notes_to_financials_q"},
        )
        if section_text:
            sections.append((section_key, label, section_text))

    statement_key = "financial_statements" if form_type == "10-K" else "financial_statements_q"
    broad_notes_key = "notes_to_financials" if form_type == "10-K" else "notes_to_financials_q"
    statement_text = next((value for key, _, value in sections if key == statement_key), "")
    numbered_notes_text, numbered_notes = _extract_numbered_note_sections(statement_text)
    if numbered_notes:
        sections = [section for section in sections if section[0] != broad_notes_key]
        sections.append((broad_notes_key, "Notes to Financial Statements", numbered_notes_text))
        sections.extend(numbered_notes)

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


def _skip_embedding_fetch() -> bool:
    return os.getenv("ALPHA_POD_EDGAR_CACHE_ONLY", "0").strip().lower() in {"1", "true", "yes"}


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
        [ticker.upper(), accession_no, doc_name, SECTION_PARSER_VERSION],
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
        [SECTION_PARSER_VERSION, ticker.upper(), accession_no, doc_name, _CHUNK_VERSION],
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
            "created_at": utc_now_iso(),
        },
    )
    return embedding


def _section_priority_score(section_key: str, priorities: list[str]) -> float:
    if section_key in priorities:
        index = priorities.index(section_key)
        return max(0.1, 1.0 - (index / max(1, len(priorities))))
    return 0.1


def _lexical_query_score(text: str, queries: list[str]) -> float:
    stopwords = {
        "and",
        "are",
        "for",
        "from",
        "into",
        "that",
        "the",
        "this",
        "use",
        "was",
        "were",
        "with",
    }
    text_terms = {
        term
        for term in re.findall(r"[a-z][a-z0-9]{2,}", text.lower())
        if term not in stopwords
    }
    scores: list[float] = []
    for query in queries:
        query_terms = {
            term
            for term in re.findall(r"[a-z][a-z0-9]{2,}", query.lower())
            if term not in stopwords
        }
        if query_terms:
            scores.append(len(text_terms & query_terms) / len(query_terms))
    return max(scores, default=0.0)


def _select_profile_chunks(
    scored_chunks: list[FilingChunk],
    *,
    profile_name: str,
    priorities: list[str],
) -> list[FilingChunk]:
    """Select ranked evidence without turning profile hints into eligibility gates."""

    ranked_chunks = sorted(scored_chunks, key=lambda item: item.score or 0.0, reverse=True)
    if len(priorities) < 2:
        return ranked_chunks[:_MAX_SELECTED_CHUNKS]

    selected: list[FilingChunk] = []
    selected_keys: set[tuple[str, str, int]] = set()
    section_counts: dict[str, int] = {}

    def _chunk_key(chunk: FilingChunk) -> tuple[str, str, int]:
        return (chunk.accession_no, chunk.section_key, int(chunk.chunk_index))

    def _append(candidate: FilingChunk) -> None:
        key = _chunk_key(candidate)
        if key not in selected_keys:
            selected.append(candidate)
            selected_keys.add(key)
            section_counts[candidate.section_key] = section_counts.get(candidate.section_key, 0) + 1

    # Use at most one third of the budget to anchor known profile sections. The
    # remaining budget must stay open to raw numbered notes and ranked surprises.
    anchor_budget = max(1, _MAX_SELECTED_CHUNKS // 3)
    for section_key in priorities:
        candidate = next((chunk for chunk in ranked_chunks if chunk.section_key == section_key), None)
        if candidate is not None:
            _append(candidate)
        if len(selected) >= anchor_budget:
            break

    raw_note_sections: set[str] = set()
    for candidate in ranked_chunks:
        if not re.fullmatch(r"note_\d{3}[a-z]?", candidate.section_key):
            continue
        if candidate.section_key in raw_note_sections:
            continue
        _append(candidate)
        raw_note_sections.add(candidate.section_key)
        if len(raw_note_sections) >= anchor_budget or len(selected) >= _MAX_SELECTED_CHUNKS:
            break

    for candidate in ranked_chunks:
        if section_counts.get(candidate.section_key, 0) >= 2:
            continue
        _append(candidate)
        if len(selected) >= _MAX_SELECTED_CHUNKS:
            break

    # Small synthetic corpora may not have enough diverse sections. In that case
    # fill the remainder by score rather than returning an unnecessarily thin packet.
    for candidate in ranked_chunks:
        _append(candidate)
        if len(selected) >= _MAX_SELECTED_CHUNKS:
            break
    return selected


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
            "created_at": utc_now_iso(),
        },
    )


def _load_filing_payloads(ticker: str, *, include_10k: bool, ten_q_limit: int | None) -> list[dict[str, Any]]:
    cik = edgar_client.get_cik(ticker)
    filings: list[dict[str, Any]] = []

    if include_10k:
        for meta in edgar_client.get_recent_filing_metadata(ticker, "10-K", limit=None):
            text = edgar_client.get_filing_text_by_accession(ticker, meta["accession_no"], max_chars=None)
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
        text = edgar_client.get_filing_text_by_accession(ticker, meta["accession_no"], max_chars=None)
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
                "parser_version": SECTION_PARSER_VERSION,
                "extracted_at": utc_now_iso(),
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
                    "created_at": utc_now_iso(),
                }
            )
    upsert_edgar_chunk_cache(conn, chunk_rows)
    return sections, chunks


def build_filing_corpus(
    ticker: str,
    *,
    include_10k: bool = True,
    ten_q_limit: int | None = 2,
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


def build_accounting_section_inventory(
    sections: list[FilingSection],
    *,
    preview_chars: int = 240,
) -> list[dict[str, Any]]:
    """Build the complete note map used by the accounting discovery agent."""

    inventory: list[dict[str, Any]] = []
    eligible = [
        section
        for section in sections
        if re.fullmatch(r"note_\d{3}[a-z]?", section.section_key)
        or (
            section.section_key.startswith("note_")
            and not section.section_key.startswith("notes_to_")
        )
    ]
    eligible.sort(key=lambda section: (section.accession_no, section.section_key))
    eligible.sort(key=lambda section: section.filing_date or "", reverse=True)

    for section in eligible:
        raw_note = bool(re.fullmatch(r"note_\d{3}[a-z]?", section.section_key))
        preview = " ".join(section.text.split())
        if preview_chars > 0 and len(preview) > preview_chars:
            preview = preview[:preview_chars].rstrip() + "…"
        inventory.append(
            {
                "section_id": f"{section.accession_no}::{section.section_key}",
                "form_type": section.form_type,
                "accession_no": section.accession_no,
                "filing_date": section.filing_date,
                "section_key": section.section_key,
                "heading": section.section_label,
                "preview": preview,
                "inventory_role": (
                    "raw_numbered_note" if raw_note else "semantic_alias"
                ),
            }
        )
    return inventory


def render_accounting_section_inventory(
    inventory: list[dict[str, Any]],
    *,
    max_chars: int | None = None,
) -> str:
    lines: list[str] = []
    used_chars = 0
    for item in inventory:
        line = (
            f"[{item.get('section_id')} | {item.get('form_type')} | "
            f"{item.get('filing_date') or 'unknown-date'} | "
            f"{item.get('inventory_role')}]\n"
            f"{item.get('heading') or item.get('section_key')}\n"
            f"Preview: {item.get('preview') or 'none'}\n"
        )
        if max_chars is not None and used_chars + len(line) > max_chars:
            break
        lines.append(line)
        used_chars += len(line)
    return "\n".join(lines).strip()


def get_accounting_section_inventory(
    ticker: str,
    *,
    include_10k: bool = True,
    ten_q_limit: int | None = None,
) -> list[dict[str, Any]]:
    corpus = build_filing_corpus(
        ticker,
        include_10k=include_10k,
        ten_q_limit=ten_q_limit,
    )
    return build_accounting_section_inventory(corpus["sections"])


# Filings whose notes to the financial statements form the accounting corpus. 8-Ks are
# cached as supplemental business/earnings sources and must never be counted as
# accounting-note coverage.
ACCOUNTING_CORPUS_FORM_TYPES = ("10-K", "10-Q")


def summarize_accounting_corpus_coverage(
    *,
    ticker: str,
    filings: list[Any],
    parsed_counts: dict[tuple[str, str], dict[str, int]],
    parser_version: str | None = None,
) -> dict[str, Any]:
    """Pure coverage summary over cached filings and current-parser section counts.

    ``complete`` requires two separate things, because they fail separately:

    1. every cached 10-K/10-Q parsed under the current parser version, and
    2. every one of those filings produced at least one raw numbered note.

    Condition 2 exists because "parsed" is not "complete". IBM had four required
    filings present and parsed that yielded zero numbered notes between them, so a
    presence-only gate would have handed the discovery agent an empty inventory
    while reporting a complete corpus.
    """

    required = [
        row for row in filings
        if str(row["form_type"]) in ACCOUNTING_CORPUS_FORM_TYPES
    ]
    missing: list[dict[str, Any]] = []
    without_notes: list[dict[str, Any]] = []
    for row in required:
        key = (str(row["accession_no"]), str(row["doc_name"]))
        descriptor = {
            "form_type": str(row["form_type"]),
            "filing_date": row["filing_date"],
            "accession_no": key[0],
            "doc_name": key[1],
        }
        counts = parsed_counts.get(key)
        if counts is None:
            missing.append(descriptor)
        elif not counts.get("raw_notes"):
            without_notes.append({**descriptor, "sections": counts.get("sections", 0)})
    return {
        "ticker": ticker.upper().strip(),
        "parser_version": parser_version or SECTION_PARSER_VERSION,
        "cached_filing_count": len(filings),
        "required_filing_count": len(required),
        "parsed_filing_count": len(required) - len(missing),
        "missing_filings": missing,
        "filings_without_notes": without_notes,
        "complete": bool(required) and not missing and not without_notes,
    }


def get_accounting_corpus_coverage(
    ticker: str,
    *,
    conn: sqlite3.Connection | None = None,
    parser_version: str | None = None,
) -> dict[str, Any]:
    """Report cached filing inventory against current-parser accounting coverage.

    Historical parser rows stay in SQLite for lineage but must not inflate the
    current coverage count, so parsed filings are counted at
    ``SECTION_PARSER_VERSION`` only.

    Pass ``conn`` to read from a caller-owned connection (the manual inspector uses
    a read-only handle); a supplied connection is not closed here.
    """

    ticker = ticker.upper().strip()
    parser_version = parser_version or SECTION_PARSER_VERSION
    owned = conn is None
    conn = conn if conn is not None else _connect()
    try:
        filings = conn.execute(
            """
            SELECT form_type, filing_date, accession_no, doc_name
            FROM edgar_filing_cache
            WHERE ticker = ?
            ORDER BY filing_date DESC, accession_no DESC
            """,
            [ticker],
        ).fetchall()
        parsed = conn.execute(
            """
            SELECT accession_no, doc_name,
                   COUNT(*) AS sections,
                   SUM(CASE WHEN section_key GLOB 'note_[0-9][0-9][0-9]*' THEN 1 ELSE 0 END)
                       AS raw_notes
            FROM edgar_section_cache
            WHERE ticker = ? AND parser_version = ?
            GROUP BY accession_no, doc_name
            """,
            [ticker, parser_version],
        ).fetchall()
    finally:
        if owned:
            conn.close()

    parsed_counts = {
        (str(row["accession_no"]), str(row["doc_name"])): {
            "sections": int(row["sections"]),
            "raw_notes": int(row["raw_notes"] or 0),
        }
        for row in parsed
    }
    return summarize_accounting_corpus_coverage(
        ticker=ticker,
        filings=filings,
        parsed_counts=parsed_counts,
        parser_version=parser_version,
    )


def _raise_for_incomplete_coverage(coverage: dict[str, Any]) -> dict[str, Any]:
    """Fail closed with the specific reason: absent filings, or filings without notes."""

    if coverage["complete"]:
        return coverage
    reasons: list[str] = []
    if coverage["missing_filings"]:
        reasons.append(
            f"parsed {coverage['parsed_filing_count']}/"
            f"{coverage['required_filing_count']} required accounting filings"
        )
    if coverage["filings_without_notes"]:
        listed = ", ".join(
            f"{item['form_type']} {item['accession_no']} ({item['sections']} sections)"
            for item in coverage["filings_without_notes"]
        )
        reasons.append(f"no numbered notes extracted from {listed}")
    if not reasons:
        reasons.append("no cached 10-K or 10-Q filings")
    raise RuntimeError(
        f"Accounting corpus incomplete for {coverage['ticker']} at parser "
        f"{coverage['parser_version']}: "
        + "; ".join(reasons)
        + "; refusing to run classification judgment."
    )


def require_accounting_corpus_coverage(ticker: str) -> dict[str, Any]:
    """Fail closed unless every cached 10-K/10-Q parsed *and* yielded numbered notes."""

    return _raise_for_incomplete_coverage(get_accounting_corpus_coverage(ticker))


def get_discovery_filing_context(
    ticker: str,
    discovery_result: dict[str, Any],
    *,
    include_10k: bool = True,
    ten_q_limit: int | None = None,
    max_selected_chunks: int = 24,
    chunks_per_section: int = 2,
) -> FilingContextBundle:
    """Retrieve only the sections and terms requested by accounting discovery."""

    ticker = ticker.upper().strip()
    corpus = build_filing_corpus(
        ticker,
        include_10k=include_10k,
        ten_q_limit=ten_q_limit,
    )
    section_terms: dict[str, list[str]] = {}
    question_ids: list[str] = []
    for question in discovery_result.get("questions") or []:
        if not isinstance(question, dict):
            continue
        question_id = str(question.get("question_id") or "").strip()
        if question_id:
            question_ids.append(question_id)
        terms = [
            str(term).strip()
            for term in (question.get("search_terms") or [])
            if str(term).strip()
        ]
        for section_id in question.get("requested_section_ids") or []:
            section_id = str(section_id).strip()
            if not section_id:
                continue
            existing_terms = section_terms.setdefault(section_id, [])
            existing_terms.extend(term for term in terms if term not in existing_terms)

    chunks_by_section: dict[str, list[FilingChunk]] = {}
    for chunk in corpus["chunks"]:
        section_id = f"{chunk.accession_no}::{chunk.section_key}"
        if section_id in section_terms:
            chunks_by_section.setdefault(section_id, []).append(chunk)

    requested_section_ids = list(section_terms)
    unmatched_section_ids = [
        section_id
        for section_id in requested_section_ids
        if section_id not in chunks_by_section
    ]
    ranked_by_section: dict[str, list[FilingChunk]] = {}
    for section_id, chunks in chunks_by_section.items():
        terms = section_terms[section_id]
        queries = [" ".join(terms)] if terms else []
        ranked = [
            FilingChunk(
                form_type=chunk.form_type,
                accession_no=chunk.accession_no,
                filing_date=chunk.filing_date,
                section_key=chunk.section_key,
                chunk_index=chunk.chunk_index,
                text=chunk.text,
                chunk_hash=chunk.chunk_hash,
                score=_lexical_query_score(chunk.text, queries),
            )
            for chunk in chunks
        ]
        ranked.sort(key=lambda chunk: (-(chunk.score or 0.0), chunk.chunk_index))
        ranked_by_section[section_id] = ranked

    selected_chunks: list[FilingChunk] = []
    for round_index in range(max(1, chunks_per_section)):
        for section_id in requested_section_ids:
            ranked = ranked_by_section.get(section_id) or []
            if round_index < len(ranked):
                selected_chunks.append(ranked[round_index])
            if len(selected_chunks) >= max_selected_chunks:
                break
        if len(selected_chunks) >= max_selected_chunks:
            break

    requested_accessions = {
        section_id.split("::", 1)[0]
        for section_id in requested_section_ids
        if "::" in section_id
    }
    sources = [
        source
        for source in corpus["sources"]
        if source.get("accession_no") in requested_accessions
    ]
    bundle = FilingContextBundle(
        ticker=ticker,
        profile_name="accounting_discovery_focus",
        corpus_hash=corpus["corpus_hash"],
        sources=sources,
        selected_chunks=selected_chunks,
        rendered_text="",
        retrieval_summary={
            "profile_name": "accounting_discovery_focus",
            "query_version": _QUERY_VERSION,
            "corpus_hash": corpus["corpus_hash"],
            "question_ids": question_ids,
            "requested_section_ids": requested_section_ids,
            "matched_section_ids": sorted(chunks_by_section),
            "unmatched_section_ids": unmatched_section_ids,
            "selected_chunk_count": len(selected_chunks),
            "corpus_chunk_count": len(corpus.get("chunks", [])),
        },
    )
    bundle.rendered_text = render_filing_context(bundle, max_chars=40_000)
    return bundle


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
            if _skip_embedding_fetch():
                raise RuntimeError("embedding fetch disabled in EDGAR cache-only mode")
            query_embeddings = _encode_texts(config["queries"], model_name)
            used_embeddings = True
        except Exception:
            fallback_mode = True
            query_embeddings = []

        scored_chunks: list[FilingChunk] = []
        for chunk in candidate_chunks:
            section_score = _section_priority_score(chunk.section_key, priorities)
            lexical_score = _lexical_query_score(chunk.text, config["queries"])
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
            if query_embeddings:
                final_score = (
                    0.55 * semantic_score
                    + 0.25 * lexical_score
                    + 0.20 * section_score
                )
            else:
                final_score = 0.75 * lexical_score + 0.25 * section_score
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
        selected_chunks = _select_profile_chunks(
            scored_chunks,
            profile_name=profile_name,
            priorities=priorities,
        )
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
        if not fallback_mode:
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
