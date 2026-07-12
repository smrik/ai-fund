"""Network-facing retrieval for dimension-preserving segment evidence."""

from __future__ import annotations

from collections import defaultdict
import os
from typing import Any, Mapping, Sequence

from src.stage_00_data.edgar_client import Company

from src.stage_00_data.segment_evidence import (
    DEFAULT_FORM_TYPES,
    REPORTABLE_SEGMENT_AXIS,
    SEGMENT_EVIDENCE_SOURCE,
    _METRICS,
    _REASONS,
    _apply_reconciliation_gate,
    _filing_url,
    _iso,
    _schedule,
    _text,
    build_segment_evidence_from_inline_xbrl,
)


def _filing_metadata(filing: Any, cik: Any) -> dict[str, Any]:
    accession = _text(getattr(filing, "accession_no", None)) or _text(
        getattr(filing, "accession", None)
    )
    primary_document = _text(getattr(filing, "primary_document", None))
    source_locator, locator_type = _filing_url(cik, accession, primary_document)
    return {
        "cik": _text(cik),
        "form_type": _text(getattr(filing, "form", None))
        or _text(getattr(filing, "form_type", None)),
        "filing_date": _iso(getattr(filing, "filing_date", None)),
        "period_of_report": _iso(getattr(filing, "period_of_report", None)),
        "accession": accession,
        "primary_document": primary_document,
        "source_locator": source_locator,
        "source_locator_type": locator_type,
    }


def _empty_schedules(
    kpi_concepts: Mapping[str, Sequence[str]] | None,
) -> dict[str, dict[str, Any]]:
    schedules = {
        key: _schedule(key, [], concepts) for key, concepts in _METRICS.items()
    }
    schedules["kpis"] = _schedule(
        "kpis",
        [],
        sorted(
            {
                concept
                for concepts in (kpi_concepts or {}).values()
                for concept in concepts
            }
        ),
    )
    return schedules


def _aggregate(
    ticker: str,
    results: Sequence[dict[str, Any]],
    forms: Sequence[str],
    errors: Sequence[str],
    kpi_concepts: Mapping[str, Sequence[str]] | None,
) -> dict[str, Any]:
    schedules: dict[str, dict[str, Any]] = {}
    for key in ("revenue", "operating_income", "assets", "kpis"):
        rows = [
            row
            for result in results
            for row in result["schedules"][key]["rows"]
        ]
        rows.sort(
            key=lambda row: (
                row["filing_date"] or "",
                row["period_end"] or row["period_instant"] or "",
                row["period_start"] or "",
                row["metric_key"],
                row["segment_member"],
            )
        )
        concepts = sorted(
            {
                concept
                for result in results
                for concept in result["schedules"][key]["requested_concepts"]
            }
        )
        if key == "kpis" and not concepts:
            concepts = sorted(
                {
                    concept
                    for values in (kpi_concepts or {}).values()
                    for concept in values
                }
            )
        reason = next(
            (
                result["schedules"][key]["reason"]
                for result in results
                if result["schedules"][key]["reason"]
            ),
            _REASONS[key],
        )
        schedules[key] = _schedule(key, rows, concepts, reason)

    reconciliations = [
        item for result in results for item in result["reconciliations"]
    ]
    reconciliations.sort(
        key=lambda row: (
            row["filing_date"] or "",
            row["metric_key"],
            row["period_end"] or row["period_instant"] or "",
            row["period_start"] or "",
        )
    )
    for key in ("revenue", "operating_income", "assets"):
        metric_reconciliations = [
            item for item in reconciliations if item["metric_key"] == key
        ]
        schedules[key] = _apply_reconciliation_gate(
            schedules[key], metric_reconciliations
        )

    statuses = [schedules[key]["status"] for key in schedules]
    if all(value == "available" for value in statuses) and not errors:
        status = "ok"
    elif any(value == "available" for value in statuses):
        status = "partial"
    else:
        status = "error" if errors else "unavailable"

    counts: dict[str, int] = defaultdict(int)
    for item in reconciliations:
        counts[item["status"]] += 1
    period_candidates = [
        result["filing"].get("period_of_report")
        for result in results
        if result["filing"].get("period_of_report")
    ]
    axis_concepts = sorted(
        {
            concept
            for result in results
            for concept in result["coverage"]["segment_axis_concepts_present"]
        }
    )
    return {
        "ticker": ticker,
        "status": status,
        "source": SEGMENT_EVIDENCE_SOURCE,
        "segment_axis": REPORTABLE_SEGMENT_AXIS,
        "forms_requested": list(forms),
        "as_of_period_end": max(period_candidates) if period_candidates else None,
        "filings": [result["filing"] for result in results],
        "schedules": schedules,
        "reconciliations": reconciliations,
        "reconciliation_summary": dict(sorted(counts.items())),
        "coverage": {
            "segment_axis_concepts_present": axis_concepts,
            "requested_metrics": {
                key: schedules[key]["status"] for key in schedules
            },
        },
        "errors": list(errors),
    }


def get_segment_evidence(
    ticker: str,
    *,
    form_types: Sequence[str] = DEFAULT_FORM_TYPES,
    kpi_concepts: Mapping[str, Sequence[str]] | None = None,
) -> dict[str, Any]:
    """Return the latest requested filing vintages and reconciled facts.

    Comparative periods stay attached to the accession that reported them; no
    filing vintage is silently collapsed or preferred.
    """

    ticker = str(ticker).upper().strip()
    forms = tuple(form.strip().upper() for form in form_types if _text(form))
    base = {
        "ticker": ticker,
        "source": SEGMENT_EVIDENCE_SOURCE,
        "segment_axis": REPORTABLE_SEGMENT_AXIS,
        "forms_requested": list(forms),
        "filings": [],
        "schedules": _empty_schedules(kpi_concepts),
        "reconciliations": [],
        "reconciliation_summary": {},
        "coverage": {
            "segment_axis_concepts_present": [],
            "requested_metrics": {
                key: "unavailable"
                for key in ("revenue", "operating_income", "assets", "kpis")
            },
        },
        "errors": [],
    }
    if not forms:
        return {**base, "status": "no_forms"}
    if os.getenv("ALPHA_POD_EDGAR_CACHE_ONLY", "0").strip().lower() in {
        "1",
        "true",
        "yes",
    }:
        message = (
            "Inline XBRL filings are not persisted in the local EDGAR cache contract"
        )
        return {
            **base,
            "status": "cache_only_unavailable",
            "errors": [message],
        }
    try:
        company = Company(ticker)
    except Exception as exc:
        return {**base, "status": "error", "errors": [str(exc)]}

    results: list[dict[str, Any]] = []
    errors: list[str] = []
    cik = _text(getattr(company, "cik", None))
    for form in forms:
        try:
            filings = company.get_filings(form=form)
            if bool(getattr(filings, "empty", False)):
                errors.append(f"{form}: no filing found")
                continue
            filing = filings.latest()
            xbrl = filing.xbrl()
            if xbrl is None:
                errors.append(f"{form}: Inline XBRL unavailable")
                continue
            results.append(
                build_segment_evidence_from_inline_xbrl(
                    ticker=ticker,
                    facts=xbrl.facts.get_facts(),
                    contexts=xbrl.contexts,
                    filing=_filing_metadata(filing, cik),
                    kpi_concepts=kpi_concepts,
                )
            )
        except Exception as exc:
            errors.append(f"{form}: {exc}")
    if not results:
        return {
            **base,
            "status": "error" if errors else "no_filings",
            "errors": errors,
        }
    return _aggregate(ticker, results, forms, errors, kpi_concepts)


__all__ = ["get_segment_evidence"]
