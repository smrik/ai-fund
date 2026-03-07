"""
ValuationAgent — judgment-layer adapter over deterministic valuation output.

Architecture rule:
- All valuation numbers come from src.stage_02_valuation (deterministic compute layer).
- This class may add narrative context in the future, but it must never generate
  numeric intrinsic values via LLM.
"""

from __future__ import annotations

from src.stage_03_judgment.base_agent import BaseAgent
from src.stage_00_data import market_data as md_client
from src.stage_02_valuation.batch_runner import value_single_ticker
from src.stage_02_valuation.templates.ic_memo import FilingsSummary, ValuationRange


class ValuationAgent(BaseAgent):
    """Judgment-layer wrapper that exposes deterministic valuation output."""

    def __init__(self):
        super().__init__()
        self.name = "ValuationAgent"
        self.system_prompt = (
            "Deterministic valuation adapter. Numeric outputs must come from "
            "src.stage_02_valuation only."
        )
        self.tools = []
        self.tool_handlers = {}

    @staticmethod
    def _safe_float(value) -> float | None:
        try:
            if value is None:
                return None
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _fallback_range(ticker: str) -> ValuationRange:
        mkt = md_client.get_market_data(ticker)
        price = float(mkt.get("current_price") or 0)
        return ValuationRange(
            bear=price * 0.70,
            base=price,
            bull=price * 1.30,
            current_price=price,
            upside_pct_base=0.0,
        )

    def analyze(self, ticker: str, filings_summary: FilingsSummary | None = None) -> ValuationRange:
        """
        Return deterministic bear/base/bull values for the ticker.

        Note: filings_summary is accepted for interface compatibility with the
        orchestrator but is not used to mutate numeric outputs here.
        """
        _ = filings_summary  # Explicitly unused in deterministic path.

        ticker = ticker.upper().strip()
        data = value_single_ticker(ticker)
        if not data:
            return self._fallback_range(ticker)

        bear = self._safe_float(data.get("iv_bear"))
        base = self._safe_float(data.get("iv_base"))
        bull = self._safe_float(data.get("iv_bull"))
        price = self._safe_float(data.get("price")) or 0.0

        if bear is None or base is None or bull is None:
            return self._fallback_range(ticker)

        upside_pct_base = self._safe_float(data.get("upside_base_pct"))
        if upside_pct_base is None:
            upside_decimal = ((base / price) - 1.0) if price > 0 else 0.0
        else:
            upside_decimal = upside_pct_base / 100.0

        return ValuationRange(
            bear=bear,
            base=base,
            bull=bull,
            current_price=price,
            upside_pct_base=upside_decimal,
        )
