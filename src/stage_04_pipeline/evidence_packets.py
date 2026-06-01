from __future__ import annotations

import re
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from typing import Any, Callable

from db.schema import create_tables, get_connection
from src.contracts.evidence_packet import (
    EvidencePacket,
    EvidencePacketFact,
    EvidencePacketKind,
    EvidenceSourceQuality,
    EvidenceSourceRef,
    TextEvidenceSnippet,
)
from src.stage_00_data.edgar_client import get_8k_texts, get_recent_10q_texts
from src.stage_00_data.filing_retrieval import get_agent_filing_context
from src.stage_00_data.market_data import get_market_data
from src.stage_00_data.sec_filing_metrics import get_sec_filing_metrics
from src.stage_02_valuation.input_assembler import build_valuation_inputs
from src.stage_02_valuation.professional_dcf import default_scenario_specs, run_dcf_professional
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


def _extract_total_revenue_facts(text: str | None) -> dict[str, float]:
    cleaned = " ".join(str(text or "").replace(",", "").split())
    match = re.search(
        r"Total revenue \$?\s+(-?\d+(?:\.\d+)?) \$?\s+(-?\d+(?:\.\d+)?)"
        r"(?: \$?\s+(-?\d+(?:\.\d+)?) \$?\s+(-?\d+(?:\.\d+)?))?",
        cleaned,
        flags=re.IGNORECASE,
    )
    if not match:
        return {}
    current = float(match.group(1))
    prior = float(match.group(2))
    facts = {
        "latest_quarter_total_revenue_mm": current,
        "prior_year_quarter_total_revenue_mm": prior,
    }
    if prior:
        facts["latest_quarter_revenue_yoy_pct"] = round((current / prior - 1.0) * 100.0, 2)
    if match.group(3) is not None and match.group(4) is not None:
        ytd_current = float(match.group(3))
        ytd_prior = float(match.group(4))
        facts["ytd_total_revenue_mm"] = ytd_current
        facts["prior_year_ytd_total_revenue_mm"] = ytd_prior
        if ytd_prior:
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
            selected_chunks = list(getattr(bundle, "selected_chunks", []) or [])
            for chunk in selected_chunks:
                excerpt = _relevant_excerpt(chunk.text, "company_analysis")
                if excerpt is None:
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
                if doc.get("text"):
                    excerpt = _relevant_excerpt(doc.get("text"), "earnings_update", max_chars=420)
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
                    excerpt = _relevant_excerpt(doc.get("text"), "earnings_update", max_chars=520)
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
) -> dict[str, Any] | None:
    if value is None:
        return None
    return {
        "fact_id": f"fact:{profile_name}:{fact_name}",
        "fact_name": fact_name,
        "value": value,
        "metadata": {"source_ref_id": source_ref_id},
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
            for chunk in list(getattr(bundle, "selected_chunks", []) or []):
                excerpt = _relevant_excerpt(chunk.text, "industry_analysis")
                if excerpt is None:
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

    scenario_fact_count = 0
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
        for spec in default_scenario_specs():
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
            except Exception:
                continue
            facts.append(
                {
                    "fact_id": f"fact:valuation_review:scenario_iv:{spec.name}",
                    "fact_name": f"scenario_iv_{spec.name}",
                    "value": result.intrinsic_value_per_share,
                    "metadata": {"source_ref_id": scenario_ref_id},
                }
            )
            scenario_fact_count += 1
        statuses.append(
            _collector_status(
                "dcf_scenarios",
                "ok" if scenario_fact_count else "partial",
                scenario_fact_count=scenario_fact_count,
            )
        )

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
                fact = _driver_fact("risk_review", source_ref_id, field_name, getattr(inputs.drivers, field_name))
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
            for chunk in list(getattr(bundle, "selected_chunks", []) or []):
                excerpt = _relevant_excerpt(chunk.text, "risk_review")
                if excerpt is None:
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


def _collect_profile_inputs(ticker: str, profile_name: str) -> dict[str, Any]:
    collectors: dict[str, Callable[[str], dict[str, Any]]] = {
        "company_analysis": _collect_company_analysis_inputs,
        "earnings_update": _collect_earnings_update_inputs,
        "industry_analysis": _collect_industry_analysis_inputs,
        "valuation_review": _collect_valuation_review_inputs,
        "comps_analysis": _collect_comps_analysis_inputs,
        "risk_review": _collect_risk_review_inputs,
    }
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


_PROFILE_BUILDERS: dict[str, Callable[[str], EvidencePacket]] = {
    "earnings_update": build_earnings_update_packet,
    "company_analysis": build_company_analysis_packet,
    "industry_analysis": build_industry_analysis_packet,
    "comps_analysis": build_comps_analysis_packet,
    "valuation_review": build_valuation_review_packet,
    "risk_review": build_risk_review_packet,
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
