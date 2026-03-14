"""
PipelineOrchestrator — runs all judgment agents sequentially and returns the final IC memo.
Prints live progress to console. Human checkpoint is at the end.
"""

from __future__ import annotations

from collections.abc import Callable

from rich.console import Console
from rich.panel import Panel

from src.stage_00_data import market_data as md_client
from src.stage_00_data.sec_filing_metrics import get_sec_filing_metrics
from src.stage_02_valuation.templates.ic_memo import (
    EarningsSummary,
    FilingsSummary,
    ICMemo,
    RiskOutput,
    SentimentOutput,
    ValuationRange,
)
from src.stage_03_judgment.accounting_recast_agent import (
    AccountingRecastAgent,
    build_accounting_recast_context,
)
from src.stage_03_judgment.earnings_agent import EarningsAgent
from src.stage_03_judgment.filings_agent import FilingsAgent
from src.stage_03_judgment.industry_agent import IndustryAgent
from src.stage_03_judgment.qoe_agent import QoEAgent
from src.stage_03_judgment.risk_agent import RiskAgent
from src.stage_03_judgment.sentiment_agent import SentimentAgent
from src.stage_03_judgment.thesis_agent import ThesisAgent
from src.stage_03_judgment.valuation_agent import ValuationAgent
from src.stage_04_pipeline.agent_cache import AgentRunCache

console = Console()


def _step(label: str):
    console.print(f"\n[bold cyan]▶ {label}[/bold cyan]")


def _ok(label: str, detail: str = ""):
    console.print(f"  [bold green]✓[/bold green] {label}" + (f"  {detail}" if detail else ""))


def _warn(label: str):
    console.print(f"  [yellow]⚠[/yellow] {label}")


class PipelineOrchestrator:
    def __init__(self):
        self.filings_agent = FilingsAgent()
        self.earnings_agent = EarningsAgent()
        self.qoe_agent = QoEAgent()
        self.accounting_recast_agent = AccountingRecastAgent()
        self.industry_agent = IndustryAgent()
        self.valuation_agent = ValuationAgent()
        self.sentiment_agent = SentimentAgent()
        self.risk_agent = RiskAgent()
        self.thesis_agent = ThesisAgent()
        self.agent_cache = AgentRunCache()

        self.last_qoe_result: dict = {}
        self.last_accounting_recast_result: dict = {}
        self.last_industry_result: dict = {}
        self.last_filings_metrics = None
        self.last_run_trace: list[dict] = []

    def _on_step(self, label: str) -> None:
        _step(label)

    def _on_done(self, label: str, detail: str = "") -> None:
        _ok(label, detail)

    def _on_warn(self, label: str) -> None:
        _warn(label)

    def _record_trace(
        self,
        *,
        agent: str,
        display_label: str,
        status: str,
        cache_hit: bool,
        forced_refresh: bool,
        duration_ms: int | None = None,
        detail: str = "",
        error: str | None = None,
    ) -> None:
        self.last_run_trace.append(
            {
                "agent": agent,
                "display_label": display_label,
                "status": status,
                "cache_hit": cache_hit,
                "forced_refresh": forced_refresh,
                "duration_ms": duration_ms,
                "detail": detail,
                "error": error,
            }
        )

    def _run_cached_step(
        self,
        *,
        ticker: str,
        display_label: str,
        agent_name: str,
        agent: object,
        input_payload: dict,
        runner: Callable[[], object],
        use_cache: bool,
        force_refresh_agents: set[str],
        detail_builder: Callable[[object], str],
    ):
        force_refresh = agent_name in force_refresh_agents
        self._on_step(display_label)
        try:
            result, meta = self.agent_cache.run_cached(
                ticker=ticker,
                agent_name=agent_name,
                agent=agent,
                input_payload=input_payload,
                runner=runner,
                use_cache=use_cache,
                force_refresh=force_refresh,
            )
            detail = detail_builder(result)
            if meta["cache_hit"]:
                detail = f"{detail} | cache" if detail else "cache"
                status = "cache_hit"
            elif meta["forced_refresh"]:
                detail = f"{detail} | refreshed" if detail else "refreshed"
                status = "executed"
            else:
                status = "executed"
            self._on_done(display_label, detail)
            self._record_trace(
                agent=agent_name,
                display_label=display_label,
                status=status,
                cache_hit=meta["cache_hit"],
                forced_refresh=meta["forced_refresh"],
                duration_ms=meta["duration_ms"],
                detail=detail,
            )
            return result
        except Exception as exc:
            self._record_trace(
                agent=agent_name,
                display_label=display_label,
                status="error",
                cache_hit=False,
                forced_refresh=force_refresh,
                detail=str(exc),
                error=str(exc),
            )
            raise

    def run(
        self,
        ticker: str,
        *,
        use_cache: bool = True,
        force_refresh_agents: set[str] | None = None,
    ) -> ICMemo:
        ticker = ticker.upper().strip()
        force_refresh_agents = {item.strip() for item in (force_refresh_agents or set())}
        self.last_run_trace = []

        console.print(Panel(
            f"[bold]AI Research Pod[/bold] — {ticker}\nRunning 9-agent fundamental analysis pipeline",
            style="blue",
        ))

        self._on_step("Fetching market snapshot")
        mkt = {}
        company_name = ticker
        sector = ""
        industry = ""
        try:
            mkt = md_client.get_market_data(ticker)
            company_name = mkt.get("name") or ticker
            sector = mkt.get("sector") or ""
            industry = mkt.get("industry") or ""
            price = mkt.get("current_price")
            mktcap = mkt.get("market_cap")
            self._on_done(
                "Fetching market snapshot",
                f"${price:,.2f}  |  Mkt Cap ${mktcap/1e9:.1f}B" if price and mktcap else "",
            )
        except Exception as exc:
            self._on_warn(f"Market data error: {exc}")

        industry_context = ""
        industry_result = {}
        industry_events = {}
        if sector:
            try:
                bundle = self._run_cached_step(
                    ticker=ticker,
                    display_label="0a/9  IndustryAgent — sector benchmarks & recent events",
                    agent_name="IndustryAgent",
                    agent=self.industry_agent,
                    input_payload={"ticker": ticker, "sector": sector, "industry": industry or sector},
                    runner=lambda: {
                        "industry_result": self.industry_agent.research(sector, industry or sector),
                        "industry_events": self.industry_agent.get_recent_events(ticker, sector),
                    },
                    use_cache=use_cache,
                    force_refresh_agents=force_refresh_agents,
                    detail_builder=lambda bundle: (
                        f"Growth {((bundle['industry_result'].get('consensus_growth_near') or 0) * 100):.1f}%"
                        f"  |  Margin benchmark {((bundle['industry_result'].get('margin_benchmark') or 0) * 100):.1f}%"
                    ),
                )
                industry_result = bundle.get("industry_result") or {}
                industry_events = bundle.get("industry_events") or {}
                self.last_industry_result = industry_result
                events_list = industry_events.get("recent_events") or []
                tailwinds = industry_events.get("sector_tailwinds") or []
                headwinds = industry_events.get("sector_headwinds") or []
                macro_rel = industry_events.get("macro_relevance") or ""
                catalyst = industry_events.get("key_catalyst_watch") or ""
                growth_near = industry_result.get("consensus_growth_near") or 0
                industry_context = (
                    f"Sector: {sector}  |  Industry: {industry or sector}\n"
                    f"Consensus growth (near/mid): {growth_near*100:.1f}% / "
                    f"{(industry_result.get('consensus_growth_mid') or 0)*100:.1f}%  "
                    f"|  Margin benchmark: {(industry_result.get('margin_benchmark') or 0)*100:.1f}%\n"
                    f"Valuation framework: {industry_result.get('valuation_framework', '')}\n"
                )
                if events_list:
                    industry_context += "Recent events:\n" + "\n".join(f"  • {e}" for e in events_list[:6]) + "\n"
                if tailwinds:
                    industry_context += "Tailwinds: " + "; ".join(tailwinds[:3]) + "\n"
                if headwinds:
                    industry_context += "Headwinds: " + "; ".join(headwinds[:3]) + "\n"
                if macro_rel:
                    industry_context += f"Macro relevance: {macro_rel}\n"
                if catalyst:
                    industry_context += f"Key catalyst watch: {catalyst}\n"
            except Exception as exc:
                self._on_warn(f"IndustryAgent error: {exc}")
        else:
            self._on_warn("Sector unknown — skipping IndustryAgent")
            self._record_trace(
                agent="IndustryAgent",
                display_label="0a/9  IndustryAgent — sector benchmarks & recent events",
                status="skipped",
                cache_hit=False,
                forced_refresh=False,
                detail="Sector unknown",
            )

        try:
            filings = self._run_cached_step(
                ticker=ticker,
                display_label="1/9  FilingsAgent — parsing SEC 10-K / 10-Q",
                agent_name="FilingsAgent",
                agent=self.filings_agent,
                input_payload={"ticker": ticker},
                runner=lambda: self.filings_agent.analyze(ticker),
                use_cache=use_cache,
                force_refresh_agents=force_refresh_agents,
                detail_builder=lambda result: f"Revenue trend: {result.revenue_trend}  |  Margins: {result.margin_trend}",
            )
            self.last_filings_metrics = get_sec_filing_metrics(ticker)
            if filings.red_flags:
                for flag in filings.red_flags:
                    self._on_warn(f"  {flag}")
        except Exception as exc:
            self._on_warn(f"FilingsAgent error: {exc}")
            filings = FilingsSummary(raw_summary=f"Error: {exc}")

        try:
            earnings = self._run_cached_step(
                ticker=ticker,
                display_label="2/9  EarningsAgent — analysing earnings calls",
                agent_name="EarningsAgent",
                agent=self.earnings_agent,
                input_payload={"ticker": ticker, "filings_context": filings.raw_summary},
                runner=lambda: self.earnings_agent.analyze(ticker, filings.raw_summary),
                use_cache=use_cache,
                force_refresh_agents=force_refresh_agents,
                detail_builder=lambda result: (
                    f"Guidance: {result.guidance_trend}  |  Tone: {result.management_tone}"
                ),
            )
        except Exception as exc:
            self._on_warn(f"EarningsAgent error: {exc}")
            earnings = EarningsSummary(raw_summary=f"Error: {exc}")

        qoe_context = ""
        qoe_result = {}
        reported_ebit = float(mkt.get("ebitda_ttm") or 0) * 0.85 if mkt else 0.0
        try:
            hist = md_client.get_historical_financials(ticker)
            op_income_series = hist.get("operating_income") or []
            reported_ebit = float(op_income_series[0]) if op_income_series else float(mkt.get("ebitda_ttm") or 0) * 0.85
            qoe_result = self._run_cached_step(
                ticker=ticker,
                display_label="2a/9  QoEAgent — quality-of-earnings signals + EBIT normalisation",
                agent_name="QoEAgent",
                agent=self.qoe_agent,
                input_payload={"ticker": ticker, "reported_ebit": reported_ebit},
                runner=lambda: self.qoe_agent.analyze(ticker=ticker, reported_ebit=reported_ebit),
                use_cache=use_cache,
                force_refresh_agents=force_refresh_agents,
                detail_builder=lambda result: (
                    f"QoE score: {result.get('qoe_score')}/5 ({str(result.get('qoe_flag', '')).upper()})"
                ),
            )
            self.last_qoe_result = qoe_result
            llm_block = qoe_result.get("llm") or {}
            pending = llm_block.get("dcf_ebit_override_pending", False)
            if pending:
                self._on_warn("EBIT haircut >10% — review and manually approve any override in config/valuation_overrides.yaml before acting")
            det = qoe_result.get("deterministic") or {}
            signal_scores = det.get("signal_scores") or {}
            flags = [f"{k}: {v}" for k, v in signal_scores.items() if v in ("amber", "red")]
            rev_flags = llm_block.get("revenue_recognition_flags") or []
            auditor_flags = llm_block.get("auditor_flags") or []
            qoe_context = (
                f"QoE score: {qoe_result.get('qoe_score')}/5 ({qoe_result.get('qoe_flag', '').upper()})\n"
                f"PM summary: {qoe_result.get('pm_summary') or ''}\n"
            )
            if flags:
                qoe_context += "Flagged signals: " + ", ".join(flags) + "\n"
            haircut = llm_block.get("ebit_haircut_pct")
            if haircut is not None:
                qoe_context += f"EBIT normalisation: {haircut:+.1f}% haircut"
                if pending:
                    qoe_context += " (OVERRIDE PENDING PM APPROVAL)"
                qoe_context += "\n"
            if rev_flags:
                qoe_context += "Revenue recognition flags: " + "; ".join(rev_flags) + "\n"
            if auditor_flags:
                qoe_context += "Auditor flags: " + "; ".join(auditor_flags) + "\n"
        except Exception as exc:
            self._on_warn(f"QoEAgent error: {exc}")

        accounting_recast_result = {}
        accounting_recast_context = ""
        try:
            accounting_recast_result = self._run_cached_step(
                ticker=ticker,
                display_label="2b/9  AccountingRecastAgent — proposing EBIT and EV-bridge reclassifications",
                agent_name="AccountingRecastAgent",
                agent=self.accounting_recast_agent,
                input_payload={"ticker": ticker, "reported_ebit": reported_ebit},
                runner=lambda: self.accounting_recast_agent.analyze(ticker=ticker, reported_ebit=reported_ebit),
                use_cache=use_cache,
                force_refresh_agents=force_refresh_agents,
                detail_builder=lambda result: (
                    f"Recast confidence: {result.get('confidence', 'low')}"
                    f"  |  Adj: {len(result.get('income_statement_adjustments') or [])}"
                    f"  |  Reclasses: {len(result.get('balance_sheet_reclassifications') or [])}"
                ),
            )
            self.last_accounting_recast_result = accounting_recast_result
            if accounting_recast_result.get("approval_required"):
                self._on_warn("Accounting recast remains advisory — approve any values manually in config/valuation_overrides.yaml")
            accounting_recast_context = build_accounting_recast_context(accounting_recast_result)
        except Exception as exc:
            self._on_warn(f"AccountingRecastAgent error: {exc}")

        try:
            valuation = self._run_cached_step(
                ticker=ticker,
                display_label="3/9  ValuationAgent — running DCF + comps",
                agent_name="ValuationAgent",
                agent=self.valuation_agent,
                input_payload={"ticker": ticker},
                runner=lambda: self.valuation_agent.analyze(ticker, filings),
                use_cache=use_cache,
                force_refresh_agents=force_refresh_agents,
                detail_builder=lambda result: (
                    f"Bear ${result.bear:.0f}  |  Base ${result.base:.0f}  |  Bull ${result.bull:.0f}"
                ),
            )
        except Exception as exc:
            self._on_warn(f"ValuationAgent error: {exc}")
            p = mkt.get("current_price", 0) if mkt else 0
            valuation = ValuationRange(bear=p * 0.7, base=p, bull=p * 1.3, current_price=p)

        try:
            sentiment = self._run_cached_step(
                ticker=ticker,
                display_label="4/9  SentimentAgent — scoring news & analyst positioning",
                agent_name="SentimentAgent",
                agent=self.sentiment_agent,
                input_payload={"ticker": ticker},
                runner=lambda: self.sentiment_agent.analyze(ticker),
                use_cache=use_cache,
                force_refresh_agents=force_refresh_agents,
                detail_builder=lambda result: (
                    f"Direction: {result.direction}  |  Score: {result.score:+.2f}"
                ),
            )
        except Exception as exc:
            self._on_warn(f"SentimentAgent error: {exc}")
            sentiment = SentimentOutput(raw_summary=f"Error: {exc}")

        try:
            risk = self._run_cached_step(
                ticker=ticker,
                display_label="5/9  RiskAgent — sizing position",
                agent_name="RiskAgent",
                agent=self.risk_agent,
                input_payload={
                    "ticker": ticker,
                    "valuation": valuation.model_dump(mode="python"),
                    "sentiment": sentiment.model_dump(mode="python"),
                },
                runner=lambda: self.risk_agent.analyze(ticker, valuation, sentiment),
                use_cache=use_cache,
                force_refresh_agents=force_refresh_agents,
                detail_builder=lambda result: (
                    f"Conviction: {result.conviction.upper()}  |  Size: ${result.position_size_usd:,.0f} ({result.position_pct*100:.1f}%)"
                ),
            )
        except Exception as exc:
            self._on_warn(f"RiskAgent error: {exc}")
            from config import CONVICTION_SIZING, PORTFOLIO_SIZE_USD

            risk = RiskOutput(
                conviction="low",
                position_size_usd=PORTFOLIO_SIZE_USD * CONVICTION_SIZING["low"],
                position_pct=CONVICTION_SIZING["low"],
                suggested_stop_loss_pct=0.20,
                rationale=f"Error: {exc}",
            )

        try:
            memo = self._run_cached_step(
                ticker=ticker,
                display_label="6/9  ThesisAgent — synthesizing IC memo",
                agent_name="ThesisAgent",
                agent=self.thesis_agent,
                input_payload={
                    "ticker": ticker,
                    "company_name": company_name,
                    "sector": sector,
                    "filings": filings.model_dump(mode="python"),
                    "earnings": earnings.model_dump(mode="python"),
                    "valuation": valuation.model_dump(mode="python"),
                    "sentiment": sentiment.model_dump(mode="python"),
                    "risk": risk.model_dump(mode="python"),
                    "qoe_context": qoe_context,
                    "industry_context": industry_context,
                    "accounting_recast_context": accounting_recast_context,
                },
                runner=lambda: self.thesis_agent.synthesize(
                    ticker=ticker,
                    company_name=company_name,
                    sector=sector,
                    filings=filings,
                    earnings=earnings,
                    valuation=valuation,
                    sentiment=sentiment,
                    risk=risk,
                    qoe_context=qoe_context,
                    industry_context=industry_context,
                    accounting_recast_context=accounting_recast_context,
                ),
                use_cache=use_cache,
                force_refresh_agents=force_refresh_agents,
                detail_builder=lambda result: f"Action: {result.action}  |  {result.one_liner}",
            )
            memo.accounting_recast = accounting_recast_result
        except Exception as exc:
            self._on_warn(f"ThesisAgent error: {exc}")
            memo = ICMemo(
                ticker=ticker,
                company_name=company_name,
                sector=sector,
                filings=filings,
                earnings=earnings,
                valuation=valuation,
                sentiment=sentiment,
                risk=risk,
                accounting_recast=accounting_recast_result,
                action="WATCH",
                conviction="low",
                one_liner=f"Analysis incomplete: {exc}",
                variant_thesis_prompt="Review agent outputs manually.",
            )

        console.print("\n[bold green]Pipeline complete.[/bold green]")
        return memo

    def collect_recommendations(self, ticker: str):
        from src.stage_02_valuation.batch_runner import value_single_ticker
        from src.stage_02_valuation.input_assembler import build_valuation_inputs
        from src.stage_04_pipeline.recommendations import extract_recommendations

        inputs = build_valuation_inputs(ticker.upper().strip())
        drivers = inputs.drivers if inputs else None

        current_iv_base: float | None = None
        try:
            val_row = value_single_ticker(ticker)
            if val_row:
                current_iv_base = val_row.get("iv_base")
        except Exception:
            pass

        return extract_recommendations(
            ticker=ticker,
            qoe_result=self.last_qoe_result,
            accounting_recast_result=self.last_accounting_recast_result,
            industry_result=self.last_industry_result,
            current_drivers=drivers,
            current_iv_base=current_iv_base,
            filings_metrics=self.last_filings_metrics,
        )
