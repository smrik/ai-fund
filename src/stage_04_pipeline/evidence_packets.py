from __future__ import annotations

import os
import re
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from typing import Any, Callable


def _evidence_chars() -> int:
    """Per-snippet char budget, set by ALPHA_POD_EVIDENCE_CHARS env var."""
    try:
        return max(100, int(os.getenv("ALPHA_POD_EVIDENCE_CHARS", "420")))
    except (ValueError, TypeError):
        return 420

from db.schema import create_tables, get_connection
from src.contracts.accounting_evidence import AccountingTopic
from src.contracts.evidence_packet import (
    EvidencePacket,
    EvidencePacketFact,
    EvidencePacketKind,
    EvidenceSourceQuality,
    EvidenceSourceRef,
    TextEvidenceSnippet,
)
from src.stage_00_data.edgar_client import get_8k_texts, get_recent_10q_texts
from src.stage_00_data.ciq_adapter import get_ciq_nwc_history, get_ciq_snapshot
from src.stage_00_data.filing_retrieval import get_agent_filing_context
from src.stage_00_data.market_data import get_historical_financials, get_market_data
from src.stage_00_data.sec_filing_metrics import get_sec_filing_metrics
from src.stage_00_data.xbrl_evidence import get_xbrl_fact_evidence
from src.stage_02_valuation.input_assembler import build_valuation_inputs
from src.stage_02_valuation.professional_dcf import default_scenario_specs, run_dcf_professional
from src.stage_03_judgment.qoe_signals import compute_qoe_signals
from src.stage_04_pipeline.comps_dashboard import build_comps_dashboard_view
from src.stage_04_pipeline.dcf_audit import build_dcf_audit_view
from src.stage_04_pipeline.agentic_handoff_profiles import get_agentic_handoff_profile


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean_text(text: str | None, *, max_chars: int = 320) -> str:
    cleaned = " ".join(str(text or "").split())
    if len(cleaned) <= max_chars:
        return cleaned
    return f"{cleaned[: max_chars - 3].rstrip()}..."


_LOW_SIGNAL_PATTERNS = (
    "incorporated by reference",
    "regulation s-k",
    "certificate of incorporation",
    "instruments defining the rights",
    "united states securities and exchange commission",
    "emerging growth company",
    "rule 405 of the securities act",
    "securities exchange act of 1934",
    "new york stock exchange",
    "debentures due",
    "standard/description",
    "this guidance requires",
    ".htm says",
)

_PROFILE_EXCERPT_KEYWORDS: dict[str, tuple[str, ...]] = {
    "earnings_update": (
        "total revenue",
        "software revenue",
        "consulting revenue",
        "infrastructure revenue",
        "revenue",
        "demand",
        "margin",
        "growth",
        "cloud",
        "outlook",
        "guidance",
        "artificial intelligence",
        "generative ai",
    ),
    "company_analysis": (
        "revenue",
        "margin",
        "profit",
        "cash flow",
        "segment",
        "software",
        "consulting",
        "infrastructure",
    ),
    "industry_analysis": (
        "industry",
        "market",
        "demand",
        "competition",
        "cloud",
        "artificial intelligence",
        "generative ai",
        "spending",
    ),
    "risk_review": (
        "risk",
        "cybersecurity",
        "competition",
        "debt",
        "liquidity",
        "execution",
        "regulation",
        "macroeconomic",
    ),
}

_EARNINGS_SIGNAL_TERMS = (
    "guidance",
    "outlook",
    "total revenue",
    "revenue year-to-year",
    "earnings per share",
    "operating income",
    "free cash flow",
    "cash flow",
    "gross profit",
    "segment profit",
    "raised",
    "lowered",
)


def _is_meaningful_evidence_text(text: str | None) -> bool:
    cleaned = " ".join(str(text or "").split())
    lower = cleaned.lower()
    if any(pattern in lower for pattern in _LOW_SIGNAL_PATTERNS):
        return False
    if len(cleaned) < 120:
        short_signal_terms = (
            "revenue growth",
            "guidance",
            "demand",
            "hybrid cloud",
            "execution risk",
            "client spending",
            "margin",
            "cash flow",
            "profit",
            "software",
            "consulting",
        )
        if len(cleaned) < 60 or not any(term in lower for term in short_signal_terms):
            return False
    if lower.startswith("item ") and len(cleaned) < 180:
        return False
    alpha_chars = sum(char.isalpha() for char in cleaned)
    if alpha_chars / max(len(cleaned), 1) < 0.45:
        return False
    if cleaned.count("─") > 20:
        return False
    return True


_LARGE_CONTEXT_THRESHOLD = 2_000


def _relevant_excerpt(text: str | None, profile_name: str, *, max_chars: int = 360) -> str | None:
    cleaned = " ".join(str(text or "").split())
    if not cleaned:
        return None
    keywords = _PROFILE_EXCERPT_KEYWORDS.get(profile_name, ())
    lower = cleaned.lower()
    candidate_starts: list[int] = []
    for keyword in keywords:
        search_at = 0
        while True:
            idx = lower.find(keyword, search_at)
            if idx < 0:
                break
            candidate_starts.append(max(0, idx - 120))
            search_at = idx + max(len(keyword), 1)
    if not candidate_starts:
        candidate_starts.append(0)
    seen: set[int] = set()
    for start in candidate_starts:
        if start in seen:
            continue
        seen.add(start)
        excerpt = _clean_text(cleaned[start:], max_chars=max_chars)
        if _is_meaningful_evidence_text(excerpt):
            return excerpt
    return None


def _is_earnings_update_excerpt(text: str | None) -> bool:
    lower = " ".join(str(text or "").lower().split())
    if not lower:
        return False
    if any(pattern in lower for pattern in _LOW_SIGNAL_PATTERNS):
        return False
    if "financial statements and exhibits" in lower and not any(
        term in lower for term in ("revenue", "earnings", "cash flow", "guidance", "outlook")
    ):
        return False
    return any(term in lower for term in _EARNINGS_SIGNAL_TERMS)


def _comparable_period_pair(current: float, prior: float) -> bool:
    """Both positive and within 4x of each other — filters out percent-change
    columns and subtotals being misread as the prior-year comparison."""
    if current <= 0 or prior <= 0:
        return False
    ratio = current / prior
    return 0.25 <= ratio <= 4.0


def _extract_total_revenue_facts(text: str | None) -> dict[str, float]:
    cleaned = " ".join(str(text or "").replace(",", "").split())
    # Filing tables render with '$' on some columns and single spaces between
    # values, so each number allows an optional leading '$'.
    match = re.search(
        r"Total revenue\s+\$?\s*(-?\d+(?:\.\d+)?)\s+\$?\s*(-?\d+(?:\.\d+)?)"
        r"(?:\s+\$?\s*(-?\d+(?:\.\d+)?)\s+\$?\s*(-?\d+(?:\.\d+)?))?",
        cleaned,
        flags=re.IGNORECASE,
    )
    if not match:
        return {}
    current = float(match.group(1))
    prior = float(match.group(2))
    facts: dict[str, float] = {"latest_quarter_total_revenue_mm": current}
    if _comparable_period_pair(current, prior):
        facts["prior_year_quarter_total_revenue_mm"] = prior
        facts["latest_quarter_revenue_yoy_pct"] = round((current / prior - 1.0) * 100.0, 2)
    if match.group(3) is not None and match.group(4) is not None:
        ytd_current = float(match.group(3))
        ytd_prior = float(match.group(4))
        if (
            ytd_current >= current
            and ytd_prior >= prior
            and _comparable_period_pair(ytd_current, ytd_prior)
        ):
            facts["ytd_total_revenue_mm"] = ytd_current
            facts["prior_year_ytd_total_revenue_mm"] = ytd_prior
            facts["ytd_revenue_yoy_pct"] = round((ytd_current / ytd_prior - 1.0) * 100.0, 2)
    return facts


def _collector_status(name: str, status: str, **details: Any) -> dict[str, Any]:
    payload = {"collector": name, "status": status}
    payload.update(details)
    return payload


def _missing_packet(
    ticker: str,
    profile_name: str,
    *,
    reason: str,
    source_quality: EvidenceSourceQuality,
    collector_statuses: list[dict[str, Any]],
    source_refs: list[dict[str, Any]] | None = None,
    facts: list[dict[str, Any]] | None = None,
    snippets: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    missing_collectors = [
        status["collector"]
        for status in collector_statuses
        if status.get("status") not in {"ok", "partial"}
    ]
    return {
        "source_refs": source_refs
        or [
            {
                "source_ref_id": f"src:{profile_name}:collector-status",
                "source_kind": "collector_status",
                "source_label": f"{profile_name.replace('_', ' ').title()} collector status",
                "source_locator": f"internal://{ticker}/{profile_name}/collector-status",
                "metadata": {
                    "status": "missing_real_sources",
                    "reason": reason,
                },
            }
        ],
        "facts": facts or [],
        "snippets": snippets or [],
        "source_quality": source_quality.value,
        "run_metadata": {
            "profile_name": profile_name,
            "collector_status": "missing_real_sources",
            "reason": reason,
            "collector_statuses": collector_statuses,
            "missing_collectors": missing_collectors,
        },
    }


def _collect_company_analysis_inputs(ticker: str) -> dict[str, Any]:
    source_refs: list[dict[str, Any]] = []
    facts: list[dict[str, Any]] = []
    snippets: list[dict[str, Any]] = []
    statuses: list[dict[str, Any]] = []

    bundle = None
    try:
        bundle = get_agent_filing_context(
            ticker,
            profile_name="filings",
            include_10k=True,
            ten_q_limit=2,
            use_cache=True,
        )
    except Exception as exc:
        statuses.append(_collector_status("filing_context", "error", message=str(exc)))
    else:
        if bundle is not None and getattr(bundle, "sources", None):
            for source in bundle.sources:
                accession_no = source.get("accession_no") or "unknown"
                doc_name = source.get("doc_name") or accession_no
                form_type = source.get("form_type") or "filing"
                source_refs.append(
                    {
                        "source_ref_id": f"filing:{accession_no}",
                        "source_kind": form_type,
                        "source_label": f"{form_type} {source.get('filing_date') or accession_no}",
                        "source_locator": f"edgar://{ticker}/{accession_no}/{doc_name}",
                        "metadata": {
                            "filing_date": source.get("filing_date"),
                            "doc_name": doc_name,
                        },
                    }
                )
            if source_refs:
                facts.extend(_filing_context_facts("company_analysis", source_refs[0]["source_ref_id"], bundle))
            selected_chunks = list(getattr(bundle, "selected_chunks", []) or [])
            for chunk in selected_chunks:
                _ec = _evidence_chars()
                excerpt = _relevant_excerpt(chunk.text, "company_analysis", max_chars=_ec)
                if excerpt is None:
                    continue
                if _ec < _LARGE_CONTEXT_THRESHOLD and not _is_meaningful_evidence_text(excerpt):
                    continue
                snippets.append(
                    {
                        "snippet_id": f"snippet:filing:{chunk.accession_no}:{chunk.chunk_index}",
                        "source_ref_id": f"filing:{chunk.accession_no}",
                        "text": excerpt,
                        "metadata": {
                            "section_key": chunk.section_key,
                            "score": chunk.score,
                            "filing_date": chunk.filing_date,
                        },
                    }
                )
                if len(snippets) >= 6:
                    break
            statuses.append(
                _collector_status(
                    "filing_context",
                    "ok" if selected_chunks else "partial",
                    selected_chunk_count=len(selected_chunks),
                )
            )
        else:
            statuses.append(_collector_status("filing_context", "missing"))

    metrics = None
    try:
        metrics = get_sec_filing_metrics(ticker)
    except Exception as exc:
        statuses.append(_collector_status("sec_metrics", "error", message=str(exc)))
    else:
        if metrics is not None:
            source_ref_id = f"sec-metrics:{metrics.source_form}:{metrics.source_filing_date}"
            source_refs.append(
                {
                    "source_ref_id": source_ref_id,
                    "source_kind": "sec_xbrl",
                    "source_label": f"{metrics.source_form} XBRL metrics {metrics.source_filing_date}",
                    "source_locator": f"sec://{ticker}/{metrics.source_form}/{metrics.source_filing_date}",
                    "metadata": {"metric_source": metrics.metric_source},
                }
            )
            metric_map = {
                "revenue_cagr_3y": metrics.revenue_cagr_3y,
                "ebit_margin_avg_3y": metrics.ebit_margin_avg_3y,
                "gross_margin_avg_3y": metrics.gross_margin_avg_3y,
                "net_debt_to_ebitda": metrics.net_debt_to_ebitda,
                "fcf_yield": metrics.fcf_yield,
                # Per-year series let the agent see acceleration/deceleration,
                # not just the point CAGR.
                "revenue_series_annual": metrics.revenue_series or None,
                "ebit_series_annual": metrics.ebit_series or None,
            }
            for fact_name, value in metric_map.items():
                if value is None:
                    continue
                facts.append(
                    {
                        "fact_id": f"fact:company_analysis:{fact_name}",
                        "fact_name": fact_name,
                        "value": value,
                        "metadata": {"source_ref_id": source_ref_id},
                    }
                )
            statuses.append(_collector_status("sec_metrics", "ok", fact_count=len(facts)))
        else:
            statuses.append(_collector_status("sec_metrics", "missing"))

    # Current model assumptions, so historical quality can be judged against
    # what the model actually assumes rather than in the abstract.
    try:
        inputs = build_valuation_inputs(ticker)
    except Exception as exc:
        statuses.append(_collector_status("model_assumptions", "error", message=str(exc)))
    else:
        if inputs is not None:
            source_ref_id = f"model-assumptions:{ticker}"
            source_refs.append(
                {
                    "source_ref_id": source_ref_id,
                    "source_kind": "valuation_inputs",
                    "source_label": "Current model growth and margin assumptions",
                    "source_locator": f"valuation://{ticker}/inputs",
                    "metadata": {"as_of_date": getattr(inputs, "as_of_date", None)},
                }
            )
            for field_name in ("revenue_growth_near", "ebit_margin_start", "ebit_margin_target"):
                if not hasattr(inputs.drivers, field_name):
                    continue
                fact = _driver_fact(
                    "company_analysis",
                    source_ref_id,
                    f"model_assumption_{field_name}",
                    getattr(inputs.drivers, field_name),
                    source_lineage=(getattr(inputs, "source_lineage", {}) or {}).get(field_name),
                )
                if fact is not None:
                    facts.append(fact)
            statuses.append(_collector_status("model_assumptions", "ok"))
        else:
            statuses.append(_collector_status("model_assumptions", "missing"))

    if snippets:
        quality = EvidenceSourceQuality.real
    elif source_refs or facts:
        quality = EvidenceSourceQuality.partial
    else:
        quality = EvidenceSourceQuality.placeholder

    if quality != EvidenceSourceQuality.real:
        return _missing_packet(
            ticker,
            "company_analysis",
            reason="missing_filing_context",
            source_quality=quality,
            collector_statuses=statuses,
            source_refs=source_refs,
            facts=facts,
            snippets=snippets,
        )
    return {
        "source_refs": source_refs,
        "facts": facts,
        "snippets": snippets,
        "source_quality": quality.value,
        "run_metadata": {
            "profile_name": "company_analysis",
            "collector_statuses": statuses,
            "selected_chunk_count": len(snippets),
        },
    }


def _collect_earnings_update_inputs(ticker: str) -> dict[str, Any]:
    source_refs: list[dict[str, Any]] = []
    facts: list[dict[str, Any]] = []
    snippets: list[dict[str, Any]] = []
    statuses: list[dict[str, Any]] = []

    earnings_docs: list[dict[str, Any]] = []
    try:
        earnings_docs = list(get_8k_texts(ticker, limit=12, max_chars_each=25_000) or [])
    except Exception as exc:
        statuses.append(_collector_status("recent_8k", "error", message=str(exc)))
    else:
        if earnings_docs:
            for idx, doc in enumerate(earnings_docs, start=1):
                accession_no = doc.get("accession_no") or f"8k-{idx}"
                source_ref_id = f"8k:{accession_no}"
                source_refs.append(
                    {
                        "source_ref_id": source_ref_id,
                        "source_kind": "8-K",
                        "source_label": f"8-K {doc.get('filing_date') or accession_no}",
                        "source_locator": f"edgar://{ticker}/{accession_no}",
                    }
                )
                if not doc.get("text"):
                    continue
                excerpt = _relevant_excerpt(doc.get("text"), "earnings_update", max_chars=_evidence_chars())
                if excerpt is None or not _is_earnings_update_excerpt(excerpt):
                    continue
                snippets.append(
                    {
                        "snippet_id": f"snippet:earnings_update:{accession_no}",
                        "source_ref_id": source_ref_id,
                        "text": excerpt,
                        "metadata": {"filing_date": doc.get("filing_date")},
                    }
                )
                for fact_name, value in _extract_total_revenue_facts(excerpt).items():
                    facts.append(
                        {
                            "fact_id": f"fact:earnings_update:{accession_no}:{fact_name}",
                            "fact_name": fact_name,
                            "value": value,
                            "metadata": {"source_ref_id": source_ref_id},
                        }
                    )
            statuses.append(_collector_status("recent_8k", "ok", filing_count=len(earnings_docs)))
        else:
            statuses.append(_collector_status("recent_8k", "missing"))

    if earnings_docs and not snippets:
        quarterly_docs: list[dict[str, Any]] = []
        try:
            quarterly_docs = list(get_recent_10q_texts(ticker, limit=2, max_chars_each=180_000) or [])
        except Exception as exc:
            statuses.append(_collector_status("recent_10q_fallback", "error", message=str(exc)))
        else:
            if quarterly_docs:
                for idx, doc in enumerate(quarterly_docs, start=1):
                    accession_no = doc.get("accession_no") or f"10q-{idx}"
                    source_ref_id = f"10q:{accession_no}"
                    source_refs.append(
                        {
                            "source_ref_id": source_ref_id,
                            "source_kind": "10-Q",
                            "source_label": f"10-Q fallback {doc.get('filing_date') or accession_no}",
                            "source_locator": f"edgar://{ticker}/{accession_no}",
                        }
                    )
                    excerpt = _relevant_excerpt(
                        doc.get("text"),
                        "earnings_update",
                        max_chars=_evidence_chars(),
                    )
                    if excerpt is None or not _is_earnings_update_excerpt(excerpt):
                        continue
                    snippets.append(
                        {
                            "snippet_id": f"snippet:earnings_update:{accession_no}",
                            "source_ref_id": source_ref_id,
                            "text": excerpt,
                            "metadata": {
                                "filing_date": doc.get("filing_date"),
                                "fallback_source": "10-Q",
                            },
                        }
                    )
                    for fact_name, value in _extract_total_revenue_facts(excerpt).items():
                        facts.append(
                            {
                                "fact_id": f"fact:earnings_update:{accession_no}:{fact_name}",
                                "fact_name": fact_name,
                                "value": value,
                                "metadata": {"source_ref_id": source_ref_id},
                            }
                        )
                statuses.append(
                    _collector_status(
                        "recent_10q_fallback",
                        "ok",
                        filing_count=len(quarterly_docs),
                        snippet_count=len(snippets),
                    )
                )
            else:
                statuses.append(_collector_status("recent_10q_fallback", "missing"))

    # The model's current growth/margin assumptions: the PM-relevant question in
    # an earnings update is whether reported results support or contradict them.
    try:
        inputs = build_valuation_inputs(ticker)
    except Exception as exc:
        statuses.append(_collector_status("model_assumptions", "error", message=str(exc)))
    else:
        if inputs is not None:
            source_ref_id = f"model-assumptions:{ticker}"
            source_refs.append(
                {
                    "source_ref_id": source_ref_id,
                    "source_kind": "valuation_inputs",
                    "source_label": "Current model growth and margin assumptions",
                    "source_locator": f"valuation://{ticker}/inputs",
                    "metadata": {"as_of_date": getattr(inputs, "as_of_date", None)},
                }
            )
            for field_name in (
                "revenue_growth_near",
                "revenue_growth_mid",
                "ebit_margin_start",
                "ebit_margin_target",
            ):
                if not hasattr(inputs.drivers, field_name):
                    continue
                fact = _driver_fact(
                    "earnings_update",
                    source_ref_id,
                    f"model_assumption_{field_name}",
                    getattr(inputs.drivers, field_name),
                    source_lineage=(getattr(inputs, "source_lineage", {}) or {}).get(field_name),
                )
                if fact is not None:
                    facts.append(fact)
            statuses.append(_collector_status("model_assumptions", "ok"))
        else:
            statuses.append(_collector_status("model_assumptions", "missing"))

    market = None
    try:
        market = get_market_data(ticker, use_cache=True)
    except TypeError:
        market = get_market_data(ticker)
    except Exception as exc:
        statuses.append(_collector_status("market_data", "error", message=str(exc)))
    else:
        if market:
            source_ref_id = "market:latest"
            source_refs.append(
                {
                    "source_ref_id": source_ref_id,
                    "source_kind": "market_data",
                    "source_label": "Latest market snapshot",
                    "source_locator": f"market://{ticker}/latest",
                }
            )
            for fact_name in (
                "current_price",
                "analyst_target_mean",
                "analyst_recommendation",
                "number_of_analysts",
            ):
                value = market.get(fact_name)
                if value is None:
                    continue
                facts.append(
                    {
                        "fact_id": f"fact:earnings_update:{fact_name}",
                        "fact_name": fact_name,
                        "value": value,
                        "metadata": {"source_ref_id": source_ref_id},
                    }
                )
            statuses.append(_collector_status("market_data", "ok", fact_count=len(facts)))
        else:
            statuses.append(_collector_status("market_data", "missing"))

    quality = EvidenceSourceQuality.real if snippets else (
        EvidenceSourceQuality.partial if source_refs or facts else EvidenceSourceQuality.placeholder
    )
    if quality != EvidenceSourceQuality.real:
        return _missing_packet(
            ticker,
            "earnings_update",
            reason="missing_recent_earnings_context",
            source_quality=quality,
            collector_statuses=statuses,
            source_refs=source_refs,
            facts=facts,
            snippets=snippets,
        )
    return {
        "source_refs": source_refs,
        "facts": facts,
        "snippets": snippets,
        "source_quality": quality.value,
        "run_metadata": {
            "profile_name": "earnings_update",
            "collector_statuses": statuses,
            "filing_count": len(earnings_docs),
        },
    }


def _driver_fact(
    profile_name: str,
    source_ref_id: str,
    fact_name: str,
    value: Any,
    *,
    source_lineage: str | None = None,
) -> dict[str, Any] | None:
    if value is None:
        return None
    metadata: dict[str, Any] = {"source_ref_id": source_ref_id}
    if source_lineage:
        metadata["source_lineage"] = source_lineage
    return {
        "fact_id": f"fact:{profile_name}:{fact_name}",
        "fact_name": fact_name,
        "value": value,
        "metadata": metadata,
    }


def _filing_context_facts(profile_name: str, source_ref_id: str, bundle: Any) -> list[dict[str, Any]]:
    # Per-section chunk counts are retrieval plumbing, not evidence — they live
    # in the collector status, not in the facts the agent reasons over.
    facts: list[dict[str, Any]] = []
    base_values = {
        "filing_source_count": len(getattr(bundle, "sources", []) or []),
        "filing_selected_chunk_count": len(getattr(bundle, "selected_chunks", []) or []),
    }
    for fact_name, value in base_values.items():
        fact = _driver_fact(profile_name, source_ref_id, fact_name, value)
        if fact is not None:
            facts.append(fact)
    return facts


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
    """Collect additive structured facts without making accounting judgments."""

    try:
        result = get_xbrl_fact_evidence(
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
    """Describe what retrieval actually did, without treating absence as proof."""

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
    xbrl_metadata: dict[str, Any] = {
        "xbrl_retrieval_status": "not_run",
        "xbrl_fact_count": 0,
        "xbrl_concepts": list(config.get("xbrl_concepts") or []),
        "xbrl_errors": [],
        "xbrl_cik": None,
    }

    xbrl_facts, xbrl_refs, xbrl_status, xbrl_metadata = _collect_xbrl_accounting_facts(
        ticker,
        profile_name,
        topic,
        tuple(config.get("xbrl_concepts") or ()),
    )
    facts.extend(xbrl_facts)
    source_refs.extend(xbrl_refs)
    statuses.append(xbrl_status)

    try:
        bundle = get_agent_filing_context(
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
        allowed_snippet_sections = set(config["note_keys"]) | {
            "notes_to_financials",
            "notes_to_financials_q",
        }
        for chunk in selected_chunks:
            if chunk.section_key not in allowed_snippet_sections:
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

    try:
        model_inputs = build_valuation_inputs(ticker)
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
            ciq = get_ciq_snapshot(ticker) or {}
            ciq_history = list(get_ciq_nwc_history(ticker) or [])
            statuses.append(_collector_status("ciq_accounting_snapshot", "ok" if ciq else "missing"))
        except Exception as exc:
            statuses.append(_collector_status("ciq_accounting_snapshot", "error", message=str(exc)))
        try:
            mkt = get_market_data(ticker, use_cache=True) or {}
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
            hist = get_historical_financials(ticker, use_cache=True) or {}
            statuses.append(_collector_status("historical_qoe_financials", "ok" if hist.get("revenue") else "missing"))
        except Exception as exc:
            statuses.append(_collector_status("historical_qoe_financials", "error", message=str(exc)))
        try:
            mkt = get_market_data(ticker, use_cache=True) or {}
            statuses.append(_collector_status("market_qoe_snapshot", "ok" if mkt else "missing"))
        except Exception as exc:
            statuses.append(_collector_status("market_qoe_snapshot", "error", message=str(exc)))
        try:
            ciq = get_ciq_snapshot(ticker) or {}
            ciq_history = list(get_ciq_nwc_history(ticker) or [])
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
            qoe = compute_qoe_signals(ticker, sector, ciq, ciq_history, hist, mkt) or {}
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
            "selected_section_keys": selected_section_keys,
            "retrieval_selected_section_keys": retrieval_selected_section_keys,
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


def _collect_industry_analysis_inputs(ticker: str) -> dict[str, Any]:
    source_refs: list[dict[str, Any]] = []
    facts: list[dict[str, Any]] = []
    snippets: list[dict[str, Any]] = []
    statuses: list[dict[str, Any]] = []

    inputs = None
    try:
        inputs = build_valuation_inputs(ticker)
    except Exception as exc:
        statuses.append(_collector_status("valuation_inputs", "error", message=str(exc)))
    else:
        if inputs is not None:
            source_ref_id = f"industry-inputs:{ticker}"
            source_refs.append(
                {
                    "source_ref_id": source_ref_id,
                    "source_kind": "valuation_inputs",
                    "source_label": "Company and driver context for industry review",
                    "source_locator": f"valuation://{ticker}/inputs",
                    "metadata": {
                        "company_name": getattr(inputs, "company_name", None),
                        "sector": getattr(inputs, "sector", None),
                        "industry": getattr(inputs, "industry", None),
                        "as_of_date": getattr(inputs, "as_of_date", None),
                    },
                }
            )
            identity_facts = {
                "company_name": getattr(inputs, "company_name", None),
                "sector": getattr(inputs, "sector", None),
                "industry": getattr(inputs, "industry", None),
            }
            for fact_name, value in identity_facts.items():
                fact = _driver_fact("industry_analysis", source_ref_id, fact_name, value)
                if fact is not None:
                    facts.append(fact)
            for field_name in ("revenue_growth_near", "revenue_growth_mid", "ebit_margin_target", "terminal_growth"):
                if not hasattr(inputs.drivers, field_name):
                    continue
                fact = _driver_fact(
                    "industry_analysis",
                    source_ref_id,
                    field_name,
                    getattr(inputs.drivers, field_name),
                    source_lineage=(getattr(inputs, "source_lineage", {}) or {}).get(field_name),
                )
                if fact is not None:
                    facts.append(fact)
            statuses.append(_collector_status("valuation_inputs", "ok", fact_count=len(facts)))
        else:
            statuses.append(_collector_status("valuation_inputs", "missing"))

    try:
        bundle = get_agent_filing_context(
            ticker,
            profile_name="industry",
            include_10k=True,
            ten_q_limit=1,
            use_cache=True,
        )
    except Exception as exc:
        statuses.append(_collector_status("industry_filing_context", "error", message=str(exc)))
    else:
        if bundle is not None and getattr(bundle, "sources", None):
            for source in bundle.sources[:2]:
                accession_no = source.get("accession_no") or "unknown"
                source_refs.append(
                    {
                        "source_ref_id": f"industry-filing:{accession_no}",
                        "source_kind": source.get("form_type") or "filing",
                        "source_label": f"Industry context filing {source.get('filing_date') or accession_no}",
                        "source_locator": f"edgar://{ticker}/{accession_no}/{source.get('doc_name') or accession_no}",
                        "metadata": {"filing_date": source.get("filing_date")},
                    }
                )
            if source_refs:
                filing_ref = next(
                    (ref for ref in source_refs if str(ref.get("source_ref_id", "")).startswith("industry-filing:")),
                    source_refs[0],
                )
                facts.extend(_filing_context_facts("industry_analysis", filing_ref["source_ref_id"], bundle))
            for chunk in list(getattr(bundle, "selected_chunks", []) or []):
                _ec = _evidence_chars()
                excerpt = _relevant_excerpt(chunk.text, "industry_analysis", max_chars=_ec)
                if excerpt is None:
                    continue
                if _ec < _LARGE_CONTEXT_THRESHOLD and not _is_meaningful_evidence_text(excerpt):
                    continue
                snippets.append(
                    {
                        "snippet_id": f"snippet:industry:{chunk.accession_no}:{chunk.chunk_index}",
                        "source_ref_id": f"industry-filing:{chunk.accession_no}",
                        "text": excerpt,
                        "metadata": {
                            "section_key": chunk.section_key,
                            "score": chunk.score,
                            "filing_date": chunk.filing_date,
                        },
                    }
                )
                if len(snippets) >= 4:
                    break
            statuses.append(
                _collector_status(
                    "industry_filing_context",
                    "ok" if snippets else "partial",
                    selected_chunk_count=len(snippets),
                )
            )
        else:
            statuses.append(_collector_status("industry_filing_context", "missing"))

    quality = EvidenceSourceQuality.real if facts and source_refs and snippets else (
        EvidenceSourceQuality.partial if source_refs or facts else EvidenceSourceQuality.placeholder
    )
    if quality != EvidenceSourceQuality.real:
        return _missing_packet(
            ticker,
            "industry_analysis",
            reason="missing_industry_context",
            source_quality=quality,
            collector_statuses=statuses,
            source_refs=source_refs,
            facts=facts,
            snippets=snippets,
        )
    return {
        "source_refs": source_refs,
        "facts": facts,
        "snippets": snippets,
        "source_quality": quality.value,
        "run_metadata": {
            "profile_name": "industry_analysis",
            "collector_statuses": statuses,
            "selected_chunk_count": len(snippets),
        },
    }


def _collect_valuation_review_inputs(ticker: str) -> dict[str, Any]:
    statuses: list[dict[str, Any]] = []
    source_refs: list[dict[str, Any]] = []
    facts: list[dict[str, Any]] = []
    dcf_view: dict[str, Any] = {}

    inputs = None
    try:
        inputs = build_valuation_inputs(ticker)
    except Exception as exc:
        statuses.append(_collector_status("valuation_inputs", "error", message=str(exc)))
    else:
        if inputs is not None:
            source_ref_id = f"valuation-inputs:{ticker}"
            source_refs.append(
                {
                    "source_ref_id": source_ref_id,
                    "source_kind": "valuation_inputs",
                    "source_label": "Deterministic valuation inputs",
                    "source_locator": f"valuation://{ticker}/inputs",
                    "metadata": {"as_of_date": getattr(inputs, "as_of_date", None)},
                }
            )
            for field_name in ("revenue_growth_near", "revenue_growth_mid", "ebit_margin_target", "wacc", "exit_multiple"):
                if not hasattr(inputs.drivers, field_name):
                    continue
                facts.append(
                    {
                        "fact_id": f"fact:valuation_review:{field_name}",
                        "fact_name": field_name,
                        "value": getattr(inputs.drivers, field_name),
                        "metadata": {
                            "source_ref_id": source_ref_id,
                            "source_lineage": (getattr(inputs, "source_lineage", {}) or {}).get(field_name),
                        },
                    }
                )
            statuses.append(_collector_status("valuation_inputs", "ok", fact_count=len(facts)))
        else:
            statuses.append(_collector_status("valuation_inputs", "missing"))

    try:
        dcf_view = build_dcf_audit_view(ticker)
    except Exception as exc:
        statuses.append(_collector_status("dcf_audit_view", "error", message=str(exc)))
    else:
        integrity = dcf_view.get("model_integrity") if isinstance(dcf_view.get("model_integrity"), dict) else {}
        terminal = dcf_view.get("terminal_bridge") if isinstance(dcf_view.get("terminal_bridge"), dict) else {}
        if integrity or terminal:
            audit_ref_id = f"valuation-audit:{ticker}"
            source_refs.append(
                {
                    "source_ref_id": audit_ref_id,
                    "source_kind": "dcf_audit",
                    "source_label": "Deterministic DCF audit",
                    "source_locator": f"valuation://{ticker}/audit",
                }
            )
            audit_facts = {
                "tv_pct_of_ev": integrity.get("tv_pct_of_ev") or terminal.get("tv_pct_of_ev"),
                "tv_high_flag": integrity.get("tv_high_flag"),
                "revenue_data_quality_flag": integrity.get("revenue_data_quality_flag"),
                "wacc_method_spread_high": integrity.get("wacc_method_spread_high"),
                "terminal_growth_pct": terminal.get("terminal_growth_pct"),
                "pv_tv_blended_mm": terminal.get("pv_tv_blended_mm"),
            }
            for fact_name, fact_value in audit_facts.items():
                if fact_value is None:
                    continue
                facts.append(
                    {
                        "fact_id": f"fact:valuation_review:{fact_name}",
                        "fact_name": fact_name,
                        "value": fact_value,
                        "metadata": {"source_ref_id": audit_ref_id},
                    }
                )
            statuses.append(_collector_status("dcf_audit_view", "ok", fact_count=len([v for v in audit_facts.values() if v is not None])))
        else:
            statuses.append(_collector_status("dcf_audit_view", "missing"))

    scenario_specs = list(default_scenario_specs()) if inputs is not None else []
    scenario_fact_count = 0
    scenario_ivs: dict[str, float] = {}
    scenario_probs: dict[str, float] = {}
    if inputs is not None:
        scenario_ref_id = f"valuation-scenarios:{ticker}"
        source_refs.append(
            {
                "source_ref_id": scenario_ref_id,
                "source_kind": "dcf_scenarios",
                "source_label": "Deterministic DCF scenarios",
                "source_locator": f"valuation://{ticker}/dcf",
            }
        )
        for spec in scenario_specs:
            spec_values = (
                asdict(spec)
                if is_dataclass(spec)
                else {
                    key: getattr(spec, key)
                    for key in (
                        "name",
                        "probability",
                        "growth_multiplier",
                        "margin_shift",
                        "wacc_shift",
                        "terminal_growth_shift",
                        "exit_multiple_multiplier",
                    )
                    if hasattr(spec, key)
                }
            )
            facts.append(
                {
                    "fact_id": f"fact:valuation_review:scenario_spec:{spec.name}",
                    "fact_name": f"scenario_spec_{spec.name}",
                    "value": spec_values,
                    "metadata": {
                        "source_ref_id": scenario_ref_id,
                        "note": (
                            "Scenario IV changes reflect this full deterministic scenario spec; "
                            "do not attribute bear/base/bull differences to one driver unless the spec supports it."
                        ),
                    },
                }
            )
            try:
                result = run_dcf_professional(inputs.drivers, spec)
                iv_value = float(result.intrinsic_value_per_share)
            except (Exception, TypeError, ValueError):
                continue
            facts.append(
                {
                    "fact_id": f"fact:valuation_review:scenario_iv:{spec.name}",
                    "fact_name": f"scenario_iv_{spec.name}",
                    "value": iv_value,
                    "metadata": {"source_ref_id": scenario_ref_id},
                }
            )
            scenario_fact_count += 1
            scenario_ivs[str(spec.name)] = iv_value
            try:
                probability = spec_values.get("probability")
                if probability is not None:
                    scenario_probs[str(spec.name)] = float(probability)
            except (TypeError, ValueError):
                pass
        statuses.append(
            _collector_status(
                "dcf_scenarios",
                "ok" if scenario_specs and scenario_fact_count == len(scenario_specs) else "partial",
                scenario_fact_count=scenario_fact_count,
            )
        )

    # Price context and expected value: without these, scenario IVs cannot be
    # read as upside/downside, which is the PM-decision number.
    if scenario_ivs:
        market = None
        try:
            market = get_market_data(ticker, use_cache=True)
        except TypeError:
            market = get_market_data(ticker)
        except Exception as exc:
            statuses.append(_collector_status("market_price", "error", message=str(exc)))
        price = None
        if market:
            try:
                price = float(market.get("current_price") or 0.0) or None
            except (TypeError, ValueError):
                price = None
        if price:
            market_ref_id = "market:latest"
            source_refs.append(
                {
                    "source_ref_id": market_ref_id,
                    "source_kind": "market_data",
                    "source_label": "Latest market snapshot",
                    "source_locator": f"market://{ticker}/latest",
                }
            )
            fact = _driver_fact("valuation_review", market_ref_id, "current_price", price)
            if fact is not None:
                facts.append(fact)
            for name, iv in scenario_ivs.items():
                fact = _driver_fact(
                    "valuation_review",
                    market_ref_id,
                    f"scenario_upside_pct_{name}",
                    round((iv / price - 1.0) * 100.0, 1),
                )
                if fact is not None:
                    facts.append(fact)
            expected_value_complete = (
                scenario_fact_count == len(scenario_specs)
                and all(
                    str(spec.name) in scenario_ivs and str(spec.name) in scenario_probs
                    for spec in scenario_specs
                )
            )
            probability_total = sum(scenario_probs.get(str(spec.name), 0.0) for spec in scenario_specs)
            if expected_value_complete and probability_total > 0:
                expected_iv = (
                    sum(scenario_probs[name] * iv for name, iv in scenario_ivs.items())
                    / probability_total
                )
                for fact_name, value in (
                    ("expected_iv_probability_weighted", round(expected_iv, 2)),
                    ("expected_upside_pct", round((expected_iv / price - 1.0) * 100.0, 1)),
                ):
                    fact = _driver_fact("valuation_review", market_ref_id, fact_name, value)
                    if fact is not None:
                        facts.append(fact)
        if not any(
            status.get("collector") == "market_price" and status.get("status") == "error"
            for status in statuses
        ):
            statuses.append(_collector_status("market_price", "ok" if price else "missing"))
    else:
        statuses.append(_collector_status("market_price", "missing", reason="no_scenario_ivs"))

    quality = EvidenceSourceQuality.real if inputs is not None and scenario_fact_count else (
        EvidenceSourceQuality.partial if inputs is not None else EvidenceSourceQuality.placeholder
    )
    if quality != EvidenceSourceQuality.real:
        return _missing_packet(
            ticker,
            "valuation_review",
            reason="missing_deterministic_valuation_outputs",
            source_quality=quality,
            collector_statuses=statuses,
            source_refs=source_refs,
            facts=facts,
        )
    return {
        "source_refs": source_refs,
        "facts": facts,
        "snippets": [],
        "source_quality": quality.value,
        "run_metadata": {
            "profile_name": "valuation_review",
            "collector_statuses": statuses,
            "scenario_fact_count": scenario_fact_count,
        },
    }


def _collect_comps_analysis_inputs(ticker: str) -> dict[str, Any]:
    statuses: list[dict[str, Any]] = []
    source_refs: list[dict[str, Any]] = []
    facts: list[dict[str, Any]] = []

    view = None
    audit_flags: list[str] = []
    try:
        view = build_comps_dashboard_view(ticker)
    except Exception as exc:
        statuses.append(_collector_status("comps_dashboard", "error", message=str(exc)))
    else:
        if view and view.get("available"):
            audit_flags = [str(flag) for flag in (view.get("audit_flags") or [])]
            source_ref_id = "comps:dashboard"
            source_refs.append(
                {
                    "source_ref_id": source_ref_id,
                    "source_kind": "comps_dashboard",
                    "source_label": "Deterministic comps dashboard",
                    "source_locator": f"comps://{ticker}/dashboard",
                    "metadata": view.get("source_lineage") or {},
                }
            )
            facts.extend(
                [
                    {
                        "fact_id": "fact:comps_analysis:peer_count_raw",
                        "fact_name": "peer_count_raw",
                        "value": ((view.get("peer_counts") or {}).get("raw")),
                        "metadata": {"source_ref_id": source_ref_id},
                    },
                    {
                        "fact_id": "fact:comps_analysis:peer_count_clean",
                        "fact_name": "peer_count_clean",
                        "value": ((view.get("peer_counts") or {}).get("clean")),
                        "metadata": {"source_ref_id": source_ref_id},
                    },
                    {
                        "fact_id": "fact:comps_analysis:primary_metric",
                        "fact_name": "primary_metric",
                        "value": view.get("primary_metric"),
                        "metadata": {"source_ref_id": source_ref_id},
                    },
                ]
            )
            peer_medians = ((view.get("target_vs_peers") or {}).get("peer_medians") or {})
            target_metrics = ((view.get("target_vs_peers") or {}).get("target") or {})
            deltas = ((view.get("target_vs_peers") or {}).get("deltas") or {})
            metric_names = {
                "tev_ebitda_ltm",
                "tev_ebitda_fwd",
                "tev_ebit_ltm",
                "tev_ebit_fwd",
                "pe_ltm",
                str(view.get("primary_metric") or "").strip(),
            }
            for metric_name in sorted(name for name in metric_names if name):
                for label, source in (
                    ("target", target_metrics),
                    ("peer_median", peer_medians),
                    ("target_minus_peer_median", deltas),
                ):
                    value = source.get(metric_name)
                    if value is None:
                        continue
                    facts.append(
                        {
                            "fact_id": f"fact:comps_analysis:{metric_name}:{label}",
                            "fact_name": metric_name if label == "peer_median" else f"{metric_name}_{label}",
                            "value": value,
                            "metadata": {
                                "source_ref_id": source_ref_id,
                                "metric_role": label,
                                "metric_name": metric_name,
                                "primary_metric": view.get("primary_metric"),
                            },
                        }
                    )
            facts = [fact for fact in facts if fact["value"] is not None]

            # Peer composition for the primary metric: the agent cannot judge
            # whether the peer median is trustworthy without seeing who is in it.
            primary_metric = str(view.get("primary_metric") or "").strip()
            peer_rows = [
                {
                    "ticker": row.get("ticker"),
                    "multiple": row.get("raw_multiple"),
                    "status": row.get("status"),
                }
                for row in (view.get("metric_status_rows") or [])
                if row.get("metric") == primary_metric
            ]
            if peer_rows:
                facts.append(
                    {
                        "fact_id": "fact:comps_analysis:peers_primary_metric",
                        "fact_name": "peers_primary_metric",
                        "value": peer_rows,
                        "metadata": {"source_ref_id": source_ref_id, "metric_name": primary_metric},
                    }
                )
            if audit_flags:
                facts.append(
                    {
                        "fact_id": "fact:comps_analysis:peer_set_audit_flags",
                        "fact_name": "peer_set_audit_flags",
                        "value": audit_flags,
                        "metadata": {"source_ref_id": source_ref_id},
                    }
                )

            # Relative leverage: premium/discount arguments need balance-sheet context.
            operating = view.get("operating_context") or {}
            for fact_name, value in (
                ("net_debt_to_ebitda_target", (operating.get("target") or {}).get("net_debt_to_ebitda")),
                ("net_debt_to_ebitda_peer_median", (operating.get("peer_medians") or {}).get("net_debt_to_ebitda")),
            ):
                fact = _driver_fact("comps_analysis", source_ref_id, fact_name, value)
                if fact is not None:
                    facts.append(fact)

            # The company's own trading-multiple history anchors mean-reversion
            # judgments about the exit multiple.
            hist = view.get("historical_multiples_summary") or {}
            hist_metrics = (hist.get("metrics") or {}) if hist.get("available") else {}
            for metric_name, payload in hist_metrics.items():
                series_values = sorted(
                    float(point["multiple"])
                    for point in (payload.get("series") or [])
                    if isinstance(point, dict) and point.get("multiple") is not None
                )
                fact = _driver_fact(
                    "comps_analysis", source_ref_id, f"own_{metric_name}_current", payload.get("current")
                )
                if fact is not None:
                    facts.append(fact)
                if series_values:
                    mid = len(series_values) // 2
                    median = (
                        series_values[mid]
                        if len(series_values) % 2
                        else (series_values[mid - 1] + series_values[mid]) / 2
                    )
                    facts.append(
                        _driver_fact(
                            "comps_analysis",
                            source_ref_id,
                            f"own_{metric_name}_5y_median",
                            round(median, 2),
                        )
                    )

            statuses.append(
                _collector_status(
                    "comps_dashboard",
                    "ok",
                    fact_count=len(facts),
                    audit_flags=audit_flags,
                    primary_metric=view.get("primary_metric"),
                )
            )
        else:
            statuses.append(_collector_status("comps_dashboard", "missing"))

    # The exit multiple the DCF currently assumes — the number every comps
    # observation is ultimately judged against.
    try:
        inputs = build_valuation_inputs(ticker)
    except Exception as exc:
        statuses.append(_collector_status("model_assumptions", "error", message=str(exc)))
    else:
        exit_multiple = getattr(getattr(inputs, "drivers", None), "exit_multiple", None)
        exit_metric = getattr(getattr(inputs, "drivers", None), "exit_metric", None)
        exit_metric = str(exit_metric).strip() if exit_metric is not None else None
        if exit_multiple is not None:
            model_ref_id = f"model-assumptions:{ticker}"
            source_refs.append(
                {
                    "source_ref_id": model_ref_id,
                    "source_kind": "valuation_inputs",
                    "source_label": "Current model exit multiple assumption",
                    "source_locator": f"valuation://{ticker}/inputs",
                    "metadata": {"as_of_date": getattr(inputs, "as_of_date", None)},
                }
            )
            fact = _driver_fact(
                "comps_analysis",
                model_ref_id,
                "model_assumption_exit_multiple",
                exit_multiple,
                source_lineage=(getattr(inputs, "source_lineage", {}) or {}).get("exit_multiple"),
            )
            if fact is not None:
                facts.append(fact)
            if exit_metric is not None:
                fact = _driver_fact(
                    "comps_analysis", model_ref_id, "model_assumption_exit_metric", exit_metric
                )
                if fact is not None:
                    facts.append(fact)

            # Precomputed spread vs the like-for-like peer median. Doing the
            # subtraction here keeps arithmetic out of the LLM and prevents
            # EBITDA/EBIT family mismatches.
            peer_metric_candidates = {
                "ev_ebitda": ("tev_ebitda_fwd", "tev_ebitda_ltm"),
                "ev_ebit": ("tev_ebit_fwd", "tev_ebit_ltm"),
            }.get(exit_metric, ())
            peer_medians = (((view or {}).get("target_vs_peers") or {}).get("peer_medians") or {})
            for metric_used in peer_metric_candidates:
                peer_median = peer_medians.get(metric_used)
                if peer_median is None:
                    continue
                try:
                    spread = round(float(exit_multiple) - float(peer_median), 2)
                except (TypeError, ValueError):
                    continue
                fact = _driver_fact(
                    "comps_analysis",
                    model_ref_id,
                    f"model_exit_multiple_minus_peer_median_{metric_used}",
                    spread,
                )
                if fact is not None:
                    facts.append(fact)
                break
            statuses.append(_collector_status("model_assumptions", "ok"))
        else:
            statuses.append(_collector_status("model_assumptions", "missing"))

    has_peer_multiple_signal = any(
        fact.get("fact_name") == "primary_metric"
        or (fact.get("metadata") or {}).get("metric_role") == "peer_median"
        for fact in facts
    )
    comps_model_unavailable = any("comps model unavailable" in flag.lower() for flag in audit_flags)
    quality = EvidenceSourceQuality.real if source_refs and has_peer_multiple_signal and not comps_model_unavailable else (
        EvidenceSourceQuality.partial if source_refs or facts else EvidenceSourceQuality.placeholder
    )
    if quality != EvidenceSourceQuality.real:
        return _missing_packet(
            ticker,
            "comps_analysis",
            reason="missing_real_comps_inputs",
            source_quality=quality,
            collector_statuses=statuses,
            source_refs=source_refs,
            facts=facts,
        )
    return {
        "source_refs": source_refs,
        "facts": facts,
        "snippets": [],
        "source_quality": quality.value,
        "run_metadata": {
            "profile_name": "comps_analysis",
            "collector_statuses": statuses,
            "audit_flags": audit_flags,
        },
    }


def _collect_risk_review_inputs(ticker: str) -> dict[str, Any]:
    statuses: list[dict[str, Any]] = []
    source_refs: list[dict[str, Any]] = []
    facts: list[dict[str, Any]] = []
    snippets: list[dict[str, Any]] = []

    inputs = None
    try:
        inputs = build_valuation_inputs(ticker)
    except Exception as exc:
        statuses.append(_collector_status("valuation_inputs", "error", message=str(exc)))
    else:
        if inputs is not None:
            source_ref_id = f"risk-inputs:{ticker}"
            source_refs.append(
                {
                    "source_ref_id": source_ref_id,
                    "source_kind": "valuation_inputs",
                    "source_label": "Deterministic valuation and balance-sheet risk inputs",
                    "source_locator": f"valuation://{ticker}/inputs",
                    "metadata": {"as_of_date": getattr(inputs, "as_of_date", None)},
                }
            )
            for field_name in ("wacc", "net_debt", "revenue_growth_near", "ebit_margin_target"):
                if not hasattr(inputs.drivers, field_name):
                    continue
                fact = _driver_fact(
                    "risk_review",
                    source_ref_id,
                    field_name,
                    getattr(inputs.drivers, field_name),
                    source_lineage=(getattr(inputs, "source_lineage", {}) or {}).get(field_name),
                )
                if fact is not None:
                    facts.append(fact)
            statuses.append(_collector_status("valuation_inputs", "ok", fact_count=len(facts)))
        else:
            statuses.append(_collector_status("valuation_inputs", "missing"))

    try:
        market = get_market_data(ticker, use_cache=True)
    except TypeError:
        market = get_market_data(ticker)
    except Exception as exc:
        statuses.append(_collector_status("market_data", "error", message=str(exc)))
    else:
        if market:
            source_ref_id = "risk-market:latest"
            source_refs.append(
                {
                    "source_ref_id": source_ref_id,
                    "source_kind": "market_data",
                    "source_label": "Latest market risk snapshot",
                    "source_locator": f"market://{ticker}/latest",
                }
            )
            for fact_name in ("beta", "short_ratio", "current_price"):
                fact = _driver_fact("risk_review", source_ref_id, fact_name, market.get(fact_name))
                if fact is not None:
                    facts.append(fact)
            statuses.append(_collector_status("market_data", "ok", fact_count=len(facts)))
        else:
            statuses.append(_collector_status("market_data", "missing"))

    try:
        bundle = get_agent_filing_context(
            ticker,
            profile_name="risk",
            include_10k=True,
            ten_q_limit=1,
            use_cache=True,
        )
    except Exception as exc:
        statuses.append(_collector_status("risk_filing_context", "error", message=str(exc)))
    else:
        if bundle is not None and getattr(bundle, "sources", None):
            for source in bundle.sources[:2]:
                accession_no = source.get("accession_no") or "unknown"
                source_refs.append(
                    {
                        "source_ref_id": f"risk-filing:{accession_no}",
                        "source_kind": source.get("form_type") or "filing",
                        "source_label": f"Risk context filing {source.get('filing_date') or accession_no}",
                        "source_locator": f"edgar://{ticker}/{accession_no}/{source.get('doc_name') or accession_no}",
                        "metadata": {"filing_date": source.get("filing_date")},
                    }
                )
            if source_refs:
                filing_ref = next(
                    (ref for ref in source_refs if str(ref.get("source_ref_id", "")).startswith("risk-filing:")),
                    source_refs[0],
                )
                facts.extend(_filing_context_facts("risk_review", filing_ref["source_ref_id"], bundle))
            for chunk in list(getattr(bundle, "selected_chunks", []) or []):
                _ec = _evidence_chars()
                excerpt = _relevant_excerpt(chunk.text, "risk_review", max_chars=_ec)
                if excerpt is None:
                    continue
                if _ec < _LARGE_CONTEXT_THRESHOLD and not _is_meaningful_evidence_text(excerpt):
                    continue
                snippets.append(
                    {
                        "snippet_id": f"snippet:risk:{chunk.accession_no}:{chunk.chunk_index}",
                        "source_ref_id": f"risk-filing:{chunk.accession_no}",
                        "text": excerpt,
                        "metadata": {
                            "section_key": chunk.section_key,
                            "score": chunk.score,
                            "filing_date": chunk.filing_date,
                        },
                    }
                )
                if len(snippets) >= 4:
                    break
            statuses.append(
                _collector_status(
                    "risk_filing_context",
                    "ok" if snippets else "partial",
                    selected_chunk_count=len(snippets),
                )
            )
        else:
            statuses.append(_collector_status("risk_filing_context", "missing"))

    quality = EvidenceSourceQuality.real if facts and source_refs and snippets else (
        EvidenceSourceQuality.partial if source_refs or facts else EvidenceSourceQuality.placeholder
    )
    if quality != EvidenceSourceQuality.real:
        return _missing_packet(
            ticker,
            "risk_review",
            reason="missing_risk_context",
            source_quality=quality,
            collector_statuses=statuses,
            source_refs=source_refs,
            facts=facts,
            snippets=snippets,
        )
    return {
        "source_refs": source_refs,
        "facts": facts,
        "snippets": snippets,
        "source_quality": quality.value,
        "run_metadata": {
            "profile_name": "risk_review",
            "collector_statuses": statuses,
            "selected_chunk_count": len(snippets),
        },
    }


def _collect_analyst_prep_synthesis_inputs(ticker: str) -> dict[str, Any]:
    source_ref_id = f"analyst-prep:{ticker}"
    source_refs = [
        {
            "source_ref_id": source_ref_id,
            "source_kind": "analyst_prep_pack",
            "source_label": f"{ticker} Analyst Prep Pack",
            "source_locator": f"internal://{ticker}/analyst-prep",
            "metadata": {"builder": "src.stage_04_pipeline.analyst_prep_pack"},
        }
    ]
    statuses: list[dict[str, Any]] = []
    try:
        from src.stage_04_pipeline.analyst_prep_pack import build_analyst_prep_payload

        pack = build_analyst_prep_payload(ticker)
    except Exception as exc:
        return _missing_packet(
            ticker,
            "analyst_prep_synthesis",
            reason="analyst_prep_pack_unavailable",
            source_quality=EvidenceSourceQuality.placeholder,
            collector_statuses=[_collector_status("analyst_prep_pack", "error", message=str(exc))],
            source_refs=source_refs,
        )

    facts: list[dict[str, Any]] = [
        {
            "fact_id": "fact:analyst_prep:thesis_card_count",
            "fact_name": "analyst_prep_thesis_card_count",
            "value": len(pack.get("thesis_cards") or []),
            "unit": "cards",
            "metadata": {"source_ref_id": source_ref_id},
        },
        {
            "fact_id": "fact:analyst_prep:driver_card_count",
            "fact_name": "analyst_prep_driver_card_count",
            "value": len(pack.get("driver_cards") or []),
            "unit": "cards",
            "metadata": {"source_ref_id": source_ref_id},
        },
        {
            "fact_id": "fact:analyst_prep:missing_data_count",
            "fact_name": "analyst_prep_missing_data_count",
            "value": len(pack.get("missing_data") or []),
            "unit": "flags",
            "metadata": {"source_ref_id": source_ref_id},
        },
    ]
    snippets: list[dict[str, Any]] = []

    for idx, card in enumerate(pack.get("thesis_cards") or [], start=1):
        claim = _clean_text(
            " ".join(
                str(card.get(key) or "")
                for key in (
                    "title",
                    "claim",
                    "business_evidence_summary",
                    "model_implication",
                    "counter_evidence",
                    "what_would_change_mind",
                )
            ),
            max_chars=700,
        )
        if claim:
            snippets.append(
                {
                    "snippet_id": f"snippet:analyst_prep:thesis:{idx}",
                    "source_ref_id": source_ref_id,
                    "text": claim,
                    "metadata": {
                        "card_id": card.get("card_id"),
                        "linked_assumption_fields": card.get("linked_assumption_fields") or [],
                        "evidence_anchor_ids": card.get("evidence_anchor_ids") or [],
                    },
                }
            )
        if len(snippets) >= 5:
            break

    for idx, card in enumerate(pack.get("driver_cards") or [], start=1):
        field = str(card.get("assumption_name") or "").strip()
        if not field:
            continue
        facts.append(
            {
                "fact_id": f"fact:analyst_prep:driver:{field}",
                "fact_name": f"analyst_prep_driver_{field}",
                "value": card.get("proposed_or_effective_value"),
                "unit": None,
                "metadata": {
                    "source_ref_id": source_ref_id,
                    "current_value": card.get("current_value"),
                    "pm_review_status": card.get("pm_review_status"),
                    "source": card.get("source"),
                    "rationale": card.get("rationale"),
                },
            }
        )
        if idx >= 8:
            break

    for idx, flag in enumerate(pack.get("missing_data") or [], start=1):
        snippets.append(
            {
                "snippet_id": f"snippet:analyst_prep:missing:{idx}",
                "source_ref_id": source_ref_id,
                "text": _clean_text(
                    f"{flag.get('label')}: {flag.get('reason')} Suggested check: {flag.get('suggested_check')}",
                    max_chars=500,
                ),
                "metadata": {
                    "flag_id": flag.get("flag_id"),
                    "severity": flag.get("severity"),
                    "source": flag.get("source"),
                },
            }
        )
        if idx >= 6:
            break

    source_quality = str(pack.get("source_quality") or "missing").lower()
    if source_quality not in {item.value for item in EvidenceSourceQuality}:
        source_quality = EvidenceSourceQuality.partial.value
    statuses.append(
        _collector_status(
            "analyst_prep_pack",
            "ok" if snippets or facts else "missing",
            thesis_card_count=len(pack.get("thesis_cards") or []),
            driver_card_count=len(pack.get("driver_cards") or []),
            missing_data_count=len(pack.get("missing_data") or []),
        )
    )
    return {
        "source_refs": source_refs,
        "facts": facts,
        "snippets": snippets,
        "source_quality": source_quality,
        "run_metadata": {
            "profile_name": "analyst_prep_synthesis",
            "collector_statuses": statuses,
            "analyst_prep_source_quality": pack.get("source_quality"),
            "evidence_packet_ids": pack.get("evidence_packet_ids") or [],
        },
    }


def _collect_profile_inputs(ticker: str, profile_name: str) -> dict[str, Any]:
    collectors: dict[str, Callable[[str], dict[str, Any]]] = {
        "company_analysis": _collect_company_analysis_inputs,
        "earnings_update": _collect_earnings_update_inputs,
        "industry_analysis": _collect_industry_analysis_inputs,
        "valuation_review": _collect_valuation_review_inputs,
        "comps_analysis": _collect_comps_analysis_inputs,
        "risk_review": _collect_risk_review_inputs,
        "analyst_prep_synthesis": _collect_analyst_prep_synthesis_inputs,
    }
    for accounting_profile_name in _ACCOUNTING_PACKET_CONFIGS:
        collectors[accounting_profile_name] = (
            lambda current_ticker, name=accounting_profile_name: _collect_accounting_inputs(current_ticker, name)
        )
    collector = collectors.get(profile_name)
    if collector is None:
        return _missing_packet(
            ticker,
            profile_name,
            reason="collector_not_implemented",
            source_quality=EvidenceSourceQuality.placeholder,
            collector_statuses=[_collector_status(profile_name, "missing")],
        )
    return collector(ticker)


def _build_profile_packet(ticker: str, profile_name: str) -> EvidencePacket:
    profile = get_agentic_handoff_profile(profile_name)
    inputs = _collect_profile_inputs(ticker, profile_name)
    generated_at = _now()
    source_quality = str(
        inputs.get("source_quality")
        or (inputs.get("run_metadata") or {}).get("source_quality")
        or EvidenceSourceQuality.placeholder.value
    ).strip().lower()
    run_metadata = dict(inputs.get("run_metadata") or {})
    run_metadata["source_quality"] = source_quality
    return EvidencePacket(
        ticker=ticker,
        profile_name=profile.profile_name,
        packet_kind=profile.evidence_packet_kinds[0],
        generated_at=generated_at,
        source_refs=[EvidenceSourceRef.model_validate(row) for row in inputs.get("source_refs") or []],
        facts=[EvidencePacketFact.model_validate(row) for row in inputs.get("facts") or []],
        snippets=[TextEvidenceSnippet.model_validate(row) for row in inputs.get("snippets") or []],
        run_metadata=run_metadata,
    )


def build_earnings_update_packet(ticker: str) -> EvidencePacket:
    return _build_profile_packet(ticker, "earnings_update")


def build_company_analysis_packet(ticker: str) -> EvidencePacket:
    return _build_profile_packet(ticker, "company_analysis")


def build_industry_analysis_packet(ticker: str) -> EvidencePacket:
    return _build_profile_packet(ticker, "industry_analysis")


def build_comps_analysis_packet(ticker: str) -> EvidencePacket:
    return _build_profile_packet(ticker, "comps_analysis")


def build_valuation_review_packet(ticker: str) -> EvidencePacket:
    return _build_profile_packet(ticker, "valuation_review")


def build_risk_review_packet(ticker: str) -> EvidencePacket:
    return _build_profile_packet(ticker, "risk_review")


def build_analyst_prep_synthesis_packet(ticker: str) -> EvidencePacket:
    return _build_profile_packet(ticker, "analyst_prep_synthesis")


def build_accounting_qoe_packet(ticker: str) -> EvidencePacket:
    return _build_profile_packet(ticker, "accounting_qoe")


def build_accounting_ev_equity_bridge_packet(ticker: str) -> EvidencePacket:
    return _build_profile_packet(ticker, "accounting_ev_equity_bridge")


def build_accounting_contingencies_and_taxes_packet(ticker: str) -> EvidencePacket:
    return _build_profile_packet(ticker, "accounting_contingencies_and_taxes")


def build_accounting_segments_and_disclosure_packet(ticker: str) -> EvidencePacket:
    return _build_profile_packet(ticker, "accounting_segments_and_disclosure")


_PROFILE_BUILDERS: dict[str, Callable[[str], EvidencePacket]] = {
    "earnings_update": build_earnings_update_packet,
    "company_analysis": build_company_analysis_packet,
    "industry_analysis": build_industry_analysis_packet,
    "comps_analysis": build_comps_analysis_packet,
    "valuation_review": build_valuation_review_packet,
    "risk_review": build_risk_review_packet,
    "analyst_prep_synthesis": build_analyst_prep_synthesis_packet,
    "accounting_qoe": build_accounting_qoe_packet,
    "accounting_ev_equity_bridge": build_accounting_ev_equity_bridge_packet,
    "accounting_contingencies_and_taxes": build_accounting_contingencies_and_taxes_packet,
    "accounting_segments_and_disclosure": build_accounting_segments_and_disclosure_packet,
}


def build_evidence_packet(ticker: str, profile_name: str) -> EvidencePacket:
    key = str(profile_name).strip()
    if key not in _PROFILE_BUILDERS:
        raise KeyError(f"unsupported evidence packet profile: {profile_name}")
    packet = _PROFILE_BUILDERS[key](ticker)
    from db.loader import insert_evidence_packet

    created_at = _now()
    with get_connection() as conn:
        create_tables(conn)
        packet_id = insert_evidence_packet(
            conn,
            {
                "created_at": created_at,
                "updated_at": created_at,
                "ticker": packet.ticker,
                "profile_name": packet.profile_name,
                "packet_kind": packet.packet_kind.value if isinstance(packet.packet_kind, EvidencePacketKind) else packet.packet_kind,
                "bundle_id": packet.bundle_id,
                "generated_at": packet.generated_at,
                "source_refs": [row.model_dump() for row in packet.source_refs],
                "facts": [row.model_dump() for row in packet.facts],
                "snippets": [row.model_dump() for row in packet.snippets],
                "observations": [row.model_dump() for row in packet.observations],
                "run_metadata": packet.run_metadata,
            },
        )
    return packet.model_copy(update={"packet_id": packet_id})
