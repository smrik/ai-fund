# Deterministic Valuation Audit Log

**Started:** 2026-03-08  
**Audit mode:** correctness-first, deterministic-core first, phased compatibility

## Audit Rules

For every feature we must document both:

- **Financial logic:** why the calculation should work from a modeling perspective
- **Coding logic:** how the implementation enforces it in code/tests

And execute this same loop:

1. Check current implementation
2. Compare to best practices
3. Add missing features/logic
4. Test with new features and compare expected result
5. Brainstorm edge cases
6. Check downstream I/O impact and add follow-up TODOs
7. Proceed

## Run Ledger

### 2026-03-08 12:30 +01:00 - Kickoff

- Established master feature list (`F01`-`F16`)
- Baseline test status confirmed: `84 passed`
- Confirmed staged architecture exists and deterministic boundaries are already tested (`tests/test_architecture_boundaries.py`)

### 2026-03-08 12:37 +01:00 - F01 implemented

- Added deterministic revenue/growth period metadata and alignment flags in `input_assembler.py`
- Exposed metadata in batch valuation output and Excel assumptions export via `batch_runner.py`
- Added focused tests for alignment semantics and batch output fields
- Verification:
  - `python -m pytest -q tests/test_valuation_input_assembler.py tests/test_batch_runner_professional.py` → `14 passed`
  - `python -m pytest -q` → `87 passed`
### 2026-03-08 12:43 +01:00 - F02 implemented

- Hardened `get_historical_financials()` day-driver logic:
  - DIO/DPO now prefer COGS denominator when available
  - Revenue fallback preserved when COGS unavailable
  - Day metrics filtered through plausibility bounds to reduce outlier pollution
- Hardened effective tax-rate derivation to be sign-convention robust using absolute ratio bounds
- Added regression tests for COGS-based day drivers and negative-sign tax convention
- Verification:
  - `python -m pytest -q tests/test_market_data.py tests/test_valuation_input_assembler.py tests/test_batch_runner_professional.py` → `28 passed`
  - `python -m pytest -q` → `89 passed`

---

## Feature Iterations

## F01 - Revenue and period normalization

**Status:** Completed (Tranche 1)

### Step 1 - Current implementation check

**Financial logic (current):**

- Revenue base is selected from CIQ `revenue_ttm`, then yfinance `revenue_ttm`, then sector default guard.
- Growth near is selected from CIQ `rev_growth_3yr`, then yfinance-derived 3Y CAGR, then yfinance `revenue_growth`, then sector default.
- Growth is bounded before entering DCF assumptions.

**Coding logic (current):**

- Data source fields in `src/stage_00_data/market_data.py`:
  - `revenue_ttm` from yfinance info
  - `get_historical_financials()` computes `revenue_cagr_3yr`
- Assumption assembly in `src/stage_02_valuation/input_assembler.py`:
  - `_pick()` precedence for `revenue_base` and `growth_near_raw`
  - `_bounded()` clamp on growth input
  - lineage fields `revenue_base`, `revenue_growth_near`, `revenue_growth_mid`

### Step 2 - Compare to best practices

**Financial best-practice target:**

- Revenue level and growth inputs should be period-aligned and timestamped.
- Mixed-period usage (TTM level with stale annual growth) should be flagged.
- Source lineage should include period metadata, not only provider name.

**Coding best-practice target:**

- Lineage should include `source + period + as_of + currency/unit`.
- Missing/ambiguous alignment should set explicit health flags.
- Tests should cover stale data and mixed-period fallback behavior.

**Gap notes identified:**

- Current lineage stores provider but not explicit period metadata.
- No explicit flag for mixed-period revenue/growth pairing.
- No freshness flag tied to underlying date fields for revenue drivers.

### Step 3 - Missing features/logic added

- Added deterministic metadata fields in `source_lineage`:
  - `growth_source_detail`
  - `revenue_period_type`
  - `growth_period_type`
  - `revenue_alignment_flag`
  - `revenue_data_quality_flag`
- Added canonical source mapping so legacy source semantics stay stable while capturing detailed period provenance.
- Extended batch row payload + `Assumptions & Sources` export columns to include the new metadata.

### Step 4 - Test results

- Added unit tests in `tests/test_valuation_input_assembler.py`:
  - `test_revenue_alignment_flags_when_growth_comes_from_cagr`
  - `test_revenue_alignment_flags_when_growth_comes_from_ttm_yoy`
- Added integration test in `tests/test_batch_runner_professional.py`:
  - `test_value_single_ticker_emits_revenue_alignment_metadata`
- Verification output:
  - `python -m pytest -q tests/test_valuation_input_assembler.py tests/test_batch_runner_professional.py` → `14 passed`
  - `python -m pytest -q` → `87 passed`


### Step 5 - Edge cases to add

- Negative/rebased revenue year causing invalid CAGR denominator.
- Newly listed companies with <3 years of revenue history.
- CIQ revenue available but growth missing and vice versa.
- Currency/scale mismatch between CIQ and yfinance.

### Step 6 - Downstream impact TODOs

- Completed: batch export columns now include the new revenue alignment metadata in `Assumptions & Sources`.
- Validate Stage 2 filter does not assume fixed schema ordering.
- Confirm any consumers of `latest.csv` tolerate added columns.

### Step 7 - Proceed

- F01 complete for this tranche. Follow-on feature F02 is now completed; next active feature is F03.

---

## F02 - Historical financial extraction integrity

**Status:** Completed (Tranche 1)

### Step 1 - Current implementation check

**Financial logic (current before changes):**

- Capex sign normalization and NWC series construction were deterministic and stable.
- DSO/DIO/DPO all used revenue denominators, which can understate inventory/payables intensity for high-COGS businesses.
- Effective tax rate only used positive pretax rows, causing data loss under negative sign conventions.

**Coding logic (current before changes):**

- `get_historical_financials()` in `src/stage_00_data/market_data.py` extracted annual statement rows and computed derived averages.
- Day drivers were simple ratio loops with no denominator hierarchy and minimal plausibility filtering.

### Step 2 - Compare to best practices

**Financial best-practice target:**

- DIO and DPO should use COGS where available; revenue fallback is secondary.
- Day-driver outliers should be filtered to avoid contaminating reinvestment assumptions.
- Effective tax ratio handling should be robust to filing sign conventions.

**Coding best-practice target:**

- Deterministic denominator precedence with explicit fallback.
- Bounded inclusion criteria for day metrics.
- Stable tax-rate calculation despite sign flips in source data.

### Step 3 - Missing features/logic added

- Added `cost_of_revenue` extraction from annual P&L rows.
- Updated DIO/DPO derivation to:
  - prefer COGS denominator,
  - fallback to revenue if COGS missing,
  - filter implausible day values.
- Updated effective tax-rate derivation to use absolute ratio bounds for sign-convention robustness.

### Step 4 - Test results

- Added market-data regression tests:
  - `test_nwc_day_drivers_prefer_cogs_for_dio_and_dpo`
  - `test_effective_tax_rate_handles_negative_sign_convention`
- Verification output:
  - `python -m pytest -q tests/test_market_data.py tests/test_valuation_input_assembler.py tests/test_batch_runner_professional.py` → `28 passed`
  - `python -m pytest -q` → `89 passed`

### Step 5 - Edge cases to add

- Negative/zero COGS for specific sectors (fallback behavior across sparse years).
- Abrupt working-capital reclassification year-over-year (statement taxonomy drift).
- Extreme payables/inventory days from M&A-heavy years.

### Step 6 - Downstream impact TODOs

- Confirm NWC driver changes do not create unintended shifts in historical-to-target fade diagnostics.
- Add an explicit provenance field later for day-driver denominator source if PM review needs per-ticker transparency.

### Step 7 - Proceed

- F02 complete for this tranche. Next active feature: F03 CIQ workbook contract and ingestion.

## F03 - CIQ workbook contract and ingestion

**Status:** Queued

1. [ ] Check current implementation
2. [ ] Compare to best practices
3. [ ] Add missing features/logic
4. [ ] Test with expected result comparison
5. [ ] Brainstorm edge cases
6. [ ] Check downstream I/O impact + TODOs
7. [ ] Proceed

## F04 - CIQ snapshot adapter mapping

**Status:** Queued

1. [ ] Check current implementation
2. [ ] Compare to best practices
3. [ ] Add missing features/logic
4. [ ] Test with expected result comparison
5. [ ] Brainstorm edge cases
6. [ ] Check downstream I/O impact + TODOs
7. [ ] Proceed

## F05 - Assumption precedence and lineage

**Status:** Queued

1. [ ] Check current implementation
2. [ ] Compare to best practices
3. [ ] Add missing features/logic
4. [ ] Test with expected result comparison
5. [ ] Brainstorm edge cases
6. [ ] Check downstream I/O impact + TODOs
7. [ ] Proceed

## F06 - Driver bounds and clipping diagnostics

**Status:** Queued

1. [ ] Check current implementation
2. [ ] Compare to best practices
3. [ ] Add missing features/logic
4. [ ] Test with expected result comparison
5. [ ] Brainstorm edge cases
6. [ ] Check downstream I/O impact + TODOs
7. [ ] Proceed

## F07 - WACC engine correctness

**Status:** Queued

1. [ ] Check current implementation
2. [ ] Compare to best practices
3. [ ] Add missing features/logic
4. [ ] Test with expected result comparison
5. [ ] Brainstorm edge cases
6. [ ] Check downstream I/O impact + TODOs
7. [ ] Proceed

## F08 - DCF projection engine

**Status:** Queued

1. [ ] Check current implementation
2. [ ] Compare to best practices
3. [ ] Add missing features/logic
4. [ ] Test with expected result comparison
5. [ ] Brainstorm edge cases
6. [ ] Check downstream I/O impact + TODOs
7. [ ] Proceed

## F09 - NWC driver framework

**Status:** Queued

1. [ ] Check current implementation
2. [ ] Compare to best practices
3. [ ] Add missing features/logic
4. [ ] Test with expected result comparison
5. [ ] Brainstorm edge cases
6. [ ] Check downstream I/O impact + TODOs
7. [ ] Proceed

## F10 - Terminal value methodology

**Status:** Queued

1. [ ] Check current implementation
2. [ ] Compare to best practices
3. [ ] Add missing features/logic
4. [ ] Test with expected result comparison
5. [ ] Brainstorm edge cases
6. [ ] Check downstream I/O impact + TODOs
7. [ ] Proceed

## F11 - Scenario framework and expected IV

**Status:** Queued

1. [ ] Check current implementation
2. [ ] Compare to best practices
3. [ ] Add missing features/logic
4. [ ] Test with expected result comparison
5. [ ] Brainstorm edge cases
6. [ ] Check downstream I/O impact + TODOs
7. [ ] Proceed

## F12 - Reverse DCF solver

**Status:** Queued

1. [ ] Check current implementation
2. [ ] Compare to best practices
3. [ ] Add missing features/logic
4. [ ] Test with expected result comparison
5. [ ] Brainstorm edge cases
6. [ ] Check downstream I/O impact + TODOs
7. [ ] Proceed

## F13 - Comps valuation pipeline

**Status:** Queued

1. [ ] Check current implementation
2. [ ] Compare to best practices
3. [ ] Add missing features/logic
4. [ ] Test with expected result comparison
5. [ ] Brainstorm edge cases
6. [ ] Check downstream I/O impact + TODOs
7. [ ] Proceed

## F14 - One-off exclusion boundary (QoE)

**Status:** Queued

1. [ ] Check current implementation
2. [ ] Compare to best practices
3. [ ] Add missing features/logic
4. [ ] Test with expected result comparison
5. [ ] Brainstorm edge cases
6. [ ] Check downstream I/O impact + TODOs
7. [ ] Proceed

## F15 - Batch output contract and persistence

**Status:** Queued

1. [ ] Check current implementation
2. [ ] Compare to best practices
3. [ ] Add missing features/logic
4. [ ] Test with expected result comparison
5. [ ] Brainstorm edge cases
6. [ ] Check downstream I/O impact + TODOs
7. [ ] Proceed

## F16 - Screening and architecture integration

**Status:** Queued

1. [ ] Check current implementation
2. [ ] Compare to best practices
3. [ ] Add missing features/logic
4. [ ] Test with expected result comparison
5. [ ] Brainstorm edge cases
6. [ ] Check downstream I/O impact + TODOs
7. [ ] Proceed










### 2026-03-08 13:17 +01:00 - BUSO97 step audit mapped (S00-S20)

- Converted BUSO97 pseudo-code into a full master TODO checklist under `2026-03-08-deterministic-audit-master-todo.md`.
- Classified current deterministic stack coverage:
  - `Working`: 7 steps
  - `Partial`: 12 steps
  - `Missing`: 2 steps
- Verified evidence with focused deterministic test sweep:
  - `python -m pytest -q tests/test_professional_dcf.py tests/test_wacc.py tests/test_valuation_input_assembler.py tests/test_batch_runner_professional.py tests/test_batch_runner_ciq_precedence.py tests/test_ciq_parser.py tests/test_ciq_ingest.py tests/test_ciq_adapter.py tests/test_qoe_agent.py tests/test_architecture_boundaries.py`
  - Result: `60 passed in 3.15s`
- Locked next-priority implementation queue from BUSO97 gaps:
  1. Economic Profit cross-check module (missing)
  2. EV->Equity bridge hardening beyond net debt
  3. Terminal value-driver form with RONIC and stable-state constraints


### 2026-03-08 15:40 +01:00 - Tranche 2 hardening completed (F05/F07/F08/F09/F10/F11/F12/F15)

- Added professional output contract coverage in `batch_runner.py`:
  - EV bridge columns (`ev_operations_mm`, `ev_total_mm`, `non_operating_assets_mm`, `non_equity_claims_mm`)
  - EP cross-check columns (`ep_ev_operations_mm`, `ep_iv_base`, `dcf_ep_gap_pct`, `ep_reconcile_flag`)
  - FCFE branch columns (`fcfe_iv_base`, `fcfe_equity_mm`, `fcfe_pv_sum_mm`, `fcfe_terminal_value_mm`, `cost_of_equity_model`)
  - Terminal decomposition columns (`tv_*`, `pv_tv_*`, `terminal_growth_pct`, `terminal_ronic_pct`, `terminal_fcff_11_*`, `gordon_formula_mode`)
  - Deterministic health flags (`health_*`)
- Extended batch assumptions/export lineage with source fields for bridge claims, WACC source, and story profile metadata.
- Added/extended tests:
  - `tests/test_professional_dcf.py`: EV-bridge deltas, EP/FCFE output population, FCFE wrapper equivalence.
  - `tests/test_batch_runner_professional.py`: professional bridge/health fields emitted for DCF-applicable tickers and explicitly null for `alt_model_required`.
- Updated design docs to match implemented formulas/contracts:
  - `docs/design-docs/deterministic-valuation-flow-spec.md`
  - `docs/reference/valuation-glossary.md`

Verification:
- `python -m pytest -q tests/test_professional_dcf.py tests/test_batch_runner_professional.py` -> `18 passed`
- `python -m pytest -q` -> `94 passed`
