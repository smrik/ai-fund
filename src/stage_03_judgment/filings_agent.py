"""
FilingsAgent — parses SEC 10-K and 10-Q filings.
Extracts revenue trends, margins, FCF, debt, guidance, and red flags.
Returns a FilingsSummary.
"""

import json
from src.stage_03_judgment.base_agent import BaseAgent
from src.stage_00_data import edgar_client
from src.stage_02_valuation.templates.ic_memo import FilingsSummary


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
                name="get_10k_text",
                description="Fetch the full text of the most recent 10-K annual report (MD&A, risk factors, business description). Use this to read management narrative, guidance, and qualitative disclosures.",
                properties={"ticker": {"type": "string"}},
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
            "get_10k_text": self._handle_10k_text,
            "get_recent_10q_filings": self._handle_10q,
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

    def _handle_10k_text(self, inp: dict) -> str:
        ticker = inp["ticker"]
        try:
            text = edgar_client.get_10k_text(ticker, max_chars=25_000)
            if not text:
                return json.dumps({"error": "No 10-K text retrieved", "ticker": ticker, "text": ""})
            return json.dumps({"ticker": ticker, "text": text})
        except Exception as e:
            return json.dumps({"error": str(e), "ticker": ticker, "text": ""})

    def _handle_10q(self, inp: dict) -> str:
        ticker = inp["ticker"]
        limit = inp.get("limit", 4)
        try:
            cik = edgar_client.get_cik(ticker)
            filings = edgar_client.get_recent_filings(cik, "10-Q", limit)
            return json.dumps(filings)
        except Exception as e:
            return json.dumps({"error": str(e), "ticker": ticker, "filings": []})

    def analyze(self, ticker: str) -> FilingsSummary:
        """Run filings analysis for ticker. Returns FilingsSummary."""
        prompt = f"""Analyze the SEC filings for {ticker.upper()}.

Steps:
1. Call get_company_facts to retrieve XBRL financial data (revenue, EPS, cash, debt series)
2. Call get_10k_text to read the actual 10-K text — focus on MD&A, risk factors, guidance, and segment disclosures
3. Call get_recent_10q_filings to see recent quarterly filing metadata
4. Compute revenue CAGR, margin trends, FCF yield, and net debt/EBITDA from the XBRL data
5. Identify any accounting anomalies or red flags from both the numbers and the MD&A narrative
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

        try:
            raw = self.run(prompt)
        except Exception as e:
            return FilingsSummary(raw_summary=f"FilingsAgent LLM error: {e}")

        try:
            data = BaseAgent.extract_json(raw)
            return FilingsSummary(**data)
        except Exception:
            return FilingsSummary(raw_summary=raw[:2000] if raw else "")
