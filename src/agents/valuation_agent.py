"""
ValuationAgent — deep fundamental valuation with multiple methodologies.

This is NOT a quick DCF script. It performs:
1. Comprehensive financial data gathering (multi-year P&L, BS, CF)
2. Quality of earnings analysis (accruals vs cash, recurring vs one-time)
3. Multiple valuation methods: DCF, trading comps, reverse DCF, historical range
4. Assumption calibration from actual reported financials
5. Sensitivity analysis on key value drivers
6. Final synthesis with conviction-weighted fair value range

The agent uses tools to gather data and run models, then synthesizes
the results into a structured ValuationRange with commentary.
"""

import json
import numpy as np
from src.agents.base_agent import BaseAgent
from src.data import market_data as md_client
from src.templates.dcf_model import DCFAssumptions, run_scenario_dcf
from src.templates.ic_memo import FilingsSummary, ValuationRange


SYSTEM_PROMPT = """You are a senior equity research analyst at a fundamental long/short fund.
You have 15 years of experience valuing small and mid-cap companies ($500M-$10B market cap).

Your valuation process is rigorous and multi-step:

### STEP 1: Data Gathering
- Pull comprehensive market data, financial statements, and historical context
- You MUST call get_financial_profile first to understand the business fundamentals

### STEP 2: Quality of Earnings Assessment
Before running any model, assess whether reported earnings reflect true economic reality:
- Operating cash flow vs. net income: should be >80% on a 3-year basis for quality businesses
- Look for red flags: rising DSOs, inventory builds, capitalized expenses, one-time gains
- Determine a "normalized" earnings power that strips out noise

### STEP 3: Assumption Calibration  
Don't guess assumptions — derive them from the data:
- Revenue growth: use 3-year CAGR as baseline, adjust for industry trends and company guidance
- EBIT margin: use 3-year average, adjust for scale effects and competitive dynamics
- WACC: risk-free (~4.5%) + beta * equity risk premium (~5%). Adjust for size premium (+1-2% for small caps)
- Exit multiple: use current sector EV/EBIT as anchor, adjust for growth and quality

### STEP 4: Multiple Valuation Methods
Run ALL of these — no single method is sufficient:
1. **DCF (primary)**: 10-year explicit period + terminal value via exit multiple
2. **Trading comps**: Where does it trade vs. relevant peers on EV/EBITDA, P/E, P/FCF?
3. **Reverse DCF**: What growth rate is the market currently pricing in? Is it reasonable?
4. **Historical range**: Where is the stock vs. its own 3-year valuation range?

### STEP 5: Triangulation & Fair Value
- Weight the methods: DCF 40%, comps 25%, reverse DCF 20%, historical 15%
- Bear case = conservative assumptions + trough multiples
- Bull case = optimistic but plausible assumptions + peak multiples  
- Base case = most likely scenario, not just the average of bear/bull

### RULES
- Be specific. Use numbers everywhere. No vague "the company is well-positioned" language.
- When the stock is cheap, say so clearly and quantify the margin of safety.
- When it's expensive, say so and explain what needs to go right to justify the price.
- Flag the 2-3 assumptions that matter most for the valuation (what moves the needle).
- Small/mid-caps deserve a size premium in WACC — don't use mega-cap discount rates."""


class ValuationAgent(BaseAgent):
    def __init__(self):
        super().__init__()
        self.name = "ValuationAgent"
        self.system_prompt = SYSTEM_PROMPT

        self.tools = [
            self._tool(
                name="get_financial_profile",
                description="""Fetch comprehensive financial profile: current price, market cap, 
                enterprise value, margins, growth rates, balance sheet items, analyst targets, 
                and historical price data. This is the primary data source — call this FIRST.""",
                properties={"ticker": {"type": "string", "description": "Stock ticker symbol"}},
                required=["ticker"],
            ),
            self._tool(
                name="get_historical_prices",
                description="Get OHLCV price history for computing historical valuation ranges and volatility.",
                properties={
                    "ticker": {"type": "string"},
                    "period": {"type": "string", "description": "1mo, 3mo, 6mo, 1y, 2y, 5y", "default": "3y"},
                },
                required=["ticker"],
            ),
            self._tool(
                name="run_dcf",
                description="""Run a 10-year DCF valuation with bear/base/bull scenarios.
                The model uses explicit period FCFs + terminal value via exit multiple.
                Automatically generates bear (40% stress) and bull (40% upside) scenarios
                from your base case assumptions.
                
                IMPORTANT: Calibrate assumptions from actual financials, don't guess:
                - base_revenue: use TTM revenue from get_financial_profile
                - revenue_growth: use 3-year CAGR as starting point
                - ebit_margin: use operating margin from financials  
                - wacc: compute from beta (add 1-2% size premium for small caps)
                - exit_multiple: benchmark to sector EV/EBIT""",
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
                    "nwc_change_pct_revenue": {"type": "number", "description": "Change in NWC as % of revenue, e.g. 0.01"},
                    "wacc": {"type": "number", "description": "Discount rate inc. size premium, e.g. 0.10"},
                    "exit_multiple": {"type": "number", "description": "EV/EBIT terminal exit multiple, e.g. 15.0"},
                },
                required=["ticker", "base_revenue", "revenue_growth_near", "revenue_growth_mid",
                          "revenue_growth_terminal", "ebit_margin", "tax_rate", "capex_pct_revenue",
                          "da_pct_revenue", "nwc_change_pct_revenue", "wacc", "exit_multiple"],
            ),
            self._tool(
                name="run_reverse_dcf",
                description="""Compute the implied revenue growth rate the market is currently pricing in.
                Uses current EV and works backward through the DCF to find what growth rate
                justifies the current price. Useful for assessing whether expectations are
                reasonable or stretched.""",
                properties={
                    "ticker": {"type": "string"},
                    "base_revenue": {"type": "number", "description": "TTM revenue"},
                    "ebit_margin": {"type": "number", "description": "Assumed normalized EBIT margin"},
                    "wacc": {"type": "number", "description": "Discount rate"},
                    "exit_multiple": {"type": "number", "description": "Terminal EV/EBIT multiple"},
                },
                required=["ticker", "base_revenue", "ebit_margin", "wacc", "exit_multiple"],
            ),
            self._tool(
                name="compute_historical_valuation_range",
                description="""Compute where the stock currently trades relative to its own
                historical valuation range (P/E, EV/EBITDA) using price history.
                Returns current vs. 3-year high/low/median for key multiples.""",
                properties={"ticker": {"type": "string"}},
                required=["ticker"],
            ),
        ]

        self.tool_handlers = {
            "get_financial_profile": self._handle_financial_profile,
            "get_historical_prices": self._handle_historical_prices,
            "run_dcf": self._handle_run_dcf,
            "run_reverse_dcf": self._handle_reverse_dcf,
            "compute_historical_valuation_range": self._handle_historical_valuation,
        }

    # ── Tool Handlers ──────────────────────────────────────

    def _handle_financial_profile(self, inp: dict) -> str:
        """Comprehensive financial profile from yfinance."""
        ticker = inp["ticker"]
        mkt = md_client.get_market_data(ticker)

        # Compute derived quality metrics
        fcf = mkt.get("free_cashflow") or 0
        net_income = (mkt.get("profit_margin") or 0) * (mkt.get("revenue_ttm") or 0)
        mcap = mkt.get("market_cap") or 1

        quality_metrics = {
            "fcf_yield": round(fcf / mcap, 4) if mcap else None,
            "fcf_to_net_income": round(fcf / net_income, 2) if net_income else None,
            "earnings_yield": round(1 / mkt.get("pe_trailing"), 4) if mkt.get("pe_trailing") else None,
            "implied_wacc_from_earnings_yield": round(
                (1 / mkt.get("pe_trailing")) + 0.03, 4
            ) if mkt.get("pe_trailing") and mkt["pe_trailing"] > 0 else None,
        }

        # Size premium estimate
        if mcap and mcap < 2e9:
            quality_metrics["suggested_size_premium"] = 0.02  # 2% for micro/small cap
        elif mcap and mcap < 10e9:
            quality_metrics["suggested_size_premium"] = 0.01  # 1% for mid cap
        else:
            quality_metrics["suggested_size_premium"] = 0.0

        result = {**mkt, "quality_metrics": quality_metrics}
        return json.dumps(result, default=str)

    def _handle_historical_prices(self, inp: dict) -> str:
        """Historical OHLCV data."""
        ticker = inp["ticker"]
        period = inp.get("period", "3y")
        prices = md_client.get_price_history(ticker, period)
        
        # Compute basic stats
        if prices:
            closes = [p["close"] for p in prices]
            returns = [(closes[i] - closes[i-1]) / closes[i-1] for i in range(1, len(closes))]
            stats = {
                "period": period,
                "data_points": len(prices),
                "price_range": {"low": min(closes), "high": max(closes)},
                "current": closes[-1],
                "annualized_volatility": round(float(np.std(returns) * (252 ** 0.5)), 4) if returns else None,
                "total_return_pct": round((closes[-1] / closes[0] - 1) * 100, 1),
            }
        else:
            stats = {"error": "No price data available"}

        return json.dumps({"stats": stats, "recent_prices": prices[-60:]}, default=str)

    def _handle_run_dcf(self, inp: dict) -> str:
        """Run bear/base/bull DCF and return detailed results."""
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
        current_price = mkt.get("current_price") or 0

        result = {}
        for label, dcf_result in scenarios.items():
            iv = dcf_result.intrinsic_value_per_share
            result[label] = {
                "intrinsic_value_per_share": iv,
                "enterprise_value": dcf_result.enterprise_value,
                "pv_fcfs": dcf_result.pv_fcfs,
                "terminal_value": dcf_result.terminal_value,
                "terminal_pct_of_ev": round(dcf_result.terminal_value / dcf_result.enterprise_value * 100, 1) if dcf_result.enterprise_value else 0,
                "upside_pct": round((iv / current_price - 1) * 100, 1) if current_price else 0,
            }

        result["current_price"] = current_price
        result["net_debt"] = net_debt
        result["shares_outstanding"] = shares
        result["assumptions_used"] = {
            "revenue_growth_near": inp["revenue_growth_near"],
            "revenue_growth_mid": inp["revenue_growth_mid"],
            "ebit_margin": inp["ebit_margin"],
            "wacc": inp["wacc"],
            "exit_multiple": inp["exit_multiple"],
        }

        # Sensitivity: what happens if WACC ±1% or exit multiple ±2x?
        sensitivities = []
        for wacc_delta in [-0.01, 0, 0.01]:
            for mult_delta in [-2, 0, 2]:
                adj_assumptions = DCFAssumptions(
                    revenue_growth_near=inp["revenue_growth_near"],
                    revenue_growth_mid=inp["revenue_growth_mid"],
                    revenue_growth_terminal=inp["revenue_growth_terminal"],
                    ebit_margin=inp["ebit_margin"],
                    tax_rate=inp["tax_rate"],
                    capex_pct_revenue=inp["capex_pct_revenue"],
                    da_pct_revenue=inp["da_pct_revenue"],
                    nwc_change_pct_revenue=inp["nwc_change_pct_revenue"],
                    wacc=inp["wacc"] + wacc_delta,
                    exit_multiple=inp["exit_multiple"] + mult_delta,
                    net_debt=net_debt,
                    shares_outstanding=shares,
                )
                from src.templates.dcf_model import run_dcf
                sens_result = run_dcf(inp["base_revenue"], adj_assumptions, "sensitivity")
                sensitivities.append({
                    "wacc": round(inp["wacc"] + wacc_delta, 3),
                    "exit_multiple": inp["exit_multiple"] + mult_delta,
                    "intrinsic_value": sens_result.intrinsic_value_per_share,
                })
        result["sensitivity_table"] = sensitivities

        return json.dumps(result, default=str)

    def _handle_reverse_dcf(self, inp: dict) -> str:
        """Solve for implied growth rate that justifies current market price."""
        ticker = inp["ticker"]
        mkt = md_client.get_market_data(ticker)

        ev = mkt.get("enterprise_value") or 0
        shares = mkt.get("shares_outstanding") or 1
        net_debt = (mkt.get("total_debt") or 0) - (mkt.get("cash") or 0)
        current_price = mkt.get("current_price") or 0

        base_revenue = inp["base_revenue"]
        ebit_margin = inp["ebit_margin"]
        wacc = inp["wacc"]
        exit_multiple = inp["exit_multiple"]

        # Binary search for the growth rate that produces current EV
        low, high = -0.05, 0.40
        for _ in range(50):
            mid_growth = (low + high) / 2
            assumptions = DCFAssumptions(
                revenue_growth_near=mid_growth,
                revenue_growth_mid=mid_growth * 0.7,
                revenue_growth_terminal=0.03,
                ebit_margin=ebit_margin,
                tax_rate=0.21,
                capex_pct_revenue=0.05,
                da_pct_revenue=0.03,
                nwc_change_pct_revenue=0.01,
                wacc=wacc,
                exit_multiple=exit_multiple,
                net_debt=net_debt,
                shares_outstanding=shares,
            )
            from src.templates.dcf_model import run_dcf
            result = run_dcf(base_revenue, assumptions, "reverse")
            implied_ev = result.enterprise_value

            if abs(implied_ev - ev) / max(ev, 1) < 0.01:
                break
            elif implied_ev < ev:
                low = mid_growth
            else:
                high = mid_growth

        implied_growth = round(mid_growth, 4)

        # Context: is this implied growth reasonable?
        actual_growth = mkt.get("revenue_growth")
        commentary = ""
        if actual_growth is not None:
            if implied_growth > actual_growth * 1.5:
                commentary = f"Market implies {implied_growth*100:.1f}% growth, but TTM growth is only {actual_growth*100:.1f}%. Market may be overpricing growth."
            elif implied_growth < actual_growth * 0.5:
                commentary = f"Market implies just {implied_growth*100:.1f}% growth, but TTM growth is {actual_growth*100:.1f}%. Potential undervaluation if growth persists."
            else:
                commentary = f"Market implies {implied_growth*100:.1f}% growth, roughly in line with TTM {actual_growth*100:.1f}%. Fair pricing."

        return json.dumps({
            "implied_revenue_growth_rate": implied_growth,
            "actual_ttm_revenue_growth": actual_growth,
            "current_ev": ev,
            "current_price": current_price,
            "commentary": commentary,
        }, default=str)

    def _handle_historical_valuation(self, inp: dict) -> str:
        """Compare current multiples to historical range."""
        ticker = inp["ticker"]
        mkt = md_client.get_market_data(ticker)

        current_pe = mkt.get("pe_trailing")
        current_ev_ebitda = mkt.get("ev_ebitda")
        current_ps = mkt.get("price_to_sales")
        forward_pe = mkt.get("pe_forward")

        result = {
            "current_multiples": {
                "pe_trailing": current_pe,
                "pe_forward": forward_pe,
                "ev_ebitda": current_ev_ebitda,
                "price_to_sales": current_ps,
                "price_to_book": mkt.get("price_to_book"),
            },
            "analyst_consensus": {
                "target_mean": mkt.get("analyst_target_mean"),
                "target_low": mkt.get("analyst_target_low"),
                "target_high": mkt.get("analyst_target_high"),
                "recommendation": mkt.get("analyst_recommendation"),
                "num_analysts": mkt.get("number_of_analysts"),
            },
            "52_week_range": {
                "low": mkt.get("52w_low"),
                "high": mkt.get("52w_high"),
                "current": mkt.get("current_price"),
                "pct_from_low": round(
                    (mkt.get("current_price", 0) / mkt.get("52w_low", 1) - 1) * 100, 1
                ) if mkt.get("52w_low") else None,
                "pct_from_high": round(
                    (mkt.get("current_price", 0) / mkt.get("52w_high", 1) - 1) * 100, 1
                ) if mkt.get("52w_high") else None,
            },
        }

        # Forward vs trailing PE discount/premium
        if current_pe and forward_pe and forward_pe > 0:
            result["pe_expansion_contraction"] = {
                "forward_discount_pct": round((1 - forward_pe / current_pe) * 100, 1),
                "interpretation": "Earnings expected to grow (forward PE lower)" if forward_pe < current_pe else "Earnings expected to decline (forward PE higher)"
            }

        return json.dumps(result, default=str)

    # ── Main Entry Point ──────────────────────────────────

    def analyze(self, ticker: str, filings_summary: FilingsSummary = None) -> ValuationRange:
        """
        Run comprehensive multi-methodology valuation.
        Returns ValuationRange with bear/base/bull intrinsic values.
        """
        filings_ctx = filings_summary.model_dump_json(indent=2) if filings_summary else "{}"

        prompt = f"""Perform a comprehensive valuation analysis for {ticker.upper()}.

Context from filings analysis (use for assumption calibration):
{filings_ctx}

Execute your full 5-step valuation process:

1. FIRST call get_financial_profile to get the complete financial picture
2. Call get_historical_prices with period "3y" to understand price dynamics
3. Call compute_historical_valuation_range to see where multiples sit vs history
4. Based on the data gathered, calibrate your DCF assumptions and call run_dcf
5. Call run_reverse_dcf to check what growth the market is pricing in

After running all tools, synthesize your analysis into a final JSON response with:
{{
    "bear": <bear case intrinsic value per share>,
    "base": <base case intrinsic value per share>,
    "bull": <bull case intrinsic value per share>,
    "current_price": <current market price>,
    "upside_pct_base": <(base - price) / price as decimal>,
    "valuation_commentary": "<3-5 sentences covering: (1) which methodology is most reliable for this company, (2) where the stock sits vs. fair value, (3) what are the 2-3 key assumptions that drive the valuation, (4) what would make you wrong>"
}}

Remember:
- Derive assumptions from the actual financial data, don't guess
- Add size premium to WACC for small/mid-caps
- Review the sensitivity table to understand what drives the range
- Check if the reverse DCF implied growth is reasonable vs. actuals
- Be direct about whether this is cheap, fair, or expensive"""

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
