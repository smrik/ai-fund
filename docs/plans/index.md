# Plan Registry

This is the canonical planning index for Alpha Pod.

If you need to know what is being built, what shipped, and what is queued, use this file first. All work must serve the settled decisions in [docs/strategy/vision.md](../strategy/vision.md).

## Use This When

- you want to see current active work
- you want the medium-term roadmap
- you want shipped implementation history
- you want to find a canonical plan before changing code

## Rules

- `active/` contains plans that are currently being executed
- `future/` contains backlog, roadmap, and queued plans
- `completed/` contains shipped plans worth keeping as historical implementation records
- `archive/` contains superseded or legacy plans that are no longer canonical
- new plans must name the Vision decision(s) they serve and start interview-first for non-trivial scope

## Roadmap

- [Six-Month Execution Roadmap 2026-06 → 2026-12](./future/2026-06-12-six-month-execution-roadmap.md) — canonical sequencing for the current period
- [Alpha Pod Product Roadmap Dashboard](./future/2026-04-02-alpha-pod-roadmap-dashboard.md) — epic-level backlog beyond the current period

## Active

- [Weekly Loop v1 (Milestone 1)](./active/2026-06-12-weekly-loop-v1.md) — session runbook, preflight, friction log, full-suite CI, queue-in-anger verification
- [Evidence Acquisition: EDGAR End-To-End And Quartr Transcripts](./active/2026-06-13-evidence-acquisition-edgar-quartr.md) — unblocks 4 of 6 agent profiles; transcript contract with REST/import dual transport
- [Quote-Terminal UI Redesign And Streamlit Migration](./active/2026-03-28-quote-terminal-ui-redesign-and-streamlit-stabilization.md) — canonical Streamlit-retirement workstream; full parity push starts with Milestone 2 (Vision Decision 7)

## Future / Queued

- [Valuation Methodology Hardening And CIQ Retrieval Requirements](./future/2026-04-04-spike-review-valuation-inputs-and-ciq-requirements.md) — paused 2026-05; resume when weekly-loop friction demands it
- [Tech Debt Tracker](./future/tech-debt-tracker.md)
- Epic pages: see the [Roadmap Dashboard](./future/2026-04-02-alpha-pod-roadmap-dashboard.md)

## Completed

- [Analyst Prep Pack MVP](./completed/2026-06-07-analyst-prep-pack.md)
- [Agentic Handoff MVP Hardening](./completed/2026-05-22-agentic-handoff-mvp-hardening.md)
- [Internal Release Readiness And Mock Publish](./completed/2026-04-01-internal-release-readiness-and-mock-publish.md)
- [GitHub Hygiene And Repo Hardening](./completed/2026-03-31-github-hygiene-and-repo-hardening.md)
- [Universe Watchlist Landing Page](./completed/2026-03-28-universe-watchlist-landing-page.md)
- [Structured Logging First Tranche](./completed/2026-03-27-structured-logging-first-tranche.md)
- [Dashboard Decomposition And Shell Normalization](./completed/2026-03-26-dashboard-decomposition-and-shell-normalization.md)
- [Universal Agentic Handoff MVP](./completed/2026-05-21-agentic-handoff-mvp.md)
- [Thesis Tracker V2 PM Cockpit](./completed/2026-03-23-thesis-tracker-v2-pm-cockpit.md)
- [Dashboard Shell And Dossier Companion](./completed/2026-03-23-dashboard-shell-and-dossier-companion.md)
- [Deep Dive Dashboard Refactor](./completed/2026-03-21-deep-dive-dashboard-refactor.md)
- [Single Ticker Deep Dive Dossier](./completed/2026-03-18-single-ticker-deep-dive-dossier.md)
- [Dashboard Research Program](./completed/2026-03-15-dashboard-research-program.md)
- [DCF Audit Agent Cache](./completed/2026-03-14-dcf-audit-agent-cache.md)
- [Dashboard Override Workbench](./completed/2026-03-14-dashboard-override-workbench.md)

## Archive

Superseded planning material lives in `docs/plans/archive/`: legacy roadmaps, the XBRL/RAG chatbot plan, and early pipeline/config plans.

## Historical Execution Artifacts

For older task trackers, subplan briefs, and execution logs, see [docs/exec-plans/index.md](../exec-plans/index.md).
