from __future__ import annotations

import streamlit as st

from config import DB_PATH
from src.stage_02_valuation.portfolio_risk import build_portfolio_risk

from ._shared import render_clean_table


def render(memo, session_state=None) -> None:
    st.subheader("Portfolio Risk")
    st.caption("Correlation, VaR/CVaR, sector concentration, and exposure metrics across the universe.")

    try:
        import sqlite3

        conn = sqlite3.connect(str(DB_PATH))
        conn.row_factory = sqlite3.Row
        pos_rows = conn.execute("SELECT ticker, direction, market_value, shares FROM positions WHERE market_value IS NOT NULL").fetchall()
        conn.close()
        positions = [dict(row) for row in pos_rows]
    except Exception:
        positions = []

    try:
        from config import UNIVERSE_TICKERS
        universe_tickers = UNIVERSE_TICKERS if UNIVERSE_TICKERS else []
    except Exception:
        universe_tickers = []

    if positions:
        tickers = [p["ticker"] for p in positions]
    elif universe_tickers:
        tickers = list(universe_tickers)[:20]
    else:
        tickers = [memo.ticker] if memo and memo.ticker else []

    if not tickers:
        st.info("No positions or universe tickers found. Add positions or configure universe.csv.")
        return

    period = st.selectbox("Return lookback", ["6mo", "1y", "2y"], index=1, key="pr_period")
    if st.button("Compute Portfolio Risk", key="compute_pr"):
        with st.spinner("Fetching price history and computing risk metrics..."):
            try:
                weights = None
                if positions:
                    total_long = sum(abs(p.get("market_value", 0) or 0) for p in positions if (p.get("market_value") or 0) > 0)
                    weights = {p["ticker"]: (p.get("market_value") or 0) / total_long for p in positions if total_long > 0}
                st.session_state["pr_summary"] = build_portfolio_risk(tickers, weights=weights, positions=positions or None, period=period)
            except Exception as exc:
                st.error(f"Portfolio risk error: {exc}")

    summary = st.session_state.get("pr_summary")
    if summary is None:
        return

    if summary.gross_exposure:
        cols = st.columns(4)
        cols[0].metric("Gross Exposure", f"${summary.gross_exposure:,.0f}")
        cols[1].metric("Net Exposure", f"${summary.net_exposure:,.0f}")
        cols[2].metric("Long", f"${summary.long_exposure:,.0f}")
        cols[3].metric("Short", f"${summary.short_exposure:,.0f}")

    st.markdown("#### VaR / CVaR (1-Day)")
    var_cols = st.columns(4)
    for idx, (label, key) in enumerate([("VaR 95%", "var_95"), ("VaR 99%", "var_99"), ("CVaR 95%", "cvar_95"), ("CVaR 99%", "cvar_99")]):
        value = getattr(summary, key, None)
        var_cols[idx].metric(label, f"{value * 100:.2f}%" if value is not None else "—")

    if summary.correlation_matrix and len(summary.tickers) >= 2:
        st.markdown("#### Correlation Heatmap")
        try:
            import plotly.graph_objects as go
        except ImportError:
            render_clean_table(summary.corr_pairs, column_order=None)
        else:
            fig = go.Figure(
                data=go.Heatmap(
                    z=summary.correlation_matrix,
                    x=summary.tickers,
                    y=summary.tickers,
                    colorscale="RdYlGn",
                    zmin=-1,
                    zmax=1,
                )
            )
            fig.update_layout(height=max(300, 40 * len(summary.tickers)))
            st.plotly_chart(fig, width="stretch")
        st.markdown("#### Top Correlated Pairs")
        render_clean_table(summary.top_correlated_pairs, column_order=None)

    if summary.sector_weights:
        st.markdown("#### Sector Concentration")
        rows = [{"sector": sector, "weight_pct": weight} for sector, weight in summary.sector_weights.items()]
        render_clean_table(rows, {"weight_pct": "pct"}, column_order=["sector", "weight_pct"])
