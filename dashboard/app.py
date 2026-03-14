"""
Streamlit dashboard — AI Hedge Fund Research Pod.
Run: streamlit run dashboard/app.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import json
import streamlit as st
from config import LLM_MODEL

st.set_page_config(
    page_title="AI Research Pod",
    page_icon="📊",
    layout="wide",
)

# ── Sidebar ──────────────────────────────────────────────────────────────────
with st.sidebar:
    st.title("📊 AI Research Pod")
    st.caption("Tiger-style fundamental analysis pipeline")
    st.divider()

    AGENT_OPTIONS = [
        "IndustryAgent",
        "FilingsAgent",
        "EarningsAgent",
        "QoEAgent",
        "AccountingRecastAgent",
        "ValuationAgent",
        "SentimentAgent",
        "RiskAgent",
        "RiskImpactAgent",
        "ThesisAgent",
    ]

    ticker_input = st.text_input(
        "Ticker",
        placeholder="e.g. AAPL, MSFT, NVDA",
        help="US-listed tickers only (SEC EDGAR required)",
    ).upper().strip()

    run_btn = st.button("Run Analysis", type="primary", use_container_width=True)
    use_agent_cache = st.checkbox(
        "Use agent cache",
        value=True,
        help="Reuse cached agent outputs when inputs, prompt, and model hashes have not changed.",
    )
    force_refresh_agents = st.multiselect(
        "Force refresh agents",
        options=AGENT_OPTIONS,
        default=[],
        help="Bypass cache for only these steps. Downstream agents still reuse cache if their hashed inputs are unchanged.",
    )

    st.divider()
    st.caption("**Pipeline:** Industry → Filings → Earnings → QoE → Accounting Recast → Valuation → Sentiment → Risk → Risk Impact → Thesis")
    st.caption("**Data:** SEC EDGAR (free) + yfinance")
    st.caption(f"**Primary LLM:** {LLM_MODEL}")


# ── Session state ─────────────────────────────────────────────────────────────
if "memo" not in st.session_state:
    st.session_state.memo = None
if "running" not in st.session_state:
    st.session_state.running = False
if "recommendations" not in st.session_state:
    st.session_state.recommendations = None
if "workbench_preview" not in st.session_state:
    st.session_state.workbench_preview = None
if "run_trace" not in st.session_state:
    st.session_state.run_trace = []


def _to_display_value(value: float | None, unit: str) -> float:
    if value is None:
        return 0.0
    if unit == "pct":
        return float(value) * 100.0
    if unit == "usd":
        return float(value) / 1_000_000.0
    return float(value)


def _from_display_value(value: float, unit: str) -> float:
    if unit == "pct":
        return float(value) / 100.0
    if unit == "usd":
        return float(value) * 1_000_000.0
    return float(value)


def _format_value(value: float | None, unit: str) -> str:
    if value is None:
        return "—"
    if unit == "pct":
        return f"{float(value) * 100:.1f}%"
    if unit == "usd":
        return f"${float(value) / 1_000_000:,.0f}mm"
    if unit == "days":
        return f"{float(value):,.1f}d"
    if unit == "x":
        return f"{float(value):,.1f}x"
    return f"{float(value):,.4f}"


def _input_step(unit: str) -> float:
    if unit == "pct":
        return 0.5
    if unit == "usd":
        return 10.0
    if unit == "days":
        return 1.0
    if unit == "x":
        return 0.25
    return 0.01


def _render_dcf_charts(audit: dict) -> None:
    try:
        import plotly.graph_objects as go
    except ImportError:
        st.info("Plotly is not installed. Add `plotly` to requirements to enable browser-native DCF charts.")
        return

    chart_series = audit.get("chart_series") or {}
    forecast_tab, valuation_tab, sensitivity_tab, risk_tab = st.tabs(
        ["Forecast", "Valuation", "Sensitivity", "Risk Impact"]
    )

    with forecast_tab:
        projection = chart_series.get("projection_curve") or []
        if projection:
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=[row["year"] for row in projection],
                y=[row["revenue_mm"] for row in projection],
                name="Revenue ($mm)",
                mode="lines+markers",
                yaxis="y1",
            ))
            fig.add_trace(go.Scatter(
                x=[row["year"] for row in projection],
                y=[row["ebit_margin_pct"] for row in projection],
                name="EBIT Margin (%)",
                mode="lines+markers",
                yaxis="y2",
            ))
            fig.update_layout(
                height=420,
                margin=dict(l=20, r=20, t=40, b=20),
                yaxis=dict(title="Revenue ($mm)"),
                yaxis2=dict(title="EBIT Margin (%)", overlaying="y", side="right"),
                legend=dict(orientation="h"),
            )
            st.plotly_chart(fig, use_container_width=True)

        fcff = chart_series.get("fcff_curve") or []
        if fcff:
            fig = go.Figure()
            fig.add_trace(go.Bar(
                x=[row["year"] for row in fcff],
                y=[row["fcff_mm"] for row in fcff],
                name="FCFF ($mm)",
            ))
            fig.add_trace(go.Scatter(
                x=[row["year"] for row in fcff],
                y=[row["nopat_mm"] for row in fcff],
                name="NOPAT ($mm)",
                mode="lines+markers",
            ))
            fig.update_layout(height=420, margin=dict(l=20, r=20, t=40, b=20), legend=dict(orientation="h"))
            st.plotly_chart(fig, use_container_width=True)

    with valuation_tab:
        scenario_iv = chart_series.get("scenario_iv") or []
        if scenario_iv:
            fig = go.Figure()
            fig.add_trace(go.Bar(
                x=[row["scenario"].title() for row in scenario_iv],
                y=[row["intrinsic_value"] for row in scenario_iv],
                name="Intrinsic Value",
            ))
            current_price = audit.get("current_price")
            if current_price is not None:
                fig.add_hline(y=current_price, line_dash="dash", annotation_text=f"Current Price ${current_price:,.2f}")
            fig.update_layout(height=420, margin=dict(l=20, r=20, t=40, b=20))
            st.plotly_chart(fig, use_container_width=True)

        ev_bridge = chart_series.get("ev_bridge_waterfall") or []
        if ev_bridge:
            fig = go.Figure(go.Waterfall(
                x=[row["component"] for row in ev_bridge],
                y=[row["value_mm"] for row in ev_bridge],
                measure=["relative", "relative", "relative", "relative", "total"],
            ))
            fig.update_layout(height=420, margin=dict(l=20, r=20, t=40, b=20))
            st.plotly_chart(fig, use_container_width=True)

    with sensitivity_tab:
        heat_cols = st.columns(2)
        sens_growth = audit.get("sensitivity", {}).get("wacc_x_terminal_growth") or []
        sens_exit = audit.get("sensitivity", {}).get("wacc_x_exit_multiple") or []
        if sens_growth:
            x_labels = [key for key in sens_growth[0].keys() if key != "wacc_pct"]
            y_vals = [row["wacc_pct"] for row in sens_growth]
            z_vals = [[row[key] for key in x_labels] for row in sens_growth]
            fig = go.Figure(data=go.Heatmap(x=x_labels, y=y_vals, z=z_vals, colorbar_title="IV"))
            fig.update_layout(height=400, margin=dict(l=20, r=20, t=40, b=20), title="WACC × Terminal Growth")
            heat_cols[0].plotly_chart(fig, use_container_width=True)
        if sens_exit:
            x_labels = [key for key in sens_exit[0].keys() if key != "wacc_pct"]
            y_vals = [row["wacc_pct"] for row in sens_exit]
            z_vals = [[row[key] for key in x_labels] for row in sens_exit]
            fig = go.Figure(data=go.Heatmap(x=x_labels, y=y_vals, z=z_vals, colorbar_title="IV"))
            fig.update_layout(height=400, margin=dict(l=20, r=20, t=40, b=20), title="WACC × Exit Multiple")
            heat_cols[1].plotly_chart(fig, use_container_width=True)

    with risk_tab:
        risk_view = audit.get("risk_impact")
        overlays = chart_series.get("risk_overlay") or []
        if not risk_view or not risk_view.get("available") or not overlays:
            st.info("No quantified risk overlays are available for this run.")
        else:
            top = st.columns(3)
            top[0].metric("Base IV", f"${risk_view.get('base_iv', 0):,.2f}")
            top[1].metric("Risk-Adjusted Expected IV", f"${risk_view.get('risk_adjusted_expected_iv', 0):,.2f}")
            delta = risk_view.get("risk_adjusted_delta_pct")
            top[2].metric("Risk Adjustment", f"{delta*100:+.1f}%" if delta is not None else "—")

            fig = go.Figure()
            fig.add_trace(go.Bar(
                x=[row["risk_name"] for row in overlays],
                y=[row["stressed_iv"] for row in overlays],
                text=[f"p={row['probability']:.0%}" for row in overlays],
                textposition="outside",
                name="Stressed IV",
            ))
            fig.add_hline(y=risk_view.get("base_iv", 0), line_dash="dash", annotation_text="Base IV")
            fig.add_hline(y=risk_view.get("risk_adjusted_expected_iv", 0), line_dash="dot", annotation_text="Risk-Adj. EV")
            fig.update_layout(height=420, margin=dict(l=20, r=20, t=40, b=20))
            st.plotly_chart(fig, use_container_width=True)

            st.dataframe(risk_view.get("overlay_results") or [], use_container_width=True, hide_index=True)


# ── Run pipeline ──────────────────────────────────────────────────────────────
if run_btn and ticker_input:
    st.session_state.running = True
    st.session_state.memo = None
    st.session_state.recommendations = None
    st.session_state.run_trace = []

    with st.status(f"Running 10-agent analysis for **{ticker_input}**...", expanded=True) as status:
        steps = [
            "Fetching market snapshot",
            "0a/9  IndustryAgent — sector benchmarks & recent events",
            "1/9  FilingsAgent — parsing SEC 10-K / 10-Q",
            "2/9  EarningsAgent — analysing earnings calls",
            "2a/9  QoEAgent — quality-of-earnings signals + EBIT normalisation",
            "2b/9  AccountingRecastAgent — proposing EBIT and EV-bridge reclassifications",
            "3/9  ValuationAgent — running DCF + comps",
            "4/9  SentimentAgent — scoring news & analyst positioning",
            "5/9  RiskAgent — sizing position",
            "5a/9  RiskImpactAgent — converting key risks into valuation overlays",
            "6/9  ThesisAgent — synthesizing IC memo",
        ]
        placeholders = {s: st.empty() for s in steps}
        for s in steps:
            placeholders[s].markdown(f"⏳ {s}")

        try:
            from src.stage_04_pipeline.orchestrator import PipelineOrchestrator

            class StreamingOrchestrator(PipelineOrchestrator):
                def _on_step(self, step_name: str) -> None:
                    if step_name in placeholders:
                        placeholders[step_name].markdown(f"🔄 **{step_name}**")

                def _on_done(self, step_name: str, detail: str = "") -> None:
                    if step_name in placeholders:
                        msg = f"✅ {step_name}"
                        if detail:
                            msg += f" — {detail}"
                        placeholders[step_name].markdown(msg)

                def _on_warn(self, message: str) -> None:
                    status.write(f"⚠ {message}")

            orch = StreamingOrchestrator()
            memo = orch.run(
                ticker_input,
                use_cache=use_agent_cache,
                force_refresh_agents=set(force_refresh_agents),
            )
            st.session_state.memo = memo
            st.session_state.run_trace = orch.last_run_trace
            try:
                from src.stage_04_pipeline.recommendations import write_recommendations
                recs = orch.collect_recommendations(ticker_input)
                write_recommendations(recs)
                st.session_state.recommendations = recs
            except Exception:
                st.session_state.recommendations = None
            status.update(label=f"Analysis complete — **{ticker_input}**", state="complete")

        except Exception as e:
            status.update(label=f"Pipeline error: {e}", state="error")

st.session_state.running = False

memo = st.session_state.memo

if memo is None:
    st.markdown("""
## How to use

1. Enter a **US-listed ticker** in the sidebar (e.g. `AAPL`, `MSFT`, `NVDA`)
2. Click **Run Analysis**
3. The pipeline runs the full multi-agent research workflow with deterministic valuation and cached re-runs where possible
4. Review all intermediate outputs — **you are the human-in-the-loop**
5. Use the Variant Thesis Prompt as your starting point for the investment decision

### The Research Workflow

| Step | Job |
|---|---|
| **IndustryAgent** | Pulls sector benchmarks and current industry context |
| **FilingsAgent** | Parses 10-K/10-Q, extracts revenue trends, margins, FCF, red flags |
| **EarningsAgent** | Analyses earnings calls, guidance vs actuals, management tone |
| **QoEAgent** | Flags quality-of-earnings issues and possible EBIT normalisation |
| **AccountingRecastAgent** | Proposes operating vs non-operating / bridge reclassifications |
| **ValuationAgent** | Runs deterministic DCF + comps, produces bear/base/bull intrinsic value |
| **SentimentAgent** | Scores news narrative and analyst positioning |
| **RiskAgent** | Sizes position based on conviction + volatility |
| **RiskImpactAgent** | Converts top risks into downside valuation overlays and risk-adjusted IV |
| **ThesisAgent** | Synthesizes the IC memo and forces the decision |

> **Your job:** Write the variant thesis. The AI surfaces what's known; you identify why the market is wrong.
""")
    st.stop()

# ── IC Memo Header ─────────────────────────────────────────────────────────────
action_color = {
    "BUY": "🟢",
    "SELL SHORT": "🔴",
    "WATCH": "🟡",
    "PASS": "⚪",
}.get(memo.action, "⚪")

st.title(f"{action_color} {memo.ticker} — {memo.company_name}")
st.caption(f"{memo.sector} | {memo.date} | Analyst: {memo.analyst}")

col1, col2, col3, col4, col5 = st.columns(5)
col1.metric("Action", memo.action)
col2.metric("Conviction", memo.conviction.upper())
col3.metric("Current Price", f"${memo.valuation.current_price or 0:,.2f}")
col4.metric("Base Case", f"${memo.valuation.base:,.2f}")
col5.metric(
    "Upside (base)",
    f"{(memo.valuation.upside_pct_base or 0)*100:+.1f}%",
)

st.info(f"**One-liner:** {memo.one_liner}")

# ── Variant Thesis Prompt (most important) ─────────────────────────────────────
st.subheader("🎯 Variant Thesis Prompt")
st.warning(
    f"**Your judgment required:** {memo.variant_thesis_prompt}\n\n"
    "_This is the question the AI cannot answer for you. Answer this before sizing the position._"
)

# ── Sections ──────────────────────────────────────────────────────────────────
SECTION_OPTIONS = [
    "📋 Thesis",
    "💰 Valuation",
    "🧮 DCF Audit",
    "📂 Filings",
    "📞 Earnings",
    "📰 Sentiment",
    "⚖️ Risk",
    "🔄 Pipeline",
    "🔧 Recommendations",
    "🧪 Assumption Lab",
    "🔍 Raw JSON",
]
selected_section = st.radio(
    "Section",
    SECTION_OPTIONS,
    horizontal=True,
    label_visibility="collapsed",
    key="main_dashboard_section",
)

if selected_section == "📋 Thesis":
    col_a, col_b, col_c = st.columns(3)
    with col_a:
        st.subheader("🐂 Bull Case")
        st.write(memo.bull_case)
    with col_b:
        st.subheader("📊 Base Case")
        st.write(memo.base_case)
    with col_c:
        st.subheader("🐻 Bear Case")
        st.write(memo.bear_case)

    st.divider()
    col_l, col_r = st.columns(2)
    with col_l:
        st.subheader("⚡ Key Catalysts")
        for cat in memo.key_catalysts:
            st.markdown(f"- {cat}")
    with col_r:
        st.subheader("⚠️ Key Risks")
        for risk in memo.key_risks:
            st.markdown(f"- {risk}")

    st.subheader("❓ Open Questions (further diligence)")
    for q in memo.open_questions:
        st.markdown(f"- {q}")

if selected_section == "💰 Valuation":
    st.subheader("DCF Bear / Base / Bull")
    val = memo.valuation
    price = val.current_price or 0
    data = {
        "Scenario": ["Bear", "Base", "Bull", "Current Price"],
        "Intrinsic Value": [f"${val.bear:.2f}", f"${val.base:.2f}", f"${val.bull:.2f}", f"${price:.2f}"],
        "Upside": [
            f"{((val.bear - price)/price*100):+.1f}%" if price else "—",
            f"{((val.base - price)/price*100):+.1f}%" if price else "—",
            f"{((val.bull - price)/price*100):+.1f}%" if price else "—",
            "—",
        ],
    }
    st.table(data)

if selected_section == "🧮 DCF Audit":
    st.subheader("DCF Audit")
    st.caption("Browser-native review of the deterministic model. These tables come directly from the Python DCF engine, not from the Excel export.")

    try:
        from src.stage_04_pipeline.dcf_audit import build_dcf_audit_view

        audit = build_dcf_audit_view(memo.ticker, risk_output=memo.risk_impact)
    except Exception as e:
        audit = None
        st.error(f"DCF audit load error: {e}")

    if not audit or not audit.get("available"):
        st.info("DCF audit view unavailable for this ticker. Re-run after valuation inputs are available.")
    else:
        st.subheader("Scenario Summary")
        st.dataframe(audit["scenario_summary"], use_container_width=True, hide_index=True)

        left, right = st.columns(2)
        with left:
            st.subheader("Key Drivers")
            st.dataframe(audit["driver_rows"], use_container_width=True, hide_index=True)
        with right:
            st.subheader("Health Flags")
            flag_rows = [
                {"flag": key, "active": bool(value)}
                for key, value in (audit.get("health_flags") or {}).items()
            ]
            st.dataframe(flag_rows, use_container_width=True, hide_index=True)

        st.subheader("Forecast Bridge (Base Scenario)")
        st.dataframe(audit["forecast_bridge"], use_container_width=True, hide_index=True)

        col_term, col_ev = st.columns(2)
        with col_term:
            st.subheader("Terminal Bridge")
            st.dataframe([audit["terminal_bridge"]], use_container_width=True, hide_index=True)
        with col_ev:
            st.subheader("EV → Equity Bridge")
            st.dataframe([audit["ev_bridge"]], use_container_width=True, hide_index=True)

        st.subheader("Charts")
        _render_dcf_charts(audit)

        sens_a, sens_b = st.columns(2)
        with sens_a:
            st.subheader("Sensitivity: WACC × Terminal Growth")
            st.dataframe(audit["sensitivity"]["wacc_x_terminal_growth"], use_container_width=True, hide_index=True)
        with sens_b:
            st.subheader("Sensitivity: WACC × Exit Multiple")
            st.dataframe(audit["sensitivity"]["wacc_x_exit_multiple"], use_container_width=True, hide_index=True)

if selected_section == "📂 Filings":
    f = memo.filings
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Revenue Trend", f.revenue_trend.title())
    col2.metric("Margin Trend", f.margin_trend.title())
    col3.metric("3Y Revenue CAGR", f"{(f.revenue_cagr_3y or 0)*100:.1f}%")
    col4.metric("Net Debt/EBITDA", f"{f.net_debt_to_ebitda:.1f}x" if f.net_debt_to_ebitda else "—")

    if f.red_flags:
        st.subheader("🚩 Red Flags")
        for flag in f.red_flags:
            st.warning(flag)

    st.subheader("Management Guidance")
    st.write(f.management_guidance)

    st.subheader("Full Analysis")
    st.write(f.raw_summary)

if selected_section == "📞 Earnings":
    e = memo.earnings
    col1, col2, col3 = st.columns(3)
    col1.metric("Guidance Trend", e.guidance_trend.title())
    col2.metric("Management Tone", e.management_tone.title())
    col3.metric("EPS Beat Rate", f"{(e.eps_beat_rate or 0)*100:.0f}%" if e.eps_beat_rate else "—")

    if e.key_themes:
        st.subheader("Key Themes")
        for theme in e.key_themes:
            st.markdown(f"- {theme}")

    st.subheader("Full Analysis")
    st.write(e.raw_summary)

if selected_section == "📰 Sentiment":
    s = memo.sentiment
    direction_emoji = {"bullish": "🟢", "bearish": "🔴", "neutral": "🟡"}.get(s.direction, "⚪")
    col1, col2 = st.columns(2)
    col1.metric("Direction", f"{direction_emoji} {s.direction.title()}")
    col2.metric("Score", f"{s.score:+.2f} / 1.0")

    col_a, col_b = st.columns(2)
    with col_a:
        st.subheader("Bullish Themes")
        for t in s.key_bullish_themes:
            st.markdown(f"- {t}")
    with col_b:
        st.subheader("Bearish Themes")
        for t in s.key_bearish_themes:
            st.markdown(f"- {t}")

    if s.risk_narratives:
        st.subheader("Risk Narratives")
        for n in s.risk_narratives:
            st.markdown(f"- {n}")

    st.subheader("Full Analysis")
    st.write(s.raw_summary)

if selected_section == "⚖️ Risk":
    r = memo.risk
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Conviction", r.conviction.upper())
    col2.metric("Position Size", f"${r.position_size_usd:,.0f}")
    col3.metric("% of Portfolio", f"{r.position_pct*100:.1f}%")
    col4.metric("Stop Loss", f"{r.suggested_stop_loss_pct*100:.0f}% below entry")

    if r.annualized_volatility:
        st.metric("Annualized Volatility", f"{r.annualized_volatility*100:.1f}%")

    st.subheader("Sizing Rationale")
    st.write(r.rationale)

    if memo.risk_impact and memo.risk_impact.overlays:
        st.subheader("Risk-to-Valuation Overlays")
        st.caption("Advisory-only downside scenarios inferred from qualitative risks. These do not change the base DCF.")
        st.dataframe(
            [overlay.model_dump(mode="python") for overlay in memo.risk_impact.overlays],
            use_container_width=True,
            hide_index=True,
        )

if selected_section == "🔄 Pipeline":
    st.subheader("Pipeline Trace")
    st.caption("Latest run trace plus persisted agent-run history from SQLite.")

    latest_trace = st.session_state.get("run_trace") or []
    if latest_trace:
        st.dataframe(latest_trace, use_container_width=True, hide_index=True)
    else:
        st.info("No in-session run trace available yet. Run the pipeline from this dashboard to populate it.")

    try:
        from src.stage_04_pipeline.agent_cache import load_agent_run_history

        run_history = load_agent_run_history(memo.ticker, limit=50)
    except Exception as e:
        run_history = []
        st.error(f"Agent run history error: {e}")

    if run_history:
        st.subheader("Recent Agent Run History")
        st.dataframe(run_history, use_container_width=True, hide_index=True)
    else:
        st.info("No persisted agent-run history stored yet for this ticker.")

if selected_section == "🔧 Recommendations":
    st.subheader("Agent Recommendations")
    recs = st.session_state.recommendations

    if recs is None:
        # Try loading from disk
        try:
            from src.stage_04_pipeline.recommendations import load_recommendations
            recs = load_recommendations(memo.ticker)
            st.session_state.recommendations = recs
        except Exception:
            recs = None

    if recs is None or not recs.recommendations:
        st.info("No recommendations available. Run a full analysis first (or re-run to refresh).")
    else:
        if recs.current_iv_base:
            st.caption(f"Current base IV: **${recs.current_iv_base:,.2f}**  |  Generated: {recs.generated_at}")

        # Group by agent
        from collections import defaultdict
        by_agent: dict = defaultdict(list)
        for r in recs.recommendations:
            by_agent[r.agent].append(r)

        agent_labels = {
            "qoe": "🔍 Quality of Earnings",
            "accounting_recast": "📊 Accounting Recast",
            "industry": "🏭 Industry",
            "filings": "📂 Filings Cross-Check",
        }
        approved_selection: list[str] = []

        for agent_key, agent_recs in by_agent.items():
            with st.expander(f"{agent_labels.get(agent_key, agent_key)} ({len(agent_recs)} item(s))", expanded=True):
                for rec in agent_recs:
                    col_a, col_b, col_c, col_d = st.columns([3, 2, 2, 2])
                    with col_a:
                        st.markdown(f"**{rec.field}**")
                        st.caption(rec.rationale)
                        if rec.citation:
                            st.caption(f"_Citation: {rec.citation[:120]}_")
                    with col_b:
                        cur_str = f"{rec.current_value:.4f}" if rec.current_value is not None else "—"
                        prop_str = f"{rec.proposed_value:.4f}" if isinstance(rec.proposed_value, float) else str(rec.proposed_value)
                        st.metric("Current → Proposed", f"{prop_str}", delta=f"from {cur_str}", delta_color="off")
                    with col_c:
                        badge = {"high": "🟢 high", "medium": "🟡 medium", "low": "🔴 low"}.get(rec.confidence, rec.confidence)
                        st.markdown(f"Confidence: **{badge}**")
                        st.markdown(f"Agent: `{rec.agent}`")
                    with col_d:
                        status_color = {"approved": "🟢", "rejected": "🔴", "pending": "🟡"}.get(rec.status, "⚪")
                        st.markdown(f"Status: {status_color} **{rec.status}**")
                    st.divider()

        # What-if preview section
        st.subheader("What-If Preview")
        all_pending_fields = [r.field for r in recs.recommendations if r.status == "pending"]
        selected_fields = st.multiselect(
            "Select fields to preview (simulates approval):",
            options=all_pending_fields,
            default=[],
            key=f"recs_preview_{memo.ticker}",
        )

        if selected_fields and st.button("Preview IV with selected approvals", key="preview_btn"):
            with st.spinner("Running preview DCF..."):
                try:
                    from src.stage_04_pipeline.recommendations import preview_with_approvals
                    # Temporarily mark selected as approved for preview
                    import copy as _copy
                    preview_recs = _copy.deepcopy(recs)
                    for r in preview_recs.recommendations:
                        if r.field in selected_fields:
                            r.status = "approved"
                    # Write temp recs and run preview
                    from src.stage_04_pipeline.recommendations import write_recommendations as _wr
                    _wr(preview_recs)
                    preview = preview_with_approvals(memo.ticker, selected_fields)
                    if preview:
                        cur = preview.get("current_iv", {})
                        prop = preview.get("proposed_iv", {})
                        dlt = preview.get("delta_pct", {})
                        p_col1, p_col2, p_col3 = st.columns(3)
                        for col, scenario in zip([p_col1, p_col2, p_col3], ["bear", "base", "bull"]):
                            with col:
                                c_val = cur.get(scenario)
                                p_val = prop.get(scenario)
                                d_val = dlt.get(scenario)
                                col.metric(
                                    f"{scenario.capitalize()} IV",
                                    f"${p_val:,.2f}" if p_val else "—",
                                    delta=f"{d_val:+.1f}%" if d_val is not None else None,
                                )
                        # Restore original recs
                        _wr(recs)
                    else:
                        st.warning("Preview unavailable — valuation inputs could not be assembled.")
                except Exception as e:
                    st.error(f"Preview error: {e}")

        # Apply approved button
        st.subheader("Apply Approved Items")
        approved_count = sum(1 for r in recs.recommendations if r.status == "approved")
        st.caption(f"{approved_count} item(s) currently marked approved.")
        st.info(
            "To approve items, edit the YAML directly:\n"
            f"`config/agent_recommendations_{memo.ticker.upper()}.yaml`\n"
            "Set `status: approved` then click Apply."
        )
        if st.button("Apply Approved to valuation_overrides.yaml", type="primary", key="apply_btn"):
            try:
                from src.stage_04_pipeline.recommendations import apply_approved_to_overrides
                from src.stage_02_valuation.input_assembler import clear_valuation_overrides_cache
                count = apply_approved_to_overrides(memo.ticker)
                clear_valuation_overrides_cache()
                if count:
                    st.success(f"✓ {count} override(s) written to config/valuation_overrides.yaml. Re-run valuation to see updated IV.")
                else:
                    st.warning("No approved items found — nothing written.")
            except Exception as e:
                st.error(f"Apply error: {e}")

if selected_section == "🧪 Assumption Lab":
    st.subheader("Assumption Lab")
    st.caption(
        "Compare current active values, deterministic defaults, and agent suggestions. "
        "Preview the valuation impact, then apply selections into `config/valuation_overrides.yaml`. "
        "Every apply action is also written to SQLite audit history."
    )
    st.caption("Input units: percentages are entered as whole percents, debt/claims in USD millions, multiples in turns, NWC drivers in days.")

    try:
        from src.stage_04_pipeline.override_workbench import (
            apply_override_selections,
            build_override_workbench,
            load_override_audit_history,
            preview_override_selections,
        )

        workbench = build_override_workbench(memo.ticker)
    except Exception as e:
        workbench = None
        st.error(f"Workbench load error: {e}")

    if not workbench or not workbench.get("available"):
        st.info("Assumption lab unavailable for this ticker. Run the analysis first and confirm valuation inputs can be assembled.")
    else:
        head_a, head_b, head_c = st.columns(3)
        head_a.metric("Current Base IV", f"${workbench.get('current_iv_base', 0):,.2f}" if workbench.get("current_iv_base") else "—")
        head_b.metric("Current Price", f"${(workbench.get('current_price') or 0):,.2f}")
        head_c.metric("Tracked Fields", str(len(workbench.get("fields") or [])))

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

            st.markdown(f"**{row['label']}**  ")
            st.caption(f"`{field}`")
            col_a, col_b, col_c, col_d, col_e = st.columns([1.2, 1.2, 1.8, 1.0, 1.1])
            with col_a:
                st.markdown(f"Current: **{_format_value(row.get('effective_value'), row['unit'])}**")
                st.caption(f"Source: {row.get('effective_source') or '—'}")
            with col_b:
                st.markdown(f"Default: **{_format_value(row.get('baseline_value'), row['unit'])}**")
                st.caption(f"Source: {row.get('baseline_source') or '—'}")
            with col_c:
                if row.get("agent_value") is not None:
                    st.markdown(f"Agent: **{_format_value(row.get('agent_value'), row['unit'])}**")
                    st.caption(
                        f"{row.get('agent_name') or 'agent'} | "
                        f"{row.get('agent_confidence') or 'n/a'} | "
                        f"{row.get('agent_status') or 'pending'}"
                    )
                else:
                    st.markdown("Agent: **—**")
                    st.caption("No agent suggestion")
            with col_d:
                mode = st.selectbox(
                    f"{field}_mode",
                    options=options,
                    index=options.index(initial_mode),
                    label_visibility="collapsed",
                    key=f"assump_mode_{memo.ticker}_{field}",
                )
            with col_e:
                default_custom = row.get("effective_value")
                if default_custom is None:
                    default_custom = row.get("baseline_value")
                custom_display = st.number_input(
                    f"{field}_custom",
                    value=float(_to_display_value(default_custom, row["unit"])),
                    step=_input_step(row["unit"]),
                    label_visibility="collapsed",
                    key=f"assump_custom_{memo.ticker}_{field}",
                )
            selections[field] = mode
            custom_values[field] = _from_display_value(custom_display, row["unit"])
            st.divider()

        try:
            preview = preview_override_selections(
                memo.ticker,
                selections=selections,
                custom_values=custom_values,
            )
            st.session_state.workbench_preview = preview
        except Exception as e:
            preview = None
            st.session_state.workbench_preview = None
            st.error(f"Live preview error: {e}")

        if st.button("Apply selections to valuation_overrides.yaml", type="primary", key=f"assump_apply_{memo.ticker}"):
            try:
                apply_result = apply_override_selections(
                    memo.ticker,
                    selections=selections,
                    custom_values=custom_values,
                    actor="dashboard",
                )
                st.session_state.workbench_preview = apply_result.get("preview")
                st.success(
                    f"Applied {apply_result.get('applied_count', 0)} field selection(s) to "
                    "`config/valuation_overrides.yaml` and wrote audit rows to SQLite."
                )
            except Exception as e:
                st.error(f"Apply error: {e}")

        preview = st.session_state.workbench_preview
        if preview:
            st.subheader("Preview Delta")
            prev_cols = st.columns(4)
            for col, key in zip(prev_cols, ["bear", "base", "bull", "expected"]):
                current_value = preview.get("current_iv", {}).get(key) if key != "expected" else preview.get("current_expected_iv")
                proposed_value = preview.get("proposed_iv", {}).get(key) if key != "expected" else preview.get("proposed_expected_iv")
                delta_pct = None
                if key != "expected":
                    delta_pct = preview.get("delta_pct", {}).get(key)
                elif current_value and proposed_value:
                    delta_pct = round((proposed_value / current_value - 1.0) * 100.0, 1)
                col.metric(
                    f"{key.capitalize()} IV",
                    f"${proposed_value:,.2f}" if proposed_value is not None else "—",
                    delta=f"{delta_pct:+.1f}%" if delta_pct is not None else None,
                )

            resolved_rows = []
            for field, meta in (preview.get("resolved_values") or {}).items():
                resolved_rows.append(
                    {
                        "field": field,
                        "mode": meta.get("mode"),
                        "effective_before": meta.get("effective_value"),
                        "applied_value": meta.get("value"),
                    }
                )
            if resolved_rows:
                st.dataframe(resolved_rows, use_container_width=True, hide_index=True)

        st.subheader("Audit History")
        try:
            history = load_override_audit_history(memo.ticker, limit=50)
        except Exception as e:
            history = []
            st.error(f"Audit history error: {e}")

        if history:
            history_rows = [
                {
                    "timestamp": row["event_ts"],
                    "field": row["field"],
                    "mode": row["selection_mode"],
                    "baseline_source": row["baseline_source"],
                    "effective_source_before": row["effective_source_before"],
                    "applied_value": row["applied_value"],
                    "action": row["write_action"],
                    "base_iv_before": row["current_iv_base"],
                    "base_iv_after": row["proposed_iv_base"],
                }
                for row in history
            ]
            st.dataframe(history_rows, use_container_width=True, hide_index=True)
        else:
            st.info("No dashboard override audit events stored yet for this ticker.")

if selected_section == "🔍 Raw JSON":
    st.subheader("Full IC Memo JSON")
    st.download_button(
        label="Download JSON",
        data=memo.model_dump_json(indent=2),
        file_name=f"{memo.ticker}_ic_memo.json",
        mime="application/json",
    )
    st.json(json.loads(memo.model_dump_json()))

st.divider()
with st.expander("Agent Audit Trail", expanded=False):
    st.caption("Exact agent prompts, tool traces, raw outputs, and parsed artifacts for recent runs.")
    try:
        from src.stage_04_pipeline.agent_cache import (
            artifact_has_meaningful_io,
            load_agent_run_artifact,
            load_latest_agent_artifacts_by_ticker,
        )

        audit_rows = load_latest_agent_artifacts_by_ticker(memo.ticker, limit=100)
    except Exception as e:
        audit_rows = []
        st.error(f"Agent artifact load error: {e}")

    if not audit_rows:
        st.info("No stored agent artifacts available yet for this ticker.")
    else:
        agent_options = sorted({row["agent_name"] for row in audit_rows})
        selected_agent = st.selectbox("Agent", options=agent_options, key=f"audit_agent_{memo.ticker}")
        filtered = [row for row in audit_rows if row["agent_name"] == selected_agent]
        run_labels = [
            f"{row['run_ts']} | {row['status']} | {'cache' if row['cache_hit'] else 'exec'} | {row['run_log_id']}"
            for row in filtered
        ]
        selected_label = st.selectbox("Run", options=run_labels, key=f"audit_run_{memo.ticker}_{selected_agent}")
        selected_row = filtered[run_labels.index(selected_label)]
        artifact = load_agent_run_artifact(selected_row["run_log_id"])
        artifact_needs_refresh = not artifact_has_meaningful_io(artifact, selected_agent)

        meta_cols = st.columns(6)
        meta_cols[0].metric("Status", selected_row["status"])
        meta_cols[1].metric("Cache", "yes" if selected_row["cache_hit"] else "no")
        meta_cols[2].metric("Forced Refresh", "yes" if selected_row["forced_refresh"] else "no")
        meta_cols[3].metric("Duration", f"{selected_row['duration_ms']} ms" if selected_row["duration_ms"] is not None else "—")
        meta_cols[4].metric("Model", selected_row["model"] or "—")
        meta_cols[5].metric("Prompt Version", selected_row["prompt_version"] or "—")

        if artifact_needs_refresh:
            st.warning(
                "This looks like a legacy cached run without full prompt/output artifacts. "
                "Refresh the selected agent to store a complete audit payload under the current schema."
            )
            if st.button(
                "Refresh artifact by rerunning this agent",
                key=f"refresh_artifact_{memo.ticker}_{selected_agent}_{selected_row['run_log_id']}",
                use_container_width=True,
            ):
                with st.spinner(f"Refreshing {selected_agent} for {memo.ticker}..."):
                    from src.stage_04_pipeline.orchestrator import PipelineOrchestrator
                    from src.stage_04_pipeline.recommendations import write_recommendations

                    orch = PipelineOrchestrator()
                    refreshed_memo = orch.run(
                        memo.ticker,
                        use_cache=True,
                        force_refresh_agents={selected_agent},
                    )
                    st.session_state.memo = refreshed_memo
                    st.session_state.run_trace = orch.last_run_trace
                    try:
                        recs = orch.collect_recommendations(memo.ticker)
                        write_recommendations(recs)
                        st.session_state.recommendations = recs
                    except Exception:
                        st.session_state.recommendations = None
                st.rerun()

        if artifact is None:
            st.info("No artifact payload stored for this run.")
        else:
            token_cols = st.columns(3)
            token_cols[0].metric("Prompt Tokens", artifact.get("prompt_tokens") or "—")
            token_cols[1].metric("Completion Tokens", artifact.get("completion_tokens") or "—")
            token_cols[2].metric("Total Tokens", artifact.get("total_tokens") or "—")

            no_llm = not artifact.get("user_prompt") and selected_agent == "ValuationAgent"
            if no_llm:
                st.info("No LLM call: deterministic valuation adapter.")

            prompt_tab, user_tab, schema_tab, trace_tab, raw_tab, parsed_tab = st.tabs(
                ["System Prompt", "User Prompt", "Tool Schema", "Tool Trace", "Raw Final Output", "Parsed Output"]
            )
            with prompt_tab:
                st.code(artifact.get("system_prompt") or "—", language="text")
            with user_tab:
                st.code(artifact.get("user_prompt") or "—", language="text")
            with schema_tab:
                if artifact.get("tool_schema_json") is not None:
                    st.json(artifact["tool_schema_json"])
                else:
                    st.write("No tool schema for this run.")
            with trace_tab:
                if artifact.get("api_trace_json"):
                    st.json(artifact["api_trace_json"])
                else:
                    st.write("No tool calls for this run.")
            with raw_tab:
                st.text_area(
                    "raw_output",
                    value=artifact.get("raw_final_output") or "—",
                    height=240,
                    label_visibility="collapsed",
                    key=f"raw_output_{selected_row['run_log_id']}",
                )
            with parsed_tab:
                if artifact.get("parsed_output_json") is not None:
                    st.json(artifact["parsed_output_json"])
                else:
                    st.write("No parsed output stored for this run.")

            st.download_button(
                "Download Artifact JSON",
                data=json.dumps(artifact, indent=2, default=str),
                file_name=f"{memo.ticker}_{selected_agent}_{selected_row['run_log_id']}_artifact.json",
                mime="application/json",
                key=f"artifact_dl_{selected_row['run_log_id']}",
            )
            st.download_button(
                "Download Raw Output",
                data=artifact.get("raw_final_output") or "",
                file_name=f"{memo.ticker}_{selected_agent}_{selected_row['run_log_id']}_raw.txt",
                mime="text/plain",
                key=f"raw_dl_{selected_row['run_log_id']}",
            )
