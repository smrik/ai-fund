# AGENTS.md — Alpha Pod

This file is the short map, not the full manual.

Read this first, then follow the canonical docs it points to. Keep this file concise and keep the detailed truth in `docs/`.

## Vision Compliance (mandatory)

The PM's settled product decisions live in [`docs/strategy/vision.md`](./docs/strategy/vision.md). They are not suggestions:

1. **Never re-litigate a settled decision.** If your task seems to conflict with one, stop and name the conflict to the PM instead of working around it.
2. **Every new plan names the Vision decision(s) it serves** in its header. A plan that serves none is backlog, not work.
3. **Interview-first (Decision 10):** for non-trivial features, interview the PM until ambiguity is resolved before writing the plan. Do not draft specs cold from a one-line idea.
4. **Split-by-domain ambiguity rule (Decision 11):** finance semantics (thresholds, accepted ranges, valuation logic, what a metric means) always block on the PM. Engineering details get a conservative decision logged in the plan or PR.
5. **Current sequencing** is the [Six-Month Execution Roadmap](./docs/plans/future/2026-06-12-six-month-execution-roadmap.md). Real weekly-loop usage outranks feature work.

## Human-in-the-loop thinking protocol

The agent must not replace the user's analytical thinking.

Before writing substantial code, proposing an architecture, or running an autonomous implementation loop, first ask for or infer the following:

1. What is the goal?
2. What is the input data or starting state?
3. What should the output look like?
4. What is the simplest pipeline in plain English?
5. What assumptions could make the result wrong?
6. What sanity check will verify the result?

If the user has not provided these, do not proceed directly to full implementation. Instead, produce a short planning scaffold and ask the user to fill in missing pieces, unless the task is trivial.

When coding:

- Prefer the smallest working version first.
- Avoid unnecessary abstractions.
- Add sanity checks after major transformations.
- Explain assumptions and silent failure modes.
- Do not hide important reasoning inside generated code.
- After implementation, summarize what the user should manually inspect.

## What This Repo Is

Alpha Pod is an AI-augmented fundamental long/short equity research pipeline for a solo PM.

The system is split into three layers:

1. Data layer: deterministic ingestion and caching
2. Computation layer: deterministic screening, WACC, DCF, and portfolio math — and marshalling the relevant evidence for a specific analytical question
3. Judgment layer: LLM agents that reason over qualitative and quantitative evidence to **set the key forward-looking assumptions** (Vision Decision 13), routed through the PM Decision Queue

The hard rule is unchanged: LLM code never *executes inside* the deterministic computation layer,
and the PM Decision Queue is the only bridge to model mutation.

Note what that rule does **not** say. It constrains where code runs; it does not demote the
judgment layer to commentary. Forward-looking drivers are meant to be agent-reasoned from filings,
management guidance, and history — sector constants and mechanical transforms are fallbacks that
signal missing judgment. A model whose `*_target` drivers all come from lookup tables is not the
product, however many agents ran alongside it. See [The Division Of Labor](./docs/strategy/vision.md#the-division-of-labor).

## Read These In Order

1. [`docs/strategy/vision.md`](./docs/strategy/vision.md) — the PM's settled decisions; plans must serve these and must not re-litigate them. **Decisions 13-14 and [The Division Of Labor](./docs/strategy/vision.md#the-division-of-labor) are the point of the project — read them before any valuation or agent work**
2. [`docs/valuation/index.md`](./docs/valuation/index.md) — **the finance methodology in analyst order, and where the division of labor is worked out per driver.** Required before touching valuation, assumptions, or judgment agents; [12_deterministic-vs-llm-boundary.md](./docs/valuation/12_deterministic-vs-llm-boundary.md) is the ownership map
3. [`docs/PLANS.md`](./docs/PLANS.md) — repository guidance, docs taxonomy, and planning rules
4. [`docs/index.md`](./docs/index.md) — docs home
5. [`docs/design-docs/architecture-overview.md`](./docs/design-docs/architecture-overview.md) — architecture and boundaries
6. [`docs/design-docs/core-beliefs.md`](./docs/design-docs/core-beliefs.md) — design principles
7. [`docs/handbook/workflow-end-to-end.md`](./docs/handbook/workflow-end-to-end.md) — operator workflow
8. [`docs/handbook/react-frontend-setup.md`](./docs/handbook/react-frontend-setup.md) — React/API runtime map
9. [`docs/handbook/react-playwright-review-loop.md`](./docs/handbook/react-playwright-review-loop.md) — canonical UI review workflow
10. [`docs/plans/index.md`](./docs/plans/index.md) — canonical plan registry
11. [`.agent/session-state.md`](./.agent/session-state.md) — current handoff state if it exists

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
2. `dashboard/` (Streamlit) is frozen to bugfix-only and will be deleted once React covers the loop-critical surfaces (Vision Decision 7). Do not add Streamlit features. `frontend/` + `api/` is the one surface going forward.
3. `api/` is transport only. New business logic belongs in `src/stage_04_pipeline/`, `src/stage_03_judgment/`, `src/stage_02_valuation/`, `db/`, or `config/`.
4. Preserve the current route invariants unless the active plan explicitly changes them: `/watchlist` as the landing route, selected-row focus pane on watchlist, compact non-`Overview` ticker strip, and visible valuation subviews.
5. For React route review in WSL, prefer [`scripts/manual/launch-react-wsl.sh`](./scripts/manual/launch-react-wsl.sh). For Streamlit + Playwright, host PowerShell remains canonical.
6. Use the route-matrix runner in [`scripts/manual/review_react_route_matrix.py`](./scripts/manual/review_react_route_matrix.py) before claiming a React route set is healthy.
7. Do not trust `200 OK` or a clean browser console by themselves; inspect screenshots and distinguish true empty-state data from render bugs.
8. If a frontend route looks wrong, compare the rendered page against the direct API payload before changing UI code.

## Commit Cadence (default on)

**Commit as you go. This is the default, not an option.** Do not wait until the end of a session,
and do not ask permission for each commit — the PM has standing approval for commits on a feature
branch. Skip it only when the PM explicitly says not to commit.

Commit after each of these, whichever comes first:

1. a test goes from red to green;
2. a bug is fixed and its regression passes;
3. a file is created or substantially rewritten;
4. roughly thirty minutes of work, or before any risky or wide-reaching edit.

Why this is a hard requirement, from real damage in this repository:

- On 2026-07-31 an over-broad regex destroyed ~180 lines of
  `tests/test_filing_presentation.py`. The file was **untracked**, so there was no version to
  restore and the test had to be abandoned.
- On 2026-08-01 a delegated `opencode` run corrupted
  `statement_reconciliation_service.py` and its test file, and edited an existing test it had been
  told not to touch. Recovery only worked because a manual snapshot had been taken first.

Both were recoverable-in-principle failures that became unrecoverable because work sat uncommitted.
A commit is the cheapest possible undo.

Rules that follow from that:

- **Never leave new source or test files untracked.** `git add` a new file in the same change that
  creates it, even if it is incomplete.
- **Commit before delegating to another agent** (`opencode`, `codex exec`, a subagent) and before
  any bulk or regex-driven edit.
- Commit messages state what changed and why, and end with the co-author trailer.
- Committing is not the same as pushing. Push only when the PM asks.

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
dashboard/      Streamlit app (frozen, bugfix-only, retiring per Vision Decision 7)
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
