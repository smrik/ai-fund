from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from db.schema import get_read_only_connection
from src.contracts.evidence_packet import EvidencePacket, EvidenceSourceQuality
from src.stage_02_valuation.input_assembler import build_valuation_inputs_from_db
from src.stage_04_pipeline.evidence.assembly import PacketMaterial, assemble_packet


_CANONICAL_SERIES_CONCEPTS = {
    "revenue_series_annual": ("as_reported_total_revenue", "total_revenue", "revenue"),
    "ebit_series_annual": ("operating_income",),
}
_CANONICAL_SERIES_YEARS = 5


@dataclass(frozen=True)
class ContextEvidenceSnapshot:
    ticker: str
    db_path: str
    financial_as_of_date: str
    ciq_run_id: int
    source_refs: tuple[dict[str, Any], ...]
    reported_facts: tuple[dict[str, Any], ...]
    filing_sections: tuple[dict[str, Any], ...]


def _canonical_annual_series_from_db(
    db_path: str,
    ticker: str,
    *,
    run_id: int,
    concepts: tuple[str, ...],
    years: int = _CANONICAL_SERIES_YEARS,
) -> list[dict[str, float | str]]:
    placeholders = ",".join("?" for _ in concepts)
    conn = get_read_only_connection(db_path)
    try:
        rows = conn.execute(
            f"""
            SELECT concept, period_end, numeric_value, scale_factor
            FROM statement_facts
            WHERE UPPER(ticker) = ?
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


def load_context_snapshot(db_path: str, ticker: str) -> ContextEvidenceSnapshot:
    """Read one frozen, cache-only evidence snapshot from the supplied SQLite DB."""
    inputs = build_valuation_inputs_from_db(db_path, ticker)
    financial_as_of_date = str(getattr(inputs, "as_of_date", None) or "")
    ciq_run_id = int((getattr(inputs, "ciq_lineage", {}) or {}).get("snapshot_run_id") or 0)

    source_refs: list[dict[str, Any]] = []
    reported_facts: list[dict[str, Any]] = []
    filing_sections: list[dict[str, Any]] = []

    if ciq_run_id > 0:
        series_ref_id = f"canonical-db:ciq:{ciq_run_id}"
        source_refs.append(
            {
                "source_ref_id": series_ref_id,
                "source_kind": "canonical_statement_ledger",
                "source_label": f"Reported annual series, CIQ run {ciq_run_id} as of {financial_as_of_date}",
                "source_locator": f"canonical://{ticker.upper()}/ciq/{ciq_run_id}",
                "metadata": {
                    "ciq_run_id": ciq_run_id,
                    "financial_as_of_date": financial_as_of_date,
                },
            }
        )
        for fact_name, concepts in _CANONICAL_SERIES_CONCEPTS.items():
            series = _canonical_annual_series_from_db(
                db_path, ticker, run_id=ciq_run_id, concepts=concepts
            )
            if series:
                reported_facts.append(
                    {
                        "fact_id": f"fact:company_analysis:{fact_name}",
                        "fact_name": fact_name,
                        "value": series,
                        "metadata": {"source_ref_id": series_ref_id},
                    }
                )

    conn = get_read_only_connection(db_path)
    try:
        rows = conn.execute(
            """
            SELECT ticker, cik, form_type, accession_no, doc_name, filing_date,
                   section_key, section_label, section_text
            FROM edgar_section_cache
            WHERE UPPER(ticker) = ?
            ORDER BY filing_date DESC, section_key
            """,
            [ticker.upper()],
        ).fetchall()
        for row in rows:
            filing_sections.append(dict(row))
    finally:
        conn.close()

    # Create filing source refs from section rows
    seen_accessions: set[str] = set()
    for sec in filing_sections:
        acc = sec.get("accession_no") or "unknown"
        if acc in seen_accessions:
            continue
        seen_accessions.add(acc)
        form = sec.get("form_type") or "filing"
        filing_date = sec.get("filing_date") or acc
        doc_name = sec.get("doc_name") or acc
        source_refs.append(
            {
                "source_ref_id": f"filing:{acc}",
                "source_kind": form,
                "source_label": f"{form} {filing_date}",
                "source_locator": f"edgar://{ticker.upper()}/{acc}/{doc_name}",
                "metadata": {
                    "filing_date": filing_date,
                    "doc_name": doc_name,
                },
            }
        )

    if not filing_sections:
        try:
            from src.stage_00_data.filing_retrieval import get_agent_filing_context

            bundle = get_agent_filing_context(
                ticker, profile_name="filings", include_10k=True, ten_q_limit=2, use_cache=True
            )
            if bundle is not None:
                if getattr(bundle, "sources", None):
                    for src in bundle.sources:
                        acc = src.get("accession_no") or "unknown"
                        if acc not in seen_accessions:
                            seen_accessions.add(acc)
                            form = src.get("form_type") or "filing"
                            filing_date = src.get("filing_date") or acc
                            doc_name = src.get("doc_name") or acc
                            source_refs.append(
                                {
                                    "source_ref_id": f"filing:{acc}",
                                    "source_kind": form,
                                    "source_label": f"{form} {filing_date}",
                                    "source_locator": f"edgar://{ticker.upper()}/{acc}/{doc_name}",
                                    "metadata": {
                                        "filing_date": filing_date,
                                        "doc_name": doc_name,
                                    },
                                }
                            )
                chunks = list(getattr(bundle, "selected_chunks", []) or [])
                for chunk in chunks:
                    filing_sections.append(
                        {
                            "ticker": ticker.upper(),
                            "form_type": getattr(chunk, "form_type", None) or "10-K",
                            "accession_no": getattr(chunk, "accession_no", "unknown"),
                            "doc_name": getattr(chunk, "doc_name", None) or "filing.htm",
                            "filing_date": getattr(chunk, "filing_date", None),
                            "section_key": getattr(chunk, "section_key", "business"),
                            "section_text": getattr(chunk, "text", ""),
                        }
                    )
        except Exception:
            pass

    return ContextEvidenceSnapshot(
        ticker=ticker.upper(),
        db_path=db_path,
        financial_as_of_date=financial_as_of_date,
        ciq_run_id=ciq_run_id,
        source_refs=tuple(source_refs),
        reported_facts=tuple(reported_facts),
        filing_sections=tuple(filing_sections),
    )


def project_business_context(snapshot: ContextEvidenceSnapshot) -> PacketMaterial:
    """Select business evidence without forecast targets or issuer-specific keywords."""
    snippets: list[dict[str, Any]] = []
    seen_sections: set[str] = set()
    has_business_section = False
    has_mda_section = False

    for sec in snapshot.filing_sections:
        sec_key = sec.get("section_key") or ""
        form = sec.get("form_type") or ""
        text = sec.get("section_text") or ""
        acc = sec.get("accession_no") or ""
        if not text.strip():
            continue

        if sec_key == "business" and "10-K" in form.upper() and "business" not in seen_sections:
            seen_sections.add("business")
            has_business_section = True
            snippets.append(
                {
                    "snippet_id": f"snippet:filing:{acc}:business",
                    "source_ref_id": f"filing:{acc}",
                    "text": text.strip(),
                    "metadata": {
                        "section_key": "business",
                        "filing_date": sec.get("filing_date"),
                    },
                }
            )

        if sec_key == "mda" and "10-K" in form.upper() and "mda" not in seen_sections:
            seen_sections.add("mda")
            has_mda_section = True
            snippets.append(
                {
                    "snippet_id": f"snippet:filing:{acc}:mda",
                    "source_ref_id": f"filing:{acc}",
                    "text": text.strip(),
                    "metadata": {
                        "section_key": "mda",
                        "filing_date": sec.get("filing_date"),
                    },
                }
            )

    gaps: list[str] = []
    if not has_business_section:
        gaps.append("missing_latest_business_section")
    if not has_mda_section:
        gaps.append("missing_latest_mda")

    revenue_series: list[dict[str, Any]] = []
    for fact in snapshot.reported_facts:
        if fact.get("fact_name") == "revenue_series_annual":
            revenue_series = fact.get("value") or []
            break

    if not revenue_series:
        gaps.append("missing_reported_revenue_history")
    elif snapshot.financial_as_of_date:
        latest_period = str(revenue_series[-1].get("period") or "")
        if latest_period[:4] < str(snapshot.financial_as_of_date)[:4]:
            gaps.append("history_behind_resolved_period")

    sufficiency = "sufficient" if not gaps else "insufficient_evidence"
    if snapshot.filing_sections or snippets:
        quality = EvidenceSourceQuality.real.value
    elif snapshot.source_refs or snapshot.reported_facts:
        quality = EvidenceSourceQuality.partial.value
    else:
        quality = EvidenceSourceQuality.placeholder.value

    run_metadata: dict[str, Any] = {
        "profile_name": "company_analysis",
        "retrieval_mode": "db_only",
        "ciq_run_id": snapshot.ciq_run_id,
        "financial_as_of_date": snapshot.financial_as_of_date,
        "canonical_db_path": snapshot.db_path,
        "source_quality": quality,
        "evidence_sufficiency": sufficiency,
        "evidence_gaps": gaps,
        "selected_chunk_count": len(snippets),
    }

    return PacketMaterial(
        source_refs=snapshot.source_refs,
        facts=snapshot.reported_facts,
        snippets=tuple(snippets),
        run_metadata=run_metadata,
    )


def build_business_context_packet(db_path: str, ticker: str) -> EvidencePacket:
    """Public DB-backed Business Context interface used by the MSFT ride-along."""
    snapshot = load_context_snapshot(db_path, ticker)
    material = project_business_context(snapshot)
    return assemble_packet(
        ticker=ticker,
        profile_name="company_analysis",
        material=material,
    )
