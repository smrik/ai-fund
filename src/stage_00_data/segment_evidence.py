"""Deterministic reportable-segment evidence from SEC Inline XBRL.

Company Facts omits the filing contexts needed for segment dimensions.  This
adapter reads specific filings' Inline XBRL, keeps their axis/member pairs and
filing vintage, reconciles like-for-like facts, and never constructs values for
undisclosed measures.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
import hashlib
import json
import math
import re
from typing import Any, Iterable, Mapping, Sequence


SEGMENT_EVIDENCE_SOURCE = "sec_inline_xbrl_segments_v1"
REPORTABLE_SEGMENT_AXIS = "us-gaap:StatementBusinessSegmentsAxis"
DEFAULT_FORM_TYPES = ("10-K", "10-Q")

_METRICS: dict[str, tuple[str, ...]] = {
    "revenue": (
        "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
        "us-gaap:Revenues",
        "us-gaap:SalesRevenueNet",
    ),
    "operating_income": ("us-gaap:OperatingIncomeLoss",),
    "assets": ("us-gaap:Assets",),
}
_REASONS = {
    "revenue": "reportable_segment_revenue_not_disclosed_in_requested_filings",
    "operating_income": "reportable_segment_operating_income_not_disclosed_in_requested_filings",
    "assets": "reportable_segment_assets_not_disclosed_in_requested_filings",
    "kpis": "no_approved_kpi_concepts_no_semantic_inference",
}
_ACCEPTED_RECONCILIATION_STATUSES = frozenset(
    {"tied", "tied_within_reported_rounding"}
)
_RECONCILIATION_FAILURE_REASON = "segment_reconciliation_failed"


def _text(value: Any) -> str | None:
    text = "" if value is None else str(value).strip()
    return text or None


def _iso(value: Any) -> str | None:
    return value.isoformat() if isinstance(value, (date, datetime)) else _text(value)


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _local(qname: Any) -> str:
    return (_text(qname) or "").rsplit(":", 1)[-1]


def _matches(concept: Any, allowed: Iterable[str]) -> bool:
    full, local = (_text(concept) or "").lower(), _local(concept).lower()
    return any(
        full == str(candidate).strip().lower()
        or local == _local(candidate).lower()
        for candidate in allowed
    )


def _dimensions(context: Any) -> dict[str, str]:
    if context is None:
        return {}
    value = context.get("dimensions", context) if isinstance(context, Mapping) else getattr(context, "dimensions", None)
    if not isinstance(value, Mapping):
        return {}
    return {str(axis): str(member) for axis, member in value.items() if _text(axis) and _text(member)}


def _fact_dimensions(fact: Mapping[str, Any], contexts: Mapping[str, Any]) -> dict[str, str]:
    context_dims = _dimensions(contexts.get(_text(fact.get("context_ref"))))
    return context_dims or _dimensions(fact.get("dimensions"))


def _period(fact: Mapping[str, Any]) -> dict[str, str | None]:
    start, end = _iso(fact.get("period_start")), _iso(fact.get("period_end"))
    instant = _iso(fact.get("period_instant"))
    if start and end:
        label, period_type = f"{start}/{end}", "duration"
    else:
        label = instant or end or start
        period_type = _text(fact.get("period_type")) or "instant"
    return {
        "period": label,
        "period_type": period_type,
        "period_start": start,
        "period_end": end,
        "period_instant": instant,
    }


def _period_key(fact: Mapping[str, Any]) -> tuple[str | None, ...]:
    period = _period(fact)
    return tuple(period[key] for key in ("period_type", "period_start", "period_end", "period_instant"))


def _unit(fact: Mapping[str, Any]) -> str | None:
    return _text(fact.get("currency")) or _text(fact.get("unit_ref")) or _text(fact.get("unit"))


def _filing_url(cik: Any, accession: Any, document: Any) -> tuple[str | None, str]:
    cik_text, accession_text = _text(cik), _text(accession)
    if not cik_text or not accession_text:
        return None, "missing"
    try:
        cik_path = str(int(cik_text))
    except ValueError:
        return None, "missing"
    base = f"https://www.sec.gov/Archives/edgar/data/{cik_path}/{accession_text.replace('-', '')}"
    document_text = _text(document)
    return ((f"{base}/{document_text}", "sec_filing_document") if document_text else (f"{base}-index.html", "sec_filing_index"))


def _member_label(member: str, fallback: Any) -> str:
    fallback_text = _text(fallback)
    if fallback_text and fallback_text.lower() != _local(member).lower():
        return fallback_text
    local = re.sub(r"Member$", "", _local(member))
    return re.sub(r"(?<!^)(?=[A-Z0-9])", " ", local).strip() or member


def _evidence_id(ticker: str, filing: Mapping[str, Any], fact: Mapping[str, Any], dims: Mapping[str, str]) -> str:
    payload = {
        "ticker": ticker,
        "accession": filing.get("accession"),
        "concept": fact.get("concept"),
        "period": _period(fact),
        "dimensions": dict(sorted(dims.items())),
        "unit": _unit(fact),
    }
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:24]
    return f"segment-xbrl:{digest}"


def _normalize(fact: Mapping[str, Any], *, ticker: str, metric: str, dims: Mapping[str, str], filing: Mapping[str, Any]) -> dict[str, Any]:
    member = dims[REPORTABLE_SEGMENT_AXIS]
    return {
        "evidence_id": _evidence_id(ticker, filing, fact, dims),
        "ticker": ticker,
        "metric_key": metric,
        "concept": _text(fact.get("concept")),
        "label": _text(fact.get("label")),
        "segment_axis": REPORTABLE_SEGMENT_AXIS,
        "segment_member": member,
        "segment_label": _member_label(member, fact.get("label")),
        "value": fact.get("value"),
        "numeric_value": _number(fact.get("numeric_value")),
        "unit": _unit(fact),
        "unit_ref": _text(fact.get("unit_ref")),
        "currency": _text(fact.get("currency")),
        "decimals": fact.get("decimals"),
        **_period(fact),
        "fiscal_year": fact.get("fiscal_year"),
        "fiscal_period": _text(fact.get("fiscal_period")),
        "dimensions": dict(sorted(dims.items())),
        "form_type": _text(filing.get("form_type")),
        "filing_date": _iso(filing.get("filing_date")),
        "period_of_report": _iso(filing.get("period_of_report")),
        "accession": _text(filing.get("accession")),
        "cik": _text(filing.get("cik")),
        "primary_document": _text(filing.get("primary_document")),
        "statement_type": _text(fact.get("statement_type")),
        "statement_role": _text(fact.get("statement_role")),
        "context_ref": _text(fact.get("context_ref")),
        "xbrl_fact_id": _text(fact.get("fact_id")),
        "source": SEGMENT_EVIDENCE_SOURCE,
        "source_locator": _text(filing.get("source_locator")),
        "source_locator_type": _text(filing.get("source_locator_type")),
        "source_locator_detail": {
            "concept": _text(fact.get("concept")),
            "context_ref": _text(fact.get("context_ref")),
            "xbrl_fact_id": _text(fact.get("fact_id")),
        },
    }


def _half_unit(decimals: Any) -> float:
    try:
        result = 0.5 * (10.0 ** (-int(decimals)))
    except (TypeError, ValueError, OverflowError):
        return 0.0
    return result if math.isfinite(result) else 0.0


def _reconcile(metric: str, concepts: Sequence[str], rows: Sequence[dict[str, Any]], raw: Sequence[tuple[Mapping[str, Any], dict[str, str]]], filing: Mapping[str, Any]) -> list[dict[str, Any]]:
    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[(row["concept"], row["period_type"], row["period_start"], row["period_end"], row["period_instant"], row["unit"])].append(row)
    output = []
    for key, group in groups.items():
        concept, period_type, start, end, instant, unit = key
        by_member: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in group:
            by_member[row["segment_member"]].append(row)
        values, representatives, conflicts = {}, [], []
        for member, member_rows in sorted(by_member.items()):
            distinct = {float(row["numeric_value"]) for row in member_rows if row["numeric_value"] is not None}
            if len(distinct) != 1:
                conflicts.append(member)
            else:
                values[member] = next(iter(distinct))
                representatives.append(member_rows[0])
        consolidated = [
            fact for fact, dims in raw
            if not dims
            and _matches(fact.get("concept"), concepts)
            and _text(fact.get("concept")) == concept
            and _period_key(fact) == (period_type, start, end, instant)
            and _unit(fact) == unit
            and _number(fact.get("numeric_value")) is not None
        ]
        consolidated_values = {float(_number(fact.get("numeric_value"))) for fact in consolidated}
        total = consolidated_value = difference = tolerance = exact = None
        if conflicts:
            status = "segment_value_conflict"
        elif not consolidated_values:
            status = "consolidated_fact_unavailable"
        elif len(consolidated_values) > 1:
            status = "consolidated_value_ambiguous"
        else:
            total, consolidated_value = sum(values.values()), next(iter(consolidated_values))
            difference = total - consolidated_value
            tolerance = sum(_half_unit(row.get("decimals")) for row in representatives)
            tolerance += _half_unit(consolidated[0].get("decimals"))
            exact = difference == 0.0
            status = "tied" if exact else "tied_within_reported_rounding" if abs(difference) <= tolerance else "mismatch"
        output.append({
            "metric_key": metric,
            "concept": concept,
            "period": f"{start}/{end}" if start and end else instant or end or start,
            "period_type": period_type,
            "period_start": start,
            "period_end": end,
            "period_instant": instant,
            "unit": unit,
            "form_type": filing.get("form_type"),
            "filing_date": filing.get("filing_date"),
            "accession": filing.get("accession"),
            "source_locator": filing.get("source_locator"),
            "segment_count": len(values),
            "segment_members": sorted(values),
            "segment_values": values,
            "segment_total": total,
            "consolidated_value": consolidated_value,
            "difference": difference,
            "rounding_tolerance": tolerance,
            "exact_match": exact,
            "status": status,
            "conflicting_segment_members": conflicts,
            "segment_evidence_ids": sorted(row["evidence_id"] for row in group),
            "consolidated_fact_ids": sorted({_text(fact.get("fact_id")) for fact in consolidated} - {None}),
        })
    return sorted(output, key=lambda row: (row["metric_key"], row["period_end"] or row["period_instant"] or "", row["period_start"] or ""))


def _schedule(metric: str, rows: Sequence[dict[str, Any]], concepts: Sequence[str], reason: str | None = None) -> dict[str, Any]:
    return {
        "status": "available" if rows else "unavailable",
        "reason": None if rows else reason or _REASONS[metric],
        "requested_concepts": list(concepts),
        "row_count": len(rows),
        "rows": list(rows),
    }


def _apply_reconciliation_gate(
    schedule: dict[str, Any],
    reconciliations: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Fail a populated core schedule closed when any total does not tie.

    The underlying rows and reconciliation records remain intact for inspection;
    only the schedule's acceptance status changes.
    """
    if schedule["rows"] and any(
        item.get("status") not in _ACCEPTED_RECONCILIATION_STATUSES
        for item in reconciliations
    ):
        schedule["status"] = "unavailable"
        schedule["reason"] = _RECONCILIATION_FAILURE_REASON
    return schedule


def build_segment_evidence_from_inline_xbrl(*, ticker: str, facts: Iterable[Mapping[str, Any]], contexts: Mapping[str, Any], filing: Mapping[str, Any], kpi_concepts: Mapping[str, Sequence[str]] | None = None) -> dict[str, Any]:
    """Build one filing's schedules without network calls.

    KPI extraction is allowlist-only: issuer-specific concepts are never
    guessed to be KPIs in the deterministic ingestion layer.
    """
    ticker = str(ticker).upper().strip()
    raw = [(dict(fact), _fact_dimensions(fact, contexts)) for fact in facts if isinstance(fact, Mapping)]
    axis_concepts = sorted({
        _text(fact.get("concept")) for fact, dims in raw
        if REPORTABLE_SEGMENT_AXIS in dims and _text(fact.get("concept"))
    })
    schedules, reconciliations = {}, []
    for metric, concepts in _METRICS.items():
        rows = [
            _normalize(fact, ticker=ticker, metric=metric, dims=dims, filing=filing)
            for fact, dims in raw
            if REPORTABLE_SEGMENT_AXIS in dims and _matches(fact.get("concept"), concepts) and _number(fact.get("numeric_value")) is not None
        ]
        rows.sort(key=lambda row: (row["period_end"] or row["period_instant"] or "", row["period_start"] or "", row["segment_member"]))
        metric_reconciliations = _reconcile(metric, concepts, rows, raw, filing)
        schedules[metric] = _apply_reconciliation_gate(
            _schedule(metric, rows, concepts), metric_reconciliations
        )
        reconciliations.extend(metric_reconciliations)
    kpi_rows = []
    for kpi_key, concepts in sorted((kpi_concepts or {}).items()):
        kpi_rows.extend(
            _normalize(fact, ticker=ticker, metric=f"kpi:{kpi_key}", dims=dims, filing=filing)
            for fact, dims in raw
            if REPORTABLE_SEGMENT_AXIS in dims and _matches(fact.get("concept"), concepts) and _number(fact.get("numeric_value")) is not None
        )
    kpi_rows.sort(key=lambda row: (row["metric_key"], row["period_end"] or row["period_instant"] or "", row["segment_member"]))
    requested_kpis = sorted({concept for concepts in (kpi_concepts or {}).values() for concept in concepts})
    kpi_reason = "approved_kpi_concepts_not_disclosed_on_reportable_segment_axis" if kpi_concepts else _REASONS["kpis"]
    schedules["kpis"] = _schedule("kpis", kpi_rows, requested_kpis, kpi_reason)
    statuses = [schedules[key]["status"] for key in ("revenue", "operating_income", "assets", "kpis")]
    status = "ok" if all(value == "available" for value in statuses) else "partial" if any(value == "available" for value in statuses) else "unavailable"
    counts: dict[str, int] = defaultdict(int)
    for item in reconciliations:
        counts[item["status"]] += 1
    return {
        "ticker": ticker,
        "status": status,
        "source": SEGMENT_EVIDENCE_SOURCE,
        "segment_axis": REPORTABLE_SEGMENT_AXIS,
        "filing": dict(filing),
        "schedules": schedules,
        "reconciliations": reconciliations,
        "reconciliation_summary": dict(sorted(counts.items())),
        "coverage": {
            "segment_axis_concepts_present": axis_concepts,
            "requested_metrics": {key: schedules[key]["status"] for key in ("revenue", "operating_income", "assets", "kpis")},
        },
    }
