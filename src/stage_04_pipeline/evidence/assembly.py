from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

from src.contracts.evidence_packet import (
    EvidencePacket,
    EvidencePacketFact,
    EvidenceSourceQuality,
    EvidenceSourceRef,
    TextEvidenceSnippet,
)
from src.stage_04_pipeline.agentic_handoff_profiles import get_agentic_handoff_profile


@dataclass(frozen=True)
class PacketMaterial:
    source_refs: tuple[dict[str, Any], ...] = ()
    facts: tuple[dict[str, Any], ...] = ()
    snippets: tuple[dict[str, Any], ...] = ()
    run_metadata: Mapping[str, Any] = ()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def assemble_packet(
    *,
    ticker: str,
    profile_name: str,
    material: PacketMaterial,
) -> EvidencePacket:
    """Validate and serialize already-selected evidence; perform no acquisition."""
    profile = get_agentic_handoff_profile(profile_name)
    generated_at = _now()
    run_metadata = dict(material.run_metadata or {})
    source_quality = str(
        run_metadata.get("source_quality")
        or EvidenceSourceQuality.placeholder.value
    ).strip().lower()
    run_metadata["source_quality"] = source_quality
    return EvidencePacket(
        ticker=ticker.upper().strip(),
        profile_name=profile.profile_name,
        packet_kind=profile.evidence_packet_kinds[0],
        generated_at=generated_at,
        source_refs=[EvidenceSourceRef.model_validate(row) for row in material.source_refs or []],
        facts=[EvidencePacketFact.model_validate(row) for row in material.facts or []],
        snippets=[TextEvidenceSnippet.model_validate(row) for row in material.snippets or []],
        run_metadata=run_metadata,
    )
