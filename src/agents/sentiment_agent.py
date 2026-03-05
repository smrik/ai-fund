"""
SentimentAgent — scores recent news and analyst positioning.
Returns a SentimentOutput with direction, score, and key themes.
"""

import json
from src.agents.base_agent import BaseAgent
from src.data import market_data as md_client
from src.templates.ic_memo import SentimentOutput


SYSTEM_PROMPT = """You are a market intelligence analyst specializing in news sentiment and narrative analysis.

Your job is to:
1. Read recent news headlines and assess the dominant narrative around a stock
2. Identify what the market's current consensus story is
3. Flag where the narrative may be wrong, overblown, or missing something
4. Score overall sentiment from -1.0 (very bearish) to +1.0 (very bullish)

Be specific about THEMES, not just positive/negative labels.
A stock with uniformly bullish news is often more dangerous than one with mixed sentiment.
Flag if the news cycle is unusually quiet — that's also a signal.

Key patterns to watch:
- Rapid sentiment shift from bullish to cautious = potential turning point
- Analyst upgrades/downgrades clustering = herd behavior, fades quickly
- Macro blame for company-specific problems = red flag for management credibility"""


class SentimentAgent(BaseAgent):
    def __init__(self):
        super().__init__()
        self.name = "SentimentAgent"
        self.system_prompt = SYSTEM_PROMPT

        self.tools = [
            self._tool(
                name="get_news_headlines",
                description="Fetch recent news headlines and summaries for a ticker.",
                properties={
                    "ticker": {"type": "string"},
                    "limit": {"type": "integer", "description": "Number of headlines, default 15"},
                },
                required=["ticker"],
            ),
            self._tool(
                name="get_analyst_ratings",
                description="Get current analyst ratings, price targets, and recommendation distribution.",
                properties={"ticker": {"type": "string"}},
                required=["ticker"],
            ),
        ]

        self.tool_handlers = {
            "get_news_headlines": self._handle_news,
            "get_analyst_ratings": self._handle_ratings,
        }

    def _handle_news(self, inp: dict) -> str:
        ticker = inp["ticker"]
        limit = inp.get("limit", 15)
        news = md_client.get_news(ticker, limit)
        return json.dumps(news)

    def _handle_ratings(self, inp: dict) -> str:
        return json.dumps(md_client.get_analyst_ratings(inp["ticker"]))

    def analyze(self, ticker: str) -> SentimentOutput:
        """Run sentiment analysis for ticker. Returns SentimentOutput."""
        prompt = f"""Perform a sentiment and narrative analysis for {ticker.upper()}.

Steps:
1. Call get_news_headlines to retrieve recent news
2. Call get_analyst_ratings to understand analyst positioning
3. Score overall sentiment and identify dominant themes
4. Flag risk narratives and any surprising gaps in coverage

Return your analysis as JSON:
{{
  "direction": "<bullish|neutral|bearish>",
  "score": <float from -1.0 to +1.0>,
  "key_bullish_themes": ["<theme>", ...],
  "key_bearish_themes": ["<theme>", ...],
  "risk_narratives": ["<narrative>", ...],
  "raw_summary": "<2-3 paragraph analysis of the news narrative>"
}}"""

        raw = self.run(prompt)

        try:
            start = raw.find("{")
            end = raw.rfind("}") + 1
            data = json.loads(raw[start:end])
            return SentimentOutput(**data)
        except Exception:
            return SentimentOutput(raw_summary=raw)
