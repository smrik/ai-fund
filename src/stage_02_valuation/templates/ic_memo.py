"""
Investment Committee (IC) Memo — structured Pydantic model.
This is the final output of the pipeline, surfaced in the dashboard.
"""

from datetime import date
from typing import Optional
from pydantic import BaseModel, Field


class ValuationRange(BaseModel):
    bear: float = Field(description="Bear case intrinsic value per share")
    base: float = Field(description="Base case intrinsic value per share")
    bull: float = Field(description="Bull case intrinsic value per share")
    current_price: Optional[float] = None
    upside_pct_base: Optional[float] = None  # (base - price) / price


class FilingsSummary(BaseModel):
    revenue_cagr_3y: Optional[float] = None
    gross_margin_avg: Optional[float] = None
    ebit_margin_avg: Optional[float] = None
    fcf_yield: Optional[float] = None
    net_debt_to_ebitda: Optional[float] = None
    revenue_trend: str = ""        # narrative: "accelerating", "decelerating", "stable"
    margin_trend: str = ""
    red_flags: list[str] = Field(default_factory=list)
    management_guidance: str = ""
    raw_summary: str = ""          # full Claude narrative


class EarningsSummary(BaseModel):
    eps_beat_rate: Optional[float] = None    # fraction, e.g. 0.75 = 75% beats
    guidance_trend: str = ""                 # "raised", "maintained", "lowered"
    management_tone: str = ""               # "confident", "cautious", "defensive"
    key_themes: list[str] = Field(default_factory=list)
    tone_shift: str = ""                    # vs prior quarter
    raw_summary: str = ""


class SentimentOutput(BaseModel):
    direction: str = ""            # "bullish", "neutral", "bearish"
    score: float = 0.0             # -1.0 to +1.0
    key_bullish_themes: list[str] = Field(default_factory=list)
    key_bearish_themes: list[str] = Field(default_factory=list)
    risk_narratives: list[str] = Field(default_factory=list)
    raw_summary: str = ""


class RiskOutput(BaseModel):
    conviction: str = ""           # "high", "medium", "low"
    position_size_usd: float = 0.0
    position_pct: float = 0.0     # fraction of portfolio
    suggested_stop_loss_pct: float = 0.0
    annualized_volatility: Optional[float] = None
    rationale: str = ""


class ICMemo(BaseModel):
    # Header
    ticker: str
    company_name: str
    sector: str = ""
    date: str = Field(default_factory=lambda: str(date.today()))
    analyst: str = "AI Research Pod"

    # One-liner
    one_liner: str = ""            # e.g. "Dominant cloud infra compounder at 15% discount to base case"

    # Recommended action
    action: str = ""               # "BUY", "SELL SHORT", "WATCH", "PASS"
    conviction: str = ""           # "high", "medium", "low"

    # Structured sub-sections
    filings: FilingsSummary = Field(default_factory=FilingsSummary)
    earnings: EarningsSummary = Field(default_factory=EarningsSummary)
    valuation: ValuationRange = Field(default_factory=lambda: ValuationRange(bear=0, base=0, bull=0))
    sentiment: SentimentOutput = Field(default_factory=SentimentOutput)
    risk: RiskOutput = Field(default_factory=RiskOutput)

    # The thesis (what Claude synthesizes; you refine)
    bull_case: str = ""
    bear_case: str = ""
    base_case: str = ""
    variant_thesis_prompt: str = ""  # The question the AI flags for YOUR judgment
    key_catalysts: list[str] = Field(default_factory=list)
    key_risks: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)

    def display_summary(self) -> str:
        """Terminal-friendly summary string."""
        lines = [
            f"\n{'='*60}",
            f"  IC MEMO — {self.ticker} ({self.company_name})",
            f"  {self.date} | {self.sector}",
            f"{'='*60}",
            f"  ACTION: {self.action}  |  CONVICTION: {self.conviction.upper()}",
            f"  {self.one_liner}",
            f"",
            f"  VALUATION (per share)",
            f"    Bear: ${self.valuation.bear:.2f}  |  Base: ${self.valuation.base:.2f}  |  Bull: ${self.valuation.bull:.2f}",
            f"    Current: ${self.valuation.current_price or 0:.2f}  |  Upside (base): {(self.valuation.upside_pct_base or 0)*100:.1f}%",
            f"",
            f"  POSITION SIZE",
            f"    ${self.risk.position_size_usd:,.0f}  ({self.risk.position_pct*100:.1f}% of portfolio)",
            f"    Stop loss: {self.risk.suggested_stop_loss_pct*100:.0f}% below entry",
            f"",
            f"  BULL CASE",
            f"    {self.bull_case}",
            f"",
            f"  BEAR CASE",
            f"    {self.bear_case}",
            f"",
            f"  VARIANT THESIS PROMPT (your judgment required)",
            f"    {self.variant_thesis_prompt}",
            f"",
            f"  KEY CATALYSTS: {', '.join(self.key_catalysts)}",
            f"  OPEN QUESTIONS: {', '.join(self.open_questions)}",
            f"{'='*60}\n",
        ]
        return "\n".join(lines)
