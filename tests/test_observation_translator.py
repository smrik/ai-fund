import pytest

from src.contracts.evidence_packet import (
    EvidenceConfidence,
    EvidenceImportance,
    EvidencePacket,
    EvidencePacketFact,
    EvidencePacketKind,
    EvidencePacketObservation,
    EvidencePacketObservationKind,
)
from src.contracts.pm_decision_queue import PMDecisionQueueItemType, ProposalMode, QueueConfidence
import src.stage_04_pipeline.observation_translator as translator


def _observation(
    *,
    observation_type: str,
    anchors: list[str],
    snippet_ids: list[str] | None = None,
    metadata: dict | None = None,
) -> EvidencePacketObservation:
    return EvidencePacketObservation(
        observation_id=f"obs:{observation_type}",
        observation_kind=EvidencePacketObservationKind.qualitative if snippet_ids else EvidencePacketObservationKind.numeric,
        observation_type=observation_type,
        claim=f"claim for {observation_type}",
        evidence_anchor_ids=anchors,
        text_snippet_ids=snippet_ids or [],
        agent_confidence="high",
        qualitative_importance="high",
        metadata=metadata or {},
    )


def test_translator_maps_guidance_upside_to_delta_proposal():
    items = translator.translate_observations_to_queue_items(
        ticker="IBM",
        profile_name="earnings_update",
        evidence_packet_id=1,
        observations=[
            _observation(
                observation_type="guidance_revenue_raised",
                anchors=["fact:guidance:1"],
            )
        ],
    )

    assert len(items) == 1
    item = items[0]
    assert item.item_type == PMDecisionQueueItemType.assumption_change_pack
    assert item.proposal_pack is not None
    proposal = item.proposal_pack.proposals[0]
    assert proposal.assumption_name == "revenue_growth_near"
    assert proposal.proposal_mode == ProposalMode.delta
    assert proposal.proposed_delta == pytest.approx(0.01)
    assert item.translator_confidence is not None


def test_translator_maps_target_observation_to_target_mode():
    items = translator.translate_observations_to_queue_items(
        ticker="IBM",
        profile_name="company_analysis",
        evidence_packet_id=2,
        observations=[
            _observation(
                observation_type="margin_target_disclosed",
                anchors=["fact:margin:1"],
                metadata={"target_value": 0.22},
            )
        ],
    )

    assert len(items) == 1
    proposal = items[0].proposal_pack.proposals[0]
    assert proposal.assumption_name == "ebit_margin_target"
    assert proposal.proposal_mode == ProposalMode.target
    assert proposal.proposed_target_value == pytest.approx(0.22)


def test_translator_creates_two_field_pack_for_broad_demand_softness():
    items = translator.translate_observations_to_queue_items(
        ticker="IBM",
        profile_name="industry_analysis",
        evidence_packet_id=3,
        observations=[
            _observation(
                observation_type="demand_softness_broad",
                anchors=["fact:demand:1"],
            )
        ],
    )

    assert len(items) == 1
    proposals = items[0].proposal_pack.proposals
    fields = {proposal.assumption_name for proposal in proposals}
    # industry_analysis demand_softness rules target near-term and mid-term revenue, not ebit_margin_target.
    assert fields == {"revenue_growth_near", "revenue_growth_mid"}


def test_translator_creates_advisory_for_execution_risk():
    items = translator.translate_observations_to_queue_items(
        ticker="IBM",
        profile_name="risk_review",
        evidence_packet_id=4,
        observations=[
            _observation(
                observation_type="execution_risk_increased",
                anchors=["snippet:risk:1"],
                snippet_ids=["snippet:risk:1"],
            )
        ],
    )

    assert len(items) == 1
    assert items[0].item_type == PMDecisionQueueItemType.advisory_finding
    assert items[0].proposal_pack is None


def test_translator_enforces_assumption_whitelist(monkeypatch):
    monkeypatch.setitem(
        translator.TRANSLATOR_RULES["earnings_update"],
        "test_non_whitelist",
        {
            "rule_type": "assumption_change_pack",
            "proposals": [
                {"assumption_name": "shares_outstanding", "proposal_mode": "delta", "proposed_delta": 1000}
            ],
        },
    )

    items = translator.translate_observations_to_queue_items(
        ticker="IBM",
        profile_name="earnings_update",
        evidence_packet_id=5,
        observations=[
            _observation(
                observation_type="test_non_whitelist",
                anchors=["fact:shares:1"],
            )
        ],
    )
    assert items == []


def test_translator_preserves_confidence_from_enum_values(monkeypatch):
    monkeypatch.setitem(
        translator.TRANSLATOR_RULES["earnings_update"],
        "test_enum_confidence",
        {
            "rule_type": "assumption_change_pack",
            "proposals": [
                {"assumption_name": "revenue_growth_near", "proposal_mode": "delta", "proposed_delta": 0.01}
            ],
            "translator_confidence": EvidenceConfidence.high,
        },
    )

    observation = EvidencePacketObservation(
        observation_id="obs:enum",
        observation_kind=EvidencePacketObservationKind.numeric,
        observation_type="test_enum_confidence",
        claim="claim for enum confidence",
        evidence_anchor_ids=["fact:enum:1"],
        agent_confidence=EvidenceConfidence.high,
        qualitative_importance=EvidenceImportance.high,
    )

    items = translator.translate_observations_to_queue_items(
        ticker="IBM",
        profile_name="earnings_update",
        evidence_packet_id=6,
        observations=[observation],
    )

    assert len(items) == 1
    assert items[0].agent_confidence == QueueConfidence.high
    assert items[0].translator_confidence == QueueConfidence.high
    assert items[0].qualitative_importance.value == "high"


def test_translator_preserves_qualitative_importance_for_advisory_findings():
    observation = EvidencePacketObservation(
        observation_id="obs:advisory",
        observation_kind=EvidencePacketObservationKind.qualitative,
        observation_type="execution_risk_increased",
        claim="execution risk increased",
        evidence_anchor_ids=["snippet:risk:1"],
        text_snippet_ids=["snippet:risk:1"],
        agent_confidence=EvidenceConfidence.medium,
        qualitative_importance=EvidenceImportance.medium,
    )

    items = translator.translate_observations_to_queue_items(
        ticker="IBM",
        profile_name="risk_review",
        evidence_packet_id=7,
        observations=[observation],
    )

    assert len(items) == 1
    assert items[0].item_type == PMDecisionQueueItemType.advisory_finding
    assert items[0].qualitative_importance.value == "medium"
    assert items[0].proposal_pack is None


def test_translator_evidence_weighted_growth_delta_scales_with_facts():
    items = translator.translate_observations_to_queue_items(
        ticker="IBM",
        profile_name="earnings_update",
        evidence_packet_id=8,
        observations=[
            _observation(
                observation_type="demand_strength_broad",
                anchors=["fact:earnings:1"],
                metadata={"facts_snapshot": {"latest_quarter_revenue_yoy_pct": 9.1}},
            )
        ],
    )

    assert len(items) == 1
    proposal = items[0].proposal_pack.proposals[0]
    assert proposal.assumption_name == "revenue_growth_near"
    assert proposal.proposal_mode == ProposalMode.delta
    assert proposal.proposed_delta > 0.01
    assert proposal.proposed_delta <= 0.03
    assert proposal.metadata.get("sizing_mode") == "evidence_weighted"
    assert proposal.metadata.get("base_delta") == pytest.approx(0.01)


def test_translator_evidence_weighted_comps_delta_is_capped():
    items = translator.translate_observations_to_queue_items(
        ticker="IBM",
        profile_name="comps_analysis",
        evidence_packet_id=9,
        observations=[
            _observation(
                observation_type="multiple_premium_supported",
                anchors=["fact:comps:1"],
                metadata={
                    "facts_snapshot": {
                        "tev_ebitda_fwd_target_minus_peer_median": 9.0,
                        "pe_ltm_target_minus_peer_median": 8.5,
                    }
                },
            )
        ],
    )

    assert len(items) == 1
    proposal = items[0].proposal_pack.proposals[0]
    assert proposal.assumption_name == "exit_multiple"
    assert proposal.proposed_delta == pytest.approx(1.5)
    assert proposal.metadata.get("sizing_mode") == "evidence_weighted"


def test_translator_deduplicates_assumption_change_fields_within_profile_run():
    observations = [
        _observation(
            observation_type="multiple_premium_supported",
            anchors=["fact:comps:fwd"],
            metadata={"facts_snapshot": {"tev_ebitda_fwd_target_minus_peer_median": 6.8}},
        ),
        _observation(
            observation_type="multiple_premium_supported",
            anchors=["fact:comps:pe"],
            metadata={"facts_snapshot": {"pe_ltm_target_minus_peer_median": 5.8}},
        ),
    ]

    items = translator.translate_observations_to_queue_items(
        ticker="IBM",
        profile_name="comps_analysis",
        evidence_packet_id=10,
        observations=observations,
    )

    assert len(items) == 1
    assert items[0].proposal_pack is not None
    assert [proposal.assumption_name for proposal in items[0].proposal_pack.proposals] == ["exit_multiple"]


def test_translator_uses_packet_facts_for_live_observation_sizing():
    packet = EvidencePacket(
        ticker="IBM",
        profile_name="comps_analysis",
        packet_kind=EvidencePacketKind.comps_analysis,
        facts=[
            EvidencePacketFact(
                fact_id="fact:comps:spread",
                fact_name="tev_ebitda_fwd_target_minus_peer_median",
                value=6.8,
            )
        ],
    )
    observation = _observation(
        observation_type="multiple_premium_supported",
        anchors=["fact:comps:spread"],
    )

    items = translator.translate_observations_to_queue_items(
        ticker="IBM",
        profile_name="comps_analysis",
        evidence_packet_id=11,
        observations=[observation],
        evidence_packet=packet,
    )

    proposal = items[0].proposal_pack.proposals[0]
    assert proposal.assumption_name == "exit_multiple"
    assert proposal.proposed_delta > 0.5
    assert proposal.metadata["reasons"]
    assert items[0].metadata["packet_provenance"]["packet_kind"] == "comps_analysis"
    assert items[0].metadata["packet_provenance"]["fact_ids"] == ["fact:comps:spread"]
    assert items[0].metadata["packet_provenance"]["packet_hash"]


def test_translator_can_fail_closed_when_public_handoff_omits_packet():
    with pytest.raises(ValueError, match="evidence_packet is required"):
        translator.translate_observations_to_queue_items(
            ticker="IBM",
            profile_name="comps_analysis",
            evidence_packet_id=12,
            observations=[
                _observation(
                    observation_type="multiple_premium_supported",
                    anchors=["fact:comps:spread"],
                )
            ],
            require_evidence_packet=True,
        )
