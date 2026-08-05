from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from typing import Any, Callable

from db.schema import create_tables, get_connection, get_read_only_connection
from src.contracts.evidence_packet import (
    EvidencePacket,
    EvidencePacketKind,
    EvidenceSourceQuality,
)
from src.stage_00_data.filing_retrieval import get_agent_filing_context
from src.stage_00_data.sec_filing_metrics import get_sec_filing_metrics
from src.stage_02_valuation.input_assembler import (
    build_valuation_inputs,
    build_valuation_inputs_from_db,
)

from src.stage_04_pipeline.evidence.accounting import (
    ACCOUNTING_PROFILE_NAMES,
    _collect_accounting_inputs,
    build_accounting_packet,
)
from src.stage_04_pipeline.evidence.assembly import PacketMaterial, assemble_packet
from src.stage_04_pipeline.evidence.context import build_business_context_packet
from src.stage_04_pipeline.evidence.reviews import (
    REVIEW_PROFILE_NAMES,
    _driver_fact,
    _filing_context_facts,
    build_review_packet,
)



def _evidence_chars() -> int:
    """Per-snippet char budget, set by ALPHA_POD_EVIDENCE_CHARS env var."""
    try:
        return max(100, int(os.getenv("ALPHA_POD_EVIDENCE_CHARS", "420")))
    except (ValueError, TypeError):
        return 420


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


# Concepts carrying the reported annual series in the canonical statement ledger.
# Ordered by preference; the first alias with data wins, aliases are never blended.
_CANONICAL_SERIES_CONCEPTS: dict[str, tuple[str, ...]] = {
    "revenue_series_annual": ("as_reported_total_revenue", "total_revenue", "revenue"),
    "ebit_series_annual": ("operating_income",),
}

_CANONICAL_SERIES_YEARS = 5


def _canonical_annual_series(
    db_path: str,
    ticker: str,
    *,
    run_id: int,
    concepts: tuple[str, ...],
    years: int = _CANONICAL_SERIES_YEARS,
) -> list[dict[str, float | str]]:
    """Reported annual series read from the canonical statement ledger.

    Scoped to the CIQ run the Step 2 assembler already resolved, so history and
    drivers can never be paired from different ingests. Values are returned in
    absolute USD, oldest first.
    """
    placeholders = ",".join("?" for _ in concepts)
    conn = get_read_only_connection(db_path)
    try:
        rows = conn.execute(
            f"""
            SELECT concept, period_end, numeric_value, scale_factor
            FROM statement_facts
            WHERE ticker = ?
              AND source = 'ciq_workbook_v1'
              AND source_run_id = ?
              AND period_kind = 'annual'
              AND numeric_value IS NOT NULL
              AND period_end IS NOT NULL
              AND concept IN ({placeholders})
            """,
            [ticker.upper(), int(run_id), *concepts],
        ).fetchall()
    finally:
        conn.close()

    by_concept: dict[str, dict[str, float]] = {}
    for row in rows:
        data = dict(row)
        scale = data.get("scale_factor")
        by_concept.setdefault(str(data["concept"]), {})[str(data["period_end"])] = float(
            data["numeric_value"]
        ) * float(1.0 if scale is None else scale)

    for concept in concepts:
        periods = by_concept.get(concept)
        if not periods:
            continue
        latest = sorted(periods.items(), reverse=True)[:years]
        return [{"period": period, "value": value} for period, value in sorted(latest)]
    return []


def _context_evidence_sufficiency(
    *,
    snippets: list[dict[str, Any]],
    revenue_series: list[dict[str, float | str]],
    resolved_as_of_date: str | None,
) -> dict[str, Any]:
    """Whether the selected evidence can actually support context analysis.

    Distinct from ``source_quality``, which only attests authenticity: six
    authentic but boilerplate excerpts still make a packet look ``real``. This
    reports what the packet can currently prove — that the reported history
    reaches the period the model was built on.
    """
    gaps: list[str] = []
    if not snippets:
        gaps.append("no_filing_excerpts")
    if not revenue_series:
        gaps.append("no_reported_revenue_history")
    elif resolved_as_of_date:
        latest_period = str(revenue_series[-1].get("period") or "")
        if latest_period[:4] < str(resolved_as_of_date)[:4]:
            gaps.append("history_behind_resolved_period")
    return {
        "evidence_sufficiency": "sufficient" if not gaps else "insufficient_evidence",
        "evidence_gaps": gaps,
    }


def _collect_company_analysis_inputs(
    ticker: str,
    *,
    db_path: str | None = None,
) -> dict[str, Any]:
    source_refs: list[dict[str, Any]] = []
    facts: list[dict[str, Any]] = []
    snippets: list[dict[str, Any]] = []
    statuses: list[dict[str, Any]] = []
    revenue_series: list[dict[str, float | str]] = []
    resolved_as_of_date: str | None = None

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

    # Legacy path only. `sec_filing_metrics_snapshot` is a derived cache that is
    # never invalidated, so it can lag the loaded filings by a full fiscal year.
    # When a Step 1/2 database is supplied, the history comes from the canonical
    # statement ledger below instead.
    metrics = None
    try:
        metrics = get_sec_filing_metrics(ticker) if db_path is None else None
    except Exception as exc:
        statuses.append(_collector_status("sec_metrics", "error", message=str(exc)))
    else:
        if db_path is not None:
            statuses.append(_collector_status("sec_metrics", "skipped_for_canonical_db"))
        elif metrics is not None:
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
            revenue_series = list(metrics.revenue_series or [])
            statuses.append(_collector_status("sec_metrics", "ok", fact_count=len(facts)))
        else:
            statuses.append(_collector_status("sec_metrics", "missing"))

    # Current model assumptions, so historical quality can be judged against
    # what the model actually assumes rather than in the abstract.
    try:
        inputs = (
            build_valuation_inputs(ticker)
            if db_path is None
            else build_valuation_inputs_from_db(db_path, ticker)
        )
    except Exception as exc:
        statuses.append(_collector_status("model_assumptions", "error", message=str(exc)))
    else:
        if inputs is not None:
            if db_path is None:
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
                    "ebit_margin_start",
                    "ebit_margin_target",
                ):
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
                # Context analysis must not be anchored by the forecast values it
                # will later help adjustment analysts challenge. The Step 2 input
                # object is used here only to freeze source-run and date lineage.
                statuses.append(_collector_status("valuation_lineage", "ok"))

            if db_path is not None:
                # Reuse the run the assembler already resolved. Re-resolving
                # "latest" here is how history and drivers drift onto different
                # ingests.
                resolved_as_of_date = getattr(inputs, "as_of_date", None)
                run_id = (getattr(inputs, "ciq_lineage", {}) or {}).get("snapshot_run_id")
                if run_id is None:
                    statuses.append(
                        _collector_status("canonical_series", "missing", reason="unresolved_run")
                    )
                else:
                    series_ref_id = f"canonical-db:ciq:{run_id}"
                    source_refs.append(
                        {
                            "source_ref_id": series_ref_id,
                            "source_kind": "canonical_statement_ledger",
                            "source_label": (
                                f"Reported annual series, CIQ run {run_id}"
                                f" as of {resolved_as_of_date}"
                            ),
                            "source_locator": f"canonical://{ticker}/ciq/{run_id}",
                            "metadata": {
                                "ciq_run_id": run_id,
                                "financial_as_of_date": resolved_as_of_date,
                            },
                        }
                    )
                    for fact_name, concepts in _CANONICAL_SERIES_CONCEPTS.items():
                        series = _canonical_annual_series(
                            db_path, ticker, run_id=int(run_id), concepts=concepts
                        )
                        if not series:
                            continue
                        if fact_name == "revenue_series_annual":
                            revenue_series = series
                        facts.append(
                            {
                                "fact_id": f"fact:company_analysis:{fact_name}",
                                "fact_name": fact_name,
                                "value": series,
                                "metadata": {"source_ref_id": series_ref_id},
                            }
                        )
                    statuses.append(
                        _collector_status(
                            "canonical_series",
                            "ok" if revenue_series else "missing",
                            period_count=len(revenue_series),
                        )
                    )
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
            "canonical_db_path": db_path,
            "financial_as_of_date": resolved_as_of_date,
            **_context_evidence_sufficiency(
                snippets=snippets,
                revenue_series=revenue_series,
                resolved_as_of_date=resolved_as_of_date,
            ),
        },
    }


def _collect_profile_inputs(
    ticker: str,
    profile_name: str,
    *,
    db_path: str | None = None,
) -> dict[str, Any]:
    collectors: dict[str, Callable[[str], dict[str, Any]]] = {
        "company_analysis": lambda current_ticker: _collect_company_analysis_inputs(
            current_ticker, db_path=db_path
        ),
    }
    for review_profile_name in REVIEW_PROFILE_NAMES:
        collectors[review_profile_name] = (
            lambda current_ticker, name=review_profile_name: build_review_packet(current_ticker, name)
        )

    for accounting_profile_name in ACCOUNTING_PROFILE_NAMES:
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


def _build_profile_packet(
    ticker: str,
    profile_name: str,
    *,
    db_path: str | None = None,
) -> EvidencePacket:
    inputs = (
        _collect_profile_inputs(ticker, profile_name)
        if db_path is None
        else _collect_profile_inputs(ticker, profile_name, db_path=db_path)
    )
    source_quality = str(
        inputs.get("source_quality")
        or (inputs.get("run_metadata") or {}).get("source_quality")
        or EvidenceSourceQuality.placeholder.value
    ).strip().lower()
    run_metadata = dict(inputs.get("run_metadata") or {})
    run_metadata["source_quality"] = source_quality
    material = PacketMaterial(
        source_refs=tuple(inputs.get("source_refs") or []),
        facts=tuple(inputs.get("facts") or []),
        snippets=tuple(inputs.get("snippets") or []),
        run_metadata=run_metadata,
    )
    return assemble_packet(
        ticker=ticker,
        profile_name=profile_name,
        material=material,
    )


def build_earnings_update_packet(ticker: str) -> EvidencePacket:
    return build_review_packet(ticker, "earnings_update")


def build_company_analysis_packet(
    ticker: str,
    *,
    db_path: str | None = None,
) -> EvidencePacket:
    """Business-context packet.

    Pass ``db_path`` to source the reported history and model assumptions from a
    validated Step 1/2 database instead of the process-global legacy path.
    """
    if db_path is not None:
        return build_business_context_packet(db_path, ticker)
    return _build_profile_packet(ticker, "company_analysis")


def build_industry_analysis_packet(ticker: str) -> EvidencePacket:
    return build_review_packet(ticker, "industry_analysis")


def build_comps_analysis_packet(ticker: str) -> EvidencePacket:
    return build_review_packet(ticker, "comps_analysis")


def build_valuation_review_packet(ticker: str) -> EvidencePacket:
    return build_review_packet(ticker, "valuation_review")


def build_risk_review_packet(ticker: str) -> EvidencePacket:
    return build_review_packet(ticker, "risk_review")


def build_analyst_prep_synthesis_packet(ticker: str) -> EvidencePacket:
    return build_review_packet(ticker, "analyst_prep_synthesis")


def build_accounting_qoe_packet(ticker: str) -> EvidencePacket:
    return build_accounting_packet(ticker, "accounting_qoe")


def build_accounting_ev_equity_bridge_packet(ticker: str) -> EvidencePacket:
    return build_accounting_packet(ticker, "accounting_ev_equity_bridge")


def build_accounting_contingencies_and_taxes_packet(ticker: str) -> EvidencePacket:
    return build_accounting_packet(ticker, "accounting_contingencies_and_taxes")


def build_accounting_segments_and_disclosure_packet(ticker: str) -> EvidencePacket:
    return build_accounting_packet(ticker, "accounting_segments_and_disclosure")


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


def build_evidence_packet(
    ticker: str,
    profile_name: str,
    *,
    db_path: str | None = None,
) -> EvidencePacket:
    key = str(profile_name).strip()
    if key not in _PROFILE_BUILDERS:
        raise KeyError(f"unsupported evidence packet profile: {profile_name}")
    if db_path is not None and key == "company_analysis":
        packet = build_company_analysis_packet(ticker, db_path=db_path)
    else:
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
