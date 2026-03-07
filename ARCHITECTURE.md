# Architecture — Alpha Pod

## The Three-Layer Model

```
┌─────────────────────────────────────────────────────┐
│  JUDGMENT LAYER — LLM agents, used selectively      │
│  QoE Agent | Comps Agent | Industry Agent | Scenario │
│  Input: structured data  Output: typed dataclasses   │
└──────────────────────┬──────────────────────────────┘
                       │ one-way: agents consume, never modify
┌──────────────────────▼──────────────────────────────┐
│  COMPUTATION LAYER — deterministic, no LLM          │
│  DCF model | WACC calculator | Batch runner          │
│  Screening filters | Risk calculations               │
└──────────────────────┬──────────────────────────────┘
                       │ one-way: compute reads, never writes back
┌──────────────────────▼──────────────────────────────┐
│  DATA LAYER — deterministic, no LLM                 │
│  yfinance | CIQ (Excel/xlwings) | EDGAR | IBKR       │
│  SQLite DB | CSV cache                               │
└─────────────────────────────────────────────────────┘
```

**The invariant:** Data flows downward only. The computation layer never calls an LLM. The data layer never calls an LLM. This separation is what makes the system auditable and the valuations reproducible.

---

## Package Map

### Data Layer (`src/stage_00_data/`, `ciq/`, `ibkr/`)

| Module | Purpose | Data source |
|---|---|---|
| `src/stage_00_data/market_data.py` | Price, TTM financials, multiples, 3yr historical | yfinance |
| `src/stage_00_data/edgar_client.py` | 10-K/10-Q filing text, MD&A, risk factors | SEC EDGAR API |
| `ciq/ciq_refresh.py` | Fundamental data refresh via Excel plugin | Capital IQ |
| `ibkr/` | Live prices, positions, execution | Interactive Brokers TWS |
| `db/` | SQLite persistence, schema, loader, queries | Local |

**Data freshness:**
- yfinance: pulled on demand, cached 3 days (`data/cache/yfinance_info.json`)
- CIQ: refreshed weekly on Sunday, loaded to `data/alpha_pod.db`
- EDGAR: pulled per filing event, cached in `data/edgar/`
- IBKR: real-time during market hours (Phase 3)

### Computation Layer (`src/stage_01_screening/`, `src/stage_02_valuation/`)

| Module | Purpose |
|---|---|
| `src/stage_02_valuation/templates/dcf_model.py` | 10-year DCF, bear/base/bull scenarios |
| `src/stage_02_valuation/wacc.py` | CAPM + Hamada unlevering/relevering, size premia |
| `src/stage_02_valuation/batch_runner.py` | Rank full universe by DCF upside |
| `src/stage_01_screening/stage1_filter.py` | MCap/ROE/volume screen → ~300 survivors |
| `src/stage_01_screening/stage2_filter.py` | CIQ deep screen → ~50 names for active research |

**Computation rules:**
- All monetary values in absolute USD (not millions) inside functions; converted for display only
- Sector defaults in `batch_runner.SECTOR_ASSUMPTIONS` are fallbacks — actual data wins
- Every output record includes `assumption_source_*` audit fields
- WACC uses Damodaran ERP (5.0%) and Duff & Phelps size premia — update annually

### Judgment Layer (`src/stage_03_judgment/`)

| Agent | Model | Frequency | Blocking? |
|---|---|---|---|
| `qoe_agent.py` | claude-haiku-4-5 | Per 10-K | No — runs async, adjusts margin |
| `comps_agent.py` | claude-haiku-4-5 | Per CIQ refresh | No — provides peer set for WACC |
| `industry_agent.py` | claude-sonnet-4-6 | Weekly per sector | No — cached, consumed by batch runner |
| `scenario_agent.py` | claude-sonnet-4-6 | Per ticker + news | No — replaces generic DCF scalars |

All agents inherit from `src/stage_03_judgment/base_agent.py`.
All agents return typed dataclasses — no raw dict outputs that leak into the compute layer.

### Orchestration (`src/stage_04_pipeline/`)

| Script | Schedule | What it does |
|---|---|---|
| `src/stage_04_pipeline/daily_refresh.py` | 6:00 AM weekdays | Prices → positions → risk report |
| `src/stage_01_screening/stage1_filter.py` | Sunday 6 PM | Full universe screen |
| `ciq/ciq_refresh.py` | Sunday 6 PM (after Stage 1) | CIQ data refresh → DB |

---

## Dependency Rules

Allowed imports (enforced by convention, to be enforced by linter):

```
src/stage_03_judgment/     → src/stage_00_data/, src/stage_02_valuation/templates/, src/stage_02_valuation/ (read-only)
src/stage_02_valuation/  → src/stage_00_data/, src/stage_02_valuation/templates/
src/stage_02_valuation/templates/  → nothing (pure computation)
src/stage_00_data/       → nothing (external APIs only)
src/stage_01_screening/      → src/stage_00_data/, db/
src/stage_04_pipeline/       → src/stage_02_valuation/, src/stage_03_judgment/, src/stage_00_data/, db/
```

**Never allowed:**
- `src/stage_00_data/` importing from `src/stage_03_judgment/`
- `src/stage_02_valuation/` importing from `src/stage_03_judgment/`
- `src/stage_02_valuation/templates/` importing from anywhere in `src/`

---

## Data Flow: A Name Through the Full Pipeline

```
[NASDAQ listing API]
        │
        ▼
[Stage 1 screen] — MCap, ROE, volume, sector filters
        │ ~300 survivors → config/universe.csv
        ▼
[CIQ refresh] — multi-year financials, estimates, ~50 peer suggestions
        │ → data/alpha_pod.db (ciq_fundamentals table)
        ▼
[QoE Agent] — reads 10-K, adjusts EBIT margin for one-time items
        │ → QoEResult (adjusted_ebit_margin, one_time_items)
        ▼
[Comps Matching Agent] — scores CIQ peer list, selects 5-10
        │ → CompsResult (peer tickers, suggested_exit_multiple)
        ▼
[Batch DCF Runner] — WACC + 10-year DCF with bear/base/bull
        │ → data/valuations/latest.csv + dated Excel
        ▼
[Stage 2 screen] — filter batch output by upside, quality, coverage
        │ → ~50 names for active research
        ▼
[Scenario Agent] — named scenarios from 10-K risk factors + news
        │ → ScenarioSet (replaces generic ±40% stress)
        ▼
★ HUMAN CHECKPOINT ★
  Review ranked list, set assumptions, write variant perception
        │
        ▼
[Risk check] — position limits, gross/net exposure, liquidity
        │
        ▼
[Execution] — IBKR API, TWAP/VWAP (Phase 3)
```

---

## Key Parameters (update annually)

| Parameter | Value | Source | Last updated |
|---|---|---|---|
| Risk-free rate | 4.5% | 10Y US Treasury | 2026-03 |
| Equity risk premium | 5.0% | Damodaran | 2026-03 |
| Default tax rate | 21.0% | US corporate | 2026-03 |
| Default cost of debt | 6.0% | BBB spread (fallback) | 2026-03 |
| Stage 1 MCap range | $500M–$10B | Config | 2026-03 |
| Stage 1 min ROE | 12% | Config | 2026-03 |
