# Quote-Terminal UI Redesign And Streamlit Migration

## Summary

This plan is the canonical workstream for the quote-terminal migration.

The target architecture is:

- `frontend/`
  - React + TypeScript + Vite
  - React Router for client routing
  - TanStack Query for server state
  - TanStack Table for watchlist presentation
- `api/`
  - FastAPI transport layer only
  - may call `src/stage_04_pipeline/`, `src/stage_03_judgment/`, `src/stage_02_valuation/`, `db/`, and `config/`
- existing Python pipeline remains the system of record

The migration is staged. Streamlit remains usable while the React shell is expanded route-by-route.

## Current State

Shipped in this workstream already:

- Streamlit stabilization:
  - watchlist `Open Latest Snapshot` no longer mutates widget-bound state directly
  - non-`Overview` ticker pages use a compact strip instead of the full hero
  - `Valuation` exposes `Summary`, `DCF`, `Comparables`, `Multiples`, `Assumptions`, `WACC`, and `Recommendations`
  - shell styling was simplified away from the older orange-heavy treatment
- backend scaffold:
  - `api/main.py` exposes watchlist, run-status, ticker workspace, overview, valuation, market, research, audit, export, assumptions-apply, deep-analysis, and snapshot-open endpoints
  - export bundles now persist completed artifact metadata for ticker and watchlist flows
- frontend scaffold:
  - `frontend/` provides `/watchlist` plus ticker routes for `overview`, `valuation`, `market`, `research`, and `audit`
  - watchlist refresh and snapshot/deep-analysis triggers use the FastAPI endpoints
  - `/watchlist` now keeps a selected-ticker focus pane instead of forcing immediate navigation on row click
  - `Valuation` now renders distinct `Summary`, `DCF`, `Comparables`, `Multiples`, `Assumptions`, `WACC`, and `Recommendations` panels off the existing payloads
  - `Audit` now acts as the canonical ticker export hub for Excel and HTML, with saved export history and direct downloads
  - `Valuation` and `Research` now expose contextual export shortcuts, and `/watchlist` exposes explicit batch Excel and HTML export actions
  - the sticky ticker strip was slimmed to the core five metrics so route content has room to breathe
  - the repo now has a canonical React route-review harness in `scripts/manual/review_react_route_matrix.py`, with handbook docs for the React runtime and Playwright debugging flow

## Remaining Scope

### 1. Complete route-by-route frontend parity

- deepen `Overview`, `Market`, `Research`, and `Audit` with richer endpoint-backed views
- keep lazy route/query loading so tab changes do not refetch unrelated payloads

### 2. Tighten the watchlist-first operator workflow

- keep `/watchlist` as the canonical landing route in the React shell
- preserve ranking and PM stance metadata from the saved deterministic universe snapshot
- keep the selected-row focus pane as the primary on-page decision surface
- surface manual deep-analysis triggers without auto-running agent work

### 3. Keep Streamlit usable during the migration

- maintain the compact non-`Overview` layout
- keep `Audit -> Batch Funnel` as the no-memo landing surface until the remaining non-export workflows move cleanly into React
- fix regressions in Streamlit if they block validation or PM use
- do not add new export-only UX to Streamlit; React owns that surface now

### 4. Document the dual-surface transition

- keep `AGENTS.md`, `docs/PLANS.md`, `docs/index.md`, and `docs/handbook/workflow-end-to-end.md` aligned with the actual `api/` + `frontend/` surfaces
- move shipped subplans out of `docs/plans/active/`

## Verification

Minimum verification for this workstream:

- `C:\\Users\\patri\\miniconda3\\envs\\ai-fund\\python.exe -m pytest tests/test_api_contracts.py tests/test_dashboard_runtime_contracts.py tests/test_dashboard_render_contracts.py tests/test_batch_funnel.py tests/test_batch_watchlist.py tests/test_batch_runner_storage.py -q`
- `C:\\Users\\patri\\miniconda3\\envs\\ai-fund\\python.exe -m pytest -m "not live" --tb=short -q`
- `npm --prefix frontend run test`
- `npm --prefix frontend run build`
- `python3 scripts/manual/review_react_route_matrix.py`
- host-side Streamlit + Playwright smoke validation for:
  - watchlist landing
  - `Open Latest Snapshot`
  - visible `Assumptions` / `WACC`
  - compact non-`Overview` ticker pages

## Notes

- `api/` is a transport surface, not a new business-logic layer.
- The React shell is the strategic direction.
- Streamlit stabilization remains in scope only as a transitional operator surface.
