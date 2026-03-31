# End-to-End Workflow

This page explains the operational flow from ticker universe to reviewed valuation output.

## What The Pipeline Produces

Primary output artifacts:

- `data/alpha_pod.db` table `batch_valuations_latest` (canonical latest snapshot)
- `data/alpha_pod.db` table `valuations` (historical valuation metrics by date)
- `data/valuations/latest.csv` (flat export for Excel/Power Query)
- Optional `data/valuations/batch_valuation_YYYY-MM-DD.xlsx` when `--xlsx` is used

## High-Level Process

```mermaid
flowchart LR
    U["Seed Universe"] --> S1["Stage 1 Filter\nsrc/stage_01_screening/stage1_filter.py"]
    S1 --> UC["config/universe.csv"]
    UC --> BR["Batch Runner\nsrc/stage_02_valuation/batch_runner.py"]

    BR --> MD["Market Data\nsrc/stage_00_data/market_data.py"]
    BR --> WF["WACC\nsrc/stage_02_valuation/wacc.py"]
    BR --> DF["DCF + Scenarios\nsrc/stage_02_valuation/templates/dcf_model.py"]
    BR --> RD["Reverse DCF"]

    BR --> SQL["SQLite\nbatch_valuations_latest + valuations"]
    BR --> CSV["data/valuations/latest.csv"]
    BR --> XLSX["Optional Excel Export"]

    SQL --> PM["PM Review"]
    CSV --> PM
    XLSX --> PM
```

## Stage 1: Universe Filtering (Fast, Broad)

Entry point: `python -m src.stage_01_screening.stage1_filter`

Goal:

- Reduce initial listing universe to a manageable quality subset
- Keep filters broad enough to avoid dropping interesting names too early

Core filters in `src/stage_01_screening/stage1_filter.py`:

- Market cap band: $500M to $10B
- ROE floor: >= 12%
- Profitability: positive net income
- Liquidity: average volume threshold
- Exclusions: Financials, Utilities, Real Estate
- Geography: US bias

Design choices:

- Uses yfinance cache (`data/cache/yfinance_info.json`) to reduce API churn
- Applies fast pre-filter before yfinance calls to lower network cost
- Writes survivors to `config/universe.csv` for downstream deterministic valuation

## Stage 2: Deterministic Valuation Batch

Entry point: `python -m src.stage_02_valuation.batch_runner --top 50`

Per ticker sequence inside `value_single_ticker()`:

1. Pull market and financial snapshot (`get_market_data`)
2. Pull historical 3-year financial series (`get_historical_financials`)
3. Compute WACC using CAPM + unlevered/relevered beta (`compute_wacc_from_yfinance`)
4. Build DCF assumptions with source audit fields
5. Run base/bear/bull DCF
6. Run reverse DCF (implied growth at current price)
7. Emit one row with full assumptions + outputs + quality flags

## Optional CIQ Workbook Refresh Path

Entry point: `python -m ciq.ciq_refresh --ticker CALM --ciq-symbol NASDAQ:CALM`

This is the host-Windows Excel path for refreshing CIQ workbook data into SQLite.

Per ticker sequence:

1. Update `ciq/templates/financials_input.json` with the target CIQ symbol and date
2. Copy `ciq/templates/ciq_cleandata.xlsx` to `data/exports/{TICKER}_Standard.xlsx`
3. Open the staged workbook in desktop Excel via `xlwings`
4. Trigger workbook refresh and wait for async query completion
5. Save and close the workbook
6. Copy the refreshed staged workbook into `data/ciq_archive/` using ticker + date + timestamp
7. Run deterministic CIQ workbook ingest into SQLite

Important:

- this is separate from the Power Query JSON review path
- this should be run from host PowerShell, not WSL
- the safest operator path is passing `--ciq-symbol` explicitly when there is any doubt about exchange prefix

## Assumption Source Priority (Per Ticker)

The deterministic layer uses explicit priority order:

- EBIT margin:
  1. 3-year average operating margin
  2. TTM operating margin
  3. Sector default

- Revenue growth:
  1. 3-year revenue CAGR (bounded)
  2. TTM revenue growth (bounded)
  3. Sector default

- Capex and D&A percentages:
  1. 3-year averages (within sanity bands)
  2. Sector defaults

- Tax rate:
  1. 3-year effective tax average (bounded)
  2. 21% US fallback

## Output Contract For Ranking

Every valuation row includes:

- Identity, sector, and core market metrics
- WACC decomposition fields
- Bear/base/bull intrinsic values
- Upside and margin-of-safety
- Assumption values and assumption sources
- Reverse DCF implied growth
- `tv_pct_of_ev` and `tv_high_flag` to detect terminal-value dominance

## Persistence And Consumption

`run_batch()` persistence behavior:

- Writes full latest snapshot to `batch_valuations_latest` (replace)
- Upserts normalized valuation history into `valuations`
- Writes `latest.csv` every run
- Optional multi-tab Excel for manual review

Operational logging behavior:

- `batch_runner.py` now routes lifecycle, warning, and export-path diagnostics through the shared CLI logging setup in `src/logging_config.py`
- the operator-facing summary remains concise, while `ALPHA_POD_LOG_FILE` can capture machine-readable JSON log lines for debugging and audit trails

Practical usage pattern:

- Use SQLite as system-of-record for analytics and automation
- Use `latest.csv` as convenience bridge to Excel review workflows

## Optional Judgment Layer

Judgment agents (`src/stage_03_judgment/`) consume deterministic outputs and external text context.

Current specialized modules:

- `qoe_agent.py`: normalize EBIT from 10-K text
- `industry_agent.py`: weekly sector benchmarks cached in SQLite

Guardrail:

- Agent outputs should be treated as contextual overlays unless promoted through a deterministic acceptance rule.

## Dashboard Shell

The Streamlit dashboard remains available as a transitional review surface for the valuation workflow.

Current shell model:

- `Overview` for the cross-functional cockpit
- `Valuation` for DCF, comparables, and multiples
- `Market` for macro, revisions, sentiment, and factor context
- `Research` for the working research board and dossier-backed note blocks
- `Audit` for pipeline review, filings evidence, exports, and operational checks
  - `Audit -> Batch Funnel` is the default no-memo landing surface and restores the latest saved deterministic universe watchlist on load.
  - The primary table is the full ranked universe watchlist with current price, scenario IVs, expected IV, analyst target, and latest archived PM stance metadata.
  - Deterministic batch refresh is manual. Use it to overwrite the saved watchlist from `config/universe.csv` or an ad hoc ticker subset.
  - Deep analysis stays explicit and cost-aware: open the latest archived snapshot for a ticker when it exists, or manually run deep analysis only for the focused ticker or selected shortlist when needed.

The dossier companion is available as a right-side collapsible rail from loaded-ticker pages. Use the `Show Notes Rail` toggle in the shell header to open or close it without leaving the current analysis page.

## Transitional UI Surfaces

Alpha Pod currently has two operator-facing shells during the quote-terminal migration:

- `dashboard/app.py`
  - Streamlit stabilization path
  - default no-memo landing remains `Audit -> Batch Funnel`
  - loaded tickers use a compact strip on non-`Overview` pages
  - `Valuation` now exposes `Assumptions`, `WACC`, and `Recommendations` as first-class visible subviews
- `frontend/`
  - React + TypeScript + Vite quote-terminal scaffold
  - strategic shell for the migration and the primary export surface
  - routes:
    - `/watchlist`
    - `/ticker/:ticker/overview`
    - `/ticker/:ticker/valuation`
    - `/ticker/:ticker/market`
    - `/ticker/:ticker/research`
    - `/ticker/:ticker/audit`
  - uses the thin FastAPI layer in `api/`
  - `Audit` is the canonical ticker export hub
  - `/watchlist` exposes explicit batch Excel and HTML export actions
  - `Valuation` and `Research` expose contextual export shortcuts

Local development commands:

```bash
python -m uvicorn api.main:app --reload
npm --prefix frontend run dev
python -m streamlit run dashboard/app.py
```

Migration guardrails:

- keep business logic in `src/stage_04_pipeline/`, `src/stage_03_judgment/`, and `src/stage_02_valuation/`
- keep `api/` as a transport layer only
- do not duplicate valuation logic in the frontend

## Legacy Full-Memo Path

`main.py` -> `PipelineOrchestrator` runs a 6-agent IC memo pipeline.

Use case:

- Narrative synthesis, thesis articulation, and decision memo drafting

Caution:

- This path is useful for research context but should not replace deterministic ranking outputs as the source of truth for intrinsic values.

## End-to-End Operator Checklist

1. Refresh/seed universe if needed
2. Run Stage 1 screen and inspect survivor count
3. Run batch valuation (`--top` and optional `--xlsx`)
   - dashboard alternative: `Audit -> Batch Funnel`, which auto-restores the latest saved watchlist before you refresh
4. Verify required output columns and coverage
5. Review highest-upside names with `tv_high_flag`, implied growth, and WACC reasonableness
6. Optionally overlay QoE/industry context for final PM judgment


