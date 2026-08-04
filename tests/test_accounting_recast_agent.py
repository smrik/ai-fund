import json
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.stage_03_judgment.accounting_recast_agent import AccountingRecastAgent


def _fake_agent_init(self, *args, **kwargs):
    self.client = None
    self.model = "test-model"
    self.name = "AccountingRecastAgent"
    self.system_prompt = ""
    self.tools = []
    self.tool_handlers = {}


def _assert_schema(out: dict) -> None:
    assert out["ticker"] == "IBM"
    assert out["source"] in {"sec_edgar_10k", "provided_filing_text", "fallback", "sec_edgar_10k_fallback"}
    assert out["confidence"] in {"high", "medium", "low"}
    assert isinstance(out["income_statement_adjustments"], list)
    assert isinstance(out["reclassify"], list)
    assert isinstance(out["driver_proposals"], list)
    assert isinstance(out["model_change_proposals"], list)
    assert isinstance(out["rejected_legacy_fields"], list)
    assert "balance_sheet_reclassifications" not in out
    assert "override_candidates" not in out
    assert out["approval_required"] is True
    assert isinstance(out["pm_review_notes"], str)


def test_accounting_recast_agent_returns_structured_output(monkeypatch):
    monkeypatch.setattr("src.stage_03_judgment.accounting_recast_agent.BaseAgent.__init__", _fake_agent_init)
    monkeypatch.setattr(
        "src.stage_03_judgment.accounting_recast_agent.filing_retrieval.get_agent_filing_context",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("no shared context in unit test")),
    )
    monkeypatch.setattr(
        "src.stage_03_judgment.accounting_recast_agent.edgar_client.get_10k_text",
        lambda ticker, max_chars=40_000: "Annual report notes discuss restructuring charges and lease liabilities.",
    )

    agent = AccountingRecastAgent()
    llm_response = {
        "confidence": "high",
        "income_statement_adjustments": [
            {
                "item": "Restructuring charges",
                "amount": 125000000.0,
                "classification": "non_recurring_expense",
                "proposed_ebit_direction": "+",
                "rationale": "Management described the charge as part of a one-time footprint optimization plan.",
                "citation_text": "Restructuring charges of $125 million were recorded in 2025.",
            }
        ],
        "balance_sheet_reclassifications": [
            {
                "line_item": "Operating lease liabilities",
                "reported_value": 900000000.0,
                "classification": "financing_liability",
                "proposed_driver_field": "lease_liabilities",
                "rationale": "Lease obligations should be treated as financing claims in EV to equity bridge.",
                "citation_text": "Operating lease liabilities totaled $900 million at year end.",
            }
        ],
        "override_candidates": {
            "normalized_ebit": 2125000000.0,
            "non_operating_assets": None,
            "lease_liabilities": 900000000.0,
            "minority_interest": None,
            "preferred_equity": None,
            "pension_deficit": None,
        },
        "model_change_proposals": [
            {
                "proposal": "Model supplier financing as debt-like financing.",
                "valuation_effect": "Add the confirmed balance to the EV-to-equity bridge.",
                "reasoning": "The arrangement economically substitutes for borrowing.",
                "citation_text": "Supplier-finance obligations were included in accounts payable.",
                "implementation_status": "unsupported_driver",
            }
        ],
        "reclassify": [
            {
                "reported_line": "ciq:lease_liabilities",
                "from_component": "unclaimed",
                "to_component": "lease_liabilities",
                "rationale": "Lease obligations are financing claims.",
                "citation_text": "Operating lease liabilities totaled $900 million.",
            }
        ],
        "pm_review_notes": "Approve lease liabilities and EBIT normalization only if the charge is confirmed non-recurring.",
    }
    prompts = []
    monkeypatch.setattr(
        agent,
        "run",
        lambda prompt: prompts.append(prompt) or json.dumps(llm_response),
    )

    out = agent.analyze(
        "IBM",
        reported_ebit=2000000000.0,
        analysis_task="Test whether acquisition costs distort normalized EBIT.",
        current_model_context=(
            "CIQ total debt already includes lease liabilities; the standalone "
            "lease-liability driver is zero."
        ),
    )

    _assert_schema(out)
    assert out["source"] == "sec_edgar_10k"
    assert out["reclassify"][0]["reported_line"] == "ciq:lease_liabilities"
    assert out["model_change_proposals"][0]["implementation_status"] == "unsupported_driver"
    assert out["rejected_legacy_fields"] == [
        "balance_sheet_reclassifications",
        "override_candidates",
    ]
    assert out["pm_review_notes"] == llm_response["pm_review_notes"]
    assert "already includes lease liabilities" in prompts[0]
    assert "acquisition costs distort normalized EBIT" in prompts[0]
    assert "use reclassify" in prompts[0]
    assert "override_candidates" not in prompts[0]
    assert "multiply amounts reported in millions by 1,000,000" in prompts[0]


def test_accounting_recast_agent_falls_back_when_text_missing(monkeypatch):
    monkeypatch.setattr("src.stage_03_judgment.accounting_recast_agent.BaseAgent.__init__", _fake_agent_init)
    monkeypatch.setattr(
        "src.stage_03_judgment.accounting_recast_agent.filing_retrieval.get_agent_filing_context",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("no shared context in unit test")),
    )
    monkeypatch.setattr(
        "src.stage_03_judgment.accounting_recast_agent.edgar_client.get_10k_text",
        lambda ticker, max_chars=40_000: None,
    )

    agent = AccountingRecastAgent()
    out = agent.analyze("IBM", reported_ebit=2000000000.0)

    _assert_schema(out)
    assert out["source"] == "fallback"
    assert out["confidence"] == "low"
    assert out["income_statement_adjustments"] == []
    assert out["reclassify"] == []
    assert out["rejected_legacy_fields"] == []


def test_accounting_recast_agent_falls_back_on_invalid_json(monkeypatch):
    monkeypatch.setattr("src.stage_03_judgment.accounting_recast_agent.BaseAgent.__init__", _fake_agent_init)
    monkeypatch.setattr(
        "src.stage_03_judgment.accounting_recast_agent.filing_retrieval.get_agent_filing_context",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("no shared context in unit test")),
    )
    monkeypatch.setattr(
        "src.stage_03_judgment.accounting_recast_agent.edgar_client.get_10k_text",
        lambda ticker, max_chars=40_000: "10-K text exists",
    )

    agent = AccountingRecastAgent()
    monkeypatch.setattr(agent, "run", lambda prompt: "not-json")

    out = agent.analyze("IBM", reported_ebit=2000000000.0)

    _assert_schema(out)
    assert out["source"] == "sec_edgar_10k_fallback"
    assert out["confidence"] == "low"
