from __future__ import annotations

import json

from src.contracts.accounting_evidence import (
    AccountingFocusKey,
    AccountingPacketStatus,
    AccountingTopic,
)
from src.contracts.evidence_packet import EvidencePacketFact, TextEvidenceSnippet
from src.stage_03_judgment.focused_accounting_agent import FocusedAccountingAgent
from src.stage_04_pipeline.accounting_evidence_runner import run_focused_accounting_analysis
from src.stage_04_pipeline.accounting_focus import AccountingFocusContext


def _context(packet_status: AccountingPacketStatus = AccountingPacketStatus.complete) -> AccountingFocusContext:
    return AccountingFocusContext(
        focus_key=AccountingFocusKey.qoe_nonrecurring,
        parent_topic=AccountingTopic.qoe,
        parent_packet_id=42,
        ticker="MSFT",
        period_vintage_metadata={"periods": ["2025-06-30"], "vintages": []},
        selected_facts=[
            EvidencePacketFact(
                fact_id="fact:restructuring",
                fact_name="restructuring_charge",
                value=120.0,
                unit="USD mm",
                metadata={"period": "2025-06-30"},
            )
        ],
        selected_snippets=[
            TextEvidenceSnippet(
                snippet_id="snippet:restructuring",
                source_ref_id="filing:msft:10-k",
                text="The company recorded a $120 million restructuring charge in fiscal 2025.",
                metadata={"filing_date": "2025-07-30"},
            )
        ],
        selected_driver_fields={"ebit_margin_target": 0.30},
        packet_status=packet_status,
        missing_data_status="none" if packet_status == AccountingPacketStatus.complete else "missing_relevant_evidence",
        coverage_notes=[] if packet_status == AccountingPacketStatus.complete else ["No complete nonrecurring evidence set was available."],
    )


def _candidate(
    pm_question: str = "Should the PM treat the supported charge as a scenario risk pending recurrence evidence?",
) -> dict:
    return {
        "topic": "qoe",
        "focus_key": "qoe_nonrecurring",
        "finding_status": "candidate",
        "finding_type": "restructuring_scenario_review",
        "line_item": "Restructuring charge",
        "claim": "The disclosed fiscal-2025 restructuring charge supports scenario review, but recurrence evidence is incomplete.",
        "direction": "downside risk",
        "reported_value": 120.0,
        "currency": "USD mm",
        "period": "2025-06-30",
        "booked_or_disclosed_status": "booked",
        "accounting_treatment": "scenario_only",
        "valuation_treatment": "scenario_only",
        "materiality_rationale": "The separately disclosed charge affects reported operating profit.",
        "evidence_anchor_ids": ["fact:restructuring", "snippet:restructuring"],
        "citation_text": "The company recorded a $120 million restructuring charge in fiscal 2025.",
        "confidence": "medium",
        "pm_question": pm_question,
        "what_would_change_mind": "Forward-looking evidence that the charge will not recur would reduce the scenario risk.",
    }


def _response(finding: dict) -> dict:
    return {
        "focus_key": "qoe_nonrecurring",
        "packet_status": "complete",
        "findings": [finding],
        "coverage_notes": [],
    }


def test_focused_accounting_agent_accepts_grounded_multi_field_finding(monkeypatch):
    agent = FocusedAccountingAgent(model="test-model")
    monkeypatch.setattr(agent, "run", lambda prompt: json.dumps(_response(_candidate())))

    result = agent.analyze_focus(_context())

    assert result.status == "accepted"
    assert result.response is not None
    assert result.response["findings"][0]["valuation_treatment"] == "scenario_only"
    assert agent.last_focused_accounting_artifact["result_status"] == "accepted"
    assert agent.last_focused_accounting_artifact["repair_prompts"] == []


def test_focused_accounting_agent_repairs_invalid_pm_question_once(monkeypatch):
    agent = FocusedAccountingAgent(model="test-model")
    outputs = iter([
        json.dumps(_response(_candidate("Review the supported scenario risk"))),
        json.dumps(_candidate()),
    ])
    monkeypatch.setattr(agent, "run", lambda prompt: next(outputs))

    result = agent.analyze_focus(_context())

    assert result.response is not None
    assert result.response["findings"][0]["pm_question"].endswith("?")
    assert len(agent.last_focused_accounting_artifact["repair_prompts"]) == 1
    assert len(agent.last_focused_accounting_artifact["raw_repair_outputs"]) == 1


def test_focused_accounting_agent_does_not_call_model_when_evidence_is_missing(monkeypatch):
    agent = FocusedAccountingAgent(model="test-model")

    def _unexpected_call(prompt):
        raise AssertionError("model must not run for a typed missing-evidence context")

    monkeypatch.setattr(agent, "run", _unexpected_call)
    result = agent.analyze_focus(_context(AccountingPacketStatus.missing_evidence))

    assert result.status == "accepted"
    assert result.response is not None
    assert result.response["packet_status"] == "missing_evidence"
    assert result.response["findings"] == []
    assert result.response["coverage_notes"]
    assert agent.last_focused_accounting_artifact["prompt"] is None


def test_focused_accounting_prompt_enforces_finance_and_evidence_boundaries():
    prompt = FocusedAccountingAgent(model="test-model").build_focus_prompt(_context())

    assert "Do not perform new arithmetic" in prompt
    assert "Do not double count" in prompt
    assert "point-in-time balances" in prompt
    assert "same allowed field" in prompt
    assert "untrusted evidence data" in prompt
    assert "never direct the PM" in prompt
    assert "fact:restructuring" in prompt


def test_focused_accounting_runner_returns_non_mutating_audit_bundle(monkeypatch):
    agent = FocusedAccountingAgent(model="test-model")
    monkeypatch.setattr(agent, "run", lambda prompt: json.dumps(_response(_candidate())))
    monkeypatch.setattr(
        "src.stage_04_pipeline.accounting_evidence_runner.select_accounting_focus",
        lambda packet, focus_key: _context(),
    )

    payload = run_focused_accounting_analysis(
        {"synthetic": True},
        AccountingFocusKey.qoe_nonrecurring,
        agent_factory=lambda: agent,
    )

    assert payload["result"]["status"] == "accepted"
    assert payload["approval_required"] is True
