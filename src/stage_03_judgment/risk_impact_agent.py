"""
RiskImpactAgent — converts qualitative risks into structured downside scenario overlays.
Advisory only. Does not mutate the deterministic valuation inputs.
"""

from __future__ import annotations

from src.stage_02_valuation.templates.ic_memo import RiskImpactOutput
from src.stage_03_judgment.base_agent import BaseAgent


SYSTEM_PROMPT = """You are a senior portfolio analyst translating qualitative research risks into downside valuation overlays.

Your job is to identify the 1-3 most important downside risks and convert each into a structured scenario overlay.
Each overlay must define:
- probability of occurrence
- time horizon
- downside-only shifts to key valuation drivers
- concise rationale tied to the provided evidence

Rules:
- This is advisory only. Do not change the base valuation.
- Use downside-only shifts in v1:
  - revenue growth shifts <= 0 bps
  - EBIT margin shifts <= 0 bps
  - WACC shifts >= 0 bps
  - exit multiple shifts <= 0 percent
- Keep the total probability across overlays <= 1.0
- Return at most 3 overlays
- Be specific and economically coherent. Avoid extreme values unless the evidence supports it.
"""


class RiskImpactAgent(BaseAgent):
    def __init__(self):
        super().__init__()
        self.name = "RiskImpactAgent"
        self.system_prompt = SYSTEM_PROMPT
        self.tools = []
        self.tool_handlers = {}

    def analyze(
        self,
        *,
        ticker: str,
        company_name: str,
        sector: str,
        filings_red_flags: list[str],
        management_guidance: str,
        earnings_key_themes: list[str],
        sentiment_risk_narratives: list[str],
        qoe_context: str,
        accounting_recast_context: str,
        valuation_context: str,
    ) -> RiskImpactOutput:
        prompt = f"""Assess the main downside valuation risks for {ticker.upper()} ({company_name}) in {sector}.

Inputs:
- Filings red flags: {filings_red_flags}
- Management guidance: {management_guidance}
- Earnings themes: {earnings_key_themes}
- Sentiment risk narratives: {sentiment_risk_narratives}
- QoE context: {qoe_context}
- Accounting recast context: {accounting_recast_context}
- Valuation context: {valuation_context}

Return JSON with this exact shape:
{{
  "overlays": [
    {{
      "risk_name": "<short name>",
      "source_type": "<thesis_key_risk|filings_red_flag|sentiment_risk_narrative|qoe|accounting_recast>",
      "source_text": "<short quoted source>",
      "probability": <float 0 to 1>,
      "horizon": "<12m|24m|36m>",
      "revenue_growth_near_bps": <int <= 0>,
      "revenue_growth_mid_bps": <int <= 0>,
      "ebit_margin_bps": <int <= 0>,
      "wacc_bps": <int >= 0>,
      "exit_multiple_pct": <float <= 0>,
      "rationale": "<1-2 sentence rationale>",
      "confidence": "<high|medium|low>"
    }}
  ],
  "raw_summary": "<2-4 sentence summary of aggregate downside risk>"
}}
"""

        try:
            raw = self.run(prompt)
        except Exception as exc:
            return RiskImpactOutput(raw_summary=f"RiskImpactAgent LLM error: {exc}")

        try:
            data = self.extract_json(raw)
            return RiskImpactOutput(**data)
        except Exception:
            return RiskImpactOutput(raw_summary=raw[:2000] if raw else "")
