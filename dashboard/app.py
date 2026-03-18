"""
Streamlit dashboard — AI Hedge Fund Research Pod.
Run: streamlit run dashboard/app.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import hashlib
import json
import re
from pathlib import Path
import streamlit as st
from config import LLM_MODEL
from src.stage_04_pipeline.ciq_admin import get_ciq_runtime_status, run_ciq_operation
from src.stage_02_valuation.templates.ic_memo import ICMemo
from src.stage_04_pipeline.comps_dashboard import build_comps_dashboard_view
from src.stage_04_pipeline.filings_browser import build_filings_browser_view
from src.stage_04_pipeline.news_materiality import build_news_materiality_view
from src.stage_04_pipeline.presentation_formatting import (
    format_metric_value,
    style_dataframe_rows,
)
from src.stage_04_pipeline.report_archive import (
    list_report_snapshots,
    load_report_snapshot,
    save_report_snapshot,
)
from src.stage_04_pipeline.dossier_index import (
    insert_decision_log_entry,
    insert_model_checkpoint,
    insert_review_log_entry,
    list_dossier_artifacts,
    list_model_checkpoints,
    list_decision_log,
    list_dossier_sections,
    list_dossier_sources,
    list_review_log,
    load_dossier_profile,
    upsert_dossier_artifact,
    upsert_dossier_profile,
    upsert_dossier_section_index,
    upsert_dossier_source,
    upsert_tracker_state,
    upsert_tracked_catalyst,
)
from src.stage_04_pipeline.dossier_workspace import (
    NOTE_TEMPLATES,
    ensure_dossier_workspace,
    ensure_dossier_source_note,
    normalize_linked_artifact_path,
    read_dossier_note,
    write_dossier_note,
)
from src.stage_04_pipeline.dossier_view import (
    build_model_checkpoint_view,
    build_publishable_memo_context,
    build_thesis_diff_view,
)
from src.stage_04_pipeline.wacc_workbench import (
    apply_wacc_methodology_selection,
    build_wacc_workbench,
    load_wacc_methodology_audit_history,
    preview_wacc_methodology_selection,
)
from src.stage_03_judgment.chat_agent import ChatAgent
from src.stage_00_data.filing_retrieval import query_filing_corpus

st.set_page_config(
    page_title="AI Research Pod",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Global CSS ────────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=IBM+Plex+Mono:wght@400;500&display=swap');

/* ── Base typography ── */
html, body { -webkit-font-smoothing: antialiased !important; -moz-osx-font-smoothing: grayscale !important; }
/* Text-bearing elements only — NOT span/div (those carry icon glyphs) */
p, li, label, h1, h2, h3, h4, h5, h6, th, td, caption,
button, input, select, textarea,
.stMarkdown p, .stMarkdown li, .stCaption, .stText,
[data-testid="stMetricLabel"], [data-testid="stMetricDelta"] {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif !important;
}
/* Monospace for numbers */
code, pre, [data-testid="stCode"] *, .stDataFrame td, .stDataFrame th,
[data-testid="stMetricValue"] {
    font-family: 'IBM Plex Mono', 'Consolas', monospace !important;
}
/* Preserve icon fonts */
[data-testid="stExpander"] details summary [data-baseweb],
[data-testid="stExpander"] details summary svg,
button svg, [role="button"] svg { font-family: unset !important; }

/* ── Base colors ── */
html, body, [data-testid="stAppViewContainer"] {
    background-color: #0a0e1a;
    color: #dce3ed;
}
[data-testid="stSidebar"] {
    background-color: #0f1623;
    border-right: 1px solid #1e2738;
    min-width: 360px !important;
    max-width: 360px !important;
}
[data-testid="stSidebar"] .stMarkdown p,
[data-testid="stSidebar"] label,
[data-testid="stSidebar"] .stCaption {
    color: #6b7a99 !important;
}

/* ── Metric cards ── */
[data-testid="stMetric"] {
    background: #111827;
    border: 1px solid #1e2738;
    border-radius: 6px;
    padding: 14px 18px;
}
[data-testid="stMetricLabel"] {
    color: #6b7a99 !important;
    font-size: 0.7rem !important;
    font-weight: 600 !important;
    text-transform: uppercase !important;
    letter-spacing: 0.08em !important;
}
[data-testid="stMetricValue"] {
    color: #eaf0fa !important;
    font-size: 1.45rem !important;
    font-weight: 700 !important;
    font-family: 'IBM Plex Mono', monospace !important;
}
[data-testid="stMetricDelta"] { font-family: 'IBM Plex Mono', monospace !important; }
[data-testid="stMetricDelta"] svg { display: none; }
[data-testid="stMetricDeltaIcon-Up"] { color: #22c55e !important; }
[data-testid="stMetricDeltaIcon-Down"] { color: #ef4444 !important; }

/* ── Tables / Dataframes ── */
[data-testid="stDataFrame"] {
    border-radius: 6px;
    overflow: hidden;
    border: 1px solid #1e2738;
}

/* ── Buttons ── */
.stButton > button {
    background: #1a4ed8;
    color: #ffffff;
    border: none;
    border-radius: 4px;
    font-weight: 600;
    font-size: 0.85rem;
    letter-spacing: 0.02em;
    text-transform: uppercase;
    transition: background 0.15s;
    font-family: 'Inter', sans-serif !important;
}
.stButton > button:hover { background: #2563eb; }
.stButton > button[kind="secondary"] {
    background: #1e2738;
    color: #a0aec0;
    border: 1px solid #2d3a52;
    text-transform: none;
}
.stButton > button[kind="secondary"]:hover { background: #2d3a52; }

/* ── Banners ── */
[data-testid="stInfo"] {
    background: #0d1e38;
    border-left: 3px solid #2563eb;
    border-radius: 4px;
    color: #93c5fd !important;
}
[data-testid="stWarning"] {
    background: #1c1500;
    border-left: 3px solid #ca8a04;
    border-radius: 4px;
    color: #fde68a !important;
}
[data-testid="stError"] {
    background: #1e0808;
    border-left: 3px solid #dc2626;
    border-radius: 4px;
}
[data-testid="stSuccess"] {
    background: #061a0c;
    border-left: 3px solid #16a34a;
    border-radius: 4px;
    color: #86efac !important;
}

/* ── Hide Streamlit chrome ── */
header[data-testid="stHeader"] { display: none !important; }
[data-testid="stToolbar"] { display: none !important; }
#MainMenu { display: none !important; }
footer { display: none !important; }

/* ── Kill all default Streamlit padding/margin ── */
.block-container {
    padding-top: 1.25rem !important;
    padding-bottom: 1rem !important;
    padding-left: 1.75rem !important;
    padding-right: 1.75rem !important;
    max-width: 100% !important;
}
[data-testid="stSidebar"] > div:first-child { padding-top: 1.25rem !important; }

/* ── Expander — force dark everywhere ── */
[data-testid="stExpander"] {
    border: 1px solid #1e2738 !important;
    border-radius: 6px !important;
    background: #111827 !important;
}
[data-testid="stExpander"] details,
[data-testid="stExpander"] details > div,
details, details > div {
    background: #111827 !important;
}
[data-testid="stExpander"] details summary,
details summary {
    background: #111827 !important;
    color: #a0aec0 !important;
    border-radius: 6px !important;
    font-weight: 500 !important;
    font-size: 0.875rem !important;
}
[data-testid="stExpander"] details summary:hover { background: #1e2738 !important; }
[data-testid="stExpanderDetails"],
.streamlit-expanderContent {
    background: #0a0e1a !important;
    border-top: 1px solid #1e2738 !important;
}
details summary > div { color: #a0aec0 !important; }

/* ── Divider ── */
hr { border-color: #1e2738 !important; margin: 1.25rem 0 !important; }

/* ── Tabs (inside charts) ── */
[data-testid="stTabs"] [role="tablist"] { border-bottom: 1px solid #1e2738; }
[data-testid="stTabs"] [role="tab"] {
    color: #6b7a99;
    font-size: 0.8rem;
    font-weight: 500;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    padding: 6px 14px;
}
[data-testid="stTabs"] [role="tab"][aria-selected="true"] {
    color: #3b82f6;
    border-bottom: 2px solid #3b82f6;
}

/* ── Sidebar navigation — styled radio as nav list ── */
[data-testid="stSidebar"] .stRadio { margin: 0 !important; }
[data-testid="stSidebar"] .stRadio > div { gap: 1px !important; }
[data-testid="stSidebar"] .stRadio > label { display: none !important; }
/* Each radio item label */
[data-testid="stSidebar"] .stRadio label {
    display: flex !important;
    align-items: center !important;
    padding: 7px 12px 7px 14px !important;
    margin: 0 !important;
    border-radius: 4px !important;
    font-size: 0.78rem !important;
    font-weight: 500 !important;
    letter-spacing: 0.01em !important;
    color: #64748b !important;
    cursor: pointer !important;
    transition: background 0.12s, color 0.12s, border-color 0.12s !important;
    border-left: 2px solid transparent !important;
    line-height: 1.3 !important;
    width: 100% !important;
    text-transform: none !important;
}
[data-testid="stSidebar"] .stRadio label:hover {
    background: #131d30 !important;
    color: #94a3b8 !important;
}
[data-testid="stSidebar"] .stRadio label[data-selected="true"],
[data-testid="stSidebar"] .stRadio label:has(input:checked) {
    background: #0d1f38 !important;
    color: #93c5fd !important;
    border-left: 2px solid #3b82f6 !important;
    font-weight: 600 !important;
}
/* Hide the radio circle dot */
[data-testid="stSidebar"] .stRadio [data-baseweb="radio"] > div:first-child {
    display: none !important;
}

/* Sidebar scrollable when content overflows */
[data-testid="stSidebar"] > div:first-child {
    overflow-y: auto !important;
    scrollbar-width: thin;
    scrollbar-color: #2d3a52 transparent;
}
[data-testid="stSidebar"] > div:first-child::-webkit-scrollbar { width: 4px; }
[data-testid="stSidebar"] > div:first-child::-webkit-scrollbar-thumb { background: #2d3a52; border-radius: 2px; }
/* Sidebar title styling */
[data-testid="stSidebar"] h2 {
    font-size: 0.95rem !important;
    font-weight: 700 !important;
    color: #c4d0e8 !important;
    letter-spacing: -0.01em !important;
    margin-bottom: 0 !important;
    border-bottom: none !important;
    padding-bottom: 0 !important;
}
[data-testid="stSidebar"] .stCaption p {
    font-size: 0.7rem !important;
    color: #2d3a52 !important;
}
/* Hide any orphaned icon-font glyph text in expander headers */
[data-testid="stExpander"] summary > div > p:empty,
[data-testid="stExpander"] summary span[aria-hidden="true"] {
    display: none !important;
}

/* ── Input fields ── */
.stTextInput input, .stNumberInput input {
    background: #1e2738 !important;
    border: 1px solid #2d3a52 !important;
    color: #dce3ed !important;
    border-radius: 4px !important;
    font-family: 'Inter', sans-serif !important;
}
.stSelectbox > div > div {
    background: #1e2738 !important;
    border: 1px solid #2d3a52 !important;
    color: #dce3ed !important;
    border-radius: 4px !important;
}

/* ── Section headings ── */
h1, h2, h3 {
    color: #eaf0fa !important;
    font-weight: 700 !important;
    letter-spacing: -0.01em !important;
}
h2 { font-size: 1.15rem !important; border-bottom: 1px solid #1e2738; padding-bottom: 0.4rem; margin-bottom: 1rem !important; }
h3 { font-size: 1rem !important; }

/* ── Scrollable analysis text ── */
.analysis-scroll {
    max-height: 500px;
    overflow-y: auto;
    background: #111827;
    border: 1px solid #1e2738;
    border-radius: 6px;
    padding: 18px 22px;
    line-height: 1.75;
    font-size: 0.875rem;
    color: #a0aec0;
    scrollbar-width: thin;
    scrollbar-color: #2d3a52 transparent;
}
.analysis-scroll::-webkit-scrollbar { width: 5px; }
.analysis-scroll::-webkit-scrollbar-thumb { background: #2d3a52; border-radius: 3px; }

/* ── Status widget ── */
[data-testid="stStatusWidget"] {
    background: #111827 !important;
    border: 1px solid #1e2738 !important;
    border-radius: 6px !important;
}

</style>
""", unsafe_allow_html=True)

# ── Sidebar ──────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## AI Research Pod")
    st.caption("Fundamental analysis pipeline")
    st.divider()

    AGENT_OPTIONS = [
        "IndustryAgent",
        "FilingsAgent",
        "EarningsAgent",
        "QoEAgent",
        "AccountingRecastAgent",
        "ValuationAgent",
        "SentimentAgent",
        "RiskAgent",
        "RiskImpactAgent",
        "ThesisAgent",
    ]

    ticker_input = st.text_input(
        "Ticker",
        placeholder="e.g. AAPL, MSFT, NVDA",
        help="US-listed tickers only (SEC EDGAR required)",
    ).upper().strip()

    run_btn = st.button("Run Analysis", type="primary", width="stretch")
    use_agent_cache = st.checkbox(
        "Use agent cache",
        value=True,
        help="Reuse cached agent outputs when inputs, prompt, and model hashes have not changed.",
    )
    with st.popover("Force refresh agents", width="stretch"):
        st.caption("Bypass cache only for the selected steps.")
        force_refresh_agents = st.multiselect(
            "Force refresh agents",
            options=AGENT_OPTIONS,
            default=[],
            label_visibility="collapsed",
            help="Downstream agents still reuse cache if their hashed inputs are unchanged.",
        )

    st.divider()
    st.caption(f"**LLM:** {LLM_MODEL}")
    st.caption("**Data:** SEC EDGAR · yfinance · CIQ")

    with st.expander("Dev: Quick Load", expanded=False):
        st.caption("Load the most recent archived snapshot for a ticker — no agents run.")
        ql_ticker = st.text_input("Ticker", value="IBM", key="quickload_ticker").upper().strip()
        if st.button("Load from archive", key="quickload_btn", width="stretch"):
            _ql_snaps = list_report_snapshots(ql_ticker, limit=1)
            if _ql_snaps:
                _ql = load_report_snapshot(int(_ql_snaps[0]["id"]))
                if _ql:
                    st.session_state.memo = ICMemo(**_ql["memo"])
                    _ds = _ql.get("dashboard_snapshot") or {}
                    st.session_state.dcf_audit_view = _ds.get("dcf_audit")
                    st.session_state.comps_view = _ds.get("comps_view")
                    st.session_state.market_intel_view = _ds.get("market_intel_view")
                    st.session_state.filings_browser_view = _ds.get("filings_browser_view")
                    st.session_state.run_trace = _ql.get("run_trace") or []
                    st.session_state.report_snapshot_id = _ql["id"]
                    st.session_state.report_source = f"archive:{_ql['id']}"
                    st.rerun()
                else:
                    st.error("Failed to load snapshot.")
            else:
                st.warning(f"No archived snapshots found for {ql_ticker}. Run the analysis first.")

    with st.expander("CIQ Tools", expanded=False):
        ciq_folder = st.text_input(
            "CIQ workbook folder",
            value=str(get_ciq_runtime_status().get("folder", "")),
            help="Folder containing populated CIQ workbooks.",
        )
        ciq_status = get_ciq_runtime_status(ciq_folder)

        st.caption(
            f"Env: `{ciq_status['recommended_env']}` | "
            f"Active: `{ciq_status['active_env'] or 'unknown'}`"
        )

        module_rows = [
            {"module": name, "available": "yes" if ok else "no"}
            for name, ok in ciq_status["module_status"].items()
        ]
        st.dataframe(module_rows, width="stretch", hide_index=True)

        if ciq_status.get("db_error"):
            st.warning(f"CIQ DB unavailable: {ciq_status['db_error']}")
        else:
            db_counts = ciq_status.get("db_counts", {})
            st.caption(
                f"DB: runs={db_counts.get('ciq_ingest_runs', 0)}, "
                f"snaps={db_counts.get('ciq_valuation_snapshot', 0)}, "
                f"comps={db_counts.get('ciq_comps_snapshot', 0)}"
            )

        candidates = ciq_status.get("candidate_workbooks", [])
        if candidates:
            st.caption("Workbooks: " + ", ".join(candidates))
        else:
            st.caption("No candidate workbooks found.")

        ciq_col1, ciq_col2, ciq_col3 = st.columns(3)
        if ciq_col1.button("Ingest saved", width="stretch"):
            try:
                st.session_state.ciq_last_result = run_ciq_operation("ingest_saved", folder_path=ciq_folder)
            except Exception as exc:
                st.session_state.ciq_last_result = {"error": str(exc)}
        if ciq_col2.button("Refresh + ingest", width="stretch"):
            try:
                st.session_state.ciq_last_result = run_ciq_operation("refresh_and_ingest", folder_path=ciq_folder)
            except Exception as exc:
                st.session_state.ciq_last_result = {"error": str(exc)}
        if ciq_col3.button("Dry-run parse", width="stretch"):
            try:
                st.session_state.ciq_last_result = run_ciq_operation("dry_run_parse", folder_path=ciq_folder)
            except Exception as exc:
                st.session_state.ciq_last_result = {"error": str(exc)}

        ciq_last_result = st.session_state.get("ciq_last_result")
        if ciq_last_result:
            if ciq_last_result.get("error"):
                st.error(f"CIQ failed: {ciq_last_result['error']}")
            else:
                report = ciq_last_result.get("report", {})
                st.success(
                    f"{ciq_last_result.get('action')}: "
                    f"ok={report.get('processed', 0)}, "
                    f"skip={report.get('skipped', 0)}, "
                    f"fail={report.get('failed', 0)}"
                )
                parse_rows = ciq_last_result.get("parse_results") or report.get("results") or []
                if parse_rows:
                    st.dataframe(parse_rows, width="stretch", hide_index=True)

    memo_preview = st.session_state.get("memo")
    if memo_preview is not None:
        st.divider()
        st.caption("Current Report")
        st.metric("Ticker", memo_preview.ticker)
        st.metric("Current Price", f"${memo_preview.valuation.current_price or 0:,.2f}")
        st.metric(
            "Base IV",
            f"${memo_preview.valuation.base:,.2f}",
            delta=f"{(memo_preview.valuation.upside_pct_base or 0) * 100:+.1f}%",
        )
        preview = st.session_state.get("workbench_preview") or st.session_state.get("wacc_preview")
        if preview:
            proposed = preview.get("proposed_iv") or preview.get("proposed", {}).get("valuation") or {}
            base_value = proposed.get("base")
            expected_value = proposed.get("expected")
            if base_value is not None:
                st.metric("Preview Base IV", f"${base_value:,.2f}")
            if expected_value is not None:
                st.metric("Preview Expected IV", f"${expected_value:,.2f}")
        st.caption(f"Source: {st.session_state.get('report_source', 'live')}")


# ── Session state ─────────────────────────────────────────────────────────────
for _k, _v in [
    ("memo", None),
    ("running", False),
    ("recommendations", None),
    ("workbench_preview", None),
    ("run_trace", []),
    ("ciq_last_result", None),
    ("dcf_audit_view", None),
    ("filings_browser_view", None),
    ("comps_view", None),
    ("market_intel_view", None),
    ("report_snapshot_id", None),
    ("report_source", "live"),
    ("wacc_preview", None),
    ("chat_history", {}), # ticker -> list of {"role": "...", "content": "...", "sources": [...]}
]:
    if _k not in st.session_state:
        st.session_state[_k] = _v


# ── Helper functions ──────────────────────────────────────────────────────────
def _to_display_value(value: float | None, unit: str) -> float:
    if value is None:
        return 0.0
    if unit == "pct":
        return float(value) * 100.0
    if unit == "usd":
        return float(value) / 1_000_000.0
    return float(value)


def _from_display_value(value: float, unit: str) -> float:
    if unit == "pct":
        return float(value) / 100.0
    if unit == "usd":
        return float(value) * 1_000_000.0
    return float(value)


def _format_unit_value(value: float | None, unit: str) -> str:
    if unit == "pct":
        return format_metric_value(value, kind="percent")
    if unit == "usd":
        if value is None:
            return "—"
        return f"${float(value) / 1_000_000:,.1f}M"
    if unit == "days":
        return format_metric_value(value, kind="days")
    if unit == "x":
        return format_metric_value(value, kind="multiple")
    return format_metric_value(value, kind="raw", decimals=4)


def _styled_rows(rows: list[dict], schema: dict[str, str]) -> list[dict]:
    return style_dataframe_rows(rows, schema)


def _input_step(unit: str) -> float:
    if unit == "pct":
        return 0.5
    if unit == "usd":
        return 10.0
    if unit == "days":
        return 1.0
    if unit == "x":
        return 0.25
    return 0.01


def _rec_unit(field: str) -> str:
    """Infer display unit from ForecastDrivers field name."""
    pct_keywords = ("margin", "growth", "yield", "rate", "pct", "tax", "wacc", "leverage")
    usd_keywords = ("debt", "assets", "liabilities", "equity", "interest", "pension",
                    "minority", "preferred", "net_debt", "capex", "revenue_base")
    multi_keywords = ("multiple", "ratio", "ebitda_x", "ebit_x")
    f = field.lower()
    if any(k in f for k in pct_keywords):
        return "pct"
    if any(k in f for k in usd_keywords):
        return "usd"
    if any(k in f for k in multi_keywords):
        return "x"
    return "raw"


def _fix_text(text: str) -> str:
    """Insert spaces before unexpected CamelCase runs in financial text.
    E.g. 'andOperatingLoss' -> 'and Operating Loss'
    Also normalises common EDGAR camelCase field names."""
    if not text:
        return text
    # Insert space before capital letter that follows a lowercase letter
    text = re.sub(r'([a-z])([A-Z])', r'\1 \2', text)
    # Clean up multiple spaces
    text = re.sub(r' {2,}', ' ', text)
    return text


def _fmt_sens_table(rows: list[dict]) -> list[dict]:
    """Format sensitivity table rows so IV values show as $XX.XX strings."""
    formatted = []
    for row in rows:
        new_row = {}
        for k, v in row.items():
            if k == "wacc_pct":
                new_row[k] = f"{v:.2f}%"
            elif isinstance(v, (int, float)):
                new_row[k] = f"${v:,.2f}"
            else:
                new_row[k] = v
        formatted.append(new_row)
    return formatted


# ── DCF Charts ────────────────────────────────────────────────────────────────
def _render_dcf_charts(audit: dict) -> None:
    try:
        import plotly.graph_objects as go
    except ImportError:
        st.info("Install `plotly` to enable DCF charts.")
        return

    # Dark template for all charts
    _DARK = dict(
        plot_bgcolor="#161b22",
        paper_bgcolor="#161b22",
        font=dict(color="#8b949e", size=12),
        xaxis=dict(gridcolor="#21262d", zerolinecolor="#30363d"),
        yaxis=dict(gridcolor="#21262d", zerolinecolor="#30363d"),
        margin=dict(l=20, r=20, t=40, b=20),
        legend=dict(
            orientation="h", y=-0.15,
            bgcolor="rgba(0,0,0,0)", font=dict(color="#c9d1d9"),
        ),
    )

    def _layout(**overrides):
        merged = dict(_DARK)
        merged.update(overrides)
        return merged

    BLUE = "#388bfd"
    GREEN = "#3fb950"
    ORANGE = "#d29922"
    RED = "#f85149"
    TEAL = "#58a6ff"

    chart_series = audit.get("chart_series") or {}
    forecast_tab, valuation_tab, sensitivity_tab, risk_tab, chat_tab = st.tabs(
        ["Forecast", "Valuation", "Sensitivity", "Risk Impact", "Chat with Filings"]
    )

    with forecast_tab:
        projection = chart_series.get("projection_curve") or []
        if projection:
            fig = go.Figure()
            fig.add_trace(go.Bar(
                x=[row["year"] for row in projection],
                y=[row["revenue_mm"] for row in projection],
                name="Revenue ($mm)",
                marker_color=BLUE,
                opacity=0.8,
                yaxis="y1",
            ))
            fig.add_trace(go.Scatter(
                x=[row["year"] for row in projection],
                y=[row["ebit_margin_pct"] for row in projection],
                name="EBIT Margin (%)",
                mode="lines+markers",
                line=dict(color=GREEN, width=2),
                marker=dict(size=6),
                yaxis="y2",
            ))
            fig.update_layout(
                **_layout(
                    height=360,
                    title=dict(text="Revenue & EBIT Margin Projection", x=0.02, font=dict(color="#c9d1d9", size=14)),
                    yaxis=dict(
                        title=dict(text="Revenue ($mm)", font=dict(color=BLUE)),
                        tickfont=dict(color=BLUE),
                    ),
                    yaxis2=dict(
                        title=dict(text="EBIT Margin (%)", font=dict(color=GREEN)),
                        tickfont=dict(color=GREEN),
                        overlaying="y",
                        side="right",
                    ),
                ),
            )
            st.plotly_chart(fig, width="stretch")

        fcff = chart_series.get("fcff_curve") or []
        if fcff:
            fig = go.Figure()
            fig.add_trace(go.Bar(
                x=[row["year"] for row in fcff],
                y=[row["fcff_mm"] for row in fcff],
                name="FCFF ($mm)",
                marker_color=TEAL,
                opacity=0.8,
            ))
            fig.add_trace(go.Scatter(
                x=[row["year"] for row in fcff],
                y=[row["nopat_mm"] for row in fcff],
                name="NOPAT ($mm)",
                mode="lines+markers",
                line=dict(color=ORANGE, width=2),
                marker=dict(size=6),
            ))
            fig.update_layout(
                **_layout(
                    height=360,
                    title=dict(text="FCFF & NOPAT ($mm)", x=0.02, font=dict(color="#c9d1d9", size=14)),
                ),
            )
            st.plotly_chart(fig, width="stretch")

    with valuation_tab:
        scenario_iv = chart_series.get("scenario_iv") or []
        if scenario_iv:
            colors = [RED, BLUE, GREEN, ORANGE]
            fig = go.Figure()
            fig.add_trace(go.Bar(
                x=[row["scenario"].title() for row in scenario_iv],
                y=[row["intrinsic_value"] for row in scenario_iv],
                marker_color=colors[:len(scenario_iv)],
                text=[f"${row['intrinsic_value']:,.2f}" for row in scenario_iv],
                textposition="outside",
                textfont=dict(color="#c9d1d9"),
            ))
            current_price = audit.get("current_price")
            if current_price is not None:
                fig.add_hline(
                    y=current_price,
                    line_dash="dash",
                    line_color="#d29922",
                    annotation_text=f"  Price ${current_price:,.2f}",
                    annotation_font_color="#d29922",
                )
            fig.update_layout(
                **_layout(
                    height=360,
                    title=dict(text="Intrinsic Value by Scenario", x=0.02, font=dict(color="#c9d1d9", size=14)),
                    showlegend=False,
                ),
            )
            st.plotly_chart(fig, width="stretch")

        ev_bridge = chart_series.get("ev_bridge_waterfall") or []
        if ev_bridge:
            measure = []
            for i, row in enumerate(ev_bridge):
                if i == len(ev_bridge) - 1:
                    measure.append("total")
                elif row["value_mm"] < 0:
                    measure.append("relative")
                else:
                    measure.append("relative")
            fig = go.Figure(go.Waterfall(
                x=[row["component"] for row in ev_bridge],
                y=[row["value_mm"] for row in ev_bridge],
                measure=measure,
                connector=dict(line=dict(color="#30363d")),
                increasing=dict(marker=dict(color=GREEN)),
                decreasing=dict(marker=dict(color=RED)),
                totals=dict(marker=dict(color=BLUE)),
                textfont=dict(color="#c9d1d9"),
            ))
            fig.update_layout(
                **_layout(
                    height=360,
                    title=dict(text="EV → Equity Bridge ($mm)", x=0.02, font=dict(color="#c9d1d9", size=14)),
                ),
            )
            st.plotly_chart(fig, width="stretch")

    with sensitivity_tab:
        heat_cols = st.columns(2)
        sens_growth = audit.get("sensitivity", {}).get("wacc_x_terminal_growth") or []
        sens_exit = audit.get("sensitivity", {}).get("wacc_x_exit_multiple") or []

        def _heatmap(data, title, col):
            if not data:
                return
            x_labels = [k for k in data[0].keys() if k != "wacc_pct"]
            y_vals = [row["wacc_pct"] for row in data]
            z_vals = [[row[k] for k in x_labels] for row in data]
            y_labels = [f"{v:.1f}%" for v in y_vals]
            fig = go.Figure(data=go.Heatmap(
                x=x_labels,
                y=y_labels,
                z=z_vals,
                colorscale=[[0, "#f85149"], [0.5, "#d29922"], [1, "#3fb950"]],
                text=[[f"${v:,.2f}" for v in row] for row in z_vals],
                texttemplate="%{text}",
                textfont=dict(size=11, color="#ffffff"),
                colorbar=dict(tickfont=dict(color="#8b949e"), title=dict(text="IV", font=dict(color="#8b949e"))),
            ))
            fig.update_layout(
                **_layout(
                    height=300,
                    title=dict(text=title, x=0.02, font=dict(color="#c9d1d9", size=13)),
                    xaxis=dict(tickfont=dict(color="#c9d1d9")),
                    yaxis=dict(tickfont=dict(color="#c9d1d9")),
                ),
            )
            col.plotly_chart(fig, width="stretch")

        _heatmap(sens_growth, "WACC × Terminal Growth", heat_cols[0])
        _heatmap(sens_exit, "WACC × Exit Multiple", heat_cols[1])

    with risk_tab:
        risk_view = audit.get("risk_impact")
        overlays = chart_series.get("risk_overlay") or []
        if not risk_view or not risk_view.get("available") or not overlays:
            st.info("No quantified risk overlays available for this run.")
        else:
            top = st.columns(3)
            top[0].metric("Base IV", f"${risk_view.get('base_iv', 0):,.2f}")
            top[1].metric("Risk-Adjusted IV", f"${risk_view.get('risk_adjusted_expected_iv', 0):,.2f}")
            delta = risk_view.get("risk_adjusted_delta_pct")
            top[2].metric("Risk Adjustment", f"{delta*100:+.1f}%" if delta is not None else "—")

            fig = go.Figure()
            fig.add_trace(go.Bar(
                x=[row["risk_name"] for row in overlays],
                y=[row["stressed_iv"] for row in overlays],
                text=[f"p={row['probability']:.0%}" for row in overlays],
                textposition="outside",
                textfont=dict(color="#c9d1d9"),
                marker_color=RED,
                name="Stressed IV",
            ))
            fig.add_hline(y=risk_view.get("base_iv", 0), line_dash="dash", line_color=BLUE, annotation_text="  Base IV", annotation_font_color=BLUE)
            fig.add_hline(y=risk_view.get("risk_adjusted_expected_iv", 0), line_dash="dot", line_color=ORANGE, annotation_text="  Risk-Adj. EV", annotation_font_color=ORANGE)
            fig.update_layout(
                **_layout(
                    height=360,
                    title=dict(text="Risk Stress Tests", x=0.02, font=dict(color="#c9d1d9", size=14)),
                ),
            )
            st.plotly_chart(fig, width="stretch")
            st.dataframe(risk_view.get("overlay_results") or [], width="stretch", hide_index=True)

    with chat_tab:
        ticker = audit.get("ticker", "UNKNOWN")
        st.markdown(f"### Chat with {ticker} Filings")
        st.caption("Ask questions about the company's financials, risks, and guidance directly using RAG indexing over EDGAR filings.")

        # Display history for this ticker
        ticker_history = st.session_state.chat_history.setdefault(ticker, [])
        
        chat_container = st.container(height=400)
        with chat_container:
            for message in ticker_history:
                with st.chat_message(message["role"]):
                    st.markdown(message["content"])
                    if message.get("sources"):
                        with st.expander("Sources"):
                            for source in message["sources"]:
                                st.caption(f"- {source}")

        if prompt := st.chat_input("Ask a question about the filings..."):
            ticker_history.append({"role": "user", "content": prompt})
            with chat_container:
                with st.chat_message("user"):
                    st.markdown(prompt)

                with st.chat_message("assistant"):
                    with st.spinner("Searching SEC EDGAR corpus..."):
                        context_bundle = query_filing_corpus(ticker, prompt, top_k=5)
                        
                        if context_bundle.retrieval_summary.get("error"):
                            err = context_bundle.retrieval_summary["error"]
                            st.error(f"Retrieval failed: {err}")
                            full_response = "I encountered an error retrieving the filings."
                            sources = []
                        else:
                            with st.spinner("Analyzing text..."):
                                agent = ChatAgent()
                                response = agent.answer_query(prompt, context_bundle)
                                if response.error:
                                    st.error(response.error)
                                    full_response = "I encountered an error generating the response."
                                    sources = []
                                else:
                                    full_response = response.answer
                                    sources = response.sources

                        st.markdown(full_response)
                        if sources:
                            with st.expander("Sources"):
                                for source in sources:
                                    st.caption(f"- {source}")
                                    
            ticker_history.append({"role": "assistant", "content": full_response, "sources": sources})
            st.rerun()


# ── Run pipeline ──────────────────────────────────────────────────────────────
if run_btn and ticker_input:
    st.session_state.running = True
    st.session_state.memo = None
    st.session_state.recommendations = None
    st.session_state.run_trace = []
    st.session_state.dcf_audit_view = None
    st.session_state.filings_browser_view = None
    st.session_state.comps_view = None
    st.session_state.market_intel_view = None
    st.session_state.wacc_preview = None

    with st.status(f"Running 10-agent analysis for **{ticker_input}**...", expanded=True) as status:
        steps = [
            "Fetching market snapshot",
            "0a/9  IndustryAgent — sector benchmarks & recent events",
            "1/9  FilingsAgent — parsing SEC 10-K / 10-Q",
            "2/9  EarningsAgent — analysing earnings calls",
            "2a/9  QoEAgent — quality-of-earnings signals + EBIT normalisation",
            "2b/9  AccountingRecastAgent — proposing EBIT and EV-bridge reclassifications",
            "3/9  ValuationAgent — running DCF + comps",
            "4/9  SentimentAgent — scoring news & analyst positioning",
            "5/9  RiskAgent — sizing position",
            "5a/9  RiskImpactAgent — converting key risks into valuation overlays",
            "6/9  ThesisAgent — synthesizing IC memo",
        ]
        placeholders = {s: st.empty() for s in steps}
        for s in steps:
            placeholders[s].markdown(f"⏳ {s}")

        try:
            from src.stage_04_pipeline.orchestrator import PipelineOrchestrator

            class StreamingOrchestrator(PipelineOrchestrator):
                def _on_step(self, step_name: str) -> None:
                    if step_name in placeholders:
                        placeholders[step_name].markdown(f"Running: **{step_name}**")

                def _on_done(self, step_name: str, detail: str = "") -> None:
                    if step_name in placeholders:
                        msg = f"Done: {step_name}"
                        if detail:
                            msg += f" — {detail}"
                        placeholders[step_name].markdown(msg)

                def _on_warn(self, message: str) -> None:
                    status.write(f"Warning: {message}")

            orch = StreamingOrchestrator()
            memo = orch.run(
                ticker_input,
                use_cache=use_agent_cache,
                force_refresh_agents=set(force_refresh_agents),
            )
            st.session_state.memo = memo
            st.session_state.run_trace = orch.last_run_trace
            st.session_state.report_source = "live"
            try:
                from src.stage_04_pipeline.recommendations import write_recommendations
                recs = orch.collect_recommendations(ticker_input)
                write_recommendations(recs)
                st.session_state.recommendations = recs
            except Exception:
                st.session_state.recommendations = None
            try:
                from src.stage_04_pipeline.dcf_audit import build_dcf_audit_view

                dcf_audit_view = build_dcf_audit_view(memo.ticker, risk_output=memo.risk_impact)
                filings_browser_view = build_filings_browser_view(memo.ticker)
                comps_view = build_comps_dashboard_view(memo.ticker)
                market_intel_view = build_news_materiality_view(memo.ticker)

                st.session_state.dcf_audit_view = dcf_audit_view
                st.session_state.filings_browser_view = filings_browser_view
                st.session_state.comps_view = comps_view
                st.session_state.market_intel_view = market_intel_view
                st.session_state.report_snapshot_id = save_report_snapshot(
                    memo.ticker,
                    memo,
                    dcf_audit=dcf_audit_view,
                    comps_view=comps_view,
                    market_intel_view=market_intel_view,
                    filings_browser_view=filings_browser_view,
                    run_trace=orch.last_run_trace,
                )
            except Exception as snapshot_exc:
                status.write(f"Archive/view build warning: {snapshot_exc}")
            status.update(label=f"Analysis complete — **{ticker_input}**", state="complete")

        except Exception as e:
            status.update(label=f"Pipeline error: {e}", state="error")

st.session_state.running = False
memo = st.session_state.memo

# ── Navigation (always visible, even without a ticker) ─────────────────────────
SECTION_GROUPS = {
    "Deep Dive": ["Company Hub", "Business", "Model & Valuation", "Sources", "Thesis Tracker", "Decision Log", "Review Log", "Publishable Memo"],
    "Research": ["Thesis", "Recommendations", "Risk", "Past Reports"],
    "Valuation": ["Valuation", "DCF Audit", "IV History", "Assumption Lab", "WACC Lab", "Comps"],
    "Filings": ["Filings", "Earnings", "Forensic Scores", "Filings Browser"],
    "Market Intel": ["Sentiment", "News & Materiality", "Macro", "Revisions", "Factor Exposure"],
    "Ops": ["Pipeline", "Portfolio Risk", "Export", "Raw JSON"],
}

# Sections that work without a ticker/memo
_TICKER_FREE_SECTIONS = {"Macro", "Portfolio Risk", "Pipeline"}

selected_group = st.segmented_control(
    "Workspace",
    options=list(SECTION_GROUPS.keys()),
    default="Market Intel" if memo is None else "Research",
    key="main_dashboard_group",
)
selected_section = st.segmented_control(
    "Section",
    options=SECTION_GROUPS[selected_group],
    default="Macro" if (memo is None and "Macro" in SECTION_GROUPS[selected_group]) else SECTION_GROUPS[selected_group][0],
    key=f"dashboard_section_{selected_group}",
)

st.divider()

if memo is None and selected_section not in _TICKER_FREE_SECTIONS:
    st.markdown("""
### Enter a ticker to get started

Run the full 10-agent analysis from the sidebar, or navigate to **Market Intel → Macro** or **Ops → Portfolio Risk** to explore ticker-independent views.

| Agent | Role |
|---|---|
| **IndustryAgent** | Sector benchmarks and current industry context |
| **FilingsAgent** | 10-K/10-Q: revenue trends, margins, FCF, red flags |
| **EarningsAgent** | Earnings calls, guidance vs actuals, management tone |
| **QoEAgent** | Quality-of-earnings issues and EBIT normalisation |
| **AccountingRecastAgent** | Operating vs non-operating / bridge reclassifications |
| **ValuationAgent** | Deterministic DCF + comps — bear / base / bull IV |
| **SentimentAgent** | News narrative and analyst positioning score |
| **RiskAgent** | Position sizing based on conviction + volatility |
| **RiskImpactAgent** | Downside valuation overlays and risk-adjusted IV |
| **ThesisAgent** | IC memo and variant thesis prompt |

> **Your job:** Write the variant thesis. The AI surfaces what's known; you identify why the market is wrong.
""")
    st.stop()


# ── IC Memo Header (only when memo is loaded) ──────────────────────────────────
if memo is not None:
    action_color = {"BUY": "BUY", "SELL SHORT": "SHORT", "WATCH": "WATCH", "PASS": "PASS"}.get(memo.action, "")

    st.markdown(f"## {memo.ticker} — {memo.company_name}")
    st.caption(f"{memo.sector}  ·  {memo.date}  ·  Analyst: {memo.analyst}")

    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("Action", memo.action)
    col2.metric("Conviction", memo.conviction.upper())
    col3.metric("Current Price", f"${memo.valuation.current_price or 0:,.2f}")
    col4.metric("Base Case IV", f"${memo.valuation.base:,.2f}")
    col5.metric(
        "Upside (base)",
        f"{(memo.valuation.upside_pct_base or 0)*100:+.1f}%",
    )

    st.info(f"**One-liner:** {memo.one_liner}")
    st.warning(
        f"**Variant Thesis:** {memo.variant_thesis_prompt}\n\n"
        "_This is the question the AI cannot answer for you. Answer this before sizing the position._"
    )


def _get_cached_view(key: str, builder, *args, **kwargs):
    current = st.session_state.get(key)
    if current is None:
        try:
            current = builder(*args, **kwargs)
        except Exception as exc:
            return {"available": False, "error": str(exc)}
        st.session_state[key] = current
    return current


def _sync_dossier_foundation(ticker: str, company_name: str) -> dict:
    workspace = ensure_dossier_workspace(ticker, company_name)
    root_path = Path(workspace["root_path"])
    upsert_dossier_profile(
        {
            "ticker": ticker,
            "company_name": company_name,
            "dossier_root_path": workspace["root_path"],
            "notes_root_path": workspace["notes_root_path"],
            "model_root_path": workspace["model_root_path"],
            "exports_root_path": workspace["exports_root_path"],
            "status": "active",
            "current_model_version": None,
            "current_thesis_version": None,
            "current_publishable_memo_version": None,
        }
    )
    for note_slug, path_text in workspace["note_paths"].items():
        note_path = Path(path_text)
        note_text = note_path.read_text(encoding="utf-8")
        note_meta = NOTE_TEMPLATES[note_slug]
        upsert_dossier_section_index(
            {
                "ticker": ticker,
                "note_slug": note_slug,
                "note_title": note_meta["title"],
                "relative_path": note_path.relative_to(root_path).as_posix(),
                "section_kind": note_meta["section_kind"],
                "is_private": note_meta["is_private"],
                "content_hash": hashlib.sha256(note_text.encode("utf-8")).hexdigest(),
                "metadata_json": json.dumps({"seeded": True}, sort_keys=True),
            }
        )
    return workspace


# ── Section: Company Hub ─────────────────────────────────────────────────────
if selected_section == "Company Hub":
    st.subheader("Company Hub")
    st.caption("Initialize and inspect the file-backed dossier workspace for this ticker.")

    profile = load_dossier_profile(memo.ticker)
    if st.button("Initialize Dossier Workspace", type="primary", key="init_dossier_workspace"):
        _sync_dossier_foundation(memo.ticker, memo.company_name)
        profile = load_dossier_profile(memo.ticker)
        st.success("Dossier workspace initialized and indexed.")

    if profile is None:
        st.info("No dossier exists yet for this ticker. Initialize the workspace to create the note skeleton and local index.")
    else:
        sections = list_dossier_sections(memo.ticker)
        col1, col2, col3 = st.columns(3)
        col1.metric("Dossier Status", profile.get("status", "active"))
        col2.metric("Indexed Notes", str(len(sections)))
        col3.metric("Ticker", memo.ticker)

        st.markdown("#### Workspace Paths")
        st.code(
            "\n".join(
                [
                    f"Root: {profile['dossier_root_path']}",
                    f"Notes: {profile['notes_root_path']}",
                    f"Model: {profile['model_root_path']}",
                    f"Exports: {profile['exports_root_path']}",
                ]
            )
        )

        if sections:
            st.markdown("#### Note Skeleton")
            st.dataframe(
                [
                    {
                        "Slug": row["note_slug"],
                        "Title": row["note_title"],
                        "Kind": row["section_kind"],
                        "Path": row["relative_path"],
                    }
                    for row in sections
                ],
                width="stretch",
                hide_index=True,
            )

        hub_text = read_dossier_note(memo.ticker, "company_hub")
        st.markdown("#### Hub Note")
        st.text_area("Hub note content", value=hub_text, height=320, disabled=True, key="company_hub_preview")


# ── Section: Business ────────────────────────────────────────────────────────
if selected_section == "Business":
    st.subheader("Business")
    profile = load_dossier_profile(memo.ticker)
    if profile is None:
        st.info("Initialize the dossier in Company Hub before editing business notes.")
    else:
        business_tabs = st.tabs(["Business & Industry", "Financial History", "Management", "KPI Tracker"])
        for tab, note_slug, title in zip(
            business_tabs,
            ["business", "financial_history", "management", "kpi_tracker"],
            ["Business & Industry", "Financial History", "Management & Capital Allocation", "KPI Tracker"],
        ):
            with tab:
                current_text = read_dossier_note(memo.ticker, note_slug)
                edited_text = st.text_area(
                    title,
                    value=current_text,
                    height=320,
                    key=f"dossier_note_{note_slug}",
                )
                if st.button(f"Save {title}", key=f"save_dossier_note_{note_slug}"):
                    write_dossier_note(memo.ticker, note_slug, edited_text)
                    _sync_dossier_foundation(memo.ticker, memo.company_name)
                    st.success(f"Saved {title}.")


# ── Section: Sources ─────────────────────────────────────────────────────────
if selected_section == "Sources":
    st.subheader("Sources")
    profile = load_dossier_profile(memo.ticker)
    if profile is None:
        st.info("Initialize the dossier in Company Hub before registering sources and artifacts.")
    else:
        existing_sources = list_dossier_sources(memo.ticker)
        existing_artifacts = list_dossier_artifacts(memo.ticker)
        next_source_id = f"S-{len(existing_sources) + 1:03d}"

        st.markdown("#### Register Source")
        with st.form("dossier_source_form", clear_on_submit=False):
            source_id = st.text_input("Source ID", value=next_source_id)
            source_title = st.text_input("Title", value="")
            source_type = st.selectbox(
                "Source Type",
                ["10-K", "10-Q", "8-K", "earnings_transcript", "investor_presentation", "industry_report", "article", "internal_model_export", "other"],
            )
            source_date = st.text_input("Source Date", value="")
            source_file_path = st.text_input("File Path", value="")
            source_external_uri = st.text_input("External URI", value="")
            source_why = st.text_area("Why It Matters", value="", height=100)
            save_source = st.form_submit_button("Save Source")

        if save_source:
            source_note_path = ensure_dossier_source_note(memo.ticker, source_id.strip() or next_source_id, source_title.strip() or "Untitled Source")
            upsert_dossier_source(
                {
                    "ticker": memo.ticker,
                    "source_id": source_id.strip() or next_source_id,
                    "title": source_title.strip() or "Untitled Source",
                    "source_type": source_type,
                    "source_date": source_date.strip() or None,
                    "access_date": memo.date,
                    "why_it_matters": source_why.strip(),
                    "file_path": source_file_path.strip() or None,
                    "external_uri": source_external_uri.strip() or None,
                    "zotero_key": None,
                    "relative_source_note_path": Path(source_note_path).relative_to(Path(profile["dossier_root_path"])).as_posix(),
                    "supports_json": json.dumps({}, sort_keys=True),
                    "limitations_text": "",
                }
            )
            st.success("Source saved.")
            existing_sources = list_dossier_sources(memo.ticker)

        if existing_sources:
            st.dataframe(
                [
                    {
                        "Source ID": row["source_id"],
                        "Title": row["title"],
                        "Type": row["source_type"],
                        "Date": row["source_date"] or "—",
                        "Note": row["relative_source_note_path"] or "—",
                    }
                    for row in existing_sources
                ],
                width="stretch",
                hide_index=True,
            )

        st.markdown("#### Link Artifact")
        with st.form("dossier_artifact_form", clear_on_submit=False):
            artifact_key = st.text_input("Artifact Key", value="")
            artifact_title = st.text_input("Artifact Title", value="")
            artifact_type = st.selectbox(
                "Artifact Type",
                ["excel_model", "export_png", "export_pdf", "filing_pdf", "transcript_pdf", "deck_pdf", "memo_pdf", "memo_html", "other"],
            )
            artifact_path_mode = st.selectbox("Path Mode", ["absolute", "repo_relative", "dossier_relative", "uri"])
            artifact_path_value = st.text_input("Path / URI", value="")
            artifact_note_slug = st.selectbox("Linked Note", options=list(NOTE_TEMPLATES.keys()), index=4)
            artifact_model_version = st.text_input("Model Version", value="")
            save_artifact = st.form_submit_button("Save Artifact")

        if save_artifact:
            normalized = normalize_linked_artifact_path(artifact_path_value.strip(), path_mode=artifact_path_mode)
            upsert_dossier_artifact(
                {
                    "ticker": memo.ticker,
                    "artifact_key": artifact_key.strip() or f"artifact_{len(existing_artifacts) + 1}",
                    "artifact_type": artifact_type,
                    "title": artifact_title.strip() or artifact_type,
                    "path_mode": normalized["path_mode"],
                    "path_value": normalized["path_value"],
                    "source_id": None,
                    "linked_note_slug": artifact_note_slug,
                    "linked_snapshot_id": None,
                    "model_version": artifact_model_version.strip() or None,
                    "is_private": 0,
                    "metadata_json": json.dumps({}, sort_keys=True),
                }
            )
            st.success("Artifact saved.")
            existing_artifacts = list_dossier_artifacts(memo.ticker)

        if existing_artifacts:
            st.dataframe(
                [
                    {
                        "Artifact": row["artifact_key"],
                        "Type": row["artifact_type"],
                        "Title": row["title"],
                        "Path Mode": row["path_mode"],
                        "Linked Note": row["linked_note_slug"] or "—",
                        "Model Version": row["model_version"] or "—",
                    }
                    for row in existing_artifacts
                ],
                width="stretch",
                hide_index=True,
            )


# ── Section: Model & Valuation ───────────────────────────────────────────────
if selected_section == "Model & Valuation":
    st.subheader("Model & Valuation")
    profile = load_dossier_profile(memo.ticker)
    if profile is None:
        st.info("Initialize the dossier in Company Hub before recording checkpoints.")
    else:
        st.markdown("#### Current Deterministic Valuation")
        col1, col2, col3 = st.columns(3)
        col1.metric("Current Price", format_metric_value(memo.valuation.current_price, kind="price"))
        col2.metric("Base IV", format_metric_value(memo.valuation.base, kind="price"))
        col3.metric("Upside (base)", format_metric_value(memo.valuation.upside_pct_base, kind="percent"))

        with st.form("model_checkpoint_form", clear_on_submit=False):
            model_version = st.text_input("Model Version", value=profile.get("current_model_version") or "")
            thesis_version = st.text_input("Thesis Version", value=profile.get("current_thesis_version") or "")
            change_reason = st.text_area("Change Reason", value="", height=100)
            save_checkpoint = st.form_submit_button("Save Checkpoint")

        if save_checkpoint:
            insert_model_checkpoint(
                {
                    "ticker": memo.ticker,
                    "checkpoint_ts": memo.date,
                    "model_version": model_version.strip() or "unspecified",
                    "artifact_key": "excel_model_main",
                    "snapshot_id": st.session_state.get("report_snapshot_id"),
                    "valuation_json": json.dumps(
                        {
                            "base_iv": memo.valuation.base,
                            "bear_iv": memo.valuation.bear,
                            "bull_iv": memo.valuation.bull,
                            "current_price": memo.valuation.current_price,
                            "upside_pct": memo.valuation.upside_pct_base,
                        },
                        sort_keys=True,
                    ),
                    "drivers_summary_json": json.dumps({"wacc": None}, sort_keys=True),
                    "change_reason": change_reason.strip(),
                    "thesis_version": thesis_version.strip() or None,
                    "source_ids_json": json.dumps([row["source_id"] for row in list_dossier_sources(memo.ticker)], sort_keys=True),
                    "created_by": "pm",
                }
            )
            upsert_dossier_profile(
                {
                    **profile,
                    "current_model_version": model_version.strip() or None,
                    "current_thesis_version": thesis_version.strip() or None,
                }
            )
            st.success("Checkpoint saved.")
            profile = load_dossier_profile(memo.ticker)

        checkpoint_view = build_model_checkpoint_view(memo.ticker)
        if checkpoint_view.get("available"):
            if checkpoint_view["diff"].get("base_iv_delta") is not None:
                st.info(f"Latest vs prior base IV delta: {checkpoint_view['diff']['base_iv_delta']:+.1f}")

            st.dataframe(
                [
                    {
                        "Checkpoint": row["checkpoint_ts"],
                        "Model Version": row["model_version"],
                        "Reason": row["change_reason"] or "—",
                        "Snapshot": row["snapshot_id"] or "—",
                    }
                    for row in list_model_checkpoints(memo.ticker)
                ],
                width="stretch",
                hide_index=True,
            )


# ── Section: Thesis Tracker ──────────────────────────────────────────────────
if selected_section == "Thesis Tracker":
    st.subheader("Thesis Tracker")
    thesis_view = _get_cached_view("dossier_thesis_tracker_view", build_thesis_diff_view, memo.ticker)
    if not thesis_view.get("available"):
        st.info("No archived dossier thesis history is available yet.")
    else:
        col1, col2, col3 = st.columns(3)
        col1.metric("Latest Action", thesis_view["latest_snapshot"].get("action") or "—")
        col2.metric("Prior Action", thesis_view["prior_snapshot"].get("action") if thesis_view.get("prior_snapshot") else "—")
        col3.metric(
            "Base IV Delta",
            format_metric_value(thesis_view["snapshot_diff"].get("base_iv_delta"), kind="price")
            if thesis_view["snapshot_diff"].get("base_iv_delta") is not None
            else "—",
        )
        st.markdown("#### Snapshot Diff")
        st.json(thesis_view["snapshot_diff"])
        if thesis_view.get("current_tracker_state"):
            st.markdown("#### Current PM Tracker State")
            st.json(thesis_view["current_tracker_state"])
        if thesis_view.get("catalysts"):
            st.markdown("#### Tracked Catalysts")
            st.dataframe(
                [
                    {
                        "Title": row["title"],
                        "Status": row["status"],
                        "Priority": row["priority"],
                        "Reason": row.get("status_reason") or "—",
                    }
                    for row in thesis_view["catalysts"]
                ],
                width="stretch",
                hide_index=True,
            )

        with st.form("tracker_state_form", clear_on_submit=False):
            overall_status = st.selectbox("Overall Status", ["intact", "monitor", "validated", "broken"], index=1)
            pm_action = st.selectbox("PM Action", ["BUY", "SELL SHORT", "WATCH", "PASS"], index=2)
            pm_conviction = st.selectbox("PM Conviction", ["high", "medium", "low"], index=1)
            summary_note = st.text_area("Summary Note", value="", height=80)
            save_tracker_state = st.form_submit_button("Save Tracker State")

        if save_tracker_state:
            upsert_tracker_state(
                {
                    "ticker": memo.ticker,
                    "overall_status": overall_status,
                    "pm_action": pm_action,
                    "pm_conviction": pm_conviction,
                    "summary_note": summary_note.strip(),
                    "pillar_states_json": json.dumps({}, sort_keys=True),
                    "open_questions_json": json.dumps(memo.open_questions, sort_keys=True),
                    "last_reviewed_at": memo.date,
                    "latest_snapshot_id": thesis_view["latest_snapshot"].get("id"),
                    "metadata_json": json.dumps({}, sort_keys=True),
                }
            )
            st.session_state.pop("dossier_thesis_tracker_view", None)
            thesis_view = _get_cached_view("dossier_thesis_tracker_view", build_thesis_diff_view, memo.ticker)
            st.success("Tracker state saved.")

        catalyst_options = {
            f"{row['title']} ({row['status']})": row
            for row in (thesis_view.get("catalysts") or [])
        }
        if catalyst_options:
            with st.form("tracker_catalyst_form", clear_on_submit=False):
                catalyst_label = st.selectbox("Catalyst", options=list(catalyst_options.keys()))
                catalyst_status = st.selectbox("Status", ["open", "watching", "hit", "delayed", "missed", "killed"], index=1)
                catalyst_reason = st.text_area("Status Reason", value="", height=80)
                save_catalyst_state = st.form_submit_button("Save Catalyst Status")

            if save_catalyst_state:
                selected_catalyst = catalyst_options[catalyst_label]
                upsert_tracked_catalyst(
                    {
                        "ticker": memo.ticker,
                        "catalyst_key": selected_catalyst["catalyst_key"],
                        "title": selected_catalyst["title"],
                        "description": selected_catalyst.get("description"),
                        "priority": selected_catalyst.get("priority", "medium"),
                        "status": catalyst_status,
                        "expected_date": selected_catalyst.get("expected_date"),
                        "expected_window_start": selected_catalyst.get("expected_window_start"),
                        "expected_window_end": selected_catalyst.get("expected_window_end"),
                        "status_reason": catalyst_reason.strip(),
                        "source_origin": selected_catalyst.get("source_origin", "pm"),
                        "source_snapshot_id": selected_catalyst.get("source_snapshot_id"),
                        "evidence_json": json.dumps({}, sort_keys=True),
                    }
                )
                st.session_state.pop("dossier_thesis_tracker_view", None)
                st.success("Catalyst status saved.")


# ── Section: Decision Log ────────────────────────────────────────────────────
if selected_section == "Decision Log":
    st.subheader("Decision Log")
    profile = load_dossier_profile(memo.ticker)
    if profile is None:
        st.info("Initialize the dossier in Company Hub before writing decisions.")
    else:
        with st.form("decision_log_form", clear_on_submit=False):
            decision_title = st.text_input("Decision Title", value="")
            decision_action = st.selectbox("Action", ["BUY", "SELL SHORT", "WATCH", "PASS", "TRIM", "EXIT"])
            decision_conviction = st.selectbox("Conviction", ["high", "medium", "low"], index=1)
            beliefs_text = st.text_area("Beliefs", value="", height=100)
            evidence_text = st.text_area("Evidence", value="", height=80)
            assumptions_text = st.text_area("Assumptions", value="", height=80)
            falsifiers_text = st.text_area("Falsifiers", value="", height=80)
            review_due_date = st.text_input("Review Due Date", value="")
            save_decision = st.form_submit_button("Save Decision")

        if save_decision:
            insert_decision_log_entry(
                {
                    "ticker": memo.ticker,
                    "decision_ts": memo.date,
                    "decision_title": decision_title.strip() or "Untitled Decision",
                    "action": decision_action,
                    "conviction": decision_conviction,
                    "beliefs_text": beliefs_text.strip() or memo.one_liner,
                    "evidence_text": evidence_text.strip(),
                    "assumptions_text": assumptions_text.strip(),
                    "falsifiers_text": falsifiers_text.strip(),
                    "review_due_date": review_due_date.strip() or None,
                    "snapshot_id": st.session_state.get("report_snapshot_id"),
                    "model_checkpoint_id": None,
                    "private_notes_text": "",
                    "created_by": "pm",
                }
            )
            st.success("Decision saved.")

        entries = list_decision_log(memo.ticker)
        if entries:
            st.dataframe(
                [
                    {
                        "When": row["decision_ts"],
                        "Title": row["decision_title"],
                        "Action": row["action"],
                        "Conviction": row["conviction"] or "—",
                        "Review Due": row["review_due_date"] or "—",
                    }
                    for row in entries
                ],
                width="stretch",
                hide_index=True,
            )


# ── Section: Review Log ──────────────────────────────────────────────────────
if selected_section == "Review Log":
    st.subheader("Review Log")
    profile = load_dossier_profile(memo.ticker)
    if profile is None:
        st.info("Initialize the dossier in Company Hub before writing reviews.")
    else:
        with st.form("review_log_form", clear_on_submit=False):
            review_title = st.text_input("Review Title", value="")
            period_type = st.selectbox("Period Type", ["quarterly", "event", "exit", "ad_hoc"])
            expectations_vs_outcomes = st.text_area("Expectations vs Outcomes", value="", height=100)
            interpretive_error = st.text_area("Interpretive Error", value="", height=80)
            thesis_status = st.selectbox("Thesis Status", ["intact", "monitor", "validated", "broken"], index=1)
            model_status = st.selectbox("Model Status", ["current", "needs_revision", "stale"], index=0)
            action_taken_text = st.text_area("Action Taken", value="", height=80)
            save_review = st.form_submit_button("Save Review")

        if save_review:
            insert_review_log_entry(
                {
                    "ticker": memo.ticker,
                    "review_ts": memo.date,
                    "review_title": review_title.strip() or "Untitled Review",
                    "period_type": period_type,
                    "expectations_vs_outcomes_text": expectations_vs_outcomes.strip(),
                    "factual_error_text": "",
                    "interpretive_error_text": interpretive_error.strip(),
                    "behavioral_error_text": "",
                    "thesis_status": thesis_status,
                    "model_status": model_status,
                    "action_taken_text": action_taken_text.strip(),
                    "linked_decision_id": None,
                    "linked_snapshot_id": st.session_state.get("report_snapshot_id"),
                    "private_notes_text": "",
                    "created_by": "pm",
                }
            )
            st.success("Review saved.")

        entries = list_review_log(memo.ticker)
        if entries:
            st.dataframe(
                [
                    {
                        "When": row["review_ts"],
                        "Title": row["review_title"],
                        "Period": row["period_type"],
                        "Thesis Status": row["thesis_status"],
                        "Model Status": row["model_status"],
                    }
                    for row in entries
                ],
                width="stretch",
                hide_index=True,
            )


# ── Section: Publishable Memo ────────────────────────────────────────────────
if selected_section == "Publishable Memo":
    st.subheader("Publishable Memo")
    profile = load_dossier_profile(memo.ticker)
    if profile is None:
        st.info("Initialize the dossier in Company Hub before editing the publishable memo.")
    else:
        memo_context = build_publishable_memo_context(memo.ticker)
        memo_text = st.text_area(
            "Memo Draft",
            value=memo_context.get("memo_content", ""),
            height=360,
            key="publishable_memo_editor",
        )
        col_save, col_download = st.columns(2)
        if col_save.button("Save Publishable Memo", key="save_publishable_memo"):
            write_dossier_note(memo.ticker, "publishable_memo", memo_text)
            st.success("Publishable memo saved.")
        col_download.download_button(
            "Download Memo Markdown",
            data=memo_text.encode("utf-8"),
            file_name=f"{memo.ticker.lower()}-publishable-memo.md",
            mime="text/markdown",
            key="download_publishable_memo",
        )

        if memo_context.get("sources"):
            st.markdown("#### Included Sources")
            st.dataframe(
                [
                    {
                        "Source ID": row["source_id"],
                        "Title": row["title"],
                        "Type": row["source_type"],
                    }
                    for row in memo_context["sources"]
                ],
                width="stretch",
                hide_index=True,
            )

        if memo_context.get("artifacts"):
            st.markdown("#### Public Artifacts")
            st.dataframe(
                [
                    {
                        "Artifact": row["artifact_key"],
                        "Title": row["title"],
                        "Type": row["artifact_type"],
                    }
                    for row in memo_context["artifacts"]
                ],
                width="stretch",
                hide_index=True,
            )


# ── Section: Thesis ───────────────────────────────────────────────────────────
if selected_section == "Thesis":
    col_a, col_b, col_c = st.columns(3)
    with col_a:
        st.subheader("Bull Case")
        st.write(memo.bull_case)
    with col_b:
        st.subheader("Base Case")
        st.write(memo.base_case)
    with col_c:
        st.subheader("Bear Case")
        st.write(memo.bear_case)

    st.divider()
    col_l, col_r = st.columns(2)
    with col_l:
        st.subheader("Key Catalysts")
        for cat in memo.key_catalysts:
            st.markdown(f"- {cat}")
    with col_r:
        st.subheader("Key Risks")
        for risk in memo.key_risks:
            st.markdown(f"- {risk}")

    st.subheader("Open Questions")
    for q in memo.open_questions:
        st.markdown(f"- {q}")


# ── Section: Valuation ────────────────────────────────────────────────────────
if selected_section == "Valuation":
    val = memo.valuation
    price = val.current_price or 0

    # Scenario table
    st.subheader("DCF Scenarios")
    scenario_rows = [
        {"Scenario": "Bear",          "Intrinsic Value": f"${val.bear:.2f}",  "Upside / (Downside)": f"{((val.bear-price)/price*100):+.1f}%" if price else "—"},
        {"Scenario": "Base",          "Intrinsic Value": f"${val.base:.2f}",  "Upside / (Downside)": f"{((val.base-price)/price*100):+.1f}%" if price else "—"},
        {"Scenario": "Bull",          "Intrinsic Value": f"${val.bull:.2f}",  "Upside / (Downside)": f"{((val.bull-price)/price*100):+.1f}%" if price else "—"},
        {"Scenario": "Current Price", "Intrinsic Value": f"${price:.2f}",     "Upside / (Downside)": "—"},
    ]
    st.dataframe(scenario_rows, width="stretch", hide_index=True)

    # WACC breakdown from DCF audit
    try:
        from src.stage_04_pipeline.dcf_audit import build_dcf_audit_view
        _wacc_audit = build_dcf_audit_view(memo.ticker)
    except Exception:
        _wacc_audit = None

    if _wacc_audit and _wacc_audit.get("available"):
        st.subheader("WACC & Key Drivers")
        driver_rows = _wacc_audit.get("driver_rows") or []
        st.dataframe(driver_rows, width="stretch", hide_index=True)

        # Sensitivity quick view
        st.subheader("Sensitivity (WACC × Terminal Growth)")
        sens_rows = _fmt_sens_table(
            _wacc_audit.get("sensitivity", {}).get("wacc_x_terminal_growth") or []
        )
        if sens_rows:
            st.dataframe(sens_rows, width="stretch", hide_index=True)


# ── Section: DCF Audit ────────────────────────────────────────────────────────
if selected_section == "DCF Audit":
    st.subheader("DCF Audit")
    st.caption("Browser-native review of the deterministic model — sourced directly from the Python DCF engine.")

    try:
        from src.stage_04_pipeline.dcf_audit import build_dcf_audit_view
        audit = _get_cached_view("dcf_audit_view", build_dcf_audit_view, memo.ticker, risk_output=memo.risk_impact)
    except Exception as e:
        audit = {"available": False}
        st.error(f"DCF audit load error: {e}")

    if not audit or not audit.get("available"):
        st.info("DCF audit unavailable. Re-run after valuation inputs are available.")
    else:
        st.subheader("Scenario Summary")
        st.dataframe(audit["scenario_summary"], width="stretch", hide_index=True)

        left, right = st.columns(2)
        with left:
            st.subheader("Key Drivers")
            st.dataframe(audit["driver_rows"], width="stretch", hide_index=True)
        with right:
            st.subheader("Health Flags")
            flag_rows = [
                {"flag": key, "active": bool(value)}
                for key, value in (audit.get("health_flags") or {}).items()
            ]
            st.dataframe(flag_rows, width="stretch", hide_index=True)

        st.subheader("Forecast Bridge (Base Scenario)")
        st.dataframe(audit["forecast_bridge"], width="stretch", hide_index=True)

        col_term, col_ev = st.columns(2)
        with col_term:
            st.subheader("Terminal Bridge")
            st.dataframe([audit["terminal_bridge"]], width="stretch", hide_index=True)
        with col_ev:
            st.subheader("EV → Equity Bridge")
            st.dataframe([audit["ev_bridge"]], width="stretch", hide_index=True)

        st.subheader("Charts")
        _render_dcf_charts(audit)

        st.subheader("Sensitivity Tables")
        s_col1, s_col2 = st.columns(2)
        with s_col1:
            st.caption("WACC × Terminal Growth")
            rows = _fmt_sens_table(audit["sensitivity"]["wacc_x_terminal_growth"])
            st.dataframe(rows, width="stretch", hide_index=True)
        with s_col2:
            st.caption("WACC × Exit Multiple")
            rows = _fmt_sens_table(audit["sensitivity"]["wacc_x_exit_multiple"])
            st.dataframe(rows, width="stretch", hide_index=True)

        mi = audit.get("model_integrity") or {}
        with st.expander("Model Integrity", expanded=False):
            mi_c1, mi_c2 = st.columns(2)
            tv_pct = mi.get("tv_pct_of_ev")
            tv_label = f"{tv_pct:.1f}%" if tv_pct is not None else "—"
            tv_delta = "High TV concentration (>75%)" if mi.get("tv_high_flag") else None
            with mi_c1:
                st.metric("Terminal Value % of EV", tv_label, delta=tv_delta,
                          delta_color="inverse" if mi.get("tv_high_flag") else "normal")
                rev_flag = mi.get("revenue_data_quality_flag", "—")
                st.metric("Revenue Data Quality", rev_flag,
                          delta="Review needed" if rev_flag in ("low_quality", "needs_review") else None,
                          delta_color="inverse" if rev_flag in ("low_quality", "needs_review") else "normal")
            with mi_c2:
                nwc_flag = mi.get("nwc_driver_quality_flag", False)
                st.metric("NWC Driver Quality", "Warning" if nwc_flag else "OK",
                          delta="Check NWC assumption" if nwc_flag else None,
                          delta_color="inverse" if nwc_flag else "normal")
                roic_flag = mi.get("roic_consistency_flag", False)
                st.metric("ROIC Consistency", "Warning" if roic_flag else "OK",
                          delta="ROIC inconsistency detected" if roic_flag else None,
                          delta_color="inverse" if roic_flag else "normal")


# ── Section: IV History ────────────────────────────────────────────────────────
if selected_section == "IV History":
    st.subheader("IV History")
    st.caption("Intrinsic value bear/base/bull vs. current price across batch runs.")

    try:
        import sqlite3 as _sqlite3
        from config import DB_PATH as _DB_PATH
        _conn = _sqlite3.connect(str(_DB_PATH))
        _conn.row_factory = _sqlite3.Row
        _iv_rows = _conn.execute(
            """
            SELECT run_date, iv_bear, iv_base, iv_bull, iv_expected, current_price, upside_pct, wacc, exit_multiple
            FROM dcf_valuations
            WHERE ticker = ?
            ORDER BY run_date ASC
            """,
            [memo.ticker],
        ).fetchall()
        _conn.close()
        iv_history = [dict(r) for r in _iv_rows]
    except Exception as _e:
        iv_history = []
        st.error(f"IV history load error: {_e}")

    if not iv_history:
        st.info("No IV history yet. Run the batch valuation for this ticker first.")
    else:
        import plotly.graph_objects as _go

        # Line chart
        _fig = _go.Figure()
        _dates = [r["run_date"] for r in iv_history]
        for _label, _key, _color in [
            ("IV Bear", "iv_bear", "#e74c3c"),
            ("IV Base", "iv_base", "#2ecc71"),
            ("IV Bull", "iv_bull", "#3498db"),
            ("Price", "current_price", "#f39c12"),
        ]:
            _vals = [r.get(_key) for r in iv_history]
            _fig.add_trace(_go.Scatter(x=_dates, y=_vals, mode="lines+markers", name=_label,
                                       line=dict(color=_color)))
        _fig.update_layout(title=f"{memo.ticker} — IV History", xaxis_title="Run Date",
                           yaxis_title="Price ($)", legend=dict(orientation="h"))
        st.plotly_chart(_fig, width="stretch")

        # Summary table — last 10 runs with IV delta vs prior run
        _summary = []
        for _i, _r in enumerate(iv_history[-10:], start=max(0, len(iv_history) - 10)):
            _prev = iv_history[_i - 1] if _i > 0 else None
            _base = _r.get("iv_base")
            _prev_base = _prev.get("iv_base") if _prev else None
            _delta_pct = round((_base - _prev_base) / abs(_prev_base) * 100, 1) if (_base and _prev_base) else None
            _flag = "⚠" if _delta_pct is not None and abs(_delta_pct) > 15 else ""
            _summary.append({
                "run_date": _r["run_date"],
                "iv_bear": f"${_r.get('iv_bear') or 0:,.2f}" if _r.get("iv_bear") else "—",
                "iv_base": f"${_base or 0:,.2f}" if _base else "—",
                "iv_bull": f"${_r.get('iv_bull') or 0:,.2f}" if _r.get("iv_bull") else "—",
                "price": f"${_r.get('current_price') or 0:,.2f}" if _r.get("current_price") else "—",
                "upside_%": f"{_r.get('upside_pct') or 0:.1f}%" if _r.get("upside_pct") is not None else "—",
                "Δ base %": f"{_delta_pct:+.1f}% {_flag}" if _delta_pct is not None else "—",
                "wacc": f"{(_r.get('wacc') or 0)*100:.2f}%" if _r.get("wacc") else "—",
            })
        st.subheader("Last 10 Runs")
        st.dataframe(_summary, width="stretch", hide_index=True)

        _large_moves = [r for r in _summary if "⚠" in str(r.get("Δ base %", ""))]
        if _large_moves:
            st.warning(f"{len(_large_moves)} run(s) with IV base move >15% flagged above.")


# ── Section: WACC Lab ────────────────────────────────────────────────────────
if selected_section == "WACC Lab":
    st.subheader("WACC Lab")
    st.caption("Compare peer bottom-up, industry proxy, and self-Hamada methodologies, then preview or persist the selection.")

    try:
        workbench = build_wacc_workbench(memo.ticker, apply_overrides=True)
    except Exception as e:
        workbench = {"available": False}
        st.error(f"WACC workbench error: {e}")

    if not workbench.get("available"):
        st.info("WACC workbench unavailable for this ticker.")
    else:
        methods = workbench.get("methods") or []
        method_rows = []
        for payload in methods:
            method_rows.append(
                {
                    "method": payload["method"],
                    "wacc": f"{payload['wacc']*100:.2f}%",
                    "cost_of_equity": f"{payload['cost_of_equity']*100:.2f}%",
                    "cost_of_debt_after_tax": f"{payload['cost_of_debt_after_tax']*100:.2f}%",
                    "beta": payload.get("beta_value"),
                    "beta_source": payload.get("beta_source"),
                    "equity_weight": f"{(payload.get('assumptions', {}).get('equity_weight') or 0)*100:.1f}%",
                    "debt_weight": f"{(payload.get('assumptions', {}).get('debt_weight') or 0)*100:.1f}%",
                }
            )
        st.dataframe(method_rows, width="stretch", hide_index=True)

        active_selection = workbench.get("current_selection") or {"mode": "single_method", "selected_method": "peer_bottom_up", "weights": {}}
        mode = st.radio(
            "Methodology mode",
            options=["single_method", "blended"],
            horizontal=True,
            index=0 if active_selection.get("mode") == "single_method" else 1,
            key=f"wacc_mode_{memo.ticker}",
        )
        selected_method = None
        weights: dict[str, float] | None = None
        method_names = [payload["method"] for payload in methods]
        if mode == "single_method":
            selected_method = st.selectbox(
                "Method",
                options=method_names,
                index=method_names.index(active_selection.get("selected_method") or "peer_bottom_up"),
                key=f"wacc_method_{memo.ticker}",
            )
        else:
            weight_cols = st.columns(3)
            weights = {}
            for col, method in zip(weight_cols, method_names):
                default_weight = float((active_selection.get("weights") or {}).get(method, 0.0))
                weights[method] = col.number_input(
                    f"{method} weight",
                    min_value=0.0,
                    max_value=1.0,
                    step=0.05,
                    value=default_weight,
                    key=f"wacc_weight_{memo.ticker}_{method}",
                )
            total_weight = sum(weights.values())
            st.caption(f"Entered weight sum: {total_weight:.2f}")

        preview_clicked = st.button("Preview WACC selection", key=f"wacc_preview_btn_{memo.ticker}")
        if preview_clicked:
            try:
                st.session_state.wacc_preview = preview_wacc_methodology_selection(
                    memo.ticker,
                    mode=mode,
                    selected_method=selected_method,
                    weights=weights,
                )
            except Exception as e:
                st.error(f"WACC preview error: {e}")

        if st.button("Apply WACC selection", type="primary", key=f"wacc_apply_btn_{memo.ticker}"):
            try:
                result = apply_wacc_methodology_selection(
                    memo.ticker,
                    mode=mode,
                    selected_method=selected_method,
                    weights=weights,
                    actor="dashboard",
                )
                st.success(
                    f"Saved WACC methodology. Effective WACC {result['effective_wacc']*100:.2f}% "
                    f"| base IV ${result['proposed_iv'].get('base', 0):,.2f}"
                )
                st.session_state.wacc_preview = preview_wacc_methodology_selection(
                    memo.ticker,
                    mode=mode,
                    selected_method=selected_method,
                    weights=weights,
                )
            except Exception as e:
                st.error(f"WACC apply error: {e}")

        wacc_preview = st.session_state.get("wacc_preview")
        if wacc_preview:
            prev_cols = st.columns(4)
            prev_cols[0].metric("Current WACC", f"{wacc_preview['current_wacc']*100:.2f}%")
            prev_cols[1].metric("Proposed WACC", f"{wacc_preview['effective_wacc']*100:.2f}%")
            prev_cols[2].metric("Current Base IV", f"${wacc_preview['current_iv'].get('base', 0):,.2f}")
            prev_cols[3].metric("Proposed Base IV", f"${wacc_preview['proposed_iv'].get('base', 0):,.2f}")

        history = load_wacc_methodology_audit_history(memo.ticker, limit=25)
        if history:
            st.subheader("WACC Methodology Audit")
            st.dataframe(history, width="stretch", hide_index=True)


# ── Section: Comps ────────────────────────────────────────────────────────────
if selected_section == "Comps":
    st.subheader("Comps Dashboard")
    comps_view = _get_cached_view("comps_view", build_comps_dashboard_view, memo.ticker)
    if not comps_view.get("available"):
        st.info("No comps view available for this ticker.")
    else:
        metric_options = comps_view.get("metric_options") or []
        option_lookup = {option["label"]: option["key"] for option in metric_options if option.get("key")}
        default_metric = comps_view.get("selected_metric_default")
        default_label = next(
            (option["label"] for option in metric_options if option.get("key") == default_metric),
            metric_options[0]["label"] if metric_options else "Primary",
        )
        selected_metric_label = st.selectbox(
            "Valuation Metric",
            list(option_lookup) or [default_label],
            index=(list(option_lookup).index(default_label) if option_lookup and default_label in option_lookup else 0),
            key=f"comps_metric_{memo.ticker}",
        )
        selected_metric_key = option_lookup.get(selected_metric_label, default_metric)
        selected_metric = (comps_view.get("valuation_range_by_metric") or {}).get(selected_metric_key) or {}

        top = st.columns(5)
        valuation_range = comps_view.get("valuation_range") or {}
        top[0].metric("Primary Metric", selected_metric_label or "—")
        top[1].metric("Bear IV", format_metric_value(selected_metric.get("bear"), kind="price"))
        top[2].metric("Base IV", format_metric_value(selected_metric.get("base"), kind="price"))
        top[3].metric("Bull IV", format_metric_value(selected_metric.get("bull"), kind="price"))
        top[4].metric("Blended Base", format_metric_value(valuation_range.get("blended_base"), kind="price"))

        peer_counts = comps_view.get("peer_counts") or {}
        counts_cols = st.columns(4)
        counts_cols[0].metric("Peers Raw", format_metric_value(peer_counts.get("raw"), kind="count"))
        counts_cols[1].metric("Peers Clean", format_metric_value(peer_counts.get("clean"), kind="count"))
        counts_cols[2].metric("Current Price", format_metric_value((comps_view.get("target") or {}).get("current_price"), kind="price"))
        counts_cols[3].metric("Analyst Target", format_metric_value(next((marker.get("value") for marker in (comps_view.get("football_field") or {}).get("markers", []) if marker.get("label") == "Analyst Target Mean"), None), kind="price"))

        compare_payload = comps_view.get("target_vs_peers") or {}
        compare_rows = []
        compare_schema = {
            "target": "raw",
            "peer_median": "raw",
            "delta": "raw",
        }
        metric_kinds = {
            "tev_ebitda_ltm": "x",
            "tev_ebitda_fwd": "x",
            "tev_ebit_ltm": "x",
            "tev_ebit_fwd": "x",
            "pe_ltm": "x",
            "revenue_growth": "pct",
            "ebit_margin": "pct",
            "net_debt_to_ebitda": "x",
        }
        for key, target_value in (compare_payload.get("target") or {}).items():
            peer_value = (compare_payload.get("peer_medians") or {}).get(key)
            delta_value = (compare_payload.get("deltas") or {}).get(key)
            compare_rows.append(
                {
                    "metric": key,
                    "target": format_metric_value(target_value, kind=metric_kinds.get(key, "raw")),
                    "peer_median": format_metric_value(peer_value, kind=metric_kinds.get(key, "raw")),
                    "delta": format_metric_value(delta_value, kind=metric_kinds.get(key, "raw")),
                }
            )
        if compare_rows:
            st.subheader("Target vs Peer Medians")
            st.dataframe(compare_rows, width="stretch", hide_index=True)

        football_field = comps_view.get("football_field") or {}
        markers = football_field.get("markers") or []
        if markers:
            st.subheader("Football Field")
            try:
                import plotly.graph_objects as go
            except ImportError:
                st.dataframe(
                    _styled_rows(markers, {"value": "price"}),
                    width="stretch",
                    hide_index=True,
                )
            else:
                color_map = {
                    "spot": "#38bdf8",
                    "range_point": "#f59e0b",
                }
                fig = go.Figure()
                plotted_rows = list(reversed(markers))
                for row in plotted_rows:
                    fig.add_trace(
                        go.Scatter(
                            x=[row.get("value")],
                            y=[row.get("label")],
                            mode="markers",
                            marker=dict(
                                size=12 if row.get("type") == "spot" else 10,
                                color=color_map.get(row.get("type"), "#94a3b8"),
                            ),
                            showlegend=False,
                            hovertemplate="%{y}: $%{x:.2f}<extra></extra>",
                        )
                    )
                fig.update_layout(
                    height=max(320, 40 * len(plotted_rows)),
                    margin=dict(l=20, r=20, t=20, b=20),
                    xaxis_title="Implied Value Per Share",
                    yaxis_title="",
                )
                st.plotly_chart(fig, width="stretch")

        st.subheader("Peer Table")
        peer_rows = comps_view.get("peers") or []
        peer_schema = {
            "similarity_score": "raw",
            "model_weight": "pct",
            "tev_ebitda_ltm": "x",
            "tev_ebit_fwd": "x",
            "tev_ebit_ltm": "x",
            "pe_ltm": "x",
            "revenue_growth": "pct",
            "ebit_margin": "pct",
            "net_debt_to_ebitda": "x",
        }
        st.dataframe(_styled_rows(peer_rows, peer_schema), width="stretch", hide_index=True)

        historical_multiples_summary = comps_view.get("historical_multiples_summary") or {}
        st.subheader("Historical Multiples")
        if historical_multiples_summary.get("available"):
            historical_metrics = historical_multiples_summary.get("metrics") or {}
            historical_metric = st.selectbox(
                "Historical Multiple Series",
                list(historical_metrics),
                key=f"historical_multiple_{memo.ticker}",
            )
            historical_payload = historical_metrics.get(historical_metric) or {}
            historical_summary = historical_payload.get("summary") or {}
            hist_cols = st.columns(5)
            hist_cols[0].metric("Current", format_metric_value(historical_summary.get("current"), kind="multiple"))
            hist_cols[1].metric("Median", format_metric_value(historical_summary.get("median"), kind="multiple"))
            hist_cols[2].metric("Min", format_metric_value(historical_summary.get("min"), kind="multiple"))
            hist_cols[3].metric("Max", format_metric_value(historical_summary.get("max"), kind="multiple"))
            hist_cols[4].metric("Current Percentile", format_metric_value(historical_summary.get("current_percentile"), kind="pct"))
            series = historical_payload.get("series") or []
            if series:
                try:
                    import plotly.graph_objects as go
                except ImportError:
                    st.dataframe(_styled_rows(series, {"multiple": "x", "price": "price"}), width="stretch", hide_index=True)
                else:
                    fig = go.Figure()
                    fig.add_trace(
                        go.Scatter(
                            x=[row.get("date") for row in series],
                            y=[row.get("multiple") for row in series],
                            mode="lines",
                            name=historical_metric,
                            line=dict(color="#38bdf8", width=2),
                        )
                    )
                    peer_current = historical_summary.get("peer_current")
                    if peer_current is not None:
                        fig.add_hline(
                            y=float(peer_current),
                            line_dash="dash",
                            line_color="#f59e0b",
                            annotation_text="Peer Current",
                            annotation_position="top left",
                        )
                    fig.update_layout(
                        height=320,
                        margin=dict(l=20, r=20, t=20, b=20),
                        xaxis_title="Date",
                        yaxis_title="Multiple",
                        showlegend=False,
                    )
                    st.plotly_chart(fig, width="stretch")
        else:
            st.info("Historical multiples are unavailable for this ticker.")
            for flag in historical_multiples_summary.get("audit_flags") or []:
                st.caption(flag)

        st.subheader("Audit Flags")
        audit_flags = comps_view.get("audit_flags") or []
        if audit_flags:
            for flag in audit_flags:
                st.warning(flag)
        else:
            st.info("No comps audit flags for this run.")


# ── Section: News & Materiality ──────────────────────────────────────────────
if selected_section == "News & Materiality":
    st.subheader("News & Materiality")
    intel_view = _get_cached_view("market_intel_view", build_news_materiality_view, memo.ticker)
    analyst = intel_view.get("analyst_snapshot") or {}
    top = st.columns(4)
    top[0].metric("Recommendation", str(analyst.get("recommendation") or "—").upper())
    top[1].metric("Target Mean", format_metric_value(analyst.get("target_mean"), kind="price"))
    top[2].metric("Analysts", format_metric_value(analyst.get("num_analysts"), kind="count"))
    top[3].metric("Current Price", format_metric_value(analyst.get("current_price"), kind="price"))
    sentiment_summary = intel_view.get("sentiment_summary") or {}
    if sentiment_summary:
        st.caption(
            f"Latest sentiment: {str(sentiment_summary.get('direction') or 'n/a').title()} "
            f"| score {sentiment_summary.get('score', 0):+.2f}"
        )
    historical_brief = intel_view.get("historical_brief") or {}
    st.subheader("Historical Brief")
    if historical_brief.get("summary"):
        st.markdown(_fix_text(historical_brief.get("summary") or ""))
        st.caption(
            f"Window: {historical_brief.get('period_start') or 'unknown'} → {historical_brief.get('period_end') or 'unknown'}"
        )
        event_timeline = historical_brief.get("event_timeline") or []
        if event_timeline:
            st.dataframe(event_timeline, width="stretch", hide_index=True)
    else:
        st.info("No historical brief available.")

    st.subheader("Quarterly Materiality")
    quarterly_headlines = intel_view.get("quarterly_headlines") or []
    if quarterly_headlines:
        st.dataframe(
            _styled_rows(quarterly_headlines, {"materiality_score": "raw"}),
            width="stretch",
            hide_index=True,
        )
    else:
        st.info("No recent quarterly headlines returned for this ticker.")

    with st.expander("All Ranked Headlines", expanded=False):
        if intel_view.get("headlines"):
            st.dataframe(
                _styled_rows(intel_view["headlines"], {"materiality_score": "raw"}),
                width="stretch",
                hide_index=True,
            )
        else:
            st.info("No recent headlines returned for this ticker.")

    for flag in intel_view.get("audit_flags") or []:
        st.caption(flag)


# ── Section: Filings Browser ─────────────────────────────────────────────────
if selected_section == "Filings Browser":
    st.subheader("Filings Browser")
    st.caption("Read-only browser for cached SEC filings and the exact chunks the agents used.")
    filings_view = _get_cached_view("filings_browser_view", build_filings_browser_view, memo.ticker)
    if not filings_view.get("available"):
        st.info("No filing cache available for this ticker.")
    else:
        filings = filings_view.get("filings") or []
        labels = [
            f"{row['form_type']} | {row.get('filing_date') or 'unknown-date'} | {row['accession_no']}"
            for row in filings
        ]
        selected_label = st.selectbox("Filing", labels, key=f"filing_browser_sel_{memo.ticker}")
        filing_row = filings[labels.index(selected_label)]
        filing_key = filing_row.get("filing_key") or filing_row["accession_no"]
        accession_no = filing_row["accession_no"]
        meta_cols = st.columns(5)
        meta_cols[0].metric("Form", filing_row["form_type"])
        meta_cols[1].metric("Filing Date", filing_row.get("filing_date") or "—")
        meta_cols[2].metric("Accession", accession_no)
        meta_cols[3].metric("Raw Cache", "yes" if filing_row.get("raw_available") else "no")
        meta_cols[4].metric("Clean Cache", "yes" if filing_row.get("clean_available") else "no")
        if filing_row.get("source_url"):
            st.link_button("Open on SEC", filing_row["source_url"])

        statement_presence = (filings_view.get("statement_presence_by_filing") or {}).get(filing_key, {})
        coverage_summary = filings_view.get("coverage_summary") or {}
        coverage_counts = coverage_summary.get("by_section_key") or {}
        coverage_cols = st.columns(5)
        coverage_cols[0].metric("Financial Statements", "yes" if statement_presence.get("financial_statements") else "no")
        coverage_cols[1].metric("Notes", "yes" if statement_presence.get("notes_to_financials") else "no")
        coverage_cols[2].metric("MD&A", "yes" if statement_presence.get("mda") else "no")
        coverage_cols[3].metric("Risk Factors", "yes" if statement_presence.get("risk_factors") else "no")
        coverage_cols[4].metric("Quarterly Notes", "yes" if statement_presence.get("quarterly_notes") else "no")

        filing_search = st.text_input("Filter filing content", key=f"filing_filter_{memo.ticker}_{accession_no}")
        used_chunks = []
        for agent_name, chunks in (filings_view.get("agent_usage") or {}).items():
            for chunk in chunks:
                if chunk.get("accession_no") == accession_no:
                    used_chunks.append({"agent": agent_name, **chunk})
        if filing_search:
            used_chunks = [row for row in used_chunks if filing_search.lower() in json.dumps(row).lower()]

        diagnostics_tab, used_tab, sections_tab, chunks_tab, clean_tab, raw_tab = st.tabs(["Diagnostics", "Agent-Used Chunks", "Sections", "Chunks", "Clean Text", "Raw HTML"])
        with diagnostics_tab:
            st.markdown("**Coverage Summary**")
            coverage_rows = [{"section_key": key, "count": value} for key, value in coverage_counts.items()]
            if coverage_rows:
                st.dataframe(_styled_rows(coverage_rows, {"count": "count"}), width="stretch", hide_index=True)
            else:
                st.info("No extracted section coverage is available for this filing.")

            st.markdown("**Retrieval Profiles**")
            retrieval_rows = []
            for profile_name, payload in (filings_view.get("retrieval_profiles") or {}).items():
                retrieval_rows.append(
                    {
                        "profile": profile_name,
                        "fallback_mode": payload.get("fallback_mode"),
                        "selected_chunk_count": payload.get("selected_chunk_count"),
                        "candidate_chunk_count": payload.get("candidate_chunk_count"),
                        "corpus_chunk_count": payload.get("corpus_chunk_count"),
                        "eligible_section_keys": ", ".join(payload.get("eligible_section_keys") or []),
                        "excluded_section_keys": ", ".join(payload.get("excluded_section_keys") or []),
                        "skipped_sections": ", ".join(payload.get("skipped_sections") or []),
                    }
                )
            if retrieval_rows:
                st.dataframe(
                    _styled_rows(
                        retrieval_rows,
                        {
                            "fallback_mode": "raw",
                            "selected_chunk_count": "count",
                            "candidate_chunk_count": "count",
                            "corpus_chunk_count": "count",
                        },
                    ),
                    width="stretch",
                    hide_index=True,
                )
            else:
                st.info("No retrieval diagnostics are available.")
        with used_tab:
            if used_chunks:
                st.dataframe(used_chunks, width="stretch", hide_index=True)
            else:
                st.info("No selected chunks for this filing in the cached agent contexts.")
        with sections_tab:
            section_rows = filings_view.get("sections_by_filing", {}).get(filing_key) or filings_view.get("sections_by_filing", {}).get(accession_no, [])
            if filing_search:
                section_rows = [row for row in section_rows if filing_search.lower() in json.dumps(row).lower()]
            st.dataframe(section_rows, width="stretch", hide_index=True)
        with chunks_tab:
            chunk_rows = filings_view.get("chunks_by_filing", {}).get(filing_key) or filings_view.get("chunks_by_filing", {}).get(accession_no, [])
            if filing_search:
                chunk_rows = [row for row in chunk_rows if filing_search.lower() in json.dumps(row).lower()]
            st.dataframe(chunk_rows, width="stretch", hide_index=True)
        with clean_tab:
            clean_text = filing_row.get("clean_text") or ""
            if filing_search:
                clean_text = "\n".join(line for line in clean_text.splitlines() if filing_search.lower() in line.lower())
            st.text_area("Clean text", clean_text, height=420, key=f"clean_text_{filing_key}")
        with raw_tab:
            raw_html = filing_row.get("raw_html") or ""
            if filing_search:
                raw_html = "\n".join(line for line in raw_html.splitlines() if filing_search.lower() in line.lower())
            st.code(raw_html or "No raw HTML cached for this filing.", language="html")


# ── Section: Filings ──────────────────────────────────────────────────────────
if selected_section == "Filings":
    f = memo.filings
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Revenue Trend", f.revenue_trend.title())
    col2.metric("Margin Trend", f.margin_trend.title())
    col3.metric("3Y Revenue CAGR", f"{(f.revenue_cagr_3y or 0)*100:.1f}%")
    col4.metric("Net Debt/EBITDA", f"{f.net_debt_to_ebitda:.1f}x" if f.net_debt_to_ebitda else "—")

    if f.red_flags:
        st.subheader("Red Flags")
        for flag in f.red_flags:
            st.warning(flag)

    if f.notes_watch_items:
        with st.expander("Notes Watch Items", expanded=False):
            for item in f.notes_watch_items:
                st.markdown(f"- {_fix_text(item)}")

    if f.recent_quarter_updates:
        with st.expander("Recent Quarter Updates", expanded=False):
            for item in f.recent_quarter_updates:
                st.markdown(f"- {_fix_text(item)}")

    st.subheader("Management Guidance")
    st.write(_fix_text(f.management_guidance))

    st.subheader("Full Analysis")
    st.markdown(
        f'<div class="analysis-scroll">{_fix_text(f.raw_summary).replace(chr(10), "<br>")}</div>',
        unsafe_allow_html=True,
    )


# ── Section: Earnings ─────────────────────────────────────────────────────────
if selected_section == "Earnings":
    e = memo.earnings
    col1, col2, col3 = st.columns(3)
    col1.metric("Guidance Trend", e.guidance_trend.title())
    col2.metric("Management Tone", e.management_tone.title())
    col3.metric("EPS Beat Rate", f"{(e.eps_beat_rate or 0)*100:.0f}%" if e.eps_beat_rate else "—")

    if e.key_themes:
        st.subheader("Key Themes")
        for theme in e.key_themes:
            st.markdown(f"- {_fix_text(theme)}")

    st.subheader("Full Analysis")
    st.markdown(
        f'<div class="analysis-scroll">{_fix_text(e.raw_summary).replace(chr(10), "<br>")}</div>',
        unsafe_allow_html=True,
    )


# ── Section: Forensic Scores ──────────────────────────────────────────────────
if selected_section == "Forensic Scores":
    st.subheader("Forensic Accounting Scores")
    try:
        from src.stage_03_judgment.forensic_scores import compute_forensic_signals
        _f_hist = md_client.get_historical_financials(memo.ticker)
        _f_mkt = md_client.get_market_data(memo.ticker)
        _f_mcap_mm = (_f_mkt.get("market_cap") or 0) / 1e6 or None
        fsig = compute_forensic_signals(_f_hist, _f_mcap_mm, memo.sector)

        col_m, col_z, col_flag = st.columns(3)

        m_score = fsig.get("m_score")
        m_zone = fsig.get("m_score_zone", "unknown")
        m_badge = {"manipulator": "MANIPULATOR", "grey_zone": "GREY ZONE", "non_manipulator": "Non-Manipulator"}.get(m_zone, m_zone.upper())
        col_m.metric("Beneish M-Score", f"{m_score:.2f}" if m_score is not None else "—", delta=m_badge)

        z_score = fsig.get("z_score")
        z_zone = fsig.get("z_score_zone", "unknown")
        z_badge = {"distress": "DISTRESS", "grey_zone": "GREY ZONE", "safe": "Safe"}.get(z_zone, z_zone.upper())
        col_z.metric("Altman Z'-Score", f"{z_score:.2f}" if z_score is not None else "—", delta=z_badge)

        forensic_flag = fsig.get("forensic_flag", False)
        col_flag.metric("Forensic Flag", "FLAGGED" if forensic_flag else "Clean")

        st.divider()
        col_a, col_b = st.columns(2)
        with col_a:
            st.markdown("**M-Score Interpretation**")
            st.markdown(
                "- > −1.78 → likely earnings manipulator\n"
                "- −2.50 to −1.78 → grey zone (monitor)\n"
                "- < −2.50 → non-manipulator"
            )
        with col_b:
            st.markdown("**Z'-Score Interpretation** (non-manufacturing)")
            st.markdown(
                "- > 2.6 → safe zone\n"
                "- 1.1 to 2.6 → grey zone\n"
                "- < 1.1 → distress zone"
            )

    except Exception as _fsig_exc:
        st.warning(f"Forensic scores unavailable: {_fsig_exc}")


# ── Section: Sentiment ────────────────────────────────────────────────────────
if selected_section == "Sentiment":
    s = memo.sentiment
    direction_emoji = {"bullish": "[BULL]", "bearish": "[BEAR]", "neutral": "[NEUTRAL]"}.get(s.direction, "")
    col1, col2 = st.columns(2)
    col1.metric("Direction", f"{direction_emoji} {s.direction.title()}")
    col2.metric("Score", f"{s.score:+.2f} / 1.0")

    col_a, col_b = st.columns(2)
    with col_a:
        st.subheader("Bullish Themes")
        for t in s.key_bullish_themes:
            st.markdown(f"- {_fix_text(t)}")
    with col_b:
        st.subheader("Bearish Themes")
        for t in s.key_bearish_themes:
            st.markdown(f"- {_fix_text(t)}")

    if s.risk_narratives:
        st.subheader("Risk Narratives")
        for n in s.risk_narratives:
            st.markdown(f"- {_fix_text(n)}")

    st.subheader("Full Analysis")
    st.markdown(
        f'<div class="analysis-scroll">{_fix_text(s.raw_summary).replace(chr(10), "<br>")}</div>',
        unsafe_allow_html=True,
    )


# ── Section: Risk ─────────────────────────────────────────────────────────────
if selected_section == "Risk":
    r = memo.risk
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Conviction", r.conviction.upper())
    col2.metric("Position Size", f"${r.position_size_usd:,.0f}")
    col3.metric("% of Portfolio", f"{r.position_pct*100:.1f}%")
    col4.metric("Stop Loss", f"{r.suggested_stop_loss_pct*100:.0f}% below entry")

    if r.annualized_volatility:
        st.metric("Annualized Volatility", f"{r.annualized_volatility*100:.1f}%")

    st.subheader("Sizing Rationale")
    st.write(_fix_text(r.rationale))

    if memo.risk_impact and memo.risk_impact.overlays:
        st.subheader("Risk-to-Valuation Overlays")
        st.caption("Advisory-only downside scenarios — do not change the base DCF.")
        st.dataframe(
            [overlay.model_dump(mode="python") for overlay in memo.risk_impact.overlays],
            width="stretch",
            hide_index=True,
        )


# ── Section: Pipeline ─────────────────────────────────────────────────────────
# ── Section: Portfolio Risk ────────────────────────────────────────────────────
if selected_section == "Portfolio Risk":
    st.subheader("Portfolio Risk")
    st.caption("Correlation, VaR/CVaR, sector concentration, and exposure metrics across the universe.")

    # Load positions from DB
    try:
        import sqlite3 as _pr_sqlite
        from config import DB_PATH as _PR_DB_PATH
        _pr_conn = _pr_sqlite.connect(str(_PR_DB_PATH))
        _pr_conn.row_factory = _pr_sqlite.Row
        _pos_rows = _pr_conn.execute(
            "SELECT ticker, direction, market_value, shares FROM positions WHERE market_value IS NOT NULL"
        ).fetchall()
        _pr_conn.close()
        _positions = [dict(r) for r in _pos_rows]
    except Exception as _pe:
        _positions = []

    # Fall back to universe tickers if no positions
    try:
        from config import UNIVERSE_TICKERS as _U_TICKERS
        _universe_tickers = _U_TICKERS if _U_TICKERS else []
    except Exception:
        _universe_tickers = []

    if _positions:
        _pos_tickers = [p["ticker"] for p in _positions]
    elif _universe_tickers:
        _pos_tickers = list(_universe_tickers)[:20]
    else:
        _pos_tickers = [memo.ticker] if memo.ticker else []

    if not _pos_tickers:
        st.info("No positions or universe tickers found. Add positions or configure universe.csv.")
    else:
        _pr_period = st.selectbox("Return lookback", ["6mo", "1y", "2y"], index=1, key="pr_period")
        if st.button("Compute Portfolio Risk", key="compute_pr"):
            with st.spinner("Fetching price history and computing risk metrics..."):
                try:
                    from src.stage_02_valuation.portfolio_risk import build_portfolio_risk
                    _weights = None
                    if _positions:
                        _total_long = sum(abs(p.get("market_value", 0) or 0) for p in _positions if (p.get("market_value") or 0) > 0)
                        _weights = {p["ticker"]: (p.get("market_value") or 0) / _total_long for p in _positions if _total_long > 0}
                    _pr_summary = build_portfolio_risk(_pos_tickers, weights=_weights, positions=_positions or None, period=_pr_period)
                    st.session_state["pr_summary"] = _pr_summary
                except Exception as _pre:
                    st.error(f"Portfolio risk error: {_pre}")

        _pr_summary = st.session_state.get("pr_summary")
        if _pr_summary is not None:
            # Exposure metrics
            if _pr_summary.gross_exposure:
                _exp_cols = st.columns(4)
                _exp_cols[0].metric("Gross Exposure", f"${_pr_summary.gross_exposure:,.0f}")
                _exp_cols[1].metric("Net Exposure", f"${_pr_summary.net_exposure:,.0f}")
                _exp_cols[2].metric("Long", f"${_pr_summary.long_exposure:,.0f}")
                _exp_cols[3].metric("Short", f"${_pr_summary.short_exposure:,.0f}")
                st.divider()

            # VaR/CVaR
            st.subheader("VaR / CVaR (1-Day)")
            _var_cols = st.columns(4)
            for _ci, (_lbl, _key) in enumerate([("VaR 95%", "var_95"), ("VaR 99%", "var_99"),
                                                 ("CVaR 95%", "cvar_95"), ("CVaR 99%", "cvar_99")]):
                _val = getattr(_pr_summary, _key, None)
                _var_cols[_ci].metric(_lbl, f"{_val*100:.2f}%" if _val is not None else "—")

            # Correlation heatmap
            if _pr_summary.correlation_matrix and len(_pr_summary.tickers) >= 2:
                st.subheader("Correlation Heatmap")
                import plotly.graph_objects as _pr_go
                _cm = _pr_summary.correlation_matrix
                _ct = _pr_summary.tickers
                _pr_fig = _pr_go.Figure(data=_pr_go.Heatmap(
                    z=_cm, x=_ct, y=_ct,
                    colorscale="RdYlGn", zmin=-1, zmax=1,
                    text=[[f"{v:.2f}" for v in row] for row in _cm],
                    texttemplate="%{text}", showscale=True,
                ))
                _pr_fig.update_layout(height=max(300, 40 * len(_ct)))
                st.plotly_chart(_pr_fig, width="stretch")

                # Top 5 most correlated pairs
                st.subheader("Top Correlated Pairs")
                st.dataframe(_pr_summary.top_correlated_pairs, width="stretch", hide_index=True)

            # Sector concentration
            if _pr_summary.sector_weights:
                st.subheader("Sector Concentration")
                _sc_fig = _pr_go.Figure(data=_pr_go.Bar(
                    x=list(_pr_summary.sector_weights.keys()),
                    y=list(_pr_summary.sector_weights.values()),
                    marker_color="#3498db",
                ))
                _sc_fig.update_layout(xaxis_title="Sector", yaxis_title="Weight (%)", height=300)
                st.plotly_chart(_sc_fig, width="stretch")


# ── Section: Pipeline ────────────────────────────────────────────────────────
if selected_section == "Pipeline":
    st.subheader("Pipeline Trace")
    st.caption("Latest run trace plus persisted agent-run history from SQLite.")

    latest_trace = st.session_state.get("run_trace") or []
    if latest_trace:
        st.dataframe(latest_trace, width="stretch", hide_index=True)
    else:
        st.info("No in-session run trace yet. Run the pipeline from this dashboard to populate it.")

    try:
        from src.stage_04_pipeline.agent_cache import load_agent_run_history
        run_history = load_agent_run_history(memo.ticker, limit=50)
    except Exception as e:
        run_history = []
        st.error(f"Agent run history error: {e}")

    if run_history:
        st.subheader("Recent Agent Run History")
        st.dataframe(run_history, width="stretch", hide_index=True)
    else:
        st.info("No persisted agent-run history stored yet for this ticker.")


# ── Section: Recommendations ──────────────────────────────────────────────────
if selected_section == "Recommendations":
    st.subheader("Agent Recommendations")
    recs = st.session_state.recommendations

    if recs is None:
        try:
            from src.stage_04_pipeline.recommendations import load_recommendations
            recs = load_recommendations(memo.ticker)
            st.session_state.recommendations = recs
        except Exception:
            recs = None

    if recs is None or not recs.recommendations:
        st.info("No recommendations available. Run a full analysis first.")
    else:
        if recs.current_iv_base:
            st.caption(f"Current base IV: **${recs.current_iv_base:,.2f}**  ·  Generated: {recs.generated_at}")

        from collections import defaultdict
        by_agent: dict = defaultdict(list)
        for r in recs.recommendations:
            by_agent[r.agent].append(r)

        agent_labels = {
            "qoe": "Quality of Earnings",
            "accounting_recast": "Accounting Recast",
            "industry": "Industry",
            "filings": "Filings Cross-Check",
        }

        for agent_key, agent_recs in by_agent.items():
            with st.expander(f"{agent_labels.get(agent_key, agent_key)} — {len(agent_recs)} item(s)", expanded=True):
                for rec in agent_recs:
                    unit = _rec_unit(rec.field)
                    col_a, col_b, col_c, col_d = st.columns([3, 2, 2, 2])
                    with col_a:
                        st.markdown(f"**{rec.field}**")
                        st.caption(_fix_text(rec.rationale))
                        if rec.citation:
                            st.caption(f"_{rec.citation[:120]}_")
                    with col_b:
                        cur_str = _format_unit_value(rec.current_value, unit)
                        prop_str = (
                            _format_unit_value(rec.proposed_value, unit)
                            if isinstance(rec.proposed_value, float)
                            else str(rec.proposed_value)
                        )
                        st.metric("Current → Proposed", prop_str, delta=f"from {cur_str}", delta_color="off")
                    with col_c:
                        badge_map = {"high": "HIGH", "medium": "MEDIUM", "low": "LOW"}
                        st.markdown(f"Confidence: **{badge_map.get(rec.confidence, rec.confidence)}**")
                        st.markdown(f"Source: `{rec.agent}`")
                    with col_d:
                        s_color = {"approved": "#22c55e", "rejected": "#ef4444", "pending": "#ca8a04"}
                        clr = s_color.get(rec.status, "#6b7a99")
                        st.markdown(f'Status: <span style="color:{clr};font-weight:600">{rec.status.upper()}</span>', unsafe_allow_html=True)
                    st.divider()

        st.subheader("What-If Preview")
        all_pending_fields = [r.field for r in recs.recommendations if r.status == "pending"]
        selected_fields = st.multiselect(
            "Select fields to preview (simulates approval):",
            options=all_pending_fields,
            default=[],
            key=f"recs_preview_{memo.ticker}",
        )

        if selected_fields and st.button("Preview IV with selected approvals", key="preview_btn"):
            with st.spinner("Running preview DCF..."):
                try:
                    from src.stage_04_pipeline.recommendations import preview_with_approvals, write_recommendations as _wr
                    import copy as _copy
                    preview_recs = _copy.deepcopy(recs)
                    for r in preview_recs.recommendations:
                        if r.field in selected_fields:
                            r.status = "approved"
                    _wr(preview_recs)
                    preview = preview_with_approvals(memo.ticker, selected_fields)
                    if preview:
                        cur = preview.get("current_iv", {})
                        prop = preview.get("proposed_iv", {})
                        dlt = preview.get("delta_pct", {})
                        p_col1, p_col2, p_col3 = st.columns(3)
                        for col, scenario in zip([p_col1, p_col2, p_col3], ["bear", "base", "bull"]):
                            col.metric(
                                f"{scenario.capitalize()} IV",
                                f"${prop.get(scenario):,.2f}" if prop.get(scenario) else "—",
                                delta=f"{dlt.get(scenario):+.1f}%" if dlt.get(scenario) is not None else None,
                            )
                        _wr(recs)
                    else:
                        st.warning("Preview unavailable.")
                except Exception as e:
                    st.error(f"Preview error: {e}")

        st.subheader("Apply Approved Items")
        approved_count = sum(1 for r in recs.recommendations if r.status == "approved")
        st.caption(f"{approved_count} item(s) currently marked approved.")
        st.info(
            f"Edit `config/agent_recommendations_{memo.ticker.upper()}.yaml` — set `status: approved` — then click Apply."
        )
        if st.button("Apply Approved → valuation_overrides.yaml", type="primary", key="apply_btn"):
            try:
                from src.stage_04_pipeline.recommendations import apply_approved_to_overrides
                from src.stage_02_valuation.input_assembler import clear_valuation_overrides_cache
                count = apply_approved_to_overrides(memo.ticker)
                clear_valuation_overrides_cache()
                if count:
                    st.success(f"{count} override(s) written to config/valuation_overrides.yaml. Re-run valuation to see updated IV.")
                else:
                    st.warning("No approved items found — nothing written.")
            except Exception as e:
                st.error(f"Apply error: {e}")


# ── Section: Assumption Lab ───────────────────────────────────────────────────
if selected_section == "Assumption Lab":
    st.subheader("Assumption Lab")
    st.caption(
        "Compare current active values, deterministic defaults, and agent suggestions. "
        "Preview the valuation impact live in the sidebar, then apply selections into `config/valuation_overrides.yaml`."
    )
    st.caption("Units: percentages as whole %, debt/claims in USD millions, multiples in turns, NWC drivers in days.")

    try:
        from src.stage_04_pipeline.override_workbench import (
            apply_override_selections,
            build_override_workbench,
            load_override_audit_history,
            preview_override_selections,
        )
        workbench = build_override_workbench(memo.ticker)
    except Exception as e:
        workbench = None
        st.error(f"Workbench load error: {e}")

    if not workbench or not workbench.get("available"):
        st.info("Assumption lab unavailable. Run the analysis first.")
    else:
        head_a, head_b, head_c = st.columns(3)
        head_a.metric("Current Base IV", f"${workbench.get('current_iv_base', 0):,.2f}" if workbench.get("current_iv_base") else "—")
        head_b.metric("Current Price", f"${(workbench.get('current_price') or 0):,.2f}")
        head_c.metric("Tracked Fields", str(len(workbench.get("fields") or [])))

        st.divider()
        selections: dict[str, str] = {}
        custom_values: dict[str, float] = {}

        for row in workbench["fields"]:
            field = row["field"]
            options = ["default"]
            if row.get("agent_value") is not None:
                options.append("agent")
            options.append("custom")

            initial_mode = row.get("initial_mode", "default")
            if initial_mode not in options:
                initial_mode = "default"

            # Field header
            col_label, col_mode = st.columns([4, 1])
            with col_label:
                st.markdown(f"**{row['label']}** `{field}`")
            with col_mode:
                mode = st.selectbox(
                    "Mode",
                    options=options,
                    index=options.index(initial_mode),
                    label_visibility="collapsed",
                    key=f"assump_mode_{memo.ticker}_{field}",
                )
            selections[field] = mode

            val_col_a, val_col_b, val_col_c, val_col_d = st.columns(4)
            with val_col_a:
                st.caption(f"**Effective:** {_format_unit_value(row.get('effective_value'), row['unit'])}")
                st.caption(f"Source: {row.get('effective_source') or '—'}")
            with val_col_b:
                st.caption(f"**Default:** {_format_unit_value(row.get('baseline_value'), row['unit'])}")
                st.caption(f"Source: {row.get('baseline_source') or '—'}")
            with val_col_c:
                if row.get("agent_value") is not None:
                    agent_lbl = "agent" if mode != "agent" else "**→ agent**"
                    st.caption(f"{agent_lbl}: {_format_unit_value(row.get('agent_value'), row['unit'])}")
                    st.caption(f"{row.get('agent_name') or '?'} · {row.get('agent_confidence') or 'n/a'} · {row.get('agent_status') or 'pending'}")
                else:
                    st.caption("Agent: —")
            with val_col_d:
                default_custom = row.get("effective_value") or row.get("baseline_value")
                custom_display = st.number_input(
                    "Custom value",
                    value=float(_to_display_value(default_custom, row["unit"])),
                    step=_input_step(row["unit"]),
                    label_visibility="collapsed",
                    key=f"assump_custom_{memo.ticker}_{field}",
                    disabled=(mode != "custom"),
                )
            custom_values[field] = _from_display_value(custom_display, row["unit"])
            st.divider()

        # Live preview (feeds sidebar widget too)
        try:
            preview = preview_override_selections(
                memo.ticker,
                selections=selections,
                custom_values=custom_values,
            )
            st.session_state.workbench_preview = preview
        except Exception as e:
            preview = None
            st.session_state.workbench_preview = None
            st.error(f"Live preview error: {e}")

        if st.button("Apply selections → valuation_overrides.yaml", type="primary", key=f"assump_apply_{memo.ticker}"):
            try:
                apply_result = apply_override_selections(
                    memo.ticker,
                    selections=selections,
                    custom_values=custom_values,
                    actor="dashboard",
                )
                st.session_state.workbench_preview = apply_result.get("preview")
                st.success(
                    f"Applied {apply_result.get('applied_count', 0)} field selection(s) to "
                    "`config/valuation_overrides.yaml` and wrote audit rows to SQLite."
                )
            except Exception as e:
                st.error(f"Apply error: {e}")

        preview = st.session_state.workbench_preview
        if preview:
            st.subheader("Preview Delta")
            prev_cols = st.columns(4)
            for col, key in zip(prev_cols, ["bear", "base", "bull", "expected"]):
                current_value = preview.get("current_iv", {}).get(key) if key != "expected" else preview.get("current_expected_iv")
                proposed_value = preview.get("proposed_iv", {}).get(key) if key != "expected" else preview.get("proposed_expected_iv")
                delta_pct = None
                if key != "expected":
                    delta_pct = preview.get("delta_pct", {}).get(key)
                elif current_value and proposed_value:
                    delta_pct = round((proposed_value / current_value - 1.0) * 100.0, 1)
                col.metric(
                    f"{key.capitalize()} IV",
                    f"${proposed_value:,.2f}" if proposed_value is not None else "—",
                    delta=f"{delta_pct:+.1f}%" if delta_pct is not None else None,
                )

            resolved_rows = [
                {
                    "field": field,
                    "mode": meta.get("mode"),
                    "effective_before": meta.get("effective_value"),
                    "applied_value": meta.get("value"),
                }
                for field, meta in (preview.get("resolved_values") or {}).items()
            ]
            if resolved_rows:
                st.dataframe(resolved_rows, width="stretch", hide_index=True)

        st.subheader("Audit History")
        try:
            history = load_override_audit_history(memo.ticker, limit=50)
        except Exception as e:
            history = []
            st.error(f"Audit history error: {e}")

        if history:
            history_rows = [
                {
                    "timestamp": row["event_ts"],
                    "field": row["field"],
                    "mode": row["selection_mode"],
                    "baseline_source": row["baseline_source"],
                    "applied_value": row["applied_value"],
                    "action": row["write_action"],
                    "base_iv_before": row["current_iv_base"],
                    "base_iv_after": row["proposed_iv_base"],
                }
                for row in history
            ]
            st.dataframe(history_rows, width="stretch", hide_index=True)
        else:
            st.info("No dashboard override audit events stored yet for this ticker.")


# ── Section: Past Reports ─────────────────────────────────────────────────────
if selected_section == "Past Reports":
    st.subheader("Past Reports")
    st.caption("Archived full reports plus secondary agent-run history.")

    snapshot_rows = list_report_snapshots(memo.ticker, limit=50)
    if snapshot_rows:
        labels = [
            f"{row['created_at']} | {row.get('action') or '—'} | base ${row.get('base_iv') or 0:,.2f} | #{row['id']}"
            for row in snapshot_rows
        ]
        selected_snapshot_label = st.selectbox("Archived report", labels, key=f"archive_pick_{memo.ticker}")
        selected_snapshot = snapshot_rows[labels.index(selected_snapshot_label)]
        load_col, preview_col = st.columns([1, 3])
        with load_col:
            if st.button("Load Snapshot", key=f"load_snapshot_{selected_snapshot['id']}", width="stretch"):
                loaded = load_report_snapshot(int(selected_snapshot["id"]))
                if loaded:
                    st.session_state.memo = ICMemo(**loaded["memo"])
                    st.session_state.dcf_audit_view = (loaded.get("dashboard_snapshot") or {}).get("dcf_audit")
                    st.session_state.comps_view = (loaded.get("dashboard_snapshot") or {}).get("comps_view")
                    st.session_state.market_intel_view = (loaded.get("dashboard_snapshot") or {}).get("market_intel_view")
                    st.session_state.filings_browser_view = (loaded.get("dashboard_snapshot") or {}).get("filings_browser_view")
                    st.session_state.run_trace = loaded.get("run_trace") or []
                    st.session_state.report_snapshot_id = loaded["id"]
                    st.session_state.report_source = f"archive:{loaded['id']}"
                    st.rerun()
        with preview_col:
            st.dataframe(snapshot_rows, width="stretch", hide_index=True)
    else:
        st.info("No archived full reports yet for this ticker.")

    with st.expander("Agent Run History", expanded=False):
        try:
            from src.stage_04_pipeline.agent_cache import load_agent_run_history
            history_rows = load_agent_run_history(memo.ticker, limit=100)
        except Exception as e:
            history_rows = []
            st.error(f"History load error: {e}")
        if history_rows:
            st.dataframe(history_rows, width="stretch", hide_index=True)
        else:
            st.info("No agent run history found for this ticker.")


# ── Section: Macro ────────────────────────────────────────────────────────────
if selected_section == "Macro":
    st.subheader("Macro Intelligence")

    try:
        from src.stage_00_data.fred_client import get_macro_snapshot, get_yield_curve, get_regime_indicators
        from src.stage_02_valuation.regime_model import detect_current_regime, get_regime_badge_html, get_scenario_weights

        col_regime, col_vix, col_hy, col_slope, col_ff = st.columns(5)

        regime = detect_current_regime()
        weights = get_scenario_weights(regime)

        with col_regime:
            st.markdown("**Market Regime**")
            st.markdown(get_regime_badge_html(regime), unsafe_allow_html=True)
            if regime.available:
                for lbl, prob in regime.probabilities.items():
                    st.caption(f"{lbl}: {prob:.0%}")

        macro_snap = get_macro_snapshot(lookback_days=5)
        if macro_snap.get("available"):
            series = macro_snap.get("series", {})
            vix = series.get("VIXCLS", {}).get("latest_value")
            hy = series.get("BAMLH0A0HYM2", {}).get("latest_value")
            slope = series.get("T10Y2Y", {}).get("latest_value")
            ff_rate = series.get("FEDFUNDS", {}).get("latest_value")

            with col_vix:
                st.metric("VIX", f"{vix:.1f}" if vix else "—")
            with col_hy:
                st.metric("HY Spread (bps)", f"{hy*100:.0f}" if hy else "—")
            with col_slope:
                st.metric("2s10s Slope (bps)", f"{slope*100:.0f}" if slope else "—")
            with col_ff:
                st.metric("Fed Funds", f"{ff_rate:.2%}" if ff_rate else "—")

        st.divider()
        st.markdown("**DCF Scenario Weights (Regime-Adjusted)**")
        weight_cols = st.columns(3)
        weight_cols[0].metric("Bear", f"{weights.bear:.0%}")
        weight_cols[1].metric("Base", f"{weights.base:.0%}")
        weight_cols[2].metric("Bull", f"{weights.bull:.0%}")

        st.divider()
        st.markdown("**Yield Curve**")
        yc = get_yield_curve()
        if yc.get("available") and yc.get("maturities"):
            import plotly.graph_objects as go
            mats = yc["maturities"]
            fig_yc = go.Figure()
            fig_yc.add_trace(go.Scatter(
                x=[m[0] for m in mats],
                y=[m[2] for m in mats if m[2] is not None],
                mode="lines+markers",
                line=dict(color="#388bfd", width=2),
                marker=dict(size=6),
                name="Yield Curve",
            ))
            fig_yc.update_layout(
                template="plotly_dark",
                paper_bgcolor="#0d1117",
                plot_bgcolor="#0d1117",
                height=280,
                margin=dict(l=0, r=0, t=20, b=0),
                yaxis_title="Yield (%)",
                xaxis_title="Maturity",
            )
            st.plotly_chart(fig_yc, width="stretch")

    except Exception as exc:
        st.error(f"Macro data unavailable: {exc}")
        st.info("Set FRED_API_KEY environment variable to enable live macro data.")


# ── Section: Revisions ────────────────────────────────────────────────────────
if selected_section == "Revisions":
    st.subheader("Earnings Revision Tracker")

    try:
        from src.stage_00_data.estimate_tracker import get_revision_signals, snapshot_estimates

        sigs = get_revision_signals(memo.ticker)

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("EPS Rev (30d)", f"{sigs.eps_revision_30d_pct:+.1%}" if sigs.eps_revision_30d_pct is not None else "—")
        col2.metric("Rev Rev (30d)", f"{sigs.revenue_revision_30d_pct:+.1%}" if sigs.revenue_revision_30d_pct is not None else "—")
        col3.metric("EPS Rev (90d)", f"{sigs.eps_revision_90d_pct:+.1%}" if sigs.eps_revision_90d_pct is not None else "—")
        col4.metric("Est. Dispersion", f"{sigs.estimate_dispersion:.2%}" if sigs.estimate_dispersion is not None else "—")

        momentum_colors = {
            "strong_positive": "#22c55e", "positive": "#86efac",
            "neutral": "#6b7a99", "negative": "#fca5a5", "strong_negative": "#ef4444",
            "unavailable": "#6b7a99"
        }
        mom = sigs.revision_momentum
        color = momentum_colors.get(mom, "#6b7a99")
        st.markdown(f"**Revision Momentum:** <span style='color:{color};font-weight:700'>{mom.replace('_', ' ').title()}</span>", unsafe_allow_html=True)

        if not sigs.available:
            st.info(f"No revision history yet for {memo.ticker}.")
            if st.button("Snapshot current estimates"):
                result = snapshot_estimates(memo.ticker)
                if result.get("available"):
                    st.success("Estimates snapshot saved. Run again tomorrow to build revision history.")
                else:
                    st.warning(f"Snapshot failed: {result.get('error')}")

    except Exception as exc:
        st.error(f"Revision tracker error: {exc}")


# ── Section: Factor Exposure ──────────────────────────────────────────────────
if selected_section == "Factor Exposure":
    st.subheader("Factor Exposure Decomposition")

    try:
        from src.stage_02_valuation.factor_model import decompose_factor_exposure, get_factor_summary_text

        with st.spinner("Computing factor exposures (requires ~1yr of price history)..."):
            exposure = decompose_factor_exposure(memo.ticker)

        if exposure.available:
            st.caption(get_factor_summary_text(exposure))

            col1, col2, col3 = st.columns(3)
            col1.metric("Market Beta", f"{exposure.market_beta:.2f}" if exposure.market_beta else "—")
            col2.metric("R²", f"{exposure.r_squared:.1%}" if exposure.r_squared else "—")
            col3.metric("Alpha (ann.)", f"{exposure.annualized_alpha:+.1%}" if exposure.annualized_alpha else "—")

            col4, col5, col6 = st.columns(3)
            col4.metric("Value (HML)", f"{exposure.value_beta:.2f}" if exposure.value_beta else "—")
            col5.metric("Momentum", f"{exposure.momentum_beta:.2f}" if exposure.momentum_beta else "—")
            col6.metric("Quality (RMW)", f"{exposure.profitability_beta:.2f}" if exposure.profitability_beta else "—")

            if exposure.factor_attribution:
                import plotly.graph_objects as go
                factor_names = list(exposure.factor_attribution.keys())
                factor_vals = [exposure.factor_attribution[f] * 100 for f in factor_names]
                colors = ["#388bfd" if v >= 0 else "#ef4444" for v in factor_vals]

                fig_fa = go.Figure(go.Bar(
                    x=factor_names,
                    y=factor_vals,
                    marker_color=colors,
                    name="Factor Attribution (%)",
                ))
                fig_fa.update_layout(
                    template="plotly_dark",
                    paper_bgcolor="#0d1117",
                    plot_bgcolor="#0d1117",
                    height=280,
                    margin=dict(l=0, r=0, t=20, b=0),
                    yaxis_title="Attribution (%)",
                    title_text="",
                )
                st.plotly_chart(fig_fa, width="stretch")

            if exposure.r_squared and exposure.r_squared > 0.85:
                st.warning("High R² (>85%) — returns highly systematic. Alpha opportunity may be limited.")
        else:
            st.info(f"Factor exposure unavailable: {exposure.error}")

    except Exception as exc:
        st.error(f"Factor model error: {exc}")


# ── Section: Export ───────────────────────────────────────────────────────────
if selected_section == "Export":
    st.subheader("Export Report")

    # JSON export
    st.markdown("#### IC Memo JSON")
    st.download_button(
        label="Download IC Memo JSON",
        data=memo.model_dump_json(indent=2),
        file_name=f"{memo.ticker}_ic_memo_{memo.date}.json",
        mime="application/json",
    )

    # HTML report
    st.markdown("#### HTML Report")
    st.caption("Self-contained HTML file — open in any browser, print to PDF via Ctrl+P.")

    def _build_html_report(m) -> str:
        val = m.valuation
        price = val.current_price or 0
        upside = (val.upside_pct_base or 0) * 100
        action_col = {"BUY": "#3fb950", "SELL SHORT": "#f85149", "WATCH": "#d29922", "PASS": "#8b949e"}.get(m.action, "#8b949e")

        def _row(label, value):
            return f"<tr><td style='color:#8b949e;padding:4px 8px'>{label}</td><td style='padding:4px 8px;font-weight:600'>{value}</td></tr>"

        flags_html = "".join(f"<li style='color:#f85149'>{_fix_text(x)}</li>" for x in (m.filings.red_flags or []))
        catalysts_html = "".join(f"<li>{x}</li>" for x in m.key_catalysts)
        risks_html = "".join(f"<li>{x}</li>" for x in m.key_risks)
        questions_html = "".join(f"<li>{x}</li>" for x in m.open_questions)
        filings_notes_html = "".join(f"<li>{_fix_text(x)}</li>" for x in (m.filings.notes_watch_items or []))
        risk_overlay_html = "".join(
            f"<li>{overlay.risk_name} — p={overlay.probability:.0%}, "
            f"Δgrowth {overlay.revenue_growth_near_bps}bps, Δmargin {overlay.ebit_margin_bps}bps, "
            f"ΔWACC {overlay.wacc_bps}bps</li>"
            for overlay in (m.risk_impact.overlays or [])
        )

        return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>{m.ticker} — IC Memo {m.date}</title>
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background:#0d1117; color:#e2e8f0; max-width:960px; margin:40px auto; padding:0 24px; }}
h1 {{ color:#f0f6fc; }} h2 {{ color:#388bfd; border-bottom:1px solid #21262d; padding-bottom:8px; margin-top:32px; }}
h3 {{ color:#c9d1d9; }}
.badge {{ display:inline-block; padding:4px 12px; border-radius:4px; font-weight:700; font-size:1.1em; color:#fff; background:{action_col}; }}
.metric-grid {{ display:grid; grid-template-columns:repeat(5,1fr); gap:12px; margin:20px 0; }}
.metric {{ background:#161b22; border:1px solid #21262d; border-radius:8px; padding:16px; }}
.metric-label {{ color:#8b949e; font-size:0.75rem; text-transform:uppercase; letter-spacing:0.04em; }}
.metric-value {{ color:#f0f6fc; font-size:1.4rem; font-weight:700; margin-top:4px; }}
.cases {{ display:grid; grid-template-columns:1fr 1fr 1fr; gap:16px; }}
.case {{ background:#161b22; border:1px solid #21262d; border-radius:8px; padding:16px; }}
.one-liner {{ background:#162032; border-left:3px solid #388bfd; padding:12px 16px; border-radius:6px; margin:16px 0; }}
.variant {{ background:#1f1a00; border-left:3px solid #d29922; padding:12px 16px; border-radius:6px; margin:16px 0; }}
table {{ width:100%; border-collapse:collapse; }} td,th {{ border:1px solid #21262d; padding:6px 10px; }}
th {{ background:#161b22; color:#8b949e; font-weight:600; font-size:0.85rem; }}
ul {{ padding-left:24px; }} li {{ margin-bottom:4px; line-height:1.6; }}
@media print {{
  body {{ background: #ffffff; color: #111827; }}
  .metric, .case, .one-liner, .variant {{ break-inside: avoid; border-color: #d1d5db; background: #ffffff; color: #111827; }}
  h1, h2, h3, p, li, td, th {{ color: #111827 !important; }}
}}
</style>
</head>
<body>
<h1><span class="badge">{m.action}</span> {m.ticker} — {m.company_name}</h1>
<p style="color:#8b949e">{m.sector} · {m.date} · Analyst: {m.analyst}</p>
<div class="metric-grid">
  <div class="metric"><div class="metric-label">Action</div><div class="metric-value">{m.action}</div></div>
  <div class="metric"><div class="metric-label">Conviction</div><div class="metric-value">{m.conviction.upper()}</div></div>
  <div class="metric"><div class="metric-label">Current Price</div><div class="metric-value">${price:,.2f}</div></div>
  <div class="metric"><div class="metric-label">Base Case IV</div><div class="metric-value">${val.base:,.2f}</div></div>
  <div class="metric"><div class="metric-label">Upside (Base)</div><div class="metric-value">{upside:+.1f}%</div></div>
</div>
<div class="one-liner"><strong>One-liner:</strong> {m.one_liner}</div>
<div class="variant"><strong>Variant Thesis:</strong> {m.variant_thesis_prompt}</div>
<h2>DCF Scenarios</h2>
<table>
<tr><th>Scenario</th><th>Intrinsic Value</th><th>Upside / (Downside)</th></tr>
<tr><td>Bear</td><td>${val.bear:.2f}</td><td>{((val.bear-price)/price*100):+.1f}%</td></tr>
<tr><td>Base</td><td>${val.base:.2f}</td><td>{((val.base-price)/price*100):+.1f}%</td></tr>
<tr><td>Bull</td><td>${val.bull:.2f}</td><td>{((val.bull-price)/price*100):+.1f}%</td></tr>
</table>
<h2>Investment Thesis</h2>
<div class="cases">
  <div class="case"><h3>Bull Case</h3><p>{m.bull_case}</p></div>
  <div class="case"><h3>Base Case</h3><p>{m.base_case}</p></div>
  <div class="case"><h3>Bear Case</h3><p>{m.bear_case}</p></div>
</div>
<h2>Key Catalysts</h2><ul>{catalysts_html}</ul>
<h2>Key Risks</h2><ul>{risks_html}</ul>
{"<h2>Risk Impact</h2><ul>" + risk_overlay_html + "</ul>" if risk_overlay_html else ""}
{"<h2>Red Flags (Filings)</h2><ul>" + flags_html + "</ul>" if flags_html else ""}
{"<h2>Filing Note Watch Items</h2><ul>" + filings_notes_html + "</ul>" if filings_notes_html else ""}
<h2>Open Questions</h2><ul>{questions_html}</ul>
<h2>Filings Analysis</h2><p>{_fix_text(m.filings.raw_summary or "")}</p>
<h2>Earnings Analysis</h2><p>{_fix_text(m.earnings.raw_summary or "")}</p>
<h2>Sentiment</h2><p>{_fix_text(m.sentiment.raw_summary or "")}</p>
<hr style="border-color:#21262d;margin-top:48px">
<p style="color:#8b949e;font-size:0.8rem">Generated by AI Research Pod · {m.date}</p>
</body>
</html>"""

    html_report = _build_html_report(memo)
    st.download_button(
        label="Download HTML Report",
        data=html_report,
        file_name=f"{memo.ticker}_ic_memo_{memo.date}.html",
        mime="text/html",
    )

    with st.expander("Preview HTML", expanded=False):
        st.components.v1.html(html_report, height=600, scrolling=True)

    # Research note
    st.markdown("#### AI Research Note")
    st.caption("LLM-synthesized equity research note combining all pipeline outputs.")

    col_note_a, col_note_b = st.columns([1, 3])
    with col_note_a:
        use_offline = st.checkbox("Offline mode (no LLM)", value=False)
    with col_note_b:
        generate_note = st.button("Generate Research Note", type="primary")

    if generate_note:
        with st.spinner("Generating research note..."):
            try:
                from src.stage_03_judgment.research_note_agent import ResearchNoteAgent, generate_research_note_offline
                from src.stage_04_pipeline.report_export import export_research_note_for_download

                # Gather optional context
                _macro_ctx = None
                _rev_ctx = None
                _forensic_ctx = None
                _factor_ctx = None

                try:
                    from src.stage_00_data.fred_client import get_regime_indicators
                    _macro_ctx = get_regime_indicators()
                except Exception:
                    pass
                try:
                    from src.stage_00_data.estimate_tracker import get_revision_signals
                    _rev_sigs = get_revision_signals(memo.ticker)
                    if _rev_sigs.available:
                        import dataclasses
                        _rev_ctx = dataclasses.asdict(_rev_sigs)
                except Exception:
                    pass
                try:
                    from src.stage_03_judgment.forensic_scores import compute_forensic_signals
                    _fh = md_client.get_historical_financials(memo.ticker)
                    _fm = md_client.get_market_data(memo.ticker)
                    _fmcap_mm = (_fm.get("market_cap") or 0) / 1e6 or None
                    _forensic_ctx = compute_forensic_signals(_fh, _fmcap_mm, memo.sector)
                except Exception:
                    pass

                memo_dict = memo.model_dump()

                if use_offline:
                    note = generate_research_note_offline(memo_dict, _macro_ctx, _rev_ctx, _forensic_ctx, _factor_ctx)
                else:
                    agent = ResearchNoteAgent()
                    note = agent.generate_research_note(memo_dict, _macro_ctx, _rev_ctx, _forensic_ctx, _factor_ctx)

                html_content, filename = export_research_note_for_download(note, memo_dict)
                st.success("Research note generated.")
                st.download_button(
                    label="Download Research Note (HTML)",
                    data=html_content,
                    file_name=filename,
                    mime="text/html",
                    key="research_note_dl",
                )

                with st.expander("Preview Note"):
                    for section_name in ["executive_summary", "investment_thesis", "variant_view", "valuation_summary", "earnings_quality", "macro_context", "factor_profile", "key_risks"]:
                        section_text = getattr(note, section_name, "")
                        if section_text:
                            st.markdown(f"**{section_name.replace('_', ' ').title()}**")
                            st.markdown(section_text)
                            st.divider()

            except Exception as exc:
                st.error(f"Research note generation failed: {exc}")


# ── Section: Raw JSON ─────────────────────────────────────────────────────────
if selected_section == "Raw JSON":
    st.subheader("Full IC Memo JSON")
    st.download_button(
        label="Download JSON",
        data=memo.model_dump_json(indent=2),
        file_name=f"{memo.ticker}_ic_memo.json",
        mime="application/json",
    )
    st.json(json.loads(memo.model_dump_json()))


# ── Agent Audit Trail ─────────────────────────────────────────────────────────
st.divider()
with st.expander("Agent Audit Trail", expanded=False):
    st.caption("Exact agent prompts, tool traces, raw outputs, and parsed artifacts for recent runs.")
    try:
        from src.stage_04_pipeline.agent_cache import (
            artifact_has_meaningful_io,
            load_agent_run_artifact,
            load_latest_agent_artifacts_by_ticker,
        )
        audit_rows = load_latest_agent_artifacts_by_ticker(memo.ticker, limit=100)
    except Exception as e:
        audit_rows = []
        st.error(f"Agent artifact load error: {e}")

    if not audit_rows:
        st.info("No stored agent artifacts available yet for this ticker.")
    else:
        agent_options = sorted({row["agent_name"] for row in audit_rows})
        selected_agent = st.selectbox("Agent", options=agent_options, key=f"audit_agent_{memo.ticker}")
        filtered = [row for row in audit_rows if row["agent_name"] == selected_agent]
        run_labels = [
            f"{row['run_ts']} | {row['status']} | {'cache' if row['cache_hit'] else 'exec'} | {row['run_log_id']}"
            for row in filtered
        ]
        selected_label = st.selectbox("Run", options=run_labels, key=f"audit_run_{memo.ticker}_{selected_agent}")
        selected_row = filtered[run_labels.index(selected_label)]
        artifact = load_agent_run_artifact(selected_row["run_log_id"])
        artifact_needs_refresh = not artifact_has_meaningful_io(artifact, selected_agent)

        meta_cols = st.columns(6)
        meta_cols[0].metric("Status", selected_row["status"])
        meta_cols[1].metric("Cache", "yes" if selected_row["cache_hit"] else "no")
        meta_cols[2].metric("Forced Refresh", "yes" if selected_row["forced_refresh"] else "no")
        meta_cols[3].metric("Duration", f"{selected_row['duration_ms']} ms" if selected_row["duration_ms"] is not None else "—")
        meta_cols[4].metric("Model", selected_row["model"] or "—")
        meta_cols[5].metric("Prompt Version", selected_row["prompt_version"] or "—")

        if artifact_needs_refresh:
            st.warning(
                "Legacy cached run — missing full prompt/output artifacts. "
                "Refresh the selected agent to store a complete audit payload."
            )
            if st.button(
                "Refresh artifact by rerunning this agent",
                key=f"refresh_artifact_{memo.ticker}_{selected_agent}_{selected_row['run_log_id']}",
                width="stretch",
            ):
                with st.spinner(f"Refreshing {selected_agent} for {memo.ticker}..."):
                    from src.stage_04_pipeline.orchestrator import PipelineOrchestrator
                    from src.stage_04_pipeline.recommendations import write_recommendations
                    orch = PipelineOrchestrator()
                    refreshed_memo = orch.run(
                        memo.ticker,
                        use_cache=True,
                        force_refresh_agents={selected_agent},
                    )
                    st.session_state.memo = refreshed_memo
                    st.session_state.run_trace = orch.last_run_trace
                    try:
                        recs = orch.collect_recommendations(memo.ticker)
                        write_recommendations(recs)
                        st.session_state.recommendations = recs
                    except Exception:
                        st.session_state.recommendations = None
                st.rerun()

        if artifact is None:
            st.info("No artifact payload stored for this run.")
        else:
            token_cols = st.columns(3)
            token_cols[0].metric("Prompt Tokens", artifact.get("prompt_tokens") or "—")
            token_cols[1].metric("Completion Tokens", artifact.get("completion_tokens") or "—")
            token_cols[2].metric("Total Tokens", artifact.get("total_tokens") or "—")

            no_llm = not artifact.get("user_prompt") and selected_agent == "ValuationAgent"
            if no_llm:
                st.info("No LLM call: deterministic valuation adapter.")

            prompt_tab, user_tab, schema_tab, trace_tab, raw_tab, parsed_tab = st.tabs(
                ["System Prompt", "User Prompt", "Tool Schema", "Tool Trace", "Raw Output", "Parsed Output"]
            )
            with prompt_tab:
                st.code(artifact.get("system_prompt") or "—", language="text")
            with user_tab:
                st.code(artifact.get("user_prompt") or "—", language="text")
            with schema_tab:
                if artifact.get("tool_schema_json") is not None:
                    st.json(artifact["tool_schema_json"])
                else:
                    st.write("No tool schema for this run.")
            with trace_tab:
                if artifact.get("api_trace_json"):
                    st.json(artifact["api_trace_json"])
                else:
                    st.write("No tool calls for this run.")
            with raw_tab:
                st.text_area(
                    "raw_output",
                    value=artifact.get("raw_final_output") or "—",
                    height=240,
                    label_visibility="collapsed",
                    key=f"raw_output_{selected_row['run_log_id']}",
                )
            with parsed_tab:
                if artifact.get("parsed_output_json") is not None:
                    st.json(artifact["parsed_output_json"])
                else:
                    st.write("No parsed output stored for this run.")

            dl_col1, dl_col2 = st.columns(2)
            dl_col1.download_button(
                "Artifact JSON",
                data=json.dumps(artifact, indent=2, default=str),
                file_name=f"{memo.ticker}_{selected_agent}_{selected_row['run_log_id']}_artifact.json",
                mime="application/json",
                key=f"artifact_dl_{selected_row['run_log_id']}",
            )
            dl_col2.download_button(
                "Raw Output",
                data=artifact.get("raw_final_output") or "",
                file_name=f"{memo.ticker}_{selected_agent}_{selected_row['run_log_id']}_raw.txt",
                mime="text/plain",
                key=f"raw_dl_{selected_row['run_log_id']}",
            )



