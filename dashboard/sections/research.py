from __future__ import annotations

from typing import Any

import streamlit as st

from dashboard.deep_dive_sections import (
    render_decision_log,
    render_publishable_memo,
    render_review_log,
    render_thesis_tracker,
)
from src.stage_04_pipeline.dossier_view import build_research_board_view

from ._shared import NOTEBOOK_TYPES, render_change_list, render_compact_list, set_note_context

_RESEARCH_VIEWS = ["Board", "Tracker", "Decisions", "Reviews", "Publishable Memo"]


def _render_board(memo, session_state: Any | None) -> None:
    state = session_state or st.session_state
    board = build_research_board_view(memo.ticker)
    tracker = board.get("tracker") or {}
    notebook = board.get("notebook") or {}

    st.markdown("### Working Research Board")
    st.write(memo.one_liner)

    tracker_left, tracker_right = st.columns([1.1, 0.9], gap="large")
    with tracker_left:
        st.markdown("#### Current Stance")
        stance = tracker.get("stance") or {}
        st.write(f"- Action: {stance.get('pm_action') or memo.action}")
        st.write(f"- Conviction: {(stance.get('pm_conviction') or memo.conviction).upper()}")
        st.write(f"- Thesis status: {stance.get('overall_status') or 'unknown'}")
        render_change_list("What changed", (tracker.get("what_changed") or {}).get("summary_lines") or [])
    with tracker_right:
        st.markdown("#### Diligence Queue")
        queue = tracker.get("next_queue") or {}
        render_compact_list("Open questions", queue.get("open_questions") or [], max_items=4)
        render_compact_list("Upcoming catalysts", [row.get("title") for row in queue.get("upcoming_catalysts") or []], max_items=4)

    st.divider()
    st.markdown("### Notebook Blocks")
    selected_note_type = st.selectbox(
        "Notebook type",
        options=NOTEBOOK_TYPES,
        format_func=lambda key: f"{key.title()} ({notebook.get('counts', {}).get(key, 0)})",
        key=f"research_board_type_{memo.ticker}",
    )
    set_note_context(state, page="Research", subpage="Board", item=f"Notebook · {selected_note_type.title()}")
    rows = (notebook.get("blocks_by_type") or {}).get(selected_note_type, [])
    if not rows:
        st.info("No notebook blocks in this type yet. Use the dossier companion to promote a scratch note.")
    for row in rows:
        context = row.get("source_context") or {}
        with st.expander(f"{row['title']} · {row['block_ts'][:16]}", expanded=False):
            st.caption(f"{context.get('page', 'Overview')} / {context.get('subpage', 'Overview')}")
            st.write(row["body"])
            if row.get("linked_sources"):
                st.caption("Sources: " + ", ".join(row["linked_sources"]))
            if row.get("linked_artifacts"):
                st.caption("Artifacts: " + ", ".join(row["linked_artifacts"]))


def render(memo, session_state: Any | None) -> None:
    if memo is None:
        st.info("Load a ticker to view the research board.")
        return

    state = session_state or st.session_state
    current_view = state.get("research_view", "Board")
    if current_view not in _RESEARCH_VIEWS:
        current_view = "Board"
        state["research_view"] = current_view

    selected_view = st.segmented_control(
        "Research view",
        options=_RESEARCH_VIEWS,
        key="research_view",
        label_visibility="collapsed",
    )
    set_note_context(state, page="Research", subpage=selected_view, item=selected_view)

    if selected_view == "Tracker":
        render_thesis_tracker(memo)
    elif selected_view == "Decisions":
        render_decision_log(memo)
    elif selected_view == "Reviews":
        render_review_log(memo)
    elif selected_view == "Publishable Memo":
        render_publishable_memo(memo)
    else:
        _render_board(memo, state)
