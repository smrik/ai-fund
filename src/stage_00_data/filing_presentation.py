"""Accession-specific SEC filing presentation evidence.

This module extracts ledger-ready facts from a filing's presentation and
calculation linkbases.  Company Facts remain useful for discovery, but they
cannot prove that a line was presented on a particular consolidated statement.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
import hashlib
import json
from typing import Any, Iterable, Mapping, Sequence
from urllib.parse import quote

from . import edgar_client as _edgar_client
from .source_reconciliation import (
    LTM_REQUIRED_CANONICAL_KEYS,
    canonical_statement_key,
)
from .xbrl_evidence import _ltm_identity, statement_fact_fingerprint


Company = _edgar_client.Company


FILING_PRESENTATION_SOURCE = "sec_xbrl_filing_presentation_v1"
COVERAGE_CONTRACT_VERSION = "statement_coverage_manifest.v1"

_PRIMARY_STATEMENTS = {
    "IncomeStatement",
    "BalanceSheet",
    "CashFlowStatement",
}
_ANNUAL_FORMS = {"10-K", "20-F", "40-F"}


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    text = str(value).strip()
    return text or None


def _record_dimensions(record: Mapping[str, Any]) -> dict[str, Any]:
    """Dimensions live under metadata for derived records and inline for presented ones."""

    inline = _mapping(record.get("dimensions"))
    if inline:
        return inline
    return _mapping(_mapping(record.get("metadata")).get("dimensions"))


def resolve_ltm_status(
    *,
    annual_records: Sequence[Mapping[str, Any]],
    derived_ltm: Sequence[Mapping[str, Any]],
    annual_component_ends: Any,
) -> tuple[str, set[tuple[Any, ...]], set[tuple[Any, ...]]]:
    """Decide whether an LTM window is usable, and expose the identity gap.

    Two settled PM decisions govern this rule:

    * **Decision 7** — dimensioned facts do not enter the consolidated view
      implicitly, so a segment or product breakdown must never gate LTM readiness.
    * **Decision 6** — LTM is built only from *period-compatible* facts. Sparse
      cash-flow items (impairments, debt restructuring costs) legitimately cannot
      be quarterly-differenced, so readiness is measured against
      ``LTM_REQUIRED_CANONICAL_KEYS`` rather than against every presented line.

    Requiring exact set equality over every presented concept blocked whole
    tickers on immaterial lines: MSFT constructed 74 of 91 identities and CALM 38
    of 120, and both were reported as unusable sources.

    Returns ``(status, expected_identities, constructed_identities)`` so callers
    can report the residual gap even when the window is usable.
    """

    component_ends = set(annual_component_ends or ())
    expected_identities = {
        _ltm_identity(record)
        for record in annual_records
        if record.get("statement") in {"IncomeStatement", "CashFlowStatement"}
        and record.get("period_type") == "duration"
        and str(record.get("period_end") or "") in component_ends
        and not _record_dimensions(record)
    }
    constructed_identities = {
        _ltm_identity(record)
        for record in derived_ltm
        if not _record_dimensions(record)
    }
    def _keys(records: Sequence[Mapping[str, Any]]) -> set[str]:
        return {
            canonical_statement_key(
                str(record.get("concept") or ""),
                str(record.get("label") or ""),
            )
            for record in records
            if not _record_dimensions(record)
        }

    # Scope the requirement to keys this source actually presents annually. A source
    # that never reports D&A is not "partial" for failing to build an LTM D&A — that
    # gap belongs to annual coverage, which tests it directly. What LTM readiness
    # must guarantee is that nothing the source *does* report annually and that a
    # valuation *needs* silently went missing from the trailing window.
    annual_records_in_window = [
        record
        for record in annual_records
        if str(record.get("period_end") or "") in component_ends
    ]
    required_present = LTM_REQUIRED_CANONICAL_KEYS & _keys(annual_records_in_window)
    missing_required = required_present - _keys(derived_ltm)
    status = (
        "constructed"
        if expected_identities and not missing_required
        else "partial"
    )
    return status, expected_identities, constructed_identities


def _mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    return {}


def _get(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _canonical_json(payload: Mapping[str, Any]) -> str:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=str,
    )


def _hash_id(prefix: str, payload: Mapping[str, Any]) -> str:
    digest = hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()
    return f"{prefix}:{digest}"


def _accession(filing: Any) -> str | None:
    return _text(
        _get(filing, "accession_no")
        or _get(filing, "accession_number")
        or _get(filing, "accession")
    )


def _filing_date(filing: Any) -> str | None:
    return _iso(_get(filing, "filing_date"))


def _filing_form(filing: Any) -> str | None:
    return _text(_get(filing, "form"))


def _entity_id(filing: Any, xbrl: Any) -> str | None:
    entity_info = _mapping(_get(xbrl, "entity_info"))
    identifier = _text(
        entity_info.get("identifier")
        or entity_info.get("entity_identifier")
        or _get(filing, "cik")
    )
    if identifier and identifier.isdigit():
        return identifier.zfill(10)
    return identifier


def _filing_homepage(filing: Any) -> str | None:
    return _text(
        _get(filing, "homepage_url")
        or _get(filing, "filing_url")
        or _get(filing, "url")
    )


def _source_locator(
    filing: Any,
    *,
    statement_role: str,
    concept: str | None = None,
    context_ref: str | None = None,
) -> str | None:
    homepage = _filing_homepage(filing)
    if not homepage:
        return None
    fragments = [f"role={quote(statement_role, safe='')}"]
    if concept:
        fragments.append(f"concept={quote(concept, safe='')}")
    if context_ref:
        fragments.append(f"context={quote(context_ref, safe='')}")
    return f"{homepage}#xbrl-{'&'.join(fragments)}"


def _statement_roles(xbrl: Any) -> dict[str, str]:
    roles: dict[str, str] = {}
    getter = _get(xbrl, "get_all_statements")
    statements_value = getter() if callable(getter) else []
    statements = (
        list(statements_value)
        if isinstance(statements_value, Iterable)
        and not isinstance(statements_value, (str, bytes))
        else []
    )
    for statement in statements:
        role = _text(_get(statement, "role"))
        statement_type = _text(
            _get(statement, "type") or _get(statement, "statement_type")
        )
        definition = (_text(_get(statement, "definition")) or "").lower()
        if (
            role
            and statement_type in _PRIMARY_STATEMENTS
            and "parenthetical" not in definition
        ):
            roles[role] = statement_type
    return roles


def _presentation_occurrences(tree: Any) -> list[dict[str, Any]]:
    nodes = _mapping(_get(tree, "all_nodes"))
    root_id = _text(_get(tree, "root_element_id"))
    if not root_id or root_id not in nodes:
        return []

    occurrences: list[dict[str, Any]] = []

    def walk(
        element_id: str,
        *,
        path: tuple[str, ...],
        sibling_path: tuple[int, ...],
        preferred_label: str | None,
    ) -> None:
        if element_id not in nodes or len(path) > len(nodes) + 4:
            return
        node = nodes[element_id]
        current_path = (*path, element_id)
        occurrence_payload = {
            "path": list(current_path),
            "sibling_path": list(sibling_path),
            "preferred_label": preferred_label,
        }
        occurrences.append(
            {
                "element_id": element_id,
                "node": node,
                "path": list(current_path),
                "sibling_path": list(sibling_path),
                "preferred_label": preferred_label,
                "occurrence_id": _hash_id(
                    "presentation-occurrence",
                    occurrence_payload,
                ),
            }
        )
        children = list(_get(node, "children") or [])
        child_labels = list(_get(node, "child_preferred_labels") or [])
        for sibling_index, child_id_value in enumerate(children):
            child_id = str(child_id_value)
            child_label = (
                _text(child_labels[sibling_index])
                if sibling_index < len(child_labels)
                else None
            )
            walk(
                child_id,
                path=current_path,
                sibling_path=(*sibling_path, sibling_index),
                preferred_label=child_label,
            )

    walk(root_id, path=(), sibling_path=(), preferred_label=None)
    return occurrences


def _concept_key(value: Any) -> str:
    return str(value or "").replace(":", "_")


def _raw_facts(xbrl: Any) -> list[Any]:
    parser = _get(xbrl, "parser")
    facts = _get(parser, "facts") if parser is not None else None
    if facts is None:
        facts = _get(xbrl, "facts")
    if isinstance(facts, Mapping):
        return list(facts.values())
    if isinstance(facts, Iterable) and not isinstance(facts, (str, bytes)):
        return list(facts)
    return []


def _contexts(xbrl: Any) -> dict[str, Any]:
    contexts = _get(xbrl, "contexts")
    if isinstance(contexts, Mapping):
        return {str(key): value for key, value in contexts.items()}
    parser = _get(xbrl, "parser")
    contexts = _get(parser, "contexts") if parser is not None else None
    if isinstance(contexts, Mapping):
        return {str(key): value for key, value in contexts.items()}
    return {}


def _units(xbrl: Any) -> dict[str, Any]:
    units = _get(xbrl, "units")
    if isinstance(units, Mapping):
        return {str(key): value for key, value in units.items()}
    parser = _get(xbrl, "parser")
    units = _get(parser, "units") if parser is not None else None
    if isinstance(units, Mapping):
        return {str(key): value for key, value in units.items()}
    return {}


def _unit_name(unit_ref: str | None, units: Mapping[str, Any]) -> str | None:
    if not unit_ref:
        return None
    definition = _mapping(units.get(unit_ref))
    if definition.get("type") == "simple":
        measure = _text(definition.get("measure"))
        if measure:
            return measure.split(":", 1)[-1]
    if definition.get("type") == "divide":
        numerator = [
            str(value).split(":", 1)[-1] for value in definition.get("numerator") or []
        ]
        denominator = [
            str(value).split(":", 1)[-1]
            for value in definition.get("denominator") or []
        ]
        if numerator and denominator:
            return f"{'*'.join(numerator)}/{'*'.join(denominator)}"
    return unit_ref.split(":", 1)[-1]


def _currency(unit: str | None) -> str | None:
    if not unit:
        return None
    head = unit.split("/", 1)[0].split("*", 1)[0].upper()
    return head if len(head) == 3 and head.isalpha() else None


def _period(context: Any) -> tuple[str | None, str | None, str | None]:
    period = _mapping(_get(context, "period"))
    period_type = _text(period.get("type"))
    if period_type == "instant":
        instant = _iso(period.get("instant"))
        return None, instant, "instant"
    if period_type == "duration":
        return (
            _iso(period.get("startDate") or period.get("start_date")),
            _iso(period.get("endDate") or period.get("end_date")),
            "duration",
        )
    return None, None, period_type


def _period_label(
    period_start: str | None,
    period_end: str | None,
) -> str | None:
    if period_start and period_end:
        return f"{period_start}/{period_end}"
    return period_end


def _period_kind(filing: Any) -> str:
    form = (_filing_form(filing) or "").upper()
    return "annual" if form in _ANNUAL_FORMS else "interim"


def _fact_records(
    filing: Any,
    *,
    ticker: str,
    xbrl: Any,
    roles: Mapping[str, str],
    source_run_id: int | str | None,
) -> list[dict[str, Any]]:
    contexts = _contexts(xbrl)
    units = _units(xbrl)
    facts_by_concept: dict[str, list[Any]] = defaultdict(list)
    for raw_fact in _raw_facts(xbrl):
        facts_by_concept[_concept_key(_get(raw_fact, "element_id"))].append(raw_fact)
    for concept_facts in facts_by_concept.values():
        concept_facts.sort(
            key=lambda fact: (
                str(_get(fact, "context_ref") or ""),
                str(_get(fact, "fact_id") or ""),
                str(_get(fact, "instance_id") or ""),
                str(_get(fact, "unit_ref") or ""),
                str(_get(fact, "value") or ""),
            )
        )

    accession = _accession(filing)
    filing_date = _filing_date(filing)
    form_type = _filing_form(filing)
    entity_id = _entity_id(filing, xbrl)
    entity_info = _mapping(_get(xbrl, "entity_info"))
    presentation_trees = _mapping(_get(xbrl, "presentation_trees"))
    records: list[dict[str, Any]] = []
    line_sequence = 0

    for statement_role, statement in sorted(roles.items()):
        tree = presentation_trees.get(statement_role)
        if tree is None:
            continue
        definition = _text(_get(tree, "definition"))
        for occurrence in _presentation_occurrences(tree):
            line_sequence += 1
            concept = str(occurrence["element_id"])
            node = occurrence["node"]
            for raw_fact in facts_by_concept.get(_concept_key(concept), []):
                context_ref = _text(_get(raw_fact, "context_ref"))
                context_model = contexts.get(context_ref or "")
                if context_model is None:
                    continue
                dimensions = {
                    str(key): str(value)
                    for key, value in sorted(
                        _mapping(_get(context_model, "dimensions")).items()
                    )
                }
                period_start, period_end, period_type = _period(context_model)
                if not period_end:
                    continue
                unit_ref = _text(_get(raw_fact, "unit_ref"))
                unit = _unit_name(unit_ref, units)
                currency = _currency(unit)
                label = (
                    _text(_get(node, "display_label"))
                    or _text(_get(node, "standard_label"))
                    or concept
                )
                hierarchy = {
                    "statement_role": statement_role,
                    "statement_definition": definition,
                    "presentation_path": list(occurrence["path"]),
                    "presentation_sibling_path": list(occurrence["sibling_path"]),
                    "presentation_occurrence_id": occurrence["occurrence_id"],
                    "preferred_label": occurrence["preferred_label"]
                    or _text(_get(node, "preferred_label")),
                    "line_item_sequence": line_sequence,
                    "depth": int(_get(node, "depth", len(occurrence["path"]) - 1)),
                    "parent_concept": _text(_get(node, "parent")),
                    "section": definition,
                    "is_abstract": bool(_get(node, "is_abstract", False)),
                    "is_total": None,
                    "presentation_order": _get(node, "order"),
                    "consolidated_view_eligible": not bool(dimensions),
                }
                context = {
                    "context_ref": context_ref,
                    "entity": _mapping(_get(context_model, "entity")),
                    "period": _mapping(_get(context_model, "period")),
                    "dimensions": dimensions,
                }
                fiscal_year = (
                    entity_info.get("fiscal_year")
                    if period_end
                    == _iso(
                        entity_info.get("document_period_end_date")
                        or entity_info.get("reporting_end_date")
                    )
                    else int(period_end[:4])
                    if period_end[:4].isdigit()
                    else None
                )
                if fiscal_year is None:
                    fiscal_year = entity_info.get("fiscal_year")
                fiscal_period = (
                    "FY"
                    if _period_kind(filing) == "annual"
                    else _text(entity_info.get("fiscal_period"))
                )
                fiscal_calendar = {
                    "fiscal_year": fiscal_year,
                    "fiscal_period": fiscal_period,
                    "period_start": period_start,
                    "period_end": period_end,
                }
                source_locator = _source_locator(
                    filing,
                    statement_role=statement_role,
                    concept=concept,
                    context_ref=context_ref,
                )
                metadata = {
                    "source": FILING_PRESENTATION_SOURCE,
                    "entity_id": entity_id,
                    "label": label,
                    "scale": None,
                    "decimals": _get(raw_fact, "decimals"),
                    "unit_ref": unit_ref,
                    "period_type": period_type,
                    "period_start": period_start,
                    "period_end": period_end,
                    "fiscal_year": fiscal_year,
                    "fiscal_period": fiscal_period,
                    "filing_date": filing_date,
                    "form_type": form_type,
                    "accession": accession,
                    "context_ref": context_ref,
                    "dimensions": dimensions,
                    "statement_type": statement,
                    "canonical_statement_type": statement,
                    "source_fact_id": _text(_get(raw_fact, "fact_id")),
                    "source_fact_instance_id": _get(raw_fact, "instance_id"),
                    "source_locator_type": (
                        "sec_filing_presentation" if source_locator else "missing"
                    ),
                    **hierarchy,
                }
                record: dict[str, Any] = {
                    "ticker": ticker,
                    "entity_id": entity_id,
                    "source": FILING_PRESENTATION_SOURCE,
                    "source_run_id": source_run_id,
                    "statement": statement,
                    "concept": concept,
                    "label": label,
                    "fact_name": concept,
                    "value": _get(raw_fact, "value"),
                    "numeric_value": _get(raw_fact, "numeric_value"),
                    "unit": unit,
                    "currency": currency,
                    "scale": None,
                    "scale_factor": 1.0,
                    "period": _period_label(period_start, period_end),
                    "period_kind": _period_kind(filing),
                    "period_type": period_type,
                    "period_start": period_start,
                    "period_end": period_end,
                    "fiscal_year": fiscal_year,
                    "fiscal_period": fiscal_period,
                    "filing_date": filing_date,
                    "form_type": form_type,
                    "accession": accession,
                    "context_ref": context_ref,
                    "context": context,
                    "fiscal_calendar": fiscal_calendar,
                    "dimensions": dimensions,
                    "hierarchy": hierarchy,
                    "is_derived": False,
                    "derivation": None,
                    "source_locator": source_locator,
                    "metadata": metadata,
                }
                fingerprint = statement_fact_fingerprint(
                    {
                        key: value
                        for key, value in record.items()
                        if key != "source_run_id"
                    }
                )
                record["ingestion_fingerprint"] = fingerprint
                record["fact_id"] = (
                    f"xbrl-presentation:{ticker}:{accession or 'unknown'}:"
                    f"{fingerprint[:24]}"
                )
                records.append(record)

    unique = {record["ingestion_fingerprint"]: record for record in records}
    return sorted(
        unique.values(),
        key=lambda record: (
            str((record.get("hierarchy") or {}).get("statement_role") or ""),
            tuple(
                (record.get("hierarchy") or {}).get("presentation_sibling_path") or []
            ),
            str(record.get("period_end") or ""),
            str(record.get("period_start") or ""),
            str(record.get("context_ref") or ""),
            str(record.get("fact_id") or ""),
        ),
    )


def _calculation_edges(
    filing: Any,
    *,
    xbrl: Any,
    roles: Mapping[str, str],
) -> list[dict[str, Any]]:
    calculation_trees = _mapping(_get(xbrl, "calculation_trees"))
    edges: list[dict[str, Any]] = []
    for statement_role in sorted(roles):
        tree = calculation_trees.get(statement_role)
        if tree is None:
            continue
        nodes = _mapping(_get(tree, "all_nodes"))
        for child_key, node in sorted(nodes.items(), key=lambda item: str(item[0])):
            parent = _text(_get(node, "parent"))
            child = _text(_get(node, "element_id")) or str(child_key)
            if not parent:
                continue
            edge_payload = {
                "statement_role": statement_role,
                "parent_concept": parent,
                "child_concept": child,
                "weight": _get(node, "weight"),
                "order": _get(node, "order"),
            }
            edges.append(
                {
                    "edge_id": _hash_id("calculation-edge", edge_payload),
                    **edge_payload,
                    "source_locator": _source_locator(
                        filing,
                        statement_role=statement_role,
                        concept=child,
                    ),
                }
            )
    return edges


def _coverage_entries(
    facts: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    grouped: dict[tuple[Any, ...], list[Mapping[str, Any]]] = defaultdict(list)
    for fact in facts:
        hierarchy = _mapping(fact.get("hierarchy"))
        key = (
            hierarchy.get("statement_role"),
            fact.get("statement"),
            fact.get("period_start"),
            fact.get("period_end"),
            fact.get("period_type"),
            fact.get("period_kind"),
        )
        grouped[key].append(fact)

    entries: list[dict[str, Any]] = []
    for key, grouped_facts in sorted(
        grouped.items(),
        key=lambda item: tuple(str(value or "") for value in item[0]),
    ):
        (
            statement_role,
            statement,
            period_start,
            period_end,
            period_type,
            period_kind,
        ) = key
        consolidated = sorted(
            str(fact["fact_id"])
            for fact in grouped_facts
            if not _mapping(fact.get("dimensions"))
        )
        dimensioned = sorted(
            str(fact["fact_id"])
            for fact in grouped_facts
            if _mapping(fact.get("dimensions"))
        )
        entry_payload = {
            "statement_role": statement_role,
            "statement": statement,
            "canonical_roles": [statement],
            "period_start": period_start,
            "period_end": period_end,
            "period_type": period_type,
            "period_kind": period_kind,
            "units": sorted(
                {str(fact["unit"]) for fact in grouped_facts if fact.get("unit")}
            ),
            "currencies": sorted(
                {
                    str(fact["currency"])
                    for fact in grouped_facts
                    if fact.get("currency")
                }
            ),
            "presented_fact_ids": sorted([*consolidated, *dimensioned]),
            "consolidated_fact_ids": consolidated,
            "dimensioned_fact_ids": dimensioned,
        }
        entries.append(
            {
                "coverage_key": _hash_id("statement-coverage", entry_payload),
                **entry_payload,
            }
        )
    return entries


def _manifest(
    filing: Any,
    *,
    ticker: str,
    source_run_id: int | str | None,
    status: str,
    evidence_cutoff: str | None,
    facts: Iterable[Mapping[str, Any]],
    calculation_edges: list[dict[str, Any]],
) -> dict[str, Any]:
    entries = _coverage_entries(facts)
    payload: dict[str, Any] = {
        "contract_version": COVERAGE_CONTRACT_VERSION,
        "ticker": ticker,
        "source": FILING_PRESENTATION_SOURCE,
        "accession": _accession(filing),
        "source_run_id": source_run_id,
        "status": status,
        "filing_date": _filing_date(filing),
        "evidence_cutoff": evidence_cutoff or _filing_date(filing),
        "coverage": {
            "entries": entries,
            "entry_count": len(entries),
        },
        "calculation_edges": calculation_edges,
        "calculation_edge_count": len(calculation_edges),
    }
    manifest_hash = hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()
    return {
        "manifest_id": f"sha256:{manifest_hash}",
        "manifest_hash": manifest_hash,
        **payload,
    }


def extract_filing_presentation(
    filing: Any,
    *,
    ticker: str,
    evidence_cutoff: str | None = None,
    source_run_id: int | str | None = None,
) -> dict[str, Any]:
    """Extract every fact attached to a primary statement presentation role."""

    normalized_ticker = str(ticker).upper().strip()
    try:
        xbrl = filing.xbrl()
    except Exception as exc:
        xbrl = None
        error = str(exc)
    else:
        error = None

    if xbrl is None:
        manifest = _manifest(
            filing,
            ticker=normalized_ticker,
            source_run_id=source_run_id,
            status="failed",
            evidence_cutoff=evidence_cutoff,
            facts=[],
            calculation_edges=[],
        )
        return {
            "ticker": normalized_ticker,
            "source": FILING_PRESENTATION_SOURCE,
            "accession": _accession(filing),
            "status": "failed",
            "facts": [],
            "fact_count": 0,
            "coverage_manifest": manifest,
            "errors": [error or "filing has no XBRL presentation"],
        }

    try:
        roles = _statement_roles(xbrl)
        facts = _fact_records(
            filing,
            ticker=normalized_ticker,
            xbrl=xbrl,
            roles=roles,
            source_run_id=source_run_id,
        )
        calculation_edges = _calculation_edges(
            filing,
            xbrl=xbrl,
            roles=roles,
        )
    except Exception as exc:
        manifest = _manifest(
            filing,
            ticker=normalized_ticker,
            source_run_id=source_run_id,
            status="failed",
            evidence_cutoff=evidence_cutoff,
            facts=[],
            calculation_edges=[],
        )
        return {
            "ticker": normalized_ticker,
            "source": FILING_PRESENTATION_SOURCE,
            "accession": _accession(filing),
            "status": "failed",
            "facts": [],
            "fact_count": 0,
            "coverage_manifest": manifest,
            "errors": [str(exc)],
        }
    covered_statements = {
        fact["statement"] for fact in facts if not _mapping(fact.get("dimensions"))
    }
    status = (
        "completed"
        if covered_statements == _PRIMARY_STATEMENTS
        else "partial"
        if facts
        else "failed"
    )
    manifest = _manifest(
        filing,
        ticker=normalized_ticker,
        source_run_id=source_run_id,
        status=status,
        evidence_cutoff=evidence_cutoff,
        facts=facts,
        calculation_edges=calculation_edges,
    )
    return {
        "ticker": normalized_ticker,
        "source": FILING_PRESENTATION_SOURCE,
        "accession": _accession(filing),
        "status": status,
        "facts": facts,
        "fact_count": len(facts),
        "coverage_manifest": manifest,
        "errors": [],
    }


def _take_filings(
    filings: Any,
    limit: int,
    *,
    evidence_cutoff: str | None,
) -> list[Any]:
    if filings is None or limit <= 0:
        return []
    head = _get(filings, "head")
    selected = (
        filings if evidence_cutoff else head(limit) if callable(head) else filings
    )
    values = (
        list(selected)
        if isinstance(selected, Iterable) and not isinstance(selected, (str, bytes))
        else []
    )
    cutoff_date = (evidence_cutoff or "")[:10]
    if cutoff_date:
        values = [
            filing
            for filing in values
            if (_filing_date(filing) or "")[:10] <= cutoff_date and _filing_date(filing)
        ]
    unique: dict[str, Any] = {}
    for filing in values:
        accession = _accession(filing)
        if accession:
            unique[accession] = filing
    return sorted(
        unique.values(),
        key=lambda filing: (
            _filing_date(filing) or "",
            _accession(filing) or "",
        ),
        reverse=True,
    )[:limit]


def _company_filings(
    company: Any,
    *,
    forms: list[str],
    limit: int,
    evidence_cutoff: str | None,
) -> list[Any]:
    query = {
        "form": forms,
        "amendments": False,
        "is_xbrl": True,
        "sort_by": [("filing_date", "descending")],
        # The SEC's recent-submissions payload normally covers the bounded
        # five-year window. Avoid archive pagination for every universe ticker.
        "trigger_full_load": False,
    }
    if evidence_cutoff:
        query["filing_date"] = ("1900-01-01", evidence_cutoff[:10])
    filings = company.get_filings(
        **query,
    )
    return _take_filings(
        filings,
        limit,
        evidence_cutoff=evidence_cutoff,
    )


def _normalize_derived_fact(record: dict[str, Any]) -> dict[str, Any]:
    metadata = _mapping(record.get("metadata"))
    dimensions = _mapping(metadata.get("dimensions"))
    hierarchy = {
        key: metadata[key]
        for key in (
            "statement_role",
            "statement_definition",
            "presentation_path",
            "presentation_sibling_path",
            "presentation_occurrence_id",
            "preferred_label",
            "line_item_sequence",
            "depth",
            "parent_concept",
            "section",
            "is_abstract",
            "is_total",
            "presentation_order",
            "consolidated_view_eligible",
        )
        if key in metadata
    }
    normalized = {
        **record,
        "period_type": metadata.get("period_type"),
        "period_start": metadata.get("period_start"),
        "period_end": metadata.get("period_end"),
        "fiscal_year": metadata.get("fiscal_year"),
        "fiscal_period": metadata.get("fiscal_period"),
        "filing_date": metadata.get("filing_date"),
        "form_type": metadata.get("form_type"),
        "accession": metadata.get("accession"),
        "context_ref": metadata.get("context_ref"),
        "dimensions": dimensions,
        "hierarchy": hierarchy,
    }
    return normalized


def _selected_manifests(
    extractions: Iterable[tuple[Any, Mapping[str, Any]]],
    *,
    ticker: str,
    selected_facts: Iterable[Mapping[str, Any]],
    evidence_cutoff: str | None,
    source_run_id: int | str | None,
) -> list[dict[str, Any]]:
    selected_ids = {
        str(fact["fact_id"])
        for fact in selected_facts
        if fact.get("fact_id") and not fact.get("is_derived")
    }
    manifests: list[dict[str, Any]] = []
    for filing, extraction in extractions:
        facts = [
            fact
            for fact in extraction.get("facts") or []
            if str(fact.get("fact_id")) in selected_ids
        ]
        if not facts:
            continue
        covered_statements = {
            fact.get("statement")
            for fact in facts
            if not _mapping(fact.get("dimensions"))
        }
        status = "completed" if covered_statements == _PRIMARY_STATEMENTS else "partial"
        original_manifest = _mapping(extraction.get("coverage_manifest"))
        manifests.append(
            _manifest(
                filing,
                ticker=ticker,
                source_run_id=source_run_id,
                status=status,
                evidence_cutoff=evidence_cutoff,
                facts=facts,
                calculation_edges=list(
                    original_manifest.get("calculation_edges") or []
                ),
            )
        )
    return sorted(
        manifests,
        key=lambda manifest: (
            str(manifest.get("filing_date") or ""),
            str(manifest.get("accession") or ""),
        ),
        reverse=True,
    )


def get_filing_presentation_evidence(
    ticker: str,
    *,
    max_annual_periods: int = 5,
    include_ltm: bool = True,
    evidence_cutoff: str | None = None,
    source_run_id: int | str | None = None,
    company_factory: Any = Company,
) -> dict[str, Any]:
    """Build a bounded statement ledger from accession-specific filings."""

    from .xbrl_evidence import (
        _annual_period_ends,
        _construct_ltm_facts,
    )

    normalized_ticker = str(ticker).upper().strip()
    max_periods = max(0, min(5, int(max_annual_periods)))
    try:
        company = company_factory(normalized_ticker)
        annual_filings = _company_filings(
            company,
            forms=["10-K", "20-F", "40-F"],
            limit=max_periods,
            evidence_cutoff=evidence_cutoff,
        )
        interim_filings = (
            _company_filings(
                company,
                forms=["10-Q"],
                limit=5,
                evidence_cutoff=evidence_cutoff,
            )
            if include_ltm
            else []
        )
    except Exception as exc:
        return {
            "ticker": normalized_ticker,
            "source": FILING_PRESENTATION_SOURCE,
            "status": "failed",
            "facts": [],
            "fact_count": 0,
            "annual_periods": [],
            "ltm_status": ("not_requested" if not include_ltm else "not_available"),
            "ltm_details": {
                "attempted_identity_count": 0,
                "constructed_identity_count": 0,
                "derived_fact_count": 0,
                "component_fact_count": 0,
            },
            "coverage_manifests": [],
            "calculation_edges": [],
            "errors": [str(exc)],
        }

    extractions: list[tuple[Any, Mapping[str, Any]]] = []
    errors: list[str] = []
    if not annual_filings:
        errors.append("no accession-specific annual XBRL filings available")
    for filing in [*annual_filings, *interim_filings]:
        extraction = extract_filing_presentation(
            filing,
            ticker=normalized_ticker,
            evidence_cutoff=evidence_cutoff,
            source_run_id=source_run_id,
        )
        extractions.append((filing, extraction))
        for error in extraction.get("errors") or []:
            errors.append(f"{_accession(filing) or 'unknown'}: {error}")

    annual_records = [
        fact
        for filing, extraction in extractions
        if filing in annual_filings
        for fact in extraction.get("facts") or []
    ]
    interim_records = [
        fact
        for filing, extraction in extractions
        if filing in interim_filings
        for fact in extraction.get("facts") or []
    ]
    annual_periods = _annual_period_ends(
        annual_records,
        max_periods=max_periods,
    )
    selected_annual = [
        fact
        for fact in annual_records
        if fact.get("period_kind") == "annual"
        and fact.get("period_end") in annual_periods
    ]

    ltm_status = "not_requested"
    ltm_details = {
        "attempted_identity_count": 0,
        "constructed_identity_count": 0,
        "derived_fact_count": 0,
        "component_fact_count": 0,
    }
    ltm_components: list[dict[str, Any]] = []
    derived_ltm: list[dict[str, Any]] = []
    if include_ltm:
        (
            raw_derived_ltm,
            raw_ltm_components,
            ltm_status,
            ltm_details,
        ) = _construct_ltm_facts([*annual_records, *interim_records])
        if raw_derived_ltm:
            window_groups: dict[
                tuple[str, str],
                list[dict[str, Any]],
            ] = defaultdict(list)
            for record in raw_derived_ltm:
                metadata = _mapping(record.get("metadata"))
                window_groups[
                    (
                        str(metadata.get("period_start") or ""),
                        str(metadata.get("period_end") or ""),
                    )
                ].append(record)
            target_window, target_records = max(
                window_groups.items(),
                key=lambda item: (
                    item[0][1],
                    item[0][0],
                    len(item[1]),
                ),
            )
            target_component_ids = {
                str(component_id)
                for record in target_records
                for component_id in (
                    _mapping(record.get("derivation")).get("component_fact_ids") or []
                )
            }
            component_by_id = {
                str(record["fact_id"]): record
                for record in raw_ltm_components
                if record.get("fact_id")
            }
            ltm_components = [
                component_by_id[component_id]
                for component_id in sorted(target_component_ids)
                if component_id in component_by_id
            ]
            derived_ltm = [_normalize_derived_fact(record) for record in target_records]
            annual_component_ends = {
                str(record.get("period_end") or "")
                for record in ltm_components
                if record.get("period_kind") == "annual" and record.get("period_end")
            }
            ltm_status, expected_identities, constructed_identities = (
                resolve_ltm_status(
                    annual_records=annual_records,
                    derived_ltm=derived_ltm,
                    annual_component_ends=annual_component_ends,
                )
            )
            ltm_details = {
                **ltm_details,
                "attempted_identity_count": len(expected_identities),
                "constructed_identity_count": len(constructed_identities),
                "derived_fact_count": len(derived_ltm),
                "component_fact_count": len(ltm_components),
                "target_period_start": target_window[0],
                "target_period_end": target_window[1],
            }

    selected_by_fingerprint: dict[str, dict[str, Any]] = {}
    for fact in [*selected_annual, *ltm_components, *derived_ltm]:
        fingerprint = _text(fact.get("ingestion_fingerprint"))
        if fingerprint:
            selected_by_fingerprint[fingerprint] = fact
    selected = sorted(
        selected_by_fingerprint.values(),
        key=lambda fact: (
            str(fact.get("statement") or ""),
            str(fact.get("concept") or ""),
            str(fact.get("period_end") or ""),
            str(fact.get("period_start") or ""),
            str(fact.get("accession") or ""),
            str(fact.get("fact_id") or ""),
        ),
    )
    manifests = _selected_manifests(
        extractions,
        ticker=normalized_ticker,
        selected_facts=selected,
        evidence_cutoff=evidence_cutoff,
        source_run_id=source_run_id,
    )
    calculation_edges_by_id = {
        str(edge["edge_id"]): edge
        for manifest in manifests
        for edge in manifest.get("calculation_edges") or []
    }
    annual_coverage: dict[str, set[str]] = defaultdict(set)
    for fact in selected_annual:
        if fact.get("period_end") and not _mapping(fact.get("dimensions")):
            annual_coverage[str(fact["period_end"])].add(
                str(fact.get("statement") or "")
            )
    annual_coverage_complete = bool(annual_periods) and all(
        annual_coverage.get(period_end) == _PRIMARY_STATEMENTS
        for period_end in annual_periods
    )
    status = (
        "completed"
        if annual_coverage_complete and (not include_ltm or ltm_status == "constructed")
        else "partial"
        if selected
        else "failed"
    )
    return {
        "ticker": normalized_ticker,
        "entity_id": _text(_get(company, "cik")),
        "source": FILING_PRESENTATION_SOURCE,
        "status": status,
        "facts": selected,
        "fact_count": len(selected),
        "annual_periods": annual_periods,
        "ltm_status": ltm_status,
        "ltm_details": ltm_details,
        "coverage_manifests": manifests,
        "calculation_edges": list(calculation_edges_by_id.values()),
        "errors": errors,
    }


__all__ = [
    "COVERAGE_CONTRACT_VERSION",
    "FILING_PRESENTATION_SOURCE",
    "extract_filing_presentation",
    "get_filing_presentation_evidence",
]
