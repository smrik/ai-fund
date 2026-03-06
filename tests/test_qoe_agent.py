import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.data import edgar_client
from src.agents.qoe_agent import QoEAgent


def _assert_qoe_schema(payload: dict) -> None:
    assert set(payload.keys()) == {
        "normalized_ebit",
        "reported_ebit",
        "adjustments",
        "confidence",
        "data_source",
    }
    assert isinstance(payload["normalized_ebit"], float)
    assert isinstance(payload["reported_ebit"], float)
    assert isinstance(payload["adjustments"], list)
    assert payload["confidence"] in {"high", "medium", "low"}
    assert isinstance(payload["data_source"], str)

    for adj in payload["adjustments"]:
        assert set(adj.keys()) == {"item", "amount", "direction", "rationale"}
        assert isinstance(adj["item"], str)
        assert isinstance(adj["amount"], float)
        assert adj["direction"] in {"+", "-"}
        assert isinstance(adj["rationale"], str)


def test_get_10k_text_returns_most_recent_filing_and_truncates(monkeypatch):
    calls = {}

    def fake_get_cik(ticker: str) -> str:
        calls["ticker"] = ticker
        return "0000123456"

    def fake_get_recent_filings(cik: str, form_type: str, limit: int = 4) -> list[dict]:
        calls["recent_args"] = (cik, form_type, limit)
        return [
            {
                "accession_no": "0000123456-26-000001",
                "filing_date": "2026-02-20",
                "primary_doc": "annual.htm",
            }
        ]

    def fake_get_filing_text(accession_no: str, cik: str, doc_name: str) -> str:
        calls["filing_args"] = (accession_no, cik, doc_name)
        return "ABCDEFGHIJ"

    monkeypatch.setattr(edgar_client, "get_cik", fake_get_cik)
    monkeypatch.setattr(edgar_client, "get_recent_filings", fake_get_recent_filings)
    monkeypatch.setattr(edgar_client, "get_filing_text", fake_get_filing_text)

    text = edgar_client.get_10k_text("HALO", max_chars=5)

    assert text == "ABCDE"
    assert calls["ticker"] == "HALO"
    assert calls["recent_args"] == ("0000123456", "10-K", 1)
    assert calls["filing_args"] == ("0000123456-26-000001", "0000123456", "annual.htm")


def test_get_10k_text_returns_none_when_no_filings(monkeypatch):
    monkeypatch.setattr(edgar_client, "get_cik", lambda ticker: "0000000001")
    monkeypatch.setattr(edgar_client, "get_recent_filings", lambda cik, form_type, limit=4: [])
    monkeypatch.setattr(edgar_client, "get_filing_text", lambda accession_no, cik, doc_name: "SHOULD_NOT_BE_USED")

    assert edgar_client.get_10k_text("NONE") is None


def test_get_10k_text_returns_none_on_exception(monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("network unavailable")

    monkeypatch.setattr(edgar_client, "get_cik", boom)

    assert edgar_client.get_10k_text("FAIL") is None


def test_qoe_agent_analyze_parses_json_response(monkeypatch):
    def fake_base_init(self):
        self.client = None
        self.name = "BaseAgent"
        self.system_prompt = ""
        self.tools = []
        self.tool_handlers = {}

    monkeypatch.setattr("src.agents.qoe_agent.BaseAgent.__init__", fake_base_init)
    agent = QoEAgent()

    response = {
        "normalized_ebit": 135.5,
        "reported_ebit": 120.0,
        "adjustments": [
            {
                "item": "Restructuring",
                "amount": 15.5,
                "direction": "+",
                "rationale": "One-time restructuring charge in FY2025.",
            }
        ],
        "confidence": "high",
        "data_source": "10-K",
    }

    monkeypatch.setattr(agent, "run", lambda prompt: f"analysis\n{json.dumps(response)}\nthanks")

    parsed = agent.analyze("HALO", reported_ebit=120.0, filing_text="10-K excerpt")

    _assert_qoe_schema(parsed)
    assert parsed["normalized_ebit"] == 135.5
    assert parsed["reported_ebit"] == 120.0
    assert parsed["adjustments"][0]["direction"] == "+"
    assert parsed["confidence"] == "high"


def test_qoe_agent_analyze_fallback_when_response_is_invalid(monkeypatch):
    def fake_base_init(self):
        self.client = None
        self.name = "BaseAgent"
        self.system_prompt = ""
        self.tools = []
        self.tool_handlers = {}

    monkeypatch.setattr("src.agents.qoe_agent.BaseAgent.__init__", fake_base_init)
    monkeypatch.setattr("src.agents.qoe_agent.edgar_client.get_10k_text", lambda ticker: None)

    agent = QoEAgent()
    monkeypatch.setattr(agent, "run", lambda prompt: "not-json")

    parsed = agent.analyze("HALO", reported_ebit=88.0)

    _assert_qoe_schema(parsed)
    assert parsed["normalized_ebit"] == 88.0
    assert parsed["reported_ebit"] == 88.0
    assert parsed["adjustments"] == []
    assert parsed["confidence"] == "low"

