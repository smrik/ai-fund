# Learn The Codebase

Use this guide to find the correct file without reading the full repository.

## The Six-Step Workflow

This is the workflow for one selected ticker. Universe screening happens before this workflow.

Screening code is in `src/stage_01_screening/`.

| Step | Owner | Main paths | Input | Output |
| --- | --- | --- | --- | --- |
| 1. Get data | Deterministic code | `ciq/`, `src/stage_00_data/`, `db/` | CIQ, EDGAR, market data, and transcripts | Source data in SQLite |
| 2. Build the current-state model | Deterministic code | `src/stage_02_valuation/`, `db/` | Reported history from SQLite | Reconciled history and current-state valuation inputs |
| 3. Analyze the business and industry | LLM agents | `src/stage_03_judgment/` | Filings, transcripts, history, and market context | Business and industry context |
| 4. Propose forecast inputs | LLM agents and PM | `src/stage_03_judgment/`, `src/stage_04_pipeline/` | Context and current-state model | Proposed assumptions in the PM Decision Queue |
| 5. Run DCF and comps | Deterministic code | `src/stage_02_valuation/` | PM-approved assumptions | DCF, comps, scenarios, and source records |
| 6. Review decisions and outputs | PM | `api/`, `frontend/`, `data/exports/generated/` | Valuation and queue data | PM decisions and review files |

The output of each step supports the next step.

LLM agents propose future assumptions. They do not write directly to the model.

The PM must approve each proposal. Deterministic code then runs the approved assumptions.

## Main Folder Map

| Path | Purpose |
| --- | --- |
| `docs/` | Product rules, finance method, system design, instructions, and plans |
| `config/` | Saved settings, universe lists, and PM-approved overrides |
| `ciq/` | Capital IQ Excel loading tools and source template |
| `db/` | SQLite tables and data-loading functions |
| `src/stage_00_data/` | Data collection and source adapters |
| `src/stage_01_screening/` | Deterministic universe filters |
| `src/stage_02_valuation/` | Deterministic model and valuation calculations |
| `src/stage_03_judgment/` | LLM analysis and assumption proposals |
| `src/stage_04_pipeline/` | Workflow control and PM Queue support |
| `api/` | FastAPI transport for the React app |
| `frontend/` | React user interface |
| `dashboard/` | Old Streamlit interface. Bug fixes only. |
| `data/` | SQLite data, refreshed CIQ workbooks, and generated files |
| `templates/` | PM review and valuation workbook templates |
| `tests/` | Offline tests and behavior examples |
| `scripts/` | Manual run and review commands |

## Important Data Paths

| Path | Purpose |
| --- | --- |
| `ciq/templates/ciq_cleandata.xlsx` | Main CIQ Standard source template |
| `ciq/templates/financials_input.json` | Power Query ticker, date, and currency control |
| `data/exports/{TICKER}_Standard.xlsx` | Refreshed CIQ workbook for database loading |
| `data/alpha_pod.db` | Main local SQLite database |
| `templates/ticker_review.xlsx` | Main PM review workbook template |
| `data/exports/generated/` | Generated PM review files |

For more information, read [Storage And Runtime Data](./reference/storage-runtime-map.md).

## Rules That Protect The Model

- LLM code must not run inside deterministic calculations.
- LLM agents must send proposals through the PM Decision Queue.
- The frontend must display results. It must not calculate valuation results.
- The API must move data. Business logic belongs in `src/`, `db/`, or `config/`.
- Missing data and fallback values must be visible.
- Each important value must keep its source record.
- Ask the PM before a change to financial meaning or valuation rules.

## Trace One Value

Use this order when a value looks incorrect:

1. Find the label in `frontend/`.
2. Find the response field in `api/`.
3. Find the workflow function in `src/stage_04_pipeline/`.
4. Find the calculation in `src/stage_02_valuation/`.
5. Find the source in SQLite, CIQ, EDGAR, or another data adapter.
6. Find the test that defines the expected result.

Do not stop at the user interface. Find where the value entered the system.

## Review A Pull Request

Check these points:

1. Which Vision decision does the change support?
2. Does the change help the weekly ticker process?
3. Does it change a financial rule or metric meaning?
4. Does it cross a layer rule?
5. Are missing data and fallback values visible?
6. Do tests cover the changed behavior?
7. Did the author inspect the real output?

Useful commands:

```powershell
git status --short
git diff --stat
git diff --name-only
rg "field_or_function_name" tests
```

Start with [Vision](./strategy/vision.md) for product rules.

Use [Valuation](./valuation/index.md) for the finance method.

Use [Architecture](./design-docs/architecture-overview.md) for code-layer rules.

Use [The Operator Workflow](./handbook/workflow-end-to-end.md) to run one ticker.
