"""
Streamlit dashboard — AI Hedge Fund Research Pod.
Run: streamlit run dashboard/app.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import json
import streamlit as st

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

    ticker_input = st.text_input(
        "Ticker",
        placeholder="e.g. AAPL, MSFT, NVDA",
        help="US-listed tickers only (SEC EDGAR required)",
    ).upper().strip()

    run_btn = st.button("Run Analysis", type="primary", use_container_width=True)

    st.divider()
    st.caption("**Pipeline:** FilingsAgent → EarningsAgent → ValuationAgent → SentimentAgent → RiskAgent → ThesisAgent")
    st.caption("**Data:** SEC EDGAR (free) + yfinance")
    st.caption("**Model:** claude-opus-4-6 + adaptive thinking")


# ── Session state ─────────────────────────────────────────────────────────────
if "memo" not in st.session_state:
    st.session_state.memo = None
if "running" not in st.session_state:
    st.session_state.running = False
if "recommendations" not in st.session_state:
    st.session_state.recommendations = None


# ── Run pipeline ──────────────────────────────────────────────────────────────
if run_btn and ticker_input:
    st.session_state.running = True
    st.session_state.memo = None
    st.session_state.recommendations = None

    with st.status(f"Running 9-agent analysis for **{ticker_input}**...", expanded=True) as status:
        steps = [
            "Fetching market snapshot",
            "IndustryAgent — sector benchmarks",
            "FilingsAgent — SEC 10-K / 10-Q",
            "EarningsAgent — earnings call analysis",
            "QoEAgent — quality of earnings",
            "AccountingRecastAgent — recast proposals",
            "ValuationAgent — DCF + comps",
            "SentimentAgent — news & analyst positioning",
            "RiskAgent — position sizing",
            "ThesisAgent — IC memo synthesis",
        ]
        placeholders = {s: st.empty() for s in steps}
        for s in steps:
            placeholders[s].markdown(f"⏳ {s}")

        try:
            from src.stage_04_pipeline.orchestrator import PipelineOrchestrator

            class StreamingOrchestrator(PipelineOrchestrator):
                """Orchestrator that updates Streamlit status as it runs."""

                def _step_ui(self, step_name: str):
                    placeholders[step_name].markdown(f"🔄 **{step_name}**")

                def _done_ui(self, step_name: str, detail: str = ""):
                    msg = f"✅ {step_name}"
                    if detail:
                        msg += f" — {detail}"
                    placeholders[step_name].markdown(msg)

                def run(self, ticker: str):
                    from src.stage_00_data import market_data as md_client
                    from src.stage_02_valuation.templates.ic_memo import (
                        FilingsSummary, EarningsSummary,
                        ValuationRange, SentimentOutput, RiskOutput, ICMemo,
                    )
                    from src.stage_03_judgment.accounting_recast_agent import build_accounting_recast_context
                    from config import PORTFOLIO_SIZE_USD, CONVICTION_SIZING

                    ticker = ticker.upper().strip()

                    self._step_ui("Fetching market snapshot")
                    mkt = {}
                    try:
                        mkt = md_client.get_market_data(ticker)
                        company_name = mkt.get("name") or ticker
                        sector = mkt.get("sector") or ""
                        industry = mkt.get("industry") or ""
                        price = mkt.get("current_price") or 0
                        mktcap = mkt.get("market_cap") or 0
                        self._done_ui("Fetching market snapshot", f"${price:,.2f} | Mkt Cap ${mktcap/1e9:.1f}B")
                    except Exception as e:
                        self._done_ui("Fetching market snapshot", f"⚠ {e}")
                        company_name = ticker
                        sector = ""
                        industry = ""

                    self._step_ui("IndustryAgent — sector benchmarks")
                    industry_context = ""
                    if sector:
                        try:
                            ind_result = self.industry_agent.research(sector, industry or sector)
                            self.last_industry_result = ind_result
                            ind_events = self.industry_agent.get_recent_events(ticker, sector)
                            g = ind_result.get("consensus_growth_near", 0) or 0
                            m = ind_result.get("margin_benchmark", 0) or 0
                            self._done_ui("IndustryAgent — sector benchmarks", f"Growth {g*100:.1f}% | Margin bm {m*100:.1f}%")
                            events_list = ind_events.get("recent_events") or []
                            tailwinds = ind_events.get("sector_tailwinds") or []
                            headwinds = ind_events.get("sector_headwinds") or []
                            industry_context = (
                                f"Sector: {sector} | Industry: {industry or sector}\n"
                                f"Consensus growth (near/mid): {g*100:.1f}% / "
                                f"{(ind_result.get('consensus_growth_mid') or 0)*100:.1f}%"
                                f" | Margin benchmark: {m*100:.1f}%\n"
                            )
                            if events_list:
                                industry_context += "Recent events:\n" + "\n".join(f"  • {e}" for e in events_list[:6]) + "\n"
                            if tailwinds:
                                industry_context += "Tailwinds: " + "; ".join(tailwinds[:3]) + "\n"
                            if headwinds:
                                industry_context += "Headwinds: " + "; ".join(headwinds[:3]) + "\n"
                        except Exception as e:
                            self._done_ui("IndustryAgent — sector benchmarks", f"⚠ {e}")
                    else:
                        self._done_ui("IndustryAgent — sector benchmarks", "⚠ Sector unknown — skipped")

                    self._step_ui("FilingsAgent — SEC 10-K / 10-Q")
                    try:
                        filings = self.filings_agent.analyze(ticker)
                        self._done_ui("FilingsAgent — SEC 10-K / 10-Q", f"{filings.revenue_trend} revenue | {len(filings.red_flags)} flags")
                    except Exception as e:
                        filings = FilingsSummary(raw_summary=f"Error: {e}")
                        self._done_ui("FilingsAgent — SEC 10-K / 10-Q", f"⚠ {e}")

                    self._step_ui("EarningsAgent — earnings call analysis")
                    try:
                        earnings = self.earnings_agent.analyze(ticker, filings.raw_summary)
                        self._done_ui("EarningsAgent — earnings call analysis", f"{earnings.guidance_trend} guidance | {earnings.management_tone} tone")
                    except Exception as e:
                        earnings = EarningsSummary(raw_summary=f"Error: {e}")
                        self._done_ui("EarningsAgent — earnings call analysis", f"⚠ {e}")

                    self._step_ui("QoEAgent — quality of earnings")
                    qoe_context = ""
                    reported_ebit = float(mkt.get("ebitda_ttm") or 0) * 0.85
                    try:
                        hist = md_client.get_historical_financials(ticker)
                        op_income = hist.get("operating_income") or []
                        reported_ebit = float(op_income[0]) if op_income else reported_ebit
                        qoe_result = self.qoe_agent.analyze(ticker=ticker, reported_ebit=reported_ebit)
                        self.last_qoe_result = qoe_result
                        qoe_score = qoe_result.get("qoe_score")
                        qoe_flag = qoe_result.get("qoe_flag", "")
                        llm_b = qoe_result.get("llm") or {}
                        haircut = llm_b.get("ebit_haircut_pct")
                        haircut_str = f" | Haircut {haircut:+.1f}%" if haircut is not None else ""
                        self._done_ui("QoEAgent — quality of earnings", f"Score {qoe_score}/5 ({qoe_flag}){haircut_str}")
                        det = qoe_result.get("deterministic") or {}
                        flags = [f"{k}: {v}" for k, v in (det.get("signal_scores") or {}).items() if v in ("amber", "red")]
                        qoe_context = f"QoE score: {qoe_score}/5 ({qoe_flag})\n"
                        if flags:
                            qoe_context += "Flagged: " + ", ".join(flags) + "\n"
                        if haircut is not None:
                            qoe_context += f"EBIT haircut: {haircut:+.1f}%\n"
                    except Exception as e:
                        self._done_ui("QoEAgent — quality of earnings", f"⚠ {e}")

                    self._step_ui("AccountingRecastAgent — recast proposals")
                    accounting_recast_context = ""
                    try:
                        ar_result = self.accounting_recast_agent.analyze(ticker=ticker, reported_ebit=reported_ebit)
                        self.last_accounting_recast_result = ar_result
                        confidence = ar_result.get("confidence", "low")
                        n_adj = len(ar_result.get("income_statement_adjustments") or [])
                        n_rcl = len(ar_result.get("balance_sheet_reclassifications") or [])
                        self._done_ui("AccountingRecastAgent — recast proposals", f"{confidence} confidence | {n_adj} adj | {n_rcl} reclasses")
                        accounting_recast_context = build_accounting_recast_context(ar_result)
                    except Exception as e:
                        ar_result = {}
                        self._done_ui("AccountingRecastAgent — recast proposals", f"⚠ {e}")

                    self._step_ui("ValuationAgent — DCF + comps")
                    try:
                        valuation = self.valuation_agent.analyze(ticker, filings)
                        upside = (valuation.upside_pct_base or 0) * 100
                        self._done_ui("ValuationAgent — DCF + comps", f"Base ${valuation.base:.0f} | {upside:+.1f}% upside")
                    except Exception as e:
                        p = mkt.get("current_price", 0) if mkt else 0
                        valuation = ValuationRange(bear=p * 0.7, base=p, bull=p * 1.3, current_price=p)
                        self._done_ui("ValuationAgent — DCF + comps", f"⚠ {e}")

                    self._step_ui("SentimentAgent — news & analyst positioning")
                    try:
                        sentiment = self.sentiment_agent.analyze(ticker)
                        self._done_ui("SentimentAgent — news & analyst positioning", f"{sentiment.direction} | score {sentiment.score:+.2f}")
                    except Exception as e:
                        sentiment = SentimentOutput(raw_summary=f"Error: {e}")
                        self._done_ui("SentimentAgent — news & analyst positioning", f"⚠ {e}")

                    self._step_ui("RiskAgent — position sizing")
                    try:
                        risk = self.risk_agent.analyze(ticker, valuation, sentiment)
                        self._done_ui("RiskAgent — position sizing", f"{risk.conviction.upper()} | ${risk.position_size_usd:,.0f} ({risk.position_pct*100:.1f}%)")
                    except Exception as e:
                        risk = RiskOutput(
                            conviction="low",
                            position_size_usd=PORTFOLIO_SIZE_USD * CONVICTION_SIZING["low"],
                            position_pct=CONVICTION_SIZING["low"],
                            suggested_stop_loss_pct=0.20,
                            rationale=f"Error: {e}",
                        )
                        self._done_ui("RiskAgent — position sizing", f"⚠ {e}")

                    self._step_ui("ThesisAgent — IC memo synthesis")
                    try:
                        memo = self.thesis_agent.synthesize(
                            ticker=ticker,
                            company_name=company_name,
                            sector=sector,
                            filings=filings,
                            earnings=earnings,
                            valuation=valuation,
                            sentiment=sentiment,
                            risk=risk,
                            qoe_context=qoe_context,
                            industry_context=industry_context,
                            accounting_recast_context=accounting_recast_context,
                        )
                        memo.accounting_recast = ar_result
                        self._done_ui("ThesisAgent — IC memo synthesis", f"{memo.action} | {memo.conviction.upper()}")
                    except Exception as e:
                        memo = ICMemo(
                            ticker=ticker, company_name=company_name, sector=sector,
                            filings=filings, earnings=earnings, valuation=valuation,
                            sentiment=sentiment, risk=risk,
                            action="WATCH", conviction="low",
                            one_liner=f"Analysis incomplete: {e}",
                            variant_thesis_prompt="Review agent outputs manually.",
                        )
                        self._done_ui("ThesisAgent — IC memo synthesis", f"⚠ {e}")

                    return memo

            orch = StreamingOrchestrator()
            memo = orch.run(ticker_input)
            st.session_state.memo = memo
            # Collect and persist recommendations
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


# ── Display results ────────────────────────────────────────────────────────────
memo = st.session_state.memo

if memo is None:
    st.markdown("""
## How to use

1. Enter a **US-listed ticker** in the sidebar (e.g. `AAPL`, `MSFT`, `NVDA`)
2. Click **Run Analysis**
3. The pipeline runs 6 specialized Claude agents in sequence (~3-5 min)
4. Review all intermediate outputs — **you are the human-in-the-loop**
5. Use the Variant Thesis Prompt as your starting point for the investment decision

### The 6-Agent Pipeline

| Agent | Job |
|---|---|
| **FilingsAgent** | Parses 10-K/10-Q, extracts revenue trends, margins, FCF, red flags |
| **EarningsAgent** | Analyses earnings calls, guidance vs actuals, management tone |
| **ValuationAgent** | Runs DCF + comps, produces bear/base/bull intrinsic value |
| **SentimentAgent** | Scores news narrative, analyst positioning |
| **RiskAgent** | Sizes position based on conviction + volatility |
| **ThesisAgent** | Synthesizes IC memo — forces a decision |

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

# ── Tabs ───────────────────────────────────────────────────────────────────────
tab_thesis, tab_valuation, tab_filings, tab_earnings, tab_sentiment, tab_risk, tab_recs, tab_raw = st.tabs([
    "📋 Thesis", "💰 Valuation", "📂 Filings", "📞 Earnings", "📰 Sentiment", "⚖️ Risk", "🔧 Recommendations", "🔍 Raw JSON"
])

with tab_thesis:
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

with tab_valuation:
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

with tab_filings:
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

with tab_earnings:
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

with tab_sentiment:
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

with tab_risk:
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

with tab_recs:
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

        agent_labels = {"qoe": "🔍 Quality of Earnings", "accounting_recast": "📊 Accounting Recast", "industry": "🏭 Industry"}
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

with tab_raw:
    st.subheader("Full IC Memo JSON")
    st.download_button(
        label="Download JSON",
        data=memo.model_dump_json(indent=2),
        file_name=f"{memo.ticker}_ic_memo.json",
        mime="application/json",
    )
    st.json(json.loads(memo.model_dump_json()))
