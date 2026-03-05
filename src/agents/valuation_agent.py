"""
ValuationAgent — auto-populates DCF model and computes comps multiples.
Returns a ValuationOutput with bear/base/bull intrinsic value per share.
"""

import json
from src.agents.base_agent import BaseAgent
from src.data import market_data as md_client
from src.templates.dcf_model import DCFAssumptions, run_scenario_dcf
from src.templates.ic_memo import FilingsSummary, ValuationRange


SYSTEM_PROMPT = """You are a quantitative equity analyst specializing in DCF valuation and comparable analysis.

Your job is to:
1. Review the company's financial profile
2. Choose appropriate DCF assumptions (growth rates, margins, WACC, exit multiple)
3. Run the DCF model via the provided tool
4. Benchmark against comparable multiples
5. Produce a bear/base/bull intrinsic value range

Calibrate assumptions carefully:
- WACC: risk-free rate (~4.5%) + equity risk premium (~5%) * beta. Range 7-12% for most companies.
- Terminal growth: 2-4% for mature businesses, never > long-run GDP
- Exit multiple: sector-appropriate EV/EBIT. Tech = 15-25x, Industrials = 10-15x, Utilities = 8-12x
- Be conservative — bull case is not "everything goes right", it's the reasonable upside scenario

When the stock is cheap, say so clearly. When it's expensive, say so."""


class ValuationAgent(BaseAgent):
    def __init__(self):
        super().__init__()
        self.name = "ValuationAgent"
        self.system_prompt = SYSTEM_PROMPT

        self.tools = [
            self._tool(
                name="get_market_data",
                description="Fetch current price, market cap, EV, and valuation multiples for a ticker.",
                properties={"ticker": {"type": "string"}},
                required=["ticker"],
            ),
            self._tool(
                name="run_dcf",
                description="""Run a bear/base/bull DCF valuation. Provide assumptions and the tool returns intrinsic value per share for each scenario.""",
                properties={
                    "ticker": {"type": "string"},
                    "base_revenue": {"type": "number", "description": "Most recent annual revenue in USD"},
                    "revenue_growth_near": {"type": "number", "description": "Years 1-5 revenue CAGR, e.g. 0.10"},
                    "revenue_growth_mid": {"type": "number", "description": "Years 6-10 revenue CAGR, e.g. 0.07"},
                    "revenue_growth_terminal": {"type": "number", "description": "Terminal growth rate, e.g. 0.03"},
                    "ebit_margin": {"type": "number", "description": "Normalized EBIT margin, e.g. 0.20"},
                    "tax_rate": {"type": "number", "description": "Effective tax rate, e.g. 0.21"},
                    "capex_pct_revenue": {"type": "number", "description": "Capex as % of revenue, e.g. 0.05"},
                    "da_pct_revenue": {"type": "number", "description": "D&A as % of revenue, e.g. 0.03"},
                    "nwc_change_pct_revenue": {"type": "number", "description": "NWC change as % of revenue, e.g. 0.01"},
                    "wacc": {"type": "number", "description": "Discount rate, e.g. 0.09"},
                    "exit_multiple": {"type": "number", "description": "EV/EBIT terminal exit multiple, e.g. 15.0"},
                },
                required=["ticker", "base_revenue", "revenue_growth_near", "revenue_growth_mid",
                          "revenue_growth_terminal", "ebit_margin", "tax_rate", "capex_pct_revenue",
                          "da_pct_revenue", "nwc_change_pct_revenue", "wacc", "exit_multiple"],
            ),
        ]

        self.tool_handlers = {
            "get_market_data": self._handle_market_data,
            "run_dcf": self._handle_run_dcf,
        }

    def _handle_market_data(self, inp: dict) -> str:
        return json.dumps(md_client.get_market_data(inp["ticker"]), default=str)

    def _handle_run_dcf(self, inp: dict) -> str:
        ticker = inp["ticker"]
        mkt = md_client.get_market_data(ticker)

        net_debt = (mkt.get("total_debt") or 0) - (mkt.get("cash") or 0)
        shares = mkt.get("shares_outstanding") or 1

        assumptions = DCFAssumptions(
            revenue_growth_near=inp["revenue_growth_near"],
            revenue_growth_mid=inp["revenue_growth_mid"],
            revenue_growth_terminal=inp["revenue_growth_terminal"],
            ebit_margin=inp["ebit_margin"],
            tax_rate=inp["tax_rate"],
            capex_pct_revenue=inp["capex_pct_revenue"],
            da_pct_revenue=inp["da_pct_revenue"],
            nwc_change_pct_revenue=inp["nwc_change_pct_revenue"],
            wacc=inp["wacc"],
            exit_multiple=inp["exit_multiple"],
            net_debt=net_debt,
            shares_outstanding=shares,
        )

        scenarios = run_scenario_dcf(inp["base_revenue"], assumptions)
        return json.dumps({
            "bear": scenarios["bear"].intrinsic_value_per_share,
            "base": scenarios["base"].intrinsic_value_per_share,
            "bull": scenarios["bull"].intrinsic_value_per_share,
            "current_price": mkt.get("current_price"),
            "ev_ebitda_market": mkt.get("ev_ebitda"),
            "pe_trailing": mkt.get("pe_trailing"),
        })

    def analyze(self, ticker: str, filings_summary: FilingsSummary) -> ValuationRange:
        """Run DCF + comps valuation. Returns ValuationRange."""
        filings_ctx = filings_summary.model_dump_json(indent=2) if filings_summary else "{}"

        prompt = f"""Perform a complete valuation analysis for {ticker.upper()}.

Filings context (use for assumption calibration):
{filings_ctx}

Steps:
1. Call get_market_data to get current price, market cap, and existing multiples
2. Choose appropriate DCF assumptions based on the filings context above
3. Call run_dcf with your chosen assumptions
4. Compare the DCF output to current market multiples
5. Assess whether the stock is cheap, fairly valued, or expensive

Return your analysis as JSON:
{{
  "bear": <bear case intrinsic value per share, float>,
  "base": <base case intrinsic value per share, float>,
  "bull": <bull case intrinsic value per share, float>,
  "current_price": <current market price, float>,
  "upside_pct_base": <(base - price) / price, float>,
  "valuation_commentary": "<2-3 sentences on relative cheapness/expensiveness>"
}}"""

        raw = self.run(prompt)

        try:
            start = raw.find("{")
            end = raw.rfind("}") + 1
            data = json.loads(raw[start:end])
            return ValuationRange(**{k: v for k, v in data.items() if k in ValuationRange.model_fields})
        except Exception:
            mkt = md_client.get_market_data(ticker)
            price = mkt.get("current_price") or 0
            return ValuationRange(bear=price * 0.7, base=price, bull=price * 1.3, current_price=price)
