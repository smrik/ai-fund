from __future__ import annotations

import os
from typing import Any

from src.contracts.accounting_evidence import AccountingTopic
from src.contracts.evidence_packet import EvidencePacket, EvidenceSourceQuality
import src.stage_04_pipeline.evidence_packets as facade
from src.stage_04_pipeline.evidence.assembly import PacketMaterial, assemble_packet


ACCOUNTING_PROFILE_NAMES = (
    "accounting_qoe",
    "accounting_ev_equity_bridge",
    "accounting_contingencies_and_taxes",
    "accounting_segments_and_disclosure",
)


_ACCOUNTING_PACKET_CONFIGS: dict[str, dict[str, Any]] = {
    "accounting_qoe": {
        "topic": AccountingTopic.qoe.value,
        "retrieval_profile": "qoe",
        "allowed_driver_fields": (
            "revenue_growth_near",
            "revenue_growth_mid",
            "ebit_margin_start",
            "ebit_margin_target",
            "tax_rate_start",
            "tax_rate_target",
        ),
        "note_keys": (
            "note_revenue",
            "note_restructuring",
            "note_impairment",
            "note_acquisitions",
            "note_sbc",
            "note_contingencies",
            "note_fair_value",
        ),
        "xbrl_concepts": (
            "Revenues",
            "RevenueFromContractWithCustomerExcludingAssessedTax",
            "OperatingIncomeLoss",
            "NetCashProvidedByUsedInOperatingActivities",
            "PaymentsToAcquirePropertyPlantAndEquipment",
            "ShareBasedCompensation",
            "IncomeTaxExpenseBenefit",
        ),
    },
    "accounting_ev_equity_bridge": {
        "topic": AccountingTopic.ev_equity_bridge.value,
        "retrieval_profile": "accounting_recast",
        "allowed_driver_fields": (
            "net_debt",
            "non_operating_assets",
            "lease_liabilities",
            "minority_interest",
            "preferred_equity",
            "pension_deficit",
            "shares_outstanding",
        ),
        "note_keys": (
            "note_leases",
            "note_pension",
            "note_debt",
            "note_fair_value",
            "note_segments",
        ),
        "xbrl_concepts": (
            "CashAndCashEquivalentsAtCarryingValue",
            "ShortTermInvestments",
            "LongTermDebt",
            "LongTermDebtCurrent",
            "LongTermDebtNoncurrent",
            "OperatingLeaseLiability",
            "OperatingLeaseLiabilityCurrent",
            "FinanceLeaseLiability",
            "FinanceLeaseLiabilityCurrent",
            "MinorityInterest",
            "PreferredStockValue",
            "DefinedBenefitPlanBenefitObligation",
            "DefinedBenefitPlanFairValueOfPlanAssets",
            "CommonStockSharesOutstanding",
        ),
    },
    "accounting_contingencies_and_taxes": {
        "topic": AccountingTopic.contingencies_and_taxes.value,
        "retrieval_profile": "accounting_recast",
        "allowed_driver_fields": (
            "tax_rate_start",
            "tax_rate_target",
            "wacc",
            "net_debt",
            "ebit_margin_target",
        ),
        "note_keys": (
            "note_contingencies",
            "note_taxes",
            "note_debt",
            "note_fair_value",
        ),
        "xbrl_concepts": (
            "IncomeTaxExpenseBenefit",
            "IncomeTaxesPaidNet",
            "IncomeTaxesPayableCurrent",
            "DeferredIncomeTaxExpenseBenefit",
            "LiabilityForUnrecognizedTaxBenefits",
            "UnrecognizedTaxBenefitsThatWouldImpactEffectiveTaxRate",
            "LossContingencyAccrualAtCarryingValue",
        ),
    },
    "accounting_segments_and_disclosure": {
        "topic": AccountingTopic.segments_and_disclosure.value,
        "retrieval_profile": "accounting_recast",
        "allowed_driver_fields": (
            "revenue_growth_near",
            "revenue_growth_mid",
            "ebit_margin_start",
            "ebit_margin_target",
        ),
        "note_keys": (
            "note_segments",
            "note_revenue",
            "note_fair_value",
        ),
        "xbrl_concepts": (
            "Revenues",
            "RevenueFromContractWithCustomerExcludingAssessedTax",
            "OperatingIncomeLoss",
            "SegmentReportingSegmentRevenue",
            "SegmentReportingSegmentProfitLoss",
        ),
    },
}


def _evidence_chars() -> int:
    try:
        return max(100, int(os.getenv("ALPHA_POD_EVIDENCE_CHARS", "420")))
    except (ValueError, TypeError):
        return 420


def _clean_text(text: str | None, *, max_chars: int = 320) -> str:
    cleaned = " ".join(str(text or "").split())
    if len(cleaned) <= max_chars:
        return cleaned
    return f"{cleaned[: max_chars - 3].rstrip()}..."


def _collector_status(collector: str, status: str, **extra: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"collector": collector, "status": status}
    payload.update(extra)
    return payload


def _accounting_fact(
    profile_name: str,
    source_ref_id: str,
    fact_name: str,
    value: Any,
    *,
    unit: str | None = None,
    period: str | None = None,
    source_lineage: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    if value is None:
        return None
    fact_metadata: dict[str, Any] = {"source_ref_id": source_ref_id}
    if source_lineage:
        fact_metadata["source_lineage"] = source_lineage
    if period:
        fact_metadata["period"] = period
    if metadata:
        fact_metadata.update(metadata)
    return {
        "fact_id": f"fact:{profile_name}:{fact_name}",
        "fact_name": fact_name,
        "value": value,
        "unit": unit,
        "metadata": fact_metadata,
    }


def _collect_xbrl_accounting_facts(
    ticker: str,
    profile_name: str,
    topic: str,
    concepts: tuple[str, ...],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    try:
        result = facade.get_xbrl_fact_evidence(
            ticker,
            concepts,
            max_facts_per_concept=12,
        )
    except Exception as exc:
        result = {
            "status": "error",
            "facts": [],
            "fact_count": 0,
            "errors": [str(exc)],
        }

    xbrl_status = str(result.get("status") or "error")
    records = list(result.get("facts") or [])
    source_refs: list[dict[str, Any]] = []
    source_ref_ids: set[str] = set()
    facts: list[dict[str, Any]] = []

    for record in records:
        record_metadata = dict(record.get("metadata") or {})
        accession = str(record_metadata.get("accession") or "unknown")
        source_ref_id = f"xbrl:{ticker.upper()}:{accession}"
        source_locator = record.get("source_locator") or f"edgar://{ticker}/{accession}"
        if source_ref_id not in source_ref_ids:
            source_ref_ids.add(source_ref_id)
            source_refs.append(
                {
                    "source_ref_id": source_ref_id,
                    "source_kind": "sec_xbrl_fact",
                    "source_label": f"SEC XBRL facts {accession}",
                    "source_locator": source_locator,
                    "metadata": {
                        "accession": record_metadata.get("accession"),
                        "filing_date": record_metadata.get("filing_date"),
                        "form_type": record_metadata.get("form_type"),
                        "taxonomy": record_metadata.get("taxonomy"),
                    },
                }
            )

        concept = str(record.get("fact_name") or "unknown")
        fact_name = f"xbrl_{concept.replace(':', '_')}"
        fact_metadata = {
            **record_metadata,
            "fact_role": "xbrl_structured_fact",
            "accounting_topic": topic,
            "source_ref_id": source_ref_id,
            "source_locator": source_locator,
            "numeric_value": record.get("numeric_value"),
            "xbrl_fact_name": concept,
        }
        value = record.get("numeric_value")
        if value is None:
            value = record.get("value")
        facts.append(
            {
                "fact_id": str(record.get("fact_id") or f"fact:{profile_name}:{fact_name}"),
                "fact_name": fact_name,
                "value": value,
                "unit": record.get("unit"),
                "metadata": fact_metadata,
            }
        )

    collector_status = {
        "collector": "accounting_xbrl_facts",
        "status": (
            "ok"
            if xbrl_status == "ok" and facts
            else "partial"
            if xbrl_status == "partial" and facts
            else "error"
            if xbrl_status == "error"
            else "missing"
        ),
        "xbrl_status": xbrl_status,
        "fact_count": len(facts),
        "concept_count": len(concepts),
        "errors": list(result.get("errors") or []),
    }
    metadata = {
        "xbrl_retrieval_status": xbrl_status,
        "xbrl_fact_count": len(facts),
        "xbrl_concepts": list(concepts),
        "xbrl_errors": list(result.get("errors") or []),
        "xbrl_cik": result.get("cik"),
    }
    return facts, source_refs, collector_status, metadata


def _accounting_section_counts(bundle: Any) -> dict[str, int]:
    summary = getattr(bundle, "retrieval_summary", {}) or {}
    coverage = summary.get("section_coverage", {}) if isinstance(summary, dict) else {}
    nested = coverage.get("by_section_key") if isinstance(coverage, dict) else None
    if isinstance(nested, dict):
        return {str(key): int(value) for key, value in nested.items()}
    if isinstance(coverage, dict):
        return {
            str(key): int(value)
            for key, value in coverage.items()
            if isinstance(value, (int, float))
        }
    return {}


def _accounting_topic_coverage(bundle: Any, note_keys: tuple[str, ...]) -> dict[str, str]:
    if bundle is None:
        return {key: "retrieval_unavailable" for key in note_keys}
    summary = getattr(bundle, "retrieval_summary", {}) or {}
    selected = {
        str(key)
        for key in (summary.get("selected_section_keys", []) if isinstance(summary, dict) else [])
    }
    available = set(_accounting_section_counts(bundle))
    if not available and not getattr(bundle, "sources", None):
        return {key: "retrieval_unavailable" for key in note_keys}
    return {
        key: (
            "selected"
            if key in selected
            else "available_not_selected"
            if key in available
            else "searched_absent"
        )
        for key in note_keys
    }


def _collect_accounting_inputs(ticker: str, profile_name: str) -> dict[str, Any]:
    config = _ACCOUNTING_PACKET_CONFIGS[profile_name]
    topic = str(config["topic"])
    retrieval_profile = str(config["retrieval_profile"])
    allowed_driver_fields = tuple(config["allowed_driver_fields"])
    source_refs: list[dict[str, Any]] = []
    facts: list[dict[str, Any]] = []
    snippets: list[dict[str, Any]] = []
    statuses: list[dict[str, Any]] = []
    model_inputs: Any = None
    bundle: Any = None

    xbrl_facts, xbrl_refs, xbrl_status, xbrl_metadata = _collect_xbrl_accounting_facts(
        ticker,
        profile_name,
        topic,
        tuple(config.get("xbrl_concepts") or ()),
    )
    facts.extend(xbrl_facts)
    statuses.append(xbrl_status)

    try:
        bundle = facade.get_agent_filing_context(
            ticker,
            profile_name=retrieval_profile,
            include_10k=True,
            ten_q_limit=2,
            use_cache=True,
        )
    except Exception as exc:
        statuses.append(_collector_status("accounting_filing_context", "error", message=str(exc)))
    else:
        sources = list(getattr(bundle, "sources", []) or [])
        for source in sources:
            accession_no = source.get("accession_no") or "unknown"
            doc_name = source.get("doc_name") or accession_no
            ref_id = f"filing:{accession_no}"
            source_refs.append(
                {
                    "source_ref_id": ref_id,
                    "source_kind": source.get("form_type") or "filing",
                    "source_label": f"{source.get('form_type') or 'Filing'} {source.get('filing_date') or accession_no}",
                    "source_locator": source.get("source_locator") or f"edgar://{ticker}/{accession_no}/{doc_name}",
                    "metadata": {
                        "filing_date": source.get("filing_date"),
                        "doc_name": doc_name,
                        "section_keys": source.get("section_keys") or [],
                    },
                }
            )
        selected_chunks = list(getattr(bundle, "selected_chunks", []) or [])
        bundle_summary = getattr(bundle, "retrieval_summary", {}) or {}
        selected_section_filter = {
            str(key)
            for key in (
                bundle_summary.get("selected_section_keys", [])
                if isinstance(bundle_summary, dict)
                else []
            )
        }
        for chunk in selected_chunks:
            if (
                selected_section_filter
                and str(chunk.section_key) not in selected_section_filter
            ):
                continue
            text = _clean_text(chunk.text, max_chars=max(_evidence_chars(), 900))
            if not text:
                continue
            source_ref_id = f"filing:{chunk.accession_no}"
            snippets.append(
                {
                    "snippet_id": f"snippet:{profile_name}:{chunk.accession_no}:{chunk.chunk_index}",
                    "source_ref_id": source_ref_id,
                    "text": text,
                    "metadata": {
                        "topic": topic,
                        "section_key": chunk.section_key,
                        "score": chunk.score,
                        "filing_date": chunk.filing_date,
                        "form_type": getattr(chunk, "form_type", None),
                        "locator": f"edgar://{ticker}/{chunk.accession_no}/{chunk.section_key}/chunk-{chunk.chunk_index}",
                    },
                }
            )
            if len(snippets) >= 8:
                break
        statuses.append(
            _collector_status(
                "accounting_filing_context",
                "ok" if snippets else "partial",
                retrieval_profile=retrieval_profile,
                source_count=len(sources),
                selected_chunk_count=len(selected_chunks),
            )
        )

    source_refs.extend(xbrl_refs)

    try:
        model_inputs = facade.build_valuation_inputs(ticker)
    except Exception as exc:
        statuses.append(_collector_status("accounting_valuation_inputs", "error", message=str(exc)))
    else:
        if model_inputs is None:
            statuses.append(_collector_status("accounting_valuation_inputs", "missing"))
        else:
            model_ref_id = f"model-assumptions:{ticker}"
            source_refs.append(
                {
                    "source_ref_id": model_ref_id,
                    "source_kind": "valuation_inputs",
                    "source_label": "Current deterministic valuation drivers",
                    "source_locator": f"valuation://{ticker}/inputs",
                    "metadata": {"as_of_date": getattr(model_inputs, "as_of_date", None)},
                }
            )
            drivers = getattr(model_inputs, "drivers", None)
            lineage = getattr(model_inputs, "source_lineage", {}) or {}
            for field_name in allowed_driver_fields:
                value = getattr(drivers, field_name, None) if drivers is not None else None
                fact = _accounting_fact(
                    profile_name,
                    model_ref_id,
                    field_name,
                    value,
                    source_lineage=lineage.get(field_name),
                    metadata={"driver_field": field_name, "fact_role": "current_model_driver"},
                )
                if fact is not None:
                    facts.append(fact)
            statuses.append(
                _collector_status(
                    "accounting_valuation_inputs",
                    "ok",
                    allowed_driver_count=len(allowed_driver_fields),
                )
            )

    ciq: dict[str, Any] = {}
    mkt: dict[str, Any] = {}
    hist: dict[str, Any] = {}
    ciq_history: list[dict[str, Any]] = []
    if topic == AccountingTopic.ev_equity_bridge.value:
        try:
            ciq = facade.get_ciq_snapshot(ticker) or {}
            ciq_history = list(facade.get_ciq_nwc_history(ticker) or [])
            statuses.append(_collector_status("ciq_accounting_snapshot", "ok" if ciq else "missing"))
        except Exception as exc:
            statuses.append(_collector_status("ciq_accounting_snapshot", "error", message=str(exc)))
        try:
            mkt = facade.get_market_data(ticker, use_cache=True) or {}
            statuses.append(_collector_status("market_accounting_snapshot", "ok" if mkt else "missing"))
        except Exception as exc:
            statuses.append(_collector_status("market_accounting_snapshot", "error", message=str(exc)))
        bridge_ref_id = f"balance-sheet:{ticker}"
        source_refs.append(
            {
                "source_ref_id": bridge_ref_id,
                "source_kind": "deterministic_balance_sheet",
                "source_label": "Current balance-sheet and bridge snapshot",
                "source_locator": f"balance-sheet://{ticker}/latest",
                "metadata": {"ciq_as_of_date": ciq.get("as_of_date")},
            }
        )
        for fact_name, value, unit in (
            ("cash", ciq.get("cash") if ciq else mkt.get("cash"), "USD"),
            ("total_debt", ciq.get("total_debt") if ciq else mkt.get("total_debt"), "USD"),
            ("shares_outstanding_snapshot", ciq.get("shares_outstanding") if ciq else mkt.get("shares_outstanding"), "shares"),
        ):
            fact = _accounting_fact(
                profile_name,
                bridge_ref_id,
                fact_name,
                value,
                unit=unit,
                period=ciq.get("as_of_date") if ciq else None,
                metadata={"fact_role": "reported_bridge_anchor"},
            )
            if fact is not None:
                facts.append(fact)
    if topic == AccountingTopic.qoe.value:
        try:
            hist = facade.get_historical_financials(ticker, use_cache=True) or {}
            statuses.append(_collector_status("historical_qoe_financials", "ok" if hist.get("revenue") else "missing"))
        except Exception as exc:
            statuses.append(_collector_status("historical_qoe_financials", "error", message=str(exc)))
        try:
            mkt = facade.get_market_data(ticker, use_cache=True) or {}
            statuses.append(_collector_status("market_qoe_snapshot", "ok" if mkt else "missing"))
        except Exception as exc:
            statuses.append(_collector_status("market_qoe_snapshot", "error", message=str(exc)))
        try:
            ciq = facade.get_ciq_snapshot(ticker) or {}
            ciq_history = list(facade.get_ciq_nwc_history(ticker) or [])
            statuses.append(_collector_status("ciq_qoe_snapshot", "ok" if ciq else "missing"))
        except Exception as exc:
            statuses.append(_collector_status("ciq_qoe_snapshot", "error", message=str(exc)))
        qoe_ref_id = f"deterministic-qoe:{ticker}"
        source_refs.append(
            {
                "source_ref_id": qoe_ref_id,
                "source_kind": "deterministic_qoe",
                "source_label": "Deterministic QoE and historical financial signals",
                "source_locator": f"qoe://{ticker}/deterministic",
                "metadata": {"sector": getattr(model_inputs, "sector", None) if model_inputs else mkt.get("sector")},
            }
        )
        qoe = {}
        try:
            sector = str(getattr(model_inputs, "sector", None) or mkt.get("sector") or "").strip()
            qoe = facade.compute_qoe_signals(ticker, sector, ciq, ciq_history, hist, mkt) or {}
            statuses.append(_collector_status("deterministic_qoe_signals", "ok", fact_count=len(qoe)))
        except Exception as exc:
            statuses.append(_collector_status("deterministic_qoe_signals", "error", message=str(exc)))
        latest_fields = {
            "reported_ebit": (hist.get("operating_income") or [None])[0],
            "reported_revenue": (hist.get("revenue") or [None])[0],
            "reported_cffo": (hist.get("cffo") or [None])[0],
            "reported_capex": (hist.get("capex") or [None])[0],
            "reported_da": (hist.get("da") or [None])[0],
            "reported_sbc": hist.get("sbc"),
            "effective_tax_rate_avg": hist.get("effective_tax_rate_avg"),
        }
        for fact_name, value in latest_fields.items():
            fact = _accounting_fact(
                profile_name,
                qoe_ref_id,
                fact_name,
                value,
                unit="USD" if fact_name.startswith("reported_") else None,
                metadata={"fact_role": "reported_historical_anchor", "series_position": "latest_available"},
            )
            if fact is not None:
                facts.append(fact)
        for fact_name in (
            "qoe_score",
            "qoe_flag",
            "sloan_accruals_ratio",
            "cash_conversion",
            "dso_current",
            "dso_baseline",
            "dso_drift",
            "dio_current",
            "dio_baseline",
            "dio_drift",
            "dpo_current",
            "dpo_baseline",
            "dpo_drift",
            "capex_da_ratio",
            "signal_scores",
            "m_score",
            "m_score_zone",
            "z_score",
            "z_score_zone",
            "forensic_flag",
        ):
            fact = _accounting_fact(
                profile_name,
                qoe_ref_id,
                fact_name,
                qoe.get(fact_name),
                metadata={"fact_role": "deterministic_qoe_signal"},
            )
            if fact is not None:
                facts.append(fact)

    coverage = _accounting_topic_coverage(bundle, tuple(config["note_keys"]))
    coverage_ref_id = source_refs[0]["source_ref_id"] if source_refs else f"retrieval-status:{profile_name}"
    for note_key, status in coverage.items():
        fact = _accounting_fact(
            profile_name,
            coverage_ref_id,
            f"topic_coverage_{note_key}",
            status,
            metadata={"fact_role": "retrieval_coverage", "section_key": note_key},
        )
        if fact is not None:
            facts.append(fact)

    retrieval_summary = getattr(bundle, "retrieval_summary", {}) or {}
    retrieval_selected_section_keys = sorted(
        {
            str(key)
            for key in (retrieval_summary.get("selected_section_keys", []) if isinstance(retrieval_summary, dict) else [])
        }
    )
    selected_section_keys = sorted(
        {
            str(snippet.get("metadata", {}).get("section_key"))
            for snippet in snippets
            if snippet.get("metadata", {}).get("section_key")
        }
    )
    authoritative_selected_section_keys = (
        retrieval_selected_section_keys or selected_section_keys
    )
    source_quality = (
        EvidenceSourceQuality.real.value
        if snippets
        else EvidenceSourceQuality.partial.value
        if source_refs or facts
        else EvidenceSourceQuality.placeholder.value
    )
    selected_source_locators = list(
        retrieval_summary.get("selected_source_locators", [])
        if isinstance(retrieval_summary, dict)
        else []
    )
    if not selected_source_locators:
        selected_source_locators = [
            str(snippet["metadata"]["locator"])
            for snippet in snippets
            if snippet.get("metadata", {}).get("locator")
        ]
    packet_source_locators = [
        str(snippet["metadata"]["locator"])
        for snippet in snippets
        if snippet.get("metadata", {}).get("locator")
    ]
    return {
        "source_refs": source_refs,
        "facts": facts,
        "snippets": snippets,
        "source_quality": source_quality,
        "run_metadata": {
            "profile_name": profile_name,
            "accounting_topic": topic,
            "retrieval_profile": retrieval_profile,
            "selected_section_keys": authoritative_selected_section_keys,
            "retrieval_selected_section_keys": retrieval_selected_section_keys,
            "packet_section_keys": selected_section_keys,
            "selected_source_locators": selected_source_locators,
            "packet_source_locators": packet_source_locators,
            "section_coverage": _accounting_section_counts(bundle),
            "topic_coverage": coverage,
            "allowed_driver_fields": list(allowed_driver_fields),
            "collector_statuses": statuses,
            "selected_chunk_count": len(snippets),
            "evidence_chars": max(_evidence_chars(), 900),
            **xbrl_metadata,
        },
    }


def build_accounting_packet(ticker: str, profile_name: str) -> EvidencePacket:
    """Build one of the four legacy accounting profile packets."""
    if profile_name not in ACCOUNTING_PROFILE_NAMES:
        raise KeyError(f"unsupported accounting evidence profile: {profile_name}")
    inputs = _collect_accounting_inputs(ticker, profile_name)
    material = PacketMaterial(
        source_refs=tuple(inputs.get("source_refs") or []),
        facts=tuple(inputs.get("facts") or []),
        snippets=tuple(inputs.get("snippets") or []),
        run_metadata=dict(inputs.get("run_metadata") or {}),
    )
    return assemble_packet(
        ticker=ticker,
        profile_name=profile_name,
        material=material,
    )
