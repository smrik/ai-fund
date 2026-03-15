"""
AccountingRecastAgent — LLM-assisted accounting adjustment proposal engine.

This agent lives in the judgment layer. It may propose EBIT normalization items
and EV-to-equity bridge classifications, but it never mutates deterministic
valuation inputs directly.
"""

from __future__ import annotations

from typing import Any

from src.stage_00_data import edgar_client, filing_retrieval
from src.stage_03_judgment.base_agent import BaseAgent


SYSTEM_PROMPT = """You are a buy-side accounting analyst preparing a company for intrinsic valuation.

Your job is to read filing narrative / notes and propose:
1. one-time or non-core income statement adjustments that affect normalized EBIT
2. balance-sheet / EV bridge classifications:
   - operating assets
   - operating liabilities
   - non-operating assets
   - financing liabilities
   - equity claims

You are advisory only. Do not say anything about auto-applying changes.
Return ONLY valid JSON with this schema:
{
  "confidence": "high" | "medium" | "low",
  "income_statement_adjustments": [
    {
      "item": <string>,
      "amount": <float or null>,
      "classification": "non_recurring_expense" | "non_recurring_gain" | "non_core" | "unclear",
      "proposed_ebit_direction": "+" | "-" | "none",
      "rationale": <string>,
      "citation_text": <string or null>
    }
  ],
  "balance_sheet_reclassifications": [
    {
      "line_item": <string>,
      "reported_value": <float or null>,
      "classification": "operating_asset" | "operating_liability" | "non_operating_asset" | "financing_liability" | "equity_claim" | "unclear",
      "proposed_driver_field": "non_operating_assets" | "lease_liabilities" | "minority_interest" | "preferred_equity" | "pension_deficit" | null,
      "rationale": <string>,
      "citation_text": <string or null>
    }
  ],
  "override_candidates": {
    "normalized_ebit": <float or null>,
    "non_operating_assets": <float or null>,
    "lease_liabilities": <float or null>,
    "minority_interest": <float or null>,
    "preferred_equity": <float or null>,
    "pension_deficit": <float or null>
  },
  "pm_review_notes": <string>
}
"""

_ADJUSTMENT_CLASSES = {"non_recurring_expense", "non_recurring_gain", "non_core", "unclear"}
_EBIT_DIRECTIONS = {"+", "-", "none"}
_BS_CLASSES = {
    "operating_asset",
    "operating_liability",
    "non_operating_asset",
    "financing_liability",
    "equity_claim",
    "unclear",
}
_DRIVER_FIELDS = {
    None,
    "non_operating_assets",
    "lease_liabilities",
    "minority_interest",
    "preferred_equity",
    "pension_deficit",
}
_OVERRIDE_KEYS = (
    "normalized_ebit",
    "non_operating_assets",
    "lease_liabilities",
    "minority_interest",
    "preferred_equity",
    "pension_deficit",
)


class AccountingRecastAgent(BaseAgent):
    def __init__(self):
        super().__init__()
        self.name = "AccountingRecastAgent"
        self.system_prompt = SYSTEM_PROMPT
        self.tools = []
        self.tool_handlers = {}

    @staticmethod
    def _to_float(value: Any) -> float | None:
        if value in (None, ""):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _parse_income_statement_adjustments(raw: Any) -> list[dict]:
        if not isinstance(raw, list):
            return []
        parsed: list[dict] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            classification = item.get("classification", "unclear")
            if classification not in _ADJUSTMENT_CLASSES:
                classification = "unclear"
            direction = item.get("proposed_ebit_direction", "none")
            if direction not in _EBIT_DIRECTIONS:
                direction = "none"
            parsed.append(
                {
                    "item": str(item.get("item", "")),
                    "amount": AccountingRecastAgent._to_float(item.get("amount")),
                    "classification": classification,
                    "proposed_ebit_direction": direction,
                    "rationale": str(item.get("rationale", "")),
                    "citation_text": str(item.get("citation_text")) if item.get("citation_text") else None,
                }
            )
        return parsed

    @staticmethod
    def _parse_balance_sheet_reclassifications(raw: Any) -> list[dict]:
        if not isinstance(raw, list):
            return []
        parsed: list[dict] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            classification = item.get("classification", "unclear")
            if classification not in _BS_CLASSES:
                classification = "unclear"
            driver_field = item.get("proposed_driver_field")
            if driver_field not in _DRIVER_FIELDS:
                driver_field = None
            parsed.append(
                {
                    "line_item": str(item.get("line_item", "")),
                    "reported_value": AccountingRecastAgent._to_float(item.get("reported_value")),
                    "classification": classification,
                    "proposed_driver_field": driver_field,
                    "rationale": str(item.get("rationale", "")),
                    "citation_text": str(item.get("citation_text")) if item.get("citation_text") else None,
                }
            )
        return parsed

    @staticmethod
    def _parse_override_candidates(raw: Any) -> dict:
        payload = raw if isinstance(raw, dict) else {}
        return {key: AccountingRecastAgent._to_float(payload.get(key)) for key in _OVERRIDE_KEYS}

    def _fallback(self, ticker: str, source: str) -> dict:
        return {
            "ticker": ticker.upper(),
            "source": source,
            "confidence": "low",
            "income_statement_adjustments": [],
            "balance_sheet_reclassifications": [],
            "override_candidates": {key: None for key in _OVERRIDE_KEYS},
            "approval_required": True,
            "pm_review_notes": (
                "No reliable filing-based recast proposal available. "
                "Review manually before adding any overrides."
            ),
        }

    def _parse_response(self, ticker: str, raw: str, source: str) -> dict:
        data = self.extract_json(raw)
        confidence = data.get("confidence", "low")
        if confidence not in {"high", "medium", "low"}:
            confidence = "low"
        return {
            "ticker": ticker.upper(),
            "source": source,
            "confidence": confidence,
            "income_statement_adjustments": self._parse_income_statement_adjustments(
                data.get("income_statement_adjustments")
            ),
            "balance_sheet_reclassifications": self._parse_balance_sheet_reclassifications(
                data.get("balance_sheet_reclassifications")
            ),
            "override_candidates": self._parse_override_candidates(data.get("override_candidates")),
            "approval_required": True,
            "pm_review_notes": str(data.get("pm_review_notes", "")),
        }

    def analyze(
        self,
        ticker: str,
        reported_ebit: float | None = None,
        filing_text: str | None = None,
    ) -> dict:
        ticker = ticker.upper().strip()
        source = "provided_filing_text"
        if filing_text is None:
            try:
                bundle = filing_retrieval.get_agent_filing_context(
                    ticker,
                    profile_name="accounting_recast",
                    include_10k=True,
                    ten_q_limit=2,
                )
                filing_text = filing_retrieval.render_filing_context(bundle, max_chars=40_000)
                source = "sec_edgar_filing_context"
            except Exception:
                filing_text = edgar_client.get_10k_text(ticker, max_chars=40_000)
                source = "sec_edgar_10k"

        if not filing_text:
            return self._fallback(ticker, source="fallback")

        prompt = (
            f"Ticker: {ticker}\n"
            f"Reported EBIT: {reported_ebit if reported_ebit is not None else 'unknown'}\n\n"
            "Review the filing excerpt below and propose accounting recast items relevant to intrinsic valuation.\n"
            "Prioritize notes to financial statements first, then MD&A.\n"
            "Use citations that refer to the retrieved section label and filing date when possible.\n"
            "Only identify items with a specific valuation rationale. Do not invent amounts.\n\n"
            f"Filing excerpt:\n{filing_text[:40_000]}\n"
        )
        try:
            raw = self.run(prompt)
            return self._parse_response(ticker, raw, source=source)
        except Exception:
            return self._fallback(ticker, source=f"{source}_fallback")


def build_accounting_recast_context(result: dict) -> str:
    """Compact human-readable summary for memo synthesis and terminal output."""
    if not result:
        return ""

    lines = [
        f"Accounting recast confidence: {result.get('confidence', 'low')}",
        "Accounting recast is advisory only; PM approval required before any override is added to valuation_overrides.yaml.",
    ]

    adjustments = result.get("income_statement_adjustments") or []
    if adjustments:
        rendered = []
        for item in adjustments[:3]:
            direction = item.get("proposed_ebit_direction", "none")
            amount = item.get("amount")
            amount_text = f"${amount/1e6:.1f}mm" if isinstance(amount, (int, float)) else "amount unclear"
            rendered.append(f"{item.get('item', 'Unknown item')} ({direction} {amount_text})")
        lines.append("Income statement adjustments: " + "; ".join(rendered))

    reclasses = result.get("balance_sheet_reclassifications") or []
    if reclasses:
        rendered = []
        for item in reclasses[:4]:
            rendered.append(
                f"{item.get('line_item', 'Unknown line item')} -> "
                f"{item.get('classification', 'unclear')}"
                + (
                    f" [{item.get('proposed_driver_field')}]"
                    if item.get("proposed_driver_field")
                    else ""
                )
            )
        lines.append("Balance-sheet reclassifications: " + "; ".join(rendered))

    notes = result.get("pm_review_notes")
    if notes:
        lines.append("PM review notes: " + notes)
    return "\n".join(lines)
