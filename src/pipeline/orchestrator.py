"""
PipelineOrchestrator — runs all 6 agents sequentially and returns the final IC memo.
Prints live progress to console. Human checkpoint is at the end.
"""

from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn

from src.agents.filings_agent import FilingsAgent
from src.agents.earnings_agent import EarningsAgent
from src.agents.valuation_agent import ValuationAgent
from src.agents.sentiment_agent import SentimentAgent
from src.agents.risk_agent import RiskAgent
from src.agents.thesis_agent import ThesisAgent
from src.data import market_data as md_client
from src.templates.ic_memo import ICMemo

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
        self.valuation_agent = ValuationAgent()
        self.sentiment_agent = SentimentAgent()
        self.risk_agent = RiskAgent()
        self.thesis_agent = ThesisAgent()

    def run(self, ticker: str) -> ICMemo:
        ticker = ticker.upper().strip()
        console.print(Panel(
            f"[bold]AI Research Pod[/bold] — {ticker}\nRunning 6-agent fundamental analysis pipeline",
            style="blue",
        ))

        # --- Step 0: Market snapshot ---
        _step("Fetching market snapshot")
        try:
            mkt = md_client.get_market_data(ticker)
            company_name = mkt.get("name") or ticker
            sector = mkt.get("sector") or ""
            price = mkt.get("current_price")
            mktcap = mkt.get("market_cap")
            _ok(
                f"{company_name} ({sector})",
                f"${price:,.2f}  |  Mkt Cap ${mktcap/1e9:.1f}B" if price and mktcap else "",
            )
        except Exception as e:
            _warn(f"Market data error: {e}")
            company_name = ticker
            sector = ""

        # --- Step 1: Filings ---
        _step("1/6  FilingsAgent — parsing SEC 10-K / 10-Q")
        try:
            filings = self.filings_agent.analyze(ticker)
            _ok(
                f"Revenue trend: {filings.revenue_trend}  |  Margins: {filings.margin_trend}",
                f"Red flags: {len(filings.red_flags)}",
            )
            if filings.red_flags:
                for flag in filings.red_flags:
                    _warn(f"  {flag}")
        except Exception as e:
            _warn(f"FilingsAgent error: {e}")
            from src.templates.ic_memo import FilingsSummary
            filings = FilingsSummary(raw_summary=f"Error: {e}")

        # --- Step 2: Earnings ---
        _step("2/6  EarningsAgent — analysing earnings calls")
        try:
            earnings = self.earnings_agent.analyze(ticker, filings.raw_summary)
            _ok(
                f"Guidance: {earnings.guidance_trend}  |  Tone: {earnings.management_tone}",
                f"Beat rate: {(earnings.eps_beat_rate or 0)*100:.0f}%",
            )
        except Exception as e:
            _warn(f"EarningsAgent error: {e}")
            from src.templates.ic_memo import EarningsSummary
            earnings = EarningsSummary(raw_summary=f"Error: {e}")

        # --- Step 3: Valuation ---
        _step("3/6  ValuationAgent — running DCF + comps")
        try:
            valuation = self.valuation_agent.analyze(ticker, filings)
            upside = (valuation.upside_pct_base or 0) * 100
            _ok(
                f"Bear ${valuation.bear:.0f}  |  Base ${valuation.base:.0f}  |  Bull ${valuation.bull:.0f}",
                f"Upside to base: {upside:+.1f}%",
            )
        except Exception as e:
            _warn(f"ValuationAgent error: {e}")
            from src.templates.ic_memo import ValuationRange
            p = mkt.get("current_price", 0) if "mkt" in dir() else 0
            valuation = ValuationRange(bear=p * 0.7, base=p, bull=p * 1.3, current_price=p)

        # --- Step 4: Sentiment ---
        _step("4/6  SentimentAgent — scoring news & analyst positioning")
        try:
            sentiment = self.sentiment_agent.analyze(ticker)
            _ok(
                f"Direction: {sentiment.direction}  |  Score: {sentiment.score:+.2f}",
                f"Bullish themes: {len(sentiment.key_bullish_themes)}  Bearish: {len(sentiment.key_bearish_themes)}",
            )
        except Exception as e:
            _warn(f"SentimentAgent error: {e}")
            from src.templates.ic_memo import SentimentOutput
            sentiment = SentimentOutput(raw_summary=f"Error: {e}")

        # --- Step 5: Risk ---
        _step("5/6  RiskAgent — sizing position")
        try:
            risk = self.risk_agent.analyze(ticker, valuation, sentiment)
            _ok(
                f"Conviction: {risk.conviction.upper()}  |  Size: ${risk.position_size_usd:,.0f} ({risk.position_pct*100:.1f}%)",
                f"Stop loss: {risk.suggested_stop_loss_pct*100:.0f}%",
            )
        except Exception as e:
            _warn(f"RiskAgent error: {e}")
            from src.templates.ic_memo import RiskOutput
            from config import PORTFOLIO_SIZE_USD, CONVICTION_SIZING
            risk = RiskOutput(
                conviction="low",
                position_size_usd=PORTFOLIO_SIZE_USD * CONVICTION_SIZING["low"],
                position_pct=CONVICTION_SIZING["low"],
                suggested_stop_loss_pct=0.20,
                rationale=f"Error: {e}",
            )

        # --- Step 6: Thesis synthesis ---
        _step("6/6  ThesisAgent — synthesizing IC memo")
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
            )
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
                action="WATCH",
                conviction="low",
                one_liner=f"Analysis incomplete: {e}",
                variant_thesis_prompt="Review agent outputs manually.",
            )

        console.print("\n[bold green]Pipeline complete.[/bold green]")
        return memo
