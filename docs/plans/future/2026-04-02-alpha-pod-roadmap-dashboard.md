# Alpha Pod Product Roadmap Dashboard

| Field | Value |
| --- | --- |
| Status | Epic-level backlog beyond the current 6-month period |
| Priority | Portfolio-level guidance |
| Horizon | Beyond 2026-12 |
| Last updated | 2026-06-12 |
| Governing docs | [Vision](../../strategy/vision.md), [Six-Month Execution Roadmap](./2026-06-12-six-month-execution-roadmap.md) |

The current period (2026-06 → 2026-12) is sequenced in the [Six-Month Execution Roadmap](./2026-06-12-six-month-execution-roadmap.md); that document outranks this one for "what now". This page keeps the epic backlog for what comes after, filtered through the Vision's settled decisions.

## Now (owned by the Six-Month Roadmap)

| Milestone | Outcome |
| --- | --- |
| M0 Consolidate | `main` is truth, Streamlit frozen, environment boring |
| M1 Weekly loop v1 | PM runs the real loop weekly; handoff hardening done |
| M2 One surface | React parity for loop-critical views; Streamlit deleted |
| M3 Autonomy v0 | Event-driven overnight runs with loud failure visibility |
| M4 Review | Hardening, data checkpoint, next roadmap |

## Later (post 2026-12, gated on the Six-Month Roadmap succeeding)

| Priority | Epic | Vision gate |
| --- | --- | --- |
| P1 | IBKR read-only monitoring + thesis/risk alerts (Phase D entry) | Decision 6; gated on M1-M3 exit criteria |
| P1 | [Canonical Ticker Dossier And Export Integrity](./2026-04-02-epic-canonical-ticker-dossier-and-export-integrity.md) | Serves loop quality; pull forward only if weekly-loop friction demands it |
| P2 | Track-record / calibration layer | Decision 8; waits for real positions |
| P2 | [Research Retrieval And RAG Intelligence](./2026-04-02-epic-research-retrieval-and-rag-intelligence.md) | Deferred; not in the current six months |
| P2 | [PM Web Cockpit](./2026-04-02-epic-pm-web-cockpit.md) | Largely absorbed by M2 one-surface work; revisit remainder after |
| P3 | [Solo PM State And Preferences](./2026-04-02-epic-solo-pm-state-and-preferences.md) | Decision 7-adjacent polish |
| P3 | [Platform Reliability And DevOps](./2026-04-02-epic-platform-reliability-and-devops.md) | Cross-cutting; tranches scheduled inside milestones |

The pre-vision release ladder (v0.2.0 Dossier → v0.5.0 Solo PM State) is superseded; release targets are now set per-milestone in the Six-Month Execution Roadmap and re-derived for the epics above when they activate.

## Working Rules

- This page is the scan-first roadmap, not an implementation journal.
- Each epic page should stay short and outcome-focused.
- Only active work gets a detailed implementation plan under `docs/plans/active/`.
- GitHub issues and PRs should link back here instead of duplicating full specs.
- Use [Tech Debt Tracker](./tech-debt-tracker.md) for rolling defects and debt, not for roadmap-level product direction.

## Historical Context

Older future-roadmap brainstorming docs have been archived because this dashboard now serves as the canonical future-planning entry point.
