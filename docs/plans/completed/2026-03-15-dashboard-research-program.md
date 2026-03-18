# Dashboard Research Surface Remediation and Auditability

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

The repository's checked-in PLANS file is `docs/PLANS.md`. At the time this ExecPlan was written, that file was an index rather than a full guidance document. Repository guidance has since been consolidated, but this file remains the canonical historical record of the work that shipped.

## Purpose / Big Picture

After this change, the PM can open the Streamlit dashboard and do six things that are not fully possible now. First, the dashboard will run cleanly on Streamlit 1.55 without `use_container_width` deprecation noise. Second, visible numbers will read like investment work rather than raw Python output: percentages will render as percentages, negatives will use brackets, and large values will abbreviate cleanly. Third, the Comps surface will become a real workbench where the PM can switch valuation metrics, compare the target directly against peer medians, see a football chart of valuation ranges, and inspect a historical multiples panel for the target stock. Fourth, the Filings Browser will stop being a passive text viewer and will show whether the agents actually saw financial statements, notes to the financial statements, and quarterly notes, along with whether the retrieval system used semantic ranking or a deterministic fallback. Fifth, the Market Intel tab will add a longer-horizon company-event brief above the recent-quarter headline table so that the PM can understand what materially changed over the last few years rather than only the last few days. Sixth, the final product surface will be reviewed explicitly against the repo-local research and financial-analysis skills so that missing analyst workflows become an explicit backlog instead of tribal knowledge.

A human can see this working by starting the dashboard from the repository root with `python -m streamlit run dashboard/app.py --server.headless true --server.port 8503`, opening `http://localhost:8503`, loading IBM, and confirming the new UI behaviors described in `Validation and Acceptance`. An agent can prove it by running the milestone-specific tests, then the live IBM flow, then a browser-level verification pass.

## Progress

- [x] (2026-03-15 12:21Z) Read the current master todo, exec-plan indexes, active dashboard modules, and relevant repo-local skills for planning, comps analysis, competitive analysis, equity research, and EDGAR-oriented filing work.
- [x] (2026-03-15 12:21Z) Created supporting workstream briefs under `docs/exec-plans/` for Streamlit/presentation, comps/multiples, filings diagnostics, market-intel history, formatting, and the final skill-gap review.
- [x] (2026-03-15 12:21Z) Added an active tracker entry and linked the current master todo to the new planning surface.
- [x] (2026-03-15 13:05Z) Milestone 1 implemented: added `src/stage_04_pipeline/presentation_formatting.py`, removed `use_container_width` call sites from `dashboard/app.py`, routed core visible formatting through shared helpers, and verified the formatting/render contract tests.
- [x] (2026-03-15 13:32Z) Milestone 2 implemented: extended `src/stage_00_data/filing_retrieval.py`, `src/stage_04_pipeline/filings_browser.py`, and `src/stage_04_pipeline/news_materiality.py` with filing coverage diagnostics, retrieval observability, and the hybrid-local historical brief; verified the focused filings and market-intel tests.
- [x] (2026-03-15 14:06Z) Milestone 3 implemented: extended comps with metric switching, target-vs-peer deltas, football-field payloads, and target historical multiples in `src/stage_04_pipeline/comps_dashboard.py`, `src/stage_04_pipeline/multiples_dashboard.py`, and `dashboard/app.py`; verified the comps tests plus the live IBM dashboard path.
- [x] (2026-03-15 14:32Z) Milestone 4 implemented: reviewed the repo-local research skills, updated the residual gap log in `docs/exec-plans/completed/2026-03-15-sp06-skill-gap-review-and-research-surface-audit.md`, and added explicit follow-on backlog items to `docs/plans/future/tech-debt-tracker.md`.
- [x] (2026-03-15 14:35Z) Full ExecPlan verification completed: `28 passed` on the plan test bundle, `py_compile` clean on all touched modules, Streamlit launched on port 8503, and Playwright confirmed the IBM Filings Browser diagnostics, Market Intel historical brief, and Comps workbench.

## Surprises & Discoveries

- Observation: `docs/PLANS.md` is an index file, not the full ExecPlan rubric.
  Evidence: opening `docs/PLANS.md` shows active and queued plan tables, not the full authoring rules.

- Observation: the current Market Intel surface is fed only by recent Yahoo Finance news.
  Evidence:
  src/stage_00_data/market_data.py:103:def get_news(ticker: str, limit: int = 15) -> list[dict]:
  src/stage_04_pipeline/news_materiality.py:122: headlines = market_data.get_news(ticker, limit=limit)

- Observation: the current comps helper exposes one `primary_metric` and a comparison payload, but not metric options, football-chart output, or historical multiples.
  Evidence:
  src/stage_04_pipeline/comps_dashboard.py:97: primary_metric = None
  src/stage_04_pipeline/comps_dashboard.py:135: "primary_metric": primary_metric,
  src/stage_04_pipeline/comps_dashboard.py:141: "compare_to_target": \_compare_payload(target, comps_detail.get("medians") or {})

- Observation: the current filings browser exposes agent-used chunks but not statement completeness or retrieval diagnostics.
  Evidence:
  src/stage_04_pipeline/filings_browser.py:102: agent_usage: dict[str, list[dict]] = {}
  src/stage_04_pipeline/filings_browser.py:149: "agent_usage": agent_usage,

- Observation: the dashboard still has many Streamlit 1.55 `use_container_width` call sites.
  Evidence:
  rg -n "use*container_width" dashboard/app.py
  ...
  dashboard/app.py:361: run_btn = st.button("Run Analysis", type="primary", use_container_width=True)
  dashboard/app.py:657: st.plotly_chart(fig, use_container_width=True)
  dashboard/app.py:1770: if st.button("Load Snapshot", key=f"load_snapshot*{selected_snapshot['id']}", use_container_width=True):

- Observation: the historical brief is only as deep as the local report archive, and on IBM the archive window is still shallow and same-day-heavy.
  Evidence:
  Playwright on `http://localhost:8503` showed `Window: 2026-03-15T01:01:23+00:00 -> 2026-03-15T11:41:18+00:00` in the Historical Brief block even though the UI itself rendered correctly.

- Observation: target historical EV-based multiples are stable enough for a chart if market cap is scaled with price and net debt is held constant, which is an approximation rather than a perfect reconstruction.
  Evidence:
  `python -m pytest tests/test_comps_dashboard.py tests/test_multiples_dashboard.py -q`
  `5 passed in 0.77s`

- Observation: the live IBM dashboard path now renders the three new research surfaces without additional navigation bugs.
  Evidence:
  Playwright on `http://localhost:8503` showed:
  `Filings Browser` with `Financial Statements yes` / `Notes yes` / `MD&A yes`
  `News & Materiality` with `Historical Brief` and `Quarterly Materiality`
  `Comps Dashboard` with `Valuation Metric`, `Football Field`, and `Historical Multiples`

## Decision Log

- Decision: The canonical source of truth for this work is this single file, `docs/plans/completed/2026-03-15-dashboard-research-program.md`, while `docs/exec-plans/completed/2026-03-15-master-dashboard-and-research-program.md` is the historical status pointer.
  Rationale: This matches the repository's established pattern in which the active exec-plan points to a full implementation plan in `docs/plans/`, and it satisfies the requirement that one self-contained ExecPlan must be able to restart the work without external memory.
  Date/Author: 2026-03-15 / Codex

- Decision: The longer-horizon Market Intel brief will use a hybrid local evidence set: recent Yahoo Finance headlines, archived report snapshots, and filing-derived material events, but no new external historical news provider.
  Rationale: The repository already has report archive and filing infrastructure, and adding a new historical provider would expand scope and introduce new data risk. The brief must therefore be explicit about its limits.
  Date/Author: 2026-03-15 / Codex

- Decision: Filing completeness and retrieval changes are observability-only in this tranche.
  Rationale: The product problem is that the PM cannot tell what the agents actually saw. The deterministic compute layer must remain untouched; the goal is auditability, not valuation mutation.
  Date/Author: 2026-03-15 / Codex

- Decision: Historical multiples will be target-first in this tranche. Current peer multiples will be shown alongside, but full peer historical bands are deferred unless the target implementation proves data quality is robust.
  Rationale: The user-visible value is primarily understanding whether the target is rich or cheap versus its own history. Full peer historical series are more complex and can be added later without blocking the first useful behavior.
  Date/Author: 2026-03-15 / Codex

- Decision: IBM remains the acceptance ticker for all live verification in this plan.
  Rationale: The current workspace already uses IBM for CIQ-aligned acceptance, which reduces noise while the dashboard surfaces are being expanded.
  Date/Author: 2026-03-15 / Codex

- Decision: The dashboard-level rendering contract for Milestones 2 and 3 will be enforced with source-level tests in `tests/test_dashboard_render_contracts.py` rather than full Streamlit component tests.
  Rationale: `dashboard/app.py` is a script-style Streamlit entrypoint, so source-contract tests are the lowest-risk way to lock in the required payload wiring while the live IBM + Playwright pass handles behavioral verification.
  Date/Author: 2026-03-15 / Codex

- Decision: The first historical-multiples implementation uses target-only historical bands and a deterministic EV approximation that scales equity value with price while holding net debt constant.
  Rationale: This satisfies the user-visible need to compare the stock against its own prior multiple range without inventing unsupported peer history or introducing a new data dependency. The approximation is documented so it can be refined later.
  Date/Author: 2026-03-15 / Codex

- Decision: The residual backlog is being recorded in two places: the canonical SP06 skill-gap review and `docs/plans/future/tech-debt-tracker.md`.
  Rationale: The SP06 document captures reasoning by skill, while the tech-debt tracker keeps the follow-on engineering backlog visible in the same place as existing deterministic system debt.
  Date/Author: 2026-03-15 / Codex

## Outcomes & Retrospective

The full dashboard-research remediation tranche is now implemented. Streamlit 1.55 width deprecations were removed from `dashboard/app.py`, shared formatting helpers now govern the main visible number surfaces, the Filings Browser exposes statement coverage and retrieval diagnostics, Market Intel shows a longer-horizon local historical brief above the quarterly materiality table, and the Comps area now behaves like a real workbench with metric switching, a football field, and target historical multiples. The full plan test bundle passed (`28 passed in 2.13s`), `py_compile` passed on all touched modules, the live IBM pipeline completed, and Playwright verified the new UI surfaces on the running dashboard.

The remaining gaps are no longer hidden. The skill review showed that the next tranche should focus on richer sector/competitive landscape mapping, structured thesis tracking over time, explicit model-integrity checks in the dashboard, and deeper filing-table extraction from structured EDGAR/XBRL data. The current tranche did not attempt those because the user-visible wins here were auditability, formatting, and valuation-surface usability first.

## Context and Orientation

This repository is a fundamental-equity research system with a strict layering rule: data ingestion lives under `src/stage_00_data/`, deterministic valuation and related math live under `src/stage_02_valuation/`, language-model agents live under `src/stage_03_judgment/`, and orchestration plus dashboard-focused helper logic live under `src/stage_04_pipeline/`. The dashboard itself is the Streamlit application in `dashboard/app.py`. It already has grouped navigation and existing tabs for valuation, filings, news, WACC, past reports, and agent audit data.

Several files matter immediately. `dashboard/app.py` is the only Streamlit entrypoint and currently contains many `use_container_width` calls plus an older `_format_value()` helper that does not govern all visible surfaces. `src/stage_04_pipeline/comps_dashboard.py` assembles the current comparable-company view from CIQ peer information, similarity scores, and valuation outputs, but it stops at one primary metric and a simple target comparison. `src/stage_04_pipeline/news_materiality.py` ranks recent headlines, and `src/stage_00_data/market_data.py` provides `get_news`, which means the current Market Intel view is recent-news only. `src/stage_00_data/filing_retrieval.py` already performs notes-first filing retrieval for 10-K and 10-Q text, while `src/stage_04_pipeline/filings_browser.py` displays recent filings, sections, and agent-used chunks. `src/stage_04_pipeline/report_archive.py` stores prior report snapshots and is the only local source that can support a longer-horizon event brief without introducing a new provider.

A few plain-language terms are used throughout this plan. A "football chart" here means a compact visual showing a handful of valuation ranges or point estimates on one horizontal price scale so the PM can compare current price, DCF value, comps values, and optional analyst targets at a glance. "Historical multiples" means showing where the stock's current valuation multiple, such as P/E or EV/EBITDA, sits relative to that stock's own prior trading range over a period like one, three, or five years. A "filing corpus" means the cleaned 10-K and 10-Q text that the EDGAR layer caches plus the sections and chunks extracted from it for agent retrieval. "Materiality" means a ranking of whether a headline or filing event is likely to matter to valuation, thesis, or risk, not just whether it is recent.

The starting point is not a blank slate. The dashboard already runs and the archive, filings browser, WACC lab, and news/comps helpers exist. The problem is that the current surfaces stop short of the PM's actual workflow. The current dashboard still emits deprecation warnings, the current number formatting is inconsistent, the PM cannot see whether the filing retrieval system actually found statements and notes, the market-intel view lacks long-horizon context, and the comps surface does not yet behave like a professional valuation workbench.

## Plan of Work

The work is divided into four milestones, each of which leaves behind an independently useful behavior. Milestone 1 establishes a stable visual and formatting foundation. Create `src/stage_04_pipeline/presentation_formatting.py` as the single place where user-visible numbers are transformed into display strings. Add tests in `tests/test_presentation_formatting.py` and `tests/test_dashboard_render_contracts.py`. Then change `dashboard/app.py` so visible metrics, dataframes, and plots use the shared formatting helpers and replace `use_container_width` with the Streamlit 1.55 `width` argument. The milestone is complete only when the IBM dashboard path runs without the deprecation warnings that are currently emitted from `dashboard/app.py`, and when visible percentages, negatives, and large values follow the house style consistently.

Milestone 2 makes the dashboard auditable in two critical areas: filings and market intel. Extend `src/stage_00_data/filing_retrieval.py` so the filing retrieval path exposes whether the needed filing sections are present. In plain language, that means the code must report whether the financial statements section, notes to the financial statements, management discussion, and quarterly notes were actually found. Extend `src/stage_04_pipeline/filings_browser.py` so the browser view carries that statement-presence data, per-profile selected-chunk counts, skipped sections, and whether the retrieval system fell back because embeddings were unavailable. In parallel, extend `src/stage_04_pipeline/news_materiality.py` so it can build a longer-horizon event timeline by combining archived report snapshots from `src/stage_04_pipeline/report_archive.py`, filing-derived events, and recent news. This milestone is complete when the PM can open the Filings Browser and see if the agents actually had note coverage, and can open Market Intel and see a top-of-page brief summarizing the company's last few years of material changes, with an explicit warning when that history is shallow.

Milestone 3 upgrades the valuation side from a basic comps table into a usable workbench. Extend `src/stage_04_pipeline/comps_dashboard.py` so it exposes multiple valuation metrics, target-vs-peer comparison payloads, and football-field data. Add `src/stage_04_pipeline/multiples_dashboard.py` so the dashboard can compute where the target's current multiples sit relative to one-year, three-year, and five-year ranges using existing market data and current valuation fields. Update `dashboard/app.py` so the Comps area includes a metric selector, a target-versus-peer comparison block, a football chart, and a target historical-multiples view. This milestone is complete when a PM can switch from EV/Revenue to EV/EBITDA or P/E and immediately see the valuation range and supporting comparison context change.

Milestone 4 closes the loop. Review the final surface against the checked-in skills under `skills/financial-analysis/skills/` and `skills/equity-research/skills/`, especially `comps-analysis`, `competitive-analysis`, `check-model`, `dcf-model`, `initiating-coverage`, `model-update`, `earnings-analysis`, `sector-overview`, and `thesis-tracker`. Record what the dashboard now covers well, what remains missing, and whether each remaining gap belongs in the next tranche or a later backlog. This milestone is complete when a new agent can read this plan and the resulting residual gap record and know exactly what the research surface still lacks.

Two small prototypes should be used if uncertainty slows implementation. Before the full filings diagnostics UI is wired, add unit-level tests that simulate a filing with missing notes and confirm the statement-presence output behaves exactly as intended. Before the historical multiples UI is polished, implement a target-only multiples helper and run it for IBM to prove the data series are stable enough to support a human-readable chart or percentile table. If either prototype fails, document the failure in `Surprises & Discoveries` and adapt the plan rather than quietly forcing a broken implementation through.

## Concrete Steps

Work from the repository root, `C:\Projects\03-Finance\ai-fund`.

Begin every milestone by re-reading this file and updating `Progress` before touching code. Then inspect the relevant baseline so the changes are grounded in the current state. For Milestone 1, run:

    rg -n "use_container_width" dashboard/app.py
    rg -n "_format_value|dataframe\(|plotly_chart\(" dashboard/app.py

Write or extend tests before implementing the new formatting helpers. The first focused test pass for Milestone 1 should be:

    python -m pytest tests/test_presentation_formatting.py tests/test_dashboard_render_contracts.py -q

Before the code exists, these tests should fail with import errors or unmet expectations. After implementing `src/stage_04_pipeline/presentation_formatting.py` and wiring `dashboard/app.py`, rerun the same command and expect both test modules to pass. Then compile the touched files:

    python -m py_compile dashboard/app.py src/stage_04_pipeline/presentation_formatting.py

To validate live behavior, start the dashboard on a stable port:

    python -m streamlit run dashboard/app.py --server.headless true --server.port 8503

If port 8503 is already in use, choose a different port and use it consistently in the browser step. Open the browser to the chosen URL, load IBM, and verify that visible percentages look like `10.0%`, negative values use brackets, large numbers abbreviate cleanly, and the server log no longer emits `use_container_width` deprecation warnings from the primary dashboard path.

For Milestone 2, first inspect the current code paths:

    rg -n "statement_presence|retrieval_diagnostics|coverage_summary|agent_usage" src/stage_00_data/filing_retrieval.py src/stage_04_pipeline/filings_browser.py
    rg -n "get_news|historical_brief|quarterly_headlines" src/stage_04_pipeline/news_materiality.py src/stage_00_data/market_data.py src/stage_04_pipeline/report_archive.py

Add and run failing tests:

    python -m pytest tests/test_filing_retrieval_diagnostics.py tests/test_filings_browser_diagnostics.py tests/test_market_intel_history.py -q

After the implementations land, rerun the same tests and expect them to pass, then compile:

    python -m py_compile src/stage_00_data/filing_retrieval.py src/stage_04_pipeline/filings_browser.py src/stage_04_pipeline/news_materiality.py src/stage_00_data/market_data.py dashboard/app.py

Start the dashboard again, open the Filings Browser, and confirm a statement-coverage summary is visible for IBM. Then open Market Intel and confirm a longer-horizon brief appears above the recent-quarter headlines table and that the UI clearly states when the historical brief is based on limited local evidence.

For Milestone 3, inspect the comps baseline:

    rg -n "primary_metric|compare_to_target|metric_options|football|historical_multiples" src/stage_04_pipeline/comps_dashboard.py src/stage_04_pipeline/multiples_dashboard.py

Add and run failing tests:

    python -m pytest tests/test_comps_dashboard.py tests/test_multiples_dashboard.py -q

Implement the payload extensions in `src/stage_04_pipeline/comps_dashboard.py`, create `src/stage_04_pipeline/multiples_dashboard.py`, and wire the new UI surfaces in `dashboard/app.py`. Rerun the tests, compile the touched files, and use the live dashboard to switch metrics and confirm the valuation range and supporting comparison blocks move with the selected metric.

For Milestone 4, re-read the repo-local skill files and write the residual gap record into the plan and supporting backlog docs. Use the repository root and inspect the relevant skills directly:

    Get-Content skills/financial-analysis/skills/comps-analysis/SKILL.md
    Get-Content skills/financial-analysis/skills/competitive-analysis/SKILL.md
    Get-Content skills/financial-analysis/skills/check-model/SKILL.md
    Get-Content skills/financial-analysis/skills/dcf-model/SKILL.md
    Get-Content skills/equity-research/skills/initiating-coverage/SKILL.md
    Get-Content skills/equity-research/skills/model-update/SKILL.md
    Get-Content skills/equity-research/skills/earnings-analysis/SKILL.md
    Get-Content skills/equity-research/skills/sector-overview/SKILL.md
    Get-Content skills/equity-research/skills/thesis-tracker/SKILL.md

At every stopping point, update `Progress`, `Decision Log`, and `Outcomes & Retrospective` before ending the session.

## Validation and Acceptance

Acceptance is behavior-first. Milestone 1 is accepted when the IBM dashboard path runs under Streamlit 1.55, the main dashboard surfaces stop emitting `use_container_width` deprecation warnings, and visible percentages, negatives, and large numbers follow the shared formatting rules. Milestone 2 is accepted when the Filings Browser explicitly shows whether statement and note coverage exists for the underlying filing corpus, when retrieval fallback behavior is visible instead of hidden, and when Market Intel shows a longer-horizon brief above the recent-quarter materiality table. Milestone 3 is accepted when the Comps area includes a metric selector, the target-versus-peer comparison changes with the selected metric, a football chart is visible, and a historical multiples view shows how the target compares to its own prior trading range. Milestone 4 is accepted when the repo-local research skills have been reviewed against the finished surface and the remaining gaps are written down with clear priority.

The minimum verification commands for the full plan, after all milestones are implemented, are:

    python -m pytest tests/test_presentation_formatting.py tests/test_dashboard_render_contracts.py tests/test_filing_retrieval_diagnostics.py tests/test_filings_browser_diagnostics.py tests/test_market_intel_history.py tests/test_comps_dashboard.py tests/test_multiples_dashboard.py -q
    python -m py_compile dashboard/app.py src/stage_04_pipeline/presentation_formatting.py src/stage_00_data/filing_retrieval.py src/stage_04_pipeline/filings_browser.py src/stage_04_pipeline/news_materiality.py src/stage_00_data/market_data.py src/stage_04_pipeline/comps_dashboard.py src/stage_04_pipeline/multiples_dashboard.py
    python -m streamlit run dashboard/app.py --server.headless true --server.port 8503

The human-visible acceptance scenario is: open the dashboard, run IBM, confirm formatting is clean, inspect filing coverage, inspect the historical brief, switch comps metrics, and verify that the historical multiples section is populated or gracefully explains why data is insufficient.

## Idempotence and Recovery

This work should be performed additively and can be repeated safely. The tests named in this plan can be rerun at any time. Starting the Streamlit server repeatedly is safe as long as the port is managed consistently; if a prior instance is still running, stop it or choose another port. The new helper modules in this plan are additive and should not require destructive migrations. If a milestone is interrupted halfway, the safe recovery path is to update `Progress`, inspect `git diff` only for the touched files in that milestone, and rerun the milestone-specific tests before continuing. Do not mass-revert the working tree because this repository is often intentionally dirty with unrelated local files.

## Artifacts and Notes

These short snippets capture the baseline evidence that motivated the plan and should remain useful to the next contributor.

    rg -n "use_container_width" dashboard/app.py
    dashboard/app.py:361:    run_btn = st.button("Run Analysis", type="primary", use_container_width=True)
    dashboard/app.py:657:            st.plotly_chart(fig, use_container_width=True)
    dashboard/app.py:1770:            if st.button("Load Snapshot", key=f"load_snapshot_{selected_snapshot['id']}", use_container_width=True):

    rg -n "get_news|historical_brief|quarterly_headlines" src/stage_04_pipeline/news_materiality.py src/stage_00_data/market_data.py
    src/stage_00_data/market_data.py:103:def get_news(ticker: str, limit: int = 15) -> list[dict]:
    src/stage_04_pipeline/news_materiality.py:122:    headlines = market_data.get_news(ticker, limit=limit)

    rg -n "primary_metric|football|historical_multiples|metric_options|compare_to_target" src/stage_04_pipeline/comps_dashboard.py
    src/stage_04_pipeline/comps_dashboard.py:135:        "primary_metric": primary_metric,
    src/stage_04_pipeline/comps_dashboard.py:141:        "compare_to_target": _compare_payload(target, comps_detail.get("medians") or {})

    rg -n "statement_presence|retrieval_diagnostics|coverage_summary|agent_usage" src/stage_00_data/filing_retrieval.py src/stage_04_pipeline/filings_browser.py
    src/stage_04_pipeline/filings_browser.py:149:        "agent_usage": agent_usage,

## Interfaces and Dependencies

At the end of Milestone 1, `src/stage_04_pipeline/presentation_formatting.py` must expose these stable functions: `format_metric_value(value: float | int | None, *, kind: str, decimals: int | None = None) -> str`, `format_table_value(value: object, *, kind: str | None = None) -> str`, `abbreviate_number(value: float | int | None, *, decimals: int = 1) -> str`, `format_percent(value: float | None, *, input_mode: str = "decimal", decimals: int = 1) -> str`, `format_negative(value: float | int | None, *, style: str = "parentheses") -> str`, and `style_dataframe_rows(rows: list[dict], schema: dict[str, str]) -> list[dict]`. `dashboard/app.py` must use these helpers for primary visible number rendering.

At the end of Milestone 2, `src/stage_00_data/filing_retrieval.py` and/or the browser view it feeds must expose `statement_presence`, `section_coverage`, and `retrieval_diagnostics` payloads, and `src/stage_04_pipeline/filings_browser.py` must return `coverage_summary`, `retrieval_profiles`, `statement_presence_by_filing`, and `agent_usage`. `src/stage_04_pipeline/news_materiality.py` must return `historical_brief`, `quarterly_headlines`, `headlines`, `analyst_snapshot`, `sentiment_summary`, and `audit_flags` in a single dictionary that the dashboard can render without additional business logic.

At the end of Milestone 3, `src/stage_04_pipeline/comps_dashboard.py::build_comps_dashboard_view(ticker: str) -> dict` must return `metric_options`, `selected_metric_default`, `target_vs_peers`, `football_field`, `historical_multiples_summary`, `valuation_range_by_metric`, `peer_counts`, and `audit_flags` in addition to the existing target and peer payloads. `src/stage_04_pipeline/multiples_dashboard.py` must define `build_multiples_dashboard_view(ticker: str, *, period: str = "5y", metrics: tuple[str, ...] = ("pe_trailing", "ev_ebitda", "ev_revenue", "price_to_book")) -> dict` and must degrade gracefully when the underlying data is incomplete.

Revision note, 2026-03-15 / Codex: Replaced the earlier lightweight decomposition doc with a canonical self-contained ExecPlan in `docs/plans/` because the repository's ExecPlan standard requires one living, restartable specification for the main problem rather than a loose collection of planning notes.

Revision note, 2026-03-15 / Codex: Updated the living sections after implementation to record the completed milestones, live IBM verification evidence, the historical-multiples approximation decision, and the post-skill-review residual backlog.
