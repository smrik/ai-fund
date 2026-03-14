# Architecture — Alpha Pod

## The Three-Layer Model

```
┌─────────────────────────────────────────────────────────────┐
│  JUDGMENT LAYER — LLM agents, used selectively              │
│  QoE Agent | Earnings Agent | Filings Agent | Risk Agent    │
│  Sentiment Agent | Thesis Agent | Industry Agent            │
│  Valuation Agent                                            │
│  Input: structured data   Output: typed dicts               │
└──────────────────────┬──────────────────────────────────────┘
                       │ one-way: agents consume, never modify
┌──────────────────────▼──────────────────────────────────────┐
│  COMPUTATION LAYER — deterministic, no LLM                  │
│  professional_dcf.py | input_assembler.py | wacc.py         │
│  batch_runner.py | story_drivers.py                         │
│  Screening filters | Risk calculations                       │
└──────────────────────┬──────────────────────────────────────┘
                       │ one-way: compute reads, never writes back
┌──────────────────────▼──────────────────────────────────────┐
│  DATA LAYER — deterministic, no LLM                         │
│  yfinance | CIQ (SQLite via xlwings) | EDGAR | IBKR         │
│  market_data.py | ciq_adapter.py | edgar_client.py          │
└─────────────────────────────────────────────────────────────┘
```

**The invariant:** Data flows downward only. The computation layer never calls an LLM. The data layer never calls an LLM. This separation makes valuations reproducible and auditable.

---

## Package Map

### Data Layer (`src/stage_00_data/`)

| Module | Purpose | Data source |
|---|---|---|
| `market_data.py` | Price, TTM financials, multiples, 3yr historical (revenue, net_income, cffo, capex, da) | yfinance |
| `edgar_client.py` | 10-K/10-Q filing text, MD&A, risk factors via EDGAR full-text index | SEC EDGAR API |
| `ciq_adapter.py` | CIQ snapshot (fundamentals, NWC, ROIC, forward estimates), comps valuation, NWC history | SQLite `data/alpha_pod.db` |

**`ciq_adapter.py` key functions:**
- `get_ciq_snapshot(ticker)` — returns TTM snapshot including `revenue_fy1`, `revenue_fy2` (consensus estimates), `roic_ltm`, DSO/DIO/DPO, `revenue_ttm`
- `get_ciq_comps_valuation(ticker)` — returns peer median multiples including forward (`tev_ebitda_fwd`, `tev_ebit_fwd`) and LTM; requires CIQ comps snapshot in DB
- `get_ciq_nwc_history(ticker)` — returns list of up to 3 dicts (newest first) with `{period_date, dso, dio, dpo}` for NWC drift analysis

**`market_data.py` key functions:**
- `get_market_data(ticker)` — sector, price, beta, market cap, net debt, ebitda_ttm, shares_outstanding
- `get_historical_financials(ticker)` — lists of annual values: `revenue`, `operating_income`, `net_income`, `cffo`, `capex`, `da`

**Data freshness:**
- yfinance: pulled on demand, cached 3 days (`data/cache/yfinance_info.json`)
- CIQ: refreshed weekly on Sunday, loaded to `data/alpha_pod.db`
- EDGAR: pulled per-ticker on demand, not cached to disk (10-K text only)
- IBKR: real-time during market hours (Phase 3)

### Computation Layer (`src/stage_01_screening/`, `src/stage_02_valuation/`)

| Module | Purpose |
|---|---|
| `src/stage_02_valuation/input_assembler.py` | Assembles `ForecastDrivers` from CIQ/yfinance/defaults with full source lineage |
| `src/stage_02_valuation/professional_dcf.py` | 10-year two-stage DCF, FCFE branch, EV-to-equity bridge, EP cross-check, reverse DCF |
| `src/stage_02_valuation/wacc.py` | CAPM + Hamada unlevering/relevering, Duff & Phelps size premia; Rf/ERP from `config/config.yaml` |
| `src/stage_02_valuation/batch_runner.py` | Rank full universe by DCF upside, writes Excel + CSV |
| `src/stage_02_valuation/story_drivers.py` | Loads story driver overrides from `config/valuation_overrides.yaml` |
| `src/stage_01_screening/stage1_filter.py` | MCap/ROE/volume screen → ~300 survivors |
| `src/stage_01_screening/stage2_filter.py` | CIQ deep screen → ~50 names for active research |

**`input_assembler.py` assumption priority chains:**

| Assumption | Priority order |
|---|---|
| Near-term revenue growth | CIQ consensus FY1/FY2 → CIQ 3yr CAGR → yfinance 3yr CAGR → yfinance TTM YoY → sector default |
| Exit multiple (EV/EBITDA) | CIQ comps forward median → CIQ comps LTM median → sector default |
| Exit multiple (EV/EBIT) | CIQ comps forward EBIT median → CIQ comps LTM EBIT median → sector default |
| RONIC terminal | CIQ ROIC → sector default |
| NWC start (DSO/DIO/DPO) | CIQ snapshot → yfinance → sector default |
| NWC target (DSO/DIO/DPO) | 70% sector default + 30% company start (when company data available) → pure sector default |
| Tax rate target | `bounded(company_ETR, 15%, 30%, 23%)` — company's own rate as convergence target |
| Growth fade ratio | `SECTOR_DEFAULTS[sector]["growth_fade_ratio"]` (Tech 0.70, Energy 0.50) |
| Terminal growth | `SECTOR_DEFAULTS[sector]["terminal_growth"]` (Tech 3.5%, Utilities 2.5%) |

Every assumption is tracked in `source_lineage` in the output.

**Computation rules:**
- All monetary values in absolute USD (not millions) inside functions; converted for display only
- `SECTOR_DEFAULTS` in `input_assembler.py` are fallbacks — actual data always wins
- Every output record includes full `source_lineage` audit dict
- WACC Rf/ERP configurable in `config/config.yaml` → `wacc_params` section
- Override YAML (`config/valuation_overrides.yaml`) loaded with `@lru_cache` for batch performance

### Judgment Layer (`src/stage_03_judgment/`)

| Agent | File | Purpose | Primary trigger |
|---|---|---|---|
| **QoE Agent** | `qoe_agent.py` | Quality of earnings: EBIT normalization, signal explanations, revenue recognition flags, auditor flags | Per ticker before DCF |
| Earnings Agent | `earnings_agent.py` | Earnings call transcript analysis | Post earnings |
| Filings Agent | `filings_agent.py` | 10-K/10-Q MD&A analysis | Per filing event |
| Risk Agent | `risk_agent.py` | Risk factor extraction and scoring | Per 10-K |
| Sentiment Agent | `sentiment_agent.py` | News and social sentiment | On demand |
| Thesis Agent | `thesis_agent.py` | Investment thesis synthesis | Per deep-dive |
| Industry Agent | `industry_agent.py` | Sector growth rates, margin benchmarks | Weekly per sector |
| Valuation Agent | `valuation_agent.py` | Sanity-checks DCF assumptions vs comps | Per DCF run |

All agents inherit from `base_agent.py` (wraps Anthropic SDK).

**The QoE Agent is the most integrated** — it feeds `dcf_ebit_override_pending` and `normalized_ebit` for PM review before DCF assumptions are finalized. See `docs/handbook/qoe-agent.md`.

### Orchestration (`src/stage_04_pipeline/`)

| Script | Schedule | What it does |
|---|---|---|
| `src/stage_04_pipeline/daily_refresh.py` | 6:00 AM weekdays | Prices → positions → risk report |
| `src/stage_01_screening/stage1_filter.py` | Sunday 6 PM | Full universe screen |
| `ciq/ciq_refresh.py` | Sunday 6 PM (after Stage 1) | CIQ data refresh → DB |

---

## Dependency Rules

Allowed imports (enforced by convention):

```
src/stage_03_judgment/    → src/stage_00_data/, src/stage_02_valuation/ (read-only)
src/stage_02_valuation/   → src/stage_00_data/
src/stage_00_data/        → nothing (external APIs only)
src/stage_01_screening/   → src/stage_00_data/, db/
src/stage_04_pipeline/    → src/stage_02_valuation/, src/stage_03_judgment/, src/stage_00_data/, db/
```

**Never allowed:**
- `src/stage_00_data/` importing from `src/stage_03_judgment/`
- `src/stage_02_valuation/` importing from `src/stage_03_judgment/`
- LLM calls anywhere in `src/stage_00_data/` or `src/stage_02_valuation/`

---

## Data Flow: A Name Through the Full Pipeline

```
[Universe seed — config/universe.csv]
        │
        ▼
[Stage 1 screen] — MCap $500M–$10B, ROE ≥12%, volume ≥100K, no Fins/Utilities/RE
        │ ~300 survivors
        ▼
[CIQ refresh] — fundamentals, estimates, NWC, comps, ROIC
        │ → data/alpha_pod.db
        ▼
[Input Assembler] — resolves all DCF assumptions with source lineage
        │ consensus growth | forward comps multiples | NWC blend | company ETR
        ▼
[QoE Agent] — EBIT normalization via 10-K analysis + deterministic signals
        │ → dcf_ebit_override_pending flag; PM reviews and approves via valuation_overrides.yaml
        ▼
[Batch DCF Runner] — WACC + 10-year DCF, bear/base/bull, EP cross-check, reverse DCF
        │ → data/valuations/latest.csv + dated Excel
        ▼
[Stage 2 screen] — filter by upside, quality score, coverage
        │ → ~50 names for active research
        │
        ▼
★ HUMAN CHECKPOINT ★
  Review ranked list, check source lineage, override assumptions if needed
        │
        ▼
[Other Agents on demand] — Earnings, Filings, Risk, Sentiment, Thesis, Industry
        │
        ▼
[Risk check] — position limits, gross/net exposure, liquidity
        │
        ▼
[Execution] — IBKR API (Phase 3)
```

---

## Key Parameters (update annually)

| Parameter | Value | Location | Last updated |
|---|---|---|---|
| Risk-free rate | 4.5% | `config/config.yaml` → `wacc_params.risk_free_rate` | 2026-03 |
| Equity risk premium | 5.0% | `config/config.yaml` → `wacc_params.equity_risk_premium` | 2026-03 |
| Default tax rate | 21.0% | `src/stage_02_valuation/wacc.py` | 2026-03 |
| Default cost of debt | 6.0% | `src/stage_02_valuation/wacc.py` | 2026-03 |
| Stage 1 MCap range | $500M–$10B | `config/settings.py` | 2026-03 |
| Stage 1 min ROE | 12% | `config/settings.py` | 2026-03 |
