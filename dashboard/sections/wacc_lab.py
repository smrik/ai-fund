from __future__ import annotations

import streamlit as st

from src.stage_04_pipeline.wacc_workbench import (
    apply_wacc_methodology_selection,
    build_wacc_workbench,
    load_wacc_methodology_audit_history,
    preview_wacc_methodology_selection,
)

from ._shared import render_clean_table


def render(memo, session_state=None) -> None:
    st.subheader("WACC")
    st.caption("Compare peer bottom-up, industry proxy, and self-Hamada methodologies, then preview or persist the selection.")

    try:
        workbench = build_wacc_workbench(memo.ticker, apply_overrides=True)
    except Exception as exc:
        workbench = {"available": False}
        st.error(f"WACC workbench error: {exc}")

    if not workbench.get("available"):
        st.info("WACC workbench unavailable for this ticker.")
        return

    methods = workbench.get("methods") or []
    method_rows = []
    for payload in methods:
        method_rows.append(
            {
                "method": payload["method"],
                "wacc": f"{payload['wacc'] * 100:.2f}%",
                "cost_of_equity": f"{payload['cost_of_equity'] * 100:.2f}%",
                "cost_of_debt_after_tax": f"{payload['cost_of_debt_after_tax'] * 100:.2f}%",
                "beta": payload.get("beta_value"),
                "beta_source": payload.get("beta_source"),
                "equity_weight": f"{(payload.get('assumptions', {}).get('equity_weight') or 0) * 100:.1f}%",
                "debt_weight": f"{(payload.get('assumptions', {}).get('debt_weight') or 0) * 100:.1f}%",
            }
        )
    render_clean_table(method_rows, column_order=None)

    active_selection = workbench.get("current_selection") or {"mode": "single_method", "selected_method": "peer_bottom_up", "weights": {}}
    mode = st.radio(
        "Methodology mode",
        options=["single_method", "blended"],
        horizontal=True,
        index=0 if active_selection.get("mode") == "single_method" else 1,
        key=f"wacc_mode_{memo.ticker}",
    )
    selected_method = None
    weights: dict[str, float] | None = None
    method_names = [payload["method"] for payload in methods]
    if mode == "single_method":
        selected_method = st.selectbox(
            "Method",
            options=method_names,
            index=method_names.index(active_selection.get("selected_method") or "peer_bottom_up"),
            key=f"wacc_method_{memo.ticker}",
        )
    else:
        weight_cols = st.columns(3)
        weights = {}
        for col, method in zip(weight_cols, method_names):
            default_weight = float((active_selection.get("weights") or {}).get(method, 0.0))
            weights[method] = col.number_input(
                f"{method} weight",
                min_value=0.0,
                max_value=1.0,
                step=0.05,
                value=default_weight,
                key=f"wacc_weight_{memo.ticker}_{method}",
            )
        st.caption(f"Entered weight sum: {sum(weights.values()):.2f}")

    if st.button("Preview WACC selection", key=f"wacc_preview_btn_{memo.ticker}"):
        try:
            st.session_state.wacc_preview = preview_wacc_methodology_selection(
                memo.ticker,
                mode=mode,
                selected_method=selected_method,
                weights=weights,
            )
        except Exception as exc:
            st.error(f"WACC preview error: {exc}")

    if st.button("Apply WACC selection", type="primary", key=f"wacc_apply_btn_{memo.ticker}"):
        try:
            result = apply_wacc_methodology_selection(
                memo.ticker,
                mode=mode,
                selected_method=selected_method,
                weights=weights,
                actor="dashboard",
            )
            st.success(
                f"Saved WACC methodology. Effective WACC {result['effective_wacc'] * 100:.2f}% | base IV ${result['proposed_iv'].get('base', 0):,.2f}"
            )
            st.session_state.wacc_preview = preview_wacc_methodology_selection(
                memo.ticker,
                mode=mode,
                selected_method=selected_method,
                weights=weights,
            )
        except Exception as exc:
            st.error(f"WACC apply error: {exc}")

    wacc_preview = st.session_state.get("wacc_preview")
    if wacc_preview:
        prev_cols = st.columns(4)
        prev_cols[0].metric("Current WACC", f"{wacc_preview['current_wacc'] * 100:.2f}%")
        prev_cols[1].metric("Proposed WACC", f"{wacc_preview['effective_wacc'] * 100:.2f}%")
        prev_cols[2].metric("Current Base IV", f"${wacc_preview['current_iv'].get('base', 0):,.2f}")
        prev_cols[3].metric("Proposed Base IV", f"${wacc_preview['proposed_iv'].get('base', 0):,.2f}")

    history = load_wacc_methodology_audit_history(memo.ticker, limit=25)
    if history:
        st.markdown("#### WACC Methodology Audit")
        render_clean_table(history, column_order=None)
