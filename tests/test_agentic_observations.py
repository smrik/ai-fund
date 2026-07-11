from src.contracts.evidence_packet import (
    EvidencePacket,
    EvidencePacketFact,
    EvidencePacketKind,
    EvidenceSourceRef,
    TextEvidenceSnippet,
)
from src.stage_03_judgment.agentic_observations import (
    build_agentic_observation_prompt,
    build_agentic_system_prompt,
    build_formatting_prompt,
    parse_agentic_observations,
)
from src.stage_03_judgment.grounded_observation_agent import GroundedObservationAgent


def _packet(profile_name: str, kind: EvidencePacketKind) -> EvidencePacket:
    return EvidencePacket(
        ticker="ibm",
        profile_name=profile_name,
        packet_kind=kind,
        source_refs=[
            EvidenceSourceRef(
                source_ref_id=f"src:{profile_name}:1",
                source_kind="stub",
                source_label="stub source",
                source_locator=f"stub://{profile_name}",
            )
        ],
        facts=[
            EvidencePacketFact(
                fact_id=f"fact:{profile_name}:1",
                fact_name="stub_fact",
                value=1,
            )
        ],
        snippets=[
            TextEvidenceSnippet(
                snippet_id=f"snippet:{profile_name}:1",
                source_ref_id=f"src:{profile_name}:1",
                text="pricing pressure commentary",
            )
        ],
    )


def test_grounded_runner_returns_shared_anchored_observations_and_drop_invalid(monkeypatch):
    def _stub_run(self, prompt: str) -> str:
        profile = "earnings_update"
        observation_type = "pricing_pressure_worsened"
        if "company_analysis" in prompt:
            profile = "company_analysis"
        elif "industry_analysis" in prompt:
            profile = "industry_analysis"
        elif "valuation_review" in prompt:
            profile = "valuation_review"
            observation_type = "assumption_inconsistency"
        return f"""
        {{
          "observations": [
            {{
              "observation_type": "{observation_type}",
              "observation_kind": "qualitative",
              "claim": "Pricing pressure commentary in the cited snippet turned negative enough to question the margin path.",
              "evidence_anchor_ids": ["fact:{profile}:1"],
              "text_snippet_ids": ["snippet:{profile}:1"],
              "agent_confidence": "high",
              "qualitative_importance": "high",
              "materiality": "high",
              "evidence_rationale": "The cited pricing pressure commentary directly supports a weaker pricing-power read.",
              "thesis_implication": "Lower pricing power weakens the margin expansion thesis.",
              "driver_implication": "Review ebit_margin_start and ebit_margin_target assumptions.",
              "pm_question": "Is this pressure temporary or visible across the full segment base?",
              "what_would_change_mind": "Segment disclosures showing price realization has stabilized would weaken this observation."
            }},
            {{
              "observation_type": "{observation_type}",
              "observation_kind": "qualitative",
              "claim": "Unanchored claim should be dropped.",
              "evidence_anchor_ids": [],
              "text_snippet_ids": []
            }}
          ]
        }}
        """

    monkeypatch.setattr(GroundedObservationAgent, "run", _stub_run)
    monkeypatch.setattr(
        GroundedObservationAgent,
        "run_structured_payload",
        lambda self, user_message, response_format, max_tokens=8192: (None, None),
    )

    earnings_agent = GroundedObservationAgent("earnings_update")
    earnings_obs = earnings_agent.analyze_evidence_packet(
        _packet("earnings_update", EvidencePacketKind.earnings_update),
        "earnings_update",
    )
    filings_obs = GroundedObservationAgent("company_analysis").analyze_evidence_packet(
        _packet("company_analysis", EvidencePacketKind.company_analysis),
        "company_analysis",
    )
    industry_obs = GroundedObservationAgent("industry_analysis").analyze_evidence_packet(
        _packet("industry_analysis", EvidencePacketKind.industry_analysis),
        "industry_analysis",
    )
    valuation_obs = GroundedObservationAgent("valuation_review").analyze_evidence_packet(
        _packet("valuation_review", EvidencePacketKind.valuation_review),
        "valuation_review",
    )

    assert len(earnings_obs) == 1
    assert len(filings_obs) == 1
    assert len(industry_obs) == 1
    assert len(valuation_obs) == 1
    assert earnings_obs[0].evidence_anchor_ids == ["fact:earnings_update:1"]
    assert earnings_obs[0].text_snippet_ids == ["snippet:earnings_update:1"]
    assert earnings_obs[0].materiality == "high"
    assert earnings_obs[0].thesis_implication == "Lower pricing power weakens the margin expansion thesis."
    assert earnings_obs[0].driver_implication == "Review ebit_margin_start and ebit_margin_target assumptions."
    assert earnings_obs[0].pm_question == "Is this pressure temporary or visible across the full segment base?"
    artifact = earnings_agent.last_agentic_observation_artifact
    assert artifact["profile_name"] == "earnings_update"
    assert artifact["accepted_observation_count"] == 1
    assert artifact["accepted_observation_ids"] == ["obs:earnings_update:1"]
    assert artifact["rejected_observation_count"] == 1
    assert artifact["rejection_reasons"][0]["reason"] == "missing_evidence_anchor_ids"
    assert "allowed_observation_types" in artifact["extraction_prompt"]
    assert "Raw Extraction" in artifact["formatting_prompt"]


def test_capitalized_level_fields_are_normalized_not_rejected():
    raw = """
    {"observations": [{
        "observation_type": "pricing_pressure_worsened",
        "observation_kind": "qualitative",
        "claim": "Pricing pressure commentary turned negative enough to question the margin path.",
        "evidence_anchor_ids": ["fact:earnings_update:1"],
        "text_snippet_ids": ["snippet:earnings_update:1"],
        "agent_confidence": "High",
        "qualitative_importance": "Medium",
        "materiality": "High",
        "evidence_rationale": "The cited commentary supports a weaker pricing-power read.",
        "thesis_implication": "Lower pricing power weakens the margin expansion thesis.",
        "driver_implication": "Review ebit_margin_start and ebit_margin_target assumptions.",
        "pm_question": "Is this pressure temporary or visible across the full segment base?",
        "what_would_change_mind": "Segment disclosures showing price realization has stabilized."
    }]}
    """
    rejections: list[dict] = []
    observations = parse_agentic_observations(
        raw=raw,
        packet=_packet("earnings_update", EvidencePacketKind.earnings_update),
        profile_name="earnings_update",
        rejection_reasons=rejections,
    )

    assert rejections == []
    assert len(observations) == 1
    assert observations[0].materiality == "high"
    assert observations[0].agent_confidence == "high"
    assert observations[0].qualitative_importance == "medium"


def test_formatting_parse_failure_triggers_one_corrective_retry(monkeypatch):
    valid = """
    {"observations": [{
        "observation_type": "pricing_pressure_worsened",
        "observation_kind": "qualitative",
        "claim": "Pricing pressure commentary turned negative enough to question the margin path.",
        "evidence_anchor_ids": ["fact:earnings_update:1"],
        "text_snippet_ids": ["snippet:earnings_update:1"],
        "agent_confidence": "high",
        "qualitative_importance": "high",
        "materiality": "high",
        "evidence_rationale": "The cited commentary supports a weaker pricing-power read.",
        "thesis_implication": "Lower pricing power weakens the margin expansion thesis.",
        "driver_implication": "Review ebit_margin_start and ebit_margin_target assumptions.",
        "pm_question": "Is this pressure temporary or visible across the full segment base?",
        "what_would_change_mind": "Segment disclosures showing price realization has stabilized."
    }]}
    """
    calls = {"initial_formatting": 0, "retry": 0}

    def _stub_run(self, prompt: str) -> str:
        if "was not valid JSON" in prompt:
            calls["retry"] += 1
            return valid
        if "Raw Extraction" in prompt:
            calls["initial_formatting"] += 1
            return '{"observations": [{"claim": broken json with a token glitch'
        return "extraction notes citing fact:earnings_update:1"

    monkeypatch.setattr(GroundedObservationAgent, "run", _stub_run)
    monkeypatch.setattr(
        GroundedObservationAgent,
        "run_structured_payload",
        lambda self, user_message, response_format, max_tokens=8192: (None, None),
    )

    agent = GroundedObservationAgent("earnings_update")
    observations = agent.analyze_evidence_packet(
        _packet("earnings_update", EvidencePacketKind.earnings_update),
        "earnings_update",
    )

    assert calls == {"initial_formatting": 1, "retry": 1}
    assert len(observations) == 1
    artifact = agent.last_agentic_observation_artifact
    assert artifact["accepted_observation_count"] == 1
    assert "broken json" in artifact["raw_formatting_output_initial"]
    assert artifact["raw_formatting_output"] == valid


def test_agentic_observation_prompt_includes_profile_constraints():
    prompt = build_agentic_observation_prompt(
        _packet("valuation_review", EvidencePacketKind.valuation_review),
        "valuation_review",
        "GroundedObservationAgent",
    )
    formatting_prompt = build_formatting_prompt(
        _packet("valuation_review", EvidencePacketKind.valuation_review),
        "raw extraction",
        "valuation_review",
        "GroundedObservationAgent",
    )
    system_prompt = build_agentic_system_prompt("valuation_review")

    assert "allowed_observation_types" in prompt
    assert "assumption_inconsistency" in prompt
    assert "Produce observations only" in system_prompt
    assert "never produce deterministic valuation edits" in system_prompt
    assert "Raise structural valuation concerns as observations for PM review" in system_prompt
    assert "materiality" in prompt
    assert "thesis_implication" in prompt
    assert "pm_question" in prompt
    assert "If the packet is too thin for a PM-useful observation" in prompt
    assert "metadata.target_value" in formatting_prompt


def test_formatting_prompt_kind_rule_matches_packet_snippet_availability():
    packet_with_snippets = _packet("company_analysis", EvidencePacketKind.company_analysis)
    packet_without_snippets = packet_with_snippets.model_copy(update={"snippets": []})

    facts_only_prompt = build_formatting_prompt(
        packet_without_snippets,
        "raw extraction",
        "company_analysis",
        "GroundedObservationAgent",
    )
    snippet_prompt = build_formatting_prompt(
        packet_with_snippets,
        "raw extraction",
        "company_analysis",
        "GroundedObservationAgent",
    )

    assert "MUST use observation_kind 'numeric'" in facts_only_prompt
    assert "observation_kind 'qualitative' REQUIRES at least one text_snippet_id" in snippet_prompt


def test_target_disclosure_observations_require_numeric_target_value():
    packet = _packet("company_analysis", EvidencePacketKind.company_analysis)
    raw = """
    {
      "observations": [
        {
          "observation_type": "margin_target_disclosed",
          "observation_kind": "qualitative",
          "claim": "Gross margin improved historically, but no explicit target was disclosed.",
          "evidence_anchor_ids": ["fact:company_analysis:1"],
          "text_snippet_ids": ["snippet:company_analysis:1"],
          "agent_confidence": "high",
          "qualitative_importance": "high",
          "materiality": "high",
          "evidence_rationale": "The cited pricing pressure commentary mentions margin context.",
          "thesis_implication": "Historical margin strength may support the margin thesis.",
          "driver_implication": "Review ebit_margin_target assumptions.",
          "pm_question": "Is there a real forward target in the filing?",
          "what_would_change_mind": "An explicit forward margin target would change this."
        },
        {
          "observation_type": "margin_target_disclosed",
          "observation_kind": "qualitative",
          "claim": "Management disclosed a forward margin target supported by the cited filing snippet.",
          "evidence_anchor_ids": ["fact:company_analysis:1"],
          "text_snippet_ids": ["snippet:company_analysis:1"],
          "agent_confidence": "high",
          "qualitative_importance": "high",
          "materiality": "high",
          "evidence_rationale": "The cited pricing pressure commentary directly supports a margin target read.",
          "thesis_implication": "A disclosed target would anchor the margin expansion thesis.",
          "driver_implication": "Review ebit_margin_target assumptions.",
          "pm_question": "Should the DCF target margin move to the disclosed level?",
          "what_would_change_mind": "A later filing withdrawing the target would weaken this.",
          "metadata": {"target_value": 0.58}
        }
      ]
    }
    """

    observations = parse_agentic_observations(
        raw=raw,
        packet=packet,
        profile_name="company_analysis",
    )

    assert len(observations) == 1
    assert observations[0].metadata["target_value"] == 0.58


def test_target_disclosure_can_infer_target_value_from_cited_fact():
    packet = EvidencePacket(
        ticker="IBM",
        profile_name="earnings_update",
        packet_kind=EvidencePacketKind.earnings_update,
        source_refs=[
            EvidenceSourceRef(
                source_ref_id="src:earnings:1",
                source_kind="stub",
                source_label="stub source",
                source_locator="stub://earnings",
            )
        ],
        facts=[
            EvidencePacketFact(
                fact_id="fact:earnings_update:margin_target",
                fact_name="operating_margin_target",
                value=24.0,
                unit="pct",
            )
        ],
        snippets=[
            TextEvidenceSnippet(
                snippet_id="snippet:earnings_update:margin-target",
                source_ref_id="src:earnings:1",
                text="Management reiterated a forward operating margin target of approximately 24% for the full year.",
            )
        ],
    )
    raw = """
    {
      "observations": [
        {
          "observation_type": "margin_target_disclosed",
          "observation_kind": "qualitative",
          "claim": "Management disclosed a forward operating margin target of approximately 24%.",
          "evidence_anchor_ids": ["fact:earnings_update:margin_target", "snippet:earnings_update:margin-target"],
          "text_snippet_ids": ["snippet:earnings_update:margin-target"],
          "agent_confidence": "high",
          "qualitative_importance": "high",
          "materiality": "high",
          "evidence_rationale": "The cited snippet and fact both state the forward 24% operating margin target.",
          "thesis_implication": "The target anchors the margin expansion thesis.",
          "driver_implication": "ebit_margin_target",
          "pm_question": "Should the DCF target margin move toward 24%?",
          "what_would_change_mind": "A later withdrawal of the margin target would weaken this observation."
        }
      ]
    }
    """

    observations = parse_agentic_observations(
        raw=raw,
        packet=packet,
        profile_name="earnings_update",
    )

    assert len(observations) == 1
    assert observations[0].metadata["target_value"] == 0.24


def test_wacc_driver_implication_is_allowed_to_be_short():
    packet = EvidencePacket(
        ticker="IBM",
        profile_name="valuation_review",
        packet_kind=EvidencePacketKind.valuation_review,
        source_refs=[
            EvidenceSourceRef(
                source_ref_id="src:valuation:1",
                source_kind="stub",
                source_label="stub source",
                source_locator="stub://valuation",
            )
        ],
        facts=[
            EvidencePacketFact(fact_id="fact:valuation_review:base_wacc", fact_name="base_wacc", value=0.084),
            EvidencePacketFact(fact_id="fact:valuation_review:peer_wacc", fact_name="peer_wacc", value=0.074),
        ],
        snippets=[
            TextEvidenceSnippet(
                snippet_id="snippet:valuation_review:wacc-disagreement",
                source_ref_id="src:valuation:1",
                text="The selected WACC is 8.4%, while the peer-implied WACC reference is 7.4%.",
            )
        ],
    )
    raw = """
    {
      "observations": [
        {
          "observation_type": "wacc_method_disagreement",
          "observation_kind": "numeric",
          "claim": "The model uses a company-specific WACC of 8.4% while the peer-implied benchmark WACC is 7.4%.",
          "evidence_anchor_ids": ["fact:valuation_review:base_wacc", "fact:valuation_review:peer_wacc", "snippet:valuation_review:wacc-disagreement"],
          "text_snippet_ids": ["snippet:valuation_review:wacc-disagreement"],
          "agent_confidence": "high",
          "qualitative_importance": "high",
          "materiality": "high",
          "evidence_rationale": "The cited WACC values directly show the method disagreement.",
          "thesis_implication": "A higher WACC could understate intrinsic value.",
          "driver_implication": "wacc",
          "pm_question": "Should WACC be justified against the peer benchmark?",
          "what_would_change_mind": "Company-specific risk evidence justifying 8.4% WACC would weaken this."
        }
      ]
    }
    """

    observations = parse_agentic_observations(
        raw=raw,
        packet=packet,
        profile_name="valuation_review",
    )

    assert len(observations) == 1
    assert observations[0].driver_implication == "wacc"
