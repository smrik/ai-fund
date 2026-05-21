from __future__ import annotations

from typing import Any

from src.contracts.evidence_packet import EvidencePacketObservation
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
                {"assumption_name": "ebit_margin_target", "proposal_mode": "delta", "proposed_delta": 0.005},
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
    "execution_risk_increased": {
        "rule_type": "advisory_finding",
        "translator_confidence": "medium",
    },
    "pricing_pressure_worsened": {
        "rule_type": "assumption_change_pack",
        "proposals": [
            {"assumption_name": "ebit_margin_start", "proposal_mode": "delta", "proposed_delta": -0.005}
        ],
        "translator_confidence": "medium",
    },
    "pricing_pressure_improved": {
        "rule_type": "assumption_change_pack",
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


def _to_queue_confidence(value: str | None) -> QueueConfidence | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in {"low", "medium", "high"}:
        return QueueConfidence(text)
    return None


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
            built.append(
                AssumptionChangeProposal(
                    assumption_name=assumption_name,
                    proposal_mode=ProposalMode.delta,
                    proposed_delta=float(proposed_delta),
                    rationale=observation.claim,
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


def translate_observations_to_queue_items(
    *,
    ticker: str,
    profile_name: str,
    evidence_packet_id: int,
    observations: list[EvidencePacketObservation],
) -> list[PMDecisionQueueItem]:
    profile = get_agentic_handoff_profile(profile_name)
    rules = TRANSLATOR_RULES.get(profile.translator_rule_group, {})
    items: list[PMDecisionQueueItem] = []
    for observation in observations:
        rule = rules.get(observation.observation_type)
        if rule is None:
            continue
        translator_confidence = _to_queue_confidence(rule.get("translator_confidence"))
        if rule.get("rule_type") == "advisory_finding":
            items.append(
                PMDecisionQueueItem(
                    ticker=ticker,
                    profile_name=profile_name,
                    item_type=PMDecisionQueueItemType.advisory_finding,
                    status="pending",
                    title=observation.observation_type.replace("_", " ").title(),
                    summary=observation.claim,
                    evidence_anchor_ids=observation.evidence_anchor_ids,
                    evidence_packet_ids=[str(evidence_packet_id)],
                    qualitative_importance=observation.qualitative_importance,
                    agent_confidence=_to_queue_confidence(observation.agent_confidence),
                    translator_confidence=translator_confidence,
                    metadata={"observation_id": observation.observation_id},
                )
            )
            continue
        raw_proposals = list(rule.get("proposals") or [])
        proposals = _build_proposals(observation, profile_name, raw_proposals)
        if not proposals:
            continue
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
                title=observation.observation_type.replace("_", " ").title(),
                summary=observation.claim,
                evidence_anchor_ids=observation.evidence_anchor_ids,
                evidence_packet_ids=[str(evidence_packet_id)],
                proposal_pack=proposal_pack,
                qualitative_importance=observation.qualitative_importance,
                agent_confidence=_to_queue_confidence(observation.agent_confidence),
                translator_confidence=translator_confidence,
                metadata={"observation_id": observation.observation_id},
            )
        )
    return items
