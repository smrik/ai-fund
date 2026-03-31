from __future__ import annotations

from typing import Any

import streamlit as st

from . import assumption_lab, comps, dcf_audit, recommendations, wacc_lab
from ._shared import render_clean_table, set_note_context

_VALUATION_VIEWS = ["Summary", "DCF", "Comparables", "Multiples", "Assumptions", "WACC", "Recommendations"]


def _scenario_upside(value: float | None, current_price: float | None) -> str:
    if value is None or current_price in (None, 0):
        return "+0.0%"
    return f"{((value / current_price) - 1.0) * 100:+.1f}%"


def _render_summary(memo, session_state: Any | None) -> None:
    st.markdown("### Valuation Summary")
    top = st.columns(4)
    top[0].metric("Current Price", f"${memo.valuation.current_price or 0:,.2f}")
    top[1].metric("Base IV", f"${memo.valuation.base:,.2f}")
    top[2].metric("Upside (base)", f"{(memo.valuation.upside_pct_base or 0) * 100:+.1f}%")
    top[3].metric("Conviction", memo.conviction.upper())

    scenario_rows = [
        {"Scenario": "Bear", "Intrinsic Value": f"${memo.valuation.bear:.2f}", "Upside / (Downside)": _scenario_upside(memo.valuation.bear, memo.valuation.current_price)},
        {"Scenario": "Base", "Intrinsic Value": f"${memo.valuation.base:.2f}", "Upside / (Downside)": f"{(memo.valuation.upside_pct_base or 0) * 100:+.1f}%"},
        {"Scenario": "Bull", "Intrinsic Value": f"${memo.valuation.bull:.2f}", "Upside / (Downside)": _scenario_upside(memo.valuation.bull, memo.valuation.current_price)},
    ]
    render_clean_table(scenario_rows, column_order=["Scenario", "Intrinsic Value", "Upside / (Downside)"])
    st.caption("Use the visible valuation tabs for DCF, comparables, assumptions, WACC, and recommendation overlays.")


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
    elif selected_view == "Assumptions":
        assumption_lab.render(memo, session_state=state)
    elif selected_view == "WACC":
        wacc_lab.render(memo, session_state=state)
    elif selected_view == "Recommendations":
        recommendations.render(memo, session_state=state)
    else:
        _render_summary(memo, session_state=state)
