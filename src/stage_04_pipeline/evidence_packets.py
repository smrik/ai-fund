from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable

from db.schema import create_tables, get_connection
from src.contracts.evidence_packet import (
    EvidencePacket,
    EvidencePacketFact,
    EvidencePacketKind,
    EvidenceSourceRef,
    TextEvidenceSnippet,
)
from src.stage_04_pipeline.agentic_handoff_profiles import get_agentic_handoff_profile


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _collect_profile_inputs(ticker: str, profile_name: str) -> dict[str, Any]:
    """Deterministic MVP input skeleton; profile-specific retrieval can expand later."""
    source_refs = [
        {
            "source_ref_id": f"src:{profile_name}:default",
            "source_kind": profile_name,
            "source_label": f"{profile_name.replace('_', ' ').title()} source bundle",
            "source_locator": f"internal://{ticker}/{profile_name}",
        }
    ]
    facts = [
        {
            "fact_id": f"fact:{profile_name}:timestamp",
            "fact_name": "packet_generated_at",
            "value": _now(),
        }
    ]
    snippets = []

    if profile_name == "earnings_update":
        facts.extend([
            {
                "fact_id": "fact:earnings_update:midpoint_revenue_guidance",
                "fact_name": "midpoint_revenue_guidance",
                "value": 12500.0,
                "unit": "million",
            },
            {
                "fact_id": "fact:earnings_update:reported_operating_margin",
                "fact_name": "reported_operating_margin",
                "value": 0.185,
            }
        ])
        snippets.append({
            "snippet_id": "snippet:earnings_update:guidance_comment",
            "source_ref_id": f"src:{profile_name}:default",
            "text": "We expect strong demand for our cloud and AI services, leading us to raise our full-year revenue growth guidance.",
        })
    elif profile_name == "company_analysis":
        facts.extend([
            {
                "fact_id": "fact:company_analysis:operating_cash_flow",
                "fact_name": "operating_cash_flow",
                "value": 3200.0,
                "unit": "million",
            }
        ])
        snippets.append({
            "snippet_id": "snippet:company_analysis:margin_efficiency",
            "source_ref_id": f"src:{profile_name}:default",
            "text": "Management highlighted ongoing cost efficiency initiatives in the corporate sector, which should expand target EBIT margin.",
        })
    elif profile_name == "industry_analysis":
        facts.extend([
            {
                "fact_id": "fact:industry_analysis:industry_growth_estimate",
                "fact_name": "industry_growth_estimate",
                "value": 0.05,
            }
        ])
        snippets.append({
            "snippet_id": "snippet:industry_analysis:market_demand",
            "source_ref_id": f"src:{profile_name}:default",
            "text": "Strong industry-wide demand tailwinds observed across peers, with broad expansion in near-term and mid-term cloud spend.",
        })
    elif profile_name == "comps_analysis":
        facts.extend([
            {
                "fact_id": "fact:comps_analysis:peer_average_multiple",
                "fact_name": "peer_average_multiple",
                "value": 18.5,
                "unit": "EV/EBIT",
            }
        ])
        snippets.append({
            "snippet_id": "snippet:comps_analysis:valuation_gap",
            "source_ref_id": f"src:{profile_name}:default",
            "text": "Peer average multiple of 18.5x EV/EBIT suggests an exit multiple premium is highly supported by current market conditions.",
        })
    elif profile_name == "risk_review":
        facts.extend([
            {
                "fact_id": "fact:risk_review:debt_to_equity",
                "fact_name": "debt_to_equity",
                "value": 1.2,
            }
        ])
        snippets.append({
            "snippet_id": "snippet:risk_review:execution_risk",
            "source_ref_id": f"src:{profile_name}:default",
            "text": "Filing discloses heightened execution risk around legacy segment transformation, though balance sheet remains robust.",
        })
    elif profile_name == "valuation_review":
        facts.extend([
            {
                "fact_id": "fact:valuation_review:current_wacc",
                "fact_name": "current_wacc",
                "value": 0.082,
            }
        ])
        snippets.append({
            "snippet_id": "snippet:valuation_review:discount_inconsistency",
            "source_ref_id": f"src:{profile_name}:default",
            "text": "Internal WACC methodology debate suggests the terminal value could be overly sensitive to minor changes in exit multiple assumptions.",
        })
    else:
        snippets.append({
            "snippet_id": f"snippet:{profile_name}:default",
            "source_ref_id": f"src:{profile_name}:default",
            "text": f"Default evidence placeholder for {profile_name}.",
        })

    return {
        "source_refs": source_refs,
        "facts": facts,
        "snippets": snippets,
        "run_metadata": {"profile_name": profile_name},
    }


def _build_profile_packet(ticker: str, profile_name: str) -> EvidencePacket:
    profile = get_agentic_handoff_profile(profile_name)
    inputs = _collect_profile_inputs(ticker, profile_name)
    generated_at = _now()
    return EvidencePacket(
        ticker=ticker,
        profile_name=profile.profile_name,
        packet_kind=profile.evidence_packet_kinds[0],
        generated_at=generated_at,
        source_refs=[EvidenceSourceRef.model_validate(row) for row in inputs.get("source_refs") or []],
        facts=[EvidencePacketFact.model_validate(row) for row in inputs.get("facts") or []],
        snippets=[TextEvidenceSnippet.model_validate(row) for row in inputs.get("snippets") or []],
        run_metadata=inputs.get("run_metadata") or {},
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
