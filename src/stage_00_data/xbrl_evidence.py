"""Structured SEC XBRL fact evidence with filing-level provenance.

This module is deliberately narrower than filing narrative retrieval.  XBRL is
used here for typed values, periods, dimensions, and filing vintage.  The filing
HTML remains the source for note prose, surrounding disclosure context, and
future exact inline-XBRL anchors.
"""

from __future__ import annotations

from datetime import date, datetime
import os
from typing import Any, Iterable

from edgar import Company


XBRL_EVIDENCE_SOURCE = "sec_xbrl_companyfacts_v3"


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    text = str(value).strip()
    return text or None


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _sec_filing_index_url(cik: str | None, accession: str | None) -> str | None:
    cik_text = _text(cik)
    accession_text = _text(accession)
    if not cik_text or not accession_text:
        return None
    try:
        cik_path = str(int(cik_text))
    except ValueError:
        return None
    return (
        f"https://www.sec.gov/Archives/edgar/data/{cik_path}/"
        f"{accession_text.replace('-', '')}-index.html"
    )


def _period_label(fact: Any) -> str | None:
    start = _iso(getattr(fact, "period_start", None))
    end = _iso(getattr(fact, "period_end", None))
    if start and end:
        return f"{start}/{end}"
    return end or start


def _fact_id(
    ticker: str,
    fact: Any,
    period: str | None,
) -> str:
    concept = _text(getattr(fact, "concept", None)) or "unknown"
    accession = _text(getattr(fact, "accession", None)) or "unknown"
    context_ref = _text(getattr(fact, "context_ref", None)) or period or "unknown"
    dimensions = getattr(fact, "dimensions", None) or {}
    dimension_key = ";".join(
        f"{key}={dimensions[key]}" for key in sorted(dimensions)
    )
    suffix = f"{context_ref}:{dimension_key}" if dimension_key else context_ref
    return f"xbrl:{ticker}:{accession}:{concept}:{suffix}"


def normalize_financial_fact(
    fact: Any,
    *,
    ticker: str,
    cik: str | None = None,
) -> dict[str, Any]:
    """Convert an ``edgartools`` FinancialFact into an evidence record.

    The function intentionally preserves dimension and filing metadata.  It does
    not choose a winning restatement, infer an accounting treatment, or collapse
    dimensional facts into a company-wide total.
    """

    normalized_ticker = str(ticker).upper().strip()
    period = _period_label(fact)
    accession = _text(getattr(fact, "accession", None))
    source_locator = _sec_filing_index_url(cik, accession)
    data_quality = getattr(fact, "data_quality", None)
    data_quality_value = getattr(data_quality, "value", data_quality)
    dimensions = getattr(fact, "dimensions", None) or {}

    metadata: dict[str, Any] = {
        "source": XBRL_EVIDENCE_SOURCE,
        "taxonomy": _text(getattr(fact, "taxonomy", None)),
        "label": _text(getattr(fact, "label", None)),
        "scale": getattr(fact, "scale", None),
        "period_type": _text(getattr(fact, "period_type", None)),
        "period_start": _iso(getattr(fact, "period_start", None)),
        "period_end": _iso(getattr(fact, "period_end", None)),
        "fiscal_year": getattr(fact, "fiscal_year", None),
        "fiscal_period": _text(getattr(fact, "fiscal_period", None)),
        "filing_date": _iso(getattr(fact, "filing_date", None)),
        "form_type": _text(getattr(fact, "form_type", None)),
        "accession": accession,
        "data_quality": _text(data_quality_value),
        "is_audited": getattr(fact, "is_audited", None),
        "is_restated": getattr(fact, "is_restated", None),
        "is_estimated": getattr(fact, "is_estimated", None),
        "confidence_score": getattr(fact, "confidence_score", None),
        "context_ref": _text(getattr(fact, "context_ref", None)),
        "dimensions": dict(dimensions),
        "statement_type": _text(getattr(fact, "statement_type", None)),
        "line_item_sequence": getattr(fact, "line_item_sequence", None),
        "depth": getattr(fact, "depth", None),
        "parent_concept": _text(getattr(fact, "parent_concept", None)),
        "section": _text(getattr(fact, "section", None)),
        "is_abstract": getattr(fact, "is_abstract", None),
        "is_total": getattr(fact, "is_total", None),
        "presentation_order": getattr(fact, "presentation_order", None),
        "source_locator_type": "sec_filing_index" if source_locator else "missing",
    }

    return {
        "fact_id": _fact_id(normalized_ticker, fact, period),
        "fact_name": _text(getattr(fact, "concept", None)) or "unknown",
        "value": getattr(fact, "value", None),
        "numeric_value": getattr(fact, "numeric_value", None),
        "unit": _text(getattr(fact, "unit", None)),
        "period": period,
        "source_locator": source_locator,
        "metadata": metadata,
    }


def _query_facts(facts: Any, concept: str) -> list[Any]:
    query = facts.query().by_concept(concept)
    execute = getattr(query, "execute", None)
    if callable(execute):
        requested_local_name = str(concept).replace("_", ":").rsplit(":", 1)[-1].lower()
        return [
            fact
            for fact in list(execute() or [])
            if str(getattr(fact, "concept", "")).rsplit(":", 1)[-1].lower()
            == requested_local_name
        ]
    raise TypeError("edgartools fact query does not expose execute()")


def _fact_recency_key(fact: Any) -> tuple[str, str, str]:
    return (
        _iso(getattr(fact, "filing_date", None)) or "",
        _iso(getattr(fact, "period_end", None)) or "",
        _iso(getattr(fact, "period_start", None)) or "",
    )


def get_xbrl_fact_evidence(
    ticker: str,
    concepts: Iterable[str],
    *,
    max_facts_per_concept: int | None = None,
) -> dict[str, Any]:
    """Fetch selected Company Facts and return explicit retrieval status.

    The adapter keeps all matching fact vintages unless a caller supplies a
    per-concept cap.  Consumers remain responsible for choosing the accounting
    period or restatement appropriate to their analysis.
    """

    normalized_ticker = str(ticker).upper().strip()
    requested_concepts = [str(concept).strip() for concept in concepts if str(concept).strip()]
    base_result: dict[str, Any] = {
        "ticker": normalized_ticker,
        "source": XBRL_EVIDENCE_SOURCE,
        "concepts_requested": requested_concepts,
        "facts": [],
        "fact_count": 0,
        "errors": [],
    }
    if not requested_concepts:
        return {**base_result, "status": "no_concepts"}

    if os.getenv("ALPHA_POD_EDGAR_CACHE_ONLY", "0").strip().lower() in {
        "1",
        "true",
        "yes",
    }:
        message = "XBRL facts are not persisted in the local EDGAR cache"
        return {
            **base_result,
            "status": "cache_only_unavailable",
            "error": message,
            "errors": [message],
        }

    try:
        company = Company(normalized_ticker)
        facts = company.get_facts()
    except Exception as exc:
        message = str(exc)
        return {
            **base_result,
            "status": "error",
            "error": message,
            "errors": [message],
        }

    if facts is None:
        return {**base_result, "status": "no_facts"}

    cik = _text(getattr(company, "cik", None))
    records: list[dict[str, Any]] = []
    seen_fact_ids: set[str] = set()
    errors: list[str] = []
    for concept in requested_concepts:
        try:
            matching_facts = _query_facts(facts, concept)
            matching_facts.sort(key=_fact_recency_key, reverse=True)
            if max_facts_per_concept is not None:
                matching_facts = matching_facts[: max(0, int(max_facts_per_concept))]
            for fact in matching_facts:
                record = normalize_financial_fact(
                    fact,
                    ticker=normalized_ticker,
                    cik=cik,
                )
                if record["fact_id"] in seen_fact_ids:
                    continue
                seen_fact_ids.add(record["fact_id"])
                records.append(record)
        except Exception as exc:
            errors.append(f"{concept}: {exc}")

    status = "ok" if records and not errors else "partial" if records else (
        "error" if errors else "no_matching_facts"
    )
    return {
        **base_result,
        "status": status,
        "facts": records,
        "fact_count": len(records),
        "errors": errors,
        "cik": cik,
    }


__all__ = [
    "XBRL_EVIDENCE_SOURCE",
    "get_xbrl_fact_evidence",
    "normalize_financial_fact",
]
