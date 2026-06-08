from __future__ import annotations

from dataclasses import dataclass

from src.contracts.evidence_packet import EvidencePacketKind


GROUNDED_OBSERVATION_RUNNER_KEY = "grounded_observation"


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
    runner_key: str
    runnable: bool
    not_runnable_reason: str | None
    evidence_packet_kinds: tuple[EvidencePacketKind, ...]
    allowed_observation_types: tuple[str, ...]
    allowed_assumption_fields: tuple[str, ...]
    prompt_key: str
    translator_rule_group: str
    prompt_guidance: tuple[str, ...]


_PROFILES: dict[str, AgenticHandoffProfile] = {
    "earnings_update": AgenticHandoffProfile(
        profile_name="earnings_update",
        runner_key=GROUNDED_OBSERVATION_RUNNER_KEY,
        runnable=True,
        not_runnable_reason=None,
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
        prompt_guidance=(
            "Use recent 8-K earnings context first for guidance, tone, and management emphasis.",
            "Use market snapshot facts only as supporting context, not as standalone evidence for new claims.",
        ),
    ),
    "company_analysis": AgenticHandoffProfile(
        profile_name="company_analysis",
        runner_key=GROUNDED_OBSERVATION_RUNNER_KEY,
        runnable=True,
        not_runnable_reason=None,
        evidence_packet_kinds=(EvidencePacketKind.company_analysis,),
        allowed_observation_types=(
            "margin_target_disclosed",
            "revenue_growth_guidance_disclosed",
            "historical_growth_quality",
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
        prompt_guidance=(
            "Prioritize note disclosures and filing snippets over narrative summaries.",
            "Anchor every observation to filing facts or filing snippets already present in the packet.",
        ),
    ),
    "industry_analysis": AgenticHandoffProfile(
        profile_name="industry_analysis",
        runner_key=GROUNDED_OBSERVATION_RUNNER_KEY,
        runnable=True,
        not_runnable_reason=None,
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
        prompt_guidance=(
            "Treat packet evidence as company-grounded industry context, not a web-search freeform prompt.",
            "Only emit industry observations that are supported by provided packet anchors.",
        ),
    ),
    "comps_analysis": AgenticHandoffProfile(
        profile_name="comps_analysis",
        runner_key=GROUNDED_OBSERVATION_RUNNER_KEY,
        runnable=True,
        not_runnable_reason=None,
        evidence_packet_kinds=(EvidencePacketKind.comps_analysis,),
        allowed_observation_types=(
            "multiple_premium_supported",
            "multiple_discount_supported",
            "peer_set_drift_detected",
        ),
        allowed_assumption_fields=("exit_multiple",),
        prompt_key="comps_analysis",
        translator_rule_group="comps_analysis",
        prompt_guidance=(
            "Use deterministic comps dashboard facts only; do not invent peer multiples.",
            "Treat peer-set drift as an advisory finding unless the packet supports a clear multiple signal.",
        ),
    ),
    "risk_review": AgenticHandoffProfile(
        profile_name="risk_review",
        runner_key=GROUNDED_OBSERVATION_RUNNER_KEY,
        runnable=True,
        not_runnable_reason=None,
        evidence_packet_kinds=(EvidencePacketKind.risk_review,),
        allowed_observation_types=("execution_risk_increased",),
        allowed_assumption_fields=("wacc",),
        prompt_key="risk_review",
        translator_rule_group="risk_review",
        prompt_guidance=(
            "Use deterministic valuation, market, and filing risk anchors only.",
            "Raise execution or structural risk as PM-review advisory observations, not automatic model edits.",
        ),
    ),
    "valuation_review": AgenticHandoffProfile(
        profile_name="valuation_review",
        runner_key=GROUNDED_OBSERVATION_RUNNER_KEY,
        runnable=True,
        not_runnable_reason=None,
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
        prompt_guidance=(
            "Use deterministic valuation facts and scenario outputs already in the packet; do not invent new valuation numbers.",
            "Raise structural valuation concerns as observations for PM review, not model edits.",
        ),
    ),
    "analyst_prep_synthesis": AgenticHandoffProfile(
        profile_name="analyst_prep_synthesis",
        runner_key=GROUNDED_OBSERVATION_RUNNER_KEY,
        runnable=True,
        not_runnable_reason=None,
        evidence_packet_kinds=(EvidencePacketKind.analyst_prep_synthesis,),
        allowed_observation_types=(
            "thesis_bridge_supported",
            "model_driver_bridge_review",
            "diligence_gap_identified",
            "segment_bridge_missing",
            "comps_judgment_review",
        ),
        allowed_assumption_fields=(
            "revenue_growth_near",
            "revenue_growth_mid",
            "ebit_margin_start",
            "ebit_margin_target",
            "wacc",
            "exit_multiple",
            "terminal_growth",
        ),
        prompt_key="analyst_prep_synthesis",
        translator_rule_group="analyst_prep_synthesis",
        prompt_guidance=(
            "Synthesize only from Analyst Prep packet facts, snippets, model-driver cards, comps diagnostics, and missing-data flags.",
            "Do not propose model edits; explain what thesis claim or diligence question the PM should inspect.",
            "If segment rows are missing, state that segment evidence is missing rather than inferring a mix-shift story.",
        ),
    ),
}


def get_agentic_handoff_profile(profile_name: str) -> AgenticHandoffProfile:
    key = str(profile_name).strip()
    if key not in _PROFILES:
        raise KeyError(f"unknown agentic handoff profile: {profile_name}")
    return _PROFILES[key]


def list_agentic_handoff_profiles() -> list[AgenticHandoffProfile]:
    return list(_PROFILES.values())
