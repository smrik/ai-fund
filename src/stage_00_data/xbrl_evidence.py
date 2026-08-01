"""Structured SEC XBRL fact evidence with filing-level provenance.

This module is deliberately narrower than filing narrative retrieval.  XBRL is
used here for typed values, periods, dimensions, and filing vintage.  The filing
HTML remains the source for note prose, surrounding disclosure context, and
future exact inline-XBRL anchors.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
import hashlib
import json
import math
import os
from typing import Any, Iterable, Mapping

from . import edgar_client as _edgar_client


# Statement XBRL must enter edgartools through the same runtime boundary as
# narrative filing retrieval. Importing edgar directly here bypasses the SEC
# identity and workspace-local cache configured by edgar_client.
Company = _edgar_client.Company


XBRL_EVIDENCE_SOURCE = "sec_xbrl_companyfacts_v3"
XBRL_DERIVED_LTM_SOURCE = "sec_xbrl_derived_ltm_v1"


def _canonical_json_value(value: Any) -> Any:
    """Return a JSON-safe value whose representation is stable across runs."""

    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            return str(value)
        return value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {
            str(key): _canonical_json_value(value[key])
            for key in sorted(value, key=str)
        }
    if isinstance(value, (list, tuple)):
        return [_canonical_json_value(item) for item in value]
    return str(value)


def statement_fact_fingerprint(payload: Mapping[str, Any]) -> str:
    """Fingerprint a source fact without ingestion time or dictionary ordering."""

    canonical = _canonical_json_value(dict(payload))
    encoded = json.dumps(
        canonical,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


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


def _canonical_cik(value: Any) -> str | None:
    text = _text(value)
    if not text:
        return None
    try:
        return str(int(text)).zfill(10)
    except ValueError:
        return text


def _period_label(fact: Any) -> str | None:
    start = _iso(getattr(fact, "period_start", None))
    end = _iso(getattr(fact, "period_end", None))
    if start and end:
        return f"{start}/{end}"
    return end or start


def _currency_from_unit(unit: str | None) -> str | None:
    unit_text = _text(unit)
    if not unit_text:
        return None
    candidate = unit_text.split("/", 1)[0].split(":", 1)[-1].upper()
    return candidate if len(candidate) == 3 and candidate.isalpha() else None


def _canonical_statement_type(value: Any) -> str | None:
    text = _text(value)
    if not text:
        return None
    token = "".join(character for character in text.lower() if character.isalnum())
    if "cashflow" in token:
        return "CashFlowStatement"
    if "balance" in token or "financialposition" in token:
        return "BalanceSheet"
    if (
        "income" in token
        or "operation" in token
        or "profitandloss" in token
        or token == "profitloss"
    ):
        return "IncomeStatement"
    return None


def _period_kind(fact: Any) -> str:
    fiscal_period = (_text(getattr(fact, "fiscal_period", None)) or "").upper()
    form_type = (_text(getattr(fact, "form_type", None)) or "").upper()
    if fiscal_period == "FY" and form_type.startswith(("10-K", "20-F", "40-F")):
        return "annual"
    if form_type.startswith(("10-Q", "6-K")):
        return "interim"
    return "reported"


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
    entity_id = _canonical_cik(cik)
    period = _period_label(fact)
    accession = _text(getattr(fact, "accession", None))
    source_locator = _sec_filing_index_url(cik, accession)
    data_quality = getattr(fact, "data_quality", None)
    data_quality_value = getattr(data_quality, "value", data_quality)
    dimensions = getattr(fact, "dimensions", None) or {}
    unit = _text(getattr(fact, "unit", None))
    source_statement_type = _text(getattr(fact, "statement_type", None))
    statement = _canonical_statement_type(source_statement_type)
    concept = _text(getattr(fact, "concept", None)) or "unknown"
    label = _text(getattr(fact, "label", None))
    period_kind = _period_kind(fact)
    context = {
        "context_ref": _text(getattr(fact, "context_ref", None)),
        "semantic_tags": list(getattr(fact, "semantic_tags", None) or []),
        "business_context": _text(getattr(fact, "business_context", None)),
        "calculation_context": _text(
            getattr(fact, "calculation_context", None)
        ),
    }
    fiscal_calendar = {
        "fiscal_year": getattr(fact, "fiscal_year", None),
        "fiscal_period": _text(getattr(fact, "fiscal_period", None)),
        "period_start": _iso(getattr(fact, "period_start", None)),
        "period_end": _iso(getattr(fact, "period_end", None)),
    }

    metadata: dict[str, Any] = {
        "source": XBRL_EVIDENCE_SOURCE,
        "entity_id": entity_id,
        "taxonomy": _text(getattr(fact, "taxonomy", None)),
        "label": label,
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
        "context_ref": context["context_ref"],
        "semantic_tags": context["semantic_tags"],
        "business_context": context["business_context"],
        "calculation_context": context["calculation_context"],
        "dimensions": dict(dimensions),
        "statement_type": source_statement_type,
        "canonical_statement_type": statement,
        "line_item_sequence": getattr(fact, "line_item_sequence", None),
        "depth": getattr(fact, "depth", None),
        "parent_concept": _text(getattr(fact, "parent_concept", None)),
        "section": _text(getattr(fact, "section", None)),
        "is_abstract": getattr(fact, "is_abstract", None),
        "is_total": getattr(fact, "is_total", None),
        "presentation_order": getattr(fact, "presentation_order", None),
        "source_locator_type": "sec_filing_index" if source_locator else "missing",
    }

    record = {
        "fact_id": _fact_id(normalized_ticker, fact, period),
        "ticker": normalized_ticker,
        "entity_id": entity_id,
        "source": XBRL_EVIDENCE_SOURCE,
        "statement": statement,
        "concept": concept,
        "label": label,
        "fact_name": concept,
        "value": getattr(fact, "value", None),
        "numeric_value": getattr(fact, "numeric_value", None),
        "unit": unit,
        "currency": _currency_from_unit(unit),
        "scale": getattr(fact, "scale", None),
        # edgartools exposes ``numeric_value`` in base units already. Preserve
        # the reported XBRL scale above, but do not apply it a second time.
        "scale_factor": 1.0,
        "period": period,
        "period_kind": period_kind,
        "context": context,
        "fiscal_calendar": fiscal_calendar,
        "is_derived": False,
        "derivation": None,
        "source_locator": source_locator,
        "metadata": metadata,
    }
    fingerprint_payload = {
        key: value
        for key, value in record.items()
        if key not in {"fact_id", "ingestion_fingerprint"}
    }
    fingerprint = statement_fact_fingerprint(fingerprint_payload)
    record["fact_id"] = f"{record['fact_id']}:{fingerprint[:16]}"
    record["ingestion_fingerprint"] = fingerprint
    return record


def _annual_period_ends(
    records: Iterable[dict[str, Any]],
    *,
    max_periods: int,
) -> list[str]:
    primary_statements = {
        "IncomeStatement",
        "BalanceSheet",
        "CashFlowStatement",
    }
    duration_statements = {
        "IncomeStatement",
        "CashFlowStatement",
    }
    statements_by_end: dict[str, set[str]] = {}
    annual_duration_statements_by_end: dict[str, set[str]] = {}
    for record in records:
        if record.get("period_kind") != "annual":
            continue
        metadata = record.get("metadata") or {}
        dimensions = record.get("dimensions") or metadata.get("dimensions") or {}
        if dimensions:
            continue
        period_end = _text(record.get("period_end") or metadata.get("period_end"))
        statement = _text(record.get("statement"))
        if not period_end or statement not in primary_statements:
            continue
        statements_by_end.setdefault(period_end, set()).add(statement)
        period_type = _text(
            record.get("period_type") or metadata.get("period_type")
        )
        period_start = _date_value(
            record.get("period_start") or metadata.get("period_start")
        )
        end_date = _date_value(period_end)
        if (
            statement in duration_statements
            and (period_type or "").lower() == "duration"
            and period_start is not None
            and end_date is not None
            and 300 <= (end_date - period_start).days + 1 <= 400
        ):
            annual_duration_statements_by_end.setdefault(period_end, set()).add(
                statement
            )
    ends = {
        period_end
        for period_end, statements in statements_by_end.items()
        if statements
        and annual_duration_statements_by_end.get(period_end)
    }
    return sorted(ends, reverse=True)[: max(0, min(5, int(max_periods)))]


def _date_value(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = _text(value)
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _record_period_dates(
    record: Mapping[str, Any],
) -> tuple[date | None, date | None]:
    metadata = record.get("metadata") or {}
    return (
        _date_value(metadata.get("period_start")),
        _date_value(metadata.get("period_end")),
    )


def _ltm_identity(record: Mapping[str, Any]) -> tuple[Any, ...]:
    metadata = record.get("metadata") or {}
    dimensions = metadata.get("dimensions") or {}
    return (
        record.get("statement"),
        record.get("concept"),
        record.get("unit"),
        record.get("currency"),
        record.get("scale_factor", 1.0),
        json.dumps(
            _canonical_json_value(dimensions),
            sort_keys=True,
            separators=(",", ":"),
        ),
    )


def _latest_record(records: Iterable[dict[str, Any]]) -> dict[str, Any] | None:
    return max(
        records,
        key=lambda record: (
            str((record.get("metadata") or {}).get("filing_date") or ""),
            str((record.get("metadata") or {}).get("accession") or ""),
            str(record.get("ingestion_fingerprint") or ""),
        ),
        default=None,
    )


def _compatible_ltm_triple(
    current_ytd: dict[str, Any],
    annual: dict[str, Any],
    prior_ytd: dict[str, Any],
) -> bool:
    if not (
        _ltm_identity(current_ytd)
        == _ltm_identity(annual)
        == _ltm_identity(prior_ytd)
    ):
        return False
    if any(
        record.get("numeric_value") is None
        for record in (current_ytd, annual, prior_ytd)
    ):
        return False
    current_start, current_end = _record_period_dates(current_ytd)
    annual_start, annual_end = _record_period_dates(annual)
    prior_start, prior_end = _record_period_dates(prior_ytd)
    if None in {
        current_start,
        current_end,
        annual_start,
        annual_end,
        prior_start,
        prior_end,
    }:
        return False
    assert current_start and current_end and annual_start and annual_end
    assert prior_start and prior_end
    if not (prior_end < annual_end < current_end):
        return False
    if abs((current_start - (annual_end + timedelta(days=1))).days) > 14:
        return False
    if abs((prior_start - annual_start).days) > 14:
        return False
    current_days = (current_end - current_start).days
    prior_days = (prior_end - prior_start).days
    if abs(current_days - prior_days) > 14:
        return False
    current_fp = str(
        (current_ytd.get("metadata") or {}).get("fiscal_period") or ""
    ).upper()
    prior_fp = str(
        (prior_ytd.get("metadata") or {}).get("fiscal_period") or ""
    ).upper()
    return not current_fp or not prior_fp or current_fp == prior_fp


def _derive_ltm_fact(
    *,
    current_ytd: dict[str, Any],
    annual: dict[str, Any],
    prior_ytd: dict[str, Any],
) -> dict[str, Any]:
    _, current_end = _record_period_dates(current_ytd)
    _, prior_end = _record_period_dates(prior_ytd)
    assert current_end and prior_end
    ltm_start = prior_end + timedelta(days=1)
    numeric_value = (
        float(current_ytd["numeric_value"])
        + float(annual["numeric_value"])
        - float(prior_ytd["numeric_value"])
    )
    component_records = (current_ytd, annual, prior_ytd)
    derivation = {
        "formula": "current_ytd + prior_fy - prior_ytd",
        "component_fact_ids": [
            record["fact_id"] for record in component_records
        ],
        "component_fingerprints": [
            record["ingestion_fingerprint"] for record in component_records
        ],
        "component_source_locators": [
            record.get("source_locator") for record in component_records
        ],
    }
    current_metadata = dict(current_ytd.get("metadata") or {})
    metadata = {
        **current_metadata,
        "source": XBRL_DERIVED_LTM_SOURCE,
        "period_type": "duration",
        "period_start": ltm_start.isoformat(),
        "period_end": current_end.isoformat(),
        "fiscal_period": "LTM",
        "form_type": "DERIVED",
        "accession": None,
        "context_ref": f"LTM-{current_end.isoformat()}",
        "is_audited": False,
        "is_restated": False,
        "is_estimated": False,
        "source_locator_type": "derived_components",
    }
    context = {
        "context_ref": metadata["context_ref"],
        "semantic_tags": list(metadata.get("semantic_tags") or []),
        "business_context": metadata.get("business_context"),
        "calculation_context": metadata.get("calculation_context"),
    }
    fiscal_calendar = {
        "fiscal_year": metadata.get("fiscal_year"),
        "fiscal_period": "LTM",
        "period_start": ltm_start.isoformat(),
        "period_end": current_end.isoformat(),
    }
    record: dict[str, Any] = {
        "ticker": current_ytd["ticker"],
        "entity_id": current_ytd.get("entity_id"),
        "source": XBRL_DERIVED_LTM_SOURCE,
        "statement": current_ytd["statement"],
        "concept": current_ytd["concept"],
        "label": current_ytd.get("label"),
        "fact_name": current_ytd["concept"],
        "value": numeric_value,
        "numeric_value": numeric_value,
        "unit": current_ytd.get("unit"),
        "currency": current_ytd.get("currency"),
        "scale": current_ytd.get("scale"),
        "scale_factor": 1.0,
        "period": f"{ltm_start.isoformat()}/{current_end.isoformat()}",
        "period_kind": "ltm",
        "context": context,
        "fiscal_calendar": fiscal_calendar,
        "is_derived": True,
        "derivation": derivation,
        "source_locator": None,
        "metadata": metadata,
    }
    fingerprint_payload = {
        key: value
        for key, value in record.items()
        if key not in {"fact_id", "ingestion_fingerprint"}
    }
    fingerprint = statement_fact_fingerprint(fingerprint_payload)
    record["fact_id"] = (
        f"xbrl-ltm:{record['ticker']}:{record['concept']}:{fingerprint[:20]}"
    )
    record["ingestion_fingerprint"] = fingerprint
    return record


def _construct_ltm_facts(
    records: Iterable[dict[str, Any]],
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    str,
    dict[str, int],
]:
    all_records = list(records)
    annual_by_identity: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
    interim_by_identity: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
    for record in all_records:
        if record.get("statement") not in {
            "IncomeStatement",
            "CashFlowStatement",
        }:
            continue
        if (record.get("metadata") or {}).get("period_type") != "duration":
            continue
        target = (
            annual_by_identity
            if record.get("period_kind") == "annual"
            else interim_by_identity
            if record.get("period_kind") == "interim"
            else None
        )
        if target is not None:
            target.setdefault(_ltm_identity(record), []).append(record)

    derived: list[dict[str, Any]] = []
    components: dict[str, dict[str, Any]] = {}
    had_interim = any(interim_by_identity.values())
    attempted_identities = 0
    constructed_identities = 0
    for identity, interim_records in interim_by_identity.items():
        annual_records = annual_by_identity.get(identity) or []
        if not annual_records:
            continue
        end_groups: dict[str, list[dict[str, Any]]] = {}
        for record in interim_records:
            _, period_end = _record_period_dates(record)
            if period_end:
                end_groups.setdefault(period_end.isoformat(), []).append(record)
        if len(end_groups) < 2:
            continue
        attempted_identities += 1
        identity_constructed = False
        for current_end_key in sorted(end_groups, reverse=True):
            current_candidates = sorted(
                [
                    record
                    for record in end_groups[current_end_key]
                    if all(_record_period_dates(record))
                ],
                key=lambda record: (
                    (
                        (_record_period_dates(record)[1] or date.min)
                        - (_record_period_dates(record)[0] or date.min)
                    ).days,
                    str((record.get("metadata") or {}).get("filing_date") or ""),
                ),
                reverse=True,
            )
            for current_ytd in current_candidates:
                for annual_record in sorted(
                    annual_records,
                    key=lambda record: (
                        _record_period_dates(record)[1] or date.min,
                        str(
                            (record.get("metadata") or {}).get("filing_date")
                            or ""
                        ),
                    ),
                    reverse=True,
                ):
                    prior_candidates = [
                        record
                        for end_key, group in end_groups.items()
                        if end_key < current_end_key
                        for record in group
                        if _compatible_ltm_triple(
                            current_ytd,
                            annual_record,
                            record,
                        )
                    ]
                    prior_ytd = _latest_record(prior_candidates)
                    if prior_ytd is None:
                        continue
                    ltm = _derive_ltm_fact(
                        current_ytd=current_ytd,
                        annual=annual_record,
                        prior_ytd=prior_ytd,
                    )
                    derived.append(ltm)
                    for component in (
                        current_ytd,
                        annual_record,
                        prior_ytd,
                    ):
                        components[
                            component["ingestion_fingerprint"]
                        ] = component
                    identity_constructed = True
                    break
                if identity_constructed:
                    break
            if identity_constructed:
                break
        if identity_constructed:
            constructed_identities += 1
    status = (
        "constructed"
        if derived and constructed_identities == attempted_identities
        else "partial"
        if derived
        else "incompatible_components"
        if had_interim
        else "not_available"
    )
    return (
        derived,
        list(components.values()),
        status,
        {
            "attempted_identity_count": attempted_identities,
            "constructed_identity_count": constructed_identities,
            "derived_fact_count": len(derived),
            "component_fact_count": len(components),
        },
    )


def _deduplicate_records(
    records: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for record in records:
        fingerprint = record["ingestion_fingerprint"]
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        out.append(record)
    return sorted(
        out,
        key=lambda record: (
            str(record.get("statement") or ""),
            str((record.get("metadata") or {}).get("period_end") or ""),
            str((record.get("metadata") or {}).get("period_start") or ""),
            float(
                (record.get("metadata") or {}).get("presentation_order")
                or 0.0
            ),
            str(record.get("concept") or ""),
            json.dumps(
                _canonical_json_value(
                    (record.get("metadata") or {}).get("dimensions") or {}
                ),
                sort_keys=True,
                separators=(",", ":"),
            ),
            str((record.get("metadata") or {}).get("filing_date") or ""),
            str((record.get("metadata") or {}).get("accession") or ""),
            str(record.get("ingestion_fingerprint") or ""),
        ),
    )


def get_xbrl_statement_evidence(
    ticker: str,
    *,
    max_annual_periods: int = 5,
    include_ltm: bool = True,
    evidence_cutoff: str | None = None,
    source_run_id: int | str | None = None,
) -> dict[str, Any]:
    """Return primary statements proven by accession-level presentation trees.

    The statement-ledger path deliberately differs from concept lookup below:
    it calls ``Filing.xbrl()`` for each selected accession so presentation and
    calculation linkbases, contexts, and dimensional membership remain bound
    to the source filing.
    """

    from .filing_presentation import get_filing_presentation_evidence

    return get_filing_presentation_evidence(
        ticker,
        max_annual_periods=max_annual_periods,
        include_ltm=include_ltm,
        evidence_cutoff=evidence_cutoff,
        source_run_id=source_run_id,
        company_factory=Company,
    )


def persist_xbrl_statement_evidence(
    conn: Any,
    ticker: str,
    *,
    max_annual_periods: int = 5,
    include_ltm: bool = True,
    evidence_cutoff: str | None = None,
    source_run_id: int | str | None = None,
) -> dict[str, Any]:
    """Retrieve and append the selected statement payload to the fact ledger."""

    result = get_xbrl_statement_evidence(
        ticker,
        max_annual_periods=max_annual_periods,
        include_ltm=include_ltm,
        evidence_cutoff=evidence_cutoff,
        source_run_id=source_run_id,
    )
    records = list(result.get("facts") or [])
    inserted_count = 0
    if records:
        from db.loader import insert_statement_facts

        inserted_count = insert_statement_facts(conn, records)
    manifest_ids: list[str] = []
    manifests = list(result.get("coverage_manifests") or [])
    if manifests:
        from src.stage_04_pipeline.statement_reconciliation_store import (
            persist_statement_source_manifest,
        )

        for manifest in manifests:
            manifest_ids.append(
                persist_statement_source_manifest(
                    conn,
                    manifest,
                    source_run_id=source_run_id,
                    evidence_cutoff=evidence_cutoff,
                )
            )
    return {
        **result,
        "inserted_count": inserted_count,
        "manifest_ids": manifest_ids,
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
    "XBRL_DERIVED_LTM_SOURCE",
    "XBRL_EVIDENCE_SOURCE",
    "get_xbrl_fact_evidence",
    "get_xbrl_statement_evidence",
    "normalize_financial_fact",
    "persist_xbrl_statement_evidence",
    "statement_fact_fingerprint",
]
