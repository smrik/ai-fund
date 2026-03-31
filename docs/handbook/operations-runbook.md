# Operations Runbook

This runbook is for day-to-day usage and weekly refresh cycles.

## Environment Setup

1. Install dependencies:
```bash
python -m pip install -r requirements.txt
```

2. Configure secrets:
- Copy `.env.example` to `.env`
- Set the provider keys you actually use:
  - `GEMINI_API_KEY` or `GOOGLE_API_KEY`
  - `OPENAI_API_KEY` if using another OpenAI-compatible endpoint
  - `PERPLEXITY_API_KEY` for search-backed research flows
  - `FRED_API_KEY` for macro data

3. Initialize database:
```bash
python setup.py
```

## Core Command Set

### Local Dashboard Validation

Canonical local UI validation is host-side PowerShell, not WSL:

```powershell
ca ai-fund
python -m streamlit run dashboard/app.py --server.headless true --server.address 127.0.0.1 --server.port 8502 --browser.serverAddress 127.0.0.1 --browser.serverPort 8502
```

For the full Playwright smoke-test flow, see `docs/handbook/local-dashboard-validation.md`.

### Stage 1 Screen
```bash
python -m src.stage_01_screening.stage1_filter
```

Force fresh yfinance pull:
```bash
python -m src.stage_01_screening.stage1_filter --force
```

### Deterministic Batch Valuation

Run full batch with top table:
```bash
python -m src.stage_02_valuation.batch_runner --top 50
```

Single-name deep dive:
```bash
python -m src.stage_02_valuation.batch_runner --ticker HALO
```

Optional workbook export:
```bash
python -m src.stage_02_valuation.batch_runner --top 50 --xlsx
```

### CIQ Single-Ticker Refresh

Run this from the host PowerShell `ai-fund` environment, not WSL. It stages a ticker-specific workbook from `ciq/templates/ciq_cleandata.xlsx`, updates `financials_input.json`, refreshes the workbook in desktop Excel, then ingests the result into SQLite.

Explicit CIQ symbol:
```powershell
ca ai-fund
python -m ciq.ciq_refresh --ticker CALM --ciq-symbol NASDAQ:CALM
```

If the exchange prefix is simple and known:
```powershell
ca ai-fund
python -m ciq.ciq_refresh --ticker IBM --exchange NYSE
```

Notes:
- this requires desktop Excel plus the CIQ add-in to already be installed and signed in
- the source template workbook is `ciq/templates/ciq_cleandata.xlsx`
- the default staged workbook path is `data/exports/{TICKER}_Standard.xlsx`
- successful single-ticker runs also copy the workbook into `data/ciq_archive/{TICKER}_{as_of_date}_{timestamp}.xlsx`
- if automatic exchange inference is wrong or unavailable, pass `--ciq-symbol` explicitly
- if you only want to ingest an already-refreshed staged workbook, add `--no-refresh`

### Optional Legacy Memo Pipeline

```bash
python main.py AAPL
```

## Weekly Operating Cadence

Suggested cadence:

1. Sunday / pre-week
- Run Stage 1 screen
- Inspect universe size and sector distribution
- Refresh CIQ export pipeline if used

2. Start-of-week valuation snapshot
- Run batch valuation on current universe
- Verify output quality columns and coverage

3. Midweek analyst triage
- Review top-ranked names by upside
- Exclude rows with weak assumption-source integrity
- Apply QoE and industry context where needed

4. End-of-week review
- Compare movement in implied growth and WACC drivers
- Track promotions/demotions in watchlist

## Acceptance Gates

After each batch run, verify:
- Output coverage is non-zero and sensible
- Required columns exist (`growth_source`, `ebit_margin_source`, `implied_growth_pct`, `tv_high_flag`)
- SQLite `batch_valuations_latest` row count matches `latest.csv` rows

Quick gate snippet:
```bash
python -c "import pandas as pd; df=pd.read_csv('data/valuations/latest.csv'); print(len(df)); print(df[['growth_source','ebit_margin_source','implied_growth_pct','tv_high_flag']].head())"
```

## Incident Handling

### Symptom: many tickers skipped
Possible causes:
- Missing yfinance fields (`price`, `revenue_ttm`)
- Transient API/network instability

Action:
- Re-run batch
- Compare skipped names across runs
- If persistent, inspect ticker-level `get_market_data` output

### Symptom: extreme upside spikes
Possible causes:
- Unstable assumption fallback
- Very low current price with stale market data
- Terminal-value dominance

Action:
- Check assumption source columns
- Check `tv_pct_of_ev`, `tv_high_flag`
- Re-run on single ticker and inspect raw row JSON

### Symptom: WACC looks implausible
Possible causes:
- Missing peer beta context and fallback path
- Extreme debt/equity inputs

Action:
- Review WACC decomposition fields
- Compare raw beta and relevered beta
- Validate derived cost of debt from historicals

## Change Management

Before merging runbook-impacting changes:
1. Run `python -m pytest -q`
2. Run deterministic batch on limited subset (`--limit`)
3. Confirm CSV + SQLite persistence
4. Update handbook pages if output schema or process changed

## Data Hygiene Rules

- Treat `data/alpha_pod.db` as durable local state
- Treat `data/cache/*` as disposable refresh cache
- Treat `data/valuations/latest.csv` as regenerated artifact
- Keep generated artifacts out of git unless intentionally versioned


