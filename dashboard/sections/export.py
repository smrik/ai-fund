from __future__ import annotations

import json

import streamlit as st

from src.stage_00_data import market_data as md_client
from src.stage_03_judgment.research_note_agent import ResearchNoteAgent, generate_research_note_offline
from src.stage_04_pipeline.agent_cache import (
    artifact_has_meaningful_io,
    load_agent_run_artifact,
    load_latest_agent_artifacts_by_ticker,
)
from src.stage_04_pipeline.orchestrator import PipelineOrchestrator
from src.stage_04_pipeline.report_export import export_research_note_for_download
from src.stage_04_pipeline.recommendations import write_recommendations



def _build_html_report(memo) -> str:
    val = memo.valuation
    price = val.current_price or 0
    upside = (val.upside_pct_base or 0) * 100
    action_col = {"BUY": "#3fb950", "SELL SHORT": "#f85149", "WATCH": "#d29922", "PASS": "#8b949e"}.get(memo.action, "#8b949e")

    flags_html = "".join(f"<li style='color:#f85149'>{item}</li>" for item in (memo.filings.red_flags or []))
    catalysts_html = "".join(f"<li>{item}</li>" for item in memo.key_catalysts)
    risks_html = "".join(f"<li>{item}</li>" for item in memo.key_risks)
    questions_html = "".join(f"<li>{item}</li>" for item in memo.open_questions)
    filings_notes_html = "".join(f"<li>{item}</li>" for item in (memo.filings.notes_watch_items or []))
    risk_overlay_html = "".join(
        f"<li>{overlay.risk_name} — p={overlay.probability:.0%}, Δgrowth {overlay.revenue_growth_near_bps}bps, Δmargin {overlay.ebit_margin_bps}bps, ΔWACC {overlay.wacc_bps}bps</li>"
        for overlay in (memo.risk_impact.overlays or [])
    )
    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset='utf-8'>
<title>{memo.ticker} — IC Memo {memo.date}</title>
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background:#0d1117; color:#e2e8f0; max-width:960px; margin:40px auto; padding:0 24px; }}
h1 {{ color:#f0f6fc; }} h2 {{ color:#388bfd; border-bottom:1px solid #21262d; padding-bottom:8px; margin-top:32px; }} h3 {{ color:#c9d1d9; }}
.badge {{ display:inline-block; padding:4px 12px; border-radius:4px; font-weight:700; font-size:1.1em; color:#fff; background:{action_col}; }}
.metric-grid {{ display:grid; grid-template-columns:repeat(5,1fr); gap:12px; margin:20px 0; }}
.metric {{ background:#161b22; border:1px solid #21262d; border-radius:8px; padding:16px; }}
.metric-label {{ color:#8b949e; font-size:0.75rem; text-transform:uppercase; letter-spacing:0.04em; }}
.metric-value {{ color:#f0f6fc; font-size:1.4rem; font-weight:700; margin-top:4px; }}
.cases {{ display:grid; grid-template-columns:1fr 1fr 1fr; gap:16px; }}
.case {{ background:#161b22; border:1px solid #21262d; border-radius:8px; padding:16px; }}
.one-liner {{ background:#162032; border-left:3px solid #388bfd; padding:12px 16px; border-radius:6px; margin:16px 0; }}
.variant {{ background:#1f1a00; border-left:3px solid #d29922; padding:12px 16px; border-radius:6px; margin:16px 0; }}
table {{ width:100%; border-collapse:collapse; }} td,th {{ border:1px solid #21262d; padding:6px 10px; }}
th {{ background:#161b22; color:#8b949e; font-weight:600; font-size:0.85rem; }}
ul {{ padding-left:24px; }} li {{ margin-bottom:4px; line-height:1.6; }}
</style>
</head>
<body>
<h1><span class='badge'>{memo.action}</span> {memo.ticker} — {memo.company_name}</h1>
<p style='color:#8b949e'>{memo.sector} · {memo.date} · Analyst: {memo.analyst}</p>
<div class='metric-grid'>
  <div class='metric'><div class='metric-label'>Action</div><div class='metric-value'>{memo.action}</div></div>
  <div class='metric'><div class='metric-label'>Conviction</div><div class='metric-value'>{memo.conviction.upper()}</div></div>
  <div class='metric'><div class='metric-label'>Current Price</div><div class='metric-value'>${price:,.2f}</div></div>
  <div class='metric'><div class='metric-label'>Base Case IV</div><div class='metric-value'>${val.base:,.2f}</div></div>
  <div class='metric'><div class='metric-label'>Upside (Base)</div><div class='metric-value'>{upside:+.1f}%</div></div>
</div>
<div class='one-liner'><strong>One-liner:</strong> {memo.one_liner}</div>
<div class='variant'><strong>Variant Thesis:</strong> {memo.variant_thesis_prompt}</div>
<h2>DCF Scenarios</h2>
<table>
<tr><th>Scenario</th><th>Intrinsic Value</th><th>Upside / (Downside)</th></tr>
<tr><td>Bear</td><td>${val.bear:.2f}</td><td>{((val.bear-price)/price*100):+.1f}%</td></tr>
<tr><td>Base</td><td>${val.base:.2f}</td><td>{((val.base-price)/price*100):+.1f}%</td></tr>
<tr><td>Bull</td><td>${val.bull:.2f}</td><td>{((val.bull-price)/price*100):+.1f}%</td></tr>
</table>
<h2>Investment Thesis</h2>
<div class='cases'>
  <div class='case'><h3>Bull Case</h3><p>{memo.bull_case}</p></div>
  <div class='case'><h3>Base Case</h3><p>{memo.base_case}</p></div>
  <div class='case'><h3>Bear Case</h3><p>{memo.bear_case}</p></div>
</div>
<h2>Key Catalysts</h2><ul>{catalysts_html}</ul>
<h2>Key Risks</h2><ul>{risks_html}</ul>
{"<h2>Risk Impact</h2><ul>" + risk_overlay_html + "</ul>" if risk_overlay_html else ""}
{"<h2>Red Flags (Filings)</h2><ul>" + flags_html + "</ul>" if flags_html else ""}
{"<h2>Filing Note Watch Items</h2><ul>" + filings_notes_html + "</ul>" if filings_notes_html else ""}
<h2>Open Questions</h2><ul>{questions_html}</ul>
<h2>Filings Analysis</h2><p>{memo.filings.raw_summary or ''}</p>
<h2>Earnings Analysis</h2><p>{memo.earnings.raw_summary or ''}</p>
<h2>Sentiment</h2><p>{memo.sentiment.raw_summary or ''}</p>
</body>
</html>"""


def render_export(memo) -> None:
    st.subheader("Export")
    st.markdown("#### IC Memo JSON")
    st.download_button(
        label="Download IC Memo JSON",
        data=memo.model_dump_json(indent=2),
        file_name=f"{memo.ticker}_ic_memo_{memo.date}.json",
        mime="application/json",
        key=f"export_json_{memo.ticker}",
    )

    st.markdown("#### HTML Report")
    st.caption("Self-contained HTML file — open in any browser, print to PDF via Ctrl+P.")
    html_report = _build_html_report(memo)
    st.download_button(
        label="Download HTML Report",
        data=html_report,
        file_name=f"{memo.ticker}_ic_memo_{memo.date}.html",
        mime="text/html",
        key=f"export_html_{memo.ticker}",
    )
    with st.expander("Preview HTML", expanded=False):
        st.components.v1.html(html_report, height=600, scrolling=True)

    st.markdown("#### AI Research Note")
    col_note_a, _ = st.columns([1, 3])
    with col_note_a:
        use_offline = st.checkbox("Offline mode (no LLM)", value=False, key=f"note_offline_{memo.ticker}")
    generate_note = st.button("Generate Research Note", type="primary", key=f"generate_note_{memo.ticker}")

    if generate_note:
        with st.spinner("Generating research note..."):
            try:
                macro_ctx = None
                rev_ctx = None
                forensic_ctx = None
                factor_ctx = None
                try:
                    from src.stage_00_data.fred_client import get_regime_indicators
                    macro_ctx = get_regime_indicators()
                except Exception:
                    pass
                try:
                    from src.stage_00_data.estimate_tracker import get_revision_signals
                    import dataclasses
                    rev_sigs = get_revision_signals(memo.ticker)
                    if rev_sigs.available:
                        rev_ctx = dataclasses.asdict(rev_sigs)
                except Exception:
                    pass
                try:
                    from src.stage_03_judgment.forensic_scores import compute_forensic_signals
                    fh = md_client.get_historical_financials(memo.ticker)
                    fm = md_client.get_market_data(memo.ticker)
                    fmcap_mm = (fm.get("market_cap") or 0) / 1e6 or None
                    forensic_ctx = compute_forensic_signals(fh, fmcap_mm, memo.sector)
                except Exception:
                    pass

                memo_dict = memo.model_dump()
                if use_offline:
                    note = generate_research_note_offline(memo_dict, macro_ctx, rev_ctx, forensic_ctx, factor_ctx)
                else:
                    note = ResearchNoteAgent().generate_research_note(memo_dict, macro_ctx, rev_ctx, forensic_ctx, factor_ctx)
                html_content, filename = export_research_note_for_download(note, memo_dict)
                st.download_button(
                    label="Download Research Note (HTML)",
                    data=html_content,
                    file_name=filename,
                    mime="text/html",
                    key=f"research_note_dl_{memo.ticker}",
                )
            except Exception as exc:
                st.error(f"Research note generation failed: {exc}")

    with st.expander("Raw JSON", expanded=False):
        st.json(json.loads(memo.model_dump_json()))


def render_agent_audit(memo, session_state=None) -> None:
    with st.expander("Agent Audit Trail", expanded=False):
        try:
            audit_rows = load_latest_agent_artifacts_by_ticker(memo.ticker, limit=100)
        except Exception as exc:
            audit_rows = []
            st.error(f"Agent artifact load error: {exc}")
        if not audit_rows:
            st.info("No stored agent artifacts available yet for this ticker.")
            return

        agent_options = sorted({row["agent_name"] for row in audit_rows})
        selected_agent = st.selectbox("Agent", options=agent_options, key=f"audit_agent_{memo.ticker}")
        filtered = [row for row in audit_rows if row["agent_name"] == selected_agent]
        run_labels = [f"{row['run_ts']} | {row['status']} | {'cache' if row['cache_hit'] else 'exec'} | {row['run_log_id']}" for row in filtered]
        selected_label = st.selectbox("Run", options=run_labels, key=f"audit_run_{memo.ticker}_{selected_agent}")
        selected_row = filtered[run_labels.index(selected_label)]
        artifact = load_agent_run_artifact(selected_row["run_log_id"])
        artifact_needs_refresh = not artifact_has_meaningful_io(artifact, selected_agent)

        if artifact_needs_refresh and st.button(
            "Refresh artifact by rerunning this agent",
            key=f"refresh_artifact_{memo.ticker}_{selected_agent}_{selected_row['run_log_id']}",
            width="stretch",
        ):
            with st.spinner(f"Refreshing {selected_agent} for {memo.ticker}..."):
                orch = PipelineOrchestrator()
                refreshed_memo = orch.run(memo.ticker, use_cache=True, force_refresh_agents={selected_agent})
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
            return

        token_cols = st.columns(3)
        token_cols[0].metric("Prompt Tokens", artifact.get("prompt_tokens") or "—")
        token_cols[1].metric("Completion Tokens", artifact.get("completion_tokens") or "—")
        token_cols[2].metric("Total Tokens", artifact.get("total_tokens") or "—")

        agent_artifact_view = st.selectbox(
            "Artifact View",
            ["System Prompt", "User Prompt", "Tool Schema", "Tool Trace", "Raw Output", "Parsed Output"],
            key=f"agent_artifact_view_{selected_row['run_log_id']}",
        )
        if agent_artifact_view == "System Prompt":
            st.code(artifact.get("system_prompt") or "—", language="text")
        elif agent_artifact_view == "User Prompt":
            st.code(artifact.get("user_prompt") or "—", language="text")
        elif agent_artifact_view == "Tool Schema":
            st.json(artifact.get("tool_schema_json") or {})
        elif agent_artifact_view == "Tool Trace":
            st.json(artifact.get("api_trace_json") or {})
        elif agent_artifact_view == "Raw Output":
            st.text_area("raw_output", value=artifact.get("raw_final_output") or "—", height=240, label_visibility="collapsed", key=f"raw_output_{selected_row['run_log_id']}")
        else:
            st.json(artifact.get("parsed_output_json") or {})


def render(memo, session_state=None) -> None:
    render_export(memo)
    render_agent_audit(memo, session_state=session_state)
