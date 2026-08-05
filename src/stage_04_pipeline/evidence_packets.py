from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable

from db.schema import create_tables, get_connection
from src.contracts.evidence_packet import EvidencePacket, EvidencePacketKind
from src.stage_04_pipeline.evidence.accounting import (
    build_accounting_packet,
)
from src.stage_04_pipeline.evidence.context import build_business_context_packet
from src.stage_04_pipeline.evidence.reviews import (
    build_review_packet,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_company_analysis_packet(
    ticker: str,
    *,
    db_path: str | None = None,
) -> EvidencePacket:
    """Business-context packet."""
    return build_business_context_packet(db_path, ticker)


def build_accounting_qoe_packet(ticker: str) -> EvidencePacket:
    return build_accounting_packet(ticker, "accounting_qoe")


def build_accounting_ev_equity_bridge_packet(ticker: str) -> EvidencePacket:
    return build_accounting_packet(ticker, "accounting_ev_equity_bridge")


def build_accounting_contingencies_and_taxes_packet(ticker: str) -> EvidencePacket:
    return build_accounting_packet(ticker, "accounting_contingencies_and_taxes")


def build_accounting_segments_and_disclosure_packet(ticker: str) -> EvidencePacket:
    return build_accounting_packet(ticker, "accounting_segments_and_disclosure")


def build_earnings_update_packet(ticker: str) -> EvidencePacket:
    return build_review_packet(ticker, "earnings_update")


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
