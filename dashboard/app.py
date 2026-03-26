"""
Streamlit dashboard — AI Hedge Fund Research Pod.
Run: streamlit run dashboard/app.py
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import streamlit as st

from config import LLM_MODEL
from dashboard.design_system import DASHBOARD_CSS, render_shell_header
from dashboard.dossier_companion import render_dossier_companion
from dashboard.sections import SECTION_REGISTRY
from src.stage_02_valuation.templates.ic_memo import ICMemo
from src.stage_04_pipeline.ciq_admin import get_ciq_runtime_status, run_ciq_operation
from src.stage_04_pipeline.comps_dashboard import build_comps_dashboard_view
from src.stage_04_pipeline.dcf_audit import build_dcf_audit_view
from src.stage_04_pipeline.filings_browser import build_filings_browser_view
from src.stage_04_pipeline.news_materiality import build_news_materiality_view
from src.stage_04_pipeline.report_archive import (
    list_report_snapshots,
    load_report_snapshot,
    save_report_snapshot,
)

st.set_page_config(
    page_title="AI Research Pod",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(DASHBOARD_CSS, unsafe_allow_html=True)

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

_PRIMARY_TABS = ["Overview", "Valuation", "Market", "Research", "Audit"]
_NO_MEMO_PRIMARY_TABS = ["Overview", "Market", "Audit"]
PAGE_DESCRIPTIONS = {
    "Overview": "Cross-functional cockpit for the loaded ticker.",
    "Valuation": "DCF, comps, WACC, and assumptions organized around one valuation workflow.",
    "Market": "Macro, revisions, sentiment, and factor framing.",
    "Research": "Working research board backed by tracker state and notebook blocks.",
    "Audit": "Pipeline, filings evidence, exports, and dossier administration.",
}
_SESSION_DEFAULTS = {
    "memo": None,
    "running": False,
    "recommendations": None,
    "workbench_preview": None,
    "run_trace": [],
    "ciq_last_result": None,
    "dcf_audit_view": None,
    "filings_browser_view": None,
    "comps_view": None,
    "market_intel_view": None,
    "report_snapshot_id": None,
    "report_source": "live",
    "wacc_preview": None,
    "chat_history": {},
    "selected_primary_tab": "Overview",
    "valuation_view": "Summary",
    "market_view": "Summary",
    "research_view": "Board",
    "audit_view": "Overview",
    "notes_rail_open": False,
    "note_context": None,
}


def _ensure_session_defaults() -> None:
    for key, value in _SESSION_DEFAULTS.items():
        if key not in st.session_state:
            st.session_state[key] = value


def _clear_dashboard_views() -> None:
    for key in [
        "recommendations",
        "run_trace",
        "dcf_audit_view",
        "filings_browser_view",
        "comps_view",
        "market_intel_view",
        "wacc_preview",
        "workbench_preview",
    ]:
        st.session_state[key] = _SESSION_DEFAULTS[key]


def _hydrate_loaded_snapshot(loaded: dict) -> None:
    st.session_state.memo = ICMemo(**loaded["memo"])
    dashboard_snapshot = loaded.get("dashboard_snapshot") or {}
    st.session_state.dcf_audit_view = dashboard_snapshot.get("dcf_audit")
    st.session_state.comps_view = dashboard_snapshot.get("comps_view")
    st.session_state.market_intel_view = dashboard_snapshot.get("market_intel_view")
    st.session_state.filings_browser_view = dashboard_snapshot.get("filings_browser_view")
    st.session_state.run_trace = loaded.get("run_trace") or []
    st.session_state.report_snapshot_id = loaded["id"]
    st.session_state.report_source = f"archive:{loaded['id']}"
    st.session_state.selected_primary_tab = "Overview"


def _load_latest_archive_snapshot(ticker: str) -> None:
    snapshots = list_report_snapshots(ticker, limit=1)
    if not snapshots:
        st.warning(f"No archived snapshots found for {ticker}. Run the analysis first.")
        return
    loaded = load_report_snapshot(int(snapshots[0]["id"]))
    if not loaded:
        st.error("Failed to load snapshot.")
        return
    _hydrate_loaded_snapshot(loaded)
    st.rerun()


def _render_sidebar() -> tuple[str, bool, bool, list[str]]:
    with st.sidebar:
        st.markdown("## AI Research Pod")
        st.caption("Fundamental analysis pipeline")
        st.divider()

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
                _load_latest_archive_snapshot(ql_ticker)

        with st.expander("CIQ Tools", expanded=False):
            ciq_folder = st.text_input(
                "CIQ workbook folder",
                value=str(get_ciq_runtime_status().get("folder", "")),
                help="Folder containing populated CIQ workbooks.",
            )
            ciq_status = get_ciq_runtime_status(ciq_folder)
            st.caption(f"Env: `{ciq_status['recommended_env']}` | Active: `{ciq_status['active_env'] or 'unknown'}`")
            module_rows = [{"module": name, "available": "yes" if ok else "no"} for name, ok in ciq_status["module_status"].items()]
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
            st.caption("Workbooks: " + ", ".join(candidates) if candidates else "No candidate workbooks found.")
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
                        f"{ciq_last_result.get('action')}: ok={report.get('processed', 0)}, skip={report.get('skipped', 0)}, fail={report.get('failed', 0)}"
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

    return ticker_input, run_btn, use_agent_cache, force_refresh_agents


def _run_pipeline(ticker_input: str, *, use_agent_cache: bool, force_refresh_agents: list[str]) -> None:
    st.session_state.running = True
    st.session_state.memo = None
    _clear_dashboard_views()

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
        placeholders = {step: st.empty() for step in steps}
        for step in steps:
            placeholders[step].markdown(f"⏳ {step}")

        try:
            from src.stage_04_pipeline.orchestrator import PipelineOrchestrator
            from src.stage_04_pipeline.recommendations import write_recommendations

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

            orchestrator = StreamingOrchestrator()
            memo = orchestrator.run(
                ticker_input,
                use_cache=use_agent_cache,
                force_refresh_agents=set(force_refresh_agents),
            )
            st.session_state.memo = memo
            st.session_state.run_trace = orchestrator.last_run_trace
            st.session_state.report_source = "live"
            st.session_state.selected_primary_tab = "Overview"
            try:
                recs = orchestrator.collect_recommendations(ticker_input)
                write_recommendations(recs)
                st.session_state.recommendations = recs
            except Exception:
                st.session_state.recommendations = None

            try:
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
                    run_trace=orchestrator.last_run_trace,
                )
            except Exception as snapshot_exc:
                status.write(f"Archive/view build warning: {snapshot_exc}")

            status.update(label=f"Analysis complete — **{ticker_input}**", state="complete")
        except Exception as exc:
            status.update(label=f"Pipeline error: {exc}", state="error")

    st.session_state.running = False


def _ensure_nav_selection(key: str, default: str, options: list[str]) -> None:
    if st.session_state.get(key) not in options:
        st.session_state[key] = default


def _current_subpage_label(tab: str) -> str:
    mapping = {
        "Overview": "Cockpit",
        "Valuation": st.session_state.get("valuation_view", "Summary"),
        "Market": st.session_state.get("market_view", "Summary"),
        "Research": st.session_state.get("research_view", "Board"),
        "Audit": st.session_state.get("audit_view", "Overview"),
    }
    return mapping.get(tab, "")


def _build_page_context(selected_primary_tab: str, memo: ICMemo | None) -> dict[str, str]:
    explicit_context = st.session_state.get("note_context") or {}
    subpage = _current_subpage_label(selected_primary_tab)
    item = subpage or selected_primary_tab
    detail = ""
    if memo is not None:
        ticker = memo.ticker
        if selected_primary_tab == "Valuation":
            if subpage == "Comparables":
                detail = st.session_state.get(f"comps_metric_{ticker}", "")
            elif subpage == "Multiples":
                detail = st.session_state.get(f"historical_multiple_{ticker}", "")
        elif selected_primary_tab == "Research":
            if subpage == "Board":
                detail = st.session_state.get(f"research_board_type_{ticker}", "")
        elif selected_primary_tab == "Audit":
            if subpage == "Dossier Admin":
                detail = st.session_state.get(f"dossier_admin_view_{ticker}", "")
            elif subpage == "Filings & Evidence":
                filing_label = st.session_state.get(f"filing_browser_sel_{ticker}", "")
                if filing_label:
                    accession = filing_label.split(" | ")[-1]
                    filing_view = st.session_state.get(f"filing_view_mode_{ticker}_{accession}", "")
                    detail = f"{filing_label} · {filing_view}" if filing_view else filing_label

    if detail:
        item = f"{subpage} · {detail}"
    fallback_context = {
        "page": selected_primary_tab,
        "subpage": subpage or "Overview",
        "item": item,
    }
    if explicit_context.get("page") == selected_primary_tab:
        return {
            "page": explicit_context.get("page") or fallback_context["page"],
            "subpage": explicit_context.get("subpage") or fallback_context["subpage"],
            "item": explicit_context.get("item") or fallback_context["item"],
        }
    return fallback_context


def _render_empty_state() -> None:
    st.markdown(
        """
### Enter a ticker to get started

Three ways to use the dashboard:

1. Run a full ticker analysis from the sidebar.
2. Use **Market → Macro** for the cross-market backdrop.
3. Use **Audit → Pipeline** or **Audit → Portfolio Risk** for ticker-free operational views.

Core workflow once a ticker is loaded:

- overview cockpit and research board
- deterministic valuation and comps
- market context, filings evidence, and audit review

> **Your job:** Write the variant thesis. The system surfaces the evidence; you decide why the market is wrong.
"""
    )


def main() -> None:
    _ensure_session_defaults()
    ticker_input, run_btn, use_agent_cache, force_refresh_agents = _render_sidebar()
    if run_btn and ticker_input:
        _run_pipeline(ticker_input, use_agent_cache=use_agent_cache, force_refresh_agents=force_refresh_agents)

    memo = st.session_state.memo
    available_primary_tabs = _PRIMARY_TABS if memo is not None else _NO_MEMO_PRIMARY_TABS
    _ensure_nav_selection("selected_primary_tab", "Overview" if memo is not None else "Market", available_primary_tabs)

    selected_primary_tab = st.segmented_control(
        "Primary tabs",
        options=available_primary_tabs,
        key="selected_primary_tab",
        label_visibility="collapsed",
    )

    st.divider()

    shell_col, shell_tools_col = st.columns([0.82, 0.18], gap="large", vertical_alignment="top")
    with shell_col:
        render_shell_header(
            workspace=selected_primary_tab,
            section=_current_subpage_label(selected_primary_tab),
            description=PAGE_DESCRIPTIONS.get(selected_primary_tab, ""),
            ticker=(memo.ticker if memo is not None else None),
            company_name=(memo.company_name if memo is not None else None),
        )

    with shell_tools_col:
        if memo is not None:
            st.markdown("##### Notes")
            st.caption("Collapsible right-side research companion.")
            st.toggle("Show Notes Rail", key="notes_rail_open")

    notes_rail_open = memo is not None and bool(st.session_state.get("notes_rail_open", False))
    if notes_rail_open:
        main_col, notes_col = st.columns([0.74, 0.26], gap="large", vertical_alignment="top")
    else:
        main_col = st.container()
        notes_col = None

    with main_col:
        if memo is None:
            _render_empty_state()
        else:
            st.markdown(f"## {memo.ticker} — {memo.company_name}")
            st.caption(f"{memo.sector}  ·  {memo.date}  ·  Analyst: {memo.analyst}")
            col1, col2, col3, col4, col5 = st.columns(5)
            col1.metric("Action", memo.action)
            col2.metric("Conviction", memo.conviction.upper())
            col3.metric("Current Price", f"${memo.valuation.current_price or 0:,.2f}")
            col4.metric("Base Case IV", f"${memo.valuation.base:,.2f}")
            col5.metric("Upside (base)", f"{(memo.valuation.upside_pct_base or 0) * 100:+.1f}%")
            st.info(f"**One-liner:** {memo.one_liner}")
            st.warning(
                f"**Variant Thesis:** {memo.variant_thesis_prompt}\n\n_This is the question the AI cannot answer for you. Answer this before sizing the position._"
            )

        SECTION_REGISTRY[selected_primary_tab](memo, st.session_state)

    if notes_col is not None and memo is not None:
        with notes_col:
            st.markdown("### Dossier")
            st.caption("Context-linked research capture and notebook blocks.")
            render_dossier_companion(memo, page_context=_build_page_context(selected_primary_tab, memo))


main()
