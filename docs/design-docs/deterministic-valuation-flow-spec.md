# Deterministic Valuation Flow Spec

## 1. Purpose

This document defines the deterministic valuation path in Stage 00 -> Stage 02.

Non-negotiable boundary:
- Data and computation are deterministic.
- LLM logic is not used in this path.
- Flow direction is one-way: Data -> Computation -> Judgment.

## 2. Scope

In scope modules:
- `src/stage_00_data/market_data.py`
- `src/stage_00_data/ciq_adapter.py`
- `src/stage_02_valuation/input_assembler.py`
- `src/stage_02_valuation/wacc.py`
- `src/stage_02_valuation/professional_dcf.py`
- `src/stage_02_valuation/batch_runner.py`

Primary deterministic entrypoint:
- `value_single_ticker(ticker)` in `batch_runner.py`

## 3. End-to-End Flow

### Step A: Data pull

`build_valuation_inputs(ticker)` pulls deterministic inputs from:
- yfinance market snapshot
- yfinance historical financials
- CIQ snapshot
- CIQ comps snapshot

Hard skips:
- `price <= 0`
- `revenue_base <= 0`

### Step B: Assumption assembly

Precedence for each assumption:
1. CIQ
2. yfinance
3. sector default

Then deterministic overrides:
1. global override
2. sector override
3. ticker override

Lineage is emitted per assumption in `source_lineage`.

### Step C: WACC and capital structure

`compute_wacc_from_yfinance()` returns CAPM/WACC components.

Core equations:
- `beta_unlevered = beta_levered / (1 + (1 - tax) * D/E)`
- `beta_relevered = beta_unlevered * (1 + (1 - tax) * D/E_target)`
- `cost_of_equity = Rf + beta_relevered * ERP + size_premium`
- `cost_of_debt_after_tax = Kd * (1 - tax)`
- `wacc = cost_of_equity * E/V + cost_of_debt_after_tax * D/V`

### Step D: Scenario valuation

`run_probabilistic_valuation(drivers, scenario_specs, current_price)`:
- normalizes probabilities
- runs `run_dcf_professional` per scenario
- computes `expected_iv = sum(p_i * iv_i)`

Default policy:
- bear/base/bull = `20% / 60% / 20%`

### Step E: Reverse DCF

`reverse_dcf_professional` solves implied near-term growth via bisection while preserving the model fade rule between near and mid growth.

### Step F: Batch output assembly

`value_single_ticker` emits:
- assumptions + source lineage
- scenario IVs and expected IV/upside
- EV bridge, EP cross-check, FCFE branch outputs
- terminal-method decomposition and health flags
- serialized artifacts: `drivers_json`, `forecast_bridge_json`

## 4. Contracts

### `ValuationInputsWithLineage`

Contains identity, model applicability, `ForecastDrivers`, lineage maps, and CIQ/WACC metadata.

### `ForecastDrivers`

Key validated bounds:
- growth near: `[-0.20, 0.50]`
- growth mid: `[-0.20, 0.40]`
- terminal growth: `[0.00, 0.05]`
- margins: `[0.00, 0.80]`
- tax rates: `[0.05, 0.45]`
- capex%: `[0.00, 0.35]`
- d&a%: `[0.00, 0.25]`
- WACC: `[0.03, 0.20]`
- exit multiple: `[2.0, 40.0]`
- terminal RONIC: `[0.04, 0.45]`
- debt weight: `[0.00, 0.80]`
- optional cost of equity: `[0.04, 0.30]`
- `revenue_base > 0`, `shares_outstanding > 0`

### `ProjectionYear`

Year-level bridge fields include:
- operating path (`revenue`, `ebit`, `nopat`)
- reinvestment path (`capex`, `da`, `nwc`, `delta_nwc`, `reinvestment`)
- cash flow path (`fcff`, `pv_fcff`, `fcfe`, `pv_fcfe`)
- invested-capital path (`invested_capital_start`, `invested_capital_end`, `roic`, `economic_profit`)

### `DCFComputationResult`

Scenario-level deterministic outputs include:
- EV and equity outputs (`enterprise_value_operations`, `enterprise_value_total`, `equity_value`)
- per-method IVs (`iv_gordon`, `iv_exit`, `iv_blended`)
- terminal decomposition (`TerminalBreakdown`)
- diagnostics (`tv_pct_of_ev`, `roic_consistency_flag`, `nwc_driver_quality_flag`)
- EP cross-check (`ep_enterprise_value`, `ep_intrinsic_value_per_share`, `dcf_ep_gap_pct`, `ep_reconcile_flag`)
- FCFE branch (`fcfe_intrinsic_value_per_share`, `fcfe_equity_value`, `fcfe_pv_sum`, `fcfe_terminal_value`)
- health flags map

## 5. Core Formulas

### 5.1 Forecast and FCFF

Per year `y`:
- `Revenue_y = Revenue_{y-1} * (1 + growth_y)`
- `EBIT_y = Revenue_y * margin_y`
- `NOPAT_y = EBIT_y * (1 - tax_y)`
- `NWC_y = AR_y + Inventory_y - AP_y`
- `deltaNWC_y = NWC_y - NWC_{y-1}`
- `FCFF_y = NOPAT_y + D&A_y - CapEx_y - deltaNWC_y`

### 5.2 Terminal value (computed every run)

Year 11 bridge:
- `FCFF_11_bridge = NOPAT_11 + D&A_11 - CapEx_11 - deltaNWC_11`

Value-driver form (when valid):
- `reinvestment_rate_terminal = g_terminal / RONIC_terminal`
- `FCFF_11_value_driver = NOPAT_11 * (1 - reinvestment_rate_terminal)`

Gordon TV input selection:
- use `FCFF_11_value_driver` when valid, else `FCFF_11_bridge`

Terminal methods:
- `TV_Gordon = FCFF_11 / (WACC - g_terminal)`
- `TV_Exit = terminal_metric_10 * exit_multiple`

Blend/fallback:
- default blend `60% Gordon / 40% Exit` when both valid
- deterministic fallback to single valid method
- explicit `tv_method_fallback_flag`

### 5.3 EV -> Equity bridge

- `EV_operations = PV(FCFF_1..10) + PV(TV_blended)`
- `EV_total = EV_operations + non_operating_assets`
- `non_equity_claims = net_debt + minority + preferred + pension + leases + options + convertibles`
- `equity_value = EV_total - non_equity_claims`
- `IV = equity_value / shares_outstanding`

## 6. Deterministic Diagnostics and Audit

Batch output includes:
- scenario IVs and expected IV
- EV bridge columns
- EP reconciliation columns
- FCFE branch columns
- terminal-method columns (raw and PV)
- health flags (`tv_extreme`, terminal guardrails, contamination flag)
- full source lineage and story-profile metadata

Artifacts for reproducibility:
- `drivers_json`
- `forecast_bridge_json`

## 7. Determinism Guarantees

Determinism is guaranteed by:
- pure arithmetic over explicit inputs
- fixed, code-defined bounds/fallback rules
- explicit scenario probabilities
- no randomization
- no LLM call in data/computation path
