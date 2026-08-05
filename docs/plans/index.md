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

- [Repository Navigation Cleanup](./active/2026-08-05-repository-navigation-cleanup.md) — put the analyst workflow first and explain inputs, templates, saved data, and outputs without moving working files
- [Judgment-Driver Provenance Gate](./active/2026-08-02-judgment-driver-provenance-gate.md) — make every judgment-owned driver explicit and prevent non-judgment provenance from claiming decision-grade status
- [Runtime Model Routing And CIQ Auto-Refresh](./active/2026-08-01-runtime-model-routing-and-ciq-auto-refresh.md) — role-based LLM selection with traced precedence and opt-in guided CIQ Excel refresh outcomes
- [Intrinsic-Value Bridge](./active/2026-08-01-intrinsic-value-bridge.md) — expose Gordon, exit, and blended DCF values together on PM review surfaces without changing valuation math
- [Reconciled, Judgment-Authored Valuation](./active/2026-07-25-reconciled-statement-ledger.md) — complete reconciled statements, exact-once DCF/comps bridge, direct evidence-grounded driver packs, provider-independent replay, and universe-scale execution
- [Weekly Loop v1 (Milestone 1)](./active/2026-06-12-weekly-loop-v1.md) — session runbook, preflight, friction log, full-suite CI, queue-in-anger verification
- [Evidence Acquisition: EDGAR End-To-End And Quartr Transcripts](./active/2026-06-13-evidence-acquisition-edgar-quartr.md) — unblocks 4 of 6 agent profiles; transcript contract with REST/import dual transport
- [Accounting Evidence Packs And Focused Repair](./active/2026-07-11-accounting-evidence-packs-focused-repair.md) — broad classification discovery, focused evidence judgment, semantic repair, durable treatments/model-change requests, and PM-safe queue candidates
- [Quote-Terminal UI Redesign And Streamlit Migration](./active/2026-03-28-quote-terminal-ui-redesign-and-streamlit-stabilization.md) — canonical Streamlit-retirement workstream; full parity push starts with Milestone 2 (Vision Decision 7)

## Future / Queued

- [Valuation Methodology Hardening And CIQ Retrieval Requirements](./future/2026-04-04-spike-review-valuation-inputs-and-ciq-requirements.md) — paused 2026-05; resume when weekly-loop friction demands it
- [Tech Debt Tracker](./future/tech-debt-tracker.md)
- Epic pages: see the [Roadmap Dashboard](./future/2026-04-02-alpha-pod-roadmap-dashboard.md)

## Completed

- [Assumption Register Contract](./completed/2026-05-06-assumption-register-contract.md) — shipped deterministic assumption registry, range/trust metadata, and audit contract; later judgment ownership is governed by Decisions 13–16
- [Codex CLI Judgment Backend](./completed/2026-07-11-codex-cli-judgment-backend.md) — subscription-backed Codex routing with OpenRouter fallback and model provenance
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

## Unfiled (needs triage)

These sit loose in `docs/plans/` rather than in `active/`, `future/`, `completed/`, or `archive/`,
which violates the Canonical Structure rule in AGENTS.md. Registered here 2026-07-24 so they are
at least visible; each still needs to be moved or deleted. Not moved automatically because
choosing the destination is a judgment call about whether the work shipped.

- [React UI Parity](./2026-03-30-react-ui-parity.md) — overlaps the active Quote-Terminal UI workstream; likely `archive/` or fold into that plan
- [Grill Fixes MVP](./2026-05-16-grill-fixes-mvp.md) — status unknown

## Archive

Superseded planning material lives in `docs/plans/archive/`: legacy roadmaps, the XBRL/RAG chatbot plan, and early pipeline/config plans.

- [Judgment-Authored Drivers](./archive/2026-07-25-judgment-authored-drivers.md) — completed the first anchored story-profile slice, then superseded when the PM required direct driver values rather than fixed score coefficients

## Historical Execution Artifacts

For older task trackers, subplan briefs, and execution logs, see [docs/exec-plans/index.md](../exec-plans/index.md).
