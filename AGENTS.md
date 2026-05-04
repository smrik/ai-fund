# AGENTS.md — Alpha Pod

This file is the short map, not the full manual.

Read this first, then follow the canonical docs it points to. Keep this file concise and keep the detailed truth in `docs/`.

## What This Repo Is

Alpha Pod is an AI-augmented fundamental long/short equity research pipeline for a solo PM.

The system is split into three layers:

1. Data layer: deterministic ingestion and caching
2. Computation layer: deterministic screening, WACC, DCF, and portfolio math
3. Judgment layer: LLM agents used selectively for narrative and qualitative analysis

The hard rule is unchanged: LLM code never touches the deterministic computation layer.

## Read These In Order

1. [`docs/PLANS.md`](./docs/PLANS.md) — repository guidance, docs taxonomy, and planning rules
2. [`docs/index.md`](./docs/index.md) — docs home
3. [`docs/design-docs/architecture-overview.md`](./docs/design-docs/architecture-overview.md) — architecture and boundaries
4. [`docs/design-docs/core-beliefs.md`](./docs/design-docs/core-beliefs.md) — design principles
5. [`docs/handbook/workflow-end-to-end.md`](./docs/handbook/workflow-end-to-end.md) — operator workflow
6. [`docs/handbook/react-frontend-setup.md`](./docs/handbook/react-frontend-setup.md) — React/API runtime map
7. [`docs/handbook/react-playwright-review-loop.md`](./docs/handbook/react-playwright-review-loop.md) — canonical UI review workflow
8. [`docs/plans/index.md`](./docs/plans/index.md) — canonical plan registry
9. [`.agent/session-state.md`](./.agent/session-state.md) — current handoff state if it exists

If you are touching `dashboard/`, `frontend/`, `api/`, or browser validation, also read:

- [`docs/handbook/quote-terminal-ui.md`](./docs/handbook/quote-terminal-ui.md)
- [`docs/handbook/local-dashboard-validation.md`](./docs/handbook/local-dashboard-validation.md)

## Canonical Structure

Use these locations consistently:

- `docs/design-docs/` for architecture and design specs
- `docs/handbook/` for operator and engineer how-to guides
- `docs/reference/` for stable references and config docs
- `docs/strategy/` for product direction and quality scoring
- `docs/plans/` for the canonical plan system:
  - `active/`
  - `future/`
  - `completed/`
  - `archive/`
- `docs/exec-plans/` for archived execution artifacts only
- `docs/archive/` for deprecated or scratch material that is kept only for history

## Maintenance Rules

- `AGENTS.md` must stay short and point to canonical docs instead of duplicating them
- `docs/` is the system of record and must be updated when behavior or structure changes
- `.agent/session-state.md` is the handoff log, not the long-term source of truth
- non-trivial implementation work must have exactly one canonical active plan under `docs/plans/active/` and a matching entry in [`docs/plans/index.md`](./docs/plans/index.md)
- finished plans must move out of active areas
- stale or duplicate docs should be archived or removed, not left beside current guidance
- setup docs must match the actual environment and ignore rules

## Execution Loop

For any multi-step change:

1. Read the active plan in `docs/plans/active/` and the latest `.agent/session-state.md`
2. Implement against that plan instead of inventing a second tracker
3. Update the canonical plan and adjacent docs when scope or behavior changes
4. Update `.agent/session-state.md` before handoff so the next agent can resume quickly

## React And Playwright Rules

When working on the React shell:

1. Prefer the documented React stack and review workflow in [`docs/handbook/react-frontend-setup.md`](./docs/handbook/react-frontend-setup.md) and [`docs/handbook/react-playwright-review-loop.md`](./docs/handbook/react-playwright-review-loop.md) over inventing a new local run path.
2. `dashboard/` is still the operator-facing shell today. `frontend/` + `api/` is the strategic migration path. Keep both working during the transition.
3. `api/` is transport only. New business logic belongs in `src/stage_04_pipeline/`, `src/stage_03_judgment/`, `src/stage_02_valuation/`, `db/`, or `config/`.
4. Preserve the current route invariants unless the active plan explicitly changes them: `/watchlist` as the landing route, selected-row focus pane on watchlist, compact non-`Overview` ticker strip, and visible valuation subviews.
5. For React route review in WSL, prefer [`scripts/manual/launch-react-wsl.sh`](./scripts/manual/launch-react-wsl.sh). For Streamlit + Playwright, host PowerShell remains canonical.
6. Use the route-matrix runner in [`scripts/manual/review_react_route_matrix.py`](./scripts/manual/review_react_route_matrix.py) before claiming a React route set is healthy.
7. Do not trust `200 OK` or a clean browser console by themselves; inspect screenshots and distinguish true empty-state data from render bugs.
8. If a frontend route looks wrong, compare the rendered page against the direct API payload before changing UI code.

## Branch Hygiene

Before starting a new branch or ending a major work session:

1. Check whether `main` is clean and pushed to GitHub
2. If `main` is ahead of `origin/main` or the worktree is dirty, call that out explicitly to the user
3. Prefer syncing `main` first before creating more feature branches, unless the user intentionally wants stacked or local-only work
4. Do not assume the user remembered to push; remind them when the repo is not fully up to date on GitHub
5. If the user says they want to “start fresh” or “branch properly”, pause and verify Git hygiene before doing anything else
6. When in doubt, babysit the workflow: explain whether `main` is clean, whether GitHub matches local, and what the next safe git step is

## Pre-Commit On This Machine

The default user pre-commit cache can be readonly in Codex/Windows sandbox sessions. If `pre-commit` fails with `attempt to write a readonly database` or cannot write `C:\Users\patri\.cache\pre-commit\pre-commit.log`, rerun it with a workspace-local cache:

```powershell
$env:PRE_COMMIT_HOME = "$PWD\.pre-commit-cache-run-codex"
rtk pre-commit run --all-files
```

`.pre-commit-cache-run*/` is ignored by Git, so the local hook cache should not pollute commits.

## Project Structure

```text
config/         Committed config and overrides
api/            Thin FastAPI surface over stage_04/stage_03/stage_02 helpers
ciq/            Capital IQ Excel integration
db/             SQLite schema and loaders
src/
  stage_00_data/        Deterministic data ingestion
  stage_01_screening/   Deterministic screening
  stage_02_valuation/   Deterministic valuation and portfolio math
  stage_03_judgment/    LLM agents only
  stage_04_pipeline/    Orchestration, dashboard helpers, refresh flows
dashboard/      Streamlit app
frontend/       React + TypeScript + Vite quote-terminal scaffold
tests/          Offline-first test suite
docs/           Canonical documentation
skills/         Project-local skills and prompts
```

## Running The System

```bash
python -m src.stage_01_screening.stage1_filter
python -m src.stage_02_valuation.batch_runner --top 50
python -m src.stage_02_valuation.batch_runner --ticker IBM
python -m uvicorn api.main:app --reload
npm --prefix frontend run dev
python -m ciq.ciq_refresh
python -m pytest -v
```

## Local Secrets

Use `.env` for machine-local secrets only. Do not commit it.

Start from `.env.example` and keep committed defaults in `config/config.yaml`.
