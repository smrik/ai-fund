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


# ── Run pipeline ──────────────────────────────────────────────────────────────
if run_btn and ticker_input:
    st.session_state.running = True
    st.session_state.memo = None

    with st.status(f"Running 6-agent analysis for **{ticker_input}**...", expanded=True) as status:
        steps = [
            "Fetching market snapshot",
            "FilingsAgent — SEC 10-K / 10-Q",
            "EarningsAgent — earnings call analysis",
            "ValuationAgent — DCF + comps",
            "SentimentAgent — news & analyst positioning",
            "RiskAgent — position sizing",
            "ThesisAgent — IC memo synthesis",
        ]
        placeholders = {s: st.empty() for s in steps}
        for s in steps:
            placeholders[s].markdown(f"⏳ {s}")

        try:
            from src.pipeline.orchestrator import PipelineOrchestrator

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
                    from src.data import market_data as md_client
                    from src.templates.ic_memo import (
                        FilingsSummary, EarningsSummary,
                        ValuationRange, SentimentOutput, RiskOutput, ICMemo,
                    )
                    from config import PORTFOLIO_SIZE_USD, CONVICTION_SIZING

                    ticker = ticker.upper().strip()

                    self._step_ui("Fetching market snapshot")
                    try:
                        mkt = md_client.get_market_data(ticker)
                        company_name = mkt.get("name") or ticker
                        sector = mkt.get("sector") or ""
                        price = mkt.get("current_price") or 0
                        mktcap = mkt.get("market_cap") or 0
                        self._done_ui("Fetching market snapshot", f"${price:,.2f} | Mkt Cap ${mktcap/1e9:.1f}B")
                    except Exception as e:
                        self._done_ui("Fetching market snapshot", f"⚠ {e}")
                        company_name = ticker
                        sector = ""

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

                    self._step_ui("ValuationAgent — DCF + comps")
                    try:
                        valuation = self.valuation_agent.analyze(ticker, filings)
                        upside = (valuation.upside_pct_base or 0) * 100
                        self._done_ui("ValuationAgent — DCF + comps", f"Base ${valuation.base:.0f} | {upside:+.1f}% upside")
                    except Exception as e:
                        p = mkt.get("current_price", 0) if "mkt" in dir() else 0
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
                        )
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
tab_thesis, tab_valuation, tab_filings, tab_earnings, tab_sentiment, tab_risk, tab_raw = st.tabs([
    "📋 Thesis", "💰 Valuation", "📂 Filings", "📞 Earnings", "📰 Sentiment", "⚖️ Risk", "🔍 Raw JSON"
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

with tab_raw:
    st.subheader("Full IC Memo JSON")
    st.download_button(
        label="Download JSON",
        data=memo.model_dump_json(indent=2),
        file_name=f"{memo.ticker}_ic_memo.json",
        mime="application/json",
    )
    st.json(json.loads(memo.model_dump_json()))
