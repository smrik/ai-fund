from __future__ import annotations

import json
from datetime import datetime, timezone

import streamlit as st

from src.stage_02_valuation.templates.ic_memo import ICMemo
from src.stage_04_pipeline.dossier_index import (
    insert_dossier_note_block,
    list_dossier_artifacts,
    list_dossier_sources,
)
from src.stage_04_pipeline.dossier_view import build_dossier_notebook_view
from src.stage_04_pipeline.dossier_workspace import (
    append_research_notebook_block,
    ensure_dossier_workspace,
)


NOTEBOOK_TYPES = [
    ("thesis", "Thesis"),
    ("risk", "Risks"),
    ("catalyst", "Catalysts"),
    ("question", "Questions"),
    ("decision", "Decisions"),
    ("review", "Reviews"),
    ("evidence", "Evidence"),
    ("general", "General"),
]


def _safe_key(value: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "_" for ch in value)


def _current_note_block_ts() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _build_note_block_row(
    *,
    memo: ICMemo,
    block_type: str,
    title: str,
    body: str,
    page_context: dict[str, str],
    linked_sources: list[str],
    linked_artifacts: list[str],
    pin_to_report: bool,
    linked_snapshot_id: int | None = None,
) -> dict:
    source_context = {
        "page": page_context.get("page", "Overview"),
        "subpage": page_context.get("subpage", "Overview"),
        "item": page_context.get("item") or page_context.get("subpage", "Overview"),
    }
    return {
        "ticker": memo.ticker,
        "block_ts": _current_note_block_ts(),
        "block_type": block_type,
        "title": title,
        "body": body,
        "source_context_json": json.dumps(source_context, sort_keys=True),
        "linked_snapshot_id": linked_snapshot_id if linked_snapshot_id is not None else st.session_state.get("report_snapshot_id"),
        "linked_sources_json": json.dumps(linked_sources, sort_keys=True),
        "linked_artifacts_json": json.dumps(linked_artifacts, sort_keys=True),
        "status": "active",
        "pinned_to_report": 1 if pin_to_report else 0,
        "created_by": "pm",
    }


def _build_block_markdown(*, block_type: str, title: str, body: str, context: dict, source_ids: list[str], artifact_keys: list[str]) -> str:
    lines = [
        f"### [{block_type.title()}] {title}",
        "",
        f"- created_from: {context.get('page', 'Unknown')} / {context.get('subpage', 'Overview')}",
    ]
    context_item = context.get("item")
    if context_item:
        lines.append(f"- linked_item: {context_item}")
    if source_ids:
        lines.append(f"- source_ids: {', '.join(source_ids)}")
    if artifact_keys:
        lines.append(f"- artifact_keys: {', '.join(artifact_keys)}")
    lines.extend(["", body.strip()])
    return "\n".join(lines).strip()


def render_dossier_companion(memo: ICMemo, *, page_context: dict[str, str]) -> None:
    ensure_dossier_workspace(memo.ticker, memo.company_name)
    scratch_key = f"dossier_scratch_{memo.ticker}_{_safe_key(page_context.get('page', 'overview'))}_{_safe_key(page_context.get('subpage', 'overview'))}"
    scratch_clear_key = f"{scratch_key}_clear"
    if st.session_state.pop(scratch_clear_key, False):
        st.session_state[scratch_key] = ""
    scratch_view = st.segmented_control(
        "Dossier",
        options=["Scratchpad", "Notebook", "Pinned"],
        default="Scratchpad",
        key=f"dossier_companion_mode_{memo.ticker}",
        label_visibility="collapsed",
    )
    st.caption(f"{page_context.get('page', 'Overview')} / {page_context.get('subpage', 'Overview')}")
    if page_context.get("item"):
        st.caption("Linked item: " + str(page_context["item"]))

    if scratch_view == "Scratchpad":
        scratch_text = st.text_area(
            "Scratchpad",
            value=st.session_state.get(scratch_key, ""),
            height=220,
            key=scratch_key,
            placeholder="Capture the thought first. Promote it only if it belongs in the durable research record.",
        )

        source_options = [row["source_id"] for row in list_dossier_sources(memo.ticker)]
        artifact_options = [row["artifact_key"] for row in list_dossier_artifacts(memo.ticker)]
        with st.expander("Promote to note block", expanded=False):
            block_type = st.selectbox(
                "Block type",
                options=[key for key, _ in NOTEBOOK_TYPES],
                format_func=lambda key: dict(NOTEBOOK_TYPES).get(key, key.title()),
                key=f"dossier_block_type_{memo.ticker}",
            )
            block_title = st.text_input(
                "Block title",
                value=(scratch_text.strip().splitlines()[0][:80] if scratch_text.strip() else ""),
                key=f"dossier_block_title_{memo.ticker}",
            )
            linked_sources = st.multiselect(
                "Source IDs",
                options=source_options,
                default=[],
                key=f"dossier_block_sources_{memo.ticker}",
            )
            linked_artifacts = st.multiselect(
                "Artifact Keys",
                options=artifact_options,
                default=[],
                key=f"dossier_block_artifacts_{memo.ticker}",
            )
            pin_to_report = st.checkbox("Pin to research board", value=False, key=f"dossier_block_pin_{memo.ticker}")
            if st.button("Promote", key=f"dossier_promote_{memo.ticker}", type="primary", width="stretch"):
                body = scratch_text.strip()
                if not body:
                    st.warning("Scratchpad is empty.")
                else:
                    title = block_title.strip() or body.splitlines()[0][:80]
                    note_block_row = _build_note_block_row(
                        memo=memo,
                        block_type=block_type,
                        title=title,
                        body=body,
                        page_context=page_context,
                        linked_sources=linked_sources,
                        linked_artifacts=linked_artifacts,
                        pin_to_report=pin_to_report,
                        linked_snapshot_id=st.session_state.get("report_snapshot_id"),
                    )
                    insert_dossier_note_block(note_block_row)
                    append_research_notebook_block(
                        memo.ticker,
                        _build_block_markdown(
                            block_type=block_type,
                            title=title,
                            body=body,
                            context=json.loads(note_block_row["source_context_json"]),
                            source_ids=linked_sources,
                            artifact_keys=linked_artifacts,
                        ),
                    )
                    st.session_state[scratch_clear_key] = True
                    st.success("Promoted to notebook block.")
                    st.rerun()

    notebook = build_dossier_notebook_view(memo.ticker)
    if scratch_view == "Notebook":
        selected_type = st.selectbox(
            "Notebook type",
            options=[key for key, _ in NOTEBOOK_TYPES],
            format_func=lambda key: f"{dict(NOTEBOOK_TYPES).get(key, key.title())} ({notebook['counts'].get(key, 0)})",
            key=f"dossier_notebook_filter_{memo.ticker}",
        )
        rows = notebook["blocks_by_type"].get(selected_type, [])
        if not rows:
            st.caption("No durable blocks in this type yet.")
        for row in rows:
            with st.expander(f"{row['title']} · {row['block_ts'][:16]}", expanded=False):
                context = row.get("source_context") or {}
                st.caption(f"{context.get('page', 'Overview')} / {context.get('subpage', 'Overview')}")
                st.write(row["body"])
                linked_sources = row.get("linked_sources") or []
                linked_artifacts = row.get("linked_artifacts") or []
                if linked_sources:
                    st.caption("Sources: " + ", ".join(linked_sources))
                if linked_artifacts:
                    st.caption("Artifacts: " + ", ".join(linked_artifacts))
                if int(row.get("pinned_to_report") or 0):
                    st.caption("Pinned to research board.")

    if scratch_view == "Pinned":
        pinned_rows = [
            row
            for rows in notebook["blocks_by_type"].values()
            for row in rows
            if int(row.get("pinned_to_report") or 0)
        ]
        if not pinned_rows:
            st.caption("No pinned blocks yet.")
        for row in pinned_rows:
            with st.expander(f"{row['title']} · {row['block_type'].title()}", expanded=False):
                st.write(row["body"])
