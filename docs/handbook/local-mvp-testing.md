# Local MVP Testing Runbook

This is the practical day-to-day loop for using Alpha Pod as a local PM workstation.

Use this when you want to:

- bring up the React app and FastAPI backend
- refresh the screened universe and ranking
- load a ticker with CIQ data from Excel / S&P Capital IQ
- run agentic handoff profiles into the PM Queue
- review deterministic valuation output and Excel exports

## 1. Start The App

Run from host Windows PowerShell in the repo root:

```powershell
cd C:\Projects\03-Finance\ai-fund
conda activate ai-fund
pwsh -File .\scripts\manual\launch-mvp-app.ps1
```

The launcher starts:

- FastAPI: `http://127.0.0.1:8000`
- React/Vite: `http://127.0.0.1:5173`
- Watchlist: `http://127.0.0.1:5173/watchlist`

Keep that PowerShell window open while using the app. Press `Ctrl+C` to stop it.

Useful variants:

```powershell
pwsh -File .\scripts\manual\launch-mvp-app.ps1 -Open
pwsh -File .\scripts\manual\launch-mvp-app.ps1 -Status
pwsh -File .\scripts\manual\launch-mvp-app.ps1 -Stop
pwsh -File .\scripts\manual\launch-mvp-app.ps1 -Preview
pwsh -File .\scripts\manual\launch-mvp-app.ps1 -Reload
```

The script writes logs under ignored `.pwtmp/`:

- `.pwtmp/mvp-api.out.log`
- `.pwtmp/mvp-frontend.out.log`

If `python` on `PATH` is not the conda env, the script auto-detects `C:\Users\patri\miniconda3\envs\ai-fund\python.exe`.

Default operator mode runs FastAPI without uvicorn `--reload` so shutdown is cleaner. Use `-Reload` only for backend development.

If a restart says a port is already in use, run:

```powershell
pwsh -File .\scripts\manual\launch-mvp-app.ps1 -Stop
pwsh -File .\scripts\manual\launch-mvp-app.ps1 -Status
```

If `8000` is already serving FastAPI, the launcher reuses that backend and starts only the missing frontend. This handles the Windows case where `netstat` reports a listener PID but `taskkill` says the process does not exist.

If Windows still reports `Zugriff verweigert` for a stale PID, close the old PowerShell window that launched the app. As a last resort, run an elevated PowerShell and kill the reported PID:

```powershell
taskkill /PID <PID> /T /F
```

Temporary workaround if `8000` is occupied and you still want to work:

```powershell
pwsh -File .\scripts\manual\launch-mvp-app.ps1 -ApiPort 8011 -FrontendPort 5174
```

## 2. Refresh The Screened Universe

Run the broad deterministic screen:

```powershell
rtk python -m src.stage_01_screening.stage1_filter
```

Then rerun deterministic valuation for the saved universe or top names:

```powershell
rtk python -m src.stage_02_valuation.batch_runner --top 50 --xlsx
```

Primary outputs:

- `data/alpha_pod.db`
- `data/valuations/latest.csv`
- optional batch Excel under `data/valuations/`

Open `http://127.0.0.1:5173/watchlist` and sort/review by expected upside, base upside, quality flags, WACC, terminal-value dominance, and analyst-target spread. The watchlist is the starting point for deciding which names deserve CIQ-backed review.

## 3. Prepare CIQ Data For A Ticker

For a ticker you want to review, first write the JSON consumed by the CIQ template Power Query:

```powershell
rtk python scripts/manual/write_ciq_financials_input.py --ticker MSFT --ciq-symbol NASDAQ:MSFT
```

This writes:

```text
ciq/templates/financials_input.json
```

Then open Excel manually:

```text
ciq/templates/ciq_cleandata.xlsx
```

In Excel:

1. Make sure you are logged into the S&P Capital IQ add-in.
2. Refresh the workbook / Power Query connections.
3. Wait until CIQ formulas and Power Query finish loading.
4. Save the workbook.

The refreshed data lives in:

```text
ciq/templates/ciq_cleandata.xlsx
```

## 4. Ingest CIQ And Run Ticker Profiles

For a live UI test that writes into the app's PM Queue, omit `--isolated-db`:

```powershell
rtk python scripts/manual/run_ticker_valuation_flow.py --ticker MSFT --ingest-ciq-template --agent-mode heuristic --profiles comps_analysis company_analysis industry_analysis valuation_review risk_review
```

For a safer rehearsal that does not mutate the live queue, add `--isolated-db`:

```powershell
rtk python scripts/manual/run_ticker_valuation_flow.py --ticker MSFT --ingest-ciq-template --agent-mode heuristic --profiles comps_analysis --isolated-db
```

For live OpenRouter testing with a free model, use:

```powershell
rtk python scripts/manual/run_ticker_valuation_flow.py --ticker MSFT --ingest-ciq-template --use-openrouter-free --profiles comps_analysis company_analysis industry_analysis valuation_review risk_review
```

The run writes human-readable and JSON artifacts under:

```text
output/ticker_flows/
```

Check these fields in the run artifact:

- `source_quality` should be `real` for CIQ-backed comps
- CIQ lineage should include `source_file=ciq_cleandata.xlsx`
- queue item counts should match what appears in the PM Queue
- EDGAR cache coverage and EDGAR evidence used this run are separate checks

## 5. Review In The App

Open:

```text
http://127.0.0.1:5173/ticker/MSFT/valuation?view=Recommendations
```

Use the PM Queue to answer:

- What is the proposed model change?
- Which profile proposed it?
- Which evidence packet and observation support it?
- Does another profile touch the same deterministic field?
- What does preview resolve, skip, or conflict on?
- Is the item worth approving, rejecting, or deferring?

Recommended review order:

1. `Valuation -> Recommendations`: PM Queue, conflicts, preview, approve/reject/defer.
2. `Valuation -> DCF`: current IV, scenario IVs, WACC, growth, margins, exit multiple.
3. `Valuation -> Comparables`: CIQ comps, peer cleanup, multiples, source lineage.
4. `Audit`: run artifacts, evidence packets, exports, and data provenance.

Approval is preview-gated. If you edit an item after preview, preview again before approval.

## 6. Generate And Review Excel

The preferred path is the app export action from the ticker `Audit` page.

If you want the API command directly:

```powershell
curl -sS -X POST http://127.0.0.1:8000/api/tickers/MSFT/exports -H "Content-Type: application/json" -d "{\"format\":\"xlsx\",\"source_mode\":\"loaded_backend_state\"}"
```

The response includes an export id and paths. Generated ticker workbooks are written under:

```text
data/exports/generated/ticker/<TICKER>/
```

Review these sheets first:

- `Cover`
- `Assumptions`
- `DCF_Base`
- `DCF_Bear`
- `DCF_Bull`
- `Comps`
- `Comps Diagnostics`
- `Sensitivity`
- `Output`

The workbook should be treated as an audit/review artifact. The deterministic source of truth remains SQLite plus the Python valuation pipeline.

## 7. Practical Daily Loop

```text
Start app
-> Refresh screen and batch valuation
-> Pick highest-potential names from Watchlist
-> Write CIQ input JSON
-> Refresh and save ciq_cleandata.xlsx in Excel
-> Ingest CIQ template and run ticker profiles
-> Review PM Queue and conflicts
-> Approve only previewed, grounded changes
-> Review DCF / comps / audit
-> Export Excel and inspect workbook
-> Note finance/code issues discovered during review
```

For MVP testing, prefer small batches of one to three tickers. The point is to find finance-logic problems, data-quality issues, UI friction, and missing PM workflow features before making the system broader or cleverer.
