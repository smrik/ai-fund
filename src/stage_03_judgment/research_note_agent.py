"""
Research Note Agent — synthesizes all pipeline outputs into a structured equity research note.
Follows BaseAgent pattern. Output is a structured markdown document.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from typing import Optional

from src.stage_03_judgment.base_agent import BaseAgent
from config import LLM_SYNTHESIS_MODEL


# ---------------------------------------------------------------------------
# Output dataclass
# ---------------------------------------------------------------------------

@dataclass
class ResearchNote:
    ticker: str
    company_name: str
    date: str
    action: str
    conviction: str
    current_price: Optional[float]
    base_iv: Optional[float]
    upside_pct: Optional[float]
    # Sections (markdown text)
    executive_summary: str = ""
    investment_thesis: str = ""
    variant_view: str = ""
    valuation_summary: str = ""
    earnings_quality: str = ""
    macro_context: str = ""
    factor_profile: str = ""
    key_risks: str = ""
    # Meta
    available: bool = True
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Section header mapping
# ---------------------------------------------------------------------------

_SECTION_KEYS = {
    "executive summary": "executive_summary",
    "investment thesis": "investment_thesis",
    "variant view": "variant_view",
    "valuation": "valuation_summary",
    "earnings quality": "earnings_quality",
    "macro context": "macro_context",
    "factor profile": "factor_profile",
    "key risks": "key_risks",
}

_SYSTEM_PROMPT = (
    "You are a senior equity research analyst at a Tiger Cub hedge fund. "
    "You write precise, concise, institutional-quality research notes. "
    "Be factual, data-driven, and direct. Write for a sophisticated audience."
)


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

class ResearchNoteAgent(BaseAgent):
    """
    Synthesizes all pipeline outputs (IC memo, macro, forensic, factors, revisions)
    into a structured equity research note written in markdown.
    """

    def __init__(self):
        super().__init__(model=LLM_SYNTHESIS_MODEL)
        self.name = "ResearchNoteAgent"
        self.prompt_version = "v1"
        self.system_prompt = _SYSTEM_PROMPT
        self.tools = []
        self.tool_handlers = {}

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def generate_research_note(
        self,
        memo: dict,
        macro: dict | None = None,
        revisions: dict | None = None,
        forensic: dict | None = None,
        factors: dict | None = None,
    ) -> ResearchNote:
        """
        Call the LLM to produce a structured research note from pipeline outputs.

        Parameters
        ----------
        memo      : dict from ICMemo.model_dump()
        macro     : dict from get_regime_indicators() — regime state, vix, spreads
        revisions : dict from RevisionSignals (if available)
        forensic  : dict from compute_forensic_signals() (if available)
        factors   : dict from FactorExposure (if available)

        Returns
        -------
        ResearchNote dataclass with all 8 markdown sections populated.
        """
        ticker = memo.get("ticker", "UNKNOWN")
        company_name = memo.get("company_name", "")
        today = str(date.today())

        prompt = _build_prompt(memo, macro, revisions, forensic, factors)

        try:
            raw = self.run(prompt)
        except Exception as exc:
            return _error_note(ticker, company_name, today, memo, str(exc))

        sections = _parse_sections(raw)

        val = memo.get("valuation", {})
        price = val.get("current_price")
        base_iv = val.get("base")
        upside = val.get("upside_pct_base")
        if upside is not None:
            upside = upside * 100  # store as percentage points

        note = ResearchNote(
            ticker=ticker,
            company_name=company_name,
            date=today,
            action=memo.get("action", ""),
            conviction=memo.get("conviction", ""),
            current_price=price,
            base_iv=base_iv,
            upside_pct=upside,
            executive_summary=sections.get("executive_summary", ""),
            investment_thesis=sections.get("investment_thesis", ""),
            variant_view=sections.get("variant_view", ""),
            valuation_summary=sections.get("valuation_summary", ""),
            earnings_quality=sections.get("earnings_quality", ""),
            macro_context=sections.get("macro_context", ""),
            factor_profile=sections.get("factor_profile", ""),
            key_risks=sections.get("key_risks", ""),
            available=True,
            error=None,
        )
        self.last_run_artifact["parsed_output"] = note
        return note

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def parse_sections(raw_text: str) -> dict[str, str]:
        """Public alias — parse LLM output into section dict."""
        return _parse_sections(raw_text)


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def _parse_sections(raw_text: str) -> dict[str, str]:
    """
    Split LLM output on '## ' header lines into a dict keyed by normalised
    section name.  Unknown headers are silently ignored.
    """
    result: dict[str, str] = {}
    current_key: str | None = None
    buffer: list[str] = []

    def _flush():
        if current_key and buffer:
            result[current_key] = "\n".join(buffer).strip()

    for line in raw_text.splitlines():
        if line.startswith("## "):
            _flush()
            buffer = []
            header = line[3:].strip().lower().rstrip(":")
            # Map to canonical key
            current_key = _SECTION_KEYS.get(header)
        else:
            if current_key is not None:
                buffer.append(line)

    _flush()
    return result


def _build_prompt(
    memo: dict,
    macro: dict | None,
    revisions: dict | None,
    forensic: dict | None,
    factors: dict | None,
) -> str:
    ticker = memo.get("ticker", "UNKNOWN")
    company = memo.get("company_name", "")
    sector = memo.get("sector", "")
    action = memo.get("action", "N/A")
    conviction = memo.get("conviction", "N/A")
    one_liner = memo.get("one_liner", "")
    bull = memo.get("bull_case", "")
    base = memo.get("base_case", "")
    bear = memo.get("bear_case", "")
    variant = memo.get("variant_thesis_prompt", "")
    catalysts = memo.get("key_catalysts", [])
    risks = memo.get("key_risks", [])
    open_q = memo.get("open_questions", [])

    val = memo.get("valuation", {})
    price = val.get("current_price") or 0.0
    bear_iv = val.get("bear") or 0.0
    base_iv = val.get("base") or 0.0
    bull_iv = val.get("bull") or 0.0
    upside = (val.get("upside_pct_base") or 0.0) * 100

    filings = memo.get("filings", {})
    earnings = memo.get("earnings", {})
    risk_out = memo.get("risk", {})

    macro_block = ""
    if macro:
        macro_block = f"""
=== MACRO / REGIME ===
{json.dumps(macro, indent=2, default=str)}
"""

    revisions_block = ""
    if revisions:
        revisions_block = f"""
=== EARNINGS REVISIONS ===
{json.dumps(revisions, indent=2, default=str)}
"""

    forensic_block = ""
    if forensic:
        forensic_block = f"""
=== FORENSIC SIGNALS ===
M-Score: {forensic.get('m_score', 'N/A')} ({forensic.get('m_zone', 'N/A')})
Z-Score: {forensic.get('z_score', 'N/A')} ({forensic.get('z_zone', 'N/A')})
Forensic flag: {forensic.get('forensic_flag', 'N/A')}
Flags: {json.dumps(forensic.get('flags', []), default=str)}
"""

    factors_block = ""
    if factors:
        factors_block = f"""
=== FACTOR EXPOSURES ===
{json.dumps(factors, indent=2, default=str)}
"""

    return f"""Produce a structured institutional equity research note for {ticker} ({company}).

=== IC MEMO SUMMARY ===
Ticker: {ticker} | Company: {company} | Sector: {sector}
Action: {action} | Conviction: {conviction}
One-liner: {one_liner}

Valuation (per share):
  Bear ${bear_iv:.2f} | Base ${base_iv:.2f} | Bull ${bull_iv:.2f}
  Current price: ${price:.2f} | Base upside: {upside:+.1f}%

Bull case: {bull}
Base case: {base}
Bear case: {bear}
Variant thesis prompt: {variant}

Key catalysts: {catalysts}
Key risks: {risks}
Open questions: {open_q}

Filings highlights:
  Revenue CAGR 3y: {filings.get('revenue_cagr_3y', 'N/A')}
  Gross margin avg: {filings.get('gross_margin_avg', 'N/A')}
  EBIT margin avg: {filings.get('ebit_margin_avg', 'N/A')}
  FCF yield: {filings.get('fcf_yield', 'N/A')}
  Net debt/EBITDA: {filings.get('net_debt_to_ebitda', 'N/A')}
  Revenue trend: {filings.get('revenue_trend', 'N/A')}
  Margin trend: {filings.get('margin_trend', 'N/A')}
  Red flags: {filings.get('red_flags', [])}

Earnings highlights:
  EPS beat rate: {earnings.get('eps_beat_rate', 'N/A')}
  Guidance trend: {earnings.get('guidance_trend', 'N/A')}
  Management tone: {earnings.get('management_tone', 'N/A')}
  Key themes: {earnings.get('key_themes', [])}

Risk/Position:
  Conviction: {risk_out.get('conviction', 'N/A')}
  Position: {risk_out.get('position_pct', 0)*100:.1f}% of portfolio
  Stop loss: {risk_out.get('suggested_stop_loss_pct', 0)*100:.0f}% below entry
  Ann. vol: {risk_out.get('annualized_volatility', 'N/A')}
{macro_block}{revisions_block}{forensic_block}{factors_block}
---

Write the research note with EXACTLY these 8 sections using ## headers.
Be specific to {ticker}. No hedging or generic language. Write for a professional PM.

## Executive Summary
[2-3 sentences max. Action + conviction + key reason + price target.]

## Investment Thesis
[3-5 bullet points. Bull/base/bear view with specific drivers.]

## Variant View
[1-2 sentences. The question the market isn't asking. What is the non-consensus view?]

## Valuation
[DCF bear/base/bull table summary. Key assumption. Scenario probabilities.]

## Earnings Quality
[QoE score, M-Score interpretation, Z-Score zone, top 2 flags.]

## Macro Context
[Current regime, relevant macro headwinds/tailwinds, WACC implications.]

## Factor Profile
[Key factor exposures, R², alpha. Is this alpha or beta?]

## Key Risks
[Top 3 risks with brief mitigation note each.]"""


def _error_note(
    ticker: str,
    company_name: str,
    today: str,
    memo: dict,
    error_msg: str,
) -> ResearchNote:
    """Return a ResearchNote populated from memo data without LLM sections."""
    val = memo.get("valuation", {})
    price = val.get("current_price")
    base_iv = val.get("base")
    upside = val.get("upside_pct_base")
    if upside is not None:
        upside = upside * 100
    return ResearchNote(
        ticker=ticker,
        company_name=company_name,
        date=today,
        action=memo.get("action", ""),
        conviction=memo.get("conviction", ""),
        current_price=price,
        base_iv=base_iv,
        upside_pct=upside,
        available=False,
        error=error_msg,
    )


# ---------------------------------------------------------------------------
# Offline fallback (no LLM)
# ---------------------------------------------------------------------------

def generate_research_note_offline(
    memo: dict,
    macro: dict | None = None,
    revisions: dict | None = None,
    forensic: dict | None = None,
    factors: dict | None = None,
) -> ResearchNote:
    """
    Standalone function (no LLM) that generates a basic research note from
    available structured data.  Used as fallback when LLM is unavailable or
    when a quick, deterministic summary is needed.
    """
    ticker = memo.get("ticker", "UNKNOWN")
    company_name = memo.get("company_name", "")
    today = str(date.today())
    action = memo.get("action", "")
    conviction = memo.get("conviction", "")
    one_liner = memo.get("one_liner", "")
    bull = memo.get("bull_case", "")
    base = memo.get("base_case", "")
    bear = memo.get("bear_case", "")
    variant = memo.get("variant_thesis_prompt", "")
    catalysts = memo.get("key_catalysts", [])
    risks = memo.get("key_risks", [])

    val = memo.get("valuation", {})
    price = val.get("current_price") or 0.0
    bear_iv = val.get("bear") or 0.0
    base_iv_v = val.get("base") or 0.0
    bull_iv = val.get("bull") or 0.0
    upside = (val.get("upside_pct_base") or 0.0) * 100

    filings = memo.get("filings", {})

    # Build deterministic section text
    exec_summary = (
        f"**{action} | {conviction.upper()} conviction** — {one_liner or ticker}. "
        f"Base case IV ${base_iv_v:.2f} vs current ${price:.2f} ({upside:+.1f}% upside)."
    )

    thesis_lines = [f"- **Bull:** {bull}"] if bull else []
    if base:
        thesis_lines.append(f"- **Base:** {base}")
    if bear:
        thesis_lines.append(f"- **Bear:** {bear}")
    if catalysts:
        thesis_lines.append("- **Key catalysts:** " + "; ".join(catalysts))
    investment_thesis = "\n".join(thesis_lines) if thesis_lines else "See IC memo for thesis details."

    variant_view = variant or "No variant view available offline."

    valuation_summary = (
        f"| Scenario | IV | Upside |\n"
        f"|----------|-----|--------|\n"
        f"| Bear | ${bear_iv:.2f} | {((bear_iv - price) / price * 100):+.1f}% |\n"
        f"| Base | ${base_iv_v:.2f} | {((base_iv_v - price) / price * 100):+.1f}% |\n"
        f"| Bull | ${bull_iv:.2f} | {((bull_iv - price) / price * 100):+.1f}% |"
        if price > 0 else f"Bear: ${bear_iv:.2f} | Base: ${base_iv_v:.2f} | Bull: ${bull_iv:.2f}"
    )

    eq_lines = []
    if forensic:
        m_score = forensic.get("m_score")
        m_zone = forensic.get("m_zone", "")
        z_score = forensic.get("z_score")
        z_zone = forensic.get("z_zone", "")
        if m_score is not None:
            eq_lines.append(f"M-Score: {m_score:.2f} ({m_zone})")
        if z_score is not None:
            eq_lines.append(f"Z-Score: {z_score:.2f} ({z_zone})")
        flags = forensic.get("flags", [])
        if flags:
            eq_lines.append("Flags: " + ", ".join(str(f) for f in flags[:2]))
    red_flags = filings.get("red_flags", [])
    if red_flags:
        eq_lines.append("Filing red flags: " + ", ".join(str(f) for f in red_flags[:2]))
    earnings_quality = "\n".join(eq_lines) if eq_lines else "No forensic data available."

    macro_ctx = "No macro data available offline."
    if macro:
        regime = macro.get("regime", macro.get("regime_label", ""))
        vix = macro.get("vix")
        spreads = macro.get("credit_spreads", macro.get("ig_spread", macro.get("hy_spread")))
        parts = []
        if regime:
            parts.append(f"Regime: {regime}")
        if vix is not None:
            parts.append(f"VIX: {vix}")
        if spreads is not None:
            parts.append(f"Spreads: {spreads}")
        macro_ctx = " | ".join(parts) if parts else "Macro data present but unstructured."

    factor_profile = "No factor data available offline."
    if factors:
        items = []
        for k, v in list(factors.items())[:5]:
            items.append(f"{k}: {v}")
        factor_profile = " | ".join(items) if items else "Factor data present but unstructured."

    risks_text = "\n".join(f"- {r}" for r in risks) if risks else "See IC memo for risk details."

    return ResearchNote(
        ticker=ticker,
        company_name=company_name,
        date=today,
        action=action,
        conviction=conviction,
        current_price=val.get("current_price"),
        base_iv=val.get("base"),
        upside_pct=upside,
        executive_summary=exec_summary,
        investment_thesis=investment_thesis,
        variant_view=variant_view,
        valuation_summary=valuation_summary,
        earnings_quality=earnings_quality,
        macro_context=macro_ctx,
        factor_profile=factor_profile,
        key_risks=risks_text,
        available=True,
        error=None,
    )
