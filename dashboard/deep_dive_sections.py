from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Callable

import streamlit as st

from src.stage_02_valuation.templates.ic_memo import ICMemo
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
from src.stage_04_pipeline.dossier_view import (
    build_model_checkpoint_view,
    build_publishable_memo_context,
    build_thesis_tracker_view,
)
from src.stage_04_pipeline.dossier_workspace import (
    NOTE_TEMPLATES,
    ensure_dossier_source_note,
    ensure_dossier_workspace,
    normalize_linked_artifact_path,
    read_dossier_note,
    write_dossier_note,
)
from src.stage_04_pipeline.presentation_formatting import format_metric_value


def _get_cached_view(key: str, builder, *args, **kwargs):
    current = st.session_state.get(key)
    if current is None:
        try:
            current = builder(*args, **kwargs)
        except Exception as exc:
            return {"available": False, "error": str(exc)}
        st.session_state[key] = current
    return current


def _text_to_lines(value: str) -> list[str]:
    return [line.strip() for line in (value or "").splitlines() if line.strip()]


def _render_change_list(title: str, items: list[str]) -> None:
    st.markdown(f"**{title}**")
    if not items:
        st.caption("None.")
        return
    for item in items:
        st.write(f"- {item}")


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


def render_company_hub(memo: ICMemo) -> None:
    st.subheader("Company Hub")
    st.caption("Initialize and inspect the file-backed dossier workspace for this ticker.")

    profile = load_dossier_profile(memo.ticker)
    if st.button("Initialize Dossier Workspace", type="primary", key="init_dossier_workspace"):
        _sync_dossier_foundation(memo.ticker, memo.company_name)
        profile = load_dossier_profile(memo.ticker)
        st.success("Dossier workspace initialized and indexed.")

    if profile is None:
        st.info("No dossier exists yet for this ticker. Initialize the workspace to create the note skeleton and local index.")
        return

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


def render_business(memo: ICMemo) -> None:
    st.subheader("Business")
    profile = load_dossier_profile(memo.ticker)
    if profile is None:
        st.info("Initialize the dossier in Company Hub before editing business notes.")
        return

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


def render_sources(memo: ICMemo) -> None:
    st.subheader("Sources")
    profile = load_dossier_profile(memo.ticker)
    if profile is None:
        st.info("Initialize the dossier in Company Hub before registering sources and artifacts.")
        return

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


def render_model_and_valuation(memo: ICMemo) -> None:
    st.subheader("Model & Valuation")
    profile = load_dossier_profile(memo.ticker)
    if profile is None:
        st.info("Initialize the dossier in Company Hub before recording checkpoints.")
        return

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


def render_thesis_tracker(memo: ICMemo) -> None:
    st.subheader("Thesis Tracker")
    notice = st.session_state.pop("dossier_thesis_tracker_notice", None)
    if notice:
        st.success(notice)
    thesis_view = _get_cached_view("dossier_thesis_tracker_view", build_thesis_tracker_view, memo.ticker)
    if not thesis_view.get("available"):
        st.info("No archived dossier thesis history is available yet. Run the research pipeline for this ticker first, then reopen Thesis Tracker.")
        return
    stance = thesis_view["stance"]
    what_changed = thesis_view["what_changed"]
    next_queue = thesis_view["next_queue"]
    tracker_state = thesis_view.get("tracker_state") or {}

    if thesis_view.get("audit_flags"):
        fallback_labels = {
            "legacy_pillar_fallback": "Structured thesis pillars were not present in the latest archive snapshot, so the tracker is using a compatibility fallback.",
            "legacy_catalyst_fallback": "Structured catalysts were not present in the latest archive snapshot, so the tracker is using a compatibility fallback.",
        }
        for flag in thesis_view["audit_flags"]:
            if flag in fallback_labels:
                st.warning(fallback_labels[flag])

    col1, col2, col3 = st.columns(3)
    col1.metric("PM Action", stance.get("pm_action") or "—")
    col2.metric("PM Conviction", (stance.get("pm_conviction") or "—").upper())
    col3.metric("Thesis Status", stance.get("overall_status") or "unknown")

    col4, col5, col6 = st.columns(3)
    col4.metric("Base IV", format_metric_value(stance.get("base_iv"), kind="price"))
    col5.metric("Current Price", format_metric_value(stance.get("current_price"), kind="price"))
    col6.metric("Upside", format_metric_value(stance.get("upside_pct"), kind="percent"))

    next_catalyst = stance.get("next_catalyst")
    st.caption(
        " | ".join(
            [
                f"Next catalyst: {next_catalyst['title']}" if next_catalyst else "Next catalyst: —",
                f"Latest archive stance: {stance.get('latest_archived_action') or '—'} / {(stance.get('latest_archived_conviction') or '—').upper()}",
                f"Last review: {stance.get('last_reviewed_at') or '—'}",
            ]
        )
    )

    left, right = st.columns(2)
    with left:
        st.markdown("#### What Changed Since Last Snapshot")
        action_delta = what_changed.get("action_delta", {})
        conviction_delta = what_changed.get("conviction_delta", {})
        st.write(f"Action: {action_delta.get('from') or '—'} -> {action_delta.get('to') or '—'}")
        st.write(f"Conviction: {conviction_delta.get('from') or '—'} -> {conviction_delta.get('to') or '—'}")
        st.write(
            "Base IV delta: "
            + (
                format_metric_value(what_changed.get("base_iv_delta"), kind="price")
                if what_changed.get("base_iv_delta") is not None
                else "—"
            )
        )
        _render_change_list("Catalysts added", what_changed.get("catalysts_added", []))
        _render_change_list("Catalysts removed", what_changed.get("catalysts_removed", []))
        _render_change_list("Risks added", what_changed.get("risks_added", []))
        _render_change_list("Risks removed", what_changed.get("risks_removed", []))
        _render_change_list("Open questions added", what_changed.get("open_questions_added", []))
        _render_change_list("Open questions closed", what_changed.get("open_questions_closed", []))
    with right:
        st.markdown("#### Next Diligence Queue")
        _render_change_list("Open questions", next_queue.get("open_questions", []))
        upcoming = next_queue.get("upcoming_catalysts", [])
        st.markdown("**Upcoming catalysts**")
        if not upcoming:
            st.caption("None.")
        else:
            for row in upcoming:
                date_hint = row.get("expected_date") or row.get("expected_window") or "undated"
                st.write(f"- {row['title']} ({row['status']}, {date_hint})")
        review_status = next_queue.get("review_status") or "none"
        st.write(f"Review queue: {review_status}")
        missing_flags = next_queue.get("missing_evidence_flags", [])
        if missing_flags:
            _render_change_list("Missing evidence flags", missing_flags)

    with st.form("tracker_overview_form", clear_on_submit=False):
        overall_status_options = ["intact", "monitor", "validated", "broken", "unknown"]
        overall_status = st.selectbox(
            "Overall Status",
            overall_status_options,
            index=max(overall_status_options.index(stance.get("overall_status")), 0) if stance.get("overall_status") in overall_status_options else 1,
        )
        pm_action_options = ["BUY", "SELL SHORT", "WATCH", "PASS", "TRIM", "EXIT"]
        pm_action = st.selectbox(
            "PM Action",
            pm_action_options,
            index=pm_action_options.index(stance.get("pm_action")) if stance.get("pm_action") in pm_action_options else 2,
        )
        pm_conviction_options = ["high", "medium", "low"]
        pm_conviction = st.selectbox(
            "PM Conviction",
            pm_conviction_options,
            index=pm_conviction_options.index(stance.get("pm_conviction")) if stance.get("pm_conviction") in pm_conviction_options else 1,
        )
        summary_note = st.text_area("Summary Note", value=stance.get("summary_note") or "", height=90)
        open_questions_text = st.text_area(
            "Open Questions",
            value="\n".join(next_queue.get("open_questions", [])),
            height=120,
            help="One question per line.",
        )
        save_tracker_state = st.form_submit_button("Save Overview")

    if save_tracker_state:
        upsert_tracker_state(
            {
                "ticker": memo.ticker,
                "overall_status": overall_status,
                "pm_action": pm_action,
                "pm_conviction": pm_conviction,
                "summary_note": summary_note.strip(),
                "pillar_states_json": tracker_state.get("pillar_states_json") or json.dumps({}, sort_keys=True),
                "open_questions_json": json.dumps(_text_to_lines(open_questions_text), sort_keys=True),
                "last_reviewed_at": memo.date,
                "latest_snapshot_id": thesis_view["latest_snapshot"].get("id"),
                "metadata_json": tracker_state.get("metadata_json") or json.dumps({}, sort_keys=True),
            }
        )
        st.session_state.pop("dossier_thesis_tracker_view", None)
        st.session_state["dossier_thesis_tracker_notice"] = "Overview saved."
        st.rerun()

    pillars_tab, catalysts_tab, continuity_tab = st.tabs(["Pillars", "Catalysts", "Continuity"])

    with pillars_tab:
        pillar_board = thesis_view.get("pillar_board", [])
        if not pillar_board:
            st.info("No thesis pillars are available for this ticker yet.")
        else:
            with st.form("tracker_pillars_form", clear_on_submit=False):
                updated_pillars: dict[str, dict[str, str]] = {}
                for row in pillar_board:
                    with st.expander(row["title"], expanded=True):
                        st.write(row.get("description") or "No description recorded.")
                        if row.get("falsifier"):
                            st.caption(f"Falsifier: {row['falsifier']}")
                        if row.get("latest_evidence_cue"):
                            st.caption(f"Evidence cue: {row['latest_evidence_cue']}")
                        status_options = ["intact", "monitor", "validated", "broken", "unknown"]
                        status_key = f"pillar_status_{row['pillar_id']}"
                        note_key = f"pillar_note_{row['pillar_id']}"
                        updated_pillars[row["pillar_id"]] = {
                            "status": st.selectbox(
                                "Status",
                                status_options,
                                index=status_options.index(row.get("pm_status")) if row.get("pm_status") in status_options else 4,
                                key=status_key,
                            ),
                            "title_slug": row["title"].strip().lower().replace(" ", "-"),
                            "note": st.text_area("PM Note", value=row.get("pm_note") or "", height=80, key=note_key),
                        }
                save_pillars = st.form_submit_button("Save Pillar Board")

            if save_pillars:
                upsert_tracker_state(
                    {
                        "ticker": memo.ticker,
                        "overall_status": stance.get("overall_status") or "unknown",
                        "pm_action": stance.get("pm_action"),
                        "pm_conviction": stance.get("pm_conviction"),
                        "summary_note": stance.get("summary_note") or "",
                        "pillar_states_json": json.dumps(updated_pillars, sort_keys=True),
                        "open_questions_json": tracker_state.get("open_questions_json") or json.dumps(next_queue.get("open_questions", []), sort_keys=True),
                        "last_reviewed_at": memo.date,
                        "latest_snapshot_id": thesis_view["latest_snapshot"].get("id"),
                        "metadata_json": tracker_state.get("metadata_json") or json.dumps({}, sort_keys=True),
                    }
                )
                st.session_state.pop("dossier_thesis_tracker_view", None)
                st.session_state["dossier_thesis_tracker_notice"] = "Pillar board saved."
                st.rerun()

    with catalysts_tab:
        catalyst_board = thesis_view.get("catalyst_board", {})
        all_catalysts = catalyst_board.get("urgent_open", []) + catalyst_board.get("watching", []) + catalyst_board.get("resolved", [])
        if not all_catalysts:
            st.info("No catalysts are available for this ticker yet.")
        else:
            with st.form("tracker_catalyst_board_form", clear_on_submit=False):
                updated_catalysts = []
                for row in all_catalysts:
                    with st.expander(f"{row['title']} [{row['status']}]", expanded=row["status"] != "resolved"):
                        st.write(row.get("description") or "No description recorded.")
                        st.caption(f"Priority: {row.get('priority') or 'medium'} | Source: {row.get('source_origin') or 'archive'}")
                        status_options = ["open", "watching", "hit", "delayed", "missed", "killed", "resolved"]
                        updated_catalysts.append(
                            {
                                **row,
                                "status": st.selectbox(
                                    "Status",
                                    status_options,
                                    index=status_options.index(row.get("status")) if row.get("status") in status_options else 0,
                                    key=f"catalyst_status_{row['catalyst_key']}",
                                ),
                                "expected_date": st.text_input(
                                    "Expected Date",
                                    value=row.get("expected_date") or "",
                                    key=f"catalyst_date_{row['catalyst_key']}",
                                ).strip()
                                or None,
                                "expected_window_start": st.text_input(
                                    "Expected Window Start",
                                    value=row.get("expected_window_start") or "",
                                    key=f"catalyst_window_start_{row['catalyst_key']}",
                                ).strip()
                                or None,
                                "expected_window_end": st.text_input(
                                    "Expected Window End",
                                    value=row.get("expected_window_end") or "",
                                    key=f"catalyst_window_end_{row['catalyst_key']}",
                                ).strip()
                                or None,
                                "status_reason": st.text_area(
                                    "Status Reason",
                                    value=row.get("status_reason") or "",
                                    height=80,
                                    key=f"catalyst_reason_{row['catalyst_key']}",
                                ).strip(),
                            }
                        )
                save_catalysts = st.form_submit_button("Save Catalyst Board")

            if save_catalysts:
                for row in updated_catalysts:
                    upsert_tracked_catalyst(
                        {
                            "ticker": memo.ticker,
                            "catalyst_key": row["catalyst_key"],
                            "title": row["title"],
                            "description": row.get("description"),
                            "priority": row.get("priority", "medium"),
                            "status": row["status"],
                            "expected_date": row.get("expected_date"),
                            "expected_window_start": row.get("expected_window_start"),
                            "expected_window_end": row.get("expected_window_end"),
                            "status_reason": row.get("status_reason", ""),
                            "source_origin": row.get("source_origin", "pm"),
                            "source_snapshot_id": row.get("source_snapshot_id"),
                            "evidence_json": json.dumps(row.get("evidence_json") or {}, sort_keys=True),
                        }
                    )
                st.session_state.pop("dossier_thesis_tracker_view", None)
                st.session_state["dossier_thesis_tracker_notice"] = "Catalyst board saved."
                st.rerun()

    with continuity_tab:
        continuity = thesis_view.get("continuity", {})
        latest_decision = continuity.get("latest_decision")
        latest_review = continuity.get("latest_review")
        latest_checkpoint = continuity.get("latest_checkpoint")
        snapshot_refs = continuity.get("snapshot_refs", {})

        st.markdown("#### Latest Decision")
        if latest_decision:
            st.write(f"{latest_decision['decision_title']} | {latest_decision['action']} | {latest_decision.get('conviction') or '—'}")
            st.caption(f"Review due: {latest_decision.get('review_due_date') or '—'}")
        else:
            st.caption("No decision log entry recorded yet.")

        st.markdown("#### Latest Review")
        if latest_review:
            st.write(f"{latest_review['review_title']} | {latest_review['period_type']} | {latest_review['thesis_status']}")
            st.caption(f"Model status: {latest_review.get('model_status') or '—'}")
        else:
            st.caption("No review log entry recorded yet.")

        st.markdown("#### Latest Checkpoint")
        if latest_checkpoint:
            checkpoint_base = (latest_checkpoint.get("valuation") or {}).get("base_iv")
            st.write(f"{latest_checkpoint['model_version']} | Base IV: {format_metric_value(checkpoint_base, kind='price')}")
            st.caption(latest_checkpoint.get("change_reason") or "No checkpoint note.")
        else:
            st.caption("No model checkpoint recorded yet.")

        st.markdown("#### Archive Snapshot References")
        st.write(f"Latest snapshot: {snapshot_refs.get('latest_snapshot_id') or '—'} @ {snapshot_refs.get('latest_snapshot_created_at') or '—'}")
        st.write(f"Prior snapshot: {snapshot_refs.get('prior_snapshot_id') or '—'} @ {snapshot_refs.get('prior_snapshot_created_at') or '—'}")
        st.caption("Use Decision Log and Review Log for full journal entry editing.")


def render_decision_log(memo: ICMemo) -> None:
    st.subheader("Decision Log")
    profile = load_dossier_profile(memo.ticker)
    if profile is None:
        st.info("Initialize the dossier in Company Hub before writing decisions.")
        return

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


def render_review_log(memo: ICMemo) -> None:
    st.subheader("Review Log")
    profile = load_dossier_profile(memo.ticker)
    if profile is None:
        st.info("Initialize the dossier in Company Hub before writing reviews.")
        return

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


def render_publishable_memo(memo: ICMemo) -> None:
    st.subheader("Publishable Memo")
    profile = load_dossier_profile(memo.ticker)
    if profile is None:
        st.info("Initialize the dossier in Company Hub before editing the publishable memo.")
        return

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


DEEP_DIVE_RENDERERS: dict[str, Callable[[ICMemo], None]] = {
    "Company Hub": render_company_hub,
    "Business": render_business,
    "Model & Valuation": render_model_and_valuation,
    "Sources": render_sources,
    "Thesis Tracker": render_thesis_tracker,
    "Decision Log": render_decision_log,
    "Review Log": render_review_log,
    "Publishable Memo": render_publishable_memo,
}


def render_deep_dive_section(selected_section: str, memo: ICMemo) -> bool:
    renderer = DEEP_DIVE_RENDERERS.get(selected_section)
    if renderer is None:
        return False
    renderer(memo)
    return True
