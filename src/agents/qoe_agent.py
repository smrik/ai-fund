"""
QoEAgent — quality of earnings normalization from 10-K text.
"""

import json
from typing import Any

from src.agents.base_agent import BaseAgent
from src.data import edgar_client


SYSTEM_PROMPT = """You are a buy-side accounting analyst focused on quality-of-earnings (QoE).
Identify one-time or non-core items and normalize reported EBIT.
Return only valid JSON and use this exact schema:
{
  \"normalized_ebit\": <float>,
  \"reported_ebit\": <float>,
  \"adjustments\": [
    {
      \"item\": <string>,
      \"amount\": <float>,
      \"direction\": \"+\" or \"-\",
      \"rationale\": <string>
    }
  ],
  \"confidence\": \"high\" | \"medium\" | \"low\",
  \"data_source\": <string>
}
"""


class QoEAgent(BaseAgent):
    def __init__(self):
        super().__init__()
        self.name = "QoEAgent"
        self.system_prompt = SYSTEM_PROMPT

    def _fallback(self, reported_ebit: float, data_source: str) -> dict:
        value = float(reported_ebit)
        return {
            "normalized_ebit": value,
            "reported_ebit": value,
            "adjustments": [],
            "confidence": "low",
            "data_source": data_source,
        }

    @staticmethod
    def _parse_adjustments(raw_adjustments: Any) -> list[dict]:
        if not isinstance(raw_adjustments, list):
            return []

        parsed = []
        for adj in raw_adjustments:
            if not isinstance(adj, dict):
                continue

            try:
                amount = float(adj.get("amount", 0.0))
            except (TypeError, ValueError):
                amount = 0.0

            direction = adj.get("direction", "+")
            if direction not in {"+", "-"}:
                direction = "+" if amount >= 0 else "-"

            parsed.append(
                {
                    "item": str(adj.get("item", "")),
                    "amount": float(abs(amount)),
                    "direction": direction,
                    "rationale": str(adj.get("rationale", "")),
                }
            )

        return parsed

    def _build_contract(self, parsed: dict, reported_ebit: float, data_source: str) -> dict:
        try:
            normalized_ebit = float(parsed.get("normalized_ebit", reported_ebit))
        except (TypeError, ValueError):
            normalized_ebit = float(reported_ebit)

        try:
            reported_value = float(parsed.get("reported_ebit", reported_ebit))
        except (TypeError, ValueError):
            reported_value = float(reported_ebit)

        confidence = parsed.get("confidence", "low")
        if confidence not in {"high", "medium", "low"}:
            confidence = "low"

        source = parsed.get("data_source", data_source)
        if not isinstance(source, str) or not source.strip():
            source = data_source

        return {
            "normalized_ebit": normalized_ebit,
            "reported_ebit": reported_value,
            "adjustments": self._parse_adjustments(parsed.get("adjustments", [])),
            "confidence": confidence,
            "data_source": source,
        }

    def analyze(self, ticker: str, reported_ebit: float, filing_text: str | None = None) -> dict:
        source = "provided_10k_text"
        filing = filing_text

        if filing is None:
            source = "sec_edgar_10k"
            filing = edgar_client.get_10k_text(ticker)

        filing_block = filing if filing else "No 10-K text available. Use conservative assumptions."

        prompt = f"""Ticker: {ticker.upper()}
Reported EBIT: {float(reported_ebit)}

10-K excerpt:
{filing_block}

Task:
1. Identify one-time or non-core EBIT items.
2. Provide signed adjustments with a rationale for each.
3. Compute normalized EBIT from reported EBIT + adjustments.
4. Return only JSON with the exact required schema.
"""

        try:
            raw = self.run(prompt)
            start = raw.find("{")
            end = raw.rfind("}") + 1
            if start == -1 or end <= start:
                raise ValueError("No JSON object in model response")

            parsed = json.loads(raw[start:end])
            if not isinstance(parsed, dict):
                raise ValueError("Response JSON is not an object")

            return self._build_contract(parsed, reported_ebit=reported_ebit, data_source=source)
        except Exception:
            return self._fallback(reported_ebit=reported_ebit, data_source=f"{source}_fallback")
