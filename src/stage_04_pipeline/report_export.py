"""HTML research note export — generates a professional self-contained HTML report.

Converts a ResearchNote dataclass into a complete, dark-themed, print-ready
HTML document styled to match the existing IC memo dashboard report.
"""
from __future__ import annotations

import html
import re
from datetime import date

from src.stage_03_judgment.research_note_agent import ResearchNote


# ---------------------------------------------------------------------------
# Action colour palette (matches dashboard/app.py _build_html_report)
# ---------------------------------------------------------------------------
_ACTION_COLORS: dict[str, str] = {
    "BUY": "#3fb950",
    "SELL SHORT": "#f85149",
    "WATCH": "#d29922",
    "PASS": "#8b949e",
}

_DEFAULT_COLOR = "#8b949e"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def export_html_research_note(
    note: ResearchNote,
    memo: dict | None = None,
) -> str:
    """
    Generate a complete, self-contained HTML research note.

    Parameters
    ----------
    note  : ResearchNote dataclass (from ResearchNoteAgent or offline fallback)
    memo  : Optional raw IC memo dict — used to populate the scenario table
            and any extra context not captured in the ResearchNote itself.

    Returns
    -------
    Complete HTML string, suitable for writing to a .html file or streaming.
    """
    action = note.action or "WATCH"
    action_col = _ACTION_COLORS.get(action.upper(), _DEFAULT_COLOR)
    conviction = (note.conviction or "").upper()
    price = note.current_price or 0.0
    base_iv = note.base_iv or 0.0
    upside = note.upside_pct or 0.0
    today = note.date or str(date.today())
    ticker = note.ticker or ""
    company = note.company_name or ""

    # Scenario rows from memo valuation or ResearchNote fields
    scenario_rows = _build_scenario_rows(note, memo, price)

    # Section bodies
    def _sec(title: str, body: str, icon: str = "") -> str:
        if not body or not body.strip():
            return ""
        title_html = f"{icon} {title}".strip()
        return f"""
<section class="note-section">
  <h2>{_esc(title_html)}</h2>
  <div class="section-body">{_md_to_html(body)}</div>
</section>"""

    sections_html = "".join([
        _sec("Executive Summary", note.executive_summary, ""),
        _sec("Investment Thesis", note.investment_thesis, ""),
        _sec("Variant View", note.variant_view, ""),
        _sec("Valuation", note.valuation_summary, ""),
        _sec("Earnings Quality", note.earnings_quality, ""),
        _sec("Macro Context", note.macro_context, ""),
        _sec("Factor Profile", note.factor_profile, ""),
        _sec("Key Risks", note.key_risks, ""),
    ])

    one_liner = (memo or {}).get("one_liner", "") if memo else ""
    variant_prompt = (memo or {}).get("variant_thesis_prompt", "") if memo else ""

    one_liner_block = ""
    if one_liner:
        one_liner_block = f"""
<div class="one-liner"><strong>Thesis:</strong> {_esc(one_liner)}</div>"""

    variant_block = ""
    if variant_prompt:
        variant_block = f"""
<div class="variant"><strong>Variant View:</strong> {_esc(variant_prompt)}</div>"""

    unavailable_banner = ""
    if not note.available:
        err = _esc(note.error or "LLM unavailable")
        unavailable_banner = f"""
<div class="warning-banner">Research note generated offline (no LLM): {err}</div>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_esc(ticker)} — Research Note {_esc(today)}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
/* ── Base ────────────────────────────────────────────────────────────────── */
*, *::before, *::after {{ box-sizing: border-box; }}
body {{
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  background: #0d1117;
  color: #e2e8f0;
  max-width: 980px;
  margin: 40px auto;
  padding: 0 24px 64px;
  font-size: 0.95rem;
  line-height: 1.65;
}}

/* ── Typography ─────────────────────────────────────────────────────────── */
h1 {{ color: #f0f6fc; font-size: 1.75rem; margin: 0 0 4px; }}
h2 {{
  color: #388bfd;
  font-size: 1.05rem;
  font-weight: 600;
  border-bottom: 1px solid #21262d;
  padding-bottom: 6px;
  margin-top: 32px;
  margin-bottom: 12px;
}}
h3 {{ color: #c9d1d9; font-size: 0.95rem; margin: 16px 0 6px; }}
p {{ margin: 0 0 10px; }}

/* ── Header ─────────────────────────────────────────────────────────────── */
.report-header {{
  border-bottom: 1px solid #21262d;
  padding-bottom: 20px;
  margin-bottom: 24px;
}}
.header-meta {{
  color: #8b949e;
  font-size: 0.82rem;
  margin-top: 4px;
}}

/* ── Action badge ───────────────────────────────────────────────────────── */
.badge {{
  display: inline-block;
  padding: 4px 14px;
  border-radius: 4px;
  font-weight: 700;
  font-size: 1rem;
  color: #fff;
  background: {action_col};
  margin-right: 10px;
  vertical-align: middle;
}}

/* ── Metric grid ────────────────────────────────────────────────────────── */
.metric-grid {{
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 12px;
  margin: 20px 0;
}}
.metric {{
  background: #161b22;
  border: 1px solid #21262d;
  border-radius: 8px;
  padding: 14px 16px;
}}
.metric-label {{
  color: #8b949e;
  font-size: 0.72rem;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  font-weight: 600;
}}
.metric-value {{
  color: #f0f6fc;
  font-size: 1.35rem;
  font-weight: 700;
  margin-top: 4px;
}}
.metric-value.positive {{ color: #3fb950; }}
.metric-value.negative {{ color: #f85149; }}

/* ── One-liner / Variant boxes ──────────────────────────────────────────── */
.one-liner {{
  background: #162032;
  border-left: 3px solid #388bfd;
  padding: 12px 16px;
  border-radius: 0 6px 6px 0;
  margin: 12px 0;
  font-style: italic;
}}
.variant {{
  background: #1f1a00;
  border-left: 3px solid #d29922;
  padding: 12px 16px;
  border-radius: 0 6px 6px 0;
  margin: 12px 0;
}}

/* ── Warning banner ─────────────────────────────────────────────────────── */
.warning-banner {{
  background: #2d1f00;
  border: 1px solid #d29922;
  border-radius: 6px;
  padding: 10px 16px;
  color: #d29922;
  margin: 16px 0;
  font-size: 0.85rem;
}}

/* ── Scenario table ─────────────────────────────────────────────────────── */
table {{
  width: 100%;
  border-collapse: collapse;
  margin: 8px 0 16px;
  font-size: 0.9rem;
}}
th {{
  background: #161b22;
  color: #8b949e;
  font-weight: 600;
  font-size: 0.8rem;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  padding: 8px 12px;
  border: 1px solid #21262d;
  text-align: left;
}}
td {{
  border: 1px solid #21262d;
  padding: 8px 12px;
}}
tr:nth-child(even) td {{ background: #0d1117; }}
tr:nth-child(odd) td {{ background: #161b22; }}

/* ── Note sections ──────────────────────────────────────────────────────── */
.note-section {{
  margin-bottom: 8px;
}}
.section-body {{
  color: #c9d1d9;
}}
.section-body ul {{
  padding-left: 24px;
  margin: 4px 0 10px;
}}
.section-body li {{
  margin-bottom: 5px;
  line-height: 1.6;
}}
.section-body strong {{ color: #e2e8f0; }}
.section-body code {{
  background: #161b22;
  border: 1px solid #21262d;
  border-radius: 3px;
  padding: 1px 5px;
  font-size: 0.88em;
  font-family: 'SFMono-Regular', Consolas, monospace;
}}

/* ── Footer ─────────────────────────────────────────────────────────────── */
.report-footer {{
  border-top: 1px solid #21262d;
  margin-top: 56px;
  padding-top: 16px;
  color: #8b949e;
  font-size: 0.78rem;
}}

/* ── Print ───────────────────────────────────────────────────────────────── */
@media print {{
  body {{
    background: #ffffff;
    color: #111827;
    max-width: none;
    margin: 0;
    padding: 24px 32px;
  }}
  h1, h2, h3, p, li, td, th, .section-body {{ color: #111827 !important; }}
  .badge {{ -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
  .metric, .one-liner, .variant, .warning-banner {{
    break-inside: avoid;
    border-color: #d1d5db !important;
    background: #f9fafb !important;
    color: #111827 !important;
  }}
  .metric-value {{ color: #111827 !important; }}
  .metric-label {{ color: #6b7280 !important; }}
  h2 {{ color: #1d4ed8 !important; border-color: #d1d5db !important; }}
  th {{ background: #f3f4f6 !important; color: #374151 !important; }}
  td {{ border-color: #d1d5db !important; }}
  tr:nth-child(even) td, tr:nth-child(odd) td {{ background: #fff !important; }}
  .report-footer {{ color: #6b7280 !important; border-color: #d1d5db !important; }}
  a {{ color: #1d4ed8 !important; }}
}}
</style>
</head>
<body>

<div class="report-header">
  <h1>
    <span class="badge">{_esc(action)}</span>
    {_esc(ticker)} — {_esc(company)}
  </h1>
  <div class="header-meta">{_esc(today)} &nbsp;·&nbsp; Analyst: AI Research Pod</div>
</div>

{unavailable_banner}

<div class="metric-grid">
  <div class="metric">
    <div class="metric-label">Action</div>
    <div class="metric-value" style="color:{action_col}">{_esc(action)}</div>
  </div>
  <div class="metric">
    <div class="metric-label">Conviction</div>
    <div class="metric-value">{_esc(conviction)}</div>
  </div>
  <div class="metric">
    <div class="metric-label">Current Price</div>
    <div class="metric-value">${price:,.2f}</div>
  </div>
  <div class="metric">
    <div class="metric-label">Base Case IV</div>
    <div class="metric-value">${base_iv:,.2f}</div>
  </div>
  <div class="metric">
    <div class="metric-label">Upside (Base)</div>
    <div class="metric-value {_upside_class(upside)}">{upside:+.1f}%</div>
  </div>
</div>

{one_liner_block}
{variant_block}

<h2>DCF Scenarios</h2>
<table>
  <thead>
    <tr><th>Scenario</th><th>Intrinsic Value</th><th>Upside / (Downside)</th></tr>
  </thead>
  <tbody>
    {scenario_rows}
  </tbody>
</table>

{sections_html}

<div class="report-footer">
  Generated by AI Research Pod &nbsp;·&nbsp; {_esc(today)}
</div>

</body>
</html>"""


def export_research_note_for_download(
    note: ResearchNote,
    memo: dict | None = None,
) -> tuple[str, str]:
    """
    Generate the HTML report and return (html_content, filename).

    Filename format: {TICKER}_research_note_{YYYY-MM-DD}.html
    """
    html_content = export_html_research_note(note, memo)
    today = note.date or str(date.today())
    ticker = (note.ticker or "UNKNOWN").upper()
    filename = f"{ticker}_research_note_{today}.html"
    return html_content, filename


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _esc(text: str) -> str:
    """HTML-escape a string."""
    return html.escape(str(text) if text is not None else "")


def _upside_class(upside: float) -> str:
    if upside > 0:
        return "positive"
    if upside < 0:
        return "negative"
    return ""


def _build_scenario_rows(
    note: ResearchNote,
    memo: dict | None,
    price: float,
) -> str:
    """Build the three bear/base/bull table rows."""
    val = (memo or {}).get("valuation", {}) if memo else {}

    bear_iv = val.get("bear") or 0.0
    base_iv = val.get("base") or note.base_iv or 0.0
    bull_iv = val.get("bull") or 0.0

    rows = []
    for label, iv in [("Bear", bear_iv), ("Base", base_iv), ("Bull", bull_iv)]:
        if price > 0:
            delta = (iv - price) / price * 100
            delta_str = f"{delta:+.1f}%"
            color = "#3fb950" if delta > 0 else "#f85149" if delta < 0 else "#8b949e"
        else:
            delta_str = "—"
            color = "#8b949e"
        rows.append(
            f"<tr><td>{_esc(label)}</td>"
            f"<td>${iv:,.2f}</td>"
            f"<td style='color:{color};font-weight:600'>{delta_str}</td></tr>"
        )
    return "\n    ".join(rows)


def _md_to_html(text: str) -> str:
    """
    Minimal markdown-to-HTML converter for research note section bodies.
    Handles: bullet lists, bold (**text**), and paragraph breaks.
    Does not use an external markdown library to keep the module self-contained.
    """
    if not text:
        return ""

    lines = text.split("\n")
    out: list[str] = []
    in_list = False

    for line in lines:
        stripped = line.strip()

        if not stripped:
            if in_list:
                out.append("</ul>")
                in_list = False
            out.append("")
            continue

        # Bullet list items: - or * prefix
        if re.match(r"^[-*]\s+", stripped):
            if not in_list:
                out.append("<ul>")
                in_list = True
            item = stripped[2:].strip()
            out.append(f"<li>{_inline_md(_esc(item))}</li>")
        else:
            if in_list:
                out.append("</ul>")
                in_list = False
            # Table rows (markdown pipe syntax) — pass through as-is escaped
            if stripped.startswith("|"):
                out.append(_render_md_table_row(stripped))
            else:
                out.append(f"<p>{_inline_md(_esc(stripped))}</p>")

    if in_list:
        out.append("</ul>")

    return "\n".join(line for line in out if line != "")


def _inline_md(text: str) -> str:
    """Apply inline markdown: **bold** and `code`."""
    # Bold: **text** or __text__
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"__(.+?)__", r"<strong>\1</strong>", text)
    # Inline code: `text`
    text = re.sub(r"`(.+?)`", r"<code>\1</code>", text)
    return text


def _render_md_table_row(line: str) -> str:
    """
    Render a single markdown table row as an HTML table row.
    Caller is responsible for wrapping in <table> if needed.
    Simple: just emit a <tr> with <td> cells. Header detection is omitted
    for simplicity (separator rows are skipped).
    """
    # Skip separator rows (---|---)
    if re.match(r"^\|[-:| ]+\|$", line):
        return ""
    cells = [c.strip() for c in line.strip("|").split("|")]
    tds = "".join(f"<td>{_inline_md(_esc(c))}</td>" for c in cells)
    return f"<tr>{tds}</tr>"
