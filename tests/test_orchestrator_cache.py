from __future__ import annotations

import sqlite3
from pathlib import Path

import src.stage_04_pipeline.orchestrator as orch_mod
from db.schema import create_tables
from src.stage_00_data.filing_retrieval import FilingContextBundle, FilingChunk
from src.stage_02_valuation.templates.ic_memo import (
    EarningsSummary,
    FilingsSummary,
    ICMemo,
    RiskImpactOutput,
    RiskOutput,
    RiskScenarioOverlay,
    SentimentOutput,
    ValuationRange,
)


COUNTS: dict[str, int] = {}


def _bump(name: str) -> int:
    COUNTS[name] = COUNTS.get(name, 0) + 1
    return COUNTS[name]


class _StubIndustryAgent:
    name = "IndustryAgent"
    model = "stub"
    system_prompt = "industry"
    prompt_version = "v-test"

    def research(self, sector, industry):
        _bump("IndustryAgent.research")
        return {"consensus_growth_near": 0.05, "margin_benchmark": 0.2, "consensus_growth_mid": 0.04, "valuation_framework": "DCF"}

    def get_recent_events(self, ticker, sector):
        _bump("IndustryAgent.events")
        return {"recent_events": [], "sector_tailwinds": [], "sector_headwinds": [], "macro_relevance": "", "key_catalyst_watch": ""}


class _StubFilingsAgent:
    name = "FilingsAgent"
    model = "stub"
    system_prompt = "filings"
    prompt_version = "v-test"

    def analyze(self, ticker, filing_context=None):
        _bump("FilingsAgent")
        return FilingsSummary(
            revenue_trend="stable",
            margin_trend="stable",
            raw_summary="filings context",
            notes_watch_items=["Lease note"],
            recent_quarter_updates=["Q2 update"],
        )


class _StubEarningsAgent:
    name = "EarningsAgent"
    model = "stub"
    system_prompt = "earnings"
    prompt_version = "v-test"

    def analyze(self, ticker, filings_context="", filing_context=None, earnings_8k_context=None):
        _bump("EarningsAgent")
        return EarningsSummary(
            guidance_trend="maintained",
            management_tone="confident",
            raw_summary=f"earnings {filings_context}",
            notes_watch_items=["Restructuring note"],
            quarterly_disclosure_changes=["Added litigation disclosure"],
        )


class _StubQoEAgent:
    name = "QoEAgent"
    model = "stub"
    system_prompt = "qoe"
    prompt_version = "v-test"

    def analyze(self, ticker, reported_ebit, filing_text=None):
        _bump("QoEAgent")
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
            "pm_summary": "qoe ok",
        }


class _StubAccountingRecastAgent:
    name = "AccountingRecastAgent"
    model = "stub"
    system_prompt = "recast"
    prompt_version = "v-test"

    def analyze(self, ticker, reported_ebit=None, filing_text=None):
        _bump("AccountingRecastAgent")
        return {
            "ticker": ticker,
            "source": "sec_edgar_10k",
            "confidence": "high",
            "income_statement_adjustments": [],
            "balance_sheet_reclassifications": [],
            "override_candidates": {},
            "approval_required": True,
            "pm_review_notes": "review",
        }


class _StubValuationAgent:
    name = "ValuationAgent"
    model = "stub"
    system_prompt = "valuation"
    prompt_version = "v-test"

    def analyze(self, ticker, filings):
        _bump("ValuationAgent")
        return ValuationRange(bear=80.0, base=100.0, bull=120.0, current_price=90.0, upside_pct_base=100.0 / 90.0 - 1.0)


class _StubSentimentAgent:
    name = "SentimentAgent"
    model = "stub"
    system_prompt = "sentiment"
    prompt_version = "v-test"

    def analyze(self, ticker):
        _bump("SentimentAgent")
        return SentimentOutput(direction="neutral", score=0.0)


class _StubRiskAgent:
    name = "RiskAgent"
    model = "stub"
    system_prompt = "risk"
    prompt_version = "v-test"

    def analyze(self, ticker, valuation, sentiment):
        _bump("RiskAgent")
        return RiskOutput(conviction="medium", position_size_usd=5000.0, position_pct=0.05, suggested_stop_loss_pct=0.15)


class _StubThesisAgent:
    name = "ThesisAgent"
    model = "stub"
    system_prompt = "thesis"
    prompt_version = "v-test"

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
        risk_impact_context="",
        qoe_context="",
        industry_context="",
        accounting_recast_context="",
        filing_update_context="",
    ):
        _bump("ThesisAgent")
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
            variant_thesis_prompt=f"{accounting_recast_context}\n{risk_impact_context}",
        )


class _StubRiskImpactAgent:
    name = "RiskImpactAgent"
    model = "stub"
    system_prompt = "risk-impact"
    prompt_version = "v-test"

    def analyze(
        self,
        ticker,
        company_name,
        sector,
        filings_red_flags,
        management_guidance,
        earnings_key_themes,
        sentiment_risk_narratives,
        qoe_context,
        accounting_recast_context,
        valuation_context,
    ):
        _bump("RiskImpactAgent")
        return RiskImpactOutput(
            raw_summary="Risk impact summary",
            overlays=[
                RiskScenarioOverlay(
                    risk_name="Competitive Displacement",
                    source_type="sentiment_risk_narrative",
                    source_text="AI entrants",
                    probability=0.25,
                    horizon="24m",
                    revenue_growth_near_bps=-300,
                    revenue_growth_mid_bps=-200,
                    ebit_margin_bps=-150,
                    wacc_bps=50,
                    exit_multiple_pct=-10.0,
                    rationale="Competitive pressure",
                    confidence="medium",
                )
            ],
        )


def _temp_conn_factory(db_path: Path):
    def _factory():
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        create_tables(conn)
        return conn

    return _factory


def _setup_orchestrator(monkeypatch, tmp_path: Path):
    COUNTS.clear()
    monkeypatch.setattr(orch_mod, "IndustryAgent", _StubIndustryAgent)
    monkeypatch.setattr(orch_mod, "FilingsAgent", _StubFilingsAgent)
    monkeypatch.setattr(orch_mod, "EarningsAgent", _StubEarningsAgent)
    monkeypatch.setattr(orch_mod, "QoEAgent", _StubQoEAgent)
    monkeypatch.setattr(orch_mod, "AccountingRecastAgent", _StubAccountingRecastAgent)
    monkeypatch.setattr(orch_mod, "ValuationAgent", _StubValuationAgent)
    monkeypatch.setattr(orch_mod, "SentimentAgent", _StubSentimentAgent)
    monkeypatch.setattr(orch_mod, "RiskAgent", _StubRiskAgent)
    monkeypatch.setattr(orch_mod, "RiskImpactAgent", _StubRiskImpactAgent)
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
    monkeypatch.setattr(
        orch_mod,
        "get_sec_filing_metrics",
        lambda ticker: None,
    )
    monkeypatch.setattr(
        orch_mod,
        "quantify_risk_impact",
        lambda ticker, risk_output, as_of_date=None, apply_overrides=True: {
            "available": True,
            "base_iv": 100.0,
            "risk_adjusted_expected_iv": 92.5,
            "risk_adjusted_delta_pct": -0.075,
            "residual_base_probability": 0.75,
            "overlay_results": [
                {
                    "risk_name": "Competitive Displacement",
                    "probability": 0.25,
                    "stressed_iv": 70.0,
                    "iv_delta_pct": -30.0,
                    "applied_shifts": {
                        "revenue_growth_near_bps": -300,
                        "revenue_growth_mid_bps": -200,
                        "ebit_margin_bps": -150,
                        "wacc_bps": 50,
                        "exit_multiple_pct": -10.0,
                    },
                }
            ],
        },
    )
    monkeypatch.setattr(
        orch_mod.filing_retrieval,
        "get_agent_filing_context",
        lambda ticker, profile_name, include_10k=True, ten_q_limit=2, use_cache=True: FilingContextBundle(
            ticker=ticker,
            profile_name=profile_name,
            corpus_hash=f"{profile_name}-hash",
            sources=[],
            selected_chunks=[
                FilingChunk("10-K", "a1", "2025-12-31", "notes_to_financials", 0, f"{profile_name} context", f"{profile_name}-chunk")
            ],
            rendered_text=f"[10-K | 2025-12-31 | notes_to_financials | chunk 0]\n{profile_name} context",
            retrieval_summary={"used_embeddings": False},
        ),
    )
    monkeypatch.setattr(
        orch_mod.filing_retrieval,
        "render_filing_context",
        lambda bundle, max_chars: bundle.rendered_text,
    )
    monkeypatch.setattr(
        orch_mod.edgar_client,
        "get_8k_texts",
        lambda ticker, limit=3: [{"filing_date": "2026-01-31", "text": "Earnings release"}],
    )

    import src.stage_04_pipeline.agent_cache as cache_mod

    db_path = tmp_path / "agent_cache.db"
    monkeypatch.setattr(cache_mod, "get_connection", _temp_conn_factory(db_path))


def test_orchestrator_reuses_cached_agent_outputs(monkeypatch, tmp_path):
    _setup_orchestrator(monkeypatch, tmp_path)

    orch1 = orch_mod.PipelineOrchestrator()
    orch1.run("IBM", use_cache=True)
    orch2 = orch_mod.PipelineOrchestrator()
    orch2.run("IBM", use_cache=True)

    assert COUNTS["FilingsAgent"] == 1
    assert COUNTS["EarningsAgent"] == 1
    assert COUNTS["ThesisAgent"] == 1
    assert any(item["agent"] == "FilingsAgent" and item["cache_hit"] is True for item in orch2.last_run_trace)


def test_orchestrator_force_refresh_reruns_selected_agent_only(monkeypatch, tmp_path):
    _setup_orchestrator(monkeypatch, tmp_path)

    orch1 = orch_mod.PipelineOrchestrator()
    orch1.run("IBM", use_cache=True)
    orch2 = orch_mod.PipelineOrchestrator()
    orch2.run("IBM", use_cache=True, force_refresh_agents={"FilingsAgent"})

    assert COUNTS["FilingsAgent"] == 2
    assert COUNTS["EarningsAgent"] == 1
    filings_trace = next(item for item in orch2.last_run_trace if item["agent"] == "FilingsAgent")
    earnings_trace = next(item for item in orch2.last_run_trace if item["agent"] == "EarningsAgent")
    assert filings_trace["forced_refresh"] is True
    assert filings_trace["cache_hit"] is False
    assert earnings_trace["cache_hit"] is True


def test_agent_run_history_includes_model_and_prompt_metadata(monkeypatch, tmp_path):
    _setup_orchestrator(monkeypatch, tmp_path)

    orch = orch_mod.PipelineOrchestrator()
    orch.run("IBM", use_cache=True)

    from src.stage_04_pipeline.agent_cache import load_agent_run_history

    history = load_agent_run_history("IBM", limit=20)
    filings_row = next(row for row in history if row["agent_name"] == "FilingsAgent")

    assert filings_row["model"] == "stub"
    assert filings_row["prompt_version"] == "v-test"
    assert filings_row["prompt_hash"]


def test_orchestrator_caches_risk_impact_and_attaches_to_memo(monkeypatch, tmp_path):
    _setup_orchestrator(monkeypatch, tmp_path)

    orch = orch_mod.PipelineOrchestrator()
    memo = orch.run("IBM", use_cache=True)

    assert COUNTS["RiskImpactAgent"] == 1
    assert memo.risk_impact.overlays[0].risk_name == "Competitive Displacement"
    assert orch.last_risk_impact_view["risk_adjusted_expected_iv"] == 92.5
    assert "Competitive Displacement" in memo.variant_thesis_prompt
