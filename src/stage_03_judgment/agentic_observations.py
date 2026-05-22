from __future__ import annotations

import json
import re
from typing import Any

from src.contracts.evidence_packet import (
    EvidencePacket,
    EvidencePacketObservation,
    EvidencePacketObservationKind,
)
from src.stage_03_judgment.base_agent import BaseAgent
from src.stage_04_pipeline.agentic_handoff_profiles import get_agentic_handoff_profile


_GENERIC_OBSERVATION_PHRASES = (
    "warrants pm review",
    "could change the confidence",
    "enough to raise a pm-review item",
    "material to the thesis",
    "review before accepting",
    "supports reviewing whether",
)

_STOPWORDS = {
    "about",
    "across",
    "against",
    "agent",
    "also",
    "and",
    "any",
    "are",
    "before",
    "being",
    "both",
    "but",
    "can",
    "company",
    "could",
    "current",
    "does",
    "driver",
    "evidence",
    "from",
    "has",
    "have",
    "into",
    "its",
    "make",
    "may",
    "model",
    "not",
    "observation",
    "only",
    "packet",
    "review",
    "should",
    "that",
    "the",
    "this",
    "ticker",
    "what",
    "when",
    "which",
    "with",
    "would",
}


def _material_terms(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-zA-Z][a-zA-Z0-9_\-]{2,}", str(text).lower())
        if token not in _STOPWORDS
    }


def _evidence_text_by_anchor(packet: EvidencePacket) -> dict[str, str]:
    evidence: dict[str, str] = {}
    for fact in packet.facts:
        evidence[fact.fact_id] = f"{fact.fact_name} {fact.value} {json.dumps(fact.metadata, default=str)}"
    for snippet in packet.snippets:
        evidence[snippet.snippet_id] = snippet.text
    for source in packet.source_refs:
        evidence[source.source_ref_id] = (
            f"{source.source_kind} {source.source_label} {source.source_locator} "
            f"{json.dumps(source.metadata, default=str)}"
        )
    return evidence


def _has_specific_evidence_overlap(row: dict[str, Any], anchor_ids: list[str], evidence_by_anchor: dict[str, str]) -> bool:
    anchored_text = " ".join(evidence_by_anchor.get(anchor, "") for anchor in anchor_ids)
    evidence_terms = _material_terms(anchored_text)
    if not evidence_terms:
        return False
    observation_text = " ".join(
        str(row.get(key) or "")
        for key in (
            "claim",
            "evidence_rationale",
            "thesis_implication",
            "driver_implication",
            "pm_question",
        )
    )
    observation_terms = _material_terms(observation_text)
    return bool(evidence_terms & observation_terms)


def _passes_pm_usefulness_gate(
    row: dict[str, Any],
    *,
    anchor_ids: list[str],
    evidence_by_anchor: dict[str, str],
) -> bool:
    claim = str(row.get("claim") or "").strip()
    rationale = str(row.get("evidence_rationale") or "").strip()
    thesis = str(row.get("thesis_implication") or "").strip()
    driver = str(row.get("driver_implication") or "").strip()
    pm_question = str(row.get("pm_question") or "").strip()
    change_mind = str(row.get("what_would_change_mind") or "").strip()
    combined = " ".join([claim, rationale, thesis, driver, pm_question, change_mind]).lower()

    if len(claim) < 35 or len(rationale) < 35:
        return False
    if len(driver) < 8 or len(pm_question) < 25 or "?" not in pm_question:
        return False
    if len(thesis) < 30 or len(change_mind) < 30:
        return False
    if any(phrase in combined for phrase in _GENERIC_OBSERVATION_PHRASES) and not _has_specific_evidence_overlap(
        row,
        anchor_ids,
        evidence_by_anchor,
    ):
        return False
    return _has_specific_evidence_overlap(row, anchor_ids, evidence_by_anchor)


def build_agentic_observation_prompt(packet: EvidencePacket, profile_name: str, agent_name: str) -> str:
    facts = [row.model_dump() for row in packet.facts]
    snippets = [row.model_dump() for row in packet.snippets]
    source_refs = [row.model_dump() for row in packet.source_refs]
    profile = get_agentic_handoff_profile(profile_name)
    allowed_types = list(profile.allowed_observation_types)
    profile_guidance = "\n".join(f"- {line}" for line in profile.prompt_guidance)
    return (
        f"Generate anchored observations for ticker {packet.ticker}.\n"
        f"Agent: {agent_name}\n"
        f"profile_name: {profile_name}\n"
        f"packet_kind: {packet.packet_kind.value}\n"
        f"allowed_observation_types: {json.dumps(allowed_types)}\n\n"
        "Important boundary:\n"
        "- Agents produce observations only.\n"
        "- Do not propose deterministic model edits or direct valuation overrides.\n\n"
        f"Profile guidance:\n{profile_guidance}\n\n"
        "Return JSON object with key `observations` as a list. Each item should include:\n"
        "- observation_type\n"
        "- observation_kind (qualitative|numeric)\n"
        "- claim\n"
        "- evidence_anchor_ids: list of IDs taken VERBATIM from the fact_id, snippet_id, or source_ref_id fields in the data below (do NOT invent IDs or add prefixes)\n"
        "- text_snippet_ids (required for qualitative; must be taken VERBATIM from snippet_id fields below)\n"
        "- qualitative_importance (optional: low|medium|high)\n"
        "- materiality (optional: low|medium|high; use high only when the observation could change thesis or valuation)\n"
        "- agent_confidence (optional: low|medium|high)\n"
        "- evidence_rationale (1 sentence explaining why the cited evidence supports the claim)\n"
        "- thesis_implication (1 sentence on what this means for the long/short thesis)\n"
        "- driver_implication (1 sentence naming the affected valuation driver, if any)\n"
        "- pm_question (1 concrete question the PM should answer before approving any change)\n"
        "- what_would_change_mind (1 sentence naming the evidence that would weaken or reverse the observation)\n\n"
        "Quality bar:\n"
        "- Prefer one material observation over several generic ones.\n"
        "- Do not restate facts unless you explain why they matter to a PM.\n"
        "- The claim and evidence_rationale must name the concrete cited evidence signal, not just say the packet warrants review.\n"
        "- The driver_implication must name a specific valuation driver such as revenue_growth_near, ebit_margin_target, wacc, exit_multiple, or terminal_growth (minimum 8 chars).\n"
        "- IMPORTANT: evidence_anchor_ids and text_snippet_ids must use the EXACT id strings from fact_id / snippet_id / source_ref_id fields in the data below. Do not add prefixes or modify the IDs.\n"
        "- The pm_question must be a question mark sentence that a PM could answer approve/edit/reject from.\n"
        "- If the packet is too thin for a PM-useful observation, return an empty observations list.\n\n"
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
    evidence_by_anchor = _evidence_text_by_anchor(packet)

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
        usefulness_anchor_ids = list(dict.fromkeys([*anchor_ids, *text_snippet_ids]))
        if not _passes_pm_usefulness_gate(row, anchor_ids=usefulness_anchor_ids, evidence_by_anchor=evidence_by_anchor):
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
            "materiality": row.get("materiality"),
            "thesis_implication": row.get("thesis_implication"),
            "driver_implication": row.get("driver_implication"),
            "evidence_rationale": row.get("evidence_rationale"),
            "pm_question": row.get("pm_question"),
            "what_would_change_mind": row.get("what_would_change_mind"),
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
