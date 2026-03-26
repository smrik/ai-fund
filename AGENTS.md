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
6. [`docs/plans/index.md`](./docs/plans/index.md) — canonical plan registry
7. [`.agent/session-state.md`](./.agent/session-state.md) — current handoff state if it exists

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

## Branch Hygiene

Before starting a new branch or ending a major work session:

1. Check whether `main` is clean and pushed to GitHub
2. If `main` is ahead of `origin/main` or the worktree is dirty, call that out explicitly to the user
3. Prefer syncing `main` first before creating more feature branches, unless the user intentionally wants stacked or local-only work
4. Do not assume the user remembered to push; remind them when the repo is not fully up to date on GitHub
5. If the user says they want to “start fresh” or “branch properly”, pause and verify Git hygiene before doing anything else
6. When in doubt, babysit the workflow: explain whether `main` is clean, whether GitHub matches local, and what the next safe git step is

## Project Structure

```text
config/         Committed config and overrides
ciq/            Capital IQ Excel integration
db/             SQLite schema and loaders
src/
  stage_00_data/        Deterministic data ingestion
  stage_01_screening/   Deterministic screening
  stage_02_valuation/   Deterministic valuation and portfolio math
  stage_03_judgment/    LLM agents only
  stage_04_pipeline/    Orchestration, dashboard helpers, refresh flows
dashboard/      Streamlit app
tests/          Offline-first test suite
docs/           Canonical documentation
skills/         Project-local skills and prompts
```

## Running The System

```bash
python -m src.stage_01_screening.stage1_filter
python -m src.stage_02_valuation.batch_runner --top 50
python -m src.stage_02_valuation.batch_runner --ticker IBM
python -m ciq.ciq_refresh
python -m pytest -v
```

## Local Secrets

Use `.env` for machine-local secrets only. Do not commit it.

Start from `.env.example` and keep committed defaults in `config/config.yaml`.
