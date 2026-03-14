from src.stage_02_valuation.templates.ic_memo import RiskImpactOutput
from src.stage_03_judgment.risk_impact_agent import RiskImpactAgent


def test_risk_impact_agent_parses_overlay_json(monkeypatch):
    agent = RiskImpactAgent()
    monkeypatch.setattr(
        agent,
        "run",
        lambda prompt: '''{
          "overlays": [
            {
              "risk_name": "Competitive Displacement",
              "source_type": "sentiment_risk_narrative",
              "source_text": "Frontier models entering enterprise governance.",
              "probability": 0.25,
              "horizon": "24m",
              "revenue_growth_near_bps": -300,
              "revenue_growth_mid_bps": -200,
              "ebit_margin_bps": -150,
              "wacc_bps": 50,
              "exit_multiple_pct": -10.0,
              "rationale": "Pressure on pricing and retention.",
              "confidence": "medium"
            }
          ],
          "raw_summary": "Competitive pressure creates meaningful downside."
        }''',
    )

    out = agent.analyze(
        ticker="IBM",
        company_name="IBM",
        sector="Technology",
        filings_red_flags=["Large AI competitors entering category"],
        management_guidance="Management says demand remains healthy.",
        earnings_key_themes=["AI monetization"],
        sentiment_risk_narratives=["Market fears commoditization"],
        qoe_context="No major QoE flags.",
        accounting_recast_context="No major reclasses.",
        valuation_context="Base IV $100",
    )

    assert isinstance(out, RiskImpactOutput)
    assert len(out.overlays) == 1
    assert out.overlays[0].risk_name == "Competitive Displacement"
    assert out.overlays[0].wacc_bps == 50


def test_risk_impact_agent_fallback_on_invalid_json(monkeypatch):
    agent = RiskImpactAgent()
    monkeypatch.setattr(agent, "run", lambda prompt: "not json")

    out = agent.analyze(
        ticker="IBM",
        company_name="IBM",
        sector="Technology",
        filings_red_flags=[],
        management_guidance="",
        earnings_key_themes=[],
        sentiment_risk_narratives=[],
        qoe_context="",
        accounting_recast_context="",
        valuation_context="Base IV $100",
    )

    assert isinstance(out, RiskImpactOutput)
    assert out.overlays == []
    assert out.raw_summary
