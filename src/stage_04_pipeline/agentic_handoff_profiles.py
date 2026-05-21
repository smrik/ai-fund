from __future__ import annotations

from dataclasses import dataclass

from src.contracts.evidence_packet import EvidencePacketKind


AGENT_PROPOSABLE_ASSUMPTION_FIELDS = (
    "revenue_growth_near",
    "revenue_growth_mid",
    "ebit_margin_start",
    "ebit_margin_target",
    "exit_multiple",
    "terminal_growth",
    "ronic_terminal",
    "wacc",
    "lease_liabilities",
    "pension_deficit",
    "non_operating_assets",
)


@dataclass(frozen=True)
class AgenticHandoffProfile:
    profile_name: str
    primary_source: str
    evidence_packet_kinds: tuple[EvidencePacketKind, ...]
    allowed_observation_types: tuple[str, ...]
    allowed_assumption_fields: tuple[str, ...]
    prompt_key: str
    translator_rule_group: str


_PROFILES: dict[str, AgenticHandoffProfile] = {
    "earnings_update": AgenticHandoffProfile(
        profile_name="earnings_update",
        primary_source="EarningsAgent",
        evidence_packet_kinds=(EvidencePacketKind.earnings_update,),
        allowed_observation_types=(
            "guidance_revenue_raised",
            "guidance_revenue_lowered",
            "pricing_pressure_improved",
            "pricing_pressure_worsened",
            "demand_strength_broad",
            "demand_softness_broad",
            "margin_target_disclosed",
            "revenue_growth_guidance_disclosed",
        ),
        allowed_assumption_fields=(
            "revenue_growth_near",
            "ebit_margin_start",
            "ebit_margin_target",
        ),
        prompt_key="earnings_update",
        translator_rule_group="earnings_update",
    ),
    "company_analysis": AgenticHandoffProfile(
        profile_name="company_analysis",
        primary_source="FilingsAgent",
        evidence_packet_kinds=(EvidencePacketKind.company_analysis,),
        allowed_observation_types=(
            "margin_target_disclosed",
            "revenue_growth_guidance_disclosed",
            "execution_risk_increased",
            "pricing_pressure_worsened",
            "pricing_pressure_improved",
        ),
        allowed_assumption_fields=(
            "revenue_growth_near",
            "ebit_margin_start",
            "ebit_margin_target",
            "lease_liabilities",
            "pension_deficit",
            "non_operating_assets",
        ),
        prompt_key="company_analysis",
        translator_rule_group="company_analysis",
    ),
    "industry_analysis": AgenticHandoffProfile(
        profile_name="industry_analysis",
        primary_source="IndustryAgent",
        evidence_packet_kinds=(EvidencePacketKind.industry_analysis,),
        allowed_observation_types=(
            "demand_strength_broad",
            "demand_softness_broad",
            "pricing_pressure_improved",
            "pricing_pressure_worsened",
        ),
        allowed_assumption_fields=(
            "revenue_growth_near",
            "revenue_growth_mid",
            "ebit_margin_target",
            "terminal_growth",
        ),
        prompt_key="industry_analysis",
        translator_rule_group="industry_analysis",
    ),
    "comps_analysis": AgenticHandoffProfile(
        profile_name="comps_analysis",
        primary_source="ValuationAgent",
        evidence_packet_kinds=(EvidencePacketKind.comps_analysis,),
        allowed_observation_types=(
            "multiple_premium_supported",
            "multiple_discount_supported",
            "peer_set_drift_detected",
        ),
        allowed_assumption_fields=("exit_multiple",),
        prompt_key="comps_analysis",
        translator_rule_group="comps_analysis",
    ),
    "risk_review": AgenticHandoffProfile(
        profile_name="risk_review",
        primary_source="RiskAgent",
        evidence_packet_kinds=(EvidencePacketKind.risk_review,),
        allowed_observation_types=("execution_risk_increased",),
        allowed_assumption_fields=("wacc",),
        prompt_key="risk_review",
        translator_rule_group="risk_review",
    ),
    "valuation_review": AgenticHandoffProfile(
        profile_name="valuation_review",
        primary_source="ValuationAgent",
        evidence_packet_kinds=(EvidencePacketKind.valuation_review,),
        allowed_observation_types=(
            "terminal_value_fragility",
            "wacc_method_disagreement",
            "assumption_inconsistency",
        ),
        allowed_assumption_fields=(
            "revenue_growth_near",
            "ebit_margin_target",
            "wacc",
            "terminal_growth",
            "ronic_terminal",
        ),
        prompt_key="valuation_review",
        translator_rule_group="valuation_review",
    ),
}


def get_agentic_handoff_profile(profile_name: str) -> AgenticHandoffProfile:
    key = str(profile_name).strip()
    if key not in _PROFILES:
        raise KeyError(f"unknown agentic handoff profile: {profile_name}")
    return _PROFILES[key]


def list_agentic_handoff_profiles() -> list[AgenticHandoffProfile]:
    return list(_PROFILES.values())
