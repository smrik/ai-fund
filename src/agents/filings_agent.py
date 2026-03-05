"""
FilingsAgent — parses SEC 10-K and 10-Q filings.
Extracts revenue trends, margins, FCF, debt, guidance, and red flags.
Returns a FilingsSummary.
"""

import json
from src.agents.base_agent import BaseAgent
from src.data import edgar_client
from src.templates.ic_memo import FilingsSummary


SYSTEM_PROMPT = """You are a senior equity research analyst specializing in fundamental analysis of SEC filings.
Your job is to extract and analyse financial data from 10-K and 10-Q filings.

Focus on:
1. Revenue trend and CAGR — is growth accelerating, stable, or decelerating?
2. Gross and EBIT margin trajectory — is the business becoming more or less profitable?
3. Free cash flow generation and FCF yield relative to market cap
4. Balance sheet health — net debt / EBITDA, interest coverage
5. Management guidance vs actuals — are they sandbagging or missing?
6. Accounting red flags — revenue recognition changes, rising DSOs, accruals vs cash divergence
7. Key business drivers from MD&A section

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
            self._tool(
                name="get_recent_10k_filings",
                description="Return metadata for the most recent 10-K annual filings for the given ticker.",
                properties={
                    "ticker": {"type": "string"},
                    "limit": {"type": "integer", "description": "Number of filings to return, default 3"},
                },
                required=["ticker"],
            ),
            self._tool(
                name="get_recent_10q_filings",
                description="Return metadata for the most recent 10-Q quarterly filings for the given ticker.",
                properties={
                    "ticker": {"type": "string"},
                    "limit": {"type": "integer", "description": "Number of filings to return, default 4"},
                },
                required=["ticker"],
            ),
        ]

        self.tool_handlers = {
            "get_company_facts": self._handle_company_facts,
            "get_recent_10k_filings": self._handle_10k,
            "get_recent_10q_filings": self._handle_10q,
        }

    def _handle_company_facts(self, inp: dict) -> str:
        ticker = inp["ticker"]
        cik = edgar_client.get_cik(ticker)
        facts = edgar_client.get_company_facts(cik)
        extracted = edgar_client.extract_financial_facts(facts)
        company_name = facts.get("entityName", ticker)
        return json.dumps({"company": company_name, "cik": cik, "facts": extracted}, default=str)

    def _handle_10k(self, inp: dict) -> str:
        ticker = inp["ticker"]
        limit = inp.get("limit", 3)
        cik = edgar_client.get_cik(ticker)
        filings = edgar_client.get_recent_filings(cik, "10-K", limit)
        return json.dumps(filings)

    def _handle_10q(self, inp: dict) -> str:
        ticker = inp["ticker"]
        limit = inp.get("limit", 4)
        cik = edgar_client.get_cik(ticker)
        filings = edgar_client.get_recent_filings(cik, "10-Q", limit)
        return json.dumps(filings)

    def analyze(self, ticker: str) -> FilingsSummary:
        """Run filings analysis for ticker. Returns FilingsSummary."""
        prompt = f"""Analyze the SEC filings for {ticker.upper()}.

Steps:
1. Call get_company_facts to retrieve XBRL financial data
2. Call get_recent_10k_filings to see recent annual filings
3. Call get_recent_10q_filings to see recent quarterly filings
4. Compute revenue CAGR, margin trends, FCF yield, and net debt/EBITDA
5. Identify any accounting anomalies or red flags
6. Summarize management guidance from the most recent filings

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
  "management_guidance": "<brief narrative>",
  "raw_summary": "<2-3 paragraph qualitative analysis>"
}}"""

        raw = self.run(prompt)

        # Parse JSON from Claude's response
        try:
            start = raw.find("{")
            end = raw.rfind("}") + 1
            data = json.loads(raw[start:end])
            return FilingsSummary(**data)
        except Exception:
            return FilingsSummary(raw_summary=raw)
