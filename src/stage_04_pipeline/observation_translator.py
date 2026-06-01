from __future__ import annotations

from typing import Any

from src.contracts.evidence_packet import EvidencePacket, EvidencePacketObservation
from src.contracts.pm_decision_queue import (
    AssumptionChangePack,
    AssumptionChangeProposal,
    PMDecisionQueueItem,
    PMDecisionQueueItemType,
    ProposalMode,
    QueueConfidence,
)
from src.stage_04_pipeline.agentic_handoff_profiles import (
    AGENT_PROPOSABLE_ASSUMPTION_FIELDS,
    get_agentic_handoff_profile,
)


TRANSLATOR_RULES: dict[str, dict[str, dict[str, Any]]] = {
    "earnings_update": {
        "guidance_revenue_raised": {
            "rule_type": "assumption_change_pack",
            "proposals": [
                {"assumption_name": "revenue_growth_near", "proposal_mode": "delta", "proposed_delta": 0.01}
            ],
            "translator_confidence": "high",
        },
        "guidance_revenue_lowered": {
            "rule_type": "assumption_change_pack",
            "proposals": [
                {"assumption_name": "revenue_growth_near", "proposal_mode": "delta", "proposed_delta": -0.01}
            ],
            "translator_confidence": "high",
        },
        "pricing_pressure_improved": {
            "rule_type": "assumption_change_pack",
            "proposals": [
                {"assumption_name": "ebit_margin_start", "proposal_mode": "delta", "proposed_delta": 0.005}
            ],
            "translator_confidence": "medium",
        },
        "pricing_pressure_worsened": {
            "rule_type": "assumption_change_pack",
            "proposals": [
                {"assumption_name": "ebit_margin_start", "proposal_mode": "delta", "proposed_delta": -0.005}
            ],
            "translator_confidence": "medium",
        },
        "demand_strength_broad": {
            "rule_type": "assumption_change_pack",
            "proposals": [
                {"assumption_name": "revenue_growth_near", "proposal_mode": "delta", "proposed_delta": 0.01},
            ],
            "translator_confidence": "medium",
        },
        "demand_softness_broad": {
            "rule_type": "assumption_change_pack",
            "proposals": [
                {"assumption_name": "revenue_growth_near", "proposal_mode": "delta", "proposed_delta": -0.01},
                {"assumption_name": "ebit_margin_target", "proposal_mode": "delta", "proposed_delta": -0.005},
            ],
            "translator_confidence": "medium",
        },
        "execution_risk_increased": {
            "rule_type": "advisory_finding",
            "translator_confidence": "medium",
        },
        "margin_target_disclosed": {
            "rule_type": "assumption_change_pack",
            "proposals": [
                {
                    "assumption_name": "ebit_margin_target",
                    "proposal_mode": "target",
                    "metadata_key": "target_value",
                }
            ],
            "translator_confidence": "high",
        },
        "revenue_growth_guidance_disclosed": {
            "rule_type": "assumption_change_pack",
            "proposals": [
                {
                    "assumption_name": "revenue_growth_near",
                    "proposal_mode": "target",
                    "metadata_key": "target_value",
                }
            ],
            "translator_confidence": "high",
        },
    },
}

# company_analysis: same observation vocabulary as earnings (filings disclose the same guidance/margin/risk signals)
# but adds the broader execution_risk observation type.
TRANSLATOR_RULES["company_analysis"] = {
    "margin_target_disclosed": {
        "rule_type": "assumption_change_pack",
        "proposals": [
            {
                "assumption_name": "ebit_margin_target",
                "proposal_mode": "target",
                "metadata_key": "target_value",
            }
        ],
        "translator_confidence": "high",
    },
    "revenue_growth_guidance_disclosed": {
        "rule_type": "assumption_change_pack",
        "proposals": [
            {
                "assumption_name": "revenue_growth_near",
                "proposal_mode": "target",
                "metadata_key": "target_value",
            }
        ],
        "translator_confidence": "high",
    },
    "historical_growth_quality": {
        "rule_type": "advisory_finding",
        "title": "Historical Growth Quality",
        "translator_confidence": "medium",
    },
    "execution_risk_increased": {
        "rule_type": "advisory_finding",
        "translator_confidence": "medium",
    },
    "pricing_pressure_worsened": {
        "rule_type": "assumption_change_pack",
        "title": "Margin Bridge Pressure",
        "proposals": [
            {"assumption_name": "ebit_margin_start", "proposal_mode": "delta", "proposed_delta": -0.005}
        ],
        "translator_confidence": "medium",
    },
    "pricing_pressure_improved": {
        "rule_type": "assumption_change_pack",
        "title": "Margin Bridge Support",
        "proposals": [
            {"assumption_name": "ebit_margin_start", "proposal_mode": "delta", "proposed_delta": 0.005}
        ],
        "translator_confidence": "medium",
    },
}

# industry_analysis: demand and pricing signals affecting near-term revenue and mid-term growth and terminal growth.
TRANSLATOR_RULES["industry_analysis"] = {
    "demand_strength_broad": {
        "rule_type": "assumption_change_pack",
        "proposals": [
            {"assumption_name": "revenue_growth_near", "proposal_mode": "delta", "proposed_delta": 0.01},
            {"assumption_name": "revenue_growth_mid", "proposal_mode": "delta", "proposed_delta": 0.005},
        ],
        "translator_confidence": "medium",
    },
    "demand_softness_broad": {
        "rule_type": "assumption_change_pack",
        "proposals": [
            {"assumption_name": "revenue_growth_near", "proposal_mode": "delta", "proposed_delta": -0.01},
            {"assumption_name": "revenue_growth_mid", "proposal_mode": "delta", "proposed_delta": -0.005},
        ],
        "translator_confidence": "medium",
    },
    "pricing_pressure_improved": {
        "rule_type": "assumption_change_pack",
        "proposals": [
            {"assumption_name": "ebit_margin_target", "proposal_mode": "delta", "proposed_delta": 0.005}
        ],
        "translator_confidence": "medium",
    },
    "pricing_pressure_worsened": {
        "rule_type": "assumption_change_pack",
        "proposals": [
            {"assumption_name": "ebit_margin_target", "proposal_mode": "delta", "proposed_delta": -0.005}
        ],
        "translator_confidence": "medium",
    },
}

# comps_analysis: peer multiple signals → exit_multiple assumption.
# multiple_premium_supported → raise exit_multiple
# multiple_discount_supported → lower exit_multiple
# peer_set_drift_detected → advisory (PM should review peer set)
TRANSLATOR_RULES["comps_analysis"] = {
    "multiple_premium_supported": {
        "rule_type": "assumption_change_pack",
        "proposals": [
            {"assumption_name": "exit_multiple", "proposal_mode": "delta", "proposed_delta": 0.5}
        ],
        "translator_confidence": "medium",
    },
    "multiple_discount_supported": {
        "rule_type": "assumption_change_pack",
        "proposals": [
            {"assumption_name": "exit_multiple", "proposal_mode": "delta", "proposed_delta": -0.5}
        ],
        "translator_confidence": "medium",
    },
    "peer_set_drift_detected": {
        "rule_type": "advisory_finding",
        "translator_confidence": "medium",
    },
}

# risk_review: execution risk always produces an advisory finding; structural risk may flag WACC.
TRANSLATOR_RULES["risk_review"] = {
    "execution_risk_increased": {
        "rule_type": "advisory_finding",
        "translator_confidence": "medium",
    },
}

# valuation_review: model-structural observations produce advisory findings for PM review.
# assumption_inconsistency may also recommend assumption_change_pack for margin/wacc fields.
TRANSLATOR_RULES["valuation_review"] = {
    "terminal_value_fragility": {
        "rule_type": "advisory_finding",
        "translator_confidence": "high",
    },
    "wacc_method_disagreement": {
        "rule_type": "advisory_finding",
        "translator_confidence": "medium",
    },
    "assumption_inconsistency": {
        "rule_type": "advisory_finding",
        "translator_confidence": "medium",
    },
}


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _confidence_weight(value: Any | None) -> float:
    if value is None:
        return 1.0
    raw_value = value.value if hasattr(value, "value") else value
    text = str(raw_value).strip().lower()
    if text == "high":
        return 1.2
    if text == "low":
        return 0.85
    return 1.0


def _proposal_delta_bounds(assumption_name: str) -> tuple[float, float]:
    bounds: dict[str, tuple[float, float]] = {
        "revenue_growth_near": (0.0025, 0.03),
        "revenue_growth_mid": (0.0020, 0.02),
        "ebit_margin_start": (0.0015, 0.015),
        "ebit_margin_target": (0.0015, 0.02),
        "exit_multiple": (0.15, 1.5),
    }
    return bounds.get(assumption_name, (0.001, 0.05))


def _evidence_sized_delta(
    *,
    observation: EvidencePacketObservation,
    assumption_name: str,
    base_delta: float,
) -> tuple[float, dict[str, Any]]:
    metadata = observation.metadata if isinstance(observation.metadata, dict) else {}
    facts = metadata.get("facts_snapshot")
    facts = facts if isinstance(facts, dict) else {}

    scale = 1.0
    reasons: list[str] = []

    # Confidence weighting only when real finance facts are present; otherwise preserve legacy base deltas.
    if facts:
        confidence_scale = (
            _confidence_weight(observation.agent_confidence)
            * _confidence_weight(observation.qualitative_importance)
            * _confidence_weight(observation.materiality)
        )
        confidence_scale = _clamp(confidence_scale, 0.75, 1.5)
        scale *= confidence_scale
        if confidence_scale != 1.0:
            reasons.append(f"confidence={confidence_scale:.2f}")

    if assumption_name in {"revenue_growth_near", "revenue_growth_mid"}:
        yoy = _safe_float(facts.get("latest_quarter_revenue_yoy_pct"))
        cagr = _safe_float(facts.get("revenue_cagr_3y"))
        if yoy is not None:
            yoy_scale = _clamp(abs(yoy) / 8.0, 0.75, 1.8)
            scale *= yoy_scale
            reasons.append(f"yoy_scale={yoy_scale:.2f}")
        elif cagr is not None:
            cagr_scale = _clamp(abs(cagr) / 0.05, 0.75, 1.5)
            scale *= cagr_scale
            reasons.append(f"cagr_scale={cagr_scale:.2f}")
    elif assumption_name in {"ebit_margin_start", "ebit_margin_target"}:
        gross_margin = _safe_float(facts.get("gross_margin_avg_3y"))
        if gross_margin is not None:
            margin_scale = _clamp(gross_margin / 0.50, 0.85, 1.35)
            scale *= margin_scale
            reasons.append(f"gross_margin_scale={margin_scale:.2f}")
    elif assumption_name == "exit_multiple":
        spreads = [
            _safe_float(facts.get("pe_ltm_target_minus_peer_median")),
            _safe_float(facts.get("tev_ebitda_fwd_target_minus_peer_median")),
            _safe_float(facts.get("tev_ebitda_ltm_target_minus_peer_median")),
        ]
        spread_values = [abs(value) for value in spreads if value is not None]
        if spread_values:
            max_spread = max(spread_values)
            spread_scale = _clamp(max_spread / 4.0, 0.75, 2.5)
            scale *= spread_scale
            reasons.append(f"peer_spread_scale={spread_scale:.2f}")

    magnitude = abs(base_delta) * scale
    min_abs, max_abs = _proposal_delta_bounds(assumption_name)
    bounded = _clamp(magnitude, min_abs, max_abs)
    adjusted = bounded if base_delta >= 0 else -bounded
    return adjusted, {
        "base_delta": base_delta,
        "scale": round(scale, 4),
        "bounded_abs_delta": round(bounded, 6),
        "reasons": reasons,
    }


def _to_queue_confidence(value: Any | None) -> QueueConfidence | None:
    if value is None:
        return None
    raw_value = value.value if hasattr(value, "value") else value
    text = str(raw_value).strip().lower()
    if text in {"low", "medium", "high"}:
        return QueueConfidence(text)
    return None


def _queue_title(observation_type: str, rule: dict[str, Any]) -> str:
    return str(rule.get("title") or observation_type.replace("_", " ").title())


def _build_proposals(
    observation: EvidencePacketObservation,
    profile_name: str,
    raw_proposals: list[dict[str, Any]],
) -> list[AssumptionChangeProposal]:
    profile = get_agentic_handoff_profile(profile_name)
    allowed_assumptions = set(AGENT_PROPOSABLE_ASSUMPTION_FIELDS)
    allowed_assumptions.intersection_update(profile.allowed_assumption_fields)
    built: list[AssumptionChangeProposal] = []
    for proposal_def in raw_proposals:
        assumption_name = str(proposal_def.get("assumption_name") or "").strip()
        if not assumption_name or assumption_name not in allowed_assumptions:
            continue
        mode = str(proposal_def.get("proposal_mode") or "").strip().lower()
        if mode == ProposalMode.delta.value:
            proposed_delta = proposal_def.get("proposed_delta")
            if proposed_delta is None:
                continue
            base_delta = float(proposed_delta)
            adjusted_delta, sizing_meta = _evidence_sized_delta(
                observation=observation,
                assumption_name=assumption_name,
                base_delta=base_delta,
            )
            built.append(
                AssumptionChangeProposal(
                    assumption_name=assumption_name,
                    proposal_mode=ProposalMode.delta,
                    proposed_delta=adjusted_delta,
                    rationale=observation.claim,
                    metadata={
                        "sizing_mode": "evidence_weighted",
                        **sizing_meta,
                    },
                )
            )
        elif mode == ProposalMode.target.value:
            metadata_key = str(proposal_def.get("metadata_key") or "target_value")
            target_value = observation.metadata.get(metadata_key)
            if target_value is None:
                target_value = proposal_def.get("proposed_target_value")
            if target_value is None:
                continue
            built.append(
                AssumptionChangeProposal(
                    assumption_name=assumption_name,
                    proposal_mode=ProposalMode.target,
                    proposed_target_value=float(target_value),
                    rationale=observation.claim,
                )
            )
    return built


def _with_packet_fact_snapshot(
    observation: EvidencePacketObservation,
    evidence_packet: EvidencePacket | None,
) -> EvidencePacketObservation:
    if evidence_packet is None or not evidence_packet.facts:
        return observation
    packet_facts = {
        str(fact.fact_name): fact.value
        for fact in evidence_packet.facts
        if str(fact.fact_name or "").strip()
    }
    if not packet_facts:
        return observation
    metadata = dict(observation.metadata or {})
    existing_snapshot = metadata.get("facts_snapshot")
    existing_snapshot = existing_snapshot if isinstance(existing_snapshot, dict) else {}
    metadata["facts_snapshot"] = {**packet_facts, **existing_snapshot}
    return observation.model_copy(update={"metadata": metadata})


def _packet_provenance(evidence_packet: EvidencePacket | None) -> dict[str, Any]:
    if evidence_packet is None:
        return {}
    packet_payload = evidence_packet.model_dump(mode="json")
    compact_payload = {
        "ticker": packet_payload.get("ticker"),
        "profile_name": packet_payload.get("profile_name"),
        "packet_kind": packet_payload.get("packet_kind"),
        "bundle_id": packet_payload.get("bundle_id"),
        "generated_at": packet_payload.get("generated_at"),
        "source_quality": (packet_payload.get("run_metadata") or {}).get("source_quality"),
        "fact_ids": [fact.get("fact_id") for fact in packet_payload.get("facts") or []],
        "snippet_ids": [snippet.get("snippet_id") for snippet in packet_payload.get("snippets") or []],
        "source_ref_ids": [source.get("source_ref_id") for source in packet_payload.get("source_refs") or []],
    }
    import hashlib
    import json

    return {
        **compact_payload,
        "packet_hash": hashlib.sha256(
            json.dumps(compact_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
    }


def translate_observations_to_queue_items(
    *,
    ticker: str,
    profile_name: str,
    evidence_packet_id: int,
    observations: list[EvidencePacketObservation],
    evidence_packet: EvidencePacket | None = None,
    require_evidence_packet: bool = False,
) -> list[PMDecisionQueueItem]:
    if require_evidence_packet and evidence_packet is None:
        raise ValueError("evidence_packet is required for grounded PM Queue translation")
    profile = get_agentic_handoff_profile(profile_name)
    rules = TRANSLATOR_RULES.get(profile.translator_rule_group, {})
    items: list[PMDecisionQueueItem] = []
    emitted_assumption_fields: set[str] = set()
    provenance = _packet_provenance(evidence_packet)
    for raw_observation in observations:
        observation = _with_packet_fact_snapshot(raw_observation, evidence_packet)
        rule = rules.get(observation.observation_type)
        if rule is None:
            continue
        observation_metadata = {
            "observation_id": observation.observation_id,
            "materiality": (
                observation.materiality.value
                if hasattr(observation.materiality, "value")
                else observation.materiality
            ),
            "thesis_implication": observation.thesis_implication,
            "driver_implication": observation.driver_implication,
            "evidence_rationale": observation.evidence_rationale,
            "pm_question": observation.pm_question,
            "what_would_change_mind": observation.what_would_change_mind,
        }
        if provenance:
            observation_metadata["packet_provenance"] = provenance
        observation_metadata = {
            key: value for key, value in observation_metadata.items() if value is not None
        }
        translator_confidence = _to_queue_confidence(rule.get("translator_confidence"))
        if rule.get("rule_type") == "advisory_finding":
            items.append(
                PMDecisionQueueItem(
                    ticker=ticker,
                    profile_name=profile_name,
                    item_type=PMDecisionQueueItemType.advisory_finding,
                    status="pending",
                    title=_queue_title(observation.observation_type, rule),
                    summary=observation.claim,
                    evidence_anchor_ids=observation.evidence_anchor_ids,
                    evidence_packet_ids=[str(evidence_packet_id)],
                    qualitative_importance=observation.qualitative_importance,
                    agent_confidence=_to_queue_confidence(observation.agent_confidence),
                    translator_confidence=translator_confidence,
                    metadata=observation_metadata,
                )
            )
            continue
        raw_proposals = list(rule.get("proposals") or [])
        proposals = _build_proposals(observation, profile_name, raw_proposals)
        if not proposals:
            continue
        proposal_fields = {proposal.assumption_name for proposal in proposals}
        if proposal_fields & emitted_assumption_fields:
            continue
        emitted_assumption_fields.update(proposal_fields)
        proposal_pack = AssumptionChangePack(
            pack_id=f"pack:{profile_name}:{observation.observation_id}",
            proposals=proposals,
        )
        items.append(
            PMDecisionQueueItem(
                ticker=ticker,
                profile_name=profile_name,
                item_type=PMDecisionQueueItemType.assumption_change_pack,
                status="pending",
                title=_queue_title(observation.observation_type, rule),
                summary=observation.claim,
                evidence_anchor_ids=observation.evidence_anchor_ids,
                evidence_packet_ids=[str(evidence_packet_id)],
                proposal_pack=proposal_pack,
                qualitative_importance=observation.qualitative_importance,
                agent_confidence=_to_queue_confidence(observation.agent_confidence),
                translator_confidence=translator_confidence,
                metadata=observation_metadata,
            )
        )
    return items
