"""
SEC EDGAR REST API client.
Now powered by `edgartools` for robust fetching, caching, and XBRL parsing.
"""

from typing import Optional, Union
from edgar import set_identity, Company
from config import EDGAR_HEADERS

# Set identity for SEC API
user_agent_fallback = EDGAR_HEADERS.get("User-Agent", "AI Fund Manager ai@example.com")
set_identity(user_agent_fallback)

def get_cik(ticker: str) -> str:
    """Resolve ticker → zero-padded CIK string."""
    company = Company(ticker)
    return str(company.cik).zfill(10)

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
    try:
        results = []
        filings = Company(ticker).get_filings(form=form_type).head(limit)
        for filing in filings:
            results.append({
                "accession_no": str(filing.accession_no),
                "filing_date": str(filing.filing_date),
                "primary_doc": str(filing.accession_no),
            })
        return results
    except Exception:
        return []


def get_filing_text_by_accession(ticker: str, accession_no: str, max_chars: Optional[int] = None) -> Optional[str]:
    """
    Fetch the full text for a specific filing identified by accession number.
    Searches recent 10-K and 10-Q filings for the matching accession.
    """
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
        return None
    except Exception:
        return None

def get_10k_text(ticker: str, max_chars: Optional[int] = None) -> Optional[str]:
    """
    Return the most recent 10-K primary document text for a ticker.
    If max_chars is specified, truncates the document (good for LLMs).
    """
    try:
        filings = Company(ticker).get_filings(form="10-K")
        if filings.empty:
            return None

        filing = filings.latest()
        text = filing.text()
        if max_chars is not None:
            return text[:max_chars]
        return text
    except Exception:
        return None

def get_recent_10q_texts(ticker: str, limit: int = 2, max_chars_each: Optional[int] = None) -> list[dict]:
    """
    Return the cleaned text of the most recent 10-Q filings for a ticker.
    """
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
        return results
    except Exception:
        return []

def get_8k_texts(ticker: str, limit: int = 3, max_chars_each: Optional[int] = None) -> list[dict]:
    """
    Return the text of the most recent 8-K filings for a ticker.
    """
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
        return results
    except Exception:
        return []

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
