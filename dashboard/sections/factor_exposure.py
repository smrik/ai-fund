from __future__ import annotations

import streamlit as st

from src.stage_02_valuation.factor_model import decompose_factor_exposure, get_factor_summary_text


def render(memo, session_state=None) -> None:
    st.subheader("Factor Exposure")
    try:
        with st.spinner("Computing factor exposures (requires ~1yr of price history)..."):
            exposure = decompose_factor_exposure(memo.ticker)

        if exposure.available:
            st.caption(get_factor_summary_text(exposure))

            col1, col2, col3 = st.columns(3)
            col1.metric("Market Beta", f"{exposure.market_beta:.2f}" if exposure.market_beta is not None else "—")
            col2.metric("R²", f"{exposure.r_squared:.1%}" if exposure.r_squared is not None else "—")
            col3.metric("Alpha (ann.)", f"{exposure.annualized_alpha:+.1%}" if exposure.annualized_alpha is not None else "—")

            col4, col5, col6 = st.columns(3)
            col4.metric("Value (HML)", f"{exposure.value_beta:.2f}" if exposure.value_beta is not None else "—")
            col5.metric("Momentum", f"{exposure.momentum_beta:.2f}" if exposure.momentum_beta is not None else "—")
            col6.metric("Quality (RMW)", f"{exposure.profitability_beta:.2f}" if exposure.profitability_beta is not None else "—")

            if exposure.factor_attribution:
                try:
                    import plotly.graph_objects as go
                except ImportError:
                    st.info("Install Plotly to view the factor attribution chart.")
                else:
                    factor_names = list(exposure.factor_attribution.keys())
                    factor_vals = [exposure.factor_attribution[f] * 100 for f in factor_names]
                    colors = ["#388bfd" if v >= 0 else "#ef4444" for v in factor_vals]
                    fig = go.Figure(go.Bar(x=factor_names, y=factor_vals, marker_color=colors, name="Factor Attribution (%)"))
                    fig.update_layout(height=280, margin=dict(l=0, r=0, t=20, b=0), yaxis_title="Attribution (%)")
                    st.plotly_chart(fig, width="stretch")

            if exposure.r_squared and exposure.r_squared > 0.85:
                st.warning("High R² (>85%) — returns highly systematic. Alpha opportunity may be limited.")
        else:
            st.info(f"Factor exposure unavailable: {exposure.error}")
    except Exception as exc:
        st.error(f"Factor model error: {exc}")
