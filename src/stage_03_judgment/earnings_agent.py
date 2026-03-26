"""
EarningsAgent — analyses earnings call 8-K filings and EPS history.
Extracts guidance vs actuals, management tone, and key themes.
Returns an EarningsSummary.
"""

import json

from src.stage_00_data import edgar_client, filing_retrieval, market_data
from src.stage_02_valuation.templates.ic_memo import EarningsSummary
from src.stage_03_judgment.base_agent import BaseAgent


SYSTEM_PROMPT = """You are a buy-side equity analyst specializing in earnings quality analysis.
Your job is to extract signal from earnings releases, quarterly filings, and EPS histories.

The input is intentionally split into:
- accounting / filing context from 10-K notes plus the latest 2 10-Qs
- recent management communication from 8-K earnings releases

Use that split correctly:
1. Use notes and quarterly filings first for one-offs, accounting signals, classification issues, and disclosure changes
2. Use 8-K earnings releases first for guidance, tone, framing, and what management chose to emphasize
3. Compare the accounting context with management communication and flag mismatches

Focus on:
1. Beat/miss rate vs consensus — are they sandbagging or genuinely uncertain?
2. Guidance trend — raised, maintained, or lowered? By how much?
3. Management tone — confident, cautious, defensive? Has it shifted?
4. Key themes — what are they emphasizing? What are they avoiding?
5. Divergence between narrative and numbers — happy talk with deteriorating metrics is a red flag
6. One-off events or note disclosures that matter for interpreting the quarter

Be direct. Identify tone shifts even if subtle. A management team that suddenly talks more about macro headwinds
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

    def analyze(
        self,
        ticker: str,
        filings_context: str = "",
        filing_context: str | None = None,
        earnings_8k_context: str | None = None,
    ) -> EarningsSummary:
        """Run earnings analysis for ticker. Returns EarningsSummary."""
        if filing_context is None:
            try:
                bundle = filing_retrieval.get_agent_filing_context(
                    ticker,
                    profile_name="earnings",
                    include_10k=True,
                    ten_q_limit=2,
                )
                filing_context = filing_retrieval.render_filing_context(bundle, max_chars=24_000)
            except Exception:
                filing_context = filings_context or ""

        if earnings_8k_context is None:
            earnings_8k_payload = self._handle_8k_text({"ticker": ticker, "limit": 3})
            earnings_8k_context = earnings_8k_payload

        legacy_context_block = f"\nLegacy filings summary:\n{filings_context}" if filings_context else ""

        prompt = f"""Analyze the earnings quality and management communication for {ticker.upper()}.

Accounting / filing context:
{filing_context}

Recent management communication (8-K earnings releases):
{earnings_8k_context}{legacy_context_block}

Steps:
1. Call get_eps_history to get EPS growth and analyst positioning
2. Use the accounting / filing context first to identify one-offs, non-recurring items, and what changed in the latest 2 10-Qs
3. Use the 8-K management communication block to assess tone, guidance, and framing
4. Estimate the beat/miss rate from available data
5. Assess whether guidance has been raised, maintained, or lowered
6. Identify management tone and any shifts vs prior quarters
7. Extract the 3-5 most important recurring themes
8. Explicitly list note-derived watch items and quarterly disclosure changes

Return your analysis as JSON:
{{
  "eps_beat_rate": <float 0-1 or null if insufficient data>,
  "guidance_trend": "<raised|maintained|lowered>",
  "management_tone": "<confident|cautious|defensive>",
  "key_themes": ["<theme 1>", "<theme 2>", ...],
  "notes_watch_items": ["<note-derived watch item>", ...],
  "quarterly_disclosure_changes": ["<latest 10-Q disclosure change>", ...],
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
