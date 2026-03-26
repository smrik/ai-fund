# Dashboard And AI Investing Feature Roadmap

This document captures a grounded brainstorming pass over Alpha Pod's next product features. It is not an implementation log. It exists so the best ideas do not get lost in chat and so future implementation plans can start from a coherent product view.

## Purpose

Alpha Pod already has a usable research dashboard. The next gains will not come from adding more tabs for their own sake. They will come from closing the remaining PM workflow gaps: what changed in the thesis, what matters now, what is breaking in the model, what deserves attention across the watchlist, and where the system still lacks structured evidence.

The goal of this roadmap is to prioritize features that improve real investing throughput for a solo PM while respecting the repository's core rule: LLMs can help with judgment, summarization, and ranking, but they do not directly set deterministic valuation outputs.

## Current Strengths

The current product already has more infrastructure than a normal prototype. The dashboard and pipeline now provide:

- deterministic DCF, WACC, and scenario outputs
- DCF audit, IV history, and assumption override workflow
- WACC methodology lab with preview and audit trail
- filings browser with retrieval diagnostics and agent-used chunk provenance
- market-intel tab with recent-news ranking and a local historical brief
- comps workbench with metric switching, football-field view, and target historical multiples
- risk-impact overlays, factor exposure, macro snapshot, revisions, and portfolio-risk analytics
- report archive and agent audit trail

This means the highest-value next features are workflow and evidence features, not generic UI polish.

## Product Principles For Future Features

All future dashboard and model features should follow these rules:

1. A feature must help the PM decide faster, size better, or avoid being wrong.
2. A feature should prefer structured evidence over more narrative when both are possible.
3. A feature should preserve the current data -> computation -> judgment boundary.
4. A feature should make model quality and source quality more visible, not less.
5. A feature should compound over time by creating reusable history, not just a prettier one-off view.

## Highest-Value Features

### 1. Thesis Tracker And Catalyst Calendar

This is the single highest-value gap.

Today the system can generate a memo, a variant-thesis prompt, key catalysts, key risks, revisions, and filing/news summaries. What it does not do is track how that thesis evolves over time. The PM still has to remember whether the original thesis is intact, whether catalysts are on schedule, and whether new evidence supports or weakens the old view.

Build a dedicated surface that records, per ticker:

- original thesis snapshot
- current thesis snapshot
- thesis pillars and whether each is strengthening, unchanged, or breaking
- catalyst list with target date, expected mechanism, and current status
- reason-for-change log tied to filings, earnings, revisions, and risk overlays
- old versus new conviction and stance

This should sit on top of `pipeline_report_archive`, `agent_cache`, revisions, and the existing memo fields. This is more valuable than another narrative agent because it turns research into a living investment process.

### 2. Model Integrity Panel

The dashboard has DCF audit and WACC lab, but it still lacks a single model-integrity view that answers: can I trust this model enough to spend time on it?

Add a panel that surfaces:

- balance-sheet tie checks
- cash-flow tie checks
- terminal value concentration warnings
- sensitivity instability warnings
- assumption quality flags based on source lineage
- fallback/default usage counts
- data staleness for CIQ, yfinance, and filings
- explicit red/yellow/green model confidence score

This would likely live near `dcf_audit.py`, `input_assembler.py`, and the dashboard valuation group. It would materially improve triage quality across a large watchlist.

### 3. Revision Bridge And Expectation Gap Surface

The product currently shows revisions, but not the full expectation bridge that a PM actually needs.

Add a dedicated view that answers:

- what the market expects now
- what changed in estimates over 1 week, 1 month, and 1 quarter
- whether estimate changes are driven by revenue, margin, tax, or capital structure assumptions
- whether the stock move already priced the revision
- whether the DCF base case is above or below the new expectation set

This becomes the bridge between market narrative and valuation. It is one of the cleanest ways to operationalize variant perception without letting LLMs set the model.

### 4. Watchlist Triage / Opportunity Queue

The system is still ticker-centric. A solo PM also needs a cross-sectional control surface.

Build a watchlist queue that ranks ideas by:

- upside versus current price
- quality of evidence
- model confidence
- thesis freshness
- upcoming catalyst proximity
- recent estimate-change magnitude
- risk-overlay severity
- filing/news/event novelty

This should not be a trade signal. It should be a research-priority queue. It is likely the highest leverage dashboard feature for daily use once the underlying surfaces are strong.

### 5. Structured Filing Explorer With Statement Tables

The current filings browser is audit-friendly but still text-first. It needs one more step: a structured browser for statement tables and exhibits.

Add:

- statement table browser for income statement, balance sheet, and cash flow
- note table extraction where possible
- exhibit list and quick open
- section-to-agent provenance mapping
- search scoped to statement tables versus narrative text
- explicit incomplete-parser warnings

This should remain read-only and audit-first. The value is not prettier filings. The value is faster extraction of accounting signals and lower trust risk when using the judgment layer.

### 6. Competitor Taxonomy And Moat Map

The comps tab is now usable, but it still lacks true competitive analysis.

Add:

- peer clusters by business model and end market
- target versus peers on growth, margins, leverage, valuation, and qualitative positioning
- business-description snippets with source lineage
- explicit peer-rationale notes: why this name is in the set
- moat map: where the company is advantaged, neutral, or weak
- competitor event monitor: major peer earnings, guidance cuts, pricing changes, M&A

This would make the comps surface feel like buy-side research instead of just relative valuation.

### 7. PM Decision Journal And Override Review

The system has assumption overrides and audit trails, but not a clean PM journal.

Add a surface that captures:

- manual override applied
- why the override exists
- what evidence justified it
- what would falsify it
- when it should be revisited
- whether the override improved or hurt later outcomes

This compounds learning and keeps human judgment explicit rather than hidden in YAML and memory.

### 8. Position Monitoring Against Thesis

Portfolio risk exists, but thesis-aware position monitoring is still missing.

Add a position monitor that asks:

- which live positions are still on-thesis
- which positions are drifting off-thesis before price confirms it
- which catalyst windows are approaching or missed
- whether factor exposure, revisions, or risk overlays have changed position quality
- which names should move from hold to review now

This is where Alpha Pod starts behaving more like a real PM cockpit than a research notebook.

## Second-Tier Features

These are valuable, but they should follow the highest-value set above.

### 9. Scenario Lab For Named Business Outcomes

The current DCF scenarios are still mostly mechanical. A better scenario lab would let the PM build named operating scenarios such as "AI monetization works", "margin reset", or "pricing war" and map them to deterministic driver changes.

The important constraint is that the scenario translation should be explicit and reviewable. The LLM may help generate candidate scenarios, but the actual DCF driver changes must remain deterministic and visible.

### 10. Evidence Weighting And Source Confidence

Not all evidence should count equally. Add a source-confidence layer that distinguishes:

- reported data
- company guidance
- analyst inference
- recent market narrative
- archived thesis memory
- fallback/default assumptions

This would be useful across filings, market intel, risk overlays, and thesis tracking.

### 11. Short-Side Workflow Support

The current product sense is implicitly long-biased even though the repo describes long/short research. A short workflow would need:

- fraud/accounting screens
- deterioration tracker
- crowded-short or squeeze risk monitor
- downside path decomposition
- bear-case catalyst calendar

This is valuable, but it should follow stronger thesis-tracking and filing-quality infrastructure.

### 12. Research Note Factory

The dashboard can already export reports. A next step is a repeatable note factory with templates for:

- initiating view
- earnings update
- thesis change note
- risk update
- post-mortem

This is operationally helpful, but it should come after the evidence and tracking layers improve.

## Features To Avoid For Now

Avoid these directions unless the core workflow gaps above are already solved.

### Generic Chat-First Productization

Do not turn the dashboard into a general chat app. The EDGAR RAG chat is useful as a utility, but a generic chatbot is not the PM bottleneck.

### More Narrative Agents Before More Structure

The system already produces significant narrative. The next edge comes from structured comparison, tracking, and diagnostics.

### LLM-Controlled Valuation Inputs

Do not let an agent directly rewrite DCF drivers, WACC, or terminal assumptions without deterministic review gates. That would violate the most valuable architecture property in the repo.

### Historical-News Provider Expansion Before Thesis Tracking

A richer news provider could help later, but the product will gain more from a thesis/catalyst memory layer first. Otherwise the system just ingests more information without improving decision quality.

### Pure UI Polish As A Priority

The dashboard already works. Better polish is fine, but it is not the current bottleneck. Analytical workflow quality matters more than visual refinement right now.

## Recommended Build Order

If the goal is maximum PM value per unit of engineering effort, build in this order:

1. Thesis Tracker And Catalyst Calendar
2. Model Integrity Panel
3. Revision Bridge And Expectation Gap Surface
4. Watchlist Triage / Opportunity Queue
5. Structured Filing Explorer With Statement Tables
6. Competitor Taxonomy And Moat Map
7. PM Decision Journal And Override Review
8. Position Monitoring Against Thesis

## Architecture Fit

These features fit the current repository cleanly.

Most of the required data already exists in some form:

- `src/stage_04_pipeline/report_archive.py` for historical memory
- `src/stage_04_pipeline/agent_cache.py` for run artifacts and traces
- `src/stage_04_pipeline/filings_browser.py` and `src/stage_00_data/filing_retrieval.py` for filing evidence and chunk provenance
- `src/stage_04_pipeline/comps_dashboard.py` and `src/stage_04_pipeline/multiples_dashboard.py` for peer analysis
- `src/stage_04_pipeline/news_materiality.py` for recent-market context
- `src/stage_04_pipeline/wacc_workbench.py` and `src/stage_04_pipeline/dcf_audit.py` for model control surfaces
- `src/stage_02_valuation/portfolio_risk.py` and factor/macro modules for monitoring

That means the product is now at the stage where the main challenge is not raw capability. The main challenge is integrating these capabilities into higher-order PM workflows.

## Bottom Line

The next best version of Alpha Pod is not "more AI." It is a system that remembers the thesis, measures what changed, exposes whether the model is trustworthy, and tells the PM where attention is most valuable right now.

If only one feature gets built next, it should be the Thesis Tracker And Catalyst Calendar. That is the clearest path from a clever research dashboard to a real investing operating system.
