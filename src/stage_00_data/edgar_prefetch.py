from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
import sqlite3
from typing import Iterable

from config import EDGAR_CACHE_CLEAN_DIR, EDGAR_PARSER_VERSION
from db.loader import upsert_edgar_filing_cache
from db.schema import create_tables, get_connection
from src.stage_00_data import edgar_client
from src.utils import coerce_ticker, utc_now_iso


DEFAULT_FORMS = ("10-K", "10-Q", "8-K")


@dataclass(frozen=True)
class FilingPrefetchRow:
    form_type: str
    accession_no: str
    filing_date: str | None
    cached_chars: int
    cache_status: str


@dataclass(frozen=True)
class FilingPrefetchResult:
    ticker: str
    rows: list[FilingPrefetchRow]
    errors: list[str]

    @property
    def cached_count(self) -> int:
        return sum(1 for row in self.rows if row.cached_chars > 0)


def normalise_forms(forms: Iterable[str]) -> list[str]:
    normalised: list[str] = []
    seen: set[str] = set()
    for value in forms:
        form = value.strip().upper()
        if not form or form in seen:
            continue
        normalised.append(form)
        seen.add(form)
    return normalised or list(DEFAULT_FORMS)


def summarise_cached_filings(
    ticker: str,
    *,
    forms: Iterable[str] = DEFAULT_FORMS,
    limit: int = 4,
) -> FilingPrefetchResult:
    ticker = coerce_ticker(ticker)
    form_list = normalise_forms(forms)
    _ensure_tables()
    with get_connection() as conn:
        conn.row_factory = sqlite3.Row
        rows: list[FilingPrefetchRow] = []
        for form in form_list:
            cached_rows = conn.execute(
                """
                SELECT form_type, accession_no, filing_date, clean_path, raw_path
                FROM edgar_filing_cache
                WHERE ticker = ? AND form_type = ?
                ORDER BY COALESCE(filing_date, '') DESC, fetched_at DESC
                LIMIT ?
                """,
                [ticker, form, int(limit)],
            ).fetchall()
            for row in cached_rows:
                cached_chars = _cached_char_count(row["clean_path"]) or _cached_char_count(row["raw_path"])
                rows.append(
                    FilingPrefetchRow(
                        form_type=row["form_type"],
                        accession_no=row["accession_no"],
                        filing_date=row["filing_date"],
                        cached_chars=cached_chars,
                        cache_status="hit" if cached_chars > 0 else "missing",
                    )
                )
    return FilingPrefetchResult(ticker=ticker, rows=rows, errors=[])


def prefetch_filings(
    ticker: str,
    *,
    forms: Iterable[str] = DEFAULT_FORMS,
    limit: int = 4,
    summary_only: bool = False,
) -> FilingPrefetchResult:
    ticker = coerce_ticker(ticker)
    form_list = normalise_forms(forms)
    if summary_only:
        return summarise_cached_filings(ticker, forms=form_list, limit=limit)

    _ensure_tables()
    rows: list[FilingPrefetchRow] = []
    errors: list[str] = []
    try:
        cik = edgar_client.get_cik(ticker)
    except Exception as exc:
        return FilingPrefetchResult(ticker=ticker, rows=[], errors=[f"CIK lookup failed for {ticker}: {exc}"])

    with get_connection() as conn:
        conn.row_factory = sqlite3.Row
        for form in form_list:
            try:
                metadata_rows = edgar_client.get_recent_filing_metadata(ticker, form, limit=limit)
            except Exception as exc:
                errors.append(f"{form}: filing metadata fetch failed: {exc}")
                continue
            if not metadata_rows:
                errors.append(f"{form}: no filings returned")
                continue

            for metadata in metadata_rows:
                row = _prefetch_one(conn, ticker=ticker, cik=cik, form_type=form, metadata=metadata)
                rows.append(row)
                if row.cached_chars <= 0:
                    errors.append(f"{form} {row.accession_no}: text fetch returned no content")

    return FilingPrefetchResult(ticker=ticker, rows=rows, errors=errors)


def _prefetch_one(
    conn: sqlite3.Connection,
    *,
    ticker: str,
    cik: str,
    form_type: str,
    metadata: dict,
) -> FilingPrefetchRow:
    accession_no = str(metadata.get("accession_no") or "").strip()
    filing_date = metadata.get("filing_date")
    doc_name = str(metadata.get("primary_doc") or accession_no).strip() or accession_no
    cached = _load_cached_row(conn, ticker, accession_no, doc_name)
    if cached is not None:
        cached_chars = _cached_char_count(cached["clean_path"]) or _cached_char_count(cached["raw_path"])
        if cached_chars > 0:
            return FilingPrefetchRow(form_type=form_type, accession_no=accession_no, filing_date=filing_date, cached_chars=cached_chars, cache_status="hit")

    text = edgar_client.get_filing_text_by_accession(ticker, accession_no)
    if not text:
        return FilingPrefetchRow(form_type=form_type, accession_no=accession_no, filing_date=filing_date, cached_chars=0, cache_status="miss")

    clean_path = _write_clean_text(ticker, form_type, accession_no, doc_name, text)
    text_hash = _hash_text(text)
    now = utc_now_iso()
    upsert_edgar_filing_cache(
        conn,
        {
            "ticker": ticker,
            "cik": str(cik).zfill(10),
            "form_type": form_type,
            "accession_no": accession_no,
            "filing_date": str(filing_date) if filing_date is not None else None,
            "doc_name": doc_name,
            "source_url": _source_url(cik, accession_no, doc_name),
            "raw_path": None,
            "clean_path": str(clean_path),
            "raw_text_hash": text_hash,
            "clean_text_hash": text_hash,
            "parser_version": EDGAR_PARSER_VERSION,
            "fetched_at": now,
            "cleaned_at": now,
        },
    )
    return FilingPrefetchRow(form_type=form_type, accession_no=accession_no, filing_date=filing_date, cached_chars=len(text), cache_status="miss")


def _ensure_tables() -> None:
    with get_connection() as conn:
        create_tables(conn)


def _load_cached_row(conn: sqlite3.Connection, ticker: str, accession_no: str, doc_name: str) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT clean_path, raw_path
        FROM edgar_filing_cache
        WHERE ticker = ? AND accession_no = ? AND doc_name = ?
        LIMIT 1
        """,
        [ticker, accession_no, doc_name],
    ).fetchone()


def _cached_char_count(path_value: str | None) -> int:
    if not path_value:
        return 0
    path = Path(path_value)
    if not path.exists():
        return 0
    return len(path.read_text(encoding="utf-8", errors="ignore"))


def _write_clean_text(ticker: str, form_type: str, accession_no: str, doc_name: str, text: str) -> Path:
    target_dir = EDGAR_CACHE_CLEAN_DIR / ticker / form_type.replace("/", "-")
    target_dir.mkdir(parents=True, exist_ok=True)
    safe_doc = "".join(char if char.isalnum() or char in {".", "-", "_"} else "_" for char in doc_name)
    path = target_dir / f"{accession_no}_{safe_doc}.txt"
    path.write_text(text, encoding="utf-8")
    return path


def _source_url(cik: str, accession_no: str, doc_name: str) -> str:
    cik_path = str(int(str(cik)))
    accession_path = accession_no.replace("-", "")
    return f"https://www.sec.gov/Archives/edgar/data/{cik_path}/{accession_path}/{doc_name}"


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
