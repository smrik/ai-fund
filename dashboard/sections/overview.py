from __future__ import annotations

from typing import Any

import streamlit as st

from src.stage_04_pipeline.dossier_view import build_thesis_tracker_view
from src.stage_04_pipeline.news_materiality import build_news_materiality_view

from ._shared import render_change_list, render_compact_list, render_drilldown_button, set_note_context


def render(memo, session_state: Any | None) -> None:
    if memo is None:
        st.info("Load a ticker to view the overview cockpit.")
        return

    state = session_state or st.session_state
    set_note_context(state, page="Overview", subpage="Cockpit", item="Overview Cockpit")
    tracker_view = build_thesis_tracker_view(memo.ticker)
    market_view = state.get("market_intel_view") or build_news_materiality_view(memo.ticker)
    comps_view = state.get("comps_view") or {}

    st.markdown("### Overview")
    st.caption("One-page cockpit for stance, valuation, market pulse, and audit health.")

    top = st.columns(3)
    top[0].metric("Action", memo.action)
    top[1].metric("Base IV", f"${memo.valuation.base:,.2f}")
    top[2].metric("Current Price", f"${memo.valuation.current_price or 0:,.2f}")

    left, right = st.columns([1.1, 0.9], gap="large")
    with left:
        st.markdown("#### Thesis And Change")
        st.write(memo.one_liner)
        render_change_list("What changed", (tracker_view.get("what_changed") or {}).get("summary_lines") or [])
        render_compact_list("Open questions", (tracker_view.get("next_queue") or {}).get("open_questions") or [], max_items=4)
        render_drilldown_button(
            "Open Research →",
            target_tab="Research",
            session_state=state,
            key="overview_open_research",
        )

        st.markdown("#### Valuation Pulse")
        st.write(f"- Bull / Base / Bear: ${memo.valuation.bull:,.2f} / ${memo.valuation.base:,.2f} / ${memo.valuation.bear:,.2f}")
        if comps_view.get("available"):
            st.caption("Comparables and multiple history are available in Valuation.")
        render_drilldown_button(
            "Open Valuation →",
            target_tab="Valuation",
            target_key="valuation_view",
            target_value="Summary",
            session_state=state,
            key="overview_open_valuation",
        )

    with right:
        st.markdown("#### Market Pulse")
        historical_brief = (market_view.get("historical_brief") or {}).get("summary") or "No historical brief available."
        st.write(historical_brief)
        if market_view.get("quarterly_headlines"):
            st.caption("Recent headlines are available in Market.")
        render_drilldown_button(
            "Open Market →",
            target_tab="Market",
            target_key="market_view",
            target_value="Summary",
            session_state=state,
            key="overview_open_market",
        )

        st.markdown("#### Audit Health")
        run_trace = state.get("run_trace") or []
        filings_view = state.get("filings_browser_view") or {}
        coverage = filings_view.get("coverage_summary") or {}
        st.write(f"- Run steps recorded: {len(run_trace)}")
        st.write(f"- Filing coverage rows: {len(coverage.get('forms', [])) if coverage else 0}")
        audit_flags = tracker_view.get("audit_flags") or []
        if audit_flags:
            st.caption("Tracker flags: " + ", ".join(audit_flags[:3]))
        render_drilldown_button(
            "Open Audit →",
            target_tab="Audit",
            target_key="audit_view",
            target_value="Overview",
            session_state=state,
            key="overview_open_audit",
        )

    next_catalyst = (tracker_view.get("stance") or {}).get("next_catalyst")
    if next_catalyst:
        st.markdown("#### Next Catalyst")
        render_compact_list(
            next_catalyst.get("title") or "Next catalyst",
            [
                next_catalyst.get("description") or "",
                next_catalyst.get("expected_date") or next_catalyst.get("expected_window") or "",
            ],
            max_items=2,
        )
