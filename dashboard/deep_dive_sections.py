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
    build_thesis_diff_view,
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
    thesis_view = _get_cached_view("dossier_thesis_tracker_view", build_thesis_diff_view, memo.ticker)
    if not thesis_view.get("available"):
        st.info("No archived dossier thesis history is available yet.")
        return

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
