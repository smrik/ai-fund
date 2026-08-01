"""
ValuationAgent — judgment-layer adapter over deterministic valuation output.

Architecture rule:
- All valuation numbers come from src.stage_02_valuation (deterministic compute layer).
- This class may add narrative context in the future, but it must never generate
  numeric intrinsic values via LLM.
"""

from __future__ import annotations

import json
import os
from src.contracts.evidence_packet import EvidencePacket, EvidencePacketObservation
from src.stage_03_judgment.base_agent import BaseAgent
from src.stage_03_judgment.agentic_observations import analyze_evidence_packet_with_agent
from src.stage_02_valuation.batch_runner import value_single_ticker
from src.stage_02_valuation.templates.ic_memo import FilingsSummary, ValuationRange
from src.utils import safe_float



class ValuationAgent(BaseAgent):
    """Judgment-layer wrapper that exposes deterministic valuation output."""

    def __init__(self):
        super().__init__(role="valuation")
        self.name = "ValuationAgent"
        self.system_prompt = (
            "Deterministic valuation adapter. Numeric outputs must come from "
            "src.stage_02_valuation only."
        )
        self.tools = []
        self.tool_handlers = {}

    @staticmethod
    def _blocked_range(
        *,
        reason_code: str,
        message: str,
        blocker: dict | None = None,
        current_price: float | None = None,
    ) -> ValuationRange:
        return ValuationRange(
            current_price=current_price,
            valuation_status="blocked",
            valuation_output_mode="none",
            blocker=blocker
            or {
                "status": "blocked",
                "reason_code": reason_code,
                "message": message,
            },
        )

    def analyze(
        self, ticker: str, filings_summary: FilingsSummary | None = None
    ) -> ValuationRange:
        """
        Return deterministic bear/base/bull values for the ticker.

        Note: filings_summary is accepted for interface compatibility with the
        orchestrator but is not used to mutate numeric outputs here.
        """
        _ = filings_summary  # Explicitly unused in deterministic path.

        ticker = ticker.upper().strip()
        data = value_single_ticker(ticker)
        if not data:
            return self._blocked_range(
                reason_code="deterministic_valuation_unavailable",
                message=(
                    f"Deterministic valuation produced no result for {ticker}."
                ),
            )

        status = str(data.get("valuation_status") or "provisional")
        output_mode = str(
            data.get("valuation_output_mode") or "shadow_preview"
        )
        price = safe_float(data.get("price"))
        if status == "blocked":
            blocker = None
            raw_blocker = data.get("valuation_blocker_json")
            if isinstance(raw_blocker, str) and raw_blocker:
                try:
                    parsed = json.loads(raw_blocker)
                    blocker = parsed if isinstance(parsed, dict) else None
                except json.JSONDecodeError:
                    blocker = None
            return self._blocked_range(
                reason_code="deterministic_valuation_blocked",
                message=(
                    f"Deterministic valuation is blocked for {ticker}."
                ),
                blocker=blocker,
                current_price=price,
            )

        bear = safe_float(data.get("iv_bear"))
        base = safe_float(data.get("iv_base"))
        bull = safe_float(data.get("iv_bull"))

        if bear is None or base is None or bull is None:
            return self._blocked_range(
                reason_code="deterministic_valuation_incomplete",
                message=(
                    "Deterministic valuation did not produce all bear/base/"
                    f"bull values for {ticker}."
                ),
                current_price=price,
            )

        upside_pct_base = safe_float(data.get("upside_base_pct"))
        if upside_pct_base is None:
            upside_decimal = (
                (base / price) - 1.0
                if price is not None and price > 0
                else None
            )
        else:
            upside_decimal = upside_pct_base / 100.0

        return ValuationRange(
            bear=bear,
            base=base,
            bull=bull,
            current_price=price,
            upside_pct_base=upside_decimal,
            valuation_status=status,
            valuation_output_mode=output_mode,
        )

    def analyze_evidence_packet(
        self,
        packet: EvidencePacket,
        profile_name: str = "valuation_review",
    ) -> list[EvidencePacketObservation]:
        return analyze_evidence_packet_with_agent(
            agent=self,
            packet=packet,
            profile_name=profile_name,
        )
