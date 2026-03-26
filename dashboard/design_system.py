from __future__ import annotations

import streamlit as st


DASHBOARD_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter+Tight:wght@400;500;600;700;800&family=Inter:wght@400;500;600;700&family=Playfair+Display:wght@500;700&family=JetBrains+Mono:wght@400;500&display=swap');

:root {
    --ap-background: #0A0A0A;
    --ap-foreground: #FAFAFA;
    --ap-muted: #1A1A1A;
    --ap-muted-foreground: #737373;
    --ap-accent: #FF3D00;
    --ap-accent-foreground: #0A0A0A;
    --ap-border: #262626;
    --ap-input: #1A1A1A;
    --ap-card: #0F0F0F;
    --ap-card-foreground: #FAFAFA;
    --ap-ring: #FF3D00;
    --ap-sidebar: #111111;
    --ap-sidebar-border: #222222;
}

html, body, [data-testid="stAppViewContainer"] {
    background:
        radial-gradient(circle at top left, rgba(255, 61, 0, 0.08), transparent 30%),
        radial-gradient(circle at top right, rgba(255, 255, 255, 0.03), transparent 24%),
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
    min-width: 330px;
    max-width: 330px;
}

[data-testid="stSidebar"] .stMarkdown p,
[data-testid="stSidebar"] label,
[data-testid="stSidebar"] .stCaption {
    color: var(--ap-muted-foreground);
}

[data-testid="stMetric"] {
    background: var(--ap-card);
    border: 1px solid var(--ap-border);
    border-radius: 0;
    padding: 16px 18px;
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
    border-radius: 0;
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
    background: rgba(255, 61, 0, 0.12);
    color: var(--ap-foreground);
}

.stButton > button {
    background: transparent;
    color: var(--ap-foreground);
    border: 0;
    border-bottom: 2px solid var(--ap-accent);
    border-radius: 0;
    font-family: "Inter Tight", "Inter", system-ui, sans-serif;
    font-size: 0.85rem;
    font-weight: 700;
    letter-spacing: 0.1em;
    padding: 0.9rem 0;
    text-transform: uppercase;
}

.stButton > button:hover {
    color: var(--ap-accent);
    background: transparent;
}

[data-testid="stPopoverButton"] > button {
    width: 100%;
    background: transparent;
    border: 1px solid var(--ap-border);
    border-bottom: 2px solid var(--ap-accent);
    border-radius: 0;
    color: var(--ap-foreground);
    font-family: "Inter Tight", "Inter", system-ui, sans-serif;
    font-size: 0.82rem;
    font-weight: 700;
    letter-spacing: 0.1em;
    text-transform: uppercase;
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
}

div[data-baseweb="button-group"] button {
    background: transparent;
    border: 0;
    border-bottom: 2px solid transparent;
    border-radius: 0;
    color: var(--ap-muted-foreground);
    font-family: "Inter Tight", "Inter", system-ui, sans-serif;
    font-size: 0.85rem;
    font-weight: 700;
    letter-spacing: 0.08em;
    text-transform: uppercase;
}

div[data-baseweb="button-group"] button[aria-pressed="true"] {
    color: var(--ap-foreground);
    border-bottom-color: var(--ap-accent);
}

div[data-baseweb="button-group"] button:hover {
    color: var(--ap-foreground);
}

[data-testid="stInfo"],
[data-testid="stWarning"],
[data-testid="stError"],
[data-testid="stSuccess"] {
    border-radius: 0;
    border-left-width: 2px;
}

[data-testid="stInfo"] {
    background: rgba(255, 61, 0, 0.08);
    border-left-color: var(--ap-accent);
    color: var(--ap-foreground);
}

[data-testid="stWarning"] {
    background: rgba(255, 61, 0, 0.08);
    border-left-color: var(--ap-accent);
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
    padding: 1.5rem 2rem 1.25rem 2rem;
}

hr {
    border-color: var(--ap-border);
    margin: 1.5rem 0;
}

h2 {
    font-size: 1.2rem;
    border-bottom: 1px solid var(--ap-border);
    padding-bottom: 0.45rem;
    margin-bottom: 1rem;
}

h3 {
    font-size: 1.05rem;
}

.ap-shell {
    border-top: 2px solid var(--ap-accent);
    padding: 0.35rem 0 1.75rem 0;
    margin-bottom: 1.5rem;
}

.ap-shell-kicker {
    color: var(--ap-accent);
    font-size: 0.72rem;
    font-weight: 700;
    letter-spacing: 0.18em;
    text-transform: uppercase;
    margin-bottom: 0.75rem;
}

.ap-shell-title {
    font-size: clamp(3.25rem, 6vw, 6.5rem);
    font-weight: 800;
    line-height: 0.96;
    margin: 0;
}

.ap-shell-copy {
    color: var(--ap-foreground);
    font-size: 1.05rem;
    line-height: 1.65;
    max-width: 48rem;
    margin-top: 0.9rem;
}

.ap-shell-meta {
    color: var(--ap-muted-foreground);
    font-size: 0.78rem;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    margin-top: 1rem;
}

.ap-sidebar-title {
    font-family: "Inter Tight", "Inter", system-ui, sans-serif;
    font-size: 1.25rem;
    font-weight: 800;
    letter-spacing: -0.04em;
}

@media (max-width: 900px) {
    .block-container {
        padding: 1.25rem 1rem 1rem 1rem;
    }

    .ap-shell-title {
        font-size: clamp(2.5rem, 12vw, 4rem);
    }

    [data-testid="stSidebar"] {
        min-width: unset;
        max-width: unset;
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
