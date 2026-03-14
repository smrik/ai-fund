import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.stage_00_data.sec_filing_metrics import SecFilingMetrics
from src.stage_02_valuation.templates.ic_memo import (
    EarningsSummary,
    FilingsSummary,
    ICMemo,
    RiskOutput,
    SentimentOutput,
    ValuationRange,
)
import src.stage_04_pipeline.orchestrator as orch_mod


class _StubIndustryAgent:
    def research(self, sector, industry):
        return {"consensus_growth_near": 0.05, "margin_benchmark": 0.2, "consensus_growth_mid": 0.04, "valuation_framework": "DCF"}

    def get_recent_events(self, ticker, sector):
        return {"recent_events": [], "sector_tailwinds": [], "sector_headwinds": [], "macro_relevance": "", "key_catalyst_watch": ""}


class _StubFilingsAgent:
    def analyze(self, ticker):
        return FilingsSummary(revenue_trend="stable", margin_trend="stable", raw_summary="clean")


class _StubEarningsAgent:
    def analyze(self, ticker, filings_context=""):
        return EarningsSummary(guidance_trend="maintained", management_tone="confident", raw_summary="earnings ok")


class _StubQoEAgent:
    def analyze(self, ticker, reported_ebit, filing_text=None):
        return {
            "qoe_score": 4,
            "qoe_flag": "green",
            "deterministic": {"signal_scores": {"accruals": "green"}},
            "llm": {
                "ebit_haircut_pct": 0.0,
                "dcf_ebit_override_pending": False,
                "revenue_recognition_flags": [],
                "auditor_flags": [],
            },
            "pm_summary": "QoE looks acceptable.",
        }


class _StubAccountingRecastAgent:
    def analyze(self, ticker, reported_ebit=None, filing_text=None):
        return {
            "ticker": ticker,
            "source": "sec_edgar_10k",
            "confidence": "high",
            "income_statement_adjustments": [
                {
                    "item": "Restructuring charges",
                    "amount": 125000000.0,
                    "classification": "non_recurring_expense",
                    "proposed_ebit_direction": "+",
                    "rationale": "One-time facility closure costs.",
                    "citation_text": "Restructuring charge disclosed in Note 3.",
                }
            ],
            "balance_sheet_reclassifications": [
                {
                    "line_item": "Operating lease liabilities",
                    "reported_value": 900000000.0,
                    "classification": "financing_liability",
                    "proposed_driver_field": "lease_liabilities",
                    "rationale": "Bridge item.",
                    "citation_text": "Lease table.",
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
            "approval_required": True,
            "pm_review_notes": "PM must manually approve any overrides.",
        }


class _StubValuationAgent:
    def analyze(self, ticker, filings):
        return ValuationRange(bear=80.0, base=100.0, bull=120.0, current_price=90.0, upside_pct_base=100.0 / 90.0 - 1.0)


class _StubSentimentAgent:
    def analyze(self, ticker):
        return SentimentOutput(direction="neutral", score=0.0)


class _StubRiskAgent:
    def analyze(self, ticker, valuation, sentiment):
        return RiskOutput(conviction="medium", position_size_usd=5000.0, position_pct=0.05, suggested_stop_loss_pct=0.15)


class _StubThesisAgent:
    def synthesize(
        self,
        ticker,
        company_name,
        sector,
        filings,
        earnings,
        valuation,
        sentiment,
        risk,
        qoe_context="",
        industry_context="",
        accounting_recast_context="",
    ):
        return ICMemo(
            ticker=ticker,
            company_name=company_name,
            sector=sector,
            filings=filings,
            earnings=earnings,
            valuation=valuation,
            sentiment=sentiment,
            risk=risk,
            action="WATCH",
            conviction="medium",
            one_liner="Stub memo",
            variant_thesis_prompt=accounting_recast_context,
        )


def test_orchestrator_includes_accounting_recast_without_mutating_valuation(monkeypatch):
    monkeypatch.setattr(orch_mod, "IndustryAgent", _StubIndustryAgent)
    monkeypatch.setattr(orch_mod, "FilingsAgent", _StubFilingsAgent)
    monkeypatch.setattr(orch_mod, "EarningsAgent", _StubEarningsAgent)
    monkeypatch.setattr(orch_mod, "QoEAgent", _StubQoEAgent)
    monkeypatch.setattr(orch_mod, "AccountingRecastAgent", _StubAccountingRecastAgent)
    monkeypatch.setattr(orch_mod, "ValuationAgent", _StubValuationAgent)
    monkeypatch.setattr(orch_mod, "SentimentAgent", _StubSentimentAgent)
    monkeypatch.setattr(orch_mod, "RiskAgent", _StubRiskAgent)
    monkeypatch.setattr(orch_mod, "ThesisAgent", _StubThesisAgent)
    monkeypatch.setattr(
        orch_mod.md_client,
        "get_market_data",
        lambda ticker: {
            "name": "IBM",
            "sector": "Technology",
            "industry": "IT Services",
            "current_price": 90.0,
            "market_cap": 100000000000.0,
            "ebitda_ttm": 2500000000.0,
        },
    )
    monkeypatch.setattr(
        orch_mod.md_client,
        "get_historical_financials",
        lambda ticker: {"operating_income": [2000000000.0]},
    )

    memo = orch_mod.PipelineOrchestrator().run("IBM")

    assert memo.valuation.base == 100.0
    assert memo.accounting_recast["approval_required"] is True
    assert memo.accounting_recast["override_candidates"]["lease_liabilities"] == 900000000.0
    assert "Accounting recast" in memo.variant_thesis_prompt


def test_collect_recommendations_passes_filings_metrics(monkeypatch):
    orch = orch_mod.PipelineOrchestrator()
    orch.last_qoe_result = {"llm": {}}
    orch.last_accounting_recast_result = {}
    orch.last_industry_result = {}
    orch.last_filings_metrics = SecFilingMetrics(
        ticker="IBM",
        cik="0000051143",
        as_of_date="2026-03-14",
        source_filing_date="2025-12-31",
        source_form="10-K",
        revenue_cagr_3y=0.12,
        ebit_margin_avg_3y=0.18,
        gross_margin_avg_3y=0.52,
        fcf_yield=None,
        net_debt_to_ebitda=None,
        revenue_series=[],
        ebit_series=[],
        metric_source="sec_xbrl_companyfacts",
    )

    monkeypatch.setattr(
        "src.stage_02_valuation.input_assembler.build_valuation_inputs",
        lambda ticker: MagicMock(drivers="drivers"),
    )
    monkeypatch.setattr(
        "src.stage_02_valuation.batch_runner.value_single_ticker",
        lambda ticker: {"iv_base": 123.0},
    )

    captured = {}

    def _fake_extract_recommendations(**kwargs):
        captured.update(kwargs)
        return "ok"

    monkeypatch.setattr(
        "src.stage_04_pipeline.recommendations.extract_recommendations",
        _fake_extract_recommendations,
    )

    out = orch.collect_recommendations("IBM")

    assert out == "ok"
    assert captured["filings_metrics"] is orch.last_filings_metrics
    assert captured["current_iv_base"] == 123.0
