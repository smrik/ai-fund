# Pipeline Glass-Box Walkthrough

Run the backend pipeline one stage at a time and inspect the artifact passed to the next stage. Every command here was executed and verified on 2026-06-12 (MSFT, offline/cache flags). UI surfaces are intentionally out of scope.

Use `C:\Users\patri\miniconda3\envs\ai-fund\python.exe` (shown as `python` below) until `rtk python` resolution is fixed.

## The Chain And Its Handoff Artifacts

```text
Stage 1 screen ──> config/universe.csv
Stage 2 batch  ──> data/alpha_pod.db: batch_valuations_latest, valuations
                   data/valuations/latest.csv
[CIQ refresh]  ──> data/alpha_pod.db: CIQ snapshot/long-form/comps tables
Ticker flow    ──> evidence_packets ─> observations ─> translator
                   ─> pm_decision_queue_items (+ pending_assumption_changes link)
PM approve     ──> approved_assumption_entries
Next valuation ──> input_assembler.build_valuation_inputs() reads approved entries
Exports        ──> output/ticker_flows/, output/analyst_prep/, data/exports/
```

## Step 1 — Universe Screen

```powershell
python -m src.stage_01_screening.stage1_filter
```

- **Consumes:** seed listing universe + yfinance (cached in `data/cache/yfinance_info.json`)
- **Produces:** `config/universe.csv`
- **Inspect:** `Get-Content config/universe.csv -TotalCount 5` and check the file date. As of 2026-06-12 it was dated **2026-03-06** — rerun before a real session; this step is network-dependent.

## Step 2 — Deterministic Valuation

Single ticker (print-only — see gotcha):

```powershell
python -m src.stage_02_valuation.batch_runner --ticker MSFT
```

Batch (the persisting path):

```powershell
python -m src.stage_02_valuation.batch_runner --top 50
```

- **Consumes:** `config/universe.csv` (batch), yfinance market/financial snapshots, CIQ tables when present, sector defaults
- **Produces (batch only):** `batch_valuations_latest` (replace), `valuations` (history upsert), `data/valuations/latest.csv`
- **Gotcha (verified):** `--ticker` prints the full valuation row but persists nothing. The canonical watchlist row only updates via batch.
- **Inspect the row contract:** the printed JSON includes assumption values with `_source` lineage fields, WACC decomposition, bear/base/bull IVs, `tv_pct_of_ev`, reverse-DCF implied growth, and `context_scenario_policy_json` (regime-aware scenario weights with the official fixed policy alongside).
- **Inspect the DB:**

```powershell
python -c "import sqlite3;c=sqlite3.connect('data/alpha_pod.db');print(c.execute('select ticker, snapshot_date, wacc from batch_valuations_latest limit 5').fetchall())"
```

## Step 3 — Optional CIQ Refresh

Host-Windows Excel path; see [workflow-end-to-end.md](./workflow-end-to-end.md#optional-ciq-workbook-refresh-path). After a manual workbook refresh, ingest intentionally with `--ingest-ciq-template` on the ticker flow. CIQ rows beat yfinance in the input assembler's source priority.

## Step 4 — Evidence → Observations → Translator → Queue (the glass box)

```powershell
python scripts/manual/run_ticker_valuation_flow.py --ticker MSFT --agent-mode heuristic --isolated-db --market-cache-only --edgar-cache-only
```

- **Consumes:** DB valuation state, market cache, EDGAR filing cache, CIQ comps
- **Produces:** `output/ticker_flows/MSFT-<ts>.json` + `.md`, and (because of `--isolated-db`) a copied SQLite DB under `output/ticker_flows/_isolated_db/` holding the new Evidence Packets and PM Queue items
- **Flags:** `--isolated-db` keeps rehearsals out of the live queue; drop it only when you intend real review state. `--agent-mode heuristic` uses deterministic stub observations (workflow checks, not insights). Drop `--edgar-cache-only` to allow live SEC fetches.

The JSON artifact is the handoff bundle. Top-level keys worth reading in order:

| Key | What it shows |
| --- | --- |
| `deterministic` | valuation summary/dcf/comps/assumption payloads the agents saw |
| `profile_runs` | per-profile status; `blocked` + `insufficient_real_evidence` means fail-closed on missing sources |
| `evidence_packets` | facts vs observations per packet kind, with anchors |
| `queue_items` | advisory findings and assumption change packs, three confidence fields |
| `previews` | resolved proposal values and status transition `pending → previewed` |
| `data_freshness` | cache ages — check `edgar_filing_cache.filing_count` first |

**Verified 2026-06-12:** with an empty EDGAR cache, 4 of 6 profiles (`earnings_update`, `company_analysis`, `industry_analysis`, `risk_review`) blocked correctly; `comps_analysis` and `valuation_review` produced one observation and one queue item each.

**Inspect the canonical queue store** (point at the isolated DB from the run output):

```powershell
python -c "import sqlite3;c=sqlite3.connect('output/ticker_flows/_isolated_db/<run>.db');print(c.execute('select item_id, item_type, title, status, agent_confidence, translator_confidence from pm_decision_queue_items order by item_id desc limit 5').fetchall())"
python -c "import sqlite3;c=sqlite3.connect('output/ticker_flows/_isolated_db/<run>.db');print(c.execute('select id, ticker, assumption_name, proposed_value, status, approval_ref from pending_assumption_changes').fetchall())"
```

## Step 5 — PM Decisions And The Apply Loop

Decisions go through `src/stage_04_pipeline/pm_decision_queue.py` (`preview_pm_decision_queue_item`, `approve_pm_decision_queue_item`, `apply_pm_decision_queue_item`), exposed via the FastAPI layer. On approve+apply:

1. The proposal's delta/target is resolved to an absolute value (preview and approval use the same resolver)
2. A `pending_assumption_changes` row moves to `approved` with an `approval_ref`
3. The value lands in `approved_assumption_entries`
4. The next deterministic run reads it: `input_assembler.build_valuation_inputs()` → `get_approved_assumption_overrides(ticker)` (`src/stage_02_valuation/input_assembler.py:354`)

**Inspect the audit trail:** `valuation_override_audit` and `assumption_register_audit` tables.

## Step 6 — Analyst Prep Pack And Exports

```powershell
python scripts/manual/run_analyst_prep_pack.py --ticker MSFT --agent-mode heuristic --isolated-db --export-xlsx --skip-agent-runs --market-cache-only --edgar-cache-only
```

- **Produces:** `output/analyst_prep/MSFT/<ts>.json|.md` and, with `--export-xlsx`, a review workbook under `data/exports/generated/ticker/MSFT/`
- This is a read-only aggregation of everything above — it proposes nothing and mutates nothing.

## Known Gaps (verified 2026-06-12)

| Gap | Effect | Owner fix |
| --- | --- | --- |
| `config/universe.csv` stale (2026-03-06) | Batch ranks a 3-month-old universe | Rerun Stage 1 in each weekly session (runbook) |
| Single-ticker valuation not persisted | Deep-dive output is ephemeral; watchlist row stays stale | Decide: batch-refresh the name, or add an explicit promote step |
| No operator command to prefetch EDGAR filings | Empty cache → 4/6 profiles fail closed offline; acquisition only happens implicitly in live runs | Add a small prefetch CLI or a runbook step that runs one live (non-cache-only) flow first |
| No transcript source for `earnings_update` | Earnings evidence limited to EDGAR releases | Data-source decision for the PM (Vision Decision 9 territory) |
| Packet `source_quality` serializes as `None` in the flow JSON | Export shows less than the DB knows | Small export-contract fix |
| Pending queue items have no aging surface | DUOL QoE proposal sat pending since 2026-06-08 unnoticed | M3 morning digest owns this; until then, check `pending_assumption_changes` in sessions |
