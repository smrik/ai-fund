"""
AccountingRecastAgent — LLM-assisted accounting adjustment proposal engine.

This agent lives in the judgment layer. It may propose EBIT normalization items
and EV-to-equity bridge classifications, but it never mutates deterministic
valuation inputs directly.
"""

from __future__ import annotations

import os
from typing import Any

from src.stage_00_data import edgar_client, filing_retrieval
from src.stage_03_judgment.base_agent import BaseAgent
from src.stage_04_pipeline.agentic_handoff_profiles import (
    AGENT_PROPOSABLE_ASSUMPTION_FIELDS,
)


SYSTEM_PROMPT = """You are a buy-side accounting analyst preparing a company for intrinsic valuation.

Your job is to read filing narrative / notes and propose:
1. one-time or non-core income statement adjustments that affect normalized EBIT
2. identity-only balance-sheet / EV bridge reclassifications
3. forward-looking driver values that the accounting evidence actually supports — growth,
   margin, capex/D&A intensity, tax rate, terminal assumptions, WACC, share count
4. any other financially sound model change relevant to the DCF or comps, even when
   the current deterministic model has no matching driver yet

Use reclassify for every historical balance-sheet or EV-bridge treatment. A
reclassification identifies a reported line and its treatment; it never supplies
an amount. Deterministic code derives the amount from the claim ledger.

Use driver_proposals only for genuinely forward-looking assumptions that have no
reported balance-sheet line to consume. If you cannot support a specific forward
value, do not invent one — use model_change_proposals or say so.

You are advisory only. Do not say anything about auto-applying changes.
Reconcile every proposed bridge item against the supplied exact-once claim ledger.
Never author a historical bridge amount. If a stable reported-line identity is
unavailable, describe the uncertainty in model_change_proposals instead.
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
  "reclassify": [
    {
      "reported_line": <stable reported-line ID from the supplied claim ledger>,
      "from_component": "unclaimed" | "net_debt" | "non_operating_assets" | "lease_liabilities" | "minority_interest" | "preferred_equity" | "pension_deficit" | "options_value" | "convertibles_value",
      "to_component": "net_debt" | "non_operating_assets" | "lease_liabilities" | "minority_interest" | "preferred_equity" | "pension_deficit" | "options_value" | "convertibles_value",
      "rationale": <string>,
      "citation_text": <string or null>
    }
  ],
  "driver_proposals": [
    {
      "driver_field": one of DRIVER_FIELDS below,
      "proposed_value": <float>,
      "direction": "up" | "down" | "none",
      "rationale": <string>,
      "citation_text": <string or null>
    }
  ],
  "model_change_proposals": [
    {
      "proposal": <string>,
      "valuation_effect": <string>,
      "reasoning": <string>,
      "citation_text": <string or null>,
      "implementation_status": <string>
    }
  ],
  "pm_review_notes": <string>
}

FORWARD DRIVER_FIELDS (the only values allowed in driver_proposals[].driver_field):
revenue_growth_near, revenue_growth_mid, ebit_margin_start, ebit_margin_target,
exit_multiple, terminal_growth, ronic_terminal, wacc, capex_pct_start, capex_pct_target,
da_pct_start, da_pct_target, tax_rate_start, tax_rate_target, shares_outstanding

Rates and margins are decimal fractions (0.44 means 44%). Monetary amounts are absolute USD.
"""

_ADJUSTMENT_CLASSES = {
    "non_recurring_expense",
    "non_recurring_gain",
    "non_core",
    "unclear",
}
_EBIT_DIRECTIONS = {"+", "-", "none"}
# Driver proposals reach the full PM-proposable set. Restricting the judgment layer to
# EV-bridge claims left every forward-looking driver to sector constants, which is the
# failure Vision Decision 13 names. The queue still gates every mutation.
_BRIDGE_COMPONENTS = frozenset(
    {
        "net_debt",
        "non_operating_assets",
        "lease_liabilities",
        "minority_interest",
        "preferred_equity",
        "pension_deficit",
        "options_value",
        "convertibles_value",
    }
)
_RECLASSIFICATION_FROM_COMPONENTS = _BRIDGE_COMPONENTS | {"unclaimed"}
_PROPOSABLE_DRIVER_FIELDS = frozenset(AGENT_PROPOSABLE_ASSUMPTION_FIELDS) - _BRIDGE_COMPONENTS
DEFAULT_ACCOUNTING_RECAST_MODEL = "gemini-3-flash-preview"


DISCOVERY_SYSTEM_PROMPT = """You are a senior buy-side accounting and valuation analyst.

Your task is discovery, not final classification. Review the complete filing-section inventory
plus the business, industry, quantitative, and current-model context. Identify company-specific
questions that deserve focused evidence retrieval before forecasting, DCF, and comps.

Do not limit discovery to a predefined adjustment taxonomy. Anything financially sound may be
raised: historical recasts, accounting-policy comparability, operating-versus-financing
classification, capitalized-versus-expensed investment, non-recurring items, contingent claims,
segment economics, or a model change that the current schema cannot represent.

Do not conclude that an adjustment is warranted from a heading or preview alone. Request the
specific sections and search terms needed to test each question. Use only section IDs present in
the supplied inventory. Return zero questions if the inventory and context do not support a
useful lead.

Return ONLY valid JSON:
{
  "discovery_summary": <string>,
  "questions": [
    {
      "question_id": <stable snake_case string>,
      "question": <specific accounting/valuation question>,
      "why_it_matters": <forecast, DCF, comps, or model effect>,
      "requested_section_ids": [<exact inventory section_id>, ...],
      "search_terms": [<targeted term or phrase>, ...],
      "possible_model_implications": [<open-ended string>, ...],
      "priority": "high" | "medium" | "low"
    }
  ],
  "coverage_notes": [<limits, missing evidence, or reasons not to infer an adjustment>, ...]
}
"""


class AccountingDiscoveryAgent(BaseAgent):
    def __init__(self):
        super().__init__(
            model=os.getenv(
                "ACCOUNTING_DISCOVERY_AGENT_MODEL",
                os.getenv(
                    "ACCOUNTING_RECAST_AGENT_MODEL",
                    DEFAULT_ACCOUNTING_RECAST_MODEL,
                ),
            )
        )
        self.name = "AccountingDiscoveryAgent"
        self.system_prompt = DISCOVERY_SYSTEM_PROMPT
        self.tools = []
        self.tool_handlers = {}

    @staticmethod
    def _strings(value: Any, *, limit: int) -> list[str]:
        if not isinstance(value, list):
            return []
        values = [str(item).strip() for item in value if str(item).strip()]
        return list(dict.fromkeys(values))[:limit]

    def _fallback(self, ticker: str, reason: str) -> dict[str, Any]:
        return {
            "ticker": ticker,
            "source": "fallback",
            "discovery_summary": "Accounting discovery did not produce a usable result.",
            "questions": [],
            "coverage_notes": [reason],
        }

    def _parse_response(
        self,
        ticker: str,
        raw: str,
        *,
        available_section_ids: set[str],
    ) -> dict[str, Any]:
        data = self.extract_json(raw)
        if not isinstance(data, dict):
            raise ValueError("Accounting discovery response is not a JSON object")

        questions: list[dict[str, Any]] = []
        for index, item in enumerate(data.get("questions") or []):
            if not isinstance(item, dict):
                continue
            question = str(item.get("question") or "").strip()
            why_it_matters = str(item.get("why_it_matters") or "").strip()
            if not question or not why_it_matters:
                continue
            requested = self._strings(
                item.get("requested_section_ids"),
                limit=20,
            )
            valid = [
                section_id
                for section_id in requested
                if section_id in available_section_ids
            ]
            invalid = [
                section_id
                for section_id in requested
                if section_id not in available_section_ids
            ]
            priority = str(item.get("priority") or "medium").strip().lower()
            if priority not in {"high", "medium", "low"}:
                priority = "medium"
            question_id = str(
                item.get("question_id") or f"discovery_question_{index + 1}"
            ).strip()
            questions.append(
                {
                    "question_id": question_id,
                    "question": question,
                    "why_it_matters": why_it_matters,
                    "requested_section_ids": valid,
                    "invalid_section_ids": invalid,
                    "search_terms": self._strings(
                        item.get("search_terms"),
                        limit=16,
                    ),
                    "possible_model_implications": self._strings(
                        item.get("possible_model_implications"),
                        limit=12,
                    ),
                    "priority": priority,
                }
            )

        return {
            "ticker": ticker,
            "source": "section_inventory",
            "discovery_summary": str(
                data.get("discovery_summary") or ""
            ).strip(),
            "questions": questions[:12],
            "coverage_notes": self._strings(
                data.get("coverage_notes"),
                limit=20,
            ),
        }

    def discover(
        self,
        ticker: str,
        *,
        section_inventory: list[dict[str, Any]],
        business_context: str,
        industry_context: str,
        quantitative_context: str,
        current_model_context: str,
    ) -> dict[str, Any]:
        ticker = ticker.upper().strip()
        if not section_inventory:
            return self._fallback(ticker, "No filing-section inventory was available.")

        inventory_text = filing_retrieval.render_accounting_section_inventory(
            section_inventory
        )
        prompt = (
            f"Ticker: {ticker}\n\n"
            f"Business analysis context:\n{business_context[:8_000] or 'not provided'}\n\n"
            f"Industry analysis context:\n{industry_context[:8_000] or 'not provided'}\n\n"
            f"Historical and current quantitative context:\n"
            f"{quantitative_context[:10_000] or 'not provided'}\n\n"
            f"Current deterministic model context and source lineage:\n"
            f"{current_model_context[:8_000] or 'not provided'}\n\n"
            "Complete filing-section inventory:\n"
            f"{inventory_text}\n\n"
            "Do not limit discovery to a predefined adjustment taxonomy. "
            "Use headings and previews only to request focused evidence; do not decide the "
            "accounting treatment yet."
        )
        try:
            raw = self.run(prompt)
            return self._parse_response(
                ticker,
                raw,
                available_section_ids={
                    str(item.get("section_id"))
                    for item in section_inventory
                    if item.get("section_id")
                },
            )
        except Exception as exc:
            return self._fallback(ticker, str(exc))


class AccountingRecastAgent(BaseAgent):
    def __init__(self):
        super().__init__(
            model=os.getenv(
                "ACCOUNTING_RECAST_AGENT_MODEL", DEFAULT_ACCOUNTING_RECAST_MODEL
            )
        )
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
                    "citation_text": str(item.get("citation_text"))
                    if item.get("citation_text")
                    else None,
                }
            )
        return parsed

    @staticmethod
    def _parse_driver_proposals(raw: Any) -> list[dict]:
        """Keep only proposals naming a proposable driver AND carrying a value.

        A driver name outside the proposable set is dropped rather than remapped onto a
        neighbouring field, and a proposal with no number is not a proposal.
        """

        if not isinstance(raw, list):
            return []
        parsed: list[dict] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            driver_field = str(item.get("driver_field") or "").strip()
            if driver_field not in _PROPOSABLE_DRIVER_FIELDS:
                continue
            value = AccountingRecastAgent._to_float(item.get("proposed_value"))
            if value is None:
                continue
            direction = str(item.get("direction") or "none").strip().lower()
            if direction not in {"up", "down", "none"}:
                direction = "none"
            parsed.append(
                {
                    "driver_field": driver_field,
                    "proposed_value": value,
                    "direction": direction,
                    "rationale": str(item.get("rationale", "")),
                    "citation_text": str(item.get("citation_text"))
                    if item.get("citation_text")
                    else None,
                }
            )
        return parsed

    @staticmethod
    def _parse_reclassifications(raw: Any) -> list[dict]:
        """Parse identity-only bridge treatments; agent-authored amounts are ignored."""

        if not isinstance(raw, list):
            return []
        parsed: list[dict] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            reported_line = str(item.get("reported_line") or "").strip()
            from_component = str(item.get("from_component") or "").strip()
            to_component = str(item.get("to_component") or "").strip()
            if (
                not reported_line
                or from_component not in _RECLASSIFICATION_FROM_COMPONENTS
                or to_component not in _BRIDGE_COMPONENTS
            ):
                continue
            parsed.append(
                {
                    "reported_line": reported_line,
                    "from_component": from_component,
                    "to_component": to_component,
                    "rationale": str(item.get("rationale") or ""),
                    "citation_text": (
                        str(item.get("citation_text"))
                        if item.get("citation_text")
                        else None
                    ),
                }
            )
        return parsed

    @staticmethod
    def _parse_model_change_proposals(raw: Any) -> list[dict]:
        if not isinstance(raw, list):
            return []
        return [
            {
                "proposal": str(item.get("proposal", "")),
                "valuation_effect": str(item.get("valuation_effect", "")),
                "reasoning": str(item.get("reasoning", "")),
                "citation_text": str(item.get("citation_text"))
                if item.get("citation_text")
                else None,
                "implementation_status": str(
                    item.get("implementation_status", "analysis_only")
                ),
            }
            for item in raw
            if isinstance(item, dict) and item.get("proposal")
        ]

    def _fallback(self, ticker: str, source: str) -> dict:
        return {
            "ticker": ticker.upper(),
            "source": source,
            "confidence": "low",
            "income_statement_adjustments": [],
            "reclassify": [],
            "driver_proposals": [],
            "model_change_proposals": [],
            "rejected_legacy_fields": [],
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
        rejected_legacy_fields = [
            key
            for key in (
                "balance_sheet_reclassifications",
                "override_candidates",
            )
            if key in data
        ]
        return {
            "ticker": ticker.upper(),
            "source": source,
            "confidence": confidence,
            "income_statement_adjustments": self._parse_income_statement_adjustments(
                data.get("income_statement_adjustments")
            ),
            "reclassify": self._parse_reclassifications(data.get("reclassify")),
            "driver_proposals": self._parse_driver_proposals(
                data.get("driver_proposals")
            ),
            "model_change_proposals": self._parse_model_change_proposals(
                data.get("model_change_proposals")
            ),
            "rejected_legacy_fields": rejected_legacy_fields,
            "approval_required": True,
            "pm_review_notes": str(data.get("pm_review_notes", "")),
        }

    def analyze(
        self,
        ticker: str,
        reported_ebit: float | None = None,
        filing_text: str | None = None,
        business_context: str = "",
        industry_context: str = "",
        quantitative_context: str = "",
        current_model_context: str = "",
        analysis_task: str = "",
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
                filing_text = filing_retrieval.render_filing_context(
                    bundle, max_chars=40_000
                )
                source = "sec_edgar_filing_context"
            except Exception:
                filing_text = edgar_client.get_10k_text(ticker, max_chars=40_000)
                source = "sec_edgar_10k"

        if not filing_text:
            return self._fallback(ticker, source="fallback")

        prompt = (
            f"Ticker: {ticker}\n"
            f"Reported EBIT: {reported_ebit if reported_ebit is not None else 'unknown'}\n\n"
            f"Business analysis context:\n{business_context[:6_000] or 'not provided'}\n\n"
            f"Industry analysis context:\n{industry_context[:6_000] or 'not provided'}\n\n"
            f"Quantitative context (reported history and packet facts):\n"
            f"{quantitative_context[:6_000] or 'not provided'}\n\n"
            f"Current deterministic model context:\n"
            f"{current_model_context[:4_000] or 'not provided'}\n\n"
            f"Specific discovery task:\n{analysis_task[:4_000] or 'general accounting recast review'}\n\n"
            "Review the filing excerpt below and propose accounting recast items relevant to intrinsic valuation.\n"
            "Prioritize notes to financial statements first, then MD&A.\n"
            "Do not limit proposals to existing model fields. Put financially sound but currently unsupported "
            "treatments in model_change_proposals for PM review.\n"
            "For a bridge treatment, use reclassify with a reported line ID "
            "from the supplied ledger. Never author a bridge amount.\n"
            "Return monetary amounts in absolute USD: multiply amounts reported in millions by 1,000,000 "
            "and amounts reported in thousands by 1,000.\n"
            "Use citations that refer to the retrieved section label and filing date when possible.\n"
            "Only identify items with a specific valuation rationale. Do not invent amounts.\n\n"
            f"Focused filing evidence:\n{filing_text[:24_000]}\n"
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
            amount_text = (
                f"${amount / 1e6:.1f}mm"
                if isinstance(amount, (int, float))
                else "amount unclear"
            )
            rendered.append(
                f"{item.get('item', 'Unknown item')} ({direction} {amount_text})"
            )
        lines.append("Income statement adjustments: " + "; ".join(rendered))

    reclasses = result.get("reclassify") or []
    if reclasses:
        rendered = []
        for item in reclasses[:4]:
            rendered.append(
                f"{item.get('reported_line', 'Unknown reported line')} "
                f"{item.get('from_component', 'unknown')} -> "
                f"{item.get('to_component', 'unknown')}"
            )
        lines.append("Balance-sheet reclassifications: " + "; ".join(rendered))

    proposals = result.get("model_change_proposals") or []
    if proposals:
        lines.append(
            "Other model implications: "
            + "; ".join(
                str(item.get("proposal", "Unspecified model change"))
                for item in proposals[:4]
            )
        )

    notes = result.get("pm_review_notes")
    if notes:
        lines.append("PM review notes: " + notes)
    return "\n".join(lines)
