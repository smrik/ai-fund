from __future__ import annotations

import streamlit as st

from src.stage_00_data.estimate_tracker import get_revision_signals, snapshot_estimates


def render(memo, session_state=None) -> None:
    st.subheader("News & Revisions")
    try:
        sigs = get_revision_signals(memo.ticker)

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("EPS Rev (30d)", f"{sigs.eps_revision_30d_pct:+.1%}" if sigs.eps_revision_30d_pct is not None else "—")
        col2.metric("Rev Rev (30d)", f"{sigs.revenue_revision_30d_pct:+.1%}" if sigs.revenue_revision_30d_pct is not None else "—")
        col3.metric("EPS Rev (90d)", f"{sigs.eps_revision_90d_pct:+.1%}" if sigs.eps_revision_90d_pct is not None else "—")
        col4.metric("Est. Dispersion", f"{sigs.estimate_dispersion:.2%}" if sigs.estimate_dispersion is not None else "—")

        momentum_colors = {
            "strong_positive": "#22c55e",
            "positive": "#86efac",
            "neutral": "#6b7a99",
            "negative": "#fca5a5",
            "strong_negative": "#ef4444",
            "unavailable": "#6b7a99",
        }
        mom = sigs.revision_momentum
        color = momentum_colors.get(mom, "#6b7a99")
        st.markdown(
            f"**Revision Momentum:** <span style='color:{color};font-weight:700'>{mom.replace('_', ' ').title()}</span>",
            unsafe_allow_html=True,
        )

        if not sigs.available:
            st.info(f"No revision history yet for {memo.ticker}.")
            if st.button("Snapshot current estimates", key=f"snapshot_estimates_{memo.ticker}"):
                result = snapshot_estimates(memo.ticker)
                if result.get("available"):
                    st.success("Estimates snapshot saved. Run again tomorrow to build revision history.")
                else:
                    st.warning(f"Snapshot failed: {result.get('error')}")
    except Exception as exc:
        st.error(f"Revision tracker error: {exc}")
