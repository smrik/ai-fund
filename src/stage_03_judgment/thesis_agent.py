"""
ThesisAgent — synthesizes all prior agent outputs into a structured IC memo.
This is the final synthesis step. No external tool calls — works purely from context.
Returns a completed ICMemo.

Also provides generate_story_profile() — a focused call that produces a
structured StoryDriverProfile for the ticker, suitable for writing to
config/story_drivers_pending.yaml for PM review and approval.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

import yaml

from src.stage_03_judgment.base_agent import BaseAgent
from config import LLM_SYNTHESIS_MODEL
from src.stage_02_valuation.templates.ic_memo import (
    ICMemo, FilingsSummary, EarningsSummary,
    ValuationRange, SentimentOutput, RiskOutput,
)

_ROOT_DIR = Path(__file__).resolve().parent.parent.parent
STORY_DRIVERS_PENDING_PATH = _ROOT_DIR / "config" / "story_drivers_pending.yaml"


SYSTEM_PROMPT = """You are the chief investment officer of a Tiger-style fundamental long/short fund.

You have received research from your analyst team. Your job is to synthesize it into a final
Investment Committee memo that forces a decision.

The IC memo MUST:
1. Take a clear ACTION — BUY, SELL SHORT, WATCH (monitor but don't act), or PASS (not interesting)
2. State a specific VARIANT THESIS PROMPT — the precise question that only the PM (human) can answer
3. Articulate distinct BULL, BASE, and BEAR cases — not just "upside" and "downside"
4. Identify the 2-3 most important CATALYSTS that would close the mispricing gap
5. List the most important OPEN QUESTIONS that need further diligence

The variant thesis prompt is the most important output. Examples of good prompts:
- "Is the margin expansion sustainable given [specific competitive dynamic], or is it a one-time benefit from [factor]?"
- "Will management execute on [specific initiative] within the next 2 quarters, or is this another empty promise?"
- "Does the bear case market share loss narrative account for [specific product cycle], or is it overblown?"

Avoid generic analysis. Be specific to THIS company. Do not hedge everything.
A good IC memo is a forcing function — it makes you decide."""


class ThesisAgent(BaseAgent):
    def __init__(self):
        super().__init__(model=LLM_SYNTHESIS_MODEL)
        self.name = "ThesisAgent"
        self.system_prompt = SYSTEM_PROMPT
        # No external tools — synthesizes from context only
        self.tools = []
        self.tool_handlers = {}

    def synthesize(
        self,
        ticker: str,
        company_name: str,
        sector: str,
        filings: FilingsSummary,
        earnings: EarningsSummary,
        valuation: ValuationRange,
        sentiment: SentimentOutput,
        risk: RiskOutput,
        qoe_context: str = "",
        industry_context: str = "",
        accounting_recast_context: str = "",
    ) -> ICMemo:
        """Synthesize all agent outputs into a final IC memo."""

        qoe_block = f"\n=== QUALITY OF EARNINGS ===\n{qoe_context}" if qoe_context else ""
        industry_block = f"\n=== INDUSTRY / RECENT EVENTS ===\n{industry_context}" if industry_context else ""
        accounting_recast_block = (
            f"\n=== ACCOUNTING RECAST ===\n{accounting_recast_context}"
            if accounting_recast_context
            else ""
        )

        context = f"""
TICKER: {ticker.upper()}
COMPANY: {company_name}
SECTOR: {sector}

=== FILINGS ANALYSIS ===
{filings.model_dump_json(indent=2)}

=== EARNINGS ANALYSIS ===
{earnings.model_dump_json(indent=2)}
{qoe_block}{accounting_recast_block}{industry_block}
=== VALUATION ===
{valuation.model_dump_json(indent=2)}

=== SENTIMENT ===
{sentiment.model_dump_json(indent=2)}

=== RISK / POSITION SIZING ===
{risk.model_dump_json(indent=2)}
"""

        prompt = f"""Based on all research below, produce the final IC memo for {ticker.upper()}.

{context}

Return your synthesis as a JSON object with EXACTLY these fields:
{{
  "one_liner": "<single sentence summarizing the investment thesis>",
  "action": "<BUY|SELL SHORT|WATCH|PASS>",
  "conviction": "<high|medium|low>",
  "bull_case": "<2-3 sentences, specific>",
  "bear_case": "<2-3 sentences, specific>",
  "base_case": "<2-3 sentences, specific>",
  "variant_thesis_prompt": "<the single most important question only the human PM can answer>",
  "key_catalysts": ["<catalyst 1>", "<catalyst 2>", "<catalyst 3>"],
  "key_risks": ["<risk 1>", "<risk 2>", "<risk 3>"],
  "open_questions": ["<question 1>", "<question 2>", "<question 3>"]
}}"""

        try:
            raw = self.run(prompt)
        except Exception as e:
            raw = ""
            data = {
                "one_liner": f"ThesisAgent LLM error: {e}",
                "action": "WATCH",
                "conviction": "low",
                "bull_case": "",
                "bear_case": "",
                "base_case": f"Error: {e}",
                "variant_thesis_prompt": "Review agent outputs manually.",
                "key_catalysts": [],
                "key_risks": [],
                "open_questions": [],
            }
            return ICMemo(
                ticker=ticker.upper(),
                company_name=company_name,
                sector=sector,
                filings=filings,
                earnings=earnings,
                valuation=valuation,
                sentiment=sentiment,
                risk=risk,
                **data,
            )

        try:
            data = self.extract_json(raw)
        except Exception:
            data = {
                "one_liner": ticker,
                "action": "WATCH",
                "conviction": "low",
                "bull_case": "",
                "bear_case": "",
                "base_case": raw,
                "variant_thesis_prompt": "Review agent outputs manually.",
                "key_catalysts": [],
                "key_risks": [],
                "open_questions": [],
            }

        return ICMemo(
            ticker=ticker.upper(),
            company_name=company_name,
            sector=sector,
            filings=filings,
            earnings=earnings,
            valuation=valuation,
            sentiment=sentiment,
            risk=risk,
            **data,
        )

    def generate_story_profile(
        self,
        ticker: str,
        company_name: str,
        sector: str,
        filings: FilingsSummary,
        earnings: EarningsSummary,
    ) -> dict | None:
        """
        Produce a structured StoryDriverProfile for the ticker.

        Focused call — does not require a full pipeline run. Uses only the
        filings and earnings summaries as context.

        Returns a dict with keys matching StoryDriverProfile fields, or None
        on failure. Caller should pass result to write_story_driver_pending().
        """
        context = f"""
TICKER: {ticker.upper()}
COMPANY: {company_name}
SECTOR: {sector}

=== FILINGS SUMMARY ===
{filings.model_dump_json(indent=2)}

=== EARNINGS SUMMARY ===
{earnings.model_dump_json(indent=2)}
"""
        prompt = f"""Based on the fundamental research below, assess the qualitative competitive
characteristics for {ticker.upper()} and produce a structured story driver profile.

{context}

The story driver profile feeds directly into the DCF model to adjust growth, margins,
WACC, and terminal value weighting. Be rigorous and company-specific — do not default
to sector averages.

Field definitions:
  moat_strength (1-5): 1=commodity/no moat, 3=average, 5=wide moat (network effects, IP, switching costs)
  pricing_power (1-5): 1=pure price taker, 3=moderate, 5=strong premium pricing with demand inelasticity
  cyclicality (low|medium|high): sensitivity of revenue/margins to economic cycle
  capital_intensity (low|medium|high): capex as % of revenue; R&D-heavy = medium not high
  governance_risk (low|medium|high): quality of capital allocation, management track record, related-party risk
  competitive_advantage_years (1-20): how many years is the moat likely to be durable?

Return ONLY this JSON:
{{
  "moat_strength": <int 1-5>,
  "pricing_power": <int 1-5>,
  "cyclicality": "<low|medium|high>",
  "capital_intensity": "<low|medium|high>",
  "governance_risk": "<low|medium|high>",
  "competitive_advantage_years": <int 1-20>,
  "rationale": "<2-3 sentences justifying the scores specific to this company>"
}}"""

        try:
            raw = self.run(prompt)
        except Exception:
            return None

        try:
            return self.extract_json(raw)
        except Exception:
            return None


def write_story_driver_pending(
    ticker: str,
    profile: dict,
    basis: str = "llm_thesis",
    path: Path | None = None,
) -> Path:
    """
    Write a story driver profile to story_drivers_pending.yaml for PM review.

    PM workflow:
      1. Review config/story_drivers_pending.yaml
      2. Set status: approved  (or delete the entry to reject)
      3. The profile is consumed automatically by resolve_story_driver_profile()
         on the next valuation run (no manual copy needed)

    Returns the path written to.
    """
    out_path = path or STORY_DRIVERS_PENDING_PATH

    # Load existing pending YAML
    existing: dict = {}
    if out_path.exists():
        try:
            existing = yaml.safe_load(out_path.read_text(encoding="utf-8")) or {}
        except Exception:
            existing = {}

    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    entry: dict = {
        "status": "pending",
        "basis": basis,
        "generated_at": now,
        "profile": {
            "moat_strength": profile.get("moat_strength", 3),
            "pricing_power": profile.get("pricing_power", 3),
            "cyclicality": profile.get("cyclicality", "medium"),
            "capital_intensity": profile.get("capital_intensity", "medium"),
            "governance_risk": profile.get("governance_risk", "medium"),
            "competitive_advantage_years": profile.get("competitive_advantage_years", 7),
        },
    }
    if profile.get("rationale"):
        entry["rationale"] = profile["rationale"]

    existing[ticker.upper()] = entry

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        yaml.dump(existing, default_flow_style=False, sort_keys=True, allow_unicode=True),
        encoding="utf-8",
    )
    return out_path
