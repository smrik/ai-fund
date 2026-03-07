"""
ThesisAgent — synthesizes all prior agent outputs into a structured IC memo.
This is the final synthesis step. No external tool calls — works purely from context.
Returns a completed ICMemo.
"""

import json
from src.stage_03_judgment.base_agent import BaseAgent
from src.stage_02_valuation.templates.ic_memo import (
    ICMemo, FilingsSummary, EarningsSummary,
    ValuationRange, SentimentOutput, RiskOutput,
)


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
        super().__init__()
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
    ) -> ICMemo:
        """Synthesize all agent outputs into a final IC memo."""

        context = f"""
TICKER: {ticker.upper()}
COMPANY: {company_name}
SECTOR: {sector}

=== FILINGS ANALYSIS ===
{filings.model_dump_json(indent=2)}

=== EARNINGS ANALYSIS ===
{earnings.model_dump_json(indent=2)}

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

        raw = self.run(prompt)

        try:
            start = raw.find("{")
            end = raw.rfind("}") + 1
            data = json.loads(raw[start:end])
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
