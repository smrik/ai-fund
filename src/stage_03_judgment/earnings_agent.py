"""
EarningsAgent — analyses earnings call 8-K filings and EPS history.
Extracts guidance vs actuals, management tone, and key themes.
Returns an EarningsSummary.
"""

import json
from src.stage_03_judgment.base_agent import BaseAgent
from src.stage_00_data import edgar_client, market_data
from src.stage_02_valuation.templates.ic_memo import EarningsSummary


SYSTEM_PROMPT = """You are a buy-side equity analyst specializing in earnings quality analysis.
Your job is to extract signal from earnings calls and EPS histories.

Focus on:
1. Beat/miss rate vs consensus — are they sandbagging or genuinely uncertain?
2. Guidance trend — raised, maintained, or lowered? By how much?
3. Management tone — confident, cautious, defensive? Has it shifted?
4. Key themes — what are they emphasizing? What are they avoiding?
5. Divergence between narrative and numbers — happy talk with deteriorating metrics is a red flag
6. What the market missed vs what management telegraphed

Be direct. Identify tone shifts even if subtle. A management team that suddenly talks more about "macro headwinds"
and less about specific product KPIs is usually sending a signal."""


class EarningsAgent(BaseAgent):
    def __init__(self):
        super().__init__()
        self.name = "EarningsAgent"
        self.system_prompt = SYSTEM_PROMPT

        self.tools = [
            self._tool(
                name="get_earnings_8k_text",
                description="Fetch the full text of recent 8-K earnings press releases for a ticker from SEC EDGAR.",
                properties={
                    "ticker": {"type": "string"},
                    "limit": {"type": "integer", "description": "Number of 8-Ks to fetch, default 3"},
                },
                required=["ticker"],
            ),
            self._tool(
                name="get_eps_history",
                description="Get EPS history and analyst estimates from market data for beat/miss analysis.",
                properties={"ticker": {"type": "string"}},
                required=["ticker"],
            ),
        ]

        self.tool_handlers = {
            "get_earnings_8k_text": self._handle_8k_text,
            "get_eps_history": self._handle_eps,
        }

    def _handle_8k_text(self, inp: dict) -> str:
        ticker = inp["ticker"]
        limit = inp.get("limit", 3)
        try:
            filings = edgar_client.get_8k_texts(ticker, limit=limit)
            if not filings:
                return json.dumps({"error": "No 8-K filings found", "ticker": ticker, "filings": []})
            return json.dumps(filings)
        except Exception as e:
            return json.dumps({"error": str(e), "ticker": ticker, "filings": []})

    def _handle_eps(self, inp: dict) -> str:
        ticker = inp["ticker"]
        try:
            md = market_data.get_market_data(ticker)
            return json.dumps({
                "earnings_growth": md.get("earnings_growth"),
                "pe_trailing": md.get("pe_trailing"),
                "pe_forward": md.get("pe_forward"),
                "analyst_recommendation": md.get("analyst_recommendation"),
                "num_analysts": md.get("number_of_analysts"),
            })
        except Exception as e:
            return json.dumps({"error": str(e), "ticker": ticker})

    def analyze(self, ticker: str, filings_context: str = "") -> EarningsSummary:
        """Run earnings analysis for ticker. Returns EarningsSummary."""
        context_block = f"\n\nFilings context:\n{filings_context}" if filings_context else ""

        prompt = f"""Analyze the earnings quality and management communication for {ticker.upper()}.{context_block}

Steps:
1. Call get_earnings_8k_text to retrieve the full text of recent earnings press releases
2. Call get_eps_history to get EPS growth and analyst positioning
3. Estimate the beat/miss rate from available data
4. Assess whether guidance has been raised, maintained, or lowered
5. Identify management tone and any shifts vs prior quarters
6. Extract the 3-5 most important recurring themes

Return your analysis as JSON:
{{
  "eps_beat_rate": <float 0-1 or null if insufficient data>,
  "guidance_trend": "<raised|maintained|lowered>",
  "management_tone": "<confident|cautious|defensive>",
  "key_themes": ["<theme 1>", "<theme 2>", ...],
  "tone_shift": "<improving|stable|deteriorating>",
  "raw_summary": "<2-3 paragraph qualitative analysis>"
}}"""

        try:
            raw = self.run(prompt)
        except Exception as e:
            return EarningsSummary(raw_summary=f"EarningsAgent LLM error: {e}")

        try:
            data = BaseAgent.extract_json(raw)
            return EarningsSummary(**data)
        except Exception:
            return EarningsSummary(raw_summary=raw[:2000] if raw else "")
