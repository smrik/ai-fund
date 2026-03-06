# Engineering Deep Dive

This guide explains how the codebase is organized, why data is stored in multiple formats, and how to extend the system safely.

## Repository Map

Core implementation areas:
- `src/data/`: market and filing data adapters
- `src/valuation/`: deterministic valuation orchestration and WACC
- `src/templates/`: valuation and memo data models
- `src/agents/`: LLM-based research/context agents
- `screening/`: Stage 1 and Stage 2 universe filters
- `db/`: SQLite schema and initialization
- `config/`: central config loader and YAML defaults

## Architectural Boundary

Deterministic compute path:
- `screening/stage1_filter.py`
- `src/data/market_data.py`
- `src/valuation/wacc.py`
- `src/templates/dcf_model.py`
- `src/valuation/batch_runner.py`

Judgment/context path:
- `src/agents/*` (QoE, industry, memo synthesis agents)

Design rule:
- Deterministic outputs should remain reproducible without LLM calls.

## Data Storage Strategy: Why JSON + CSV + SQLite

Alpha Pod intentionally uses three storage forms for different jobs.

### 1) JSON (`data/cache/yfinance_info.json`)
Use case:
- Fast cache of raw-ish API snapshots for low-friction refresh

Why JSON here:
- Nested shape matches source payloads
- Cheap to overwrite in batches
- Easy debug and resume

Tradeoff:
- Weak for relational queries and history analysis

### 2) CSV (`data/valuations/latest.csv`, stage outputs)
Use case:
- Human portability and Excel interoperability

Why CSV here:
- Universal format for analysts
- Easy ingestion into Power Query and ad hoc scripts

Tradeoff:
- No constraints, no indexes, no multi-table integrity

### 3) SQLite (`data/alpha_pod.db`)
Use case:
- Canonical persistence, history, and queryable state

Why SQLite here:
- Transactional, local, zero-admin
- Good fit for periodic batch snapshots
- Supports indexing, uniqueness constraints, and audit queries

Tradeoff:
- Requires schema discipline

Practical rule:
- SQLite is source-of-truth.
- CSV is export convenience.
- JSON is input cache.

## Config System

Single committed config source:
- `config/config.yaml`

Runtime loader:
- `config/__init__.py`

Compatibility shim:
- `config/settings.py` re-exports values for older imports

Precedence model:
1. YAML defaults
2. Optional environment overrides (`.env`)

This keeps committed behavior explicit while allowing machine-local secret/runtime overrides.

## Key Deterministic Module Contracts

### `src/data/market_data.py`
- `get_market_data(ticker) -> dict`
- `get_historical_financials(ticker) -> dict` with derived 3Y metrics
- Never raises outward on common data failures (returns null-friendly fields)

### `src/valuation/wacc.py`
- `compute_wacc(target, peers) -> WACCResult`
- Pure math/data transforms, deterministic for a given input set

### `src/templates/dcf_model.py`
- `run_dcf(base_revenue, assumptions) -> DCFResult`
- `run_scenario_dcf(...) -> {bear, base, bull}`

### `src/valuation/batch_runner.py`
- `value_single_ticker(ticker) -> row dict | None`
- `run_batch(...)` for universe execution and persistence

## Agent Layer Contracts

### Base agent runtime
- `src/agents/base_agent.py`
- Anthropic message loop + optional tool-calling

### QoE agent
- Reads 10-K text via EDGAR client
- Returns strict normalization contract with signed adjustment list
- Safe fallback if parsing/model output fails

### Industry agent
- Weekly benchmark synthesis
- Cache key: `(sector, industry, week_key)` in SQLite
- Supports `force_refresh`

## Legacy Memo Orchestration Track

`src/pipeline/orchestrator.py` runs a 6-agent narrative pipeline from CLI (`main.py`).

Recommendation:
- Keep it as a research synthesis tool.
- Keep deterministic ranking as primary production decision input.

## Extension Patterns

### Add a new deterministic factor
1. Add data extraction in `market_data.py` or dedicated data module
2. Add assumption resolution in `batch_runner.py`
3. Add output column(s)
4. Add tests for fallback behavior and output schema

### Add a new agent
1. Subclass `BaseAgent`
2. Define strict output contract
3. Add schema-level normalization and fallback path
4. Persist outputs in dedicated table if needed

### Add new DB table
1. Update `db/schema.py` with `CREATE TABLE IF NOT EXISTS`
2. Add indexes for key query patterns
3. Add tests that exercise insert/read behavior

## Engineering Risk Register (Current)

1. Mixed architecture maturity
- Deterministic batch path is crisp
- Legacy full-memo path still coexists and can blur source-of-truth for newcomers

2. Runtime coupling to yfinance field availability
- Missing fields trigger fallbacks
- Good for robustness, but can silently degrade assumption quality

3. Limited deterministic acceptance gates around agent overlays
- QoE/industry context exists
- Hard deterministic promotion gates for those overlays should remain explicit

## Recommended Engineering Conventions

- Prefer pure functions for valuation math
- Keep assumption-source fields in outputs
- Add range checks near data ingress
- Make all fallbacks explicit and test-covered
- Keep CLI outputs friendly, but never as primary persistence
