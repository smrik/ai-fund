"""
RiskAgent — calculates position sizing based on conviction, volatility, and portfolio config.
Returns a RiskOutput with dollar position size, portfolio %, and stop loss.
"""

import json
from src.stage_03_judgment.base_agent import BaseAgent
from src.stage_00_data import market_data as md_client
from src.stage_02_valuation.templates.ic_memo import RiskOutput, ValuationRange, SentimentOutput
from config import PORTFOLIO_SIZE_USD, CONVICTION_SIZING


SYSTEM_PROMPT = """You are a portfolio risk manager at a fundamental long/short equity fund.

Your job is to size positions correctly given:
1. Conviction level (derived from valuation upside, sentiment, and earnings quality)
2. Stock volatility and beta
3. Portfolio concentration limits (max 8% per name)
4. Downside risk — where is the stop loss given the thesis?

Sizing framework (Tiger-inspired):
- HIGH conviction: 5-8% of portfolio. Requires: >30% upside to base case, positive earnings momentum, clear catalyst
- MEDIUM conviction: 2-4%. Requires: >15% upside, mixed signals, no near-term catalyst
- LOW conviction: 1-2%. Watch list / starter position

Stop loss logic:
- Set stop at the point where your variant thesis is definitively wrong
- Typically 15-25% below entry for longs, 15-20% above for shorts
- Higher volatility stocks warrant tighter stops or smaller size

Be conservative. It is better to start small and add on confirmation."""


class RiskAgent(BaseAgent):
    def __init__(self):
        super().__init__()
        self.name = "RiskAgent"
        self.system_prompt = SYSTEM_PROMPT

        self.tools = [
            self._tool(
                name="get_price_volatility",
                description="Get annualized historical volatility and beta for a ticker.",
                properties={"ticker": {"type": "string"}},
                required=["ticker"],
            ),
            self._tool(
                name="get_portfolio_config",
                description="Return current portfolio size and position limit configuration.",
                properties={},
                required=[],
            ),
        ]

        self.tool_handlers = {
            "get_price_volatility": self._handle_volatility,
            "get_portfolio_config": self._handle_portfolio_config,
        }

    def _handle_volatility(self, inp: dict) -> str:
        ticker = inp["ticker"]
        try:
            vol = md_client.get_volatility(ticker)
            mkt = md_client.get_market_data(ticker)
            return json.dumps({
                "annualized_volatility": vol,
                "beta": mkt.get("beta"),
                "short_ratio": mkt.get("short_ratio"),
            })
        except Exception as e:
            return json.dumps({"error": str(e), "ticker": ticker, "annualized_volatility": None, "beta": None})

    def _handle_portfolio_config(self, inp: dict) -> str:
        try:
            return json.dumps({
                "portfolio_size_usd": PORTFOLIO_SIZE_USD,
                "conviction_sizing": CONVICTION_SIZING,
                "max_position_pct": max(CONVICTION_SIZING.values()),
            })
        except Exception as e:
            return json.dumps({"error": str(e), "portfolio_size_usd": 100000, "conviction_sizing": {"high": 0.08, "medium": 0.04, "low": 0.02}})

    def analyze(
        self,
        ticker: str,
        valuation: ValuationRange,
        sentiment: SentimentOutput,
    ) -> RiskOutput:
        """Calculate position sizing. Returns RiskOutput."""
        val_ctx = valuation.model_dump_json(indent=2)
        sent_ctx = sentiment.model_dump_json(indent=2)

        prompt = f"""Determine position sizing for {ticker.upper()}.

Valuation context:
{val_ctx}

Sentiment context:
{sent_ctx}

Steps:
1. Call get_price_volatility to assess risk profile
2. Call get_portfolio_config to see sizing limits
3. Determine conviction level (high/medium/low) based on upside, sentiment, and volatility
4. Calculate position size in USD and as % of portfolio
5. Set a stop loss level

Return your analysis as JSON:
{{
  "conviction": "<high|medium|low>",
  "position_size_usd": <float>,
  "position_pct": <float, e.g. 0.06 for 6%>,
  "suggested_stop_loss_pct": <float, e.g. 0.20 for 20% stop>,
  "annualized_volatility": <float or null>,
  "rationale": "<2-3 sentences explaining the sizing decision>"
}}"""

        try:
            raw = self.run(prompt)
        except Exception as e:
            return RiskOutput(
                conviction="low",
                position_size_usd=PORTFOLIO_SIZE_USD * CONVICTION_SIZING["low"],
                position_pct=CONVICTION_SIZING["low"],
                suggested_stop_loss_pct=0.20,
                rationale=f"RiskAgent LLM error: {e}",
            )

        try:
            data = self.extract_json(raw)
            return RiskOutput(**data)
        except Exception:
            return RiskOutput(
                conviction="low",
                position_size_usd=PORTFOLIO_SIZE_USD * CONVICTION_SIZING["low"],
                position_pct=CONVICTION_SIZING["low"],
                suggested_stop_loss_pct=0.20,
                rationale=raw,
            )
