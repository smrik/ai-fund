# Universe Watchlist Landing Page Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Turn the transient `Audit -> Batch Funnel` screen into a saved universe watchlist landing page that auto-loads the latest deterministic batch snapshot, ranks the full universe, enriches rows with latest deep-analysis stance metadata, and lets the PM open the latest archived snapshot per ticker without auto-running agents.

**Architecture:** Keep the existing 5-tab shell. The no-memo landing route remains `Audit`, but `Batch Funnel` becomes a persistent watchlist backed by deterministic Stage 02 outputs plus latest `pipeline_report_archive` metadata. Deterministic batch remains the source of valuation fields; archived snapshots contribute latest PM-facing stance fields (`action`, `conviction`, `created_at`) when available.

**Tech Stack:** Streamlit, sqlite3, pandas-backed Stage 02 batch outputs, `pipeline_report_archive`, pytest, host-side Playwright CLI smoke validation.

---

### Task 1: Add failing tests for saved watchlist data loading

**Files:**
- Create: `tests/test_batch_watchlist.py`
- Modify: `src/stage_04_pipeline/batch_funnel.py`
- Reference: `src/stage_04_pipeline/report_archive.py`

**Step 1: Write the failing test**

Add a test that seeds:
- `batch_valuations_latest` rows for at least two tickers
- `pipeline_report_archive` rows for one of those tickers

Test expected behavior:
- helper returns the full deterministic universe rows
- rows are sorted with best-ranked names first
- latest archived `action`, `conviction`, and `created_at` are joined when present
- rows without archived snapshots still appear with blank PM stance fields

**Step 2: Run test to verify it fails**

Run:
```bash
'/mnt/c/Users/patri/miniconda3/envs/ai-fund/python.exe' -m pytest tests/test_batch_watchlist.py -q
```

Expected:
- fail because the watchlist loading helper does not exist yet

**Step 3: Write minimal implementation**

In `src/stage_04_pipeline/batch_funnel.py`, add a helper with a narrow contract, for example:
- `load_saved_watchlist() -> dict`

Behavior:
- read `batch_valuations_latest` from SQLite
- derive rank using existing `expected_upside_pct` / `upside_base_pct` logic
- join latest `pipeline_report_archive` row per ticker
- return:
  - full row list
  - saved timestamp / freshness marker
  - ranked default ordering

**Step 4: Run test to verify it passes**

Run:
```bash
'/mnt/c/Users/patri/miniconda3/envs/ai-fund/python.exe' -m pytest tests/test_batch_watchlist.py -q
```

Expected:
- PASS

**Step 5: Commit**

```bash
git add tests/test_batch_watchlist.py src/stage_04_pipeline/batch_funnel.py
git commit -m "feat: add saved watchlist loader"
```

### Task 2: Add failing tests for no-memo landing restore behavior

**Files:**
- Modify: `tests/test_dashboard_runtime_contracts.py`
- Modify: `dashboard/sections/batch_funnel.py`
- Modify: `dashboard/app.py`

**Step 1: Write the failing test**

Add runtime contract tests covering:
- when `batch_funnel_view` is empty but saved watchlist data exists, `Batch Funnel` renders the saved watchlist instead of only showing “Run the deterministic batch”
- no-memo app route still lands on `Audit -> Batch Funnel`
- no-memo landing does not require an immediate rerun to show the latest saved deterministic universe

**Step 2: Run test to verify it fails**

Run:
```bash
'/mnt/c/Users/patri/miniconda3/envs/ai-fund/python.exe' -m pytest tests/test_dashboard_runtime_contracts.py -q
```

Expected:
- fail because the UI still depends on ephemeral `session_state["batch_funnel_view"]`

**Step 3: Write minimal implementation**

In `dashboard/sections/batch_funnel.py`:
- on render, if no in-session view exists, call `load_saved_watchlist()`
- cache the loaded result into session state for current use
- surface “last updated” metadata and a manual `Refresh Batch` action

In `dashboard/app.py`:
- keep current no-memo route to `Audit -> Batch Funnel`
- do not change loaded-memo routing to `Overview`

**Step 4: Run test to verify it passes**

Run:
```bash
'/mnt/c/Users/patri/miniconda3/envs/ai-fund/python.exe' -m pytest tests/test_dashboard_runtime_contracts.py -q
```

Expected:
- PASS

**Step 5: Commit**

```bash
git add tests/test_dashboard_runtime_contracts.py dashboard/sections/batch_funnel.py dashboard/app.py
git commit -m "feat: restore saved watchlist on landing"
```

### Task 3: Add failing tests for watchlist row shape and PM stance columns

**Files:**
- Modify: `tests/test_batch_watchlist.py`
- Modify: `dashboard/sections/batch_funnel.py`

**Step 1: Write the failing test**

Add assertions that each rendered watchlist row exposes the agreed fields:
- `ticker`
- `company_name`
- `price`
- `iv_bear`
- `iv_base`
- `iv_bull`
- `expected_iv`
- `analyst_target`
- `latest_action`
- `latest_conviction`
- `latest_snapshot_date`

Also assert:
- rows are full-universe rows, not only the top 10
- best-ranked rows are first by default

**Step 2: Run test to verify it fails**

Run:
```bash
'/mnt/c/Users/patri/miniconda3/envs/ai-fund/python.exe' -m pytest tests/test_batch_watchlist.py -q
```

Expected:
- fail because the current UI only renders shortlist-centric rows

**Step 3: Write minimal implementation**

In `dashboard/sections/batch_funnel.py`:
- replace the shortlist-only primary table with a watchlist table for the full ranked universe
- keep shortlist/deep-analysis controls as a secondary action surface
- default sort order:
  1. rows with `expected_upside_pct`
  2. ranking score descending
  3. margin of safety descending

**Step 4: Run test to verify it passes**

Run:
```bash
'/mnt/c/Users/patri/miniconda3/envs/ai-fund/python.exe' -m pytest tests/test_batch_watchlist.py -q
```

Expected:
- PASS

**Step 5: Commit**

```bash
git add tests/test_batch_watchlist.py dashboard/sections/batch_funnel.py
git commit -m "feat: render saved universe watchlist"
```

### Task 4: Add failing tests for ticker drilldown behavior

**Files:**
- Modify: `tests/test_batch_funnel.py`
- Modify: `dashboard/sections/batch_funnel.py`
- Modify: `src/stage_04_pipeline/batch_funnel.py`

**Step 1: Write the failing test**

Add tests for:
- opening a ticker with an archived snapshot loads the latest snapshot into dashboard state
- a ticker without an archived snapshot shows a manual rerun/deep-analysis affordance
- no auto-run occurs when snapshot is missing

**Step 2: Run test to verify it fails**

Run:
```bash
'/mnt/c/Users/patri/miniconda3/envs/ai-fund/python.exe' -m pytest tests/test_batch_funnel.py -q
```

Expected:
- fail because the current screen only exposes a basic `Open Latest Snapshot` path and does not cleanly model the “missing snapshot” branch as a watchlist action

**Step 3: Write minimal implementation**

In `dashboard/sections/batch_funnel.py`:
- add row-level or selected-ticker actions:
  - `Open Latest Snapshot`
  - `Run Deep Analysis` only when snapshot missing or stale by user choice
- keep deep-analysis trigger manual

In `src/stage_04_pipeline/batch_funnel.py`:
- keep snapshot-loading helper narrow and deterministic
- return enough metadata for the UI to decide whether to show “open” versus “run”

**Step 4: Run test to verify it passes**

Run:
```bash
'/mnt/c/Users/patri/miniconda3/envs/ai-fund/python.exe' -m pytest tests/test_batch_funnel.py -q
```

Expected:
- PASS

**Step 5: Commit**

```bash
git add tests/test_batch_funnel.py dashboard/sections/batch_funnel.py src/stage_04_pipeline/batch_funnel.py
git commit -m "feat: add watchlist drilldown actions"
```

### Task 5: Add saved watchlist metadata and refresh UX

**Files:**
- Modify: `src/stage_04_pipeline/batch_funnel.py`
- Modify: `dashboard/sections/batch_funnel.py`
- Modify: `tests/test_batch_watchlist.py`

**Step 1: Write the failing test**

Add a test asserting the saved watchlist payload includes:
- last saved timestamp
- universe row count
- ranked shortlist count
- a stable default focus ticker if one exists

**Step 2: Run test to verify it fails**

Run:
```bash
'/mnt/c/Users/patri/miniconda3/envs/ai-fund/python.exe' -m pytest tests/test_batch_watchlist.py -q
```

Expected:
- fail because saved watchlist metadata is still too thin

**Step 3: Write minimal implementation**

Expose watchlist metadata sourced from:
- latest deterministic batch save time
- row counts
- latest ranked table

Render:
- `Last updated`
- `Universe size`
- `Saved rows`
- `Refresh Batch` button

Do not auto-refresh on load.

**Step 4: Run test to verify it passes**

Run:
```bash
'/mnt/c/Users/patri/miniconda3/envs/ai-fund/python.exe' -m pytest tests/test_batch_watchlist.py -q
```

Expected:
- PASS

**Step 5: Commit**

```bash
git add tests/test_batch_watchlist.py src/stage_04_pipeline/batch_funnel.py dashboard/sections/batch_funnel.py
git commit -m "feat: add saved watchlist metadata"
```

### Task 6: Update docs and verify end-to-end behavior

**Files:**
- Modify: `docs/handbook/workflow-end-to-end.md`
- Modify: `.agent/session-state.md`
- Optional: `docs/plans/index.md` if active-plan wording needs refresh after implementation

**Step 1: Write the failing doc/behavior checklist**

Create a short checklist in the plan execution notes:
- landing page auto-loads latest saved universe watchlist
- full universe table is visible
- latest deep-analysis action/conviction/date appear when available
- opening a ticker loads latest archived snapshot
- missing snapshot does not auto-run agents

**Step 2: Run verification commands**

Run:
```bash
python3 -m py_compile dashboard/app.py dashboard/sections/batch_funnel.py src/stage_04_pipeline/batch_funnel.py tests/test_batch_watchlist.py
'/mnt/c/Users/patri/miniconda3/envs/ai-fund/python.exe' -m pytest tests/test_batch_watchlist.py tests/test_batch_funnel.py tests/test_dashboard_runtime_contracts.py tests/test_dashboard_render_contracts.py tests/test_architecture_boundaries.py -q
```

Then run host smoke validation:
```bash
'/mnt/c/Program Files/PowerShell/7/pwsh.exe' -NoProfile -File scripts/manual/launch-streamlit-playwright-cli.ps1 -PythonCommand 'C:\\Users\\patri\\miniconda3\\envs\\ai-fund\\python.exe'
```

Expected:
- no-memo landing opens directly on the saved watchlist
- the watchlist shows saved universe rows without rerunning batch
- Playwright CLI can still open/snapshot/screenshot successfully

**Step 3: Update docs**

Document the new watchlist-first landing flow in `docs/handbook/workflow-end-to-end.md`:
- saved universe watchlist is the default no-memo landing surface
- deterministic batch refresh is manual
- full deep analysis is opt-in per ticker or shortlist

**Step 4: Commit**

```bash
git add docs/handbook/workflow-end-to-end.md .agent/session-state.md
git commit -m "docs: document saved watchlist landing flow"
```
