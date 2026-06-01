"""
SEC EDGAR REST API client.
Now powered by `edgartools` for robust fetching, caching, and XBRL parsing.
"""

import os
from pathlib import Path
import sqlite3
from typing import Optional, Union

from config import DB_PATH, EDGAR_HEADERS, ROOT_DIR


def _configure_workspace_edgar_cache() -> None:
    """Keep edgartools away from user-home caches in sandboxed/operator runs."""
    local_data_dir = Path(
        os.getenv("EDGAR_LOCAL_DATA_DIR")
        or ROOT_DIR / "data" / "cache" / "edgar_tools"
    )
    local_home = local_data_dir.parent / "home"
    local_data_dir.mkdir(parents=True, exist_ok=True)
    local_home.mkdir(parents=True, exist_ok=True)
    os.environ["EDGAR_LOCAL_DATA_DIR"] = str(local_data_dir)

    # edgartools' HTTP cache currently reads expanduser("~") at import time.
    # Point the process home at a workspace-local folder before importing it.
    if os.getenv("ALPHA_POD_WORKSPACE_EDGAR_HOME", "1") != "0":
        os.environ["HOME"] = str(local_home)
        os.environ["USERPROFILE"] = str(local_home)


_configure_workspace_edgar_cache()

from edgar import Company, set_identity  # noqa: E402

# Set identity for SEC API
user_agent_fallback = EDGAR_HEADERS.get("User-Agent", "AI Fund Manager ai@example.com")
set_identity(user_agent_fallback)


def _cache_only() -> bool:
    return os.getenv("ALPHA_POD_EDGAR_CACHE_ONLY", "0").strip().lower() in {"1", "true", "yes"}


def _read_cached_text(path_value: str | None, max_chars: Optional[int] = None) -> Optional[str]:
    if not path_value:
        return None
    path = Path(path_value)
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8", errors="ignore")
    return text[:max_chars] if max_chars is not None else text


def _cached_filing_rows(ticker: str, form_type: str, limit: int = 4) -> list[dict]:
    try:
        with sqlite3.connect(str(DB_PATH)) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT cik, form_type, accession_no, filing_date, doc_name, clean_path, raw_path
                FROM edgar_filing_cache
                WHERE ticker = ? AND form_type = ?
                ORDER BY COALESCE(filing_date, '') DESC, fetched_at DESC
                LIMIT ?
                """,
                [ticker.upper().strip(), form_type, int(limit)],
            ).fetchall()
    except Exception:
        return []
    return [dict(row) for row in rows]


def _cached_filing_text(
    ticker: str,
    accession_no: str,
    *,
    form_types: tuple[str, ...] = ("10-K", "10-Q", "8-K"),
    max_chars: Optional[int] = None,
) -> Optional[str]:
    try:
        placeholders = ",".join("?" for _ in form_types)
        params: list[object] = [ticker.upper().strip(), str(accession_no), *form_types]
        with sqlite3.connect(str(DB_PATH)) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                f"""
                SELECT clean_path, raw_path
                FROM edgar_filing_cache
                WHERE ticker = ? AND accession_no = ? AND form_type IN ({placeholders})
                ORDER BY COALESCE(filing_date, '') DESC
                LIMIT 1
                """,
                params,
            ).fetchone()
    except Exception:
        return None
    if row is None:
        return None
    return _read_cached_text(row["clean_path"], max_chars) or _read_cached_text(row["raw_path"], max_chars)


def _cached_cik(ticker: str) -> str | None:
    try:
        with sqlite3.connect(str(DB_PATH)) as conn:
            row = conn.execute(
                """
                SELECT cik
                FROM edgar_filing_cache
                WHERE ticker = ? AND cik IS NOT NULL AND cik != ''
                ORDER BY COALESCE(filing_date, '') DESC
                LIMIT 1
                """,
                [ticker.upper().strip()],
            ).fetchone()
    except Exception:
        return None
    if row is None:
        return None
    return str(row[0]).zfill(10)

def get_cik(ticker: str) -> str:
    """Resolve ticker → zero-padded CIK string."""
    if _cache_only():
        cached = _cached_cik(ticker)
        if cached:
            return cached
    try:
        company = Company(ticker)
        return str(company.cik).zfill(10)
    except Exception:
        cached = _cached_cik(ticker)
        if cached:
            return cached
        raise

def get_company_facts(cik: str) -> dict:
    """
    Deprecated: Was used to fetch raw JSON block for facts.
    Returns an empty dict as downstream consumers should now pass
    `ticker` directly to `extract_financial_facts`.
    """
    return {}

def get_submissions(cik: str) -> dict:
    """Deprecated: The submissions API is abstracted away by edgartools."""
    return {}

def get_filing_text(accession_no: str, cik: str, doc_name: str) -> Optional[str]:
    """Deprecated: Retrieve filings via `Company().get_filings()` directly."""
    return None

def get_recent_filings(cik: str, form_type: str, limit: int = 4) -> list[dict]:
    """Deprecated."""
    return []


def get_recent_filing_metadata(ticker: str, form_type: str, limit: int = 4) -> list[dict]:
    """
    Return metadata for recent filings of the given form type.
    Each dict has: accession_no, filing_date, primary_doc.
    """
    if _cache_only():
        return [
            {
                "accession_no": row["accession_no"],
                "filing_date": row.get("filing_date"),
                "primary_doc": row.get("doc_name") or row["accession_no"],
            }
            for row in _cached_filing_rows(ticker, form_type, limit)
        ]
    try:
        results = []
        filings = Company(ticker).get_filings(form=form_type).head(limit)
        for filing in filings:
            results.append({
                "accession_no": str(filing.accession_no),
                "filing_date": str(filing.filing_date),
                "primary_doc": str(filing.accession_no),
            })
        return results or [
            {
                "accession_no": row["accession_no"],
                "filing_date": row.get("filing_date"),
                "primary_doc": row.get("doc_name") or row["accession_no"],
            }
            for row in _cached_filing_rows(ticker, form_type, limit)
        ]
    except Exception:
        return [
            {
                "accession_no": row["accession_no"],
                "filing_date": row.get("filing_date"),
                "primary_doc": row.get("doc_name") or row["accession_no"],
            }
            for row in _cached_filing_rows(ticker, form_type, limit)
        ]


def get_filing_text_by_accession(ticker: str, accession_no: str, max_chars: Optional[int] = None) -> Optional[str]:
    """
    Fetch the full text for a specific filing identified by accession number.
    Searches recent 10-K and 10-Q filings for the matching accession.
    """
    if _cache_only():
        return _cached_filing_text(ticker, accession_no, max_chars=max_chars)
    try:
        company = Company(ticker)
        for form_type in ("10-K", "10-Q"):
            try:
                for filing in company.get_filings(form=form_type).head(10):
                    if str(filing.accession_no) == str(accession_no):
                        text = filing.text()
                        if max_chars is not None and text:
                            return text[:max_chars]
                        return text or None
            except Exception:
                continue
        return _cached_filing_text(ticker, accession_no, max_chars=max_chars)
    except Exception:
        return _cached_filing_text(ticker, accession_no, max_chars=max_chars)

def get_10k_text(ticker: str, max_chars: Optional[int] = None) -> Optional[str]:
    """
    Return the most recent 10-K primary document text for a ticker.
    If max_chars is specified, truncates the document (good for LLMs).
    """
    if _cache_only():
        rows = _cached_filing_rows(ticker, "10-K", limit=1)
        if not rows:
            return None
        return _read_cached_text(rows[0].get("clean_path"), max_chars) or _read_cached_text(rows[0].get("raw_path"), max_chars)
    try:
        filings = Company(ticker).get_filings(form="10-K")
        if filings.empty:
            rows = _cached_filing_rows(ticker, "10-K", limit=1)
            if not rows:
                return None
            return _read_cached_text(rows[0].get("clean_path"), max_chars) or _read_cached_text(rows[0].get("raw_path"), max_chars)

        filing = filings.latest()
        text = filing.text()
        if max_chars is not None:
            return text[:max_chars]
        return text
    except Exception:
        rows = _cached_filing_rows(ticker, "10-K", limit=1)
        if not rows:
            return None
        return _read_cached_text(rows[0].get("clean_path"), max_chars) or _read_cached_text(rows[0].get("raw_path"), max_chars)

def get_recent_10q_texts(ticker: str, limit: int = 2, max_chars_each: Optional[int] = None) -> list[dict]:
    """
    Return the cleaned text of the most recent 10-Q filings for a ticker.
    """
    if _cache_only():
        return [
            {
                "filing_date": str(row.get("filing_date")),
                "accession_no": row["accession_no"],
                "text": _read_cached_text(row.get("clean_path"), max_chars_each)
                or _read_cached_text(row.get("raw_path"), max_chars_each)
                or "(no text retrieved)",
            }
            for row in _cached_filing_rows(ticker, "10-Q", limit)
        ]
    try:
        filings = Company(ticker).get_filings(form="10-Q").head(limit)
        results = []
        for filing in filings:
            text = filing.text()
            if max_chars_each is not None:
                text = text[:max_chars_each]
            results.append({
                "filing_date": str(filing.filing_date),
                "accession_no": filing.accession_no,
                "text": text or "(no text retrieved)"
            })
        if results:
            return results
    except Exception:
        pass
    return [
        {
            "filing_date": str(row.get("filing_date")),
            "accession_no": row["accession_no"],
            "text": _read_cached_text(row.get("clean_path"), max_chars_each)
            or _read_cached_text(row.get("raw_path"), max_chars_each)
            or "(no text retrieved)",
        }
        for row in _cached_filing_rows(ticker, "10-Q", limit)
    ]

def get_8k_texts(ticker: str, limit: int = 3, max_chars_each: Optional[int] = None) -> list[dict]:
    """
    Return the text of the most recent 8-K filings for a ticker.
    """
    if _cache_only():
        return [
            {
                "filing_date": str(row.get("filing_date")),
                "accession_no": row["accession_no"],
                "text": _read_cached_text(row.get("clean_path"), max_chars_each)
                or _read_cached_text(row.get("raw_path"), max_chars_each)
                or "(no text retrieved)",
            }
            for row in _cached_filing_rows(ticker, "8-K", limit)
        ]
    try:
        filings = Company(ticker).get_filings(form="8-K").head(limit)
        results = []
        for filing in filings:
            text = filing.text()
            if max_chars_each is not None:
                text = text[:max_chars_each]
            results.append({
                "filing_date": str(filing.filing_date),
                "accession_no": filing.accession_no,
                "text": text or "(no text retrieved)"
            })
        if results:
            return results
    except Exception:
        pass
    return [
        {
            "filing_date": str(row.get("filing_date")),
            "accession_no": row["accession_no"],
            "text": _read_cached_text(row.get("clean_path"), max_chars_each)
            or _read_cached_text(row.get("raw_path"), max_chars_each)
            or "(no text retrieved)",
        }
        for row in _cached_filing_rows(ticker, "8-K", limit)
    ]

def extract_financial_facts(ticker_or_facts: Union[str, dict]) -> list[dict]:
    """
    Extract structured XBRL facts.
    We expect `ticker_or_facts` to be a string ticker. The legacy dict support
    will return an empty list.
    """
    if isinstance(ticker_or_facts, dict):
        return []

    ticker = ticker_or_facts
    try:
        company = Company(ticker)
        facts = company.get_facts()
    except Exception:
        return []

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
        "OperatingLeaseLiability": "OperatingLeaseLiability",
        "FinanceLeaseLiability": "FinanceLeaseLiability",
        "MinorityInterest": "MinorityInterest",
        "PreferredStockValue": "PreferredStockValue",
        "DefinedBenefitPlanBenefitObligation": "PensionObligation",
        "DefinedBenefitPlanFairValueOfPlanAssets": "PensionAssets",
        "ShareBasedCompensation": "ShareBasedCompensation",
    }

    results = []

    for concept, friendly_name in metrics.items():
        try:
            # High quality only filters out weird overlapping proxy facts
            query_df = facts.query().by_concept(concept).high_quality_only().to_dataframe()
            if query_df.empty:
                continue

            for _, row in query_df.iterrows():
                val = row.get("numeric_value")
                if val is None:
                    continue

                form_val = row.get("form_type", "Unknown")

                results.append({
                    "metric": friendly_name,
                    "form": form_val,
                    "frame": row.get("fiscal_period", "Unknown"),
                    "end": str(row.get("period_end", "Unknown")),
                    "value": float(val),
                    "unit": row.get("unit", "Unknown")
                })
        except Exception:
            continue

    # Sort chronologically
    results.sort(key=lambda x: (x["metric"], x["end"], x["frame"] or ""))
    return results
