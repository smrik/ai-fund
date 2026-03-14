"""
PipelineOrchestrator — runs all judgment agents sequentially and returns the final IC memo.
Prints live progress to console. Human checkpoint is at the end.

Agent order:
  0   Market snapshot
  0a  IndustryAgent — sector benchmarks + recent events (cached weekly)
  1   FilingsAgent  — SEC 10-K / 10-Q
  2   EarningsAgent — earnings calls + EPS history
  2a  QoEAgent      — quality-of-earnings signals + LLM EBIT normalisation
  2b  AccountingRecastAgent — advisory operating/non-operating recast proposals
  3   ValuationAgent — deterministic DCF (reads approved overrides)
  4   SentimentAgent — news + analyst positioning
  5   RiskAgent      — position sizing
  6   ThesisAgent    — IC memo synthesis
"""

from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn

from src.stage_03_judgment.filings_agent import FilingsAgent
from src.stage_03_judgment.earnings_agent import EarningsAgent
from src.stage_03_judgment.valuation_agent import ValuationAgent
from src.stage_03_judgment.sentiment_agent import SentimentAgent
from src.stage_03_judgment.risk_agent import RiskAgent
from src.stage_03_judgment.thesis_agent import ThesisAgent
from src.stage_03_judgment.qoe_agent import QoEAgent
from src.stage_03_judgment.industry_agent import IndustryAgent
from src.stage_03_judgment.accounting_recast_agent import (
    AccountingRecastAgent,
    build_accounting_recast_context,
)
from src.stage_00_data import market_data as md_client
from src.stage_00_data.sec_filing_metrics import get_sec_filing_metrics
from src.stage_02_valuation.templates.ic_memo import ICMemo

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
        # Agent output cache — populated by run(), used by collect_recommendations()
        self.last_qoe_result: dict = {}
        self.last_accounting_recast_result: dict = {}
        self.last_industry_result: dict = {}
        self.last_filings_metrics = None

    def run(self, ticker: str) -> ICMemo:
        ticker = ticker.upper().strip()
        console.print(Panel(
            f"[bold]AI Research Pod[/bold] — {ticker}\nRunning 9-agent fundamental analysis pipeline",
            style="blue",
        ))

        # --- Step 0: Market snapshot ---
        _step("Fetching market snapshot")
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
            _ok(
                f"{company_name} ({sector})",
                f"${price:,.2f}  |  Mkt Cap ${mktcap/1e9:.1f}B" if price and mktcap else "",
            )
        except Exception as e:
            _warn(f"Market data error: {e}")

        # --- Step 0a: Industry benchmarks + recent events ---
        _step("0a/9  IndustryAgent — sector benchmarks & recent events")
        industry_context = ""
        industry_result = {}
        industry_events = {}
        if sector:
            try:
                industry_result = self.industry_agent.research(sector, industry or sector)
                self.last_industry_result = industry_result
                industry_events = self.industry_agent.get_recent_events(ticker, sector)
                growth_near = industry_result.get("consensus_growth_near", 0) or 0
                margin_bm = industry_result.get("margin_benchmark", 0) or 0
                _ok(
                    f"Sector growth (near): {growth_near*100:.1f}%  |  Margin benchmark: {margin_bm*100:.1f}%",
                    f"Events: {len(industry_events.get('recent_events', []))}  "
                    f"Tail/Head: {len(industry_events.get('sector_tailwinds', []))}/{len(industry_events.get('sector_headwinds', []))}",
                )
                # Build compact context string for ThesisAgent
                events_list = industry_events.get("recent_events") or []
                tailwinds = industry_events.get("sector_tailwinds") or []
                headwinds = industry_events.get("sector_headwinds") or []
                macro_rel = industry_events.get("macro_relevance") or ""
                catalyst = industry_events.get("key_catalyst_watch") or ""
                industry_context = (
                    f"Sector: {sector}  |  Industry: {industry or sector}\n"
                    f"Consensus growth (near/mid): {growth_near*100:.1f}% / "
                    f"{(industry_result.get('consensus_growth_mid') or 0)*100:.1f}%  "
                    f"|  Margin benchmark: {margin_bm*100:.1f}%\n"
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
            except Exception as e:
                _warn(f"IndustryAgent error: {e}")
        else:
            _warn("Sector unknown — skipping IndustryAgent")

        # --- Step 1: Filings ---
        _step("1/9  FilingsAgent — parsing SEC 10-K / 10-Q")
        try:
            filings = self.filings_agent.analyze(ticker)
            self.last_filings_metrics = get_sec_filing_metrics(ticker)
            _ok(
                f"Revenue trend: {filings.revenue_trend}  |  Margins: {filings.margin_trend}",
                f"Red flags: {len(filings.red_flags)}",
            )
            if filings.red_flags:
                for flag in filings.red_flags:
                    _warn(f"  {flag}")
        except Exception as e:
            _warn(f"FilingsAgent error: {e}")
            from src.stage_02_valuation.templates.ic_memo import FilingsSummary
            filings = FilingsSummary(raw_summary=f"Error: {e}")

        # --- Step 2: Earnings ---
        _step("2/9  EarningsAgent — analysing earnings calls")
        try:
            earnings = self.earnings_agent.analyze(ticker, filings.raw_summary)
            _ok(
                f"Guidance: {earnings.guidance_trend}  |  Tone: {earnings.management_tone}",
                f"Beat rate: {(earnings.eps_beat_rate or 0)*100:.0f}%",
            )
        except Exception as e:
            _warn(f"EarningsAgent error: {e}")
            from src.stage_02_valuation.templates.ic_memo import EarningsSummary
            earnings = EarningsSummary(raw_summary=f"Error: {e}")

        # --- Step 2a: QoE ---
        _step("2a/9  QoEAgent — quality-of-earnings signals + EBIT normalisation")
        qoe_context = ""
        qoe_result = {}
        reported_ebit = float(mkt.get("ebitda_ttm") or 0) * 0.85 if mkt else 0.0
        try:
            # Derive reported_ebit from historical financials (most recent operating income)
            hist = md_client.get_historical_financials(ticker)
            op_income_series = hist.get("operating_income") or []
            reported_ebit = float(op_income_series[0]) if op_income_series else float(mkt.get("ebitda_ttm") or 0) * 0.85

            qoe_result = self.qoe_agent.analyze(ticker=ticker, reported_ebit=reported_ebit)
            self.last_qoe_result = qoe_result
            qoe_score = qoe_result.get("qoe_score")
            qoe_flag = qoe_result.get("qoe_flag", "").upper()
            pm_summary = qoe_result.get("pm_summary") or ""
            llm_block = qoe_result.get("llm") or {}
            haircut = llm_block.get("ebit_haircut_pct")
            pending = llm_block.get("dcf_ebit_override_pending", False)

            detail = f"Haircut: {haircut:+.1f}%" if haircut is not None else ""
            if pending:
                detail += "  ⚠ override pending"
            _ok(f"QoE score: {qoe_score}/5 ({qoe_flag})", detail)
            if pm_summary:
                console.print(f"  [dim]{pm_summary}[/dim]")
            if pending:
                _warn("EBIT haircut >10% — review and manually approve any override in config/valuation_overrides.yaml before acting")

            # Build compact context string for ThesisAgent
            det = qoe_result.get("deterministic") or {}
            signal_scores = det.get("signal_scores") or {}
            flags = [f"{k}: {v}" for k, v in signal_scores.items() if v in ("amber", "red")]
            rev_flags = llm_block.get("revenue_recognition_flags") or []
            auditor_flags = llm_block.get("auditor_flags") or []
            qoe_context = (
                f"QoE score: {qoe_score}/5 ({qoe_flag})\n"
                f"PM summary: {pm_summary}\n"
            )
            if flags:
                qoe_context += "Flagged signals: " + ", ".join(flags) + "\n"
            if haircut is not None:
                qoe_context += f"EBIT normalisation: {haircut:+.1f}% haircut"
                if pending:
                    qoe_context += " (OVERRIDE PENDING PM APPROVAL)"
                qoe_context += "\n"
            if rev_flags:
                qoe_context += "Revenue recognition flags: " + "; ".join(rev_flags) + "\n"
            if auditor_flags:
                qoe_context += "Auditor flags: " + "; ".join(auditor_flags) + "\n"
        except Exception as e:
            _warn(f"QoEAgent error: {e}")

        # --- Step 2b: Accounting recast ---
        _step("2b/9  AccountingRecastAgent — proposing EBIT and EV-bridge reclassifications")
        accounting_recast_result = {}
        accounting_recast_context = ""
        try:
            accounting_recast_result = self.accounting_recast_agent.analyze(
                ticker=ticker,
                reported_ebit=reported_ebit,
            )
            self.last_accounting_recast_result = accounting_recast_result
            confidence = accounting_recast_result.get("confidence", "low")
            adjustments = accounting_recast_result.get("income_statement_adjustments") or []
            reclasses = accounting_recast_result.get("balance_sheet_reclassifications") or []
            _ok(
                f"Recast confidence: {confidence}",
                f"Adj: {len(adjustments)}  |  Reclasses: {len(reclasses)}",
            )
            if accounting_recast_result.get("approval_required"):
                _warn("Accounting recast remains advisory — approve any values manually in config/valuation_overrides.yaml")
            accounting_recast_context = build_accounting_recast_context(accounting_recast_result)
            if accounting_recast_context:
                console.print(f"  [dim]{accounting_recast_context}[/dim]")
        except Exception as e:
            _warn(f"AccountingRecastAgent error: {e}")

        # --- Step 3: Valuation ---
        _step("3/9  ValuationAgent — running DCF + comps")
        try:
            valuation = self.valuation_agent.analyze(ticker, filings)
            upside = (valuation.upside_pct_base or 0) * 100
            _ok(
                f"Bear ${valuation.bear:.0f}  |  Base ${valuation.base:.0f}  |  Bull ${valuation.bull:.0f}",
                f"Upside to base: {upside:+.1f}%",
            )
        except Exception as e:
            _warn(f"ValuationAgent error: {e}")
            from src.stage_02_valuation.templates.ic_memo import ValuationRange
            p = mkt.get("current_price", 0) if mkt else 0
            valuation = ValuationRange(bear=p * 0.7, base=p, bull=p * 1.3, current_price=p)

        # --- Step 4: Sentiment ---
        _step("4/9  SentimentAgent — scoring news & analyst positioning")
        try:
            sentiment = self.sentiment_agent.analyze(ticker)
            _ok(
                f"Direction: {sentiment.direction}  |  Score: {sentiment.score:+.2f}",
                f"Bullish themes: {len(sentiment.key_bullish_themes)}  Bearish: {len(sentiment.key_bearish_themes)}",
            )
        except Exception as e:
            _warn(f"SentimentAgent error: {e}")
            from src.stage_02_valuation.templates.ic_memo import SentimentOutput
            sentiment = SentimentOutput(raw_summary=f"Error: {e}")

        # --- Step 5: Risk ---
        _step("5/9  RiskAgent — sizing position")
        try:
            risk = self.risk_agent.analyze(ticker, valuation, sentiment)
            _ok(
                f"Conviction: {risk.conviction.upper()}  |  Size: ${risk.position_size_usd:,.0f} ({risk.position_pct*100:.1f}%)",
                f"Stop loss: {risk.suggested_stop_loss_pct*100:.0f}%",
            )
        except Exception as e:
            _warn(f"RiskAgent error: {e}")
            from src.stage_02_valuation.templates.ic_memo import RiskOutput
            from config import PORTFOLIO_SIZE_USD, CONVICTION_SIZING
            risk = RiskOutput(
                conviction="low",
                position_size_usd=PORTFOLIO_SIZE_USD * CONVICTION_SIZING["low"],
                position_pct=CONVICTION_SIZING["low"],
                suggested_stop_loss_pct=0.20,
                rationale=f"Error: {e}",
            )

        # --- Step 6: Thesis synthesis ---
        _step("6/9  ThesisAgent — synthesizing IC memo")
        try:
            memo = self.thesis_agent.synthesize(
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
            )
            memo.accounting_recast = accounting_recast_result
            _ok(f"Action: {memo.action}  |  {memo.one_liner}")
        except Exception as e:
            _warn(f"ThesisAgent error: {e}")
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
                one_liner=f"Analysis incomplete: {e}",
                variant_thesis_prompt="Review agent outputs manually.",
            )

        console.print("\n[bold green]Pipeline complete.[/bold green]")
        return memo

    def collect_recommendations(self, ticker: str):
        """Build TickerRecommendations from cached agent outputs after run().

        Returns a TickerRecommendations object (empty recommendations list if
        no agent outputs are available).
        """
        from src.stage_04_pipeline.recommendations import extract_recommendations
        from src.stage_02_valuation.input_assembler import build_valuation_inputs
        from src.stage_02_valuation.batch_runner import value_single_ticker

        inputs = build_valuation_inputs(ticker.upper().strip())
        drivers = inputs.drivers if inputs else None

        # Get current base IV from deterministic valuation
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
