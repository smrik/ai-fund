from __future__ import annotations

import streamlit as st

from src.stage_04_pipeline.override_workbench import (
    apply_override_selections,
    build_override_workbench,
    load_override_audit_history,
    preview_override_selections,
)

from ._shared import (
    format_unit_value,
    from_display_value,
    input_step,
    render_clean_table,
    to_display_value,
)


def render(memo, session_state=None) -> None:
    st.subheader("Assumption Lab")
    st.caption(
        "Compare current active values, deterministic defaults, and agent suggestions. Preview the valuation impact live, then apply selections into `config/valuation_overrides.yaml`."
    )
    st.caption("Units: percentages as whole %, debt/claims in USD millions, multiples in turns, NWC drivers in days.")

    try:
        workbench = build_override_workbench(memo.ticker)
    except Exception as exc:
        workbench = None
        st.error(f"Workbench load error: {exc}")

    if not workbench or not workbench.get("available"):
        st.info("Assumption lab unavailable. Run the analysis first.")
        return

    head_a, head_b, head_c = st.columns(3)
    head_a.metric("Current Base IV", f"${workbench.get('current_iv_base', 0):,.2f}" if workbench.get("current_iv_base") else "—")
    head_b.metric("Current Price", f"${(workbench.get('current_price') or 0):,.2f}")
    head_c.metric("Tracked Fields", str(len(workbench.get("fields") or [])))

    st.divider()
    selections: dict[str, str] = {}
    custom_values: dict[str, float] = {}

    for row in workbench["fields"]:
        field = row["field"]
        options = ["default"]
        if row.get("agent_value") is not None:
            options.append("agent")
        options.append("custom")
        initial_mode = row.get("initial_mode", "default")
        if initial_mode not in options:
            initial_mode = "default"

        col_label, col_mode = st.columns([4, 1])
        with col_label:
            st.markdown(f"**{row['label']}** `{field}`")
        with col_mode:
            mode = st.selectbox(
                "Mode",
                options=options,
                index=options.index(initial_mode),
                label_visibility="collapsed",
                key=f"assump_mode_{memo.ticker}_{field}",
            )
        selections[field] = mode

        val_col_a, val_col_b, val_col_c, val_col_d = st.columns(4)
        with val_col_a:
            st.caption(f"**Effective:** {format_unit_value(row.get('effective_value'), row['unit'])}")
            st.caption(f"Source: {row.get('effective_source') or '—'}")
        with val_col_b:
            st.caption(f"**Default:** {format_unit_value(row.get('baseline_value'), row['unit'])}")
            st.caption(f"Source: {row.get('baseline_source') or '—'}")
        with val_col_c:
            if row.get("agent_value") is not None:
                agent_lbl = "agent" if mode != "agent" else "**→ agent**"
                st.caption(f"{agent_lbl}: {format_unit_value(row.get('agent_value'), row['unit'])}")
                st.caption(f"{row.get('agent_name') or '?'} · {row.get('agent_confidence') or 'n/a'} · {row.get('agent_status') or 'pending'}")
            else:
                st.caption("Agent: —")
        with val_col_d:
            default_custom = row.get("effective_value") or row.get("baseline_value")
            custom_display = st.number_input(
                "Custom value",
                value=float(to_display_value(default_custom, row["unit"])),
                step=input_step(row["unit"]),
                label_visibility="collapsed",
                key=f"assump_custom_{memo.ticker}_{field}",
                disabled=(mode != "custom"),
            )
        custom_values[field] = from_display_value(custom_display, row["unit"])
        st.divider()

    try:
        preview = preview_override_selections(memo.ticker, selections=selections, custom_values=custom_values)
        st.session_state.workbench_preview = preview
    except Exception as exc:
        preview = None
        st.session_state.workbench_preview = None
        st.error(f"Live preview error: {exc}")

    if st.button("Apply selections → valuation_overrides.yaml", type="primary", key=f"assump_apply_{memo.ticker}"):
        try:
            apply_result = apply_override_selections(
                memo.ticker,
                selections=selections,
                custom_values=custom_values,
                actor="dashboard",
            )
            st.session_state.workbench_preview = apply_result.get("preview")
            st.success(
                f"Applied {apply_result.get('applied_count', 0)} field selection(s) to `config/valuation_overrides.yaml` and wrote audit rows to SQLite."
            )
        except Exception as exc:
            st.error(f"Apply error: {exc}")

    preview = st.session_state.get("workbench_preview")
    if preview:
        st.markdown("#### Preview Delta")
        prev_cols = st.columns(4)
        for col, key in zip(prev_cols, ["bear", "base", "bull", "expected"]):
            current_value = preview.get("current_iv", {}).get(key) if key != "expected" else preview.get("current_expected_iv")
            proposed_value = preview.get("proposed_iv", {}).get(key) if key != "expected" else preview.get("proposed_expected_iv")
            delta_pct = preview.get("delta_pct", {}).get(key) if key != "expected" else None
            if key == "expected" and current_value and proposed_value:
                delta_pct = round((proposed_value / current_value - 1.0) * 100.0, 1)
            col.metric(
                f"{key.capitalize()} IV",
                f"${proposed_value:,.2f}" if proposed_value is not None else "—",
                delta=f"{delta_pct:+.1f}%" if delta_pct is not None else None,
            )

        resolved_rows = [
            {
                "field": field,
                "mode": meta.get("mode"),
                "effective_before": meta.get("effective_value"),
                "applied_value": meta.get("value"),
            }
            for field, meta in (preview.get("resolved_values") or {}).items()
        ]
        if resolved_rows:
            render_clean_table(resolved_rows, column_order=None)

    st.markdown("#### Audit History")
    try:
        history = load_override_audit_history(memo.ticker, limit=50)
    except Exception as exc:
        history = []
        st.error(f"Audit history error: {exc}")

    if history:
        history_rows = [
            {
                "timestamp": row["event_ts"],
                "field": row["field"],
                "mode": row["selection_mode"],
                "baseline_source": row["baseline_source"],
                "applied_value": row["applied_value"],
                "action": row["write_action"],
                "base_iv_before": row["current_iv_base"],
                "base_iv_after": row["proposed_iv_base"],
            }
            for row in history
        ]
        render_clean_table(history_rows, column_order=None)
    else:
        st.info("No dashboard override audit events stored yet for this ticker.")
