"""
SEC EDGAR REST API client (free, no API key required).
Rate-limited to 10 req/sec per SEC guidelines.
"""

import time
import requests
from typing import Optional
from config import EDGAR_BASE_URL, EDGAR_HEADERS, EDGAR_RATE_LIMIT_DELAY


def _get(url: str) -> dict:
    time.sleep(EDGAR_RATE_LIMIT_DELAY)
    resp = requests.get(url, headers=EDGAR_HEADERS, timeout=15)
    resp.raise_for_status()
    return resp.json()


def get_cik(ticker: str) -> str:
    """Resolve ticker → zero-padded CIK string."""
    data = _get(f"{EDGAR_BASE_URL}/submissions/ticker/{ticker.lower()}.json")
    return str(data["cik"]).zfill(10)


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
    acc_clean = accession_no.replace("-", "")
    url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc_clean}/{doc_name}"
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

        filing_text = get_filing_text(accession_no, cik, primary_doc)
        if filing_text is None:
            return None

        if max_chars <= 0:
            return ""

        return filing_text[:max_chars]
    except Exception:
        return None

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



