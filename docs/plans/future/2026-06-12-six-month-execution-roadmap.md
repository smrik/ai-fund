# Six-Month Execution Roadmap (2026-06 → 2026-12)

| Field | Value |
| --- | --- |
| Status | Canonical 6-month roadmap |
| Derived from | [Vision](../../strategy/vision.md) (PM interview 2026-06-12) |
| Governing outcome | Vision Decision 12: the weekly loop runs for real |
| Last updated | 2026-06-12 |

This is the detailed sequencing of the next six months. Each milestone has exit criteria the PM can verify by using the system, not by reading code. Detailed implementation plans are written per-milestone in `docs/plans/active/` only when work starts, via the interview-first workflow (Vision Decision 10).

## Operating Rule For The Whole Period

**Real usage outranks feature work.** From Milestone 1 onward, the PM runs the weekly loop every week. Friction found in a real session is the top of the backlog; speculative features wait. If a week's session doesn't happen, the next session's first item is understanding why.

## Milestone 0 — Consolidate (now → end of June)

Make `main` the truth and the environment boring before pushing product outcomes.

| Item | Detail |
| --- | --- |
| Merge `codex/mvp` | Analyst Prep Pack + handoff work lands on `main`; stale branches pruned or closed |
| Streamlit freeze declared | `dashboard/` is bugfix-only effective immediately (Vision Decision 7); no new Streamlit features in any plan |
| Environment drift fixed | One pinned interpreter for agent sessions (`rtk python` must resolve to the `ai-fund` env), ruff installed, pre-commit working without workarounds |
| Plan hygiene | Registry matches disk; shipped plans in `completed/` (done 2026-06-12) |

**Exit criteria:** `main` is green in CI, matches `origin/main`, and contains the Analyst Prep MVP. A fresh agent session can run the full test gate without environment surprises.

## Milestone 1 — Weekly Loop v1, PM-Driven (July)

The loop runs end-to-end with the PM pressing the buttons. Goal is proving the workflow, not automating it yet.

| Item | Detail |
| --- | --- |
| Weekly ritual | Screen → batch valuation → pick 1-2 names → Analyst Prep Pack → evidence → queue → decisions → exported note. Every week, real tickers |
| Friction log | Each session logs friction in a running note (`docs/reviews/`); top friction items become the next week's fixes |
| Finish handoff hardening | ✅ Shipped 2026-06-12 ([Agentic Handoff MVP Hardening](../completed/2026-05-22-agentic-handoff-mvp-hardening.md)): no synthetic evidence, visible agent failures, delta/target preview-approve parity. M1 execution continues in [Weekly Loop v1](../active/2026-06-12-weekly-loop-v1.md) |
| Queue workflow in anger | PM-Edited Proposals, Advisory Findings, and Assumption Change Packs exercised on real names, not fixtures |

**Exit criteria:** Four consecutive weekly sessions completed. One full ticker investigation fits in ≤1 PM-hour. Every manual-data-surgery incident is logged and has a fix or a ticket.

## Milestone 2 — React Parity And Streamlit Retirement (July → September)

One surface. Parity is defined by what the real loop uses, not by Streamlit's feature list.

| Item | Detail |
| --- | --- |
| Parity checklist | Scoped to loop-critical surfaces only: PM Decision Queue review, watchlist, valuation views, Analyst Prep display, exports. Everything else in Streamlit is presumed dead until a real session misses it |
| React-only sessions | Run the weekly loop in React+FastAPI exclusively; missing pieces go on the parity list |
| Delete Streamlit | After four React-only weekly sessions, delete `dashboard/` (history stays in git); update docs, CI, and AGENTS.md |

**Exit criteria:** `dashboard/` is deleted from `main`. The weekly loop runs entirely in React+FastAPI with no regression in session time.

## Milestone 3 — Event-Driven Autonomy v0 (September → November)

The system starts working overnight so the daily 30-60 minute session becomes review, not triggering (Vision Decisions 2 + 5).

| Item | Detail |
| --- | --- |
| Event detectors | Earnings calendar dates, new EDGAR filings, estimate-revision deltas, and material price moves on watchlist/portfolio names |
| Overnight orchestration | Detected events trigger the matching Agentic Handoff Profiles unattended; results land as Evidence Packets and queue items |
| Morning digest | One surface answering: what ran, what failed, what needs me. Agent failures are loud, never silent (this is a hard requirement) |
| Queue triage | Ranking/triage so event volume fits the daily budget — better ordering, not auto-approval (Vision, Known Tensions) |
| Data freshness gate | Every unattended run records data staleness; stale CIQ data blocks proposal creation rather than producing confident-looking items from old numbers |

**Exit criteria:** For two consecutive weeks, the PM arrives at least three mornings to fresh, real queue items they did not trigger. Zero silent failures: every broken overnight run is visible in the digest.

## Milestone 4 — Hardening And Strategy Review (November → December)

| Item | Detail |
| --- | --- |
| Reliability polish | Fix the breakage patterns three months of real use exposed; golden valuation regression fixtures; test-gate runtime budget (<5 min default gate) |
| Data decision checkpoint | Has manual CIQ refresh actually blocked autonomy? If yes, scope the paid-API migration now (Vision Decision 9's trigger); if no, explicitly defer again |
| Six-month review | Score the period against Vision success criteria; archive this roadmap; write the next one. Expected next step if on track: IBKR read-only monitoring (Phase D entry) |

**Exit criteria:** Next 6-month roadmap exists, written against evidence from ~20 weeks of real sessions.

## What Is Explicitly NOT In These Six Months

- IBKR integration of any kind (Phase D, gated on this period succeeding)
- Calibration/track-record layer (Vision Decision 8 — waits for real positions)
- Autonomous idea sourcing (Vision Decision 5 — idea generation stays human)
- New data sources beyond freshness gating of existing ones
- RAG/retrieval expansion, conversational interface work
- Any new Streamlit feature

## Milestone → Vision Decision Map

| Milestone | Serves decisions |
| --- | --- |
| M0 Consolidate | 7 (UI), platform health prerequisite for all |
| M1 Weekly loop | 12 (loop for real), 10/11 (workflow rules in practice) |
| M2 One surface | 7 (retire Streamlit, React+FastAPI) |
| M3 Autonomy v0 | 2 (cadence), 5 (event-driven runs), known tensions |
| M4 Review | 9 (data checkpoint), sets up 6 (IBKR monitoring) |
