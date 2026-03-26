from __future__ import annotations

import streamlit as st

from src.stage_00_data.fred_client import get_macro_snapshot, get_yield_curve
from src.stage_02_valuation.regime_model import (
    detect_current_regime,
    get_regime_badge_html,
    get_scenario_weights,
)

from ._shared import render_clean_table


def render(memo, session_state=None) -> None:
    st.subheader("Macro")
    try:
        regime = detect_current_regime()
        weights = get_scenario_weights(regime)

        col_regime, col_vix, col_hy, col_slope, col_ff = st.columns(5)
        with col_regime:
            st.markdown("**Market Regime**")
            st.markdown(get_regime_badge_html(regime), unsafe_allow_html=True)
            if getattr(regime, "available", False):
                for lbl, prob in (regime.probabilities or {}).items():
                    st.caption(f"{lbl}: {prob:.0%}")

        macro_snap = get_macro_snapshot(lookback_days=5)
        if macro_snap.get("available"):
            series = macro_snap.get("series", {})
            vix = series.get("VIXCLS", {}).get("latest_value")
            hy = series.get("BAMLH0A0HYM2", {}).get("latest_value")
            slope = series.get("T10Y2Y", {}).get("latest_value")
            ff_rate = series.get("FEDFUNDS", {}).get("latest_value")
            col_vix.metric("VIX", f"{vix:.1f}" if vix is not None else "—")
            col_hy.metric("HY Spread (bps)", f"{hy * 100:.0f}" if hy is not None else "—")
            col_slope.metric("2s10s Slope (bps)", f"{slope * 100:.0f}" if slope is not None else "—")
            col_ff.metric("Fed Funds", f"{ff_rate:.2%}" if ff_rate is not None else "—")

        weight_cols = st.columns(3)
        weight_cols[0].metric("Bear", f"{weights.bear:.0%}")
        weight_cols[1].metric("Base", f"{weights.base:.0%}")
        weight_cols[2].metric("Bull", f"{weights.bull:.0%}")

        yc = get_yield_curve()
        if yc.get("available") and yc.get("maturities"):
            try:
                import plotly.graph_objects as go
            except ImportError:
                render_clean_table(yc.get("maturities") or [], column_order=None)
            else:
                mats = yc["maturities"]
                fig = go.Figure(
                    go.Scatter(
                        x=[m[0] for m in mats],
                        y=[m[2] for m in mats if m[2] is not None],
                        mode="lines+markers",
                        line=dict(color="#388bfd", width=2),
                    )
                )
                fig.update_layout(height=280, margin=dict(l=0, r=0, t=20, b=0), xaxis_title="Maturity", yaxis_title="Yield (%)")
                st.plotly_chart(fig, width="stretch")
    except Exception as exc:
        st.error(f"Macro data unavailable: {exc}")
        st.info("Set FRED_API_KEY environment variable to enable live macro data.")
