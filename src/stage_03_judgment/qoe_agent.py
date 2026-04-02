"""
QoEAgent — Quality of Earnings analysis combining deterministic signals with LLM judgment.

Two-layer architecture:
  Layer 1 (deterministic): compute_qoe_signals() — Sloan accruals, cash conversion,
           NWC drift, Capex/DA. Fully auditable, no LLM.
  Layer 2 (LLM judgment):  read MD&A/10-K text, normalise EBIT, explain flagged signals,
           surface revenue recognition risks and auditor flags.

Output contract: see _build_full_output() for the canonical return structure.
The DCF valuation is NEVER updated automatically — normalized EBIT requires PM approval
via valuation_overrides.yaml when the haircut exceeds 10%.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from src.stage_03_judgment.base_agent import BaseAgent
from src.stage_03_judgment.qoe_signals import compute_qoe_signals
from src.stage_00_data import edgar_client, filing_retrieval
from src.stage_00_data import market_data as md_client
from src.stage_00_data.ciq_adapter import get_ciq_snapshot, get_ciq_nwc_history

_ROOT = Path(__file__).resolve().parent.parent.parent
QOE_PENDING_PATH = _ROOT / "config" / "qoe_pending.yaml"


SYSTEM_PROMPT = """You are a buy-side accounting analyst specialising in quality-of-earnings (QoE) analysis.

You will receive:
- The company ticker and reported EBIT
- Deterministic signals already computed (accruals ratio, cash conversion, NWC drift, Capex/DA)
- A 10-K excerpt (MD&A and Notes) — may be absent

Your job is to:
1. Identify and adjust for one-time or non-core EBIT items (restructuring, impairments, gains on
   asset sales, litigation settlements, acquisition costs, etc.)
2. For each flagged deterministic signal (amber or red), find management's explanation in the filing
   and assess whether it is credible
3. Flag any revenue recognition concerns visible in the MD&A or notes
4. Note auditor-related flags (going concern, material weakness, auditor change)
5. Write a 2-3 sentence plain-English PM summary

Return ONLY valid JSON with this exact schema — no markdown, no preamble:
{
  "normalized_ebit": <float>,
  "reported_ebit": <float>,
  "ebit_adjustments": [
    {
      "item": <string>,
      "amount": <float>,
      "direction": "+" or "-",
      "rationale": <string>
    }
  ],
  "signal_explanations": {
    "accruals": <string or null>,
    "cash_conversion": <string or null>,
    "dso": <string or null>,
    "dio": <string or null>,
    "dpo": <string or null>,
    "capex_da": <string or null>
  },
  "revenue_recognition_flags": [<string>],
  "auditor_flags": [<string>],
  "narrative_credibility": "high" | "medium" | "low",
  "confidence": "high" | "medium" | "low",
  "pm_summary": <string>
}

If no 10-K text is provided, still return the schema with null signal_explanations,
empty flags, narrative_credibility "low", confidence "low", and a pm_summary noting
that only deterministic signals are available.
"""


class QoEAgent(BaseAgent):
    def __init__(self):
        super().__init__()
        self.name = "QoEAgent"
        self.system_prompt = SYSTEM_PROMPT

    # ── LLM helpers ──────────────────────────────────────────────────────────

    @staticmethod
    def _parse_adjustments(raw: Any) -> list[dict]:
        if not isinstance(raw, list):
            return []
        parsed = []
        for adj in raw:
            if not isinstance(adj, dict):
                continue
            try:
                amount = float(adj.get("amount", 0.0))
            except (TypeError, ValueError):
                amount = 0.0
            direction = adj.get("direction", "+")
            if direction not in {"+", "-"}:
                direction = "+" if amount >= 0 else "-"
            parsed.append({
                "item": str(adj.get("item", "")),
                "amount": float(abs(amount)),
                "direction": direction,
                "rationale": str(adj.get("rationale", "")),
            })
        return parsed

    @staticmethod
    def _parse_signal_explanations(raw: Any) -> dict[str, str | None]:
        keys = {"accruals", "cash_conversion", "dso", "dio", "dpo", "capex_da"}
        if not isinstance(raw, dict):
            return {k: None for k in keys}
        return {k: (str(raw[k]) if raw.get(k) else None) for k in keys}

    def _parse_llm_response(self, raw: str, reported_ebit: float, source: str) -> dict:
        parsed = self.extract_json(raw)
        if not isinstance(parsed, dict):
            raise ValueError("Response is not a JSON object")

        try:
            normalized_ebit = float(parsed.get("normalized_ebit", reported_ebit))
        except (TypeError, ValueError):
            normalized_ebit = float(reported_ebit)

        confidence = parsed.get("confidence", "low")
        if confidence not in {"high", "medium", "low"}:
            confidence = "low"
        credibility = parsed.get("narrative_credibility", "low")
        if credibility not in {"high", "medium", "low"}:
            credibility = "low"

        return {
            "normalized_ebit": normalized_ebit,
            "reported_ebit": float(reported_ebit),
            "ebit_adjustments": self._parse_adjustments(parsed.get("ebit_adjustments", [])),
            "signal_explanations": self._parse_signal_explanations(parsed.get("signal_explanations")),
            "revenue_recognition_flags": [str(f) for f in (parsed.get("revenue_recognition_flags") or []) if f],
            "auditor_flags": [str(f) for f in (parsed.get("auditor_flags") or []) if f],
            "narrative_credibility": credibility,
            "confidence": confidence,
            "pm_summary": str(parsed.get("pm_summary", "")),
            "data_source": source,
        }

    def _llm_fallback(
        self,
        reported_ebit: float,
        source: str,
        det: dict,
        filing_text_available: bool,
    ) -> dict:
        """Fallback when LLM fails or no filing text — deterministic signals still flow."""
        n_red = sum(1 for v in det.get("signal_scores", {}).values() if v == "red")
        n_amber = sum(1 for v in det.get("signal_scores", {}).values() if v == "amber")
        review_status = (
            "filing text was available but LLM review failed or was unavailable"
            if filing_text_available
            else "no 10-K text available for LLM review"
        )
        pm_summary = (
            f"Deterministic signals only — {review_status}. "
            f"QoE score {det.get('qoe_score', '?')}/5 ({det.get('qoe_flag', '?')}): "
            f"{n_red} red signal(s), {n_amber} amber signal(s). "
            f"Management narrative not assessed."
        )
        return {
            "normalized_ebit": float(reported_ebit),
            "reported_ebit": float(reported_ebit),
            "ebit_adjustments": [],
            "signal_explanations": {k: None for k in {"accruals", "cash_conversion", "dso", "dio", "dpo", "capex_da"}},
            "revenue_recognition_flags": [],
            "auditor_flags": [],
            "narrative_credibility": None,
            "confidence": "low",
            "pm_summary": pm_summary,
            "data_source": source,
        }

    def _run_llm(
        self,
        ticker: str,
        reported_ebit: float,
        det: dict,
        filing_text: str | None,
        source: str,
    ) -> dict:
        """Build prompt, call LLM, parse result. Returns fallback on any failure."""
        # Summarise flagged signals for the prompt
        flagged = {k: v for k, v in det.get("signal_scores", {}).items() if v in {"amber", "red"}}
        signals_block = "\n".join(
            f"  {k}: {v.upper()} "
            f"(raw: {det.get(k.replace('dso', 'dso_drift').replace('dio', 'dio_drift').replace('dpo', 'dpo_drift').replace('accruals', 'sloan_accruals_ratio').replace('cash_conversion', 'cash_conversion').replace('capex_da', 'capex_da_ratio'))})"
            for k, v in flagged.items()
        ) or "  No signals flagged (all green or unavailable)."

        filing_block = filing_text if filing_text else (
            "No 10-K text available. Return conservative assumptions with low confidence."
        )

        prompt = (
            f"Ticker: {ticker.upper()}\n"
            f"Sector: {det.get('sector', '')}\n"
            f"Reported EBIT: {float(reported_ebit):,.0f}\n\n"
            f"Deterministic QoE signals (pre-computed):\n"
            f"  Overall score: {det.get('qoe_score', '?')}/5 ({det.get('qoe_flag', '?')})\n"
            f"  Sloan accruals ratio: {det.get('sloan_accruals_ratio')} "
            f"  (sector threshold amber={det.get('accruals_thresholds', {}).get('amber')}, "
            f"red={det.get('accruals_thresholds', {}).get('red')})\n"
            f"  Cash conversion (CFFO/EBITDA): {det.get('cash_conversion')}\n"
            f"  DSO drift: {det.get('dso_drift')} days (current={det.get('dso_current')}, "
            f"baseline={det.get('dso_baseline')} [{det.get('dso_baseline_source')}])\n"
            f"  DIO drift: {det.get('dio_drift')} days\n"
            f"  DPO drift: {det.get('dpo_drift')} days\n"
            f"  Capex/DA ratio: {det.get('capex_da_ratio')}\n\n"
            f"Flagged signals requiring explanation:\n{signals_block}\n\n"
            f"10-K excerpt:\n{filing_block[:40_000]}\n\n"
            f"Return only JSON per the required schema."
        )

        try:
            raw = self.run(prompt)
            return self._parse_llm_response(raw, reported_ebit=reported_ebit, source=source)
        except Exception:
            return self._llm_fallback(
                reported_ebit=reported_ebit,
                source=f"{source}_fallback",
                det=det,
                filing_text_available=bool(filing_text),
            )

    # ── Output assembly ───────────────────────────────────────────────────────

    @staticmethod
    def _build_full_output(
        ticker: str,
        det: dict,
        llm: dict,
        reported_ebit: float,
        llm_available: bool,
    ) -> dict:
        normalized_ebit = llm.get("normalized_ebit") or reported_ebit
        ebit_haircut_pct: float | None = None
        if reported_ebit and abs(reported_ebit) > 0:
            ebit_haircut_pct = round((normalized_ebit - reported_ebit) / abs(reported_ebit) * 100, 1)

        dcf_override_pending = ebit_haircut_pct is not None and abs(ebit_haircut_pct) > 10.0

        # Separate det keys that belong at the top level vs the nested deterministic block
        det_block = {k: v for k, v in det.items() if k not in {"ticker", "qoe_score", "qoe_flag"}}

        return {
            "ticker": ticker.upper(),
            "qoe_score": det["qoe_score"],
            "qoe_flag": det["qoe_flag"],
            "deterministic": det_block,
            "llm": {
                "llm_available": llm_available,
                "normalized_ebit": normalized_ebit,
                "reported_ebit": float(reported_ebit),
                "ebit_haircut_pct": ebit_haircut_pct,
                "dcf_ebit_override_pending": dcf_override_pending,
                "ebit_adjustments": llm.get("ebit_adjustments", []),
                "signal_explanations": llm.get("signal_explanations", {}),
                "revenue_recognition_flags": llm.get("revenue_recognition_flags", []),
                "auditor_flags": llm.get("auditor_flags", []),
                "narrative_credibility": llm.get("narrative_credibility"),
                "llm_confidence": llm.get("confidence", "low"),
                "data_source": llm.get("data_source", ""),
            },
            "pm_summary": llm.get("pm_summary", ""),
        }

    # ── Public API ────────────────────────────────────────────────────────────

    def analyze(
        self,
        ticker: str,
        reported_ebit: float,
        filing_text: str | None = None,
    ) -> dict:
        """
        Run full QoE analysis for a ticker.

        Parameters
        ----------
        ticker        : company ticker
        reported_ebit : reported EBIT (absolute USD) used as LLM normalization base
        filing_text   : optional pre-fetched 10-K text; fetched from EDGAR if None

        Returns
        -------
        Full QoE output dict — see _build_full_output() for schema.
        EBIT normalization does NOT auto-flow into the DCF; dcf_ebit_override_pending
        flags the case for PM approval via valuation_overrides.yaml.
        """
        ticker = ticker.upper().strip()

        # ── Layer 1: deterministic signals ───────────────────────────────────
        mkt = md_client.get_market_data(ticker)
        hist = md_client.get_historical_financials(ticker)
        ciq = get_ciq_snapshot(ticker)
        ciq_history = get_ciq_nwc_history(ticker)
        sector = (mkt.get("sector") or "").strip()

        det = compute_qoe_signals(
            ticker=ticker,
            sector=sector,
            ciq_snapshot=ciq,
            ciq_nwc_history=ciq_history,
            hist=hist,
            mkt=mkt,
        )

        # ── Layer 2: LLM judgment ─────────────────────────────────────────────
        llm_available = True
        source = "provided_10k_text"
        if filing_text is None:
            source = "sec_edgar_filing_context"
            try:
                bundle = filing_retrieval.get_agent_filing_context(
                    ticker,
                    profile_name="qoe",
                    include_10k=True,
                    ten_q_limit=2,
                )
                filing_text = filing_retrieval.render_filing_context(bundle, max_chars=40_000)
            except Exception:
                filing_text = edgar_client.get_10k_text(ticker)
                source = "sec_edgar_10k"
            llm_available = bool(filing_text)

        llm_result = self._run_llm(
            ticker=ticker,
            reported_ebit=reported_ebit,
            det=det,
            filing_text=filing_text,
            source=source,
        )

        return self._build_full_output(
            ticker=ticker,
            det=det,
            llm=llm_result,
            reported_ebit=reported_ebit,
            llm_available=llm_available,
        )


def write_qoe_pending_override(
    ticker: str,
    qoe_result: dict,
    revenue_mm: float,
) -> Path:
    """
    Write QoE LLM normalisation recommendation to config/qoe_pending.yaml.

    Status starts as 'pending'. PM sets status → 'approved' to apply the
    suggested_override on the next batch_runner --json run.
    Status → 'rejected' suppresses future writes for this ticker until cleared.

    Returns the path written.
    """
    ticker = ticker.upper().strip()
    llm = qoe_result.get("llm", {})

    reported_ebit = llm.get("reported_ebit") or 0.0
    normalized_ebit = llm.get("normalized_ebit") or reported_ebit
    haircut_pct = llm.get("ebit_haircut_pct")
    pending_flag = llm.get("dcf_ebit_override_pending", False)

    # Convert absolute EBIT to margin using LTM revenue
    rev = revenue_mm * 1_000_000 if revenue_mm else 0.0
    reported_margin = round(reported_ebit / rev, 6) if rev else None
    normalized_margin = round(normalized_ebit / rev, 6) if rev else None

    # Load existing pending file (preserve other tickers' entries)
    existing: dict = {}
    if QOE_PENDING_PATH.exists():
        with QOE_PENDING_PATH.open("r", encoding="utf-8") as f:
            existing = yaml.safe_load(f) or {}

    # Don't overwrite a PM decision (approved/rejected) with a fresh run
    prev_status = (existing.get(ticker) or {}).get("status", "pending")
    if prev_status in {"approved", "rejected"}:
        # Preserve the PM decision; just refresh metadata
        existing.setdefault(ticker, {})["last_refreshed_at"] = datetime.utcnow().isoformat(timespec="seconds")
        QOE_PENDING_PATH.write_text(
            yaml.dump(existing, default_flow_style=False, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        return QOE_PENDING_PATH

    entry: dict = {
        "generated_at": datetime.utcnow().isoformat(timespec="seconds"),
        "qoe_score": qoe_result.get("qoe_score"),
        "qoe_flag": qoe_result.get("qoe_flag"),
        "confidence": llm.get("llm_confidence", "low"),
        "reported_ebit_mm": round(reported_ebit / 1_000_000, 2) if reported_ebit else None,
        "reported_ebit_margin": reported_margin,
        "normalized_ebit_mm": round(normalized_ebit / 1_000_000, 2) if normalized_ebit else None,
        "normalized_ebit_margin": normalized_margin,
        "ebit_haircut_pct": haircut_pct,
        "override_warranted": pending_flag,
        "adjustments": [
            {
                "item": a["item"],
                "amount_mm": round(a["amount"] / 1_000_000, 2) if a["amount"] > 1_000 else a["amount"],
                "direction": a["direction"],
                "rationale": a["rationale"],
            }
            for a in llm.get("ebit_adjustments", [])
        ],
        "revenue_recognition_flags": llm.get("revenue_recognition_flags", []),
        "auditor_flags": llm.get("auditor_flags", []),
        "pm_summary": qoe_result.get("pm_summary", ""),
        # ── PM APPROVAL BLOCK ────────────────────────────────────────────────
        # To apply: set status → 'approved', then re-run:
        #   python -m src.stage_02_valuation.batch_runner --ticker TICKER --json
        # To reject without applying: set status → 'rejected'
        "suggested_override": {
            "ebit_margin_start": normalized_margin,
        } if normalized_margin is not None else {},
        "status": "pending",   # pending | approved | rejected
    }

    existing[ticker] = entry
    QOE_PENDING_PATH.write_text(
        yaml.dump(existing, default_flow_style=False, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return QOE_PENDING_PATH
