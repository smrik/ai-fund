import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.stage_03_judgment.earnings_agent import EarningsAgent
from src.stage_03_judgment.filings_agent import FilingsAgent


def _fake_agent_init(self, model=None):
    self.client = None
    self.name = self.__class__.__name__
    self.model = model or "stub"
    self.system_prompt = ""
    self.tools = []
    self.tool_handlers = {}
    self.prompt_version = "v-test"


def test_filings_agent_uses_provided_filing_context(monkeypatch):
    monkeypatch.setattr("src.stage_03_judgment.filings_agent.BaseAgent.__init__", _fake_agent_init)
    agent = FilingsAgent()

    captured = {}

    def _run(prompt: str):
        captured["prompt"] = prompt
        return json.dumps(
            {
                "revenue_cagr_3y": 0.1,
                "gross_margin_avg": 0.55,
                "ebit_margin_avg": 0.2,
                "fcf_yield": None,
                "net_debt_to_ebitda": None,
                "revenue_trend": "stable",
                "margin_trend": "expanding",
                "red_flags": [],
                "notes_watch_items": ["Lease liabilities up"],
                "recent_quarter_updates": ["Q2 gross margin down"],
                "management_guidance": "Guidance maintained",
                "raw_summary": "summary",
            }
        )

    monkeypatch.setattr(agent, "run", _run)
    out = agent.analyze("IBM", filing_context="[10-K | 2025-12-31 | notes_to_financials | chunk 0]\nLease note")

    assert out.notes_watch_items == ["Lease liabilities up"]
    assert out.recent_quarter_updates == ["Q2 gross margin down"]
    assert "Lease note" in captured["prompt"]
    assert "latest 2 quarterlies" in captured["prompt"].lower()


def test_earnings_agent_uses_note_first_filing_context_and_separate_8k_context(monkeypatch):
    monkeypatch.setattr("src.stage_03_judgment.earnings_agent.BaseAgent.__init__", _fake_agent_init)
    agent = EarningsAgent()

    captured = {}

    def _run(prompt: str):
        captured["prompt"] = prompt
        return json.dumps(
            {
                "eps_beat_rate": 0.75,
                "guidance_trend": "maintained",
                "management_tone": "cautious",
                "key_themes": ["AI demand", "Cost discipline"],
                "notes_watch_items": ["Restructuring charge noted in 10-Q"],
                "quarterly_disclosure_changes": ["Added new litigation disclosure"],
                "tone_shift": "stable",
                "raw_summary": "summary",
            }
        )

    monkeypatch.setattr(agent, "run", _run)
    out = agent.analyze(
        "IBM",
        filings_context="legacy summary",
        filing_context="[10-Q | 2026-06-30 | notes_to_financials_q | chunk 1]\nRestructuring note",
        earnings_8k_context="[8-K | 2026-07-20 | earnings_release]\nRaised backlog commentary",
    )

    assert out.notes_watch_items == ["Restructuring charge noted in 10-Q"]
    assert out.quarterly_disclosure_changes == ["Added new litigation disclosure"]
    assert "Accounting / filing context" in captured["prompt"]
    assert "Recent management communication" in captured["prompt"]
    assert "Restructuring note" in captured["prompt"]
    assert "Raised backlog commentary" in captured["prompt"]
