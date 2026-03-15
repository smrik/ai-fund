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
3. **Judgment Layer** — 8 LLM agents, used selectively.

**The single most important rule: LLM code never touches the computation layer.**
Data flows one direction: Data → Computation → Judgment. Never the reverse.

## Core Beliefs

See [`docs/design-docs/core-beliefs.md`](./docs/design-docs/core-beliefs.md)
Encode your disagreements there, not here.

## Project Structure

```
config/         Settings, universe.csv, screening_rules.yaml, valuation_overrides.yaml
ciq/            Capital IQ Excel integration (xlwings refresh script)
db/             SQLite schema, loader, queries
ibkr/           Interactive Brokers API (Phase 3)
monitoring/     Alerts and dashboard (Phase 3)
src/
  stage_00_data/        Deterministic data ingestion adapters (yfinance/CIQ/EDGAR)
  stage_01_screening/   Deterministic screening pipeline
  stage_02_valuation/   Deterministic WACC/DCF/assembler + batch runner
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
│   ├── core-beliefs.md           ← start here for design philosophy
│   ├── qoe-agent-spec.md         ← QoE agent design specification
│   └── index.md
├── exec-plans/
│   ├── active/                   ← current work items
│   └── tech-debt-tracker.md
├── handbook/
│   ├── valuation-dcf-logic.md    ← DCF math and assumption sourcing
│   ├── qoe-agent.md              ← QoE agent explanation (finance-readable)
│   └── workflow-end-to-end.md
├── PLANS.md                      ← plan index
├── PRODUCT_SENSE.md              ← what we're building and why
└── QUALITY_SCORE.md              ← per-layer quality grades
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

# Tests (all offline via monkeypatch — no network required)
pytest tests/ -v

# Tests excluding live network calls (if any marked @pytest.mark.live)
pytest tests/ -v -m "not live"
```

## Agent Triggers (when each LLM agent runs)

| Agent           | File                 | Trigger                         | Input                                | Key Output                                                      |
| --------------- | -------------------- | ------------------------------- | ------------------------------------ | --------------------------------------------------------------- |
| **QoE Agent**   | `qoe_agent.py`       | Per ticker before DCF finalised | TTM financials + CIQ NWC + 10-K text | `qoe_score` 1–5, `normalized_ebit`, `dcf_ebit_override_pending` |
| Earnings Agent  | `earnings_agent.py`  | Post earnings                   | Transcript text                      | Key themes, beat/miss assessment                                |
| Filings Agent   | `filings_agent.py`   | Per 10-K/10-Q filing            | Filing text                          | MD&A summary, risk change flags                                 |
| Risk Agent      | `risk_agent.py`      | Per 10-K                        | Risk factors section                 | Scored risk factors                                             |
| Sentiment Agent | `sentiment_agent.py` | On demand                       | Recent headlines                     | Sentiment score and themes                                      |
| Thesis Agent    | `thesis_agent.py`    | Per deep-dive                   | Research inputs                      | Bull/bear thesis narrative                                      |
| Industry Agent  | `industry_agent.py`  | Weekly per sector               | Sector name + news                   | Growth rates, margin benchmarks                                 |
| Valuation Agent | `valuation_agent.py` | Per DCF run                     | DCF output + comps                   | Assumption sanity check                                         |

**QoE Agent and DCF override gate:** When the QoE agent's normalized EBIT diverges from reported EBIT by more than 10%, `dcf_ebit_override_pending` is set to `true`. The PM must explicitly approve the adjusted EBIT in `config/valuation_overrides.yaml` before it flows into the DCF. The DCF never auto-updates from LLM output.

## Key Constraints (enforced, not negotiable)

1. LLM agents live in `src/stage_03_judgment/` only — never imported by `src/stage_00_data/`, `src/stage_01_screening/`, or `src/stage_02_valuation/`
2. `config/universe.csv` is the canonical ticker list — all pipelines read from it
3. All financial assumptions have `source_lineage` audit dict in output
4. `SECTOR_DEFAULTS` in `input_assembler.py` are fallbacks, not primaries — real data wins
5. The DCF does not auto-update from LLM outputs — PM approval required via `valuation_overrides.yaml`
6. `config/config.yaml` → `wacc_params` is the single source of truth for Rf and ERP

## What Codex Cannot See

Anything not in this repository does not exist from the agent's perspective.
Design decisions made in chat, Slack, or verbally must be encoded here.
See `docs/design-docs/core-beliefs.md` for the current list.

# ExecPlans

When writing complex features or significant refactors, use an ExecPlan (as described in .agent/PLANS.md) from design to implementation.
