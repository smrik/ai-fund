# Dashboard Research Surface Remediation and Auditability

**Status:** VERIFIED
**Started:** 2026-03-15
**Goal:** Remove Streamlit 1.55 dashboard warnings, standardize number formatting, make filing coverage auditable, add a longer-horizon Market Intel brief, and turn comps into a metric-switching workbench with historical multiples.
**Done when:** The IBM dashboard path runs cleanly under Streamlit 1.55, visible numbers are consistently formatted, Filings Browser exposes statement/retrieval diagnostics, Market Intel shows a multi-year brief plus recent-quarter materiality, Comps supports metric switching plus football-chart and historical-multiples views, and the final surface has been checked against repo-local research skills.

## Full Implementation Plan

See [docs/plans/2026-03-15-dashboard-research-program.md](../../plans/2026-03-15-dashboard-research-program.md).

## Tasks

- [x] Task 0.1 — Decompose the 2026-03-15 master todo and create the canonical ExecPlan.
- [x] Task 1.1 — Implement Streamlit 1.55 width migration and shared presentation formatting.
- [x] Task 2.1 — Add filing completeness and retrieval diagnostics.
- [x] Task 2.2 — Add Market Intel long-horizon company-event brief.
- [x] Task 3.1 — Expand Comps with metric switching, football-field output, and historical multiples.
- [x] Task 4.1 — Perform final skill-gap audit and residual backlog update.

## Decision Log

- 2026-03-15: The canonical source of truth for this program is the ExecPlan in `docs/plans/2026-03-15-dashboard-research-program.md`; this active file is the status pointer.
- 2026-03-15: IBM remains the live acceptance ticker for this program.
- 2026-03-15: Verification closed with `28 passed` on the ExecPlan test bundle plus live Streamlit and Playwright validation on IBM.
