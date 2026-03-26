from __future__ import annotations

import streamlit as st

from src.stage_04_pipeline.dcf_audit import build_dcf_audit_view

from ._shared import fmt_sens_table, get_cached_view, render_clean_table


def _render_dcf_charts(audit: dict) -> None:
    chart_series = audit.get("chart_series") or {}
    try:
        import plotly.graph_objects as go
    except ImportError:
        st.info("Install Plotly to view the DCF charts.")
        return

    scenario_iv = chart_series.get("scenario_iv") or []
    if scenario_iv:
        fig = go.Figure()
        fig.add_trace(
            go.Bar(
                x=[row["scenario"].title() for row in scenario_iv],
                y=[row["intrinsic_value"] for row in scenario_iv],
                marker_color=["#f85149", "#388bfd", "#3fb950", "#d29922"][: len(scenario_iv)],
                text=[f"${row['intrinsic_value']:,.2f}" for row in scenario_iv],
                textposition="outside",
            )
        )
        current_price = audit.get("current_price")
        if current_price is not None:
            fig.add_hline(
                y=current_price,
                line_dash="dash",
                line_color="#d29922",
                annotation_text=f"  Price ${current_price:,.2f}",
            )
        fig.update_layout(height=360, margin=dict(l=20, r=20, t=20, b=20), showlegend=False)
        st.plotly_chart(fig, width="stretch")

    fcff = chart_series.get("fcff_curve") or []
    if fcff:
        fig = go.Figure()
        fig.add_trace(go.Bar(x=[row["year"] for row in fcff], y=[row["fcff_mm"] for row in fcff], name="FCFF ($mm)"))
        fig.add_trace(
            go.Scatter(
                x=[row["year"] for row in fcff],
                y=[row["nopat_mm"] for row in fcff],
                name="NOPAT ($mm)",
                mode="lines+markers",
            )
        )
        fig.update_layout(height=320, margin=dict(l=20, r=20, t=20, b=20))
        st.plotly_chart(fig, width="stretch")

    overlays = chart_series.get("risk_overlay") or []
    risk_view = audit.get("risk_impact") or {}
    if overlays and risk_view.get("available"):
        fig = go.Figure()
        fig.add_trace(
            go.Bar(
                x=[row["risk_name"] for row in overlays],
                y=[row["stressed_iv"] for row in overlays],
                text=[f"p={row['probability']:.0%}" for row in overlays],
                textposition="outside",
                marker_color="#f85149",
            )
        )
        fig.add_hline(y=risk_view.get("base_iv", 0), line_dash="dash", line_color="#388bfd", annotation_text="  Base IV")
        fig.add_hline(y=risk_view.get("risk_adjusted_expected_iv", 0), line_dash="dot", line_color="#d29922", annotation_text="  Risk-Adj. EV")
        fig.update_layout(height=320, margin=dict(l=20, r=20, t=20, b=20))
        st.plotly_chart(fig, width="stretch")
        render_clean_table(risk_view.get("overlay_results") or [], column_order=None)


def render(memo, session_state=None) -> None:
    st.subheader("DCF Audit")
    st.caption("Browser-native review of the deterministic model — sourced directly from the Python DCF engine.")

    try:
        audit = get_cached_view(session_state or st.session_state, "dcf_audit_view", build_dcf_audit_view, memo.ticker, risk_output=memo.risk_impact)
    except Exception as exc:
        audit = {"available": False}
        st.error(f"DCF audit load error: {exc}")

    if not audit or not audit.get("available"):
        st.info("DCF audit unavailable. Re-run after valuation inputs are available.")
        return

    st.markdown("#### Scenario Summary")
    render_clean_table(audit["scenario_summary"], column_order=None)

    left, right = st.columns(2)
    with left:
        st.markdown("#### Key Drivers")
        render_clean_table(audit.get("driver_rows") or [], column_order=None)
    with right:
        st.markdown("#### Health Flags")
        flag_rows = [{"flag": key, "active": bool(value)} for key, value in (audit.get("health_flags") or {}).items()]
        render_clean_table(flag_rows, column_order=["flag", "active"])

    st.markdown("#### Forecast Bridge (Base Scenario)")
    render_clean_table(audit["forecast_bridge"], column_order=None)

    col_term, col_ev = st.columns(2)
    with col_term:
        st.markdown("#### Terminal Bridge")
        render_clean_table([audit["terminal_bridge"]], column_order=None)
    with col_ev:
        st.markdown("#### EV → Equity Bridge")
        render_clean_table([audit["ev_bridge"]], column_order=None)

    st.markdown("#### Charts")
    _render_dcf_charts(audit)

    st.markdown("#### Sensitivity Tables")
    s_col1, s_col2 = st.columns(2)
    with s_col1:
        st.caption("WACC × Terminal Growth")
        render_clean_table(fmt_sens_table(audit["sensitivity"]["wacc_x_terminal_growth"]), column_order=None)
    with s_col2:
        st.caption("WACC × Exit Multiple")
        render_clean_table(fmt_sens_table(audit["sensitivity"]["wacc_x_exit_multiple"]), column_order=None)

    mi = audit.get("model_integrity") or {}
    with st.expander("Model Integrity", expanded=False):
        mi_c1, mi_c2 = st.columns(2)
        tv_pct = mi.get("tv_pct_of_ev")
        tv_label = f"{tv_pct:.1f}%" if tv_pct is not None else "—"
        tv_delta = "High TV concentration (>75%)" if mi.get("tv_high_flag") else None
        with mi_c1:
            st.metric("Terminal Value % of EV", tv_label, delta=tv_delta, delta_color="inverse" if mi.get("tv_high_flag") else "normal")
            rev_flag = mi.get("revenue_data_quality_flag", "—")
            st.metric(
                "Revenue Data Quality",
                rev_flag,
                delta="Review needed" if rev_flag in ("low_quality", "needs_review") else None,
                delta_color="inverse" if rev_flag in ("low_quality", "needs_review") else "normal",
            )
        with mi_c2:
            nwc_flag = mi.get("nwc_driver_quality_flag", False)
            st.metric("NWC Driver Quality", "Warning" if nwc_flag else "OK", delta="Check NWC assumption" if nwc_flag else None, delta_color="inverse" if nwc_flag else "normal")
            roic_flag = mi.get("roic_consistency_flag", False)
            st.metric("ROIC Consistency", "Warning" if roic_flag else "OK", delta="ROIC inconsistency detected" if roic_flag else None, delta_color="inverse" if roic_flag else "normal")
