from __future__ import annotations

from src.stage_02_valuation.templates.ic_memo import EarningsSummary, FilingsSummary, RiskOutput, SentimentOutput, ValuationRange
from src.stage_03_judgment.thesis_agent import ThesisAgent


def test_thesis_agent_synthesize_emits_structured_pillars_and_catalysts(monkeypatch):
    agent = ThesisAgent()
    monkeypatch.setattr(
        agent,
        "run",
        lambda prompt: """
        {
          "one_liner": "IBM rerates as mix improves",
          "action": "BUY",
          "conviction": "high",
          "bull_case": "Bull",
          "bear_case": "Bear",
          "base_case": "Base",
          "variant_thesis_prompt": "Can software mix hold?",
          "key_catalysts": ["Consulting margin recovery"],
          "key_risks": ["Execution slippage"],
          "open_questions": ["How durable is demand?"],
          "thesis_pillars": [
            {
              "pillar_id": "pillar-1",
              "title": "Software mix shift",
              "description": "Software mix lifts margins.",
              "falsifier": "Mix stalls",
              "evidence_basis": "Segment disclosures"
            }
          ],
          "structured_catalysts": [
            {
              "catalyst_key": "cat-1",
              "title": "Mainframe cycle",
              "description": "Cycle refresh helps revenue",
              "expected_window": "12m",
              "importance": "high"
            }
          ]
        }
        """,
    )

    memo = agent.synthesize(
        ticker="IBM",
        company_name="IBM",
        sector="Technology",
        filings=FilingsSummary(),
        earnings=EarningsSummary(),
        valuation=ValuationRange(bear=90.0, base=110.0, bull=130.0, current_price=100.0),
        sentiment=SentimentOutput(),
        risk=RiskOutput(),
    )

    assert memo.action == "BUY"
    assert memo.thesis_pillars[0].title == "Software mix shift"
    assert memo.structured_catalysts[0].title == "Mainframe cycle"
    assert memo.key_catalysts == ["Consulting margin recovery"]
