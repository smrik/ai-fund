# Power Query M — Live JSON → Excel

Reads `data/valuations/json/{TICKER}_latest.json` and seeds the **Assumptions** sheet
Col B (JSON baseline). The DCF formulas then recalculate from those seeded values.

All percentage values in the JSON are **decimals** (0.066, not 6.6).
All `_mm` values are in **$mm**.

---

## Step 1 — Set the file path

In the Assumptions sheet, put the full path in a named cell so every query reads from one place.

| Cell | Value |
|---|---|
| `Config!A1` | `json_path` |
| `Config!B1` | `C:\Projects\03-Finance\ai-fund\data\valuations\json\IBM_latest.json` |

Name cell `Config!B1` as `json_path` via **Formulas → Name Manager**.

To switch tickers: change the path to e.g. `ORCL_latest.json` and hit **Data → Refresh All**.

---

## Step 2 — Core query: load JSON

**Home → Get Data → From Other Sources → Blank Query**. Name it `TickerJSON`.

```m
let
    Path   = Excel.CurrentWorkbook(){[Name="json_path"]}[Content]{0}[Column1],
    Source = File.Contents(Path),
    Parsed = Json.Document(Source)
in
    Parsed
```

> **Quickstart alternative** — hardcode the path during setup, parameterise later:
> ```m
> let
>     Parsed = Json.Document(File.Contents(
>         "C:\Projects\03-Finance\ai-fund\data\valuations\json\IBM_latest.json"))
> in
>     Parsed
> ```

---

## Step 3 — Named range loader queries

Create one **Blank Query** per section. Set each to **Load to: Connection Only**,
then reference output cells via Named Ranges in the Assumptions sheet.

### 3a — Assumptions block

Returns a single-column table; load to a hidden sheet and link each row to Col B.

```m
let
    A = TickerJSON[assumptions],
    Result = #table(
        {"Key", "Value"},
        {
            {"revenue_mm",            A[revenue_mm]},
            {"growth_near",           A[growth_near_pct]},
            {"growth_mid",            A[growth_mid_pct]},
            {"growth_terminal",       A[growth_terminal_pct]},
            {"ebit_margin_start",     A[ebit_margin_start_pct]},
            {"ebit_margin_target",    A[ebit_margin_target_pct]},
            {"capex_pct",             A[capex_pct]},
            {"da_pct",                A[da_pct]},
            {"tax_rate_start",        A[tax_rate_start_pct]},
            {"tax_rate_target",       A[tax_rate_target_pct]},
            {"dso_start",             A[dso_start]},
            {"dso_target",            A[dso_target]},
            {"dio_start",             A[dio_start]},
            {"dio_target",            A[dio_target]},
            {"dpo_start",             A[dpo_start]},
            {"dpo_target",            A[dpo_target]},
            {"exit_multiple",         A[exit_multiple]},
            {"ronic_terminal",        A[ronic_terminal_pct]},
            {"net_debt_mm",           A[net_debt_mm]},
            {"shares_outstanding_mm", A[shares_outstanding_mm]},
            {"non_op_assets_mm",      A[non_operating_assets_mm]},
            {"pension_deficit_mm",    A[pension_deficit_mm]},
            {"lease_liabilities_mm",  A[lease_liabilities_mm]},
            {"prob_bear",             A[scenario_prob_bear]},
            {"prob_base",             A[scenario_prob_base]},
            {"prob_bull",             A[scenario_prob_bull]}
        }
    )
in
    Result
```

### 3b — WACC block

```m
let
    W = TickerJSON[wacc],
    Result = #table(
        {"Key", "Value"},
        {
            {"wacc",          W[wacc]},
            {"ke",            W[cost_of_equity]},
            {"kd",            try W[cost_of_debt] otherwise null},
            {"rf",            try W[risk_free_rate] otherwise 0.045},
            {"erp",           try W[equity_risk_premium] otherwise 0.050},
            {"beta_rel",      W[beta_relevered]},
            {"size_prem",     W[size_premium]},
            {"eq_wt",         W[equity_weight]},
            {"debt_wt",       W[debt_weight]}
        }
    )
in
    Result
```

### 3c — Scenarios / IV

```m
let
    S = TickerJSON[scenarios],
    V = TickerJSON[valuation],
    Result = #table(
        {"Scenario", "IV", "Upside_pct"},
        {
            {"Bear",     S[bear][iv],  S[bear][upside_pct]},
            {"Base",     S[base][iv],  S[base][upside_pct]},
            {"Bull",     S[bull][iv],  S[bull][upside_pct]},
            {"Expected", V[expected_iv], V[expected_upside_pct]}
        }
    )
in
    Result
```

### 3d — Market data

```m
let
    M = TickerJSON[market],
    Result = #table(
        {"Key", "Value"},
        {
            {"price",           M[price]},
            {"market_cap_mm",   M[market_cap_mm]},
            {"ev_mm",           M[ev_mm]},
            {"pe_trailing",     M[pe_trailing]},
            {"pe_forward",      M[pe_forward]},
            {"ev_ebitda",       M[ev_ebitda]},
            {"analyst_target",  M[analyst_target]},
            {"analyst_rec",     M[analyst_recommendation]}
        }
    )
in
    Result
```

### 3e — Comps peers table

```m
let
    Peers  = TickerJSON[comps_detail][peers],
    ToTable = Table.FromList(Peers, Splitter.SplitByNothing()),
    Expand = Table.ExpandRecordColumn(ToTable, "Column1",
        {"ticker","name","market_cap_mm","tev_mm","revenue_ltm_mm",
         "ebitda_ltm_mm","eps_ltm","tev_ebitda_ltm","tev_ebitda_fwd","pe_ltm"})
in
    Expand
```

---

## Step 4 — Wire to Assumptions Col B

Cleanest pattern: load each query to a **table on a hidden `_Data` sheet**,
then have `Assumptions!B{row}` reference that table with `=_Data!B{n}`.

Override pattern in Assumptions:

| Col A | Col B | Col C | Col D |
|---|---|---|---|
| Driver | JSON (Power Query) | PM Override (yellow) | `=IF(C2="",B2,C2)` |

---

## Step 5 — Refresh

- **Manual**: Data → Refresh All (Ctrl+Alt+F5)
- **On open**: File → Options → Data → "Refresh data when opening file"
- **Workflow**: run `python -m src.stage_02_valuation.batch_runner --ticker IBM --json`
  then refresh Excel. Numbers will match exactly.

---

## Troubleshooting

| Error | Fix |
|---|---|
| `File not found` | Run batch_runner with `--json` first. Check path in `Config!B1`. |
| `Expression.Error: key not found` | JSON schema changed. Check `json_exporter.py` for exact key. |
| `DataFormat.Error` | Null value in JSON. Wrap with `try ... otherwise null`. |
| Query slow | Load to Connection Only; reference cells via named ranges. |
| Numbers differ from batch_runner | Should not happen — JSON is the source of truth. If it does, check that you refreshed after the latest `--json` run. |
