# Excel Template Guide — `ticker_review.xlsx`

## Overview

The Python pipeline writes a structured JSON per ticker. An Excel workbook (`templates/ticker_review.xlsx`) pulls that JSON via Power Query, seeds assumptions into an override column, and live Excel formulas recompute the full DCF, WACC, comps valuation, and equity bridge. You own the template; Python only produces the data.

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

## 2. JSON Schema (`$schema_version: "1.0"`)

Top-level sections and their Power Query navigation targets:

| Section | Key contents |
|---------|-------------|
| `market` | price, market_cap_mm, ev_mm, PE, analyst consensus |
| `assumptions` | all DCF drivers (growth, margins, capex, D&A, tax, NWC, exit multiple) |
| `wacc` | full CAPM build-up, peers list |
| `valuation` | IV bear/base/bull, expected IV, comps IVs, margin of safety |
| `scenarios` | probability, IV, upside per scenario |
| `terminal` | TV breakdown (Gordon / exit / blended), PV of TV |
| `health_flags` | boolean diagnostics (tv_high, tv_extreme, guardrails, etc.) |
| `forecast_bridge` | array[10] — year-by-year FCFF projection |
| `comps_detail` | target + per-peer metrics + medians |
| `source_lineage` | data source tag for every assumption |
| `ciq_lineage` | CIQ run / date / file audit trail |
| `qoe` | QoE signals (present only when `--qoe` flag used) |
| `drivers_raw` | full ForecastDrivers dataclass (unrounded) |

---

## 3. Power Query Setup

### Step 1 — Config sheet

Create a sheet named **Config**. In cell `A1` type `json_path`, in `B1` enter the full path to the latest JSON:

```
C:\Projects\03-Finance\ai-fund\data\valuations\json\IBM_latest.json
```

Name the range `B1` as `json_path` (Formulas → Name Manager → New → refers to `=Config!$B$1`).

### Step 2 — Create the base JSON query

**Data → Get Data → From Other Sources → Blank Query** → Advanced Editor:

```m
let
    FilePath = Excel.CurrentWorkbook(){[Name="ConfigTable"]}[Content]{0}[json_path],
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

Repeat the pattern for `market`, `wacc`, `valuation`, `scenarios`, `terminal`, `health_flags`, `qoe`.

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
Pull `market`, `valuation`, `scenarios`, `health_flags`. Single-record layout: field names col A, values col B. Add conditional formatting on upside and health flags (red/amber/green).

### Sheet 3 — Assumptions
- Power Query loads `assumptions` + `source_lineage`
- Override column pattern for every driver
- Additional column: **Source** (from `source_lineage`)

### Sheet 4 — WACC
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
- Power Query loads `comps_detail.peers` as a table + `comps_detail.target` as header row
- Column layout: Ticker | Name | MCap | TEV | Revenue | EBITDA | EBIT | EPS | EV/EBITDA LTM | EV/EBITDA Fwd | EV/EBIT | P/E
- **Include** column: PM types `x` to exclude a peer from medians
- Live MEDIAN that skips excluded rows:
  ```excel
  =MEDIAN(IF(Include_range<>"x", EV_EBITDA_range))
  ```
  (Enter as array formula: Ctrl+Shift+Enter, or CTRL+SHIFT+ENTER in older Excel)
- Implied IV row: `= peer_median_multiple × target_metric`, bridge to equity, ÷ shares

### Sheet 10 — QoE Signals
- Power Query loads `qoe` section
- Composite score banner at top (colour-coded)
- Per-signal table: signal name | value | score | threshold
- Conditional formatting: green (score=green), amber (score=amber), red (score=red)
- NWC drift detail: current vs baseline per DSO/DIO/DPO

---

## 5. Refresh Workflow

1. Run the pipeline: `python -m src.stage_02_valuation.batch_runner --ticker IBM --json --qoe`
2. Open `ticker_review.xlsx`
3. Update `Config!B1` to point to the new ticker's `_latest.json`
4. **Data → Refresh All** (or Ctrl+Alt+F5)
5. All sheets populate from the JSON; Col D (Active) switches to any overrides you've typed in Col C
6. Override any assumption in Col C → FCFF projections, equity bridge, and IV recalculate immediately

---

## 6. Adding a New Ticker

1. Run `--ticker MSFT --json --qoe` → creates `MSFT_latest.json`
2. Open `ticker_review.xlsx`, change `Config!B1` to `.../MSFT_latest.json`
3. Refresh All
4. Overrides in Col C are **not** ticker-specific — clear them when switching tickers

---

## 7. File Locations

| Artifact | Path |
|----------|------|
| JSON (dated) | `data/valuations/json/{TICKER}_{YYYY-MM-DD}.json` |
| JSON (latest) | `data/valuations/json/{TICKER}_latest.json` |
| Excel template | `templates/ticker_review.xlsx` |
| JSON exporter module | `src/stage_02_valuation/json_exporter.py` |
| JSON exporter tests | `tests/test_json_exporter.py` |
