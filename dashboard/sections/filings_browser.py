from __future__ import annotations

import json

import streamlit as st

from src.stage_04_pipeline.filings_browser import build_filings_browser_view

from ._shared import get_cached_view, render_clean_table, set_note_context


def render(memo, session_state=None) -> None:
    state = session_state or st.session_state
    st.subheader("Filings & Evidence")
    st.caption("Read-only browser for cached SEC filings and the exact chunks the agents used.")
    filings_view = get_cached_view(state, "filings_browser_view", build_filings_browser_view, memo.ticker)
    if not filings_view.get("available"):
        st.info("No filing cache available for this ticker.")
        return

    filings = filings_view.get("filings") or []
    labels = [f"{row['form_type']} | {row.get('filing_date') or 'unknown-date'} | {row['accession_no']}" for row in filings]
    selected_label = st.selectbox("Filing", labels, key=f"filing_browser_sel_{memo.ticker}")
    filing_row = filings[labels.index(selected_label)]
    filing_key = filing_row.get("filing_key") or filing_row["accession_no"]
    accession_no = filing_row["accession_no"]

    meta_cols = st.columns(5)
    meta_cols[0].metric("Form", filing_row["form_type"])
    meta_cols[1].metric("Filing Date", filing_row.get("filing_date") or "—")
    meta_cols[2].metric("Accession", accession_no)
    meta_cols[3].metric("Raw Cache", "yes" if filing_row.get("raw_available") else "no")
    meta_cols[4].metric("Clean Cache", "yes" if filing_row.get("clean_available") else "no")
    if filing_row.get("source_url"):
        st.link_button("Open on SEC", filing_row["source_url"])

    statement_presence = (filings_view.get("statement_presence_by_filing") or {}).get(filing_key, {})
    coverage_summary = filings_view.get("coverage_summary") or {}
    coverage_counts = coverage_summary.get("by_section_key") or {}
    coverage_cols = st.columns(5)
    coverage_cols[0].metric("Financial Statements", "yes" if statement_presence.get("financial_statements") else "no")
    coverage_cols[1].metric("Notes", "yes" if statement_presence.get("notes_to_financials") else "no")
    coverage_cols[2].metric("MD&A", "yes" if statement_presence.get("mda") else "no")
    coverage_cols[3].metric("Risk Factors", "yes" if statement_presence.get("risk_factors") else "no")
    coverage_cols[4].metric("Quarterly Notes", "yes" if statement_presence.get("quarterly_notes") else "no")

    filing_search = st.text_input("Filter filing content", key=f"filing_filter_{memo.ticker}_{accession_no}")
    used_chunks = []
    for agent_name, chunks in (filings_view.get("agent_usage") or {}).items():
        for chunk in chunks:
            if chunk.get("accession_no") == accession_no:
                used_chunks.append({"agent": agent_name, **chunk})
    if filing_search:
        used_chunks = [row for row in used_chunks if filing_search.lower() in json.dumps(row).lower()]

    filing_view_mode = st.selectbox(
        "Filing View",
        ["Diagnostics", "Agent-Used Chunks", "Sections", "Chunks", "Clean Text", "Raw HTML"],
        key=f"filing_view_mode_{memo.ticker}_{accession_no}",
    )
    set_note_context(
        state,
        page="Audit",
        subpage="Filings & Evidence",
        item=f"{selected_label} · {filing_view_mode}",
    )
    if filing_view_mode == "Diagnostics":
        coverage_rows = [{"section_key": key, "count": value} for key, value in coverage_counts.items()]
        if coverage_rows:
            render_clean_table(coverage_rows, {"count": "count"}, column_order=["section_key", "count"])
        else:
            st.info("No extracted section coverage is available for this filing.")

        retrieval_rows = []
        for profile_name, payload in (filings_view.get("retrieval_profiles") or {}).items():
            retrieval_rows.append(
                {
                    "profile": profile_name,
                    "fallback_mode": payload.get("fallback_mode"),
                    "selected_chunk_count": payload.get("selected_chunk_count"),
                    "candidate_chunk_count": payload.get("candidate_chunk_count"),
                    "corpus_chunk_count": payload.get("corpus_chunk_count"),
                    "eligible_section_keys": ", ".join(payload.get("eligible_section_keys") or []),
                    "excluded_section_keys": ", ".join(payload.get("excluded_section_keys") or []),
                    "skipped_sections": ", ".join(payload.get("skipped_sections") or []),
                }
            )
        if retrieval_rows:
            render_clean_table(
                retrieval_rows,
                {
                    "selected_chunk_count": "count",
                    "candidate_chunk_count": "count",
                    "corpus_chunk_count": "count",
                },
                column_order=None,
            )
        else:
            st.info("No retrieval diagnostics are available.")
    elif filing_view_mode == "Agent-Used Chunks":
        if used_chunks:
            render_clean_table(used_chunks, column_order=None)
        else:
            st.info("No selected chunks for this filing in the cached agent contexts.")
    elif filing_view_mode == "Sections":
        section_rows = filings_view.get("sections_by_filing", {}).get(filing_key) or filings_view.get("sections_by_filing", {}).get(accession_no, [])
        if filing_search:
            section_rows = [row for row in section_rows if filing_search.lower() in json.dumps(row).lower()]
        render_clean_table(section_rows, column_order=None)
    elif filing_view_mode == "Chunks":
        chunk_rows = filings_view.get("chunks_by_filing", {}).get(filing_key) or filings_view.get("chunks_by_filing", {}).get(accession_no, [])
        if filing_search:
            chunk_rows = [row for row in chunk_rows if filing_search.lower() in json.dumps(row).lower()]
        render_clean_table(chunk_rows, column_order=None)
    elif filing_view_mode == "Clean Text":
        clean_text = filing_row.get("clean_text") or ""
        if filing_search:
            clean_text = "\n".join(line for line in clean_text.splitlines() if filing_search.lower() in line.lower())
        st.text_area("Clean text", clean_text, height=420, key=f"clean_text_{filing_key}")
    else:
        raw_html = filing_row.get("raw_html") or ""
        if filing_search:
            raw_html = "\n".join(line for line in raw_html.splitlines() if filing_search.lower() in line.lower())
        st.code(raw_html or "No raw HTML cached for this filing.", language="html")
