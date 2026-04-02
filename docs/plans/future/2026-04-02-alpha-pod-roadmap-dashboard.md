# Alpha Pod Product Roadmap Dashboard

| Field | Value |
|---|---|
| Status | Current future roadmap |
| Priority | Portfolio-level guidance |
| Horizon | 6-12 months |
| Last updated | 2026-04-02 |
| GitHub | Mirror epic issues and milestone work here once opened |

This is the main planning dashboard for Alpha Pod. Use it to answer three questions quickly:

1. What are we building now?
2. What comes next?
3. Which short epic page explains the why and the acceptance bar?

The linked epic pages are the human-readable backlog. Detailed implementation plans belong in `docs/plans/active/` only after work starts.

## Now

| Priority | Epic | Why now | Target release |
|---|---|---|---|
| P0 | [Canonical Ticker Dossier And Export Integrity](./2026-04-02-epic-canonical-ticker-dossier-and-export-integrity.md) | Everything else depends on a trustworthy, reusable ticker payload | v0.2.0 |
| P0 | [Platform Reliability And DevOps](./2026-04-02-epic-platform-reliability-and-devops.md) | Keep the repo safe to change while product scope expands | Cross-cutting |

## Next

| Priority | Epic | Why next | Target release |
|---|---|---|---|
| P1 | [Research Retrieval And RAG Intelligence](./2026-04-02-epic-research-retrieval-and-rag-intelligence.md) | Better filing search and evidence quality compound across research workflows | v0.3.0 |
| P1 | [PM Web Cockpit](./2026-04-02-epic-pm-web-cockpit.md) | The web app should become the best lightweight investing surface | v0.4.0 |

## Later

| Priority | Epic | Why later | Target release |
|---|---|---|---|
| P2 | [Solo PM State And Preferences](./2026-04-02-epic-solo-pm-state-and-preferences.md) | Valuable, but less urgent than model integrity and research evidence | v0.5.0 |

## Releases

| Release | Outcome | Included epics |
|---|---|---|
| v0.2.0 Dossier Integrity | Canonical ticker payload, complete export contract, stronger valuation support data | Dossier and export integrity |
| v0.3.0 Research Intelligence | Filing retrieval, evidence contracts, RAG analysis surfaces | Research retrieval and RAG |
| v0.4.0 PM Web Cockpit | Stronger Overview and route preload/caching | PM web cockpit |
| v0.5.0 Solo PM State | Minimal auth, watchlists, theme, and user defaults | Solo PM state |

## Active Epic Pages

| Epic | Core outcome | Dependency notes |
|---|---|---|
| [Canonical Ticker Dossier And Export Integrity](./2026-04-02-epic-canonical-ticker-dossier-and-export-integrity.md) | One canonical product/export dossier contract | Feeds every UI/export surface |
| [Research Retrieval And RAG Intelligence](./2026-04-02-epic-research-retrieval-and-rag-intelligence.md) | Better filing retrieval plus evidence-backed RAG | Depends on clear corpus storage |
| [PM Web Cockpit](./2026-04-02-epic-pm-web-cockpit.md) | Web-first investor cockpit with fast ticker surfaces | Depends on dossier and cached API payloads |
| [Solo PM State And Preferences](./2026-04-02-epic-solo-pm-state-and-preferences.md) | Persistent watchlists and defaults | Depends on stable web/API surfaces |
| [Platform Reliability And DevOps](./2026-04-02-epic-platform-reliability-and-devops.md) | CI, logging, storage clarity, operator confidence | Cross-cuts every release |

## Dependencies And Watchouts

| Dependency | Why it matters |
|---|---|
| Canonical dossier contract | Prevents API/React/export drift |
| Filing corpus structure | Research quality depends on inspectable retrieval inputs |
| Fast cached ticker payloads | Web UX will feel slow without them |
| CI and docs discipline | Roadmap complexity rises quickly without guardrails |

## Working Rules

- This page is the scan-first roadmap, not an implementation journal.
- Each epic page should stay short and outcome-focused.
- Only active work gets a detailed implementation plan under `docs/plans/active/`.
- GitHub issues and PRs should link back here instead of duplicating full specs.
- Use [Tech Debt Tracker](./tech-debt-tracker.md) for rolling defects and debt, not for roadmap-level product direction.

## Historical Context

Older future-roadmap brainstorming docs have been archived because this dashboard now serves as the canonical future-planning entry point.
