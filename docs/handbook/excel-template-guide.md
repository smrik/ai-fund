# Excel Template Guide — `ticker_review.xlsx`

## Overview

The Python pipeline writes a structured JSON per ticker. The staged Excel workbook (`templates/ticker_review.xlsx`) carries that JSON as a sidecar export payload and uses it to populate the review tabs. During export staging, the human-facing review sheets are rewritten from the payload so stale template values cannot survive into a ticker workbook. The comps appendix is also written directly from the richer JSON payload during export staging.

The canonical payload target is the [TickerDossier contract](../design-docs/ticker-dossier-contract.md). This guide describes how the workbook consumes that contract, not how the runtime schema is implemented.

This Power Query path is separate from CIQ workbook ingestion. CIQ data enters SQLite through the deterministic workbook refresh + ingest flow under `ciq/`; Power Query here is only for loading Alpha Pod valuation JSON into Excel review templates.

---

## 0. Advanced DCF model — build once, refresh per ticker (recommended)

For the in-depth, formula-driven DCF model, use `src/stage_04_pipeline/advanced_dcf_model.py`
(`scripts/manual/build_advanced_dcf_model.py`). It is built around one idea: **you own the
model; the pipeline owns the data.**

**Build once** — generate a fresh workbook. This is *your* template:

```powershell
python scripts/manual/build_advanced_dcf_model.py --ticker BAH
```

The Base-case DCF is a transparent rebuild (PV of explicit FCFF + value-driver Gordon TV +
exit-multiple TV, blended with the **story-derived** weight, equity bridge, diluted shares) and
the build **refuses to emit unless the workbook Base IV reconciles to the backend `iv_base` to
within $0.10/share**. Tabs: Cover, Thesis_Drivers, PM_Review_Queue, Assumptions (with provenance
+ register flags), Historical_Financials, Input_Forecast, WACC, DCF_Base, Scenarios,
Valuation_Bridge, Sensitivity, Checks.

**Refresh per ticker** — swap a different ticker's data into a model you have already edited:

```powershell
python scripts/manual/build_advanced_dcf_model.py --ticker IBM --refresh path\to\BAH_model.xlsx --output-path IBM_model.xlsx
```

Refresh rebuilds **only the data sheets** and preserves:

- the MODEL sheets — `WACC`, `DCF_Base`, `Sensitivity`, and **any sheet you added**;
- the **PM Override** column on `Assumptions` (overrides flow through the formulas);
- the canonical sheet order.

Hard rules that keep this safe:

- **No PowerQuery in this workbook**, so an `openpyxl` round-trip cannot strip a DataMashup part
  (the failure that corrupted earlier templates). The pipeline never needs the fragile
  zip-patcher.
- **Do not hand-edit the data sheets** (`Assumptions` source column, `Input_Forecast`,
  `Historical_Financials`, `Thesis_Drivers`, `PM_Review_Queue`, `Scenarios`, `Valuation_Bridge`,
  `Cover`, `Checks`); a refresh rebuilds them. Put your model changes on the formula sheets or new
  sheets, and your assumption changes in the PM Override column.

To grow the model, edit the formula sheets / add tabs once, then keep refreshing data underneath.

### Known backend data caveats (surfaced, not silently fixed)

- `excel_flat.forecast[].delta_nwc_mm` is emitted in **raw dollars** (~1e6× too large) for later
  forecast years. The model derives ΔNWC from `nwc_mm` levels and never trusts `delta_nwc_mm`.
- `excel_flat.wacc.size_premium` is stored as **percentage-points** (e.g. `0.6` = 0.6%, displays
  as 60%) while every other rate is a fraction. It does not flow into the backend WACC; treat the
  unit as a known inconsistency until the exporter is fixed.

**Agent judgment.** If a guided-workup / analyst-prep run exists for the ticker (auto-discovered
from `output/guided_workups/<TICKER>/` or `output/analyst_prep/<TICKER>/`, or passed via
`--guided-workup`), the model surfaces it **read-only**: the **Thesis_Drivers** tab leads with the
agent thesis cards (claim, model implication, confidence, what-would-change-mind), and
**PM_Review_Queue** leads with the agent driver proposals (current → proposed value, rationale,
PM-queue item, `review_required` status) plus missing-data flags. These never change the model —
to act on a proposal, type the proposed value into the Assumptions **PM Override** column. When no
guided-workup run is found, the Thesis tab falls back to the deterministic story/sector layer and
says so.

---

## 1. Generating the JSON

```bash
# Single ticker with QoE signals
python -m src.stage_02_valuation.batch_runner --ticker IBM --json --qoe

# Batch (5 tickers)
python -m src.stage_02_valuation.batch_runner --limit 5 --json

# Full universe with QoE
python -m src.stage_02_valuation.batch_runner --json --qoe
```

Outputs:
- `data/valuations/json/{TICKER}_{YYYY-MM-DD}.json` — dated archive
- `data/valuations/json/{TICKER}_latest.json` — stable path for Power Query

---

## 2. Current JSON Shape And Contract Target

The workbook currently consumes the staged JSON roots emitted by the valuation exporter and `export_service`. The canonical `TickerDossier` envelope is the target documented in [docs/design-docs/ticker-dossier-contract.md](../design-docs/ticker-dossier-contract.md), but runtime adapters are intentionally deferred to child issues.

Current top-level sections and their Power Query navigation targets:

| Section | Key contents |
|---------|-------------|
| `market` | price, market_cap_mm, ev_mm, PE, analyst consensus |
| `assumptions` | all DCF drivers (growth, margins, capex, D&A, tax, NWC, exit multiple) |
| `wacc` | full CAPM build-up, peers list |
| `valuation` | IV bear/base/bull, expected IV, comps IVs, margin of safety |
| `scenarios` | probability, IV, upside per scenario |
| `terminal` | TV breakdown (Gordon / exit / blended), PV of TV |
| `health_flags` | boolean diagnostics (tv_high, tv_extreme, guardrails, etc.) |
| `forecast_bridge` | array[10] year-by-year FCFF projection |
| `comps_detail` | target + per-peer metrics + medians |
| `comps_analysis` | workbook-ready comps appendix rows, diagnostics, and history |
| `source_lineage` | data source tag for every assumption |
| `ciq_lineage` | CIQ run / date / file audit trail |
| `default_resolution` | audit rows for default-backed or prior-backed assumptions that need PM review |
| `analyst_prep` | thesis cards, model-driver map, evidence map, comps judgment, and missing-data flags for senior review |
| `qoe` | QoE signals (present only when `--qoe` flag used) |
| `drivers_raw` | full ForecastDrivers dataclass (unrounded) |

---

## 3. Power Query Setup

### Step 1 — Config sheet

The canonical template already includes a sheet named **Config** plus the defined name `json_path`.

For the shipped `templates/ticker_review.xlsx` workbook:

- `Config!B2` stores the staged JSON path
- the defined name `json_path` points at `Config!$B$2`

When the React export flow stages a workbook, it copies `templates/ticker_review.xlsx`, writes a job-scoped `{TICKER}_latest.json` into the export bundle, updates `Config!B2` to the absolute path of that staged JSON, and rewrites the visible review sheets from that same payload.

If you are building or repairing the template manually, enter the full path in `B2`:

```
C:\Projects\03-Finance\ai-fund\data\valuations\json\IBM_latest.json
```

The defined name should refer to `=Config!$B$2`.

### Step 2 — Create the base JSON query

**Data → Get Data → From Other Sources → Blank Query** → Advanced Editor:

```m
let
    FilePath = Excel.CurrentWorkbook(){[Name="json_path"]}[Content]{0}[Column1],
    Source   = Json.Document(File.Contents(FilePath)),
    Output   = Source
in
    Output
```

Name this query `RawJSON`. Do not load to sheet.

### Step 3 — Section queries

For each section, create a separate query that drills into `RawJSON`:

**Assumptions query:**
```m
let
    Source      = RawJSON,
    assumptions = Source[assumptions],
    AsRecord    = Record.ToTable(assumptions)
in
    AsRecord
```

**ForecastBridge query (returns a table):**
```m
let
    Source  = RawJSON,
    bridge  = Source[forecast_bridge],
    AsTable = Table.FromList(bridge, Splitter.SplitByNothing()),
    Expand  = Table.ExpandRecordColumn(AsTable, "Column1",
                Record.FieldNames(AsTable[Column1]{0}))
in
    Expand
```

**Peers query:**
```m
let
    Source  = RawJSON,
    peers   = Source[comps_detail][peers],
    AsTable = Table.FromList(peers, Splitter.SplitByNothing()),
    Expand  = Table.ExpandRecordColumn(AsTable, "Column1",
                Record.FieldNames(AsTable[Column1]{0}))
in
    Expand
```

Repeat the pattern for `market`, `wacc`, `valuation`, `scenarios`, `terminal`, `health_flags`, `qoe`, `source_lineage`, and `ciq_lineage`.

---

## 4. Sheet Structure

### Override Pattern (used on Assumptions, WACC sheets)

| Col A | Col B | Col C | Col D |
|-------|-------|-------|-------|
| **Driver** | **JSON** (Power Query) | **Override** (PM types) | **Active** = `=IF(C2="",B2,C2)` |

- **Col B** — refreshes from JSON via Power Query
- **Col C** — blank by default; PM types an override here
- **Col D** — referenced by all formulas; switches to override when present
- Suggested formatting: blue font on B (data), yellow fill on C (input), black on D (formula)

### Sheet 1 — Config
Path cell (`B1`) + named range `json_path`. Can be hidden.

### Sheet 2 — Summary
Pull `market`, `valuation`, `scenarios`, and `health_flags`. Single-record layout: field names col A, values col B. Add conditional formatting on upside and health flags (red/amber/green).

### Sheet 3 — Assumptions
- Power Query loads `assumptions` + `source_lineage`
- Override column pattern for every driver
- Additional column: **Source** (from `source_lineage`)

### Sheet 4 — WACC

### Analyst Prep Sheets

Ticker exports also rewrite the Analyst Prep review tabs from the same staged JSON payload:

| Sheet | Purpose |
|-------|---------|
| `Analyst_Prep` | one-page status, source quality, counts, and missing-data flags |
| `Thesis_Bridge` | anchored thesis cards linking claims to model drivers and evidence anchors |
| `Model_Driver_Map` | current/proposed/effective assumption values, source, status, and rationale |
| `Evidence_Map` | packet facts, observations, deterministic assumption anchors, and comps anchors |
| `Comps_Judgment` | peer-set quality, primary metric, premium/discount argument, and warnings |
| `Segment_Drivers` | deterministic segment rows when available; otherwise an explicit missing-evidence row |

Analyst Prep sheets are reasoning artifacts. They do not change DCF formulas or approved assumptions. Model changes still flow through PM Queue preview/approve/apply.
- Power Query loads `wacc` section
- Override column on: Rf, ERP, beta, size premium, cost of debt, D/E weights
- Live formula example (D column is "Active"):
  - `Ke = Rf_active + β_relevered_active × ERP_active + size_premium_active`
  - `Kd_after_tax = Kd_active × (1 - tax_rate_active)`
  - `WACC = Ke × equity_weight_active + Kd_after_tax × debt_weight_active`

### Sheet 5 — FCFF Projection (Base)
Year-columns Y1–Y10 + terminal. Live formulas read Active assumptions from Sheet 3:

| Row | Formula |
|-----|---------|
| Revenue | `=prev_rev × (1 + growth_active)` |
| EBIT | `=Revenue × margin_t` (linear interpolation start→target) |
| NOPAT | `=EBIT × (1 - tax_active)` |
| D&A | `=Revenue × da_pct_active` |
| Capex | `=Revenue × capex_pct_active` |
| AR | `=Revenue × dso_active / 365` |
| Inventory | `=Revenue × dio_active / 365` |
| AP | `=Revenue × dpo_active / 365` |
| NWC | `=AR + Inventory - AP` |
| ΔNWC | `=NWC_t - NWC_{t-1}` |
| FCFF | `=NOPAT + D&A - Capex - ΔNWC` |
| Discount factor | `=1 / (1 + WACC_active)^year` |
| PV FCFF | `=FCFF × discount_factor` |

### Sheet 6 — FCFF Projection (Bear)
Same as Base, but scale inputs:
- Growth × `0.6`, Margin × `0.75`, Capex × `1.2`, WACC + `0.02`, Exit × `0.7`

### Sheet 7 — FCFF Projection (Bull)
- Growth × `1.4`, Margin × `1.15`, Capex × `0.9`, WACC − `0.01`, Exit × `1.3`

### Sheet 8 — Equity Bridge
Pulls PV sums from Sheets 5/6/7:

| Row | Formula |
|-----|---------|
| PV sum of FCFF | `=SUM(PV_FCFF_Y1:PV_FCFF_Y10)` |
| PV Terminal Value | Gordon: `= (NOPAT_Y11 × (1 - g/RONIC)) / (WACC - g) × discount_Y10` |
| EV (operations) | `=PV sum + PV TV` |
| EV (total) | `=EV_ops + non_operating_assets` |
| Equity Value | `=EV_total - net_debt - minority - preferred - pension - leases - options - convertibles` |
| IV/share | `=Equity_Value / shares_outstanding` |

Three scenario columns (Bear / Base / Bull) + expected IV column = weighted average using scenario probabilities from Assumptions.

### Sheet 9 — Comps
- Export staging writes this tab directly from `comps_analysis`
- Purpose: PM-facing comparable-companies appendix
- Sections:
  - headline valuation summary: primary metric, blended base IV, bear/base/bull IV, raw/clean peer counts, similarity method
  - valuation-by-metric table: target multiple, peer median, bear/base/bull multiples, bear/base/bull IV, primary flag
  - target-vs-peer benchmark table: growth, margins, leverage, and valuation deltas
  - peer table: ticker, display name, similarity score, model weight, operating benchmarks, and trading multiples
- The shipped workbook no longer treats Excel median formulas or manual `"x"` exclusions as the official comps engine. Official comps outputs come from the deterministic backend payload.

### Sheet 10 — Comps Diagnostics
- Export staging writes this tab directly from `comps_analysis`
- Purpose: support diagnostics for the comps appendix
- Sections:
  - audit flags and model notes
  - per-peer, per-metric status rows (`included`, `outlier_removed`, `missing`)
  - football-field ranges by metric
  - historical multiple summary with current, median, quartiles, and percentile

### Sheet 11 — QoE / Data Quality
- Export staging writes this tab directly from `ciq_lineage`, `health_flags`, and `source_lineage`
- Purpose: make data freshness, fallback sources, and default-backed assumptions visible before PM approval

### Sheet 12 — Review Checks
- Export staging writes this tab directly from deterministic payload checks
- Purpose: lightweight triage of high terminal-value dependence, DCF/comps disagreement, fallback comps, `default_resolution` findings, and missing optional market context

---

## 5. Refresh Workflow

1. Use the React export hub on `/ticker/:ticker/audit` or the `Valuation -> Export Excel` shortcut
2. The backend stages a copied workbook plus a job-scoped JSON bundle under `data/exports/generated/`
3. Open the staged workbook in desktop Excel
4. Run **Data → Refresh All** (or Ctrl+Alt+F5) for workbook-native assumption sheets if needed
5. The staged workbook writes `Cover`, `Output`, `Assumptions`, scenario DCF tabs, `Equity_Bridge`, `Sensitivity`, `QoE`, `Review Checks`, `Comps`, and `Comps Diagnostics` directly from the JSON payload
6. If workbook-native override formulas are reintroduced, verify that exported copies still pass the no-stale-template-value regression test

---

## 6. Adding a New Ticker

1. Stage a new export from the React `Audit` hub or by rerunning the JSON export manually
2. Open the copied workbook and confirm `Config!B2` points at the intended `{TICKER}_latest.json`
3. Refresh All
4. Overrides in Col C are **not** ticker-specific inside a workbook copy — clear them when switching tickers or stage a fresh bundle

---

## 7. File Locations

| Artifact | Path |
|----------|------|
| JSON (dated) | `data/valuations/json/{TICKER}_{YYYY-MM-DD}.json` |
| JSON (latest) | `data/valuations/json/{TICKER}_latest.json` |
| Staged React export bundle | `data/exports/generated/ticker/{TICKER}/{TIMESTAMP}-{FORMAT}-{ID}/` |
| Excel template | `templates/ticker_review.xlsx` |
| JSON exporter module | `src/stage_02_valuation/json_exporter.py` |
| JSON exporter tests | `tests/test_json_exporter.py` |
| Rich comps appendix payload | `comps_analysis` |

## Canonical Template Notes

- `templates/ticker_review.xlsx` is the canonical review workbook used by the export flow
- `templates/ticker_review2.xlsx` and `templates/CALM_ticker_review2.xlsx` should be treated as legacy/non-canonical variants unless they are explicitly promoted in a later docs update
