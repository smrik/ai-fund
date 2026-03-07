# AGENTS.md — Alpha Pod

**This is the table of contents, not the manual.**
Read this file, then follow the pointers. Do not try to hold everything in context at once.

---

## What This Is

Alpha Pod is an AI-augmented fundamental long/short equity research pipeline for a solo operator.
Automates junior analyst, risk manager, and operations workflows.
Human is the PM — makes all final investment decisions.

## Architecture (read this first)

See [`ARCHITECTURE.md`](./ARCHITECTURE.md) — three-layer system:
1. **Data Layer** — yfinance / CIQ / EDGAR. Deterministic. No LLM.
2. **Computation Layer** — DCF, WACC, screening. Deterministic. No LLM.
3. **Judgment Layer** — 4 LLM agents, used selectively.

**The single most important rule: LLM code never touches the computation layer.**
Data flows one direction: Data → Computation → Judgment. Never the reverse.

## Core Beliefs

See [`docs/design-docs/core-beliefs.md`](./docs/design-docs/core-beliefs.md)
Encode your disagreements there, not here.

## Project Structure

```
config/         Settings, universe.csv, screening_rules.yaml, ciq_schema.yaml
ciq/            Capital IQ Excel integration (xlwings)
db/             SQLite schema, loader, queries
ibkr/           Interactive Brokers API (Phase 3)
monitoring/     Alerts and dashboard (Phase 3)
src/
  stage_00_data/        Deterministic data ingestion adapters (yfinance/CIQ/EDGAR)
  stage_01_screening/   Deterministic screening pipeline
  stage_02_valuation/   Deterministic WACC/DCF/batch valuation + templates
  stage_03_judgment/    LLM agents (judgment layer only; not in compute path)
  stage_04_pipeline/    Orchestration + refresh entrypoints
tests/          All tests — run with pytest
docs/           Product/design/operations docs
skills/         Claude Code / Codex skills
```

## Docs Structure

```
docs/
├── design-docs/
│   ├── core-beliefs.md       ← start here for design philosophy
│   └── index.md
├── exec-plans/
│   ├── active/               ← current sprint plans
│   ├── completed/            ← finished plans (history)
│   └── tech-debt-tracker.md
├── references/               ← llms.txt files for key dependencies
├── PLANS.md                  ← plan index
├── PRODUCT_SENSE.md          ← what we're building and why
└── QUALITY_SCORE.md          ← per-layer quality grades
```

## Running the Pipeline

```bash
# Stage 1 screen (seed → ~300 quality companies)
python -m src.stage_01_screening.stage1_filter

# Batch DCF valuation (ranks all survivors)
python -m src.stage_02_valuation.batch_runner --top 50

# Single ticker deep dive
python -m src.stage_02_valuation.batch_runner --ticker HALO

# CIQ refresh (requires Excel + CIQ plugin open)
python -m ciq.ciq_refresh

# Tests
pytest tests/ -v
```

## Active Plans

See [`docs/PLANS.md`](./docs/PLANS.md) for full index.

Current active sprint: [`docs/exec-plans/active/sprint-1-deterministic-hardening.md`](./docs/exec-plans/active/sprint-1-deterministic-hardening.md)

## Key Constraints (enforced, not negotiable)

1. LLM agents live in `src/stage_03_judgment/` only — never imported by `src/stage_00_data/`, `src/stage_01_screening/`, or `src/stage_02_valuation/`
2. Every agent has a typed input/output dataclass — no raw dict passing between layers
3. `config/universe.csv` is the canonical ticker list — all pipelines read from it
4. All financial assumptions have an `assumption_source` audit field in output
5. Sector defaults in `src/stage_02_valuation/batch_runner.py` are fallbacks, not primaries — real data wins
## Agent Triggers (when each LLM agent runs)

| Agent | Trigger | Input | Output |
|---|---|---|---|
| QoE | Per ticker, after 10-K filing | 10-K text + TTM financials | Adjusted EBIT margin, one-time flags |
| Comps Matching | Per ticker, after CIQ refresh | CIQ peer list (~50) | Top 5-10 scored peers |
| Industry Research | Weekly per sector | Sector name + recent news | Growth rates, margin benchmarks, framework |
| Scenario/Catalyst | Per ticker + news triggers | 10-K risk factors + headlines | Named scenarios with probabilities |

## What Codex Cannot See

Anything not in this repository does not exist from the agent's perspective.
Design decisions made in chat, Slack, or verbally must be encoded here.
See `docs/design-docs/core-beliefs.md` for the current list.




