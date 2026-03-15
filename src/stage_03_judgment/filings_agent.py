"""
FilingsAgent — parses SEC 10-K and 10-Q filings.
Extracts revenue trends, margins, FCF, debt, guidance, and red flags.
Returns a FilingsSummary.
"""

import json

from src.stage_00_data import edgar_client, filing_retrieval
from src.stage_02_valuation.templates.ic_memo import FilingsSummary
from src.stage_03_judgment.base_agent import BaseAgent


SYSTEM_PROMPT = """You are a senior equity research analyst specializing in fundamental analysis of SEC filings.
Your job is to extract and analyse financial data from 10-K and 10-Q filings.

The filing context is already curated for you. Treat it like an analyst packet:
- prioritize notes to the financial statements first for accounting issues, one-offs, contingencies, leases,
  impairments, segment disclosures, revenue recognition, pensions, taxes, and debt
- use MD&A second for operating drivers, pricing, demand, and management explanation
- use the latest 2 quarterlies to identify what changed after the annual filing

Focus on:
1. Revenue trend and CAGR — is growth accelerating, stable, or decelerating?
2. Gross and EBIT margin trajectory — is the business becoming more or less profitable?
3. Free cash flow generation and FCF yield relative to market cap
4. Balance sheet health — net debt / EBITDA, interest coverage
5. Management guidance vs actuals — are they sandbagging or missing?
6. Accounting red flags — revenue recognition changes, rising DSOs, accruals vs cash divergence
7. Key business drivers from notes + MD&A
8. Specific note-derived watch items and recent quarterly disclosure changes

Be specific. Use numbers. Flag anomalies explicitly.
Output a structured analysis. Do not hedge excessively — make a clear directional call on quality."""


class FilingsAgent(BaseAgent):
    def __init__(self):
        super().__init__()
        self.name = "FilingsAgent"
        self.system_prompt = SYSTEM_PROMPT

        self.tools = [
            self._tool(
                name="get_company_facts",
                description="Fetch XBRL financial facts (revenue, net income, EPS, cash, debt) from SEC EDGAR for the given ticker.",
                properties={"ticker": {"type": "string", "description": "Stock ticker symbol, e.g. AAPL"}},
                required=["ticker"],
            ),
        ]

        self.tool_handlers = {
            "get_company_facts": self._handle_company_facts,
        }

    def _handle_company_facts(self, inp: dict) -> str:
        ticker = inp["ticker"]
        try:
            cik = edgar_client.get_cik(ticker)
            facts = edgar_client.get_company_facts(cik)
            extracted = edgar_client.extract_financial_facts(facts)
            company_name = facts.get("entityName", ticker)
            return json.dumps({"company": company_name, "cik": cik, "facts": extracted}, default=str)
        except Exception as e:
            return json.dumps({"error": str(e), "ticker": ticker, "facts": {}})

    def analyze(self, ticker: str, filing_context: str | None = None) -> FilingsSummary:
        """Run filings analysis for ticker. Returns FilingsSummary."""
        if filing_context is None:
            try:
                bundle = filing_retrieval.get_agent_filing_context(
                    ticker,
                    profile_name="filings",
                    include_10k=True,
                    ten_q_limit=2,
                )
                filing_context = filing_retrieval.render_filing_context(bundle, max_chars=30_000)
            except Exception:
                filing_context = edgar_client.get_10k_text(ticker, max_chars=30_000) or ""

        prompt = f"""Analyze the SEC filings for {ticker.upper()}.

Steps:
1. Call get_company_facts to retrieve XBRL financial data (revenue, EPS, cash, debt series)
2. Read the curated filing context below, prioritising notes to financial statements first and MD&A second
3. Use the latest 2 quarterlies to identify what changed since year-end
4. Compute revenue CAGR, margin trends, FCF yield, and net debt/EBITDA from the XBRL data
5. Identify any accounting anomalies or red flags from both the numbers and the filing context
6. Summarize management guidance from the annual + latest 2 quarterly filings

Return your analysis as a JSON object with these exact fields:
{{
  "revenue_cagr_3y": <float, e.g. 0.12 for 12%>,
  "gross_margin_avg": <float>,
  "ebit_margin_avg": <float>,
  "fcf_yield": <float or null>,
  "net_debt_to_ebitda": <float or null>,
  "revenue_trend": "<accelerating|stable|decelerating>",
  "margin_trend": "<expanding|stable|contracting>",
  "red_flags": ["<flag 1>", ...],
  "notes_watch_items": ["<note-derived watch item>", ...],
  "recent_quarter_updates": ["<what changed in latest 2 quarterlies>", ...],
  "management_guidance": "<brief narrative>",
  "raw_summary": "<2-3 paragraph qualitative analysis>"
}}

Curated filing context:
{filing_context}"""

        try:
            raw = self.run(prompt)
        except Exception as e:
            return FilingsSummary(raw_summary=f"FilingsAgent LLM error: {e}")

        try:
            data = BaseAgent.extract_json(raw)
            return FilingsSummary(**data)
        except Exception:
            return FilingsSummary(raw_summary=raw[:2000] if raw else "")
