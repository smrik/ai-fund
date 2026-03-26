from __future__ import annotations

from typing import Any

import streamlit as st

from dashboard.deep_dive_sections import render_business, render_company_hub, render_model_and_valuation, render_sources
from src.stage_04_pipeline.agent_cache import load_agent_run_history

from . import export as export_section
from . import filings_browser, portfolio_risk
from ._shared import render_clean_table, set_note_context

_AUDIT_VIEWS = ["Overview", "Pipeline", "Filings & Evidence", "Portfolio Risk", "Dossier Admin", "Export"]


def _render_overview(memo, session_state: Any | None) -> None:
    state = session_state or st.session_state
    run_trace = state.get("run_trace") or []
    filings_view = state.get("filings_browser_view") or {}
    cols = st.columns(3)
    cols[0].metric("Pipeline Steps", str(len(run_trace)))
    cols[1].metric("Report Snapshot", str(state.get("report_snapshot_id") or "—"))
    cols[2].metric("Coverage Rows", str(len((filings_view.get("coverage_summary") or {}).get("forms", []))))
    st.write("- Audit is the operating review layer: pipeline, filings evidence, exports, and dossier admin tools.")


def _render_pipeline(memo, session_state: Any | None) -> None:
    state = session_state or st.session_state
    set_note_context(state, page="Audit", subpage="Pipeline", item="Pipeline Run Trace")
    latest_trace = state.get("run_trace") or []
    if latest_trace:
        render_clean_table(latest_trace, column_order=None)
    else:
        st.info("No in-session run trace yet. Run the pipeline from this dashboard to populate it.")

    try:
        run_history = load_agent_run_history(memo.ticker, limit=50)
    except Exception as exc:
        run_history = []
        st.error(f"Agent run history error: {exc}")
    if run_history:
        st.markdown("#### Recent Agent Run History")
        render_clean_table(run_history, column_order=None)
    else:
        st.info("No persisted agent-run history stored yet for this ticker.")


def _render_dossier_admin(memo, session_state: Any | None) -> None:
    set_note_context(session_state, page="Audit", subpage="Dossier Admin", item="Dossier Admin")
    st.subheader("Dossier Admin")
    admin_view = st.selectbox(
        "Dossier Admin View",
        options=["Company Hub", "Business", "Model & Valuation", "Sources"],
        key=f"dossier_admin_view_{memo.ticker}",
    )
    set_note_context(session_state, page="Audit", subpage="Dossier Admin", item=admin_view)
    if admin_view == "Company Hub":
        render_company_hub(memo)
    elif admin_view == "Business":
        render_business(memo)
    elif admin_view == "Model & Valuation":
        render_model_and_valuation(memo)
    else:
        render_sources(memo)


def render(memo, session_state: Any | None) -> None:
    state = session_state or st.session_state
    current_view = state.get("audit_view", "Overview")
    if current_view not in _AUDIT_VIEWS:
        current_view = "Overview"
        state["audit_view"] = current_view

    selected_view = st.segmented_control(
        "Audit view",
        options=_AUDIT_VIEWS,
        key="audit_view",
        label_visibility="collapsed",
    )
    set_note_context(state, page="Audit", subpage=selected_view, item=selected_view)

    if memo is None:
        if selected_view == "Pipeline":
            st.subheader("Pipeline")
            latest_trace = state.get("run_trace") or []
            if latest_trace:
                render_clean_table(latest_trace, column_order=None)
            else:
                st.info("No in-session run trace yet. Load a ticker and run the pipeline to populate it.")
        elif selected_view == "Portfolio Risk":
            portfolio_risk.render(None, session_state=state)
        else:
            st.info("Load a ticker to use this audit surface. Pipeline and Portfolio Risk remain available without a loaded memo.")
        return

    if selected_view == "Pipeline":
        _render_pipeline(memo, session_state=state)
    elif selected_view == "Filings & Evidence":
        filings_browser.render(memo, session_state=state)
    elif selected_view == "Portfolio Risk":
        portfolio_risk.render(memo, session_state=state)
    elif selected_view == "Dossier Admin":
        _render_dossier_admin(memo, session_state=state)
    elif selected_view == "Export":
        export_section.render(memo, session_state=state)
    else:
        _render_overview(memo, session_state=state)
