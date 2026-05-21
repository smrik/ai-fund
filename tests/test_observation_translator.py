import pytest

from src.contracts.evidence_packet import (
    EvidencePacketObservation,
    EvidencePacketObservationKind,
)
from src.contracts.pm_decision_queue import PMDecisionQueueItemType, ProposalMode
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
