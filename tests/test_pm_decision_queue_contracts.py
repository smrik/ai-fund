import pytest
from pydantic import ValidationError

from src.contracts.evidence_packet import (
    EvidencePacket,
    EvidencePacketFact,
    EvidencePacketObservation,
    EvidencePacketObservationKind,
    EvidencePacketKind,
    EvidenceSourceRef,
    TextEvidenceSnippet,
)
from src.contracts.pm_decision_queue import (
    AssumptionChangePack,
    AssumptionChangeProposal,
    PMDecisionQueueItem,
    PMDecisionQueueItemType,
    ProposalMode,
)


def _sample_packet() -> EvidencePacket:
    return EvidencePacket(
        ticker="ibm",
        profile_name="earnings_update",
        packet_kind=EvidencePacketKind.earnings_update,
        source_refs=[
            EvidenceSourceRef(
                source_ref_id="src:earnings:1",
                source_kind="transcript",
                source_label="Q1 call",
                source_locator="transcript://ibm/q1",
            )
        ],
        facts=[
            EvidencePacketFact(
                fact_id="fact:guidance_rev_midpoint",
                fact_name="guidance_revenue_growth_midpoint",
                value=0.06,
            )
        ],
        snippets=[
            TextEvidenceSnippet(
                snippet_id="snippet:pricing",
                source_ref_id="src:earnings:1",
                text="We are seeing sustained pricing discipline across segments.",
            )
        ],
    )


def test_evidence_packet_contract_keeps_facts_and_observations_separate():
    packet = _sample_packet()
    obs = EvidencePacketObservation(
        observation_id="obs:1",
        observation_kind=EvidencePacketObservationKind.numeric,
        observation_type="revenue_growth_guidance_disclosed",
        claim="Guidance midpoint implies near-term growth of 6%.",
        evidence_anchor_ids=["fact:guidance_rev_midpoint"],
    )

    enriched = packet.model_copy(update={"observations": [obs]})

    assert enriched.ticker == "IBM"
    assert enriched.facts[0].fact_id == "fact:guidance_rev_midpoint"
    assert enriched.observations[0].observation_id == "obs:1"
    assert enriched.observations[0].evidence_anchor_ids == ["fact:guidance_rev_midpoint"]


def test_qualitative_observation_requires_text_snippet_anchor():
    with pytest.raises(ValidationError):
        EvidencePacketObservation(
            observation_id="obs:2",
            observation_kind=EvidencePacketObservationKind.qualitative,
            observation_type="pricing_pressure_worsened",
            claim="Pricing pressure worsened materially.",
            evidence_anchor_ids=["fact:guidance_rev_midpoint"],
            text_snippet_ids=[],
        )


def test_queue_item_requires_at_least_one_evidence_anchor():
    with pytest.raises(ValidationError):
        PMDecisionQueueItem(
            ticker="ibm",
            profile_name="earnings_update",
            item_type=PMDecisionQueueItemType.assumption_change_pack,
            title="Guidance changed",
            status="pending",
            evidence_anchor_ids=[],
            proposal_pack=AssumptionChangePack(
                pack_id="pack:1",
                proposals=[
                    AssumptionChangeProposal(
                        assumption_name="revenue_growth_near",
                        proposal_mode=ProposalMode.delta,
                        proposed_delta=0.01,
                    )
                ],
            ),
        )


def test_assumption_change_proposal_supports_delta_and_target_modes():
    delta = AssumptionChangeProposal(
        assumption_name="ebit_margin_start",
        proposal_mode=ProposalMode.delta,
        proposed_delta=0.005,
    )
    target = AssumptionChangeProposal(
        assumption_name="revenue_growth_near",
        proposal_mode=ProposalMode.target,
        proposed_target_value=0.07,
    )

    assert delta.proposed_delta == pytest.approx(0.005)
    assert delta.proposed_target_value is None
    assert target.proposed_target_value == pytest.approx(0.07)
    assert target.proposed_delta is None


def test_pm_edited_proposal_preserves_original_and_final_approved_values():
    original = AssumptionChangePack(
        pack_id="pack:orig",
        proposals=[
            AssumptionChangeProposal(
                assumption_name="revenue_growth_near",
                proposal_mode=ProposalMode.delta,
                proposed_delta=0.01,
            )
        ],
    )
    edited = AssumptionChangePack(
        pack_id="pack:edited",
        proposals=[
            AssumptionChangeProposal(
                assumption_name="revenue_growth_near",
                proposal_mode=ProposalMode.target,
                proposed_target_value=0.065,
            )
        ],
    )
    approved = AssumptionChangePack(
        pack_id="pack:approved",
        proposals=[
            AssumptionChangeProposal(
                assumption_name="revenue_growth_near",
                proposal_mode=ProposalMode.target,
                proposed_target_value=0.065,
            )
        ],
    )

    item = PMDecisionQueueItem(
        ticker="ibm",
        profile_name="earnings_update",
        item_type=PMDecisionQueueItemType.assumption_change_pack,
        title="Revenue guidance raised",
        evidence_anchor_ids=["fact:guidance_rev_midpoint"],
        proposal_pack=original,
        pm_edited_proposal_pack=edited,
        approved_proposal_pack=approved,
        status="approved",
    )

    assert item.proposal_pack.proposals[0].proposed_delta == pytest.approx(0.01)
    assert item.pm_edited_proposal_pack.proposals[0].proposed_target_value == pytest.approx(0.065)
    assert item.approved_proposal_pack.proposals[0].proposed_target_value == pytest.approx(0.065)
