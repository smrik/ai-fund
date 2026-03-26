from __future__ import annotations

from typing import Any

import streamlit as st

from src.stage_04_pipeline.news_materiality import build_news_materiality_view

from . import factor_exposure, macro, revisions
from ._shared import get_cached_view, render_clean_table, set_note_context

_MARKET_VIEWS = ["Summary", "News & Revisions", "Macro", "Sentiment", "Factor Exposure"]


def _render_summary(memo, session_state: Any | None) -> None:
    market_view = get_cached_view(session_state or st.session_state, "market_intel_view", build_news_materiality_view, memo.ticker)
    analyst = market_view.get("analyst_snapshot") or {}
    top = st.columns(4)
    top[0].metric("Recommendation", str(analyst.get("recommendation") or "—").upper())
    top[1].metric("Target Mean", f"${(analyst.get('target_mean') or 0):,.2f}" if analyst.get("target_mean") is not None else "—")
    top[2].metric("Analysts", str(analyst.get("num_analysts") or "—"))
    top[3].metric("Current Price", f"${(analyst.get('current_price') or 0):,.2f}" if analyst.get("current_price") is not None else "—")

    historical_brief = market_view.get("historical_brief") or {}
    st.markdown("#### Historical Brief")
    st.write(historical_brief.get("summary") or "No historical market brief is available yet.")
    if historical_brief.get("event_timeline"):
        render_clean_table(historical_brief.get("event_timeline") or [], column_order=None)

    quarterly_headlines = market_view.get("quarterly_headlines") or []
    st.markdown("#### Quarterly Materiality")
    if quarterly_headlines:
        render_clean_table(quarterly_headlines, {"materiality_score": "raw"}, column_order=None)
    else:
        st.info("No recent quarterly headlines returned for this ticker.")


def _render_sentiment(memo, session_state: Any | None) -> None:
    sentiment = memo.sentiment
    col1, col2 = st.columns(2)
    col1.metric("Direction", sentiment.direction.title())
    col2.metric("Score", f"{sentiment.score:+.2f} / 1.0")
    bull_col, bear_col = st.columns(2)
    with bull_col:
        st.markdown("#### Bullish Themes")
        for item in sentiment.key_bullish_themes:
            st.write(f"- {item}")
    with bear_col:
        st.markdown("#### Bearish Themes")
        for item in sentiment.key_bearish_themes:
            st.write(f"- {item}")
    if sentiment.risk_narratives:
        st.markdown("#### Risk Narratives")
        for item in sentiment.risk_narratives:
            st.write(f"- {item}")


def render(memo, session_state: Any | None) -> None:
    state = session_state or st.session_state
    current_view = state.get("market_view", "Summary")
    if current_view not in _MARKET_VIEWS:
        current_view = "Summary"
        state["market_view"] = current_view

    selected_view = st.segmented_control(
        "Market view",
        options=_MARKET_VIEWS,
        key="market_view",
        label_visibility="collapsed",
    )
    set_note_context(state, page="Market", subpage=selected_view, item=selected_view)

    if memo is None:
        if selected_view == "Macro":
            macro.render(None, session_state=state)
        else:
            st.info("Load a ticker to view this market surface. Macro remains available without a loaded memo.")
        return

    if selected_view == "News & Revisions":
        revisions.render(memo, session_state=state)
    elif selected_view == "Macro":
        macro.render(memo, session_state=state)
    elif selected_view == "Sentiment":
        _render_sentiment(memo, session_state=state)
    elif selected_view == "Factor Exposure":
        factor_exposure.render(memo, session_state=state)
    else:
        _render_summary(memo, session_state=state)
