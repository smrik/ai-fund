from __future__ import annotations

import json
from typing import Any

from src.contracts.evidence_packet import (
    EvidencePacket,
    EvidencePacketObservation,
    EvidencePacketObservationKind,
)
from src.stage_03_judgment.base_agent import BaseAgent
from src.stage_04_pipeline.agentic_handoff_profiles import get_agentic_handoff_profile


def build_agentic_observation_prompt(packet: EvidencePacket, profile_name: str, agent_name: str) -> str:
    facts = [row.model_dump() for row in packet.facts]
    snippets = [row.model_dump() for row in packet.snippets]
    source_refs = [row.model_dump() for row in packet.source_refs]
    allowed_types = list(get_agentic_handoff_profile(profile_name).allowed_observation_types)
    return (
        f"Generate anchored observations for ticker {packet.ticker}.\n"
        f"Agent: {agent_name}\n"
        f"profile_name: {profile_name}\n"
        f"packet_kind: {packet.packet_kind.value}\n"
        f"allowed_observation_types: {json.dumps(allowed_types)}\n\n"
        "Return JSON object with key `observations` as a list. Each item should include:\n"
        "- observation_type\n"
        "- observation_kind (qualitative|numeric)\n"
        "- claim\n"
        "- evidence_anchor_ids (must reference fact_id, snippet_id, or source_ref_id)\n"
        "- text_snippet_ids (required for qualitative)\n"
        "- qualitative_importance (optional: low|medium|high)\n"
        "- agent_confidence (optional: low|medium|high)\n\n"
        f"source_refs: {json.dumps(source_refs)}\n"
        f"facts: {json.dumps(facts)}\n"
        f"snippets: {json.dumps(snippets)}\n"
    )


def _parse_raw_json(raw: str) -> dict[str, Any]:
    try:
        return BaseAgent.extract_json(raw)
    except Exception:
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}


def parse_agentic_observations(
    *,
    raw: str,
    packet: EvidencePacket,
    profile_name: str,
) -> list[EvidencePacketObservation]:
    profile = get_agentic_handoff_profile(profile_name)
    allowed_types = set(profile.allowed_observation_types)
    valid_anchor_ids = {fact.fact_id for fact in packet.facts}
    valid_anchor_ids.update({snippet.snippet_id for snippet in packet.snippets})
    valid_anchor_ids.update({source.source_ref_id for source in packet.source_refs})
    valid_snippet_ids = {snippet.snippet_id for snippet in packet.snippets}

    payload = _parse_raw_json(raw)
    raw_observations = payload.get("observations")
    if not isinstance(raw_observations, list):
        return []

    accepted: list[EvidencePacketObservation] = []
    for idx, row in enumerate(raw_observations, start=1):
        if not isinstance(row, dict):
            continue
        observation_type = str(row.get("observation_type") or "").strip()
        if observation_type not in allowed_types:
            continue
        anchor_ids = [str(value) for value in (row.get("evidence_anchor_ids") or []) if str(value).strip()]
        if not anchor_ids:
            continue
        if any(anchor not in valid_anchor_ids for anchor in anchor_ids):
            continue
        text_snippet_ids = [str(value) for value in (row.get("text_snippet_ids") or []) if str(value).strip()]
        if any(snippet_id not in valid_snippet_ids for snippet_id in text_snippet_ids):
            continue
        raw_kind = str(row.get("observation_kind") or "").strip().lower()
        if raw_kind == "qualitative":
            # Fail closed: qualitative observations without text snippet anchors are invalid.
            if not text_snippet_ids:
                continue
            observation_kind = EvidencePacketObservationKind.qualitative
        elif raw_kind == "numeric":
            observation_kind = EvidencePacketObservationKind.numeric
        else:
            # Unknown kind: infer from presence of snippets; drop qualitative inference without snippets.
            if text_snippet_ids:
                observation_kind = EvidencePacketObservationKind.qualitative
            else:
                observation_kind = EvidencePacketObservationKind.numeric
        observation = {
            "observation_id": row.get("observation_id") or f"obs:{profile_name}:{idx}",
            "observation_kind": observation_kind.value,
            "observation_type": observation_type,
            "claim": row.get("claim") or "",
            "evidence_anchor_ids": anchor_ids,
            "text_snippet_ids": text_snippet_ids,
            "direction": row.get("direction"),
            "qualitative_importance": row.get("qualitative_importance"),
            "agent_confidence": row.get("agent_confidence"),
            "metadata": row.get("metadata") or {},
        }
        try:
            accepted.append(EvidencePacketObservation.model_validate(observation))
        except Exception:
            # Fail closed: invalid observations are dropped.
            continue
    return accepted


def analyze_evidence_packet_with_agent(
    *,
    agent: Any,
    packet: EvidencePacket,
    profile_name: str,
) -> list[EvidencePacketObservation]:
    prompt = build_agentic_observation_prompt(packet, profile_name, getattr(agent, "name", "Agent"))
    raw = agent.run(prompt)
    return parse_agentic_observations(raw=raw, packet=packet, profile_name=profile_name)
