from src.contracts.evidence_packet import (
    EvidencePacket,
    EvidencePacketFact,
    EvidencePacketKind,
    EvidenceSourceRef,
    TextEvidenceSnippet,
)
from src.stage_03_judgment.earnings_agent import EarningsAgent
from src.stage_03_judgment.filings_agent import FilingsAgent
from src.stage_03_judgment.industry_agent import IndustryAgent
from src.stage_03_judgment.valuation_agent import ValuationAgent


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


def test_agents_return_shared_anchored_observations_and_drop_invalid(monkeypatch):
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
              "claim": "Pricing commentary turned negative.",
              "evidence_anchor_ids": ["fact:{profile}:1"],
              "text_snippet_ids": ["snippet:{profile}:1"],
              "agent_confidence": "high",
              "qualitative_importance": "high"
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

    monkeypatch.setattr(EarningsAgent, "run", _stub_run)
    monkeypatch.setattr(FilingsAgent, "run", _stub_run)
    monkeypatch.setattr(IndustryAgent, "run", _stub_run)
    monkeypatch.setattr(ValuationAgent, "run", _stub_run)

    earnings_obs = EarningsAgent().analyze_evidence_packet(
        _packet("earnings_update", EvidencePacketKind.earnings_update),
        "earnings_update",
    )
    filings_obs = FilingsAgent().analyze_evidence_packet(
        _packet("company_analysis", EvidencePacketKind.company_analysis),
        "company_analysis",
    )
    industry_obs = IndustryAgent().analyze_evidence_packet(
        _packet("industry_analysis", EvidencePacketKind.industry_analysis),
        "industry_analysis",
    )
    valuation_obs = ValuationAgent().analyze_evidence_packet(
        _packet("valuation_review", EvidencePacketKind.valuation_review),
        "valuation_review",
    )

    assert len(earnings_obs) == 1
    assert len(filings_obs) == 1
    assert len(industry_obs) == 1
    assert len(valuation_obs) == 1
    assert earnings_obs[0].evidence_anchor_ids == ["fact:earnings_update:1"]
    assert earnings_obs[0].text_snippet_ids == ["snippet:earnings_update:1"]
