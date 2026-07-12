# Quote-Terminal UI Redesign And Streamlit Migration

| Field | Value |
| --- | --- |
| Current tranche | Professional-model full-state review workflow |
| Status | In progress - 2026-07-12 |
| Serves Vision decisions | 1, 2, 7, 10, 11, and 12 |

> **2026-06-12 update:** Streamlit retirement is now a settled decision ([Vision](../../strategy/vision.md) Decision 7). This plan is the canonical workstream for Milestone 2 of the [Six-Month Execution Roadmap](../future/2026-06-12-six-month-execution-roadmap.md): React parity for loop-critical surfaces only (queue review, watchlist, valuation views, Analyst Prep, exports), then `dashboard/` is deleted. Any "keep both working" language below is superseded — Streamlit is bugfix-only.

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

### 0. Make the professional MSFT model reviewable and capable of reaching full state

The 2026-07-12 actual-data build produced a mechanically calculated 26-sheet model, but it remains fail-closed on source defects, unsupported modules, degraded WACC evidence, and PM scenario approvals. This tranche connects that model to the strategic React/FastAPI surface without moving valuation logic into the transport or client layers.

Non-negotiables:

- repair or replace the 24 broken `Detailed Comps` formula references with auditable source evidence; never silently bless cached values
- resolve segment, WACC, and valuation evidence in deterministic Python before lifting their gates
- keep PM approval as the only path from reviewed finance semantics to an approved/full model state
- invalidate approvals when the reviewed driver fingerprint changes
- expose readiness, blockers, checks, lineage, scenario drivers, valuation diagnostics, sheet-level audit findings, and the generated workbook through FastAPI
- add a React professional-model workbench under the existing valuation route, preserving `/watchlist` and the current ticker-route invariants
- keep `api/` transport-only and `frontend/` free of valuation calculations
- run one independent audit lane per workbook sheet, consolidate findings, remediate material defects, rebuild, recalculate, and re-audit

Acceptance criteria:

- every non-PM blocker is either cleared by evidence/mechanics or remains explicitly unresolved with a precise remediation owner
- Base, Upside, and Downside approvals are explicit, fingerprinted PM actions; no approval is inferred from opening the page or rebuilding the model
- the React workbench can show the current state, drill into all 26 sheets, preview the approval consequence, approve/reject where permitted, trigger a rebuild, and download the exact workbook
- API contract tests, frontend tests/build, workbook integrity checks, formula scans, and the canonical route-matrix browser review pass
- a final completion audit proves the workbook state shown in React matches the workbook, manifest, QA report, and deterministic source data


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
