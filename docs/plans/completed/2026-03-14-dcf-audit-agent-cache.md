# DCF Audit Viewer and Agent Cache Implementation Note

**Date:** 2026-03-14

## Scope
- Added a browser-native deterministic DCF audit surface in the Streamlit dashboard.
- Added SQLite-backed agent artifact caching plus selective rerun controls in the pipeline.

## DCF Audit Viewer
Files:
- `src/stage_04_pipeline/dcf_audit.py`
- `dashboard/app.py`

Behavior:
- Builds deterministic audit tables directly from `build_valuation_inputs()` and `run_probabilistic_valuation()`.
- Renders key tables only:
  - scenario summary
  - key drivers + lineage
  - health flags
  - forecast bridge (Y1-Y10)
  - terminal bridge
  - EV-to-equity bridge
  - 3x3 sensitivity tables
- Keeps Python DCF as the single source of truth. No spreadsheet formulas in-browser.

## Agent Cache
Files:
- `src/stage_04_pipeline/agent_cache.py`
- `src/stage_04_pipeline/orchestrator.py`
- `db/schema.py`
- `dashboard/app.py`

Behavior:
- Cache key = `ticker + agent_name + input_hash + model + prompt_hash`.
- Same hashed inputs reuse prior output from SQLite.
- `force_refresh_agents` bypasses cache only for selected steps.
- Downstream steps still reuse cache when refreshed upstream output is unchanged.
- Each run also writes a persisted `agent_run_log` row for audit/history.

## Dashboard Controls
- Sidebar:
  - `Use agent cache`
  - `Force refresh agents`
- New sections:
  - `🧮 DCF Audit`
  - `🔄 Pipeline`

## Verification
- Unit tests added:
  - `tests/test_dcf_audit.py`
  - `tests/test_orchestrator_cache.py`
- Full suite:
  - `python -m pytest tests/ -q` -> `313 passed`
- Live dashboard review with Playwright:
  - verified DCF Audit section renders
  - verified Pipeline section renders
  - verified second IBM rerun shows per-agent `| cache` status in the UI
