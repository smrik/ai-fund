from __future__ import annotations

from html import escape

import streamlit as st


DASHBOARD_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter+Tight:wght@400;500;600;700;800&family=Inter:wght@400;500;600;700&family=Playfair+Display:wght@500;700&family=JetBrains+Mono:wght@400;500&display=swap');

:root {
    --ap-background: #0d1117;
    --ap-foreground: #f6f8fb;
    --ap-muted: #141a22;
    --ap-muted-foreground: #8d99a8;
    --ap-accent: #63a8ff;
    --ap-accent-foreground: #07111f;
    --ap-border: #202938;
    --ap-input: #121923;
    --ap-card: #10161f;
    --ap-card-foreground: #FAFAFA;
    --ap-ring: #63a8ff;
    --ap-sidebar: #0f141c;
    --ap-sidebar-border: #1c2431;
}

html, body, [data-testid="stAppViewContainer"] {
    background:
        radial-gradient(circle at top left, rgba(99, 168, 255, 0.08), transparent 28%),
        radial-gradient(circle at top right, rgba(255, 255, 255, 0.02), transparent 22%),
        var(--ap-background);
    color: var(--ap-foreground);
}

[data-testid="stAppViewContainer"]::before {
    content: "";
    position: fixed;
    inset: 0;
    pointer-events: none;
    opacity: 0.015;
    background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='140' height='140' viewBox='0 0 140 140'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.8' numOctaves='2' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='140' height='140' filter='url(%23n)' opacity='1'/%3E%3C/svg%3E");
}

body, p, li, label, th, td, caption, button, input, select, textarea,
.stMarkdown p, .stMarkdown li, .stCaption, .stText,
[data-testid="stMetricLabel"], [data-testid="stMetricDelta"] {
    font-family: "Inter", system-ui, sans-serif;
}

h1, h2, h3, h4, h5, h6, .ap-shell-title {
    font-family: "Inter Tight", "Inter", system-ui, sans-serif;
    color: var(--ap-foreground);
    letter-spacing: -0.04em;
}

.ap-shell-quote {
    font-family: "Playfair Display", Georgia, serif;
}

code, pre, [data-testid="stCode"] *, .stDataFrame td, .stDataFrame th,
[data-testid="stMetricValue"], .ap-shell-kicker, .ap-shell-meta {
    font-family: "JetBrains Mono", "Fira Code", monospace;
}

[data-testid="stSidebar"] {
    background: var(--ap-sidebar);
    border-right: 1px solid var(--ap-sidebar-border);
    min-width: 290px;
    max-width: 290px;
}

[data-testid="stSidebar"] .stMarkdown p,
[data-testid="stSidebar"] label,
[data-testid="stSidebar"] .stCaption {
    color: var(--ap-muted-foreground);
}

[data-testid="stMetric"] {
    background: var(--ap-card);
    border: 1px solid var(--ap-border);
    border-radius: 10px;
    padding: 14px 16px;
}

[data-testid="stMetricLabel"] {
    color: var(--ap-muted-foreground);
    font-size: 0.72rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.12em;
}

[data-testid="stMetricValue"] {
    color: var(--ap-foreground);
    font-size: 1.5rem;
    font-weight: 700;
}

[data-testid="stDataFrame"],
[data-testid="stDataEditor"],
[data-testid="stStatusWidget"],
[data-testid="stExpander"] {
    border: 1px solid var(--ap-border);
    border-radius: 10px;
    background: var(--ap-card);
}

[data-testid="stExpander"] details,
[data-testid="stExpander"] summary,
[data-testid="stExpanderDetails"],
.streamlit-expanderContent {
    background: var(--ap-card);
    color: var(--ap-foreground);
}

.stTextInput input, .stNumberInput input, .stTextArea textarea,
div[data-baseweb="base-input"] > div,
div[data-baseweb="select"] > div,
[role="combobox"] {
    background: var(--ap-input);
    border: 1px solid var(--ap-border);
    border-radius: 0;
    color: var(--ap-foreground);
}

ul[role="listbox"],
div[data-baseweb="popover"],
li[role="option"],
div[role="option"] {
    background: var(--ap-card);
    color: var(--ap-foreground);
    border-color: var(--ap-border);
}

li[role="option"][aria-selected="true"],
div[role="option"][aria-selected="true"] {
    background: rgba(99, 168, 255, 0.12);
    color: var(--ap-foreground);
}

.stButton > button {
    background: rgba(99, 168, 255, 0.08);
    color: var(--ap-foreground);
    border: 1px solid var(--ap-border);
    border-radius: 10px;
    font-family: "Inter Tight", "Inter", system-ui, sans-serif;
    font-size: 0.85rem;
    font-weight: 700;
    letter-spacing: 0.04em;
    padding: 0.7rem 1rem;
    text-transform: none;
}

.stButton > button:hover {
    color: var(--ap-accent);
    background: rgba(99, 168, 255, 0.12);
}

[data-testid="stPopoverButton"] > button {
    width: 100%;
    background: rgba(99, 168, 255, 0.06);
    border: 1px solid var(--ap-border);
    border-radius: 10px;
    color: var(--ap-foreground);
    font-family: "Inter Tight", "Inter", system-ui, sans-serif;
    font-size: 0.82rem;
    font-weight: 700;
    letter-spacing: 0.04em;
    text-transform: none;
}

[data-testid="stPopover"] {
    border: 1px solid var(--ap-border);
    background: var(--ap-card);
}

[data-testid="stDataFrame"] [role="grid"],
[data-testid="stDataEditor"] [role="grid"] {
    background: var(--ap-card);
}

[data-testid="stDataFrame"] [role="columnheader"],
[data-testid="stDataEditor"] [role="columnheader"] {
    background: #101010;
    color: #8f8f8f;
    font-family: "JetBrains Mono", monospace;
    font-size: 0.72rem;
    letter-spacing: 0.08em;
    text-transform: uppercase;
}

[data-testid="stDataFrame"] [role="gridcell"],
[data-testid="stDataEditor"] [role="gridcell"] {
    background: #0d0d0d;
    color: var(--ap-foreground);
    border-color: #1b1b1b;
}

div[data-baseweb="button-group"] {
    background: var(--ap-card);
    border: 1px solid var(--ap-border);
    padding: 0.25rem;
    border-radius: 999px;
}

div[data-baseweb="button-group"] button {
    background: transparent;
    border: 0;
    border-radius: 999px;
    color: var(--ap-muted-foreground);
    font-family: "Inter Tight", "Inter", system-ui, sans-serif;
    font-size: 0.8rem;
    font-weight: 700;
    letter-spacing: 0.05em;
    text-transform: uppercase;
}

div[data-baseweb="button-group"] button[aria-pressed="true"] {
    color: var(--ap-foreground);
    background: rgba(99, 168, 255, 0.14);
}

div[data-baseweb="button-group"] button:hover {
    color: var(--ap-foreground);
}

[data-testid="stInfo"],
[data-testid="stWarning"],
[data-testid="stError"],
[data-testid="stSuccess"] {
    border-radius: 10px;
    border-left-width: 0;
    border: 1px solid var(--ap-border);
}

[data-testid="stInfo"] {
    background: rgba(99, 168, 255, 0.08);
    color: var(--ap-foreground);
}

[data-testid="stWarning"] {
    background: rgba(245, 197, 66, 0.10);
    color: var(--ap-foreground);
}

[data-testid="stError"] {
    background: rgba(220, 38, 38, 0.12);
    border-left-color: #dc2626;
}

[data-testid="stSuccess"] {
    background: rgba(34, 197, 94, 0.12);
    border-left-color: #22c55e;
    color: var(--ap-foreground);
}

header[data-testid="stHeader"],
[data-testid="stToolbar"],
#MainMenu,
footer {
    display: none;
}

.block-container {
    max-width: 100%;
    padding: 1rem 1.5rem 1rem 1.5rem;
}

hr {
    border-color: var(--ap-border);
    margin: 1.5rem 0;
}

h2 {
    font-size: 1.1rem;
    border-bottom: 1px solid var(--ap-border);
    padding-bottom: 0.35rem;
    margin-bottom: 0.8rem;
}

h3 {
    font-size: 1.05rem;
}

.ap-shell {
    padding: 0.15rem 0 0.85rem 0;
    margin-bottom: 0.75rem;
}

.ap-shell-kicker {
    color: var(--ap-muted-foreground);
    font-size: 0.72rem;
    font-weight: 700;
    letter-spacing: 0.16em;
    text-transform: uppercase;
    margin-bottom: 0.45rem;
}

.ap-shell-title {
    font-size: clamp(1.7rem, 3.2vw, 2.8rem);
    font-weight: 800;
    line-height: 1.02;
    margin: 0;
}

.ap-shell-copy {
    color: var(--ap-muted-foreground);
    font-size: 0.94rem;
    line-height: 1.55;
    max-width: 42rem;
    margin-top: 0.55rem;
}

.ap-shell-meta {
    color: var(--ap-muted-foreground);
    font-size: 0.78rem;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    margin-top: 0.6rem;
}

.ap-ticker-strip {
    position: sticky;
    top: 0.35rem;
    z-index: 5;
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    gap: 1rem;
    background: rgba(16, 22, 31, 0.92);
    border: 1px solid var(--ap-border);
    border-radius: 12px;
    padding: 0.85rem 1rem;
    margin-bottom: 1rem;
    backdrop-filter: blur(10px);
}

.ap-ticker-strip-main {
    min-width: 0;
}

.ap-ticker-strip-title {
    font-family: "Inter Tight", "Inter", system-ui, sans-serif;
    font-size: 1.15rem;
    font-weight: 700;
    margin: 0;
}

.ap-ticker-strip-meta {
    color: var(--ap-muted-foreground);
    font-size: 0.78rem;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    margin-top: 0.25rem;
}

.ap-ticker-strip-metrics {
    display: grid;
    grid-template-columns: repeat(4, minmax(88px, 1fr));
    gap: 0.75rem;
    min-width: min(100%, 520px);
}

.ap-ticker-strip-metric {
    border-left: 1px solid var(--ap-border);
    padding-left: 0.75rem;
}

.ap-ticker-strip-label {
    color: var(--ap-muted-foreground);
    font-size: 0.68rem;
    font-weight: 700;
    letter-spacing: 0.12em;
    text-transform: uppercase;
}

.ap-ticker-strip-value {
    font-family: "JetBrains Mono", monospace;
    font-size: 1rem;
    font-weight: 700;
    margin-top: 0.2rem;
}

.ap-sidebar-title {
    font-family: "Inter Tight", "Inter", system-ui, sans-serif;
    font-size: 1.25rem;
    font-weight: 800;
    letter-spacing: -0.04em;
}

@media (max-width: 900px) {
    .block-container {
        padding: 1rem 0.85rem 0.85rem 0.85rem;
    }

    .ap-shell-title {
        font-size: clamp(1.4rem, 8vw, 2.15rem);
    }

    [data-testid="stSidebar"] {
        min-width: unset;
        max-width: unset;
    }

    .ap-ticker-strip {
        position: static;
        display: block;
    }

    .ap-ticker-strip-metrics {
        grid-template-columns: repeat(2, minmax(0, 1fr));
        margin-top: 0.8rem;
    }
}
</style>
"""


def render_shell_header(*, workspace: str, section: str, description: str, ticker: str | None = None, company_name: str | None = None) -> None:
    meta_parts = [workspace]
    if ticker:
        meta_parts.append(ticker)
    if company_name:
        meta_parts.append(company_name)

    st.markdown(
        f"""
<section class="ap-shell">
  <div class="ap-shell-kicker">{workspace}</div>
  <h1 class="ap-shell-title">{section}</h1>
  <p class="ap-shell-copy">{description}</p>
  <div class="ap-shell-meta">{' · '.join(meta_parts)}</div>
</section>
""",
        unsafe_allow_html=True,
    )


def render_ticker_strip(
    *,
    ticker: str,
    company_name: str,
    sector: str,
    action: str,
    conviction: str,
    current_price: float | None,
    base_iv: float | None,
    upside_pct_base: float | None,
    snapshot_label: str,
) -> None:
    metrics = [
        ("Action", action),
        ("Conviction", conviction.upper()),
        ("Current Price", f"${current_price or 0:,.2f}"),
        ("Base IV", f"${base_iv or 0:,.2f}"),
        ("Upside", f"{(upside_pct_base or 0) * 100:+.1f}%"),
        ("Snapshot", snapshot_label),
    ]
    metric_html = "".join(
        (
            '<div class="ap-ticker-strip-metric">'
            f'<div class="ap-ticker-strip-label">{escape(str(label))}</div>'
            f'<div class="ap-ticker-strip-value">{escape(str(value))}</div>'
            "</div>"
        )
        for label, value in metrics
    )
    st.markdown(
        (
            '<section class="ap-ticker-strip">'
            '<div class="ap-ticker-strip-main">'
            f'<h2 class="ap-ticker-strip-title">{escape(str(ticker))} — {escape(str(company_name))}</h2>'
            f'<div class="ap-ticker-strip-meta">{escape(str(sector))}</div>'
            "</div>"
            f'<div class="ap-ticker-strip-metrics">{metric_html}</div>'
            "</section>"
        ),
        unsafe_allow_html=True,
    )
