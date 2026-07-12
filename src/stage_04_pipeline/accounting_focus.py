"""Deterministic projections of persisted accounting packets into focus contexts.

This module is deliberately a projection layer: it does not call agents, infer
accounting treatment, or mutate the persisted packet.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Mapping

from pydantic import Field

from src.contracts.accounting_evidence import (
    ACCOUNTING_FOCUS_TO_TOPIC,
    AccountingFocusKey,
    AccountingPacketStatus,
    AccountingTopic,
)
from src.contracts.assumption_policy import ContractModel
from src.contracts.evidence_packet import EvidencePacket, EvidencePacketFact, EvidenceSourceRef, TextEvidenceSnippet


@dataclass(frozen=True)
class AccountingFocusDefinition:
    """Inspectible deterministic configuration for one reasoning focus."""

    focus_key: AccountingFocusKey
    parent_topic: AccountingTopic
    allowed_driver_fields: tuple[str, ...]
    fact_tokens: tuple[str, ...]
    note_section_tokens: tuple[str, ...]
    purpose: str


def _definition(
    key: AccountingFocusKey,
    drivers: tuple[str, ...],
    facts: tuple[str, ...],
    sections: tuple[str, ...],
    purpose: str,
) -> AccountingFocusDefinition:
    return AccountingFocusDefinition(
        focus_key=key,
        parent_topic=ACCOUNTING_FOCUS_TO_TOPIC[key],
        allowed_driver_fields=drivers,
        fact_tokens=facts,
        note_section_tokens=sections,
        purpose=purpose,
    )


ACCOUNTING_FOCUS_REGISTRY: dict[AccountingFocusKey, AccountingFocusDefinition] = {
    AccountingFocusKey.qoe_revenue: _definition(
        AccountingFocusKey.qoe_revenue,
        ("revenue_growth_near", "revenue_growth_mid", "revenue_growth_long"),
        ("revenue", "contract", "deferred", "receivable", "price", "volume", "growth"),
        ("note_revenue", "note_contract", "note_receivable", "revenue"),
        "Assess revenue quality, recognition, and the durability of reported growth.",
    ),
    AccountingFocusKey.qoe_opex_and_compensation: _definition(
        AccountingFocusKey.qoe_opex_and_compensation,
        ("ebit_margin_start", "ebit_margin_target", "sbc_addback"),
        ("operating", "opex", "compensation", "stockbased", "sharebased", "sbc", "ebit", "margin"),
        ("note_compensation", "note_stock", "note_share", "note_operating", "compensation"),
        "Assess recurring operating cost and compensation pressure on earnings quality.",
    ),
    AccountingFocusKey.qoe_nonrecurring: _definition(
        AccountingFocusKey.qoe_nonrecurring,
        ("ebit_margin_start", "ebit_margin_target"),
        ("restructur", "impairment", "nonrecurr", "reorganization", "disposal",
         "unusual", "severance", "writeoff", "writedown", "abandonment", "settlement"),
        ("note_restructur", "note_impairment", "note_discontinued", "note_other"),
        "Identify disclosed items that may be unusual, non-recurring, or normalization candidates.",
    ),
    AccountingFocusKey.qoe_cash_conversion: _definition(
        AccountingFocusKey.qoe_cash_conversion,
        ("nwc_start", "nwc_target", "cash_conversion"),
        ("cash_conversion", "cffo", "operatingcash", "capex", "accrual", "dso", "dio", "dpo", "workingcapital"),
        ("note_cashflow", "note_receivable", "note_inventory", "note_payable", "cash_flow"),
        "Assess conversion of reported earnings into operating cash and working capital behavior.",
    ),
    AccountingFocusKey.bridge_cash_debt_investments: _definition(
        AccountingFocusKey.bridge_cash_debt_investments,
        ("net_debt", "non_operating_assets", "cash", "total_debt", "shares_outstanding"),
        ("cash", "debt", "investment", "marketable", "securit", "net_debt", "minority", "preferred", "shares"),
        ("note_debt", "note_cash", "note_investment", "note_fair_value", "debt"),
        "Assemble the cash, debt, investments, and other non-operating bridge components.",
    ),
    AccountingFocusKey.bridge_leases_pensions_claims: _definition(
        AccountingFocusKey.bridge_leases_pensions_claims,
        ("lease_liabilities", "pension_deficit", "minority_interest", "preferred_equity"),
        ("lease", "pension", "retirement", "claim", "litigation", "contingenc", "minority", "preferred"),
        ("note_leases", "note_lease", "note_pension", "note_retirement", "note_contingenc", "note_claim"),
        "Identify lease, pension, claims, and similar non-operating obligations affecting equity value.",
    ),
    AccountingFocusKey.tax_contingencies: _definition(
        AccountingFocusKey.tax_contingencies,
        ("tax_rate_start", "tax_rate_target"),
        ("tax", "uncertain", "contingenc", "effective_tax", "deferred_tax", "nols", "valuation_allowance"),
        ("note_taxes", "note_tax", "note_contingenc", "note_income_tax"),
        "Assess tax-rate sustainability and disclosed tax contingencies or exposures.",
    ),
    AccountingFocusKey.segments_disclosure: _definition(
        AccountingFocusKey.segments_disclosure,
        ("revenue_growth_near", "revenue_growth_mid", "ebit_margin_target"),
        ("segment", "revenue", "operating_income", "margin", "geograph", "product", "disaggregat"),
        ("note_segments", "note_segment", "note_disaggreg", "segment"),
        "Use segment and disaggregated disclosure to distinguish business mix and economics.",
    ),
}


class AccountingFocusContext(ContractModel):
    """Typed, bounded evidence view supplied to one accounting focus."""

    focus_key: AccountingFocusKey
    parent_topic: AccountingTopic
    parent_packet_id: int | str | None = None
    ticker: str
    period_vintage_metadata: dict[str, Any] = Field(default_factory=dict)
    selected_facts: list[EvidencePacketFact] = Field(default_factory=list)
    selected_snippets: list[TextEvidenceSnippet] = Field(default_factory=list)
    selected_source_refs: list[EvidenceSourceRef] = Field(default_factory=list)
    selected_driver_fields: dict[str, Any] = Field(default_factory=dict)
    packet_status: AccountingPacketStatus
    missing_data_status: str
    coverage_notes: list[str] = Field(default_factory=list)


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return str(value).lower()


def _dump(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="python")
    raise TypeError("packet must be an EvidencePacket or mapping/model dump")


def _metadata_text(metadata: Mapping[str, Any]) -> str:
    relevant = {
        key: value
        for key, value in metadata.items()
        if key in {
            "fact_role", "driver_field", "xbrl_fact_name", "section_key",
            "note_key", "accession", "filing_date", "period", "period_end",
            "form_type", "taxonomy", "dimensions", "series_position",
        }
    }
    return " ".join(_text(value) for value in relevant.values())


def _date_key(value: Any) -> str:
    return _text(value).replace("/", "")


def _fact_score(fact: EvidencePacketFact, definition: AccountingFocusDefinition) -> tuple[int, str, str, str]:
    metadata = fact.metadata or {}
    role = _text(metadata.get("fact_role"))
    driver = _text(metadata.get("driver_field"))
    searchable = f"{_text(fact.fact_name)} {_metadata_text(metadata)}"
    token_hits = sum(1 for token in definition.fact_tokens if token in searchable)
    is_driver = role == "current_model_driver"
    driver_allowed = driver in definition.allowed_driver_fields
    if is_driver and not driver_allowed:
        return (-1000, "", "", fact.fact_id)
    if not token_hits and not (is_driver and driver_allowed):
        return (-1000, "", "", fact.fact_id)
    score = token_hits * 10
    if is_driver and driver_allowed:
        score += 35
    if role == "xbrl_structured_fact":
        score += 15
    if role in {"reported_historical_anchor", "reported_bridge_anchor"}:
        score += 8
    if metadata.get("dimensions"):
        score += 20
    return score, _date_key(metadata.get("filing_date")), _date_key(metadata.get("period_end") or fact.metadata.get("period")), fact.fact_id


def _snippet_score(snippet: TextEvidenceSnippet, definition: AccountingFocusDefinition) -> tuple[int, str, str]:
    metadata = snippet.metadata or {}
    section = f"{_text(metadata.get('section_key'))} {_text(metadata.get('note_key'))}"
    text = f"{section} {_text(snippet.text)}"
    section_hits = sum(1 for token in definition.note_section_tokens if token in section)
    text_hits = sum(1 for token in definition.note_section_tokens if token in text)
    if not section_hits and not text_hits:
        return -1000, "", snippet.snippet_id
    return section_hits * 30 + text_hits * 5, _date_key(metadata.get("filing_date")), snippet.snippet_id


def _source_vintages(packet: EvidencePacket) -> list[dict[str, Any]]:
    vintages: dict[tuple[str, str, str], dict[str, Any]] = {}
    for source in packet.source_refs:
        metadata = source.metadata or {}
        accession = _text(metadata.get("accession"))
        filing_date = _text(metadata.get("filing_date"))
        form_type = _text(metadata.get("form_type"))
        if accession or filing_date:
            vintages[(accession, filing_date, form_type)] = {
                "accession": accession or None,
                "filing_date": filing_date or None,
                "form_type": form_type or None,
            }
    for fact in packet.facts:
        metadata = fact.metadata or {}
        accession = _text(metadata.get("accession"))
        filing_date = _text(metadata.get("filing_date"))
        form_type = _text(metadata.get("form_type"))
        if accession or filing_date:
            vintages[(accession, filing_date, form_type)] = {
                "accession": accession or None,
                "filing_date": filing_date or None,
                "form_type": form_type or None,
            }
    return sorted(vintages.values(), key=lambda item: (item["filing_date"] or "", item["accession"] or ""), reverse=True)


def select_accounting_focus(
    packet: EvidencePacket | Mapping[str, Any],
    focus_key: AccountingFocusKey | str,
    *,
    parent_topic: AccountingTopic | str | None = None,
) -> AccountingFocusContext:
    """Select one deterministic focus context from a full persisted packet."""

    try:
        key = focus_key if isinstance(focus_key, AccountingFocusKey) else AccountingFocusKey(str(focus_key))
    except ValueError as exc:
        raise ValueError(f"unsupported accounting focus key: {focus_key!r}") from exc
    definition = ACCOUNTING_FOCUS_REGISTRY[key]
    expected_topic = definition.parent_topic
    if parent_topic is not None:
        try:
            supplied_topic = parent_topic if isinstance(parent_topic, AccountingTopic) else AccountingTopic(str(parent_topic))
        except ValueError as exc:
            raise ValueError(f"unsupported accounting parent topic: {parent_topic!r}") from exc
        if supplied_topic != expected_topic:
            raise ValueError(f"focus {key.value!r} belongs to {expected_topic.value!r}, not {supplied_topic.value!r}")

    packet_data = _dump(packet)
    persisted = EvidencePacket.model_validate(packet_data)
    packet_topic = (persisted.run_metadata or {}).get("accounting_topic")
    if packet_topic is None and persisted.profile_name.startswith("accounting_"):
        packet_topic = persisted.profile_name.removeprefix("accounting_")
    if packet_topic is not None and str(packet_topic) != expected_topic.value:
        raise ValueError(f"focus {key.value!r} is incompatible with packet topic {packet_topic!r}")

    ranked_facts = sorted(
        ((fact, _fact_score(fact, definition)) for fact in persisted.facts),
        key=lambda item: item[1], reverse=True,
    )
    selected_facts: list[EvidencePacketFact] = []
    seen_fact_ids: set[str] = set()
    fact_name_counts: dict[str, int] = {}
    fact_name_period_counts: dict[tuple[str, str], int] = {}
    for fact, score in ranked_facts:
        if score[0] < 0 or fact.fact_id in seen_fact_ids:
            continue
        fact_name_key = _text(fact.fact_name)
        is_current_driver = _text((fact.metadata or {}).get("fact_role")) == "current_model_driver"
        period_key = _text(
            (fact.metadata or {}).get("period_end")
            or (fact.metadata or {}).get("period")
            or (fact.metadata or {}).get("period_start")
        )
        name_period_key = (fact_name_key, period_key)
        period_count = fact_name_period_counts.get(name_period_key, 0)
        if (fact_name_counts.get(fact_name_key, 0) >= 5 or period_count >= 3) and not is_current_driver:
            continue
        fact_name_counts[fact_name_key] = fact_name_counts.get(fact_name_key, 0) + 1
        fact_name_period_counts[name_period_key] = period_count + 1
        selected_facts.append(fact)
        seen_fact_ids.add(fact.fact_id)
        if len(selected_facts) == 25:
            break

    ranked_snippets = sorted(
        ((snippet, _snippet_score(snippet, definition)) for snippet in persisted.snippets),
        key=lambda item: item[1], reverse=True,
    )
    selected_snippets: list[TextEvidenceSnippet] = []
    seen_snippet_ids: set[str] = set()
    for snippet, score in ranked_snippets:
        if score[0] < 0 or snippet.snippet_id in seen_snippet_ids:
            continue
        selected_snippets.append(snippet)
        seen_snippet_ids.add(snippet.snippet_id)
        if len(selected_snippets) == 5:
            break

    selected_source_ids = {snippet.source_ref_id for snippet in selected_snippets}
    selected_source_ids.update(
        str((fact.metadata or {}).get("source_ref_id"))
        for fact in selected_facts
        if (fact.metadata or {}).get("source_ref_id")
    )
    selected_source_refs = [
        source for source in persisted.source_refs if source.source_ref_id in selected_source_ids
    ]
    selected_driver_fields: dict[str, Any] = {}
    for fact in selected_facts:
        metadata = fact.metadata or {}
        driver = metadata.get("driver_field")
        if metadata.get("fact_role") == "current_model_driver" and driver in definition.allowed_driver_fields:
            selected_driver_fields.setdefault(str(driver), fact.value)
    for field in definition.allowed_driver_fields:
        if field in selected_driver_fields:
            continue
        if field in (persisted.run_metadata or {}).get("current_model_fields", {}):
            selected_driver_fields[field] = persisted.run_metadata["current_model_fields"][field]

    vintages = _source_vintages(persisted)
    selected_vintages = {
        _text(fact.metadata.get("accession"))
        for fact in selected_facts
        if fact.metadata.get("accession")
    }
    periods = sorted({_text(fact.metadata.get("period") or fact.metadata.get("period_end") or fact.metadata.get("period_start")) for fact in selected_facts if fact.metadata.get("period") or fact.metadata.get("period_end") or fact.metadata.get("period_start")})
    notes: list[str] = []
    if not selected_facts and not selected_snippets:
        notes.append("No facts or note snippets matched this accounting focus.")
    if len(vintages) > 1 or len(selected_vintages) > 1:
        notes.append("Multiple filing vintages are present; selected evidence retains accession and filing metadata.")
    if len(selected_facts) < 10:
        notes.append(f"Only {len(selected_facts)} relevant facts were available; target is 10-25.")
    if len(selected_snippets) < 2:
        notes.append(f"Only {len(selected_snippets)} relevant snippets were available; target is 2-5.")
    if not selected_driver_fields:
        notes.append("No allowed current model driver fields were available.")

    run_metadata = persisted.run_metadata or {}
    source_quality = _text(run_metadata.get("source_quality"))
    if not selected_facts and not selected_snippets:
        status = AccountingPacketStatus.unavailable if source_quality in {"placeholder", "unavailable", "error"} else AccountingPacketStatus.missing_evidence
        missing_status = "unavailable" if status == AccountingPacketStatus.unavailable else "missing_relevant_evidence"
    elif len(selected_facts) >= 10 and len(selected_snippets) >= 2:
        status, missing_status = AccountingPacketStatus.complete, "none"
    else:
        status, missing_status = AccountingPacketStatus.partial, "partial_coverage"

    return AccountingFocusContext(
        focus_key=key,
        parent_topic=expected_topic,
        parent_packet_id=persisted.packet_id,
        ticker=persisted.ticker,
        period_vintage_metadata={
            "packet_generated_at": persisted.generated_at,
            "bundle_id": persisted.bundle_id,
            "periods": periods,
            "vintages": vintages,
            "selected_accessions": sorted(selected_vintages),
        },
        selected_facts=selected_facts,
        selected_snippets=selected_snippets,
        selected_source_refs=selected_source_refs,
        selected_driver_fields=selected_driver_fields,
        packet_status=status,
        missing_data_status=missing_status,
        coverage_notes=notes,
    )


__all__ = [
    "ACCOUNTING_FOCUS_REGISTRY",
    "AccountingFocusContext",
    "AccountingFocusDefinition",
    "select_accounting_focus",
]
