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
            "Primary sources are the earnings-related filings in the packet (8-K earnings releases first, 10-Q as fallback). Look for quarterly revenue trends, segment performance, year-over-year growth rates, and management commentary on demand and pricing.",
            "Extract specific figures: revenue amounts, growth percentages, margin levels, and any explicit guidance language on forward outlook.",
            "The packet includes the model's current assumptions as model_assumption_* facts (e.g. model_assumption_revenue_growth_near). When reported growth or margins are also in evidence, state both numbers and the gap explicitly — e.g. 'quarterly revenue +18.3% YoY vs model near-term growth assumption of 12.8%' — and say which direction the evidence pushes the assumption. One quarter is a data point, not a trend: flag the gap for PM review rather than extrapolating it.",
            "Use market snapshot facts (price, analyst target, recommendation) only as supporting context, not as primary evidence.",
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
            "Prioritize note disclosures and filing snippets over narrative summaries. Quantify what you find: named dollar exposures (tax disputes, litigation reserves, impairments), margin drivers, and capital commitments.",
            "Tie each observation to the valuation driver it touches: revenue growth, EBIT margin, or an EV bridge item (lease_liabilities, pension_deficit, non_operating_assets).",
            "The packet includes deterministic 3-year revenue/EBIT series (revenue_series_annual, ebit_series_annual), their CAGR/averages, and the model's current assumptions (model_assumption_*). If history contradicts the model's growth or margin trajectory — in level or in direction of travel — quantify the gap and raise it as historical_growth_quality.",
            "Anchor every observation to filing facts or filing snippets already present in the packet.",
        ),
    ),
    "accounting_qoe": AgenticHandoffProfile(
        profile_name="accounting_qoe",
        runner_key=GROUNDED_OBSERVATION_RUNNER_KEY,
        runnable=True,
        not_runnable_reason=None,
        evidence_packet_kinds=(EvidencePacketKind.accounting,),
        allowed_observation_types=(
            "qoe_adjustment_candidate",
            "qoe_no_adjustment_identified",
            "qoe_missing_evidence",
        ),
        allowed_assumption_fields=(
            "revenue_growth_near",
            "revenue_growth_mid",
            "ebit_margin_start",
            "ebit_margin_target",
            "tax_rate_start",
            "tax_rate_target",
        ),
        prompt_key="accounting_qoe",
        translator_rule_group="accounting_finding",
        prompt_guidance=(
            "This is a focused QoE and revenue-recognition review. Use only the packet's note snippets, reported historical anchors, and deterministic QoE signals.",
            "Separate booked/disclosed accounting facts from a proposed valuation treatment. Stock compensation, restructuring, impairment, acquisition costs, accruals, and revenue-recognition issues are distinct findings.",
            "A weak signal may be no_adjustment_identified or missing_evidence; do not manufacture an EBIT normalization from a risk flag.",
            "Return one small typed finding or an explicit no-adjustment/missing-evidence result. Do not inspect or propose changes to the PM queue.",
        ),
    ),
    "accounting_ev_equity_bridge": AgenticHandoffProfile(
        profile_name="accounting_ev_equity_bridge",
        runner_key=GROUNDED_OBSERVATION_RUNNER_KEY,
        runnable=True,
        not_runnable_reason=None,
        evidence_packet_kinds=(EvidencePacketKind.accounting,),
        allowed_observation_types=(
            "ev_equity_bridge_candidate",
            "ev_equity_bridge_no_adjustment_identified",
            "ev_equity_bridge_missing_evidence",
        ),
        allowed_assumption_fields=(
            "net_debt",
            "non_operating_assets",
            "lease_liabilities",
            "minority_interest",
            "preferred_equity",
            "pension_deficit",
            "shares_outstanding",
        ),
        prompt_key="accounting_ev_equity_bridge",
        translator_rule_group="accounting_finding",
        prompt_guidance=(
            "This is a focused EV-to-equity bridge review. Reconcile disclosed cash, debt, leases, pension, minority interest, preferred equity, and share counts to the deterministic bridge fields shown in the packet.",
            "Do not assume an operating lease convention or treat a disclosed balance as an adjustment without stating booked status, valuation treatment, and the peer/EV convention question.",
            "Return one small typed finding or an explicit no-adjustment/missing-evidence result, with exact evidence anchors and a PM question when convention judgment remains.",
        ),
    ),
    "accounting_contingencies_and_taxes": AgenticHandoffProfile(
        profile_name="accounting_contingencies_and_taxes",
        runner_key=GROUNDED_OBSERVATION_RUNNER_KEY,
        runnable=True,
        not_runnable_reason=None,
        evidence_packet_kinds=(EvidencePacketKind.accounting,),
        allowed_observation_types=(
            "contingency_or_tax_candidate",
            "contingency_or_tax_no_adjustment_identified",
            "contingency_or_tax_missing_evidence",
        ),
        allowed_assumption_fields=(
            "tax_rate_start",
            "tax_rate_target",
            "wacc",
            "net_debt",
            "ebit_margin_target",
        ),
        prompt_key="accounting_contingencies_and_taxes",
        translator_rule_group="accounting_finding",
        prompt_guidance=(
            "This is a focused contingencies and taxes review. Extract named litigation, tax disputes, guarantees, commitments, reserves, and probability/timing disclosures from the note evidence.",
            "A contingency can be scenario_only or disclosure_only; do not force an EBIT or bridge adjustment when amount, probability, or timing is unresolved.",
            "Return one small typed finding or an explicit no-adjustment/missing-evidence result. State what would change the view.",
        ),
    ),
    "accounting_segments_and_disclosure": AgenticHandoffProfile(
        profile_name="accounting_segments_and_disclosure",
        runner_key=GROUNDED_OBSERVATION_RUNNER_KEY,
        runnable=True,
        not_runnable_reason=None,
        evidence_packet_kinds=(EvidencePacketKind.accounting,),
        allowed_observation_types=(
            "segment_or_disclosure_candidate",
            "segment_or_disclosure_no_adjustment_identified",
            "segment_or_disclosure_missing_evidence",
        ),
        allowed_assumption_fields=(
            "revenue_growth_near",
            "revenue_growth_mid",
            "ebit_margin_start",
            "ebit_margin_target",
        ),
        prompt_key="accounting_segments_and_disclosure",
        translator_rule_group="accounting_finding",
        prompt_guidance=(
            "This is a focused segment and disclosure-quality review. Use disclosed segment revenue, margins, mix shifts, discontinued/recast presentation, and explicit gaps only.",
            "Missing segment evidence is a diligence result, not permission to infer a mix shift or change a margin assumption.",
            "Return one small typed finding or an explicit no-adjustment/missing-evidence result with exact section anchors.",
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
            "Extract competitive positioning signals: market share language, win/loss commentary, pricing environment, and technology adoption trends from the filing text.",
            "Look for specific statements about demand strength or softness by segment, geography, or customer type.",
            "The packet includes the model's current assumptions as facts (revenue_growth_near, revenue_growth_mid, ebit_margin_target, terminal_growth). Map each signal to the assumption it touches: cyclical demand signals bear on revenue_growth_near/mid; structural competitive shifts (share loss, platform disintermediation, secular pricing pressure) bear on ebit_margin_target or terminal_growth. State the direction.",
            "Only emit observations anchored to packet facts or snippets — no external knowledge.",
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
            "Fact naming: <metric>_target is the company's own trading multiple; <metric> with no suffix is the cleaned peer median; <metric>_target_minus_peer_median is the spread. model_assumption_exit_multiple is the exit multiple the DCF assumes today; own_<metric>_current and own_<metric>_5y_median are the company's own trading-multiple history.",
            "Judge the model's exit multiple against three anchors: the peer median, the company's current multiple, and its 5-year median. A mismatch in either direction is an observation — an exit multiple above the peer median needs structural support (superior growth, margin quality, lower relative leverage), and one implying re-rating or de-rating versus the company's own history needs an explicit reason. Do not default to either premium or discount.",
            "Metric identity is non-negotiable: compare the exit multiple only within the family named by model_assumption_exit_metric (tev_ebitda_* for ev_ebitda, tev_ebit_* for ev_ebit); never against pe_* facts. The precomputed model_exit_multiple_minus_peer_median_* spread already uses this like-for-like comparison.",
            "Observation type must match your claim's direction: multiple_premium_supported argues the exit multiple should be HIGHER than currently assumed; multiple_discount_supported argues it should be LOWER.",
            "Use peers_primary_metric, peer_set_audit_flags, and the relative leverage facts to judge whether the peer median itself is trustworthy (small clean set, removed outliers, leverage mismatch); raise peer_set_drift_detected when it is not.",
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
            "Prioritize risks that are specific and quantifiable: named regulatory actions, cyber incidents with disclosed costs, litigation with dollar exposure, or geopolitical events with named supply chain impact.",
            "The wacc fact is the model's current discount rate. Only systematic, balance-sheet-scale risks (funding stress, structural regulatory change, litigation large relative to net_debt) plausibly bear on wacc; idiosyncratic execution items are position-sizing and scenario-probability questions. Say which framing applies and avoid double counting a risk already carried in WACC or scenario weights.",
            "Raise execution or structural risk as PM-review advisory observations with a concrete PM question. Generic sector risks without specific anchors should be skipped.",
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
            "Lead with the expected-value read: the packet includes current_price, per-scenario upside (scenario_upside_pct_*), and probability-weighted expected_upside_pct. State plainly whether the model says the stock is undervalued or overvalued at the current price, and whether the bear/bull asymmetry supports a position.",
            "Stress-test the model's structure, not just its output: a high tv_pct_of_ev means the answer hinges on terminal assumptions (exit_multiple, terminal_growth); check whether growth, margin, and exit-multiple assumptions are internally consistent with each other and with their source_lineage (a sector default deserves more scrutiny than a company-specific input).",
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
