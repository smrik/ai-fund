from __future__ import annotations

import json
import re
from typing import Any
from pydantic import BaseModel, Field

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

_OBSERVATION_TYPE_GUIDANCE: dict[str, str] = {
    "guidance_revenue_raised": "Explicit forward revenue guidance was raised by management.",
    "guidance_revenue_lowered": "Explicit forward revenue guidance was lowered by management.",
    "revenue_growth_guidance_disclosed": "Explicit forward revenue growth guidance was disclosed; historical CAGR alone is not guidance.",
    "margin_target_disclosed": "Explicit forward margin target was disclosed; historical margin alone is not a target.",
    "historical_growth_quality": "Historical growth facts such as multi-year CAGR or YoY growth affect thesis quality but do not by themselves change deterministic assumptions.",
    "demand_strength_broad": "Current demand evidence is broad enough to review revenue growth assumptions.",
    "demand_softness_broad": "Current demand evidence is weak enough to review revenue growth assumptions.",
    "pricing_pressure_improved": "Evidence supports improving pricing power or margins.",
    "pricing_pressure_worsened": "Evidence supports worsening pricing power or margins.",
    "execution_risk_increased": "Evidence raises execution, liquidity, covenant, regulatory, cyber, or operational risk.",
    "multiple_premium_supported": "Comps evidence supports a higher exit multiple than the deterministic model uses.",
    "multiple_discount_supported": "Comps evidence supports a lower exit multiple than the deterministic model uses.",
    "peer_set_drift_detected": "Peer-count, cleaning, or comparability evidence makes the peer set questionable.",
    "terminal_value_fragility": "Valuation is highly sensitive to terminal value assumptions, using correctly cited scenario specs and outputs.",
    "wacc_method_disagreement": "WACC inputs or source lineage need PM review.",
    "assumption_inconsistency": "Deterministic assumptions conflict with each other or with source lineage.",
}

_TARGET_DISCLOSURE_OBSERVATION_TYPES = {
    "margin_target_disclosed",
    "revenue_growth_guidance_disclosed",
}

_SHORT_DRIVER_IMPLICATIONS = {"wacc"}

_TARGET_DISCLOSURE_PROMPT_RULES = (
    "Target disclosure rules:\n"
    "- Use margin_target_disclosed only for an explicit forward margin target, not for historical margin expansion.\n"
    "- Use revenue_growth_guidance_disclosed only for explicit forward revenue guidance, not for historical revenue growth quality.\n"
    "- For margin_target_disclosed or revenue_growth_guidance_disclosed, metadata.target_value MUST be a numeric decimal target for the deterministic layer, e.g. 0.58 for 58%.\n"
    "- If evidence shows historical margin improvement without a forward target, use pricing_pressure_improved/pricing_pressure_worsened when directly supported, or drop it.\n"
    "- If evidence shows historical recurring growth quality without forward guidance, use historical_growth_quality.\n\n"
)


def _has_numeric_target_value(row: dict[str, Any]) -> bool:
    metadata = row.get("metadata")
    if not isinstance(metadata, dict):
        return False
    value = metadata.get("target_value")
    if value is None:
        return False
    try:
        float(value)
    except (TypeError, ValueError):
        return False
    return True


def _coerce_target_value(value: Any, unit: str | None = None) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    unit_text = str(unit or "").strip().lower()
    if unit_text in {"pct", "percent", "%"} or abs(numeric) > 1.0:
        return numeric / 100.0
    return numeric


def _infer_target_value_from_anchors(
    row: dict[str, Any],
    packet: EvidencePacket,
    observation_type: str,
) -> float | None:
    anchor_ids = {str(value) for value in (row.get("evidence_anchor_ids") or [])}
    facts_by_id = {fact.fact_id: fact for fact in packet.facts}
    if observation_type == "margin_target_disclosed":
        required_terms = ("margin", "target")
    elif observation_type == "revenue_growth_guidance_disclosed":
        required_terms = ("guidance",)
    else:
        return None
    for anchor_id in anchor_ids:
        fact = facts_by_id.get(anchor_id)
        if fact is None:
            continue
        fact_name = str(fact.fact_name or "").lower()
        if all(term in fact_name for term in required_terms):
            return _coerce_target_value(fact.value, fact.unit)
    return None


class _StructuredObservationRow(BaseModel):
    observation_id: str | None = None
    observation_type: str
    observation_kind: str
    claim: str
    evidence_anchor_ids: list[str] = Field(default_factory=list)
    text_snippet_ids: list[str] = Field(default_factory=list)
    direction: str | None = None
    qualitative_importance: str | None = None
    agent_confidence: str | None = None
    materiality: str | None = None
    thesis_implication: str
    driver_implication: str
    evidence_rationale: str
    pm_question: str
    what_would_change_mind: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class _StructuredObservationPayload(BaseModel):
    observations: list[_StructuredObservationRow] = Field(default_factory=list)


def build_agentic_system_prompt(
    profile_name: str,
    agent_name: str = "GroundedObservationAgent",
) -> str:
    profile = get_agentic_handoff_profile(profile_name)
    profile_guidance = "\n".join(f"- {line}" for line in profile.prompt_guidance)
    return (
        f"You are {agent_name}, a grounded observation runner for Alpha Pod's PM Queue handoff.\n"
        f"profile_name: {profile.profile_name}\n"
        f"prompt_key: {profile.prompt_key}\n\n"
        "Boundary rules:\n"
        "- Use only evidence packet facts, snippets, source refs, and run metadata supplied by the user prompt.\n"
        "- Produce observations only; never produce deterministic valuation edits or direct overrides.\n"
        "- Cite exact fact_id, snippet_id, or source_ref_id strings from the packet.\n"
        "- If the packet is too thin, generic, or not directly tied to an allowed observation type, return no observations.\n\n"
        f"Profile guidance:\n{profile_guidance}\n"
    )


def _material_terms(text: str) -> set[str]:
    normalized = str(text).lower().replace("_", " ").replace("-", " ")
    return {
        token
        for token in re.findall(r"[a-zA-Z][a-zA-Z0-9]{2,}", normalized)
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

    if len(claim) < 15 or len(rationale) < 15:
        return False
    if (len(driver) < 8 and driver.lower() not in _SHORT_DRIVER_IMPLICATIONS) or len(pm_question) < 15 or "?" not in pm_question:
        return False
    if len(thesis) < 15 or len(change_mind) < 15:
        return False

    has_overlap = _has_specific_evidence_overlap(row, anchor_ids, evidence_by_anchor)
    if any(phrase in combined for phrase in _GENERIC_OBSERVATION_PHRASES) and not has_overlap:
        return False
    return has_overlap


def _compact_anchor_evidence_index(packet: EvidencePacket, *, max_chars: int = 280) -> dict[str, str]:
    evidence: dict[str, str] = {}
    for anchor_id, text in _evidence_text_by_anchor(packet).items():
        compact = " ".join(str(text or "").split())
        if len(compact) > max_chars:
            compact = f"{compact[: max_chars - 3].rstrip()}..."
        evidence[anchor_id] = compact
    return evidence


def build_extraction_prompt(packet: EvidencePacket, profile_name: str, agent_name: str) -> str:
    facts = [row.model_dump() for row in packet.facts]
    snippets = [row.model_dump() for row in packet.snippets]
    source_refs = [row.model_dump() for row in packet.source_refs]
    profile = get_agentic_handoff_profile(profile_name)
    allowed_types = list(profile.allowed_observation_types)
    observation_type_guidance = "\n".join(
        f"- {name}: {_OBSERVATION_TYPE_GUIDANCE.get(name, 'Use only when directly supported by cited evidence.')}"
        for name in allowed_types
    )

    return (
        f"Extract key observations from the following evidence for ticker {packet.ticker}.\n"
        f"Agent: {agent_name}\n"
        f"profile_name: {profile_name}\n"
        f"packet_kind: {packet.packet_kind.value}\n"
        f"allowed_observation_types: {json.dumps(allowed_types)}\n\n"
        "Important boundary:\n"
        "- Agents produce observations only.\n"
        "- Extract observations only.\n"
        "- Do not propose deterministic model edits or direct valuation overrides.\n\n"
        f"Allowed observation type definitions:\n{observation_type_guidance}\n\n"
        f"{_TARGET_DISCLOSURE_PROMPT_RULES}"
        "Instructions for Extraction:\n"
        "1. Identify the most important analytical points from the data below.\n"
        "2. Write them out in plain text (bullet points are fine).\n"
        "3. CRITICAL: For every point you make, you MUST cite the EXACT 'fact_id', 'snippet_id', or 'source_ref_id' string from the provided data. Do not invent or modify IDs.\n"
        "4. Focus on identifying the core claim, why the evidence supports it, and what it implies for the thesis or valuation drivers.\n"
        "5. Include materiality, thesis_implication, driver implication, and pm_question in plain text when useful.\n"
        "6. Return no observation when evidence is thin, generic, or not directly connected to an allowed observation type.\n\n"
        "If the packet is too thin for a PM-useful observation, return no observations.\n\n"
        f"source_refs: {json.dumps(source_refs)}\n"
        f"facts: {json.dumps(facts)}\n"
        f"snippets: {json.dumps(snippets)}\n"
    )


def build_agentic_observation_prompt(packet: EvidencePacket, profile_name: str, agent_name: str) -> str:
    """Backward-compatible name for callers that inspect the first-pass prompt."""
    return build_extraction_prompt(packet, profile_name, agent_name)


def build_formatting_prompt(packet: EvidencePacket, raw_extraction: str, profile_name: str, agent_name: str) -> str:
    profile = get_agentic_handoff_profile(profile_name)
    allowed_types = list(profile.allowed_observation_types)
    observation_type_guidance = "\n".join(
        f"- {name}: {_OBSERVATION_TYPE_GUIDANCE.get(name, 'Use only when directly supported by cited evidence.')}"
        for name in allowed_types
    )

    valid_anchor_ids = (
        [fact.fact_id for fact in packet.facts]
        + [snippet.snippet_id for snippet in packet.snippets]
        + [source.source_ref_id for source in packet.source_refs]
    )
    valid_snippet_ids = [s.snippet_id for s in packet.snippets]
    anchor_evidence_index = _compact_anchor_evidence_index(packet)

    return (
        f"Format the following extracted observations into strict JSON.\n"
        f"Agent: {agent_name}\n"
        f"profile_name: {profile_name}\n"
        f"allowed_observation_types: {json.dumps(allowed_types)}\n\n"
        f"Allowed observation type definitions:\n{observation_type_guidance}\n\n"
        "Raw Extraction:\n"
        f"{raw_extraction}\n\n"
        "Instructions for Formatting:\n"
        "Return a JSON object with a single key `observations` containing a list of objects. Each object MUST include:\n"
        "- observation_type (must be one of the allowed_observation_types)\n"
        "- observation_kind (qualitative|numeric)\n"
        "- claim (string)\n"
        f"- evidence_anchor_ids: list of exact IDs cited. MUST be chosen from this exact list: {json.dumps(valid_anchor_ids)}\n"
        f"- text_snippet_ids: list of exact snippet IDs cited. MUST be chosen from this exact list: {json.dumps(valid_snippet_ids)}\n"
        "- qualitative_importance (optional: low|medium|high)\n"
        "- materiality (optional: low|medium|high)\n"
        "- agent_confidence (optional: low|medium|high)\n"
        "- evidence_rationale (1 sentence explaining why the cited evidence supports the claim)\n"
        "- thesis_implication (1 sentence on what this means for the long/short thesis)\n"
        "- driver_implication (1 sentence naming the affected valuation driver, e.g., revenue_growth_near, ebit_margin_target, wacc, exit_multiple, terminal_growth)\n"
        "- pm_question (1 concrete question ending in '?' for the PM)\n"
        "- what_would_change_mind (1 sentence naming evidence that would weaken the observation)\n\n"
        f"{_TARGET_DISCLOSURE_PROMPT_RULES}"
        "Quality bar:\n"
        "- The pm_question MUST contain a '?'.\n"
        "- The driver_implication MUST be at least 8 characters unless the driver is wacc.\n"
        "- For demand_strength_broad or demand_softness_broad, name revenue_growth_near/revenue_growth_mid unless the cited evidence separately supports a margin change.\n"
        "- Drop any raw-text observation when the cited IDs do not directly support the claim.\n"
        "- It is valid to return an empty observations list if no supported PM-useful observation remains.\n\n"
        f"Anchor evidence index for support checks: {json.dumps(anchor_evidence_index)}\n"
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
    rejection_reasons: list[dict[str, Any]] | None = None,
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
        if rejection_reasons is not None:
            rejection_reasons.append({"row_index": None, "reason": "observations_not_list"})
        return []

    accepted: list[EvidencePacketObservation] = []
    for idx, row in enumerate(raw_observations, start=1):
        def reject(reason: str, **details: Any) -> None:
            if rejection_reasons is not None:
                rejection_reasons.append({"row_index": idx, "reason": reason, **details})

        if not isinstance(row, dict):
            reject("row_not_object")
            continue
        observation_type = str(row.get("observation_type") or "").strip()
        if observation_type not in allowed_types:
            reject("observation_type_not_allowed", observation_type=observation_type)
            continue
        if observation_type in _TARGET_DISCLOSURE_OBSERVATION_TYPES and not _has_numeric_target_value(row):
            inferred_target_value = _infer_target_value_from_anchors(row, packet, observation_type)
            if inferred_target_value is None:
                reject("target_disclosure_missing_numeric_target", observation_type=observation_type)
                continue
            metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
            row = {**row, "metadata": {**metadata, "target_value": inferred_target_value}}
        anchor_ids = [str(value) for value in (row.get("evidence_anchor_ids") or []) if str(value).strip()]
        if not anchor_ids:
            reject("missing_evidence_anchor_ids")
            continue
        if any(anchor not in valid_anchor_ids for anchor in anchor_ids):
            reject(
                "unknown_evidence_anchor_id",
                unknown_anchor_ids=[anchor for anchor in anchor_ids if anchor not in valid_anchor_ids],
            )
            continue
        text_snippet_ids = [str(value) for value in (row.get("text_snippet_ids") or []) if str(value).strip()]
        if any(snippet_id not in valid_snippet_ids for snippet_id in text_snippet_ids):
            reject(
                "unknown_text_snippet_id",
                unknown_text_snippet_ids=[snippet_id for snippet_id in text_snippet_ids if snippet_id not in valid_snippet_ids],
            )
            continue
        usefulness_anchor_ids = list(dict.fromkeys([*anchor_ids, *text_snippet_ids]))
        if not _passes_pm_usefulness_gate(row, anchor_ids=usefulness_anchor_ids, evidence_by_anchor=evidence_by_anchor):
            reject("pm_usefulness_gate_failed", observation_type=observation_type)
            continue
        raw_kind = str(row.get("observation_kind") or "").strip().lower()
        if raw_kind == "qualitative":
            # Fail closed: qualitative observations without text snippet anchors are invalid.
            if not text_snippet_ids:
                reject("qualitative_observation_missing_text_snippet")
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
        except Exception as exc:
            # Fail closed: invalid observations are dropped.
            reject("observation_contract_validation_failed", message=str(exc))
            continue
    return accepted


def analyze_evidence_packet_with_agent(
    *,
    agent: Any,
    packet: EvidencePacket,
    profile_name: str,
) -> list[EvidencePacketObservation]:
    agent_name = getattr(agent, "name", "Agent")
    artifact: dict[str, Any] = {
        "profile_name": profile_name,
        "packet_id": packet.packet_id,
        "packet_kind": packet.packet_kind.value,
        "ticker": packet.ticker,
        "source_quality": (packet.run_metadata or {}).get("source_quality"),
        "fact_ids": [fact.fact_id for fact in packet.facts],
        "snippet_ids": [snippet.snippet_id for snippet in packet.snippets],
        "source_ref_ids": [source.source_ref_id for source in packet.source_refs],
        "extraction_prompt": None,
        "raw_extraction": None,
        "formatting_prompt": None,
        "raw_formatting_output": None,
        "structured_model_used": None,
        "accepted_observation_count": 0,
        "accepted_observation_ids": [],
        "model_used": None,
    }
    setattr(agent, "last_agentic_observation_artifact", artifact)
    
    # Pass 1: Extraction
    extraction_prompt = build_extraction_prompt(packet, profile_name, agent_name)
    artifact["extraction_prompt"] = extraction_prompt
    raw_extraction = agent.run(extraction_prompt)
    artifact["raw_extraction"] = raw_extraction
    
    # Pass 2: Formatting (strict parse first, raw-json fallback)
    formatting_prompt = build_formatting_prompt(packet, raw_extraction, profile_name, agent_name)
    artifact["formatting_prompt"] = formatting_prompt
    payload: dict[str, Any] | None = None
    if hasattr(agent, "run_structured_payload"):
        try:
            payload, model_used = agent.run_structured_payload(
                formatting_prompt,
                _StructuredObservationPayload,
            )
            artifact["structured_model_used"] = model_used
        except Exception:
            payload = None
    if payload is None:
        raw_json = agent.run(formatting_prompt)
    else:
        raw_json = json.dumps(payload, ensure_ascii=False)
    artifact["raw_formatting_output"] = raw_json

    rejection_reasons: list[dict[str, Any]] = []
    observations = parse_agentic_observations(
        raw=raw_json,
        packet=packet,
        profile_name=profile_name,
        rejection_reasons=rejection_reasons,
    )
    artifact["accepted_observation_count"] = len(observations)
    artifact["accepted_observation_ids"] = [observation.observation_id for observation in observations]
    artifact["rejected_observation_count"] = len(rejection_reasons)
    artifact["rejection_reasons"] = rejection_reasons
    artifact["model_used"] = getattr(agent, "last_used_model", None)
    return observations
