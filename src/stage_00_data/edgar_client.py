"""
SEC EDGAR REST API client (free, no API key required).
Rate-limited to 10 req/sec per SEC guidelines.
"""

import html
import hashlib
import json
import re
import sqlite3
import time
import requests
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from config import (
    DB_PATH,
    EDGAR_BASE_URL,
    EDGAR_CACHE_CLEAN_DIR,
    EDGAR_CACHE_RAW_DIR,
    EDGAR_HEADERS,
    EDGAR_PARSER_VERSION,
    EDGAR_RATE_LIMIT_DELAY,
)
from db.loader import upsert_edgar_filing_cache
from db.schema import create_tables

_ROOT_DIR = Path(__file__).resolve().parent.parent.parent
_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
_TICKERS_CACHE_PATH = _ROOT_DIR / "data" / "cache" / "sec_company_tickers.json"
_TICKERS_CACHE_TTL_SECONDS = 86_400  # 24 hours


def _connect_cache() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    create_tables(conn)
    return conn


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _safe_filename(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", value)


def _strip_html_tags(text: str) -> str:
    """Convert iXBRL / HTML filing markup into readable plain text."""
    cleaned = text or ""

    for pattern in (
        r"<script\b[^>]*>.*?</script>",
        r"<style\b[^>]*>.*?</style>",
        r"<ix:header\b[^>]*>.*?</ix:header>",
        r"<!--.*?-->",
    ):
        cleaned = re.sub(pattern, " ", cleaned, flags=re.IGNORECASE | re.DOTALL)

    for pattern, replacement in (
        (r"<\s*br\s*/?>", "\n"),
        (r"<\s*(p|div|li|tr|table|section|article|h[1-6])\b[^>]*>", "\n"),
        (r"<\s*/\s*(p|div|li|tr|table|section|article|h[1-6])\s*>", "\n"),
        (r"<\s*/\s*(td|th)\s*>", " "),
    ):
        cleaned = re.sub(pattern, replacement, cleaned, flags=re.IGNORECASE)

    cleaned = re.sub(r"<[^>]+>", " ", cleaned)
    cleaned = html.unescape(cleaned).replace("\xa0", " ")
    cleaned = re.sub(r"[ \t\r\f\v]+", " ", cleaned)
    cleaned = re.sub(r"\s*\n\s*", "\n", cleaned)
    cleaned = re.sub(r"\n{2,}", "\n", cleaned)
    return cleaned.strip()


def _get(url: str) -> dict:
    time.sleep(EDGAR_RATE_LIMIT_DELAY)
    resp = requests.get(url, headers=EDGAR_HEADERS, timeout=15)
    resp.raise_for_status()
    return resp.json()


def _build_filing_url(accession_no: str, cik: str, doc_name: str) -> str:
    acc_clean = accession_no.replace("-", "")
    return f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc_clean}/{doc_name}"


def _normalise_filing_text(text: str) -> str:
    if text.lstrip().startswith("<"):
        return _strip_html_tags(text)
    return text


def _load_cached_filing_row(
    conn: sqlite3.Connection,
    ticker: str,
    accession_no: str,
    doc_name: str,
) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT *
        FROM edgar_filing_cache
        WHERE ticker = ? AND accession_no = ? AND doc_name = ?
        LIMIT 1
        """,
        [ticker.upper(), accession_no, doc_name],
    ).fetchone()


def _cache_filing_text(
    ticker: str,
    cik: str,
    form_type: str,
    filing_date: str | None,
    accession_no: str,
    doc_name: str,
    raw_text: str,
) -> str:
    clean_text = _normalise_filing_text(raw_text)
    raw_dir = EDGAR_CACHE_RAW_DIR / ticker.upper()
    clean_dir = EDGAR_CACHE_CLEAN_DIR / ticker.upper()
    raw_dir.mkdir(parents=True, exist_ok=True)
    clean_dir.mkdir(parents=True, exist_ok=True)

    file_stub = f"{accession_no}_{_safe_filename(doc_name)}"
    raw_path = raw_dir / f"{file_stub}.html"
    clean_path = clean_dir / f"{file_stub}.txt"
    raw_path.write_text(raw_text, encoding="utf-8")
    clean_path.write_text(clean_text, encoding="utf-8")

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    conn = _connect_cache()
    try:
        upsert_edgar_filing_cache(
            conn,
            {
                "ticker": ticker.upper(),
                "cik": cik,
                "form_type": form_type,
                "accession_no": accession_no,
                "filing_date": filing_date,
                "doc_name": doc_name,
                "source_url": _build_filing_url(accession_no, cik, doc_name),
                "raw_path": str(raw_path),
                "clean_path": str(clean_path),
                "raw_text_hash": _hash_text(raw_text),
                "clean_text_hash": _hash_text(clean_text),
                "parser_version": EDGAR_PARSER_VERSION,
                "fetched_at": now,
                "cleaned_at": now,
            },
        )
    finally:
        conn.close()
    return clean_text


def _get_cached_or_fetch_filing_text(
    ticker: str,
    cik: str,
    form_type: str,
    filing_date: str | None,
    accession_no: str,
    doc_name: str,
    max_chars: int,
) -> str | None:
    if max_chars <= 0:
        return ""

    conn = _connect_cache()
    try:
        cached = _load_cached_filing_row(conn, ticker, accession_no, doc_name)
        if cached is not None:
            clean_path = Path(cached["clean_path"]) if cached["clean_path"] else None
            raw_path = Path(cached["raw_path"]) if cached["raw_path"] else None
            if (
                clean_path
                and clean_path.exists()
                and str(cached["parser_version"] or "") == EDGAR_PARSER_VERSION
            ):
                return clean_path.read_text(encoding="utf-8")[:max_chars]

            if raw_path and raw_path.exists():
                raw_text = raw_path.read_text(encoding="utf-8")
                clean_text = _normalise_filing_text(raw_text)
                clean_path = clean_path or (
                    EDGAR_CACHE_CLEAN_DIR / ticker.upper() / f"{accession_no}_{_safe_filename(doc_name)}.txt"
                )
                clean_path.parent.mkdir(parents=True, exist_ok=True)
                clean_path.write_text(clean_text, encoding="utf-8")
                now = datetime.now(timezone.utc).isoformat(timespec="seconds")
                upsert_edgar_filing_cache(
                    conn,
                    {
                        "ticker": ticker.upper(),
                        "cik": cik,
                        "form_type": form_type,
                        "accession_no": accession_no,
                        "filing_date": filing_date,
                        "doc_name": doc_name,
                        "source_url": _build_filing_url(accession_no, cik, doc_name),
                        "raw_path": str(raw_path),
                        "clean_path": str(clean_path),
                        "raw_text_hash": _hash_text(raw_text),
                        "clean_text_hash": _hash_text(clean_text),
                        "parser_version": EDGAR_PARSER_VERSION,
                        "fetched_at": str(cached["fetched_at"] or now),
                        "cleaned_at": now,
                    },
                )
                return clean_text[:max_chars]
        raw_text = get_filing_text(accession_no, cik, doc_name)
    finally:
        conn.close()

    if raw_text is None:
        return None
    return _cache_filing_text(
        ticker=ticker,
        cik=cik,
        form_type=form_type,
        filing_date=filing_date,
        accession_no=accession_no,
        doc_name=doc_name,
        raw_text=raw_text,
    )[:max_chars]


def _load_ticker_map() -> dict[str, str]:
    """
    Return {TICKER_UPPER: zero_padded_cik} for every public company.
    Downloads company_tickers.json from SEC if cache is missing or stale (>24h).
    """
    # Use cache if fresh
    if _TICKERS_CACHE_PATH.exists():
        age = (
            datetime.now(timezone.utc).timestamp()
            - _TICKERS_CACHE_PATH.stat().st_mtime
        )
        if age < _TICKERS_CACHE_TTL_SECONDS:
            raw = json.loads(_TICKERS_CACHE_PATH.read_text(encoding="utf-8"))
            return {
                v["ticker"].upper(): str(v["cik_str"]).zfill(10)
                for v in raw.values()
            }

    # Download fresh copy
    resp = requests.get(_TICKERS_URL, headers=EDGAR_HEADERS, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    _TICKERS_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _TICKERS_CACHE_PATH.write_text(json.dumps(data), encoding="utf-8")

    return {
        v["ticker"].upper(): str(v["cik_str"]).zfill(10)
        for v in data.values()
    }


def get_cik(ticker: str) -> str:
    """Resolve ticker → zero-padded CIK string."""
    mapping = _load_ticker_map()
    cik = mapping.get(ticker.upper())
    if cik is None:
        raise ValueError(f"CIK not found for {ticker!r}")
    return cik


def get_company_facts(cik: str) -> dict:
    """Return full XBRL company facts (revenue, EPS, etc.)."""
    return _get(f"{EDGAR_BASE_URL}/api/xbrl/companyfacts/CIK{cik}.json")


def get_submissions(cik: str) -> dict:
    """Return company submission history (all filings)."""
    return _get(f"{EDGAR_BASE_URL}/submissions/CIK{cik}.json")


def get_filing_text(accession_no: str, cik: str, doc_name: str) -> Optional[str]:
    """
    Fetch the raw text of a specific document from a filing.
    accession_no: e.g. '0001234567-23-000001'
    doc_name: e.g. 'R2.htm', primary document name from filing index
    """
    url = _build_filing_url(accession_no, cik, doc_name)
    time.sleep(EDGAR_RATE_LIMIT_DELAY)
    resp = requests.get(url, headers=EDGAR_HEADERS, timeout=20)
    if resp.status_code == 200:
        return resp.text
    return None


def get_recent_filings(cik: str, form_type: str, limit: int = 4) -> list[dict]:
    """
    Return the most recent filings of a given type (10-K, 10-Q, 8-K).
    Each item: {accession_no, filing_date, primary_doc}
    """
    subs = get_submissions(cik)
    filings = subs.get("filings", {}).get("recent", {})

    forms = filings.get("form", [])
    accessions = filings.get("accessionNumber", [])
    dates = filings.get("filingDate", [])
    primary_docs = filings.get("primaryDocument", [])

    results = []
    for form, acc, date, doc in zip(forms, accessions, dates, primary_docs):
        if form == form_type:
            results.append({
                "accession_no": acc,
                "filing_date": date,
                "primary_doc": doc,
            })
        if len(results) >= limit:
            break

    return results


def get_10k_text(ticker: str, max_chars: int = 50_000) -> str | None:
    """
    Return the most recent 10-K primary document text for a ticker.
    Returns None on any failure.
    """
    try:
        cik = get_cik(ticker)
        filings = get_recent_filings(cik, "10-K", limit=1)
        if not filings:
            return None

        recent = filings[0]
        accession_no = recent.get("accession_no")
        primary_doc = recent.get("primary_doc")
        if not accession_no or not primary_doc:
            return None

        return _get_cached_or_fetch_filing_text(
            ticker=ticker,
            cik=cik,
            form_type="10-K",
            filing_date=recent.get("filing_date"),
            accession_no=accession_no,
            doc_name=primary_doc,
            max_chars=max_chars,
        )
    except Exception:
        return None


def get_recent_10q_texts(ticker: str, limit: int = 2, max_chars_each: int = 50_000) -> list[dict]:
    """
    Return the cleaned text of the most recent 10-Q filings for a ticker.
    Each item: {filing_date, accession_no, text}
    Returns an empty list on failure.
    """
    try:
        cik = get_cik(ticker)
        filings = get_recent_filings(cik, "10-Q", limit=limit)
        results = []
        for f in filings:
            accession_no = f.get("accession_no")
            primary_doc = f.get("primary_doc")
            if not accession_no or not primary_doc:
                continue
            text = _get_cached_or_fetch_filing_text(
                ticker=ticker,
                cik=cik,
                form_type="10-Q",
                filing_date=f.get("filing_date"),
                accession_no=accession_no,
                doc_name=primary_doc,
                max_chars=max_chars_each,
            )
            results.append(
                {
                    "filing_date": f.get("filing_date"),
                    "accession_no": accession_no,
                    "text": text if text else "(no text retrieved)",
                }
            )
        return results
    except Exception:
        return []


def get_8k_texts(ticker: str, limit: int = 3, max_chars_each: int = 15_000) -> list[dict]:
    """
    Return the text of the most recent 8-K filings for a ticker.
    Each item: {filing_date, accession_no, text}
    8-Ks are earnings press releases — the primary document is usually a .htm exhibit.
    Returns an empty list on failure.
    """
    try:
        cik = get_cik(ticker)
        filings = get_recent_filings(cik, "8-K", limit=limit)
        results = []
        for f in filings:
            accession_no = f.get("accession_no")
            primary_doc = f.get("primary_doc")
            if not accession_no or not primary_doc:
                continue
            text = _get_cached_or_fetch_filing_text(
                ticker=ticker,
                cik=cik,
                form_type="8-K",
                filing_date=f.get("filing_date"),
                accession_no=accession_no,
                doc_name=primary_doc,
                max_chars=max_chars_each,
            )
            results.append({
                "filing_date": f.get("filing_date"),
                "accession_no": accession_no,
                "text": (text if text else "(no text retrieved)"),
            })
        return results
    except Exception:
        return []


def extract_financial_facts(company_facts: dict) -> dict:
    """
    Pull key financial metrics from XBRL company facts.
    Returns dict of {metric: [(period, value), ...]} for recent periods.
    """
    us_gaap = company_facts.get("facts", {}).get("us-gaap", {})

    metrics = {
        "Revenues": "Revenues",
        "NetIncomeLoss": "NetIncomeLoss",
        "EarningsPerShareBasic": "EarningsPerShareBasic",
        "OperatingIncomeLoss": "OperatingIncomeLoss",
        "GrossProfit": "GrossProfit",
        "CashAndCashEquivalentsAtCarryingValue": "CashAndCashEquivalentsAtCarryingValue",
        "LongTermDebt": "LongTermDebt",
        "NetCashProvidedByUsedInOperatingActivities": "OperatingCashFlow",
        "CapitalExpenditureDiscontinuedOperations": "Capex",
        "CommonStockSharesOutstanding": "SharesOutstanding",
    }

    result = {}
    for gaap_key, friendly_key in metrics.items():
        if gaap_key not in us_gaap:
            continue
        units = us_gaap[gaap_key].get("units", {})
        # Prefer USD, fall back to shares or pure number
        vals = units.get("USD") or units.get("shares") or units.get("pure") or []
        # Filter to annual (10-K) filings, last 5 years
        annual = [
            v for v in vals
            if v.get("form") == "10-K" and v.get("end", "")[:4].isdigit()
        ]
        annual.sort(key=lambda x: x["end"])
        result[friendly_key] = [
            {"period": v["end"], "value": v["val"]}
            for v in annual[-5:]
        ]

    return result
