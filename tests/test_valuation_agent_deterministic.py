import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.stage_02_valuation.templates.ic_memo import FilingsSummary
from src.stage_03_judgment.valuation_agent import ValuationAgent


def _fake_base_init(self):
    self.client = None
    self.name = "BaseAgent"
    self.system_prompt = ""
    self.tools = []
    self.tool_handlers = {}


def test_valuation_agent_uses_deterministic_batch_runner(monkeypatch):
    monkeypatch.setattr("src.stage_03_judgment.valuation_agent.BaseAgent.__init__", _fake_base_init)

    def fail_if_called(*args, **kwargs):
        raise AssertionError("LLM run should not be called for valuation numbers")

    monkeypatch.setattr("src.stage_03_judgment.valuation_agent.BaseAgent.run", fail_if_called)

    monkeypatch.setattr(
        "src.stage_03_judgment.valuation_agent.value_single_ticker",
        lambda ticker: {
            "iv_bear": 80.0,
            "iv_base": 100.0,
            "iv_bull": 130.0,
            "price": 90.0,
            "upside_base_pct": 11.1,
        },
    )

    agent = ValuationAgent()
    result = agent.analyze("TEST", FilingsSummary())

    assert result.bear == 80.0
    assert result.base == 100.0
    assert result.bull == 130.0
    assert result.current_price == 90.0
    assert abs((result.upside_pct_base or 0) - 0.111) < 1e-9


def test_valuation_agent_fallback_when_deterministic_result_missing(monkeypatch):
    monkeypatch.setattr("src.stage_03_judgment.valuation_agent.BaseAgent.__init__", _fake_base_init)
    monkeypatch.setattr("src.stage_03_judgment.valuation_agent.value_single_ticker", lambda ticker: None)
    monkeypatch.setattr(
        "src.stage_03_judgment.valuation_agent.md_client.get_market_data",
        lambda ticker: {"current_price": 50.0},
    )

    agent = ValuationAgent()
    result = agent.analyze("MISS", FilingsSummary())

    assert result.current_price == 50.0
    assert result.bear == 35.0
    assert result.base == 50.0
    assert result.bull == 65.0
    assert (result.upside_pct_base or 0) == 0.0
