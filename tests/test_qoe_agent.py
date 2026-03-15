"""Tests for QoEAgent — covers LLM parsing, fallback, and full output contract."""
import json
import sqlite3
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from db.schema import create_tables
from src.stage_00_data import edgar_client
from src.stage_03_judgment.qoe_agent import QoEAgent
from src.stage_03_judgment import qoe_signals


# ── Schema helpers ─────────────────────────────────────────────────────────────

def _assert_full_schema(out: dict) -> None:
    """Assert the full QoE output contract."""
    assert isinstance(out["ticker"], str)
    assert out["qoe_score"] in range(1, 6)
    assert out["qoe_flag"] in {"green", "amber", "red"}

    det = out["deterministic"]
    assert isinstance(det, dict)
    assert "signal_scores" in det
    for key in {"accruals", "cash_conversion", "dso", "dio", "dpo", "capex_da"}:
        assert key in det["signal_scores"]
        assert det["signal_scores"][key] in {"green", "amber", "red", "unavailable"}

    llm = out["llm"]
    assert isinstance(llm["llm_available"], bool)
    assert isinstance(llm["normalized_ebit"], float)
    assert isinstance(llm["reported_ebit"], float)
    assert isinstance(llm["dcf_ebit_override_pending"], bool)
    assert isinstance(llm["ebit_adjustments"], list)
    assert isinstance(llm["signal_explanations"], dict)
    assert isinstance(llm["revenue_recognition_flags"], list)
    assert isinstance(llm["auditor_flags"], list)
    assert llm["llm_confidence"] in {"high", "medium", "low"}

    assert isinstance(out["pm_summary"], str)


def _stub_deterministic(monkeypatch, agent_module):
    """Replace all data fetchers with minimal stubs so the agent can run offline."""
    import src.stage_03_judgment.qoe_agent as qa

    monkeypatch.setattr(qa.md_client, "get_market_data",
                        lambda ticker: {"sector": "Technology", "ebitda_ttm": 200_000_000.0})
    monkeypatch.setattr(qa.md_client, "get_historical_financials",
                        lambda ticker: {
                            "revenue": [1_000_000_000.0],
                            "net_income": [100_000_000.0],
                            "cffo": [150_000_000.0],
                            "capex": [60_000_000.0],
                            "da": [50_000_000.0],
                        })
    monkeypatch.setattr(qa, "get_ciq_snapshot", lambda ticker: None)
    monkeypatch.setattr(qa, "get_ciq_nwc_history", lambda ticker: [])
    monkeypatch.setattr(
        qa.filing_retrieval,
        "get_agent_filing_context",
        lambda ticker, profile_name, include_10k=True, ten_q_limit=2: SimpleNamespace(rendered_text="Retrieved filing context"),
    )
    monkeypatch.setattr(
        qa.filing_retrieval,
        "render_filing_context",
        lambda bundle, max_chars: bundle.rendered_text,
    )


def _fake_agent_init(self):
    self.client = None
    self.name = "QoEAgent"
    self.system_prompt = ""
    self.tools = []
    self.tool_handlers = {}


# ── EDGAR client tests (unchanged) ────────────────────────────────────────────

def test_get_10k_text_returns_most_recent_filing_and_truncates(monkeypatch, tmp_path):
    calls = {}

    db_path = tmp_path / "alpha_pod.db"
    conn = sqlite3.connect(db_path)
    create_tables(conn)
    conn.close()

    def fake_get_cik(ticker: str) -> str:
        calls["ticker"] = ticker
        return "0000123456"

    def fake_get_recent_filings(cik: str, form_type: str, limit: int = 4) -> list[dict]:
        calls["recent_args"] = (cik, form_type, limit)
        return [{"accession_no": "0000123456-26-000001", "filing_date": "2026-02-20", "primary_doc": "annual.htm"}]

    def fake_get_filing_text(accession_no: str, cik: str, doc_name: str) -> str:
        calls["filing_args"] = (accession_no, cik, doc_name)
        return "ABCDEFGHIJ"

    monkeypatch.setattr(edgar_client, "get_cik", fake_get_cik)
    monkeypatch.setattr(edgar_client, "get_recent_filings", fake_get_recent_filings)
    monkeypatch.setattr(edgar_client, "get_filing_text", fake_get_filing_text)
    monkeypatch.setattr(edgar_client, "DB_PATH", db_path)
    monkeypatch.setattr(edgar_client, "EDGAR_CACHE_RAW_DIR", tmp_path / "raw")
    monkeypatch.setattr(edgar_client, "EDGAR_CACHE_CLEAN_DIR", tmp_path / "clean")
    monkeypatch.setattr(edgar_client, "EDGAR_PARSER_VERSION", "test-v1")

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
    monkeypatch.setattr(edgar_client, "get_cik", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("network unavailable")))
    assert edgar_client.get_10k_text("FAIL") is None


# ── Agent output schema ────────────────────────────────────────────────────────

def test_qoe_agent_returns_full_schema_with_valid_llm_response(monkeypatch):
    monkeypatch.setattr("src.stage_03_judgment.qoe_agent.BaseAgent.__init__", _fake_agent_init)
    _stub_deterministic(monkeypatch, None)

    agent = QoEAgent()

    llm_response = {
        "normalized_ebit": 135.5,
        "reported_ebit": 120.0,
        "ebit_adjustments": [
            {"item": "Restructuring", "amount": 15.5, "direction": "+", "rationale": "One-time FY2025."}
        ],
        "signal_explanations": {
            "accruals": "Management cited stock-based compensation as primary driver.",
            "cash_conversion": None,
            "dso": None,
            "dio": None,
            "dpo": None,
            "capex_da": None,
        },
        "revenue_recognition_flags": [],
        "auditor_flags": [],
        "narrative_credibility": "high",
        "confidence": "high",
        "pm_summary": "Earnings quality is high. One restructuring add-back of $15.5M.",
    }

    monkeypatch.setattr(agent, "run", lambda prompt: json.dumps(llm_response))
    monkeypatch.setattr("src.stage_03_judgment.qoe_agent.edgar_client.get_10k_text",
                        lambda ticker: "Annual report text here.")

    out = agent.analyze("TEST", reported_ebit=120.0)

    _assert_full_schema(out)
    assert out["ticker"] == "TEST"
    assert out["llm"]["normalized_ebit"] == 135.5
    assert out["llm"]["reported_ebit"] == 120.0
    assert out["llm"]["ebit_haircut_pct"] == pytest.approx((135.5 - 120.0) / 120.0 * 100, abs=0.1)
    assert out["llm"]["dcf_ebit_override_pending"] is True  # haircut ~12.9% > 10% threshold
    assert out["llm"]["ebit_adjustments"][0]["direction"] == "+"
    assert out["llm"]["llm_confidence"] == "high"
    assert out["llm"]["llm_available"] is True


def test_qoe_agent_dcf_override_pending_when_haircut_exceeds_10_pct(monkeypatch):
    monkeypatch.setattr("src.stage_03_judgment.qoe_agent.BaseAgent.__init__", _fake_agent_init)
    _stub_deterministic(monkeypatch, None)

    agent = QoEAgent()

    llm_response = {
        "normalized_ebit": 80.0,   # reported=120 → haircut = -33%
        "reported_ebit": 120.0,
        "ebit_adjustments": [],
        "signal_explanations": {k: None for k in ["accruals", "cash_conversion", "dso", "dio", "dpo", "capex_da"]},
        "revenue_recognition_flags": [],
        "auditor_flags": [],
        "narrative_credibility": "medium",
        "confidence": "medium",
        "pm_summary": "Significant non-recurring gains removed.",
    }

    monkeypatch.setattr(agent, "run", lambda prompt: json.dumps(llm_response))
    monkeypatch.setattr("src.stage_03_judgment.qoe_agent.edgar_client.get_10k_text",
                        lambda ticker: "10-K text")

    out = agent.analyze("TEST", reported_ebit=120.0)

    assert out["llm"]["dcf_ebit_override_pending"] is True
    assert out["llm"]["ebit_haircut_pct"] == pytest.approx(-33.3, abs=0.2)


def test_qoe_agent_fallback_when_llm_returns_invalid_json(monkeypatch):
    monkeypatch.setattr("src.stage_03_judgment.qoe_agent.BaseAgent.__init__", _fake_agent_init)
    _stub_deterministic(monkeypatch, None)

    agent = QoEAgent()
    monkeypatch.setattr(agent, "run", lambda prompt: "not-valid-json-at-all")
    monkeypatch.setattr("src.stage_03_judgment.qoe_agent.edgar_client.get_10k_text",
                        lambda ticker: None)

    out = agent.analyze("TEST", reported_ebit=88.0)

    _assert_full_schema(out)
    # Fallback: normalized = reported
    assert out["llm"]["normalized_ebit"] == 88.0
    assert out["llm"]["reported_ebit"] == 88.0
    assert out["llm"]["ebit_adjustments"] == []
    assert out["llm"]["llm_confidence"] == "low"
    assert out["llm"]["dcf_ebit_override_pending"] is False


def test_qoe_agent_fallback_mentions_llm_failure_when_filing_text_exists(monkeypatch):
    monkeypatch.setattr("src.stage_03_judgment.qoe_agent.BaseAgent.__init__", _fake_agent_init)
    _stub_deterministic(monkeypatch, None)

    agent = QoEAgent()
    monkeypatch.setattr(agent, "run", lambda prompt: "not-valid-json-at-all")
    monkeypatch.setattr("src.stage_03_judgment.qoe_agent.edgar_client.get_10k_text",
                        lambda ticker: "Fetched 10-K text is available.")

    out = agent.analyze("TEST", reported_ebit=88.0)

    _assert_full_schema(out)
    assert out["llm"]["llm_available"] is True
    assert "llm review failed or was unavailable" in out["pm_summary"].lower()
    assert "no 10-k text available" not in out["pm_summary"].lower()


def test_qoe_agent_llm_unavailable_when_no_filing_text(monkeypatch):
    monkeypatch.setattr("src.stage_03_judgment.qoe_agent.BaseAgent.__init__", _fake_agent_init)
    _stub_deterministic(monkeypatch, None)

    agent = QoEAgent()
    monkeypatch.setattr(agent, "run", lambda prompt: "bad json")
    monkeypatch.setattr(
        "src.stage_03_judgment.qoe_agent.filing_retrieval.get_agent_filing_context",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("no filing context")),
    )
    monkeypatch.setattr("src.stage_03_judgment.qoe_agent.edgar_client.get_10k_text",
                        lambda ticker: None)

    out = agent.analyze("TEST", reported_ebit=100.0)

    _assert_full_schema(out)
    assert out["llm"]["llm_available"] is False
    assert out["llm"]["llm_confidence"] == "low"
    assert "deterministic signals only" in out["pm_summary"].lower()


def test_qoe_agent_provided_filing_text_sets_llm_available_true(monkeypatch):
    monkeypatch.setattr("src.stage_03_judgment.qoe_agent.BaseAgent.__init__", _fake_agent_init)
    _stub_deterministic(monkeypatch, None)

    agent = QoEAgent()

    llm_response = {
        "normalized_ebit": 100.0, "reported_ebit": 100.0,
        "ebit_adjustments": [],
        "signal_explanations": {k: None for k in ["accruals", "cash_conversion", "dso", "dio", "dpo", "capex_da"]},
        "revenue_recognition_flags": [], "auditor_flags": [],
        "narrative_credibility": "medium", "confidence": "medium",
        "pm_summary": "Earnings quality looks reasonable.",
    }
    monkeypatch.setattr(agent, "run", lambda prompt: json.dumps(llm_response))

    out = agent.analyze("TEST", reported_ebit=100.0, filing_text="Pre-fetched 10-K text here.")

    _assert_full_schema(out)
    assert out["llm"]["llm_available"] is True


def test_qoe_agent_revenue_recognition_flags_passed_through(monkeypatch):
    monkeypatch.setattr("src.stage_03_judgment.qoe_agent.BaseAgent.__init__", _fake_agent_init)
    _stub_deterministic(monkeypatch, None)

    agent = QoEAgent()

    llm_response = {
        "normalized_ebit": 100.0, "reported_ebit": 100.0,
        "ebit_adjustments": [],
        "signal_explanations": {k: None for k in ["accruals", "cash_conversion", "dso", "dio", "dpo", "capex_da"]},
        "revenue_recognition_flags": ["Unbilled AR growing 25% vs revenue +8%", "Channel mix shift to distributor"],
        "auditor_flags": ["Auditor changed in FY2025"],
        "narrative_credibility": "low",
        "confidence": "medium",
        "pm_summary": "Revenue recognition concerns flagged.",
    }
    monkeypatch.setattr(agent, "run", lambda prompt: json.dumps(llm_response))

    out = agent.analyze("TEST", reported_ebit=100.0, filing_text="10-K text")

    assert len(out["llm"]["revenue_recognition_flags"]) == 2
    assert len(out["llm"]["auditor_flags"]) == 1
    assert out["llm"]["narrative_credibility"] == "low"


import pytest
