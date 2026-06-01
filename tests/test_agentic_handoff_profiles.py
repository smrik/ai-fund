import pytest

from src.contracts.evidence_packet import EvidencePacketKind
from src.stage_04_pipeline.agentic_handoff_profiles import (
    GROUNDED_OBSERVATION_RUNNER_KEY,
    get_agentic_handoff_profile,
    list_agentic_handoff_profiles,
)


def test_profile_registry_contains_required_profiles():
    names = {profile.profile_name for profile in list_agentic_handoff_profiles()}

    assert "earnings_update" in names
    assert "company_analysis" in names
    assert "industry_analysis" in names
    assert "comps_analysis" in names
    assert "risk_review" in names
    assert "valuation_review" in names


def test_earnings_profile_declares_allowed_packets_observations_and_proposals():
    profile = get_agentic_handoff_profile("earnings_update")

    assert profile.runner_key == GROUNDED_OBSERVATION_RUNNER_KEY
    assert EvidencePacketKind.earnings_update in profile.evidence_packet_kinds
    assert "guidance_revenue_raised" in profile.allowed_observation_types
    assert "revenue_growth_near" in profile.allowed_assumption_fields
    assert profile.prompt_key == "earnings_update"
    assert profile.translator_rule_group == "earnings_update"


def test_non_earnings_profile_uses_same_contract_shape():
    profile = get_agentic_handoff_profile("company_analysis")

    assert profile.runner_key == GROUNDED_OBSERVATION_RUNNER_KEY
    assert profile.runnable is True
    assert EvidencePacketKind.company_analysis in profile.evidence_packet_kinds
    assert "margin_target_disclosed" in profile.allowed_observation_types
    assert "ebit_margin_target" in profile.allowed_assumption_fields
    assert profile.prompt_key == "company_analysis"
    assert profile.translator_rule_group == "company_analysis"


def test_every_runnable_profile_declares_single_runner_and_contract_shape():
    runnable_profiles = [profile for profile in list_agentic_handoff_profiles() if profile.runnable]

    assert runnable_profiles
    for profile in runnable_profiles:
        assert profile.runner_key == GROUNDED_OBSERVATION_RUNNER_KEY
        assert profile.evidence_packet_kinds
        assert profile.allowed_observation_types
        assert profile.allowed_assumption_fields
        assert profile.prompt_guidance
        assert not hasattr(profile, "agent_class_name")


def test_not_runnable_profiles_are_explicitly_marked():
    comps_profile = get_agentic_handoff_profile("comps_analysis")
    risk_profile = get_agentic_handoff_profile("risk_review")

    assert comps_profile.runnable is True
    assert comps_profile.not_runnable_reason is None
    assert comps_profile.runner_key == GROUNDED_OBSERVATION_RUNNER_KEY

    assert risk_profile.runnable is True
    assert risk_profile.not_runnable_reason is None
    assert risk_profile.runner_key == GROUNDED_OBSERVATION_RUNNER_KEY


def test_unknown_profile_lookup_fails_closed():
    with pytest.raises(KeyError):
        get_agentic_handoff_profile("not_a_profile")
