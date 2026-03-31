# `CALM_ticker_review2.xlsx` Workbook Inventory

## Scope

This note documents the contents of the snapshot workbook:

- source template: `templates/CALM_ticker_review2.xlsx`
- working snapshot: `output/workbook-snapshots/CALM_ticker_review2-snapshot-20260331-191703.xlsx`

This is a structural inventory only. The workbook itself was not modified.

## High-Level Summary

- The workbook is a 12-sheet Excel model.
- All sheets are visible in this snapshot.
- It is query-backed and uses a Power Query staging layer on `_Data`.
- There are no charts or embedded images in the snapshot reviewed.
- The model follows the `baseline -> override -> active` convention on the assumptions sheet.

## Workbook Conventions

- `Assumptions` uses:
  - column `B` for JSON baseline values
  - column `C` for PM overrides
  - column `D` for active values
  - column `E` for source tags
- `Config!B2` points at `CALM_latest.json`.
- Named ranges and workbook metadata include:
  - `json_path`
  - `Price`
  - hidden `ExternalData_3` through `ExternalData_7`
  - multiple `IQ_*` constants tied to workbook/query machinery
- Power Query / mashup metadata is present, including connections for:
  - `Assumptions`
  - `WACC`
  - `Scenarios`
  - `MarketData`
  - `Comps`
  - `TickerJSON`
  - the workbook data model

## Sheet Inventory

### `Cover`

- populated area: approximately `B4:C26`
- purpose: workbook title and operator guide
- contents:
  - explains the workbook flow
  - explains the `B/C/D` override convention
  - includes live links/references into `Price` and `_Data`

### `Assumptions`

- populated area: approximately `A1:E53`
- purpose: primary input and control sheet
- contents:
  - valuation assumptions for revenue, margins, tax, WACC, and equity bridge inputs
  - baseline JSON values in `B`
  - PM override cells in `C`
  - active values in `D`
  - source labels in `E`
- important note:
  - `E33` contains a malformed formula and caches as `#NAME?`

### `DCF_Base`

- populated area: approximately `A1:N43`
- purpose: base-case 10-year FCFF model
- contents:
  - revenue forecast
  - EBIT
  - D&A
  - capex
  - NWC
  - FCFF
  - ROIC
  - economic profit
  - blended terminal value / EV summary

### `DCF_Bear`

- populated area: approximately `A1:N50`
- purpose: downside case DCF
- contents:
  - same core DCF structure as base case
  - scenario multipliers in `B3:B7`
  - multipliers cover:
    - growth
    - margin
    - capex
    - WACC
    - exit multiple

### `DCF_Bull`

- populated area: approximately `A1:N50`
- purpose: upside case DCF
- contents:
  - same core DCF structure as base case
  - scenario multipliers in `B3:B7`
  - multipliers cover:
    - growth
    - margin
    - capex
    - WACC
    - exit multiple

### `Equity_Bridge`

- populated area: approximately `A1:E23`
- purpose: convert EV outputs into equity value and IV/share
- contents:
  - bear / base / bull EV-to-equity bridge
  - intrinsic value per share by scenario
  - probability-weighted expected IV
  - implied upside

### `Comps`

- populated area: approximately `A1:M17`
- purpose: comparable-company valuation sheet
- contents:
  - peer rows in roughly rows `3:11`
  - median row in row `12`
  - exclusion convention using `"x"` for peers
  - comp-implied IV outputs in roughly rows `15:17`
- output methods shown:
  - EV / EBITDA
  - EV / EBIT
  - P / E

### `Sensitivity`

- populated area: approximately `A1:J14`
- purpose: WACC versus terminal growth sensitivity table
- contents:
  - IV/share sensitivity grid
  - footer color legend

### `QoE`

- populated area: approximately `A1:E16`
- purpose: quality-of-earnings scorecard
- contents:
  - scored QoE flags
  - NWC baseline detail
- note:
  - appears mostly like a static snapshot rather than a complex live workbench

### `Output`

- populated area: approximately `A1:E33`
- purpose: summary dashboard sheet
- contents:
  - market data summary
  - IV summary
  - WACC summary
  - QoE flags / high-level outputs
- dependencies:
  - `Price`
  - `_Data`
  - `Assumptions`
  - `Equity_Bridge`
- anomaly:
  - trailing P/E resolves to `0` because `_Data!B50` is blank in the reviewed snapshot

### `Config`

- populated area: approximately `A1:B8`
- purpose: refresh control sheet
- contents:
  - JSON path control
  - refresh instructions
- key cell:
  - `B2` points at `CALM_latest.json`

### `_Data`

- populated area: approximately `A1:J64`
- purpose: Power Query staging layer
- contents:
  - loaded query tables
  - summary outputs that feed the visible model sheets

## Structural Notes

- no hidden worksheets were found in the snapshot reviewed
- no external workbook links were found
- workbook complexity appears to come from:
  - Power Query connections
  - named ranges
  - the scenario-specific DCF sheets
  - the `_Data` staging layer

## Issues Observed

1. `Assumptions!E33` shows `#NAME?` from a malformed formula.
2. `_Data!B50` is blank in the snapshot, which causes the `Output` sheet trailing P/E line to display `0`.

## Status

This workbook should be treated as a legacy / non-canonical variant unless it is intentionally promoted later. The canonical documented Power Query review workbook remains `templates/ticker_review.xlsx`.
