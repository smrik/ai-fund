from __future__ import annotations

from collections import defaultdict

import streamlit as st

from src.stage_02_valuation.input_assembler import clear_valuation_overrides_cache
from src.stage_04_pipeline.recommendations import (
    apply_approved_to_overrides,
    load_recommendations,
    preview_with_approvals,
    write_recommendations,
)

from ._shared import fix_text, format_unit_value, rec_unit


def render(memo, session_state=None) -> None:
    state = session_state or st.session_state
    st.subheader("Recommendations")
    recs = state.get("recommendations")

    if recs is None:
        try:
            recs = load_recommendations(memo.ticker)
            state.recommendations = recs
        except Exception:
            recs = None

    if recs is None or not recs.recommendations:
        st.info("No recommendations available. Run a full analysis first.")
        return

    if recs.current_iv_base:
        st.caption(f"Current base IV: **${recs.current_iv_base:,.2f}**  ·  Generated: {recs.generated_at}")

    by_agent: dict = defaultdict(list)
    for rec in recs.recommendations:
        by_agent[rec.agent].append(rec)

    agent_labels = {
        "qoe": "Quality of Earnings",
        "accounting_recast": "Accounting Recast",
        "industry": "Industry",
        "filings": "Filings Cross-Check",
    }

    for agent_key, agent_recs in by_agent.items():
        with st.expander(f"{agent_labels.get(agent_key, agent_key)} — {len(agent_recs)} item(s)", expanded=False):
            for rec in agent_recs:
                unit = rec_unit(rec.field)
                col_a, col_b, col_c, col_d = st.columns([3, 2, 2, 2])
                with col_a:
                    st.markdown(f"**{rec.field}**")
                    st.caption(fix_text(rec.rationale))
                    if rec.citation:
                        st.caption(f"_{rec.citation[:120]}_")
                with col_b:
                    cur_str = format_unit_value(rec.current_value, unit)
                    prop_str = format_unit_value(rec.proposed_value, unit) if isinstance(rec.proposed_value, float) else str(rec.proposed_value)
                    st.metric("Current → Proposed", prop_str, delta=f"from {cur_str}", delta_color="off")
                with col_c:
                    badge_map = {"high": "HIGH", "medium": "MEDIUM", "low": "LOW"}
                    st.markdown(f"Confidence: **{badge_map.get(rec.confidence, rec.confidence)}**")
                    st.markdown(f"Source: `{rec.agent}`")
                with col_d:
                    s_color = {"approved": "#22c55e", "rejected": "#ef4444", "pending": "#ca8a04"}
                    clr = s_color.get(rec.status, "#6b7a99")
                    st.markdown(f'Status: <span style="color:{clr};font-weight:600">{rec.status.upper()}</span>', unsafe_allow_html=True)
                st.divider()

    st.markdown("#### What-If Preview")
    all_pending_fields = [r.field for r in recs.recommendations if r.status == "pending"]
    selected_fields = st.multiselect(
        "Select fields to preview (simulates approval):",
        options=all_pending_fields,
        default=[],
        key=f"recs_preview_{memo.ticker}",
    )

    if selected_fields and st.button("Preview IV with selected approvals", key=f"preview_btn_{memo.ticker}"):
        with st.spinner("Running preview DCF..."):
            try:
                import copy as _copy

                preview_recs = _copy.deepcopy(recs)
                for rec in preview_recs.recommendations:
                    if rec.field in selected_fields:
                        rec.status = "approved"
                write_recommendations(preview_recs)
                preview = preview_with_approvals(memo.ticker, selected_fields)
                if preview:
                    prop = preview.get("proposed_iv", {})
                    dlt = preview.get("delta_pct", {})
                    p_col1, p_col2, p_col3 = st.columns(3)
                    for col, scenario in zip([p_col1, p_col2, p_col3], ["bear", "base", "bull"]):
                        col.metric(
                            f"{scenario.capitalize()} IV",
                            f"${prop.get(scenario):,.2f}" if prop.get(scenario) else "—",
                            delta=f"{dlt.get(scenario):+.1f}%" if dlt.get(scenario) is not None else None,
                        )
                    write_recommendations(recs)
                else:
                    st.warning("Preview unavailable.")
            except Exception as exc:
                st.error(f"Preview error: {exc}")

    st.markdown("#### Apply Approved Items")
    approved_count = sum(1 for rec in recs.recommendations if rec.status == "approved")
    st.caption(f"{approved_count} item(s) currently marked approved.")
    st.info(f"Edit `config/agent_recommendations_{memo.ticker.upper()}.yaml` — set `status: approved` — then click Apply.")
    if st.button("Apply Approved → valuation_overrides.yaml", type="primary", key=f"apply_btn_{memo.ticker}"):
        try:
            count = apply_approved_to_overrides(memo.ticker)
            clear_valuation_overrides_cache()
            if count:
                st.success(f"{count} override(s) written to config/valuation_overrides.yaml. Re-run valuation to see updated IV.")
            else:
                st.warning("No approved items found — nothing written.")
        except Exception as exc:
            st.error(f"Apply error: {exc}")
