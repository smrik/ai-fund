# Storage And Runtime Data

Use this page before you move or delete a data file.

## Main Data Flow

| Path | Purpose | Can the system rebuild it? |
| --- | --- | --- |
| `ciq/templates/ciq_cleandata.xlsx` | Main CIQ Standard source template | No |
| `ciq/templates/financials_input.json` | Power Query control file | No |
| `data/exports/{TICKER}_Standard.xlsx` | Refreshed CIQ workbook for database loading | Not without another CIQ refresh |
| `data/ciq_archive/{TICKER}_{date}_{ts}.xlsx` | Saved copy of a successful CIQ refresh | No |
| `data/alpha_pod.db` | Main local SQLite database | Not fully |
| `templates/ticker_review.xlsx` | Main PM review template | No |
| `data/exports/generated/` | Generated PM review files | Yes |
| `output/` | Generated run records and diagnostic files | Yes |

## CIQ Workbook Chain

```text
ciq/templates/financials_input.json
  + ciq/templates/ciq_cleandata.xlsx
  -> data/exports/{TICKER}_Standard.xlsx
       +-> data/alpha_pod.db
       +-> data/ciq_archive/{TICKER}_{date}_{ts}.xlsx
```

The Standard workbook is an input to the database. It is not a PM review workbook.

Power Query reads this fixed path:

```text
C:\Projects\03-Finance\ai-fund\ciq\templates\financials_input.json
```

Check the ticker and date before each Excel refresh. Do not move this file.

## Files To Keep

| Path | Reason |
| --- | --- |
| `data/alpha_pod.db` | Contains saved source data, run history, and PM Queue data |
| `data/exports/{TICKER}_Standard.xlsx` | Contains refreshed CIQ vendor data |
| `data/ciq_archive/` | Contains saved copies of successful CIQ refreshes |
| `config/config.yaml` | Contains system settings |
| `config/universe.csv` | Defines the research universe |
| `config/story_drivers.yaml` | Contains PM-approved story drivers |
| `config/valuation_overrides.yaml` | Contains PM-approved valuation changes |
| `.env` | Contains local secrets. Never commit it. |

Back up the database, refreshed CIQ workbooks, and CIQ archive. Git cannot rebuild them.

## Files The System Can Rebuild

| Path | How it returns |
| --- | --- |
| `data/cache/` | The system gets the source data again |
| `data/exports/generated/` | The export process creates it again |
| `data/valuations/` | The valuation process creates it again |
| `data/dossiers/` | The dossier process creates it again |
| `data/stage1_survivors.csv` | The screening process creates it again |
| `frontend/dist/` | `npm --prefix frontend run build` creates it |
| `frontend/node_modules/` | `npm --prefix frontend ci` creates it |
| `site/` | MkDocs creates it |
| `.tmp-tests/` | Tests create it |
| `.pre-commit-cache*/` | Pre-commit creates it |

Delete only the specific generated path that you intend to rebuild.

Do not delete all of `data/exports/`. It can contain refreshed CIQ workbooks.

## Files That Must Not Enter Git

- `.env`
- `data/alpha_pod.db`
- downloaded caches
- generated exports
- generated valuation files
- frontend build files
- test scratch files

The `.gitignore` file contains the exact rules.

Read [Learn The Codebase](../learn-codebase.md) for the six-step workflow.

Read [CIQ Operations](../handbook/operations-runbook.md#ciq-single-ticker-refresh) for refresh instructions.
