from __future__ import annotations

import streamlit as st

from src.stage_04_pipeline.comps_dashboard import build_comps_dashboard_view

from ._shared import (
    format_metric_value,
    get_cached_view,
    metric_label,
    normalize_football_field_payload,
    render_clean_table,
    set_note_context,
)


_METRIC_KINDS = {
    "tev_ebitda_ltm": "x",
    "tev_ebitda_fwd": "x",
    "tev_ebit_ltm": "x",
    "tev_ebit_fwd": "x",
    "pe_ltm": "x",
    "revenue_growth": "pct",
    "ebit_margin": "pct",
    "net_debt_to_ebitda": "x",
}


def _load_view(memo, session_state=None) -> dict:
    state = session_state or st.session_state
    comps_view = get_cached_view(state, "comps_view", build_comps_dashboard_view, memo.ticker)
    football_field_payload = (comps_view or {}).get("football_field") or {}
    if comps_view.get("available") and "ranges" not in football_field_payload:
        upgraded_football_field = normalize_football_field_payload(football_field_payload)
        if upgraded_football_field.get("ranges"):
            comps_view = {**comps_view, "football_field": upgraded_football_field}
            state["comps_view"] = comps_view
        else:
            comps_view = build_comps_dashboard_view(memo.ticker)
            state["comps_view"] = comps_view
    return comps_view


def render_comparables(memo, session_state=None) -> None:
    state = session_state or st.session_state
    st.subheader("Comparables")
    comps_view = _load_view(memo, state)
    if not comps_view.get("available"):
        st.info("No comps view available for this ticker.")
        return

    metric_options = comps_view.get("metric_options") or []
    option_lookup = {option["label"]: option["key"] for option in metric_options if option.get("key")}
    default_metric = comps_view.get("selected_metric_default")
    default_label = next(
        (option["label"] for option in metric_options if option.get("key") == default_metric),
        metric_options[0]["label"] if metric_options else "Primary",
    )
    selected_metric_label = st.selectbox(
        "Valuation Metric",
        list(option_lookup) or [default_label],
        index=(list(option_lookup).index(default_label) if option_lookup and default_label in option_lookup else 0),
        key=f"comps_metric_{memo.ticker}",
    )
    selected_metric_key = option_lookup.get(selected_metric_label, default_metric)
    set_note_context(
        state,
        page="Valuation",
        subpage="Comparables",
        item=f"{selected_metric_label} Football Field",
    )
    selected_metric = (comps_view.get("valuation_range_by_metric") or {}).get(selected_metric_key) or {}

    top = st.columns(5)
    valuation_range = comps_view.get("valuation_range") or {}
    top[0].metric("Primary Metric", selected_metric_label or "—")
    top[1].metric("Bear IV", format_metric_value(selected_metric.get("bear"), kind="price"))
    top[2].metric("Base IV", format_metric_value(selected_metric.get("base"), kind="price"))
    top[3].metric("Bull IV", format_metric_value(selected_metric.get("bull"), kind="price"))
    top[4].metric("Blended Base", format_metric_value(valuation_range.get("blended_base"), kind="price"))

    peer_counts = comps_view.get("peer_counts") or {}
    counts_cols = st.columns(4)
    counts_cols[0].metric("Peers Raw", format_metric_value(peer_counts.get("raw"), kind="count"))
    counts_cols[1].metric("Peers Clean", format_metric_value(peer_counts.get("clean"), kind="count"))
    counts_cols[2].metric("Current Price", format_metric_value((comps_view.get("target") or {}).get("current_price"), kind="price"))
    counts_cols[3].metric(
        "Analyst Target",
        format_metric_value(
            next((marker.get("value") for marker in (comps_view.get("football_field") or {}).get("markers", []) if marker.get("label") == "Analyst Target Mean"), None),
            kind="price",
        ),
    )

    compare_rows = []
    compare_payload = comps_view.get("target_vs_peers") or {}
    for key, target_value in (compare_payload.get("target") or {}).items():
        kind = _METRIC_KINDS.get(key, "raw")
        compare_rows.append(
            {
                "metric": metric_label(key),
                "target": format_metric_value(target_value, kind=kind),
                "peer_median": format_metric_value((compare_payload.get("peer_medians") or {}).get(key), kind=kind),
                "delta": format_metric_value((compare_payload.get("deltas") or {}).get(key), kind=kind),
            }
        )
    if compare_rows:
        st.markdown("#### Target vs Peer Medians")
        render_clean_table(compare_rows, column_order=["metric", "target", "peer_median", "delta"])

    football_field = comps_view.get("football_field") or {}
    markers = football_field.get("markers") or []
    range_rows = football_field.get("ranges") or []
    if range_rows:
        st.markdown("#### Football Field")
        try:
            import plotly.graph_objects as go
        except ImportError:
            fallback_rows = [
                {
                    "metric": row.get("label"),
                    "bear": format_metric_value(row.get("bear"), kind="price"),
                    "base": format_metric_value(row.get("base"), kind="price"),
                    "bull": format_metric_value(row.get("bull"), kind="price"),
                }
                for row in range_rows
            ]
            render_clean_table(fallback_rows, column_order=["metric", "bear", "base", "bull"])
        else:
            fig = go.Figure()
            plotted_rows = list(reversed(range_rows))
            for row in plotted_rows:
                bear_value = row.get("bear")
                bull_value = row.get("bull")
                base_value = row.get("base")
                if bear_value is not None and bull_value is not None:
                    fig.add_trace(
                        go.Bar(
                            x=[float(bull_value) - float(bear_value)],
                            y=[row.get("label")],
                            orientation="h",
                            base=[float(bear_value)],
                            marker=dict(color="rgba(255, 61, 0, 0.34)", line=dict(color="#ff7a59", width=1.2)),
                            showlegend=False,
                        )
                    )
                if base_value is not None:
                    fig.add_trace(
                        go.Scatter(
                            x=[float(base_value)],
                            y=[row.get("label")],
                            mode="markers",
                            marker=dict(size=13, symbol="diamond", color="#FAFAFA", line=dict(color="#FF3D00", width=1.5)),
                            showlegend=False,
                        )
                    )
            for marker in markers:
                if marker.get("type") != "spot" or marker.get("value") is None:
                    continue
                fig.add_trace(
                    go.Scatter(
                        x=[float(marker["value"]), float(marker["value"])],
                        y=[plotted_rows[0].get("label"), plotted_rows[-1].get("label")],
                        mode="lines",
                        line=dict(
                            color="#38bdf8" if marker.get("label") == "Current Price" else "#f59e0b",
                            width=2,
                            dash="dot" if marker.get("label") == "Current Price" else "dash",
                        ),
                        name=marker.get("label"),
                    )
                )
            range_min = football_field.get("range_min")
            range_max = football_field.get("range_max")
            if range_min is not None and range_max is not None:
                spread = max(float(range_max) - float(range_min), 10.0)
                pad = spread * 0.08
                fig.update_xaxes(range=[float(range_min) - pad, float(range_max) + pad])
            fig.update_layout(
                barmode="overlay",
                height=max(340, 72 * len(plotted_rows)),
                margin=dict(l=20, r=20, t=20, b=20),
                xaxis_title="Implied Value Per Share",
                yaxis_title="",
                plot_bgcolor="rgba(0,0,0,0)",
                paper_bgcolor="rgba(0,0,0,0)",
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
            )
            st.plotly_chart(fig, width="stretch")

    st.markdown("#### Peer Table")
    peer_table_rows = []
    for row in comps_view.get("peers") or []:
        peer_table_rows.append(
            {
                "ticker": row.get("ticker"),
                "similarity": row.get("similarity_score"),
                "weight": row.get("model_weight"),
                "TEV / EBITDA LTM": row.get("tev_ebitda_ltm"),
                "TEV / EBIT Fwd": row.get("tev_ebit_fwd"),
                "TEV / EBIT LTM": row.get("tev_ebit_ltm"),
                "P / E LTM": row.get("pe_ltm"),
                "Revenue Growth": row.get("revenue_growth"),
                "EBIT Margin": row.get("ebit_margin"),
                "Net Debt / EBITDA": row.get("net_debt_to_ebitda"),
            }
        )
    render_clean_table(
        peer_table_rows,
        {
            "similarity": "raw",
            "weight": "pct",
            "TEV / EBITDA LTM": "x",
            "TEV / EBIT Fwd": "x",
            "TEV / EBIT LTM": "x",
            "P / E LTM": "x",
            "Revenue Growth": "pct",
            "EBIT Margin": "pct",
            "Net Debt / EBITDA": "x",
        },
        column_order=[
            "ticker",
            "similarity",
            "weight",
            "TEV / EBITDA LTM",
            "TEV / EBIT Fwd",
            "TEV / EBIT LTM",
            "P / E LTM",
            "Revenue Growth",
            "EBIT Margin",
            "Net Debt / EBITDA",
        ],
        height=420,
    )

    audit_flags = comps_view.get("audit_flags") or []
    st.markdown("#### Audit Flags")
    if audit_flags:
        for flag in audit_flags:
            st.warning(flag)
    else:
        st.info("No comps audit flags for this run.")


def render_multiples(memo, session_state=None) -> None:
    state = session_state or st.session_state
    st.subheader("Multiples")
    comps_view = _load_view(memo, state)
    summary = comps_view.get("historical_multiples_summary") or {}
    if not summary.get("available"):
        st.info("Historical multiples are unavailable for this ticker.")
        for flag in summary.get("audit_flags") or []:
            st.caption(flag)
        return

    historical_metrics = summary.get("metrics") or {}
    selected_metric = st.selectbox("Historical Multiple Series", list(historical_metrics), key=f"historical_multiple_{memo.ticker}")
    set_note_context(state, page="Valuation", subpage="Multiples", item=f"Historical {selected_metric}")
    historical_payload = historical_metrics.get(selected_metric) or {}
    historical_summary = historical_payload.get("summary") or {}
    hist_cols = st.columns(5)
    hist_cols[0].metric("Current", format_metric_value(historical_summary.get("current"), kind="multiple"))
    hist_cols[1].metric("Median", format_metric_value(historical_summary.get("median"), kind="multiple"))
    hist_cols[2].metric("Min", format_metric_value(historical_summary.get("min"), kind="multiple"))
    hist_cols[3].metric("Max", format_metric_value(historical_summary.get("max"), kind="multiple"))
    hist_cols[4].metric("Current Percentile", format_metric_value(historical_summary.get("current_percentile"), kind="pct"))

    series = historical_payload.get("series") or []
    if series:
        try:
            import plotly.graph_objects as go
        except ImportError:
            render_clean_table(series, {"multiple": "x", "price": "price"}, column_order=["date", "multiple", "price"])
        else:
            fig = go.Figure()
            fig.add_trace(
                go.Scatter(
                    x=[row.get("date") for row in series],
                    y=[row.get("multiple") for row in series],
                    mode="lines",
                    name=selected_metric,
                    line=dict(color="#38bdf8", width=2),
                )
            )
            peer_current = historical_summary.get("peer_current")
            if peer_current is not None:
                fig.add_hline(y=float(peer_current), line_dash="dash", line_color="#f59e0b", annotation_text="Peer Current", annotation_position="top left")
            fig.update_layout(height=320, margin=dict(l=20, r=20, t=20, b=20), xaxis_title="Date", yaxis_title="Multiple", showlegend=False)
            st.plotly_chart(fig, width="stretch")
