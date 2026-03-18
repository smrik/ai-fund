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
- finished plans must move out of active areas
- stale or duplicate docs should be archived or removed, not left beside current guidance
- setup docs must match the actual environment and ignore rules

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
