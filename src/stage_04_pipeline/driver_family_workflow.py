"""Focused primary-plus-critic workflow for valuation driver families."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
import json
import re
from typing import Any, Literal

from config.llm_routing import resolve_family_projection_limit_chars
from src.contracts.analysis_snapshot import AnalysisSnapshot
from src.contracts.assumption_registry import (
    DriverFamily,
    get_assumption_definition,
    judgment_owned_fields,
)
from src.contracts.driver_families import (
    DriverFamilyCritique,
    DriverFamilyProposal,
)
from src.contracts.judgment_runs import (
    AgentRunEnvelope,
    JudgmentTask,
    ProviderRoute,
    canonical_semantic_hash,
)
from src.contracts.pm_decision_queue import PMDecisionQueueItem
from src.stage_03_judgment.judgment_gateway import (
    JudgmentGateway,
    JudgmentBackendResponse,
    StructuredJudgmentBackend,
)
from src.stage_04_pipeline.driver_family_queue import (
    build_driver_family_queue_item,
)


DRIVER_FAMILY_PROMPT_VERSION = "1.2.0"
DRIVER_FAMILY_COMPILER_VERSION = "1.1.0"

_FAMILY_STATEMENT_TYPES: dict[DriverFamily, tuple[str, ...]] = {
    DriverFamily.revenue: ("IncomeStatement",),
    DriverFamily.profitability_tax: ("IncomeStatement",),
    DriverFamily.reinvestment_working_capital: (
        "BalanceSheet",
        "CashFlowStatement",
        "IncomeStatement",
    ),
    DriverFamily.terminal_capital_comps: (),
}

# These terms are deliberately broader than the driver names. They map a
# driver family to the accounting concepts that can support its forward-looking
# assumption, including the numerator and denominator facts needed to
# calculate a ratio. A record that cannot be classified as another family's
# fact is retained as uncertainty rather than silently under-feeding a model.
_FAMILY_FACT_TERMS: dict[DriverFamily, tuple[str, ...]] = {
    DriverFamily.revenue: (
        "revenue_growth_near",
        "revenue_growth_mid",
        "revenue_growth_terminal",
        "revenue",
        "sales",
        "contract_with_customer",
        "subscription",
    ),
    DriverFamily.profitability_tax: (
        "ebit_margin_target",
        "cogs_pct_of_revenue",
        "tax_rate_target",
        "revenue",
        "sales",
        "operating_income",
        "ebit",
        "cost_of_goods",
        "cost_of_revenue",
        "cogs",
        "gross_profit",
        "income_tax",
        "tax",
        "pretax",
    ),
    DriverFamily.reinvestment_working_capital: (
        "capex_pct_target",
        "da_pct_target",
        "dso_target",
        "dio_target",
        "dpo_target",
        "revenue",
        "sales",
        "cost_of_goods",
        "cost_of_revenue",
        "cogs",
        "capex",
        "capital_expenditure",
        "payments_to_acquire_property_plant_and_equipment",
        "depreciation",
        "amortization",
        "receivable",
        "inventory",
        "payable",
    ),
    DriverFamily.terminal_capital_comps: (
        "annual_dilution_pct",
        "exit_multiple",
        "ronic_terminal",
        "dilution",
        "share",
        "weighted_average",
        "peer",
        "comps",
        "multiple",
        "return_on_invested_capital",
    ),
}

_SOURCE_VALUE_KEYS = frozenset(
    {
        "source",
        "source_locator",
        "source_url",
        "url",
        "filing_url",
        "sec_url",
        "archive_url",
        "accession",
        "filing_accession",
    }
)
_FACT_REFERENCE_KEYS = frozenset(
    {
        "fact_id",
        "fact_ids",
        "selected_fact_ids",
        "source_fact_id",
        "source_fact_ids",
    }
)

_PRIMARY_SYSTEM_PROMPT = """\
You are a fundamental-equity analyst authoring one focused valuation-driver family.
Use only the frozen evidence supplied in the request. Author direct low, base, and high
case values for this company; do not apply sector constants, canned deltas, score
coefficients, or mechanical averaging. Cite only evidence anchor handles present in the
family evidence table. Every evidence_anchor_ids value must be an exact string from
allowed_evidence_anchor_ids in the user payload; the table maps each handle back to
the immutable fact ID. Nested paths into comps_inputs,
statements, or market_inputs are not evidence anchor IDs. Explain the conditions for each
case and what evidence would change the view.
Mark a conditional driver not_applicable only when the evidence establishes that fact.
Return only the requested structured contract."""

_CRITIC_SYSTEM_PROMPT = """\
You are the independent grounded critic for one valuation-driver family. Review the
primary proposal against the same focused evidence, reconciled statements, business
analysis, industry analysis, and comps inputs. Identify unsupported leaps, internal
inconsistency, missing evidence, scenario-order errors, and reconciliation risk. Do not
replace, average, or silently edit the primary values. If deterministic WACC or another
model methodology is structurally inadequate, emit a methodology challenge with evidence
and required capability; never invent a numeric proxy. Every evidence_anchor_ids value must
be an exact string from allowed_evidence_anchor_ids in the user payload. Nested paths into
comps_inputs, statements, or market_inputs are not evidence anchor IDs. Return only the
requested structured critique contract."""

_REVISION_SYSTEM_PROMPT = """\
You are the original fundamental-equity analyst revising one focused valuation-driver
family exactly once. Reassess the entire atomic family against the same focused evidence
and address the critic's explicit issues. Keep or change each direct low, base, and high
value based on evidence; do not copy values from the critic, mechanically average,
apply sector constants, canned deltas, or score coefficients. Return the complete
structured family contract, not a patch. Every evidence_anchor_ids value must be an exact
string from allowed_evidence_anchor_ids in the user payload. Nested paths into comps_inputs,
statements, or market_inputs are not evidence anchor IDs."""


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _family_contract_context(family: DriverFamily) -> list[dict[str, str]]:
    context = []
    for name in judgment_owned_fields(family):
        definition = get_assumption_definition(name)
        context.append(
            {
                "assumption_name": name,
                "unit": definition.unit.value,
                "applicability": definition.applicability.value,
                "scenario_direction": (
                    definition.scenario_direction.value
                    if definition.scenario_direction is not None
                    else "unordered"
                ),
            }
        )
    return context


def _normalized_text(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value).lower())


def _recursive_strings(value: object) -> list[str]:
    if isinstance(value, Mapping):
        strings: list[str] = []
        for key, child in value.items():
            strings.append(str(key))
            strings.extend(_recursive_strings(child))
        return strings
    if isinstance(value, (list, tuple)):
        strings = []
        for child in value:
            strings.extend(_recursive_strings(child))
        return strings
    if isinstance(value, str):
        return [value]
    return []


def _family_term_matches(value: object, family: DriverFamily) -> bool:
    searchable = _normalized_text(" ".join(_recursive_strings(value)))
    return any(
        _normalized_text(term) in searchable
        for term in _FAMILY_FACT_TERMS[family]
    )


def _family_matches(value: object) -> set[DriverFamily]:
    return {
        family
        for family in DriverFamily
        if _family_term_matches(value, family)
    }


def _statement_descriptor(record: Mapping[str, object]) -> str:
    concept = record.get("concept")
    if isinstance(concept, str) and concept.strip():
        return _normalized_text(concept)
    return _normalized_text(
        " ".join(
            _recursive_strings(
                {
                    key: record.get(key)
                    for key in (
                        "fact_id",
                        "label",
                        "name",
                        "metric",
                        "line_item",
                    )
                    if key in record
                }
            )
        )
    )


def _income_statement_role(
    record: Mapping[str, object],
) -> str | None:
    descriptor = _statement_descriptor(record)
    if not descriptor:
        return None

    if any(
        term in descriptor
        for term in (
            "costofgoods",
            "costofrevenue",
            "costofsales",
            "cogs",
        )
    ):
        return "cogs"
    if "grossprofit" in descriptor:
        return "gross_profit"
    if any(
        term in descriptor
        for term in ("operatingincome", "operatingincomeloss", "ebit")
    ) and "nonoperating" not in descriptor:
        return "operating_income"
    if any(
        term in descriptor
        for term in (
            "incometax",
            "taxexpense",
            "taxprovision",
            "provisionforincome",
        )
    ):
        return "tax"
    if any(term in descriptor for term in ("pretax", "beforeincometax")):
        return "pretax"
    if any(
        term in descriptor
        for term in (
            "revenue",
            "sales",
            "contractwithcustomer",
            "subscription",
        )
    ) and not any(
        term in descriptor
        for term in (
            "expense",
            "selling",
            "marketing",
            "nonoperating",
        )
    ):
        return "revenue"
    return None


def _statement_role(
    record: Mapping[str, object],
    family: DriverFamily,
) -> str | None:
    statement = record.get("statement")
    descriptor = _statement_descriptor(record)

    if family is DriverFamily.terminal_capital_comps:
        return None

    if statement == "IncomeStatement":
        income_role = _income_statement_role(record)
        if family is DriverFamily.revenue:
            return income_role if income_role == "revenue" else None
        if family is DriverFamily.profitability_tax:
            return income_role
        if family is DriverFamily.reinvestment_working_capital:
            return income_role if income_role in {"revenue", "cogs"} else None

    if family is not DriverFamily.reinvestment_working_capital:
        return None

    if statement == "CashFlowStatement":
        if any(
            term in descriptor
            for term in (
                "capitalexpenditure",
                "capex",
                "paymentstoacquirepropertyplantandequipment",
                "purchaseofpropertyplantandequipment",
            )
        ):
            return "capex"
        if any(term in descriptor for term in ("depreciation", "amortization")):
            return "da"
        return None

    if statement == "BalanceSheet":
        if any(term in descriptor for term in ("receivable", "accountsreceivable")):
            return None if any(
                term in descriptor for term in ("increase", "decrease", "change")
            ) else "receivables"
        if "inventory" in descriptor:
            return None if any(
                term in descriptor for term in ("increase", "decrease", "change")
            ) else "inventory"
        if any(
            term in descriptor
            for term in (
                "accountspayable",
                "tradepayable",
                "tradeaccountsandotherpayables",
                "payables",
            )
        ) and not any(
            term in descriptor
            for term in ("taxpayable", "incometax", "incometaxes")
        ):
            return "payables"

    return None


def _statement_dedupe_key(
    record: Mapping[str, object],
    role: str,
) -> str:
    temporal_keys = (
        "period_start",
        "period_end",
        "period_kind",
        "period_type",
        "fiscal_period",
        "fiscal_year",
    )
    temporal = tuple(record.get(key) for key in temporal_keys)
    if not any(value is not None for value in temporal):
        return _canonical_json(
            {
                "role": role,
                "fact_id": record.get("fact_id"),
            }
        )
    return _canonical_json(
        {
            "role": role,
            "statement": record.get("statement"),
            "temporal": temporal,
            "numeric_value": record.get("numeric_value"),
            "unit": record.get("unit"),
            "currency": record.get("currency"),
            "scale": record.get("scale"),
        }
    )


def _family_statement_records(
    statements: Mapping[str, object],
    family: DriverFamily,
) -> tuple[list[Mapping[str, object]], int | None, bool]:
    records = statements.get("consolidated_view")
    if not isinstance(records, (list, tuple)):
        return [], None, True
    eligible_records = [
        record
        for record in records
        if isinstance(record, Mapping)
        and record.get("statement") in _FAMILY_STATEMENT_TYPES[family]
        and not (
            isinstance(record.get("hierarchy"), Mapping)
            and record["hierarchy"].get("consolidated_view_eligible") is False
        )
    ]
    selected_records: list[Mapping[str, object]] = []
    seen_keys: set[str] = set()
    for record in eligible_records:
        role = _statement_role(record, family)
        if role is None:
            continue
        dedupe_key = _statement_dedupe_key(record, role)
        if dedupe_key in seen_keys:
            continue
        seen_keys.add(dedupe_key)
        selected_records.append(record)

    # An unfamiliar statement schema is an evidence-risk, not a reason to send
    # an empty packet. Keep the eligible records and expose the fallback in the
    # projection scope so the caller can monitor it.
    if eligible_records and not selected_records:
        return eligible_records, len(records), True
    return selected_records, len(records), False


def _select_family_evidence(
    evidence: Mapping[str, object],
    family: DriverFamily,
    selected_fact_ids: set[str],
) -> tuple[dict[str, object], list[str]]:
    selected: dict[str, object] = {}
    uncertain_anchor_ids: list[str] = []
    irrelevant_terms = (
        "lease",
        "pension",
        "goodwill",
        "debt",
        "wacc",
    )
    for anchor_id in sorted(evidence, key=str):
        value = evidence[anchor_id]
        matches = _family_matches((anchor_id, value))
        if anchor_id in selected_fact_ids or family in matches or not matches:
            if not matches and any(
                _normalized_text(term)
                in _normalized_text(" ".join(_recursive_strings((anchor_id, value))))
                for term in irrelevant_terms
            ):
                continue
            selected[str(anchor_id)] = value
            if not matches:
                uncertain_anchor_ids.append(str(anchor_id))
    # An empty classification is an unsafe result: retain the full evidence
    # set so a model never receives a plausible but incomplete evidence packet.
    if evidence and not selected:
        selected = {str(key): value for key, value in evidence.items()}
        uncertain_anchor_ids = sorted(selected)
    return selected, uncertain_anchor_ids


def _iter_mappings(value: object) -> list[Mapping[str, object]]:
    if isinstance(value, Mapping):
        mappings: list[Mapping[str, object]] = [value]
        for child in value.values():
            mappings.extend(_iter_mappings(child))
        return mappings
    if isinstance(value, (list, tuple)):
        mappings = []
        for child in value:
            mappings.extend(_iter_mappings(child))
        return mappings
    return []


def _source_identity(value: object) -> tuple[str, ...] | None:
    if not isinstance(value, Mapping):
        return None
    source = value.get("source")
    accession = value.get("accession") or value.get("filing_accession")
    locator = next(
        (
            value.get(key)
            for key in (
                "source_locator",
                "source_url",
                "url",
                "filing_url",
                "sec_url",
                "archive_url",
            )
            if isinstance(value.get(key), str) and value.get(key)
        ),
        None,
    )
    source_text = source if isinstance(source, str) else None
    accession_text = accession if isinstance(accession, str) else None
    locator_text = locator if isinstance(locator, str) else None
    if not any((source_text, accession_text, locator_text)):
        return None
    return (
        source_text or "",
        accession_text or "",
        locator_text or "",
    )


def _build_source_table(
    values: object,
) -> tuple[dict[tuple[str, ...], str], list[dict[str, str]]]:
    raw_identities = {
        identity
        for mapping in _iter_mappings(values)
        if (identity := _source_identity(mapping)) is not None
    }
    merged_identities: dict[tuple[str, str], tuple[str, str, str]] = {}
    for identity in raw_identities:
        source, accession, locator = identity
        merge_key = (source, locator) if locator else identity
        current = merged_identities.get(merge_key)
        if current is None or (not current[1] and accession):
            merged_identities[merge_key] = (source, accession, locator)
    identities = set(merged_identities.values())
    handle_by_identity = {
        identity: f"s{index:04d}"
        for index, identity in enumerate(sorted(identities), start=1)
    }
    table: list[dict[str, str]] = []
    for identity, handle in handle_by_identity.items():
        source, accession, locator = identity
        row = {"source_handle": handle}
        if source:
            row["source"] = source
        if accession:
            row["accession"] = accession
        if locator:
            row["source_locator"] = locator
        table.append(row)
    return handle_by_identity, table


def _collect_fact_ids(value: object) -> set[str]:
    fact_ids: set[str] = set()
    if isinstance(value, Mapping):
        for key, child in value.items():
            if _normalized_text(key) in {
                _normalized_text(reference_key)
                for reference_key in _FACT_REFERENCE_KEYS
            }:
                fact_ids.update(
                    string
                    for string in _recursive_strings(child)
                    if string
                )
            else:
                fact_ids.update(_collect_fact_ids(child))
    elif isinstance(value, (list, tuple)):
        for child in value:
            fact_ids.update(_collect_fact_ids(child))
    return fact_ids


def _build_fact_handle_map(values: object) -> dict[str, str]:
    fact_ids = sorted(
        fact_id
        for fact_id in _collect_fact_ids(values)
        if isinstance(fact_id, str)
    )
    return {
        f"f{index:04d}": fact_id
        for index, fact_id in enumerate(fact_ids, start=1)
    }


def _contains_selected_fact(value: object, selected_fact_ids: set[str]) -> bool:
    return any(
        string in selected_fact_ids
        for string in _recursive_strings(value)
    )


_RECONCILIATION_STATUS_KEYS = frozenset(
    {
        "status",
        "decision_grade",
        "annual_period_count",
        "ltm_status",
        "reason_codes",
        "reconciliation_run_hash",
        "readiness",
        "source_count",
    }
)


def _filter_reconciliation_nested(
    value: object,
    selected_fact_ids: set[str],
) -> object:
    if isinstance(value, list):
        return [
            _filter_reconciliation_nested(item, selected_fact_ids)
            for item in value
            if _contains_selected_fact(item, selected_fact_ids)
        ]
    if isinstance(value, Mapping):
        filtered: dict[str, object] = {}
        for key, child in value.items():
            key_text = str(key)
            if (
                _normalized_text(key_text)
                in {_normalized_text(item) for item in _RECONCILIATION_STATUS_KEYS}
            ):
                filtered[key_text] = child
            elif _contains_selected_fact(child, selected_fact_ids):
                filtered[key_text] = _filter_reconciliation_nested(
                    child,
                    selected_fact_ids,
                )
        return filtered
    return value


def _family_reconciliation_projection(
    reconciliation: Mapping[str, object],
    selected_fact_ids: set[str],
) -> dict[str, object]:
    projected: dict[str, object] = {}
    for key, value in reconciliation.items():
        key_text = str(key)
        normalized_key = _normalized_text(key_text)
        if normalized_key in {
            _normalized_text(item) for item in _RECONCILIATION_STATUS_KEYS
        }:
            projected[key_text] = value
        elif normalized_key == "selectedfactids":
            projected[key_text] = sorted(selected_fact_ids)
        elif normalized_key in {"checks", "findings"}:
            if isinstance(value, (list, tuple)):
                projected[key_text] = [
                    item
                    for item in value
                    if _contains_selected_fact(item, selected_fact_ids)
                ]
        elif normalized_key == "sourcereconciliation":
            filtered = _filter_reconciliation_nested(
                value,
                selected_fact_ids,
            )
            if filtered:
                projected[key_text] = filtered
    return projected


def _compact_value(
    value: object,
    *,
    fact_handles: Mapping[str, str],
    anchor_handles: Mapping[str, str] | None = None,
    source_handles: Mapping[tuple[str, ...], str] | None = None,
) -> object:
    replacements = dict(fact_handles)
    if anchor_handles:
        replacements.update(anchor_handles)
    if isinstance(value, Mapping):
        source_handle = None
        if source_handles:
            identity = _source_identity(value)
            if identity is not None:
                source_handle = source_handles.get(identity)
                if source_handle is None and identity[2]:
                    source_handle = next(
                        (
                            handle
                            for source_identity, handle in source_handles.items()
                            if source_identity[0] == identity[0]
                            and source_identity[2] == identity[2]
                        ),
                        None,
                    )
        compact: dict[object, object] = {}
        for key, child in value.items():
            key_text = str(key)
            if source_handle and key_text in _SOURCE_VALUE_KEYS:
                continue
            compact_key = replacements.get(key_text, key)
            compact[compact_key] = _compact_value(
                child,
                fact_handles=fact_handles,
                anchor_handles=anchor_handles,
                source_handles=source_handles,
            )
        if source_handle:
            compact["source_handle"] = source_handle
        return compact
    if isinstance(value, list):
        return [
            _compact_value(
                child,
                fact_handles=fact_handles,
                anchor_handles=anchor_handles,
                source_handles=source_handles,
            )
            for child in value
        ]
    if isinstance(value, tuple):
        return [
            _compact_value(
                child,
                fact_handles=fact_handles,
                anchor_handles=anchor_handles,
                source_handles=source_handles,
            )
            for child in value
        ]
    if isinstance(value, str):
        return replacements.get(value, value)
    return value


def _family_market_inputs(
    market_inputs: object,
    family: DriverFamily,
) -> object:
    if not isinstance(market_inputs, Mapping):
        return market_inputs
    driver_names = set(judgment_owned_fields(family))
    projected: dict[str, object] = {}
    for key, value in market_inputs.items():
        if key not in {"base_drivers", "source_lineage"}:
            projected[str(key)] = value
            continue
        if not isinstance(value, Mapping):
            projected[str(key)] = value
            continue
        projected[str(key)] = {
            str(driver): driver_value
            for driver, driver_value in value.items()
            if str(driver) in driver_names
            or any(
                str(driver).startswith(f"{driver_name}_")
                for driver_name in driver_names
            )
        }
    return projected


def _family_statement_projection(
    statements: Mapping[str, object],
    family: DriverFamily,
    *,
    fact_handle_map: Mapping[str, str] | None = None,
    source_handles: Mapping[tuple[str, ...], str] | None = None,
) -> tuple[dict[str, object], dict[str, object]]:
    """Keep only driver-supporting statement rows in a compact family view."""

    records = statements.get("consolidated_view")
    retained_types = _FAMILY_STATEMENT_TYPES[family]
    if not isinstance(records, (list, tuple)):
        return (
            dict(statements),
            {
                "format": "snapshot-native",
                "source_fact_count": None,
                "retained_fact_count": None,
                "retained_statement_types": list(retained_types),
                "selection_fallback": "snapshot-native-no-ledger",
            },
        )

    selected_records, source_fact_count, _ = _family_statement_records(
        statements,
        family,
    )
    full_to_short = {
        full_id: handle
        for handle, full_id in (fact_handle_map or {}).items()
    }
    compact_selected_records = [
        _compact_value(
            record,
            fact_handles=full_to_short,
            source_handles=source_handles,
        )
        for record in selected_records
    ]
    all_columns = {
        str(key)
        for record in compact_selected_records
        if isinstance(record, Mapping)
        for key in record
    }
    omitted_record_fields = sorted(all_columns & {"hierarchy"})
    columns = sorted(set(all_columns) - set(omitted_record_fields))
    compact_records = {
        "format": "columnar-records-v2",
        "columns": columns,
        "rows": [
            [
                record.get(column) if isinstance(record, Mapping) else None
                for column in columns
            ]
            for record in compact_selected_records
        ],
    }
    projected = {
        key: value
        for key, value in statements.items()
        if key not in {"consolidated_view", "fact_ids", "fact_handle_map"}
    }
    projected["fact_ids"] = [
        full_to_short.get(str(record.get("fact_id")), record.get("fact_id"))
        for record in selected_records
        if record.get("fact_id")
    ]
    projected["fact_handle_map"] = dict(fact_handle_map or {})
    projected["consolidated_view"] = compact_records
    scope = {
        "format": "family-relevant-columnar-records-v2",
        "source_fact_count": source_fact_count,
        "retained_fact_count": len(selected_records),
        "retained_statement_types": list(retained_types),
        "selection_terms": list(_FAMILY_FACT_TERMS[family]),
        "omitted_record_fields": omitted_record_fields,
        "omission_reason": (
            "presentation hierarchy is redundant with the fact identity and "
            "source lineage carried in this view"
            if omitted_record_fields
            else None
        ),
    }
    projected["projection_scope"] = scope
    return projected, scope


def _family_analysis_projection(
    snapshot: AnalysisSnapshot,
    family: DriverFamily,
    *,
    max_chars: int,
) -> dict[str, object]:
    """Return a deterministic family view; never silently truncate evidence."""

    if max_chars < 1:
        raise ValueError("max projection size must be positive")
    family_components = {
        DriverFamily.revenue: (
            "statements",
            "statement_reconciliation",
            "market_inputs",
            "comps_inputs",
        ),
        DriverFamily.profitability_tax: (
            "statements",
            "statement_reconciliation",
            "market_inputs",
            "wacc_inputs",
        ),
        DriverFamily.reinvestment_working_capital: (
            "statements",
            "statement_reconciliation",
            "claim_ledger",
            "market_inputs",
        ),
        DriverFamily.terminal_capital_comps: (
            "claim_ledger",
            "market_inputs",
            "wacc_inputs",
            "comps_inputs",
        ),
    }[family]
    selected_records, source_fact_count, statement_fallback = (
        _family_statement_records(snapshot.statements, family)
    )
    selected_statement_fact_ids = {
        str(record["fact_id"])
        for record in selected_records
        if record.get("fact_id")
    }
    raw_reconciliation = _family_reconciliation_projection(
        snapshot.statement_reconciliation,
        selected_statement_fact_ids,
    )
    selected_evidence, uncertain_anchor_ids = _select_family_evidence(
        snapshot.evidence,
        family,
        selected_statement_fact_ids,
    )
    fact_handle_map = _build_fact_handle_map(
        [selected_records, raw_reconciliation, selected_evidence]
    )
    anchor_handle_map = {
        f"a{index:04d}": anchor_id
        for index, anchor_id in enumerate(sorted(selected_evidence), start=1)
    }
    source_handles, source_table = _build_source_table(
        [selected_records, raw_reconciliation, selected_evidence]
    )
    projected_statements, statement_scope = _family_statement_projection(
        snapshot.statements,
        family,
        fact_handle_map=fact_handle_map,
        source_handles=source_handles,
    )
    compact_fact_handles = {
        full_id: handle
        for handle, full_id in fact_handle_map.items()
    }
    compact_anchor_handles = {
        full_id: handle
        for handle, full_id in anchor_handle_map.items()
    }
    evidence_rows = [
        {
            "handle": compact_anchor_handles[anchor_id],
            "record": _compact_value(
                selected_evidence[anchor_id],
                fact_handles=compact_fact_handles,
                source_handles=source_handles,
            ),
        }
        for anchor_id in sorted(selected_evidence)
    ]
    projection: dict[str, object] = {
        "ticker": snapshot.ticker,
        "as_of_date": snapshot.as_of_date,
        "analysis_snapshot_hash": snapshot.snapshot_hash,
        "family": family.value,
        "identity": snapshot.identity,
        "approved_treatments": _compact_value(
            snapshot.approved_treatments,
            fact_handles=compact_fact_handles,
            anchor_handles=compact_anchor_handles,
            source_handles=source_handles,
        ),
        "evidence": {
            "format": "family-relevant-anchor-table-v1",
            "rows": evidence_rows,
            "anchor_handle_map": anchor_handle_map,
            "source_anchor_count": len(snapshot.evidence),
            "selected_anchor_count": len(selected_evidence),
            "uncertain_anchor_handles": [
                compact_anchor_handles[anchor_id]
                for anchor_id in uncertain_anchor_ids
                if anchor_id in compact_anchor_handles
            ],
        },
        "upstream_context": _compact_value(
            snapshot.upstream_context,
            fact_handles=compact_fact_handles,
            anchor_handles=compact_anchor_handles,
            source_handles=source_handles,
        ),
        "source_fingerprints": snapshot.source_fingerprints,
        "component_versions": snapshot.component_versions,
        "projection_scope": {
            "statements": statement_scope,
            "evidence": {
                "source_anchor_count": len(snapshot.evidence),
                "selected_anchor_count": len(selected_evidence),
                "uncertain_anchor_count": len(uncertain_anchor_ids),
            },
            "fact_handle_count": len(fact_handle_map),
            "source_table_count": len(source_table),
            "selection_fallback": (
                "snapshot-native-no-ledger" if statement_fallback else None
            ),
        },
    }
    for component in family_components:
        if component == "statements":
            projection[component] = projected_statements
        elif component == "statement_reconciliation":
            projection[component] = _compact_value(
                raw_reconciliation,
                fact_handles=compact_fact_handles,
                source_handles=source_handles,
            )
        elif component == "market_inputs":
            projection[component] = _compact_value(
                _family_market_inputs(snapshot.market_inputs, family),
                fact_handles=compact_fact_handles,
                anchor_handles=compact_anchor_handles,
                source_handles=source_handles,
            )
        else:
            projection[component] = _compact_value(
                getattr(snapshot, component),
                fact_handles=compact_fact_handles,
                anchor_handles=compact_anchor_handles,
                source_handles=source_handles,
            )
    projection["source_table"] = source_table
    encoded = _canonical_json(projection)
    if len(encoded) > max_chars:
        raise OverflowError(
            "family projection exceeds deterministic context bound: "
            f"family={family.value}, chars={len(encoded)}, max={max_chars}"
        )
    return projection


def _proposal_unknown_anchors(
    proposal: DriverFamilyProposal,
    snapshot: AnalysisSnapshot,
    allowed_anchor_ids: set[str] | None = None,
) -> set[str]:
    available = set(snapshot.evidence) if allowed_anchor_ids is None else allowed_anchor_ids
    return {
        anchor
        for assumption in proposal.assumptions
        for anchor in assumption.evidence_anchor_ids
        if anchor not in available
    }


def _critique_unknown_anchors(
    critique: DriverFamilyCritique,
    snapshot: AnalysisSnapshot,
    allowed_anchor_ids: set[str] | None = None,
) -> set[str]:
    available = set(snapshot.evidence) if allowed_anchor_ids is None else allowed_anchor_ids
    issue_anchors = {
        anchor
        for issue in critique.issues
        for anchor in issue.evidence_anchor_ids
        if anchor not in available
    }
    challenge_anchors = {
        anchor
        for challenge in critique.methodology_challenges
        for anchor in challenge.evidence_anchor_ids
        if anchor not in available
    }
    return issue_anchors | challenge_anchors


def _task(
    *,
    snapshot: AnalysisSnapshot,
    family: DriverFamily,
    role: Literal["primary", "critic", "revision"],
    analysis_projection: dict[str, object],
    reviewed_proposal: DriverFamilyProposal | None = None,
    critique: DriverFamilyCritique | None = None,
) -> JudgmentTask:
    output_model = (
        DriverFamilyCritique if role == "critic" else DriverFamilyProposal
    )
    system_prompt = {
        "primary": _PRIMARY_SYSTEM_PROMPT,
        "critic": _CRITIC_SYSTEM_PROMPT,
        "revision": _REVISION_SYSTEM_PROMPT,
    }[role]
    evidence_projection = analysis_projection.get("evidence", {})
    anchor_handle_map = (
        evidence_projection.get("anchor_handle_map", {})
        if isinstance(evidence_projection, Mapping)
        else {}
    )
    full_to_anchor_handle = {
        full_id: handle
        for handle, full_id in anchor_handle_map.items()
    }
    allowed_anchor_handles = (
        sorted(anchor_handle_map)
        if isinstance(evidence_projection, Mapping)
        and "anchor_handle_map" in evidence_projection
        else sorted(snapshot.evidence)
    )
    static_prompt_identity = {
        "version": DRIVER_FAMILY_PROMPT_VERSION,
        "role": role,
        "system_prompt": system_prompt,
        "family_contract": _family_contract_context(family),
    }
    user_payload: dict[str, object] = {
        "ticker": snapshot.ticker,
        "as_of_date": snapshot.as_of_date,
        "family": family.value,
        "family_contract": _family_contract_context(family),
        "analysis_snapshot_hash": snapshot.snapshot_hash,
        "analysis_snapshot": analysis_projection,
        "allowed_evidence_anchor_ids": allowed_anchor_handles,
    }
    reviewed_identity: dict[str, object] = {}
    if reviewed_proposal is not None:
        reviewed_payload = _compact_value(
            reviewed_proposal.model_dump(mode="json"),
            fact_handles={},
            anchor_handles=full_to_anchor_handle,
        )
        user_payload["primary_proposal"] = reviewed_payload
        reviewed_identity["primary_proposal"] = reviewed_payload
    if critique is not None:
        critique_payload = _compact_value(
            critique.model_dump(mode="json"),
            fact_handles={},
            anchor_handles=full_to_anchor_handle,
        )
        user_payload["critic_review"] = critique_payload
        reviewed_identity["critic_review"] = critique_payload
    reviewed_hash = (
        canonical_semantic_hash(reviewed_identity)
        if reviewed_identity
        else None
    )
    schema = output_model.model_json_schema()
    return JudgmentTask(
        task_version=f"driver-family-{role}-{DRIVER_FAMILY_PROMPT_VERSION}",
        ticker=snapshot.ticker,
        family=family.value,
        role=role,
        frozen_snapshot_hash=snapshot.snapshot_hash,
        prompt_id=f"driver-family.{family.value}.{role}",
        prompt_hash=canonical_semantic_hash(static_prompt_identity),
        schema_id=output_model.__name__,
        schema_hash=canonical_semantic_hash(schema),
        compiler_id="driver-family-message-compiler",
        compiler_hash=canonical_semantic_hash(
            {"version": DRIVER_FAMILY_COMPILER_VERSION}
        ),
        messages=(
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": _canonical_json(user_payload)},
        ),
        reviewed_output_hash=reviewed_hash,
    )


def _resolve_anchor_handles(
    value: Any,
    handle_to_anchor: Mapping[str, str],
) -> Any:
    if isinstance(value, Mapping):
        return {
            key: _resolve_anchor_handles(child, handle_to_anchor)
            for key, child in value.items()
        }
    if isinstance(value, list):
        return [
            _resolve_anchor_handles(child, handle_to_anchor)
            for child in value
        ]
    if isinstance(value, tuple):
        return tuple(
            _resolve_anchor_handles(child, handle_to_anchor)
            for child in value
        )
    if isinstance(value, str):
        if value in handle_to_anchor:
            return handle_to_anchor[value]
        for handle, anchor_id in handle_to_anchor.items():
            value = value.replace(f'"{handle}"', f'"{anchor_id}"')
        return value
    return value


class _AnchorResolvingBackend:
    def __init__(
        self,
        backend: StructuredJudgmentBackend,
        handle_to_anchor: Mapping[str, str],
    ) -> None:
        self._backend = backend
        self._handle_to_anchor = dict(handle_to_anchor)

    def generate(self, request: object) -> JudgmentBackendResponse:
        response = self._backend.generate(request)  # type: ignore[arg-type]
        return replace(
            response,
            output=_resolve_anchor_handles(
                response.output,
                self._handle_to_anchor,
            ),
        )


@dataclass(frozen=True, slots=True)
class DriverFamilyWorkflowResult:
    status: Literal["queued", "blocked"]
    family: DriverFamily
    primary_envelope: AgentRunEnvelope | None
    critic_envelope: AgentRunEnvelope | None
    revision_envelope: AgentRunEnvelope | None
    revision_critic_envelope: AgentRunEnvelope | None
    proposal: DriverFamilyProposal | None
    critique: DriverFamilyCritique | None
    queue_item: PMDecisionQueueItem | None
    blocker_reason: str | None = None


def run_driver_family_workflow(
    *,
    snapshot: AnalysisSnapshot,
    family: DriverFamily | str,
    primary_route: ProviderRoute,
    primary_backend: StructuredJudgmentBackend,
    critic_route: ProviderRoute,
    critic_backend: StructuredJudgmentBackend,
    gateway: JudgmentGateway | None = None,
    force_refresh: bool = False,
    transport_timeout_seconds: float = 120.0,
    max_projection_chars: int | None = None,
) -> DriverFamilyWorkflowResult:
    """Run one primary and one critic against an identical frozen snapshot."""

    selected_family = DriverFamily(family)
    resolved_gateway = gateway or JudgmentGateway()
    projection_limit = (
        resolve_family_projection_limit_chars(
            primary_route.provider,
            primary_route.requested_model,
            critic_route.requested_model,
        )
        if max_projection_chars is None
        else max_projection_chars
    )
    try:
        analysis_projection = _family_analysis_projection(
            snapshot,
            selected_family,
            max_chars=projection_limit,
        )
    except OverflowError:
        return DriverFamilyWorkflowResult(
            status="blocked",
            family=selected_family,
            primary_envelope=None,
            critic_envelope=None,
            revision_envelope=None,
            revision_critic_envelope=None,
            proposal=None,
            critique=None,
            queue_item=None,
            blocker_reason="family_projection_overflow",
        )
    evidence_projection = analysis_projection.get("evidence", {})
    anchor_handle_map = (
        evidence_projection.get("anchor_handle_map", {})
        if isinstance(evidence_projection, Mapping)
        else {}
    )
    handle_to_anchor = {
        str(handle): str(anchor_id)
        for handle, anchor_id in anchor_handle_map.items()
    }
    allowed_anchor_ids = set(handle_to_anchor.values())
    primary_model_backend = _AnchorResolvingBackend(
        primary_backend,
        handle_to_anchor,
    )
    critic_model_backend = _AnchorResolvingBackend(
        critic_backend,
        handle_to_anchor,
    )
    primary_envelope = resolved_gateway.execute_structured(
        task=_task(
            snapshot=snapshot,
            family=selected_family,
            role="primary",
            analysis_projection=analysis_projection,
        ),
        route=primary_route,
        backend=primary_model_backend,
        output_model=DriverFamilyProposal,
        force_refresh=force_refresh,
        transport_timeout_seconds=transport_timeout_seconds,
    )
    if primary_envelope.validated_payload is None:
        return DriverFamilyWorkflowResult(
            status="blocked",
            family=selected_family,
            primary_envelope=primary_envelope,
            critic_envelope=None,
            revision_envelope=None,
            revision_critic_envelope=None,
            proposal=None,
            critique=None,
            queue_item=None,
            blocker_reason="primary_judgment_failed",
        )
    proposal = DriverFamilyProposal.model_validate(
        primary_envelope.validated_payload
    )
    if proposal.family != selected_family:
        return DriverFamilyWorkflowResult(
            status="blocked",
            family=selected_family,
            primary_envelope=primary_envelope,
            critic_envelope=None,
            revision_envelope=None,
            revision_critic_envelope=None,
            proposal=proposal,
            critique=None,
            queue_item=None,
            blocker_reason="primary_family_mismatch",
        )
    if _proposal_unknown_anchors(proposal, snapshot, allowed_anchor_ids):
        return DriverFamilyWorkflowResult(
            status="blocked",
            family=selected_family,
            primary_envelope=primary_envelope,
            critic_envelope=None,
            revision_envelope=None,
            revision_critic_envelope=None,
            proposal=proposal,
            critique=None,
            queue_item=None,
            blocker_reason="primary_unknown_evidence_anchors",
        )

    critic_envelope = resolved_gateway.execute_structured(
        task=_task(
            snapshot=snapshot,
            family=selected_family,
            role="critic",
            analysis_projection=analysis_projection,
            reviewed_proposal=proposal,
        ),
        route=critic_route,
        backend=critic_model_backend,
        output_model=DriverFamilyCritique,
        force_refresh=force_refresh,
        transport_timeout_seconds=transport_timeout_seconds,
    )
    if critic_envelope.validated_payload is None:
        return DriverFamilyWorkflowResult(
            status="blocked",
            family=selected_family,
            primary_envelope=primary_envelope,
            critic_envelope=critic_envelope,
            revision_envelope=None,
            revision_critic_envelope=None,
            proposal=proposal,
            critique=None,
            queue_item=None,
            blocker_reason="critic_judgment_failed",
        )
    critique = DriverFamilyCritique.model_validate(
        critic_envelope.validated_payload
    )
    if critique.family != selected_family:
        return DriverFamilyWorkflowResult(
            status="blocked",
            family=selected_family,
            primary_envelope=primary_envelope,
            critic_envelope=critic_envelope,
            revision_envelope=None,
            revision_critic_envelope=None,
            proposal=proposal,
            critique=critique,
            queue_item=None,
            blocker_reason="critic_family_mismatch",
        )
    if _critique_unknown_anchors(critique, snapshot, allowed_anchor_ids):
        return DriverFamilyWorkflowResult(
            status="blocked",
            family=selected_family,
            primary_envelope=primary_envelope,
            critic_envelope=critic_envelope,
            revision_envelope=None,
            revision_critic_envelope=None,
            proposal=proposal,
            critique=critique,
            queue_item=None,
            blocker_reason="critic_unknown_evidence_anchors",
        )
    if critique.verdict == "block":
        return DriverFamilyWorkflowResult(
            status="blocked",
            family=selected_family,
            primary_envelope=primary_envelope,
            critic_envelope=critic_envelope,
            revision_envelope=None,
            revision_critic_envelope=None,
            proposal=proposal,
            critique=critique,
            queue_item=None,
            blocker_reason="critic_blocked",
        )

    revision_envelope = None
    revision_critic_envelope = None
    queue_primary_run_id = primary_envelope.run_id
    queue_critic_run_id = critic_envelope.run_id
    if critique.verdict == "revise":
        revision_envelope = resolved_gateway.execute_structured(
            task=_task(
                snapshot=snapshot,
                family=selected_family,
                role="revision",
                analysis_projection=analysis_projection,
                reviewed_proposal=proposal,
                critique=critique,
            ),
            route=primary_route,
            backend=primary_model_backend,
            output_model=DriverFamilyProposal,
            force_refresh=force_refresh,
            transport_timeout_seconds=transport_timeout_seconds,
        )
        if revision_envelope.validated_payload is None:
            return DriverFamilyWorkflowResult(
                status="blocked",
                family=selected_family,
                primary_envelope=primary_envelope,
                critic_envelope=critic_envelope,
                revision_envelope=revision_envelope,
                revision_critic_envelope=None,
                proposal=proposal,
                critique=critique,
                queue_item=None,
                blocker_reason="primary_revision_failed",
            )
        revised_proposal = DriverFamilyProposal.model_validate(
            revision_envelope.validated_payload
        )
        if revised_proposal.family != selected_family:
            return DriverFamilyWorkflowResult(
                status="blocked",
                family=selected_family,
                primary_envelope=primary_envelope,
                critic_envelope=critic_envelope,
                revision_envelope=revision_envelope,
                revision_critic_envelope=None,
                proposal=revised_proposal,
                critique=critique,
                queue_item=None,
                blocker_reason="primary_revision_family_mismatch",
            )
        if _proposal_unknown_anchors(
            revised_proposal,
            snapshot,
            allowed_anchor_ids,
        ):
            return DriverFamilyWorkflowResult(
                status="blocked",
                family=selected_family,
                primary_envelope=primary_envelope,
                critic_envelope=critic_envelope,
                revision_envelope=revision_envelope,
                revision_critic_envelope=None,
                proposal=revised_proposal,
                critique=critique,
                queue_item=None,
                blocker_reason="primary_revision_unknown_evidence_anchors",
            )
        proposal = revised_proposal
        queue_primary_run_id = revision_envelope.run_id
        revision_critic_envelope = resolved_gateway.execute_structured(
            task=_task(
                snapshot=snapshot,
                family=selected_family,
                role="critic",
                analysis_projection=analysis_projection,
                reviewed_proposal=proposal,
                critique=critique,
            ),
            route=critic_route,
            backend=critic_model_backend,
            output_model=DriverFamilyCritique,
            force_refresh=force_refresh,
            transport_timeout_seconds=transport_timeout_seconds,
        )
        if revision_critic_envelope.validated_payload is None:
            return DriverFamilyWorkflowResult(
                status="blocked",
                family=selected_family,
                primary_envelope=primary_envelope,
                critic_envelope=critic_envelope,
                revision_envelope=revision_envelope,
                revision_critic_envelope=revision_critic_envelope,
                proposal=proposal,
                critique=critique,
                queue_item=None,
                blocker_reason="revision_critic_judgment_failed",
            )
        final_critique = DriverFamilyCritique.model_validate(
            revision_critic_envelope.validated_payload
        )
        if final_critique.family != selected_family:
            return DriverFamilyWorkflowResult(
                status="blocked",
                family=selected_family,
                primary_envelope=primary_envelope,
                critic_envelope=critic_envelope,
                revision_envelope=revision_envelope,
                revision_critic_envelope=revision_critic_envelope,
                proposal=proposal,
                critique=final_critique,
                queue_item=None,
                blocker_reason="revision_critic_family_mismatch",
            )
        if _critique_unknown_anchors(
            final_critique,
            snapshot,
            allowed_anchor_ids,
        ):
            return DriverFamilyWorkflowResult(
                status="blocked",
                family=selected_family,
                primary_envelope=primary_envelope,
                critic_envelope=critic_envelope,
                revision_envelope=revision_envelope,
                revision_critic_envelope=revision_critic_envelope,
                proposal=proposal,
                critique=final_critique,
                queue_item=None,
                blocker_reason="revision_critic_unknown_evidence_anchors",
            )
        if final_critique.verdict != "accept":
            return DriverFamilyWorkflowResult(
                status="blocked",
                family=selected_family,
                primary_envelope=primary_envelope,
                critic_envelope=critic_envelope,
                revision_envelope=revision_envelope,
                revision_critic_envelope=revision_critic_envelope,
                proposal=proposal,
                critique=final_critique,
                queue_item=None,
                blocker_reason="revision_not_accepted",
            )
        critique = final_critique
        queue_critic_run_id = revision_critic_envelope.run_id

    queue_item = build_driver_family_queue_item(
        ticker=snapshot.ticker,
        proposal=proposal,
        critique=critique,
        analysis_snapshot_hash=snapshot.snapshot_hash,
        primary_run_id=queue_primary_run_id,
        critic_run_id=queue_critic_run_id,
    )
    if revision_envelope is not None:
        queue_item = queue_item.model_copy(
            update={
                "metadata": {
                    **queue_item.metadata,
                    "initial_primary_run_id": primary_envelope.run_id,
                    "initial_critic_run_id": critic_envelope.run_id,
                    "revision_run_id": revision_envelope.run_id,
                    "revision_critic_run_id": queue_critic_run_id,
                }
            }
        )
    return DriverFamilyWorkflowResult(
        status="queued",
        family=selected_family,
        primary_envelope=primary_envelope,
        critic_envelope=critic_envelope,
        revision_envelope=revision_envelope,
        revision_critic_envelope=revision_critic_envelope,
        proposal=proposal,
        critique=critique,
        queue_item=queue_item,
    )
