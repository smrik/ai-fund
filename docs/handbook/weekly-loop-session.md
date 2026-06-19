# Weekly Loop Session

This is the CLI-first Milestone 1 loop for one real ticker. It is PM-driven: agents prepare evidence and proposals, but the PM is the only approval authority for model changes.

## One-Ticker Guided Workup

Recommended command for a real session:

```powershell
C:\Users\patri\miniconda3\envs\ai-fund\python.exe scripts/manual/run_guided_ticker_workup.py --ticker MSFT --ciq-symbol NASDAQ:MSFT
```

This command uses live agents and the live Alpha Pod SQLite DB by default. Use the safe rehearsal command first when validating mechanics, or add `--isolated-db` when you want a disposable queue/model review.

The command runs this sequence:

1. Stage `financials_input.json` and the ticker CIQ workbook.
2. Pause while the PM refreshes and saves the workbook in Excel.
3. Ingest the refreshed CIQ workbook.
4. Prefetch/check EDGAR filings.
5. Build the initial deterministic valuation.
6. Run each Agentic Handoff Profile one at a time.
7. After each profile, write a durable profile review packet and show evidence plus new PM Decision Queue items.
8. Let the PM approve/apply, edit target values, reject, defer, or skip.
9. Rebuild the deterministic valuation after applied changes.
10. Write the final bundle and a friction-log draft.

Outputs:

- `output/guided_workups/<TICKER>/<TICKER>-<timestamp>.json`
- `output/guided_workups/<TICKER>/<TICKER>-<timestamp>.md`
- `output/guided_workups/<TICKER>/<TICKER>-<timestamp>-<profile>-review.md`
- `output/guided_workups/<TICKER>/<TICKER>-<timestamp>-analyst-prep.md`
- optional Excel export from the existing ticker export path
- `docs/reviews/weekly-loop/<date>-<TICKER>-friction-draft.md`

At each profile pause, open the printed `Review packet:` path before answering the action prompt. The packet is the PM-facing review surface for that profile: observations, PM questions, sample evidence, queue items, proposed assumption changes, and deterministic preview impact.

Each packet also prints standalone queue commands for the item. Use them when you want to review or decide later without rerunning the profile loop:

```powershell
C:\Users\patri\miniconda3\envs\ai-fund\python.exe scripts/manual/pm_decision_queue.py --ticker BAH list
C:\Users\patri\miniconda3\envs\ai-fund\python.exe scripts/manual/pm_decision_queue.py --ticker BAH review-index
C:\Users\patri\miniconda3\envs\ai-fund\python.exe scripts/manual/pm_decision_queue.py --ticker BAH preview --item-id 88
C:\Users\patri\miniconda3\envs\ai-fund\python.exe scripts/manual/pm_decision_queue.py --ticker BAH defer --item-id 88 --reason "Needs PM review"
C:\Users\patri\miniconda3\envs\ai-fund\python.exe scripts/manual/pm_decision_queue.py --ticker BAH edit-target --item-id 88 --target exit_multiple=9.25
C:\Users\patri\miniconda3\envs\ai-fund\python.exe scripts/manual/pm_decision_queue.py --ticker BAH approve-apply --item-id 88 --confirm APPLY
```

`review-index` writes `output/guided_workups/<TICKER>/<TICKER>-queue-review-index.md`. Treat that as the "start here" page after a run: it links the latest Analyst Prep and JSON bundle, groups current queue items by status, includes the profile review packet when one exists, and prints type-appropriate decision commands. Pending or previewed assumption-change packs show preview/edit/approve-apply commands. Pending or previewed advisory findings only show defer/reject commands because they do not directly mutate the deterministic model. Deferred, rejected, approved, or applied items are shown for context but do not print mutation commands.

For model review in Excel, write the valuation JSON and stage the PowerQuery workbook:

```powershell
$env:ALPHA_POD_MARKET_CACHE_ONLY='1'; $env:ALPHA_POD_ALLOW_STALE_MARKET_CACHE='1'; C:\Users\patri\miniconda3\envs\ai-fund\python.exe -m src.stage_02_valuation.batch_runner --ticker BAH --json
C:\Users\patri\miniconda3\envs\ai-fund\python.exe scripts/manual/stage_excel_model_workbook.py --ticker BAH
```

This copies `templates/20260614_template-GPT.xlsx`, points `Config!B2` at `data/valuations/json/<TICKER>_latest.json`, preserves the workbook's `_Data` PowerQuery package, and seeds the flat `HistoricalFinancials` table plus Base/Bear/Bull historical review blocks from the latest JSON. Open the staged workbook and use **Data -> Refresh All** when you want Excel PowerQuery to refresh the existing `_Data` tables from the same JSON path.

## Safe Rehearsal

Use this before a real session or when validating mechanics:

```powershell
C:\Users\patri\miniconda3\envs\ai-fund\python.exe scripts/manual/run_guided_ticker_workup.py --ticker MSFT --agent-mode heuristic --isolated-db --non-interactive --skip-ciq-stage --edgar-summary-only --market-cache-only --edgar-cache-only --no-export-xlsx
```

`--non-interactive` is for smoke tests: it skips queue decisions and, if CIQ staging is enabled, stages the workbook but does not ingest it because no PM is present to refresh/save Excel. It never approves or applies assumption changes.

## PM Review Actions

Queue actions available after each profile:

- `a`: approve and apply after a fresh deterministic preview; requires typing `APPLY`.
- `e`: enter revised target values inline, then preview again.
- `r`: reject with a required reason.
- `d`: defer with a required reason.
- `s`: skip for later review.

Only assumption-change packs can be edited or approve/applied. Advisory findings are read-only review items; reject, defer, or skip them.

Do not approve a proposal unless the cited evidence and previewed valuation impact both make sense.

## Time Box

Target for one ticker: 60 minutes.

- Preflight and CIQ refresh: 10 minutes
- EDGAR and initial valuation: 10 minutes
- Six profile review loop: 30 minutes
- Final bundle and friction log: 10 minutes

If a phase breaks the time box, finish the current safe step, record it in the friction draft, and decide whether the session still counts toward M1 exit criteria.
