from __future__ import annotations

from typing import Any

import streamlit as st

from . import assumption_lab, comps, dcf_audit, recommendations, wacc_lab
from ._shared import render_clean_table, set_note_context

_VALUATION_VIEWS = ["Summary", "DCF", "Comparables", "Multiples"]


def _render_summary(memo, session_state: Any | None) -> None:
    st.markdown("### Valuation Summary")
    top = st.columns(4)
    top[0].metric("Current Price", f"${memo.valuation.current_price or 0:,.2f}")
    top[1].metric("Base IV", f"${memo.valuation.base:,.2f}")
    top[2].metric("Upside (base)", f"{(memo.valuation.upside_pct_base or 0) * 100:+.1f}%")
    top[3].metric("Conviction", memo.conviction.upper())

    scenario_rows = [
        {"Scenario": "Bear", "Intrinsic Value": f"${memo.valuation.bear:.2f}", "Upside / (Downside)": f"{(memo.valuation.upside_pct_bear or 0) * 100:+.1f}%"},
        {"Scenario": "Base", "Intrinsic Value": f"${memo.valuation.base:.2f}", "Upside / (Downside)": f"{(memo.valuation.upside_pct_base or 0) * 100:+.1f}%"},
        {"Scenario": "Bull", "Intrinsic Value": f"${memo.valuation.bull:.2f}", "Upside / (Downside)": f"{(memo.valuation.upside_pct_bull or 0) * 100:+.1f}%"},
    ]
    render_clean_table(scenario_rows, column_order=["Scenario", "Intrinsic Value", "Upside / (Downside)"])

    with st.expander("WACC", expanded=True):
        wacc_lab.render(memo, session_state=session_state)
    with st.expander("Assumption Lab", expanded=False):
        assumption_lab.render(memo, session_state=session_state)
    with st.expander("Recommendations", expanded=False):
        recommendations.render(memo, session_state=session_state)


def render(memo, session_state: Any | None) -> None:
    if memo is None:
        st.info("Load a ticker to view valuation.")
        return

    state = session_state or st.session_state
    current_view = state.get("valuation_view", "Summary")
    if current_view not in _VALUATION_VIEWS:
        current_view = "Summary"
        state["valuation_view"] = current_view

    selected_view = st.segmented_control(
        "Valuation view",
        options=_VALUATION_VIEWS,
        key="valuation_view",
        label_visibility="collapsed",
    )
    set_note_context(state, page="Valuation", subpage=selected_view, item=selected_view)

    if selected_view == "DCF":
        dcf_audit.render(memo, session_state=state)
    elif selected_view == "Comparables":
        comps.render_comparables(memo, session_state=state)
    elif selected_view == "Multiples":
        comps.render_multiples(memo, session_state=state)
    else:
        _render_summary(memo, session_state=state)
