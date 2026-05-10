# Deterministic Valuation Audit Master TODO

**Date:** 2026-03-08  
**Owner:** Codex + PM  
**Scope:** Data + Computation layers only (Stage 00/01/02)  
**Invariant:** No LLM logic in deterministic compute path

## Objective

Run a correctness-first audit of every valuation process:

- revenue and historical financial sourcing
- projection logic by driver
- WACC derivation
- comps valuationw
- one-off handling boundaries
- output lineage and reproducibility

Each feature must pass the same 7-step loop:

1. Check current implementation
2. Compare to best practices
3. Add missing features/logic
4. Test new features and compare expected result
5. Brainstorm new edge cases
6. Check downstream I/O impact and add follow-up TODOs
7. Proceed to next feature

## Baseline (Before Audit Edits)

- Test suite baseline: `84 passed`
- Batch contract includes lineage/scenario columns and Excel export tabs
- Repository already has in-flight valuation hardening edits (tracked in git status)

## Feature Inventory

| ID  | Feature To Audit                          | Financial Logic Focus                                             | Coding Logic Focus                                                    | Status                |
| --- | ----------------------------------------- | ----------------------------------------------------------------- | --------------------------------------------------------------------- | --------------------- |
| F01 | Revenue and period normalization          | TTM vs annual alignment, growth base integrity                    | `market_data.py` extraction + normalization boundaries                | Completed (Tranche 1) |
| F02 | Historical financial extraction integrity | Capex/D&A sign, NWC construction, tax denominator correctness     | `market_data.py` row mapping, missing-key fallback safety             | Completed (Tranche 1) |
| F03 | CIQ workbook contract and ingestion       | Deterministic source-of-truth ingestion semantics                 | `ciq/workbook_parser.py`, `ciq/ingest.py` template lock + idempotency | Not started           |
| F04 | CIQ snapshot adapter mapping              | Canonical field mapping into valuation inputs                     | `stage_00_data/ciq_adapter.py` mapping + fallback merge               | Not started           |
| F05 | Assumption precedence and lineage         | CIQ > yfinance > default > override consistency                   | `input_assembler.py` `_pick`, lineage coverage, override stamps       | Not started           |
| F06 | Driver bounds and clipping diagnostics    | Realistic ranges for growth/margin/tax/NWC drivers                | `input_assembler.py` bounds + explicit flags                          | Not started           |
| F07 | WACC engine correctness                   | CAPM, unlever/relever beta, debt cost, size premia                | `wacc.py` math paths, no-peer/zero-debt paths, audit fields           | Not started           |
| F08 | DCF projection engine                     | Revenue/margin/tax/reinvestment fade mechanics                    | `professional_dcf.py` year-path math and FCFF bridge                  | Not started           |
| F09 | NWC driver framework                      | DSO/DIO/DPO economics and delta NWC behavior                      | `professional_dcf.py` NWC component math + validation                 | Not started           |
| F10 | Terminal value methodology                | Gordon + Exit blend, fallback legality, TV concentration          | `professional_dcf.py` terminal branch logic + flags                   | Not started           |
| F11 | Scenario framework and expected IV        | Probabilistic weighting quality and decision utility              | `professional_dcf.py` scenario normalization + expected value         | Not started           |
| F12 | Reverse DCF solver                        | Implied-growth consistency with forward DCF engine                | `professional_dcf.py`, `batch_runner.py` call path unification        | Not started           |
| F13 | Comps valuation pipeline                  | Peer multiple relevance and denominator hygiene                   | `ciq_adapter.py`, `batch_runner.py` comps input usage                 | Not started           |
| F14 | One-off exclusion boundary (QoE)          | Recurring vs non-recurring treatment control                      | `qoe_agent.py` contract + deterministic acceptance boundary           | Not started           |
| F15 | Batch output contract and persistence     | Auditability for PM review and reproducibility                    | `batch_runner.py`, SQLite persistence, CSV/XLSX exports               | Not started           |
| F16 | Screening and architecture integration    | Screen/valuation coherence and deterministic boundary enforcement | `stage1_filter.py`, `stage2_filter.py`, boundary tests                | Not started           |

## BUSO97 Step Audit (0-20)

Status legend: `Working` = implemented + test-backed, `Partial` = implemented but not institutional-complete, `Missing` = not implemented in deterministic stack.

| Step | BUSO97 Area                            | Status         | Current Check (Code + Tests)                                                                                                                                                                                                                          | Gap / TODO                                                                                                                                                              |
| ---- | -------------------------------------- | -------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| S00  | High-level valuation philosophy        | Partial        | DCF outputs EV/Equity/IV and scenario/sensitivity exports in `src/stage_02_valuation/professional_dcf.py` + `src/stage_02_valuation/batch_runner.py`; covered by `tests/test_professional_dcf.py` and `tests/test_batch_runner_professional.py`.      | Add deterministic Economic Profit cross-check to fully match BUSO97 dual-method philosophy.                                                                             |
| S01  | Master valuation algorithm end-to-end  | Partial        | Pipeline exists: `build_valuation_inputs()` -> `run_probabilistic_valuation()` -> `reverse_dcf_professional()` in `src/stage_02_valuation/`; batch orchestration in `value_single_ticker()` (`batch_runner.py`).                                      | Missing explicit modules for business narrative translation, full accounting recast, and EP reconciliation stage.                                                       |
| S02  | Business + industry understanding      | Partial        | Sector/industry pulled from yfinance in `src/stage_00_data/market_data.py`; sector policy/exit metric mapping in `input_assembler.py`; Stage 2 quality filter in `src/stage_01_screening/stage2_filter.py`.                                           | Add deterministic narrative-to-driver framework (competitive position, cyclicality, moat duration) as structured inputs, not implicit defaults.                         |
| S03  | Recast and adjust financial statements | Partial        | Current adjustments: capex sign normalization, tax sign robustness, NWC derivation in `get_historical_financials()` (`market_data.py`); CIQ normalization in `ciq/workbook_parser.py`; QoE agent contract in `src/stage_03_judgment/qoe_agent.py`.    | Missing full operating vs financing recast (leases, pensions, excess cash separation, debt-like claims); QoE not yet wired into deterministic input assembler boundary. |
| S04  | Historical performance analysis        | Working (core) | Historical metrics produced in `market_data.py` (`revenue_cagr_3yr`, margins, capex/DA ratios, DSO/DIO/DPO, tax, cost of debt); CIQ historical extraction in `workbook_parser.py`. Tested by `tests/test_market_data.py`, `tests/test_ciq_parser.py`. | Add explicit historical ROIC decomposition table and trend diagnostics artifact in output.                                                                              |
| S05  | Forecast pro forma build               | Working (core) | 10-year deterministic forecast with growth/margin/tax/capex/DA/NWC trajectories in `run_dcf_professional()` (`professional_dcf.py`).                                                                                                                  | Add explicit forecast horizon policy object (mature vs high-growth horizon selection) and optional invested-capital-turnover projection mode.                           |
| S06  | Cost of capital (WACC)                 | Working        | CAPM + unlever/relever beta + size premium + capital structure weighting in `src/stage_02_valuation/wacc.py`; tests in `tests/test_wacc.py` (beta math, fallbacks, zero-debt, audit fields).                                                          | Add country risk premium and explicit target capital-structure policy override hooks.                                                                                   |
| S07  | FCFF computation                       | Working        | FCFF bridge (`NOPAT + D&A - CapEx - dNWC`) implemented in `run_dcf_professional()`; validated in `tests/test_professional_dcf.py` (`test_nwc_driver_bridge_uses_dso_dio_dpo_identity`).                                                               | Add optional alternate FCFF presentation (NOPAT - delta invested capital) in exports for audit readability.                                                             |
| S08  | Continuing/terminal value              | Partial        | Gordon + Exit computed each run with deterministic blend and fallback in `professional_dcf.py`; tested in `tests/test_professional_dcf.py` (`test_terminal_blend_fallback_when_gordon_invalid`).                                                      | Add value-driver terminal formula (`NOPAT*(1-g/RONIC)/(WACC-g)`) and explicit stable-state economic constraints report.                                                 |
| S09  | Discounting to present value           | Working        | PV of yearly FCFF + PV terminal in `run_dcf_professional()` with per-year `discount_factor` and `pv_fcff`.                                                                                                                                            | Add timing-policy switch (mid-year vs end-year) and coverage tests for timing convention.                                                                               |
| S10  | EV -> Equity bridge                    | Partial        | Current bridge is `equity_value = enterprise_value - net_debt` in `professional_dcf.py`; net debt sourced with lineage in `input_assembler.py`.                                                                                                       | Add full bridge: non-operating assets, minority interest, preferreds, leases, pension deficits, option dilution adjustments.                                            |
| S11  | Value per share computation            | Working (core) | Per-share IV computed via `equity_value / shares_outstanding` in `professional_dcf.py`; shares lineage handled in `input_assembler.py`; surfaced in batch outputs.                                                                                    | Add diluted-share schedule support (options/converts/TSM) instead of single shares field.                                                                               |
| S12  | Economic Profit method cross-check     | Missing        | No deterministic EP valuation module or DCF-vs-EP reconciliation artifact currently.                                                                                                                                                                  | Implement `run_economic_profit_valuation()` and reconciliation flags/output columns.                                                                                    |
| S13  | Diagnostics + sanity checks            | Partial        | Current diagnostics: `tv_pct_of_ev`, `tv_high_flag`, `roic_consistency_flag`, `nwc_driver_quality_flag`, lineage flags in `batch_runner.py` + `professional_dcf.py`; tests in `test_batch_runner_professional.py`.                                    | Add structured realism checks (terminal growth vs macro cap, margin vs peer bounds, valuation-vs-comps reasonability deltas).                                           |
| S14  | Sensitivity + scenario analysis        | Working        | Scenario engine in `run_probabilistic_valuation()` + default bear/base/bull; 2D sensitivity grids in `_sensitivity_rows()` and Excel export tabs. Tests in `tests/test_professional_dcf.py` and `tests/test_batch_runner_professional.py`.            | Extend to configurable scenario sets and ticker/sector-specific probability policies.                                                                                   |
| S15  | Alternative FCFE branch                | Missing        | No FCFE valuation path currently in deterministic compute layer.                                                                                                                                                                                      | Implement optional FCFE engine for cases where equity-cash-flow framework is preferred.                                                                                 |
| S16  | Compact exam-style valuation flow      | Partial        | Process spread across code/docs; this BUSO97 checklist now maps it end-to-end.                                                                                                                                                                        | Add a single deterministic flow spec doc in `docs/design-docs/` with exact contract objects and formulas.                                                               |
| S17  | Mini-glossary of key variables         | Partial        | Terms appear in code/dataclasses (`ForecastDrivers`, `DCFComputationResult`) and docs, but no canonical glossary file tied to the model schema.                                                                                                       | Add `docs/reference/valuation-glossary.md` with formula + field-name mapping.                                                                                           |
| S18  | Common valuation mistake controls      | Partial        | Bounds validation, fallback flags, deterministic tests exist (`professional_dcf.py`, `input_assembler.py`, `test_professional_dcf.py`, `test_valuation_input_assembler.py`).                                                                          | Add explicit "mistake guardrail" checks/report rows (e.g., FCFF-interest contamination, TV dominance threshold tiers, denominator mismatch alerts).                     |
| S19  | Story-to-numbers mapping               | Partial        | Current mapping is sector defaults + CIQ/yfinance precedence + manual overrides (`input_assembler.py`, `config/valuation_overrides.yaml`).                                                                                                            | Add structured thesis-driver schema so assumptions are traceable to named strategic hypotheses.                                                                         |
| S20  | One-line summary formula logic         | Partial        | DCF one-line logic implemented (PV FCFF + PV TV; per-share IV).                                                                                                                                                                                       | Add EP one-line logic side-by-side in outputs so both formula families are always reconcilable.                                                                         |

## BUSO97 Priority Queue (Next Tranche)

1. `P1` Implement S12 Economic Profit cross-check module and batch export columns (`ep_ev`, `ep_iv`, `dcf_ep_gap_pct`, `ep_reconcile_flag`).
2. `P1` Harden S10 EV-to-equity bridge with non-operating assets and non-equity claims beyond net debt.
3. `P1` Upgrade S08 terminal value to value-driver form with explicit `RONIC` and stable-state diagnostics.
4. `P2` Add diluted-share mechanics (options/convertibles) to S11 per-share bridge.
5. `P2` Add deterministic narrative driver schema for S02/S19 (story-to-number mapping with lineage).
6. `P2` Add explicit valuation glossary + compact flow spec docs for S16/S17.

## Per-Feature 7-Step Checklist

### F01 Revenue and period normalization

- [x] 1. Check current implementation
- [x] 2. Compare to best practices
- [x] 3. Add missing features/logic
- [x] 4. Test and compare expected results
- [x] 5. Brainstorm edge cases
- [x] 6. Check downstream impact + TODOs
- [x] 7. Proceed

### F02 Historical financial extraction integrity

- [x] 1. Check current implementation
- [x] 2. Compare to best practices
- [x] 3. Add missing features/logic
- [x] 4. Test and compare expected results
- [x] 5. Brainstorm edge cases
- [x] 6. Check downstream impact + TODOs
- [x] 7. Proceed

### F03 CIQ workbook contract and ingestion

- [ ] 1. Check current implementation
- [ ] 2. Compare to best practices
- [ ] 3. Add missing features/logic
- [ ] 4. Test and compare expected results
- [ ] 5. Brainstorm edge cases
- [ ] 6. Check downstream impact + TODOs
- [ ] 7. Proceed

### F04 CIQ snapshot adapter mapping

- [ ] 1. Check current implementation
- [ ] 2. Compare to best practices
- [ ] 3. Add missing features/logic
- [ ] 4. Test and compare expected results
- [ ] 5. Brainstorm edge cases
- [ ] 6. Check downstream impact + TODOs
- [ ] 7. Proceed

### F05 Assumption precedence and lineage

- [ ] 1. Check current implementation
- [ ] 2. Compare to best practices
- [ ] 3. Add missing features/logic
- [ ] 4. Test and compare expected results
- [ ] 5. Brainstorm edge cases
- [ ] 6. Check downstream impact + TODOs
- [ ] 7. Proceed

### F06 Driver bounds and clipping diagnostics

- [ ] 1. Check current implementation
- [ ] 2. Compare to best practices
- [ ] 3. Add missing features/logic
- [ ] 4. Test and compare expected results
- [ ] 5. Brainstorm edge cases
- [ ] 6. Check downstream impact + TODOs
- [ ] 7. Proceed

### F07 WACC engine correctness

- [ ] 1. Check current implementation
- [ ] 2. Compare to best practices
- [ ] 3. Add missing features/logic
- [ ] 4. Test and compare expected results
- [ ] 5. Brainstorm edge cases
- [ ] 6. Check downstream impact + TODOs
- [ ] 7. Proceed

### F08 DCF projection engine

- [ ] 1. Check current implementation
- [ ] 2. Compare to best practices
- [ ] 3. Add missing features/logic
- [ ] 4. Test and compare expected results
- [ ] 5. Brainstorm edge cases
- [ ] 6. Check downstream impact + TODOs
- [ ] 7. Proceed

### F09 NWC driver framework

- [ ] 1. Check current implementation
- [ ] 2. Compare to best practices
- [ ] 3. Add missing features/logic
- [ ] 4. Test and compare expected results
- [ ] 5. Brainstorm edge cases
- [ ] 6. Check downstream impact + TODOs
- [ ] 7. Proceed

### F10 Terminal value methodology

- [ ] 1. Check current implementation
- [ ] 2. Compare to best practices
- [ ] 3. Add missing features/logic
- [ ] 4. Test and compare expected results
- [ ] 5. Brainstorm edge cases
- [ ] 6. Check downstream impact + TODOs
- [ ] 7. Proceed

### F11 Scenario framework and expected IV

- [ ] 1. Check current implementation
- [ ] 2. Compare to best practices
- [ ] 3. Add missing features/logic
- [ ] 4. Test and compare expected results
- [ ] 5. Brainstorm edge cases
- [ ] 6. Check downstream impact + TODOs
- [ ] 7. Proceed

### F12 Reverse DCF solver

- [ ] 1. Check current implementation
- [ ] 2. Compare to best practices
- [ ] 3. Add missing features/logic
- [ ] 4. Test and compare expected results
- [ ] 5. Brainstorm edge cases
- [ ] 6. Check downstream impact + TODOs
- [ ] 7. Proceed

### F13 Comps valuation pipeline

- [ ] 1. Check current implementation
- [ ] 2. Compare to best practices
- [ ] 3. Add missing features/logic
- [ ] 4. Test and compare expected results
- [ ] 5. Brainstorm edge cases
- [ ] 6. Check downstream impact + TODOs
- [ ] 7. Proceed

### F14 One-off exclusion boundary (QoE)

- [ ] 1. Check current implementation
- [ ] 2. Compare to best practices
- [ ] 3. Add missing features/logic
- [ ] 4. Test and compare expected results
- [ ] 5. Brainstorm edge cases
- [ ] 6. Check downstream impact + TODOs
- [ ] 7. Proceed

### F15 Batch output contract and persistence

- [ ] 1. Check current implementation
- [ ] 2. Compare to best practices
- [ ] 3. Add missing features/logic
- [ ] 4. Test and compare expected results
- [ ] 5. Brainstorm edge cases
- [ ] 6. Check downstream impact + TODOs
- [ ] 7. Proceed

### F16 Screening and architecture integration

- [ ] 1. Check current implementation
- [ ] 2. Compare to best practices
- [ ] 3. Add missing features/logic
- [ ] 4. Test and compare expected results
- [ ] 5. Brainstorm edge cases
- [ ] 6. Check downstream impact + TODOs
- [ ] 7. Proceed

## Tranche 2 Update (2026-03-08)

Completed in code + tests:

- `F05` Assumption precedence and lineage: extended lineage to capital-bridge, WACC source, story profile, and terminal economics fields.
- `F07` WACC engine correctness: dedicated `tests/test_wacc.py` now part of green suite.
- `F08` DCF projection engine: professional engine now emits invested-capital roll-forward, ROIC, EP, and FCFE bridge artifacts.
- `F09` NWC driver framework: days-driver path remains deterministic and test-covered (`test_nwc_driver_bridge_uses_dso_dio_dpo_identity`).
- `F10` Terminal value methodology: value-driver FCFF(11) support plus Gordon/Exit blend and deterministic fallback flags.
- `F11` Scenario framework and expected IV: deterministic probability normalization and expected IV/upside outputs remain active.
- `F12` Reverse DCF solver: batch path now uses `reverse_dcf_professional` only.
- `F15` Batch output contract and persistence: batch row/export now includes EV bridge, EP cross-check, FCFE branch, terminal decomposition, and health flags.

Verification snapshot after tranche:

- Full suite: `python -m pytest -q` -> `94 passed`.

Open carry-forward items:

- `F03/F04` CIQ ingestion+adapter depth hardening on the new clean workbook template.
- `F14` QoE deterministic boundary wiring (agent output used as review context, not compute mutation).
- `F16` screening/valuation coupling diagnostics and architecture boundary stress tests.

## Dashboard / CIQ / Report Backlog (2026-03-14)

Context:

- User reverted `ciq/templates/ciq_cleandata.xlsx` back to IBM for easier production-mode testing.
- UI-heavy work should be left to Claude.
- Backend / parser / data-flow work can be handled by Codex.
- Relevant storage surfaces already in repo:
  - dashboard UI: `dashboard/app.py`
  - DCF audit payloads: `src/stage_04_pipeline/dcf_audit.py`
  - pipeline history / artifacts: `src/stage_04_pipeline/agent_cache.py`
  - shared filing retrieval: `src/stage_00_data/filing_retrieval.py`
  - CIQ ingest/parser: `ciq/ingest.py`, `ciq/workbook_parser.py`

### Claude-Owned UI / UX Backlog

- Improve DCF Audit graphs using Playwright review:
  - fix clipping / scroll issues
  - review viewport width and responsive layout
  - make the sensitivity analysis readable
  - improve tab switching
  - surface current valuation in a persistent sidebar while Assumption Lab inputs change
  - consider auto-collapsing the left sidebar after ticker selection
  - improve the force-refresh agent selector UX
- Fix Assumption Lab interaction issues:
  - buttons do not switch inputs reliably
  - current selection state is too easy to lose
- Improve the Filings tab:
  - full analysis content should be fully visible and scrollable
  - fix formatting issues like `andOperatingLoss` running together
- Fix Recommendations tab formatting:
  - percentages like `10.0%` should not render as `0.1000`
- Add clearer WACC audit UI:
  - show the WACC build in a dedicated table
  - allow comparison of bottom-up vs industry vs Hamada beta approaches
  - allow weights across those beta approaches in the UI
- Add competitor / market context tab:
  - clearer peer comparison view
  - analyst recommendations with dates if available
  - recent-quarter news tab with materiality ranking and sentiment
- Add filing-reader tab:
  - raw filing view in browser (HTML/PDF if practical)
  - stretch goal: user-highlighted passages for agent emphasis
- Add report export UI:
  - download full report as HTML and/or generated PDF
- General UI cleanup:
  - styling is still weak
  - layout/navigation needs a cleaner top-level information architecture

### Codex-Owned Backend / Data Backlog

- Add a way to see past reports more easily:
  - likely a dashboard-backed query surface over persisted `pipeline_runs`, `agent_run_log`, `agent_run_artifacts`, and memo outputs
  - should support ticker-level history and reopening prior runs without rerunning agents
- Retest a better CIQ fetching strategy:
  - validate whether refresh + ingest flow should use a different workbook contract or refresh order
  - compare reliability of current Excel/CIQ refresh path versus saved-workbook ingest-only path
- CIQ parser rule:
  - exclude fiscal-year columns if the detected period year is `1900`
  - implemented on 2026-03-14 in `ciq/workbook_parser.py`
  - covered by `tests/test_ciq_parser.py::test_parse_ciq_workbook_excludes_1900_placeholder_period_columns`

### Suggested Handoff To Claude

If resuming the older Claude session, use this context:

- Active UI files:
  - `dashboard/app.py`
  - `src/stage_04_pipeline/dcf_audit.py`
  - `src/stage_04_pipeline/override_workbench.py`
  - `src/stage_04_pipeline/agent_cache.py`
- The dashboard already has:
  - DCF Audit
  - Pipeline
  - Assumption Lab
  - Agent Audit Trail
- Playwright should be used against the live Streamlit app to validate:
  - chart readability
  - clipping/scroll behavior
  - tab navigation
  - assumption control interactions
  - filings/recommendations formatting
