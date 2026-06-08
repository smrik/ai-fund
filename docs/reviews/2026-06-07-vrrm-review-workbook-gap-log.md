# VRRM Review Workbook Gap Log

**Date:** 2026-06-07
**Reviewed artifact:** `data/exports/generated/ticker/VRRM/20260606-231709-xlsx-3c4f1d74/VRRM_review.xlsx`
**Patched artifact generated for verification:** `data/exports/generated/ticker/VRRM/20260607-112003-xlsx-reviewfix/VRRM_review.xlsx`

## Executive Read

The pre-fix workbook was not safe for PM review because several visible tabs still showed stale IBM template values while the JSON sidecar and comps tabs were VRRM-specific. This made the workbook internally contradictory: a PM could read the `Comps` appendix as VRRM but the `Cover`, `Output`, `Assumptions`, `Equity_Bridge`, and `Sensitivity` tabs as IBM.

The refreshed VRRM financial conclusion is also not yet clean enough to trust as an actionable long idea without review. The model shows extreme upside, but the top drivers are fragile:

- Base IV is far above price, with base upside around 1280%.
- Terminal value is 77.9% of EV, triggering `tv_high_flag`.
- Bull IV is more than 4x base IV in the run log, which suggests high convexity to long-term assumptions.
- DCF and comps disagree materially.
- Comps are from `public_market_yfinance_fallback`, not CIQ detail.
- Several assumption sources include `default`, especially exit multiple and working-capital fields.

## What Was Missing Or Weak

| Area | Finding | Why It Matters | Improvement |
| --- | --- | --- | --- |
| Ticker identity | Visible workbook tabs retained IBM labels and values | Highest-risk failure: stale template values looked like real analysis | Export staging now rewrites human-facing tabs from the JSON payload |
| Review triage | No one-sheet list of active financial/data quality concerns | PM had to infer issues from scattered tabs/logs | Added `Review Checks` with deterministic findings |
| Data lineage | CIQ/fallback source quality was not visible enough | VRRM relied on public-market fallback comps | Added source/fallback/default-backed fields to `QoE` and `Review Checks` |
| DCF auditability | Scenario tabs did not clearly separate payload-backed values from template formulas | Easy to overtrust stale or workbook-native formulas | Scenario DCF tabs now show payload scenario summary and forecast bridge |
| Assumption grounding | Source lineage was not obvious next to each driver | PM could not quickly see which assumptions were default-backed | `Assumptions` now writes field, value, source, and PM-notes columns |
| Comps diagnostics | Comps were specific and useful, but source quality needed stronger warning | Public fallback comps should be treated differently from CIQ comps | Fallback comps now appear in `Review Checks` |

## Template / Export Contract Change

The workbook template is still copied from `templates/ticker_review.xlsx`, but export staging now rewrites these sheets from the export payload:

- `Cover`
- `Output`
- `Assumptions`
- `DCF_Base`
- `DCF_Bear`
- `DCF_Bull`
- `Equity_Bridge`
- `Sensitivity`
- `QoE`
- `Review Checks`
- `Comps`
- `Comps Diagnostics`

This turns the workbook into an auditable review artifact first. Workbook-native override formulas can be reintroduced later, but exported copies must keep passing the no-stale-template-value regression test.

## Default Assumption Hardening

A follow-up hardening pass added a deterministic `default_resolution` report to valuation input assembly and export payloads. The report classifies material default-backed assumptions such as `exit_multiple`, DSO/DIO/DPO, and pension/balance-sheet claims into audit-friendly rows with severity, source class, preferred replacement sources, and PM-review flags.

The input assembler now also uses normalized comps-detail medians as an additional exit-multiple source before falling back to a sector default. Public peer fallback can now be opted in through `config/valuation_overrides.yaml`; for opted-in tickers, no-CIQ public peer medians are built early enough to inform the DCF exit multiple rather than only appearing as a post-hoc comps appendix.

## Remaining Finance Hardening

- Replace fallback comps with CIQ comps once the CIQ Excel refresh/ingest path is available for the ticker.
- Add explicit bridge between DCF base IV and comps base IV, including which fields explain the gap.
- Add a PM override section that records chosen overrides and exports them back into the deterministic assumption contract.
- Add a revenue-quality section that shows fiscal-year history, CIQ/public source, and whether the latest filing confirms the run-rate.
- Add filing coverage summary to the workbook: filing count, latest filing date, accepted references, and missing references.
- Add working-capital sanity checks for DSO/DIO/DPO if those fields remain default-backed.

## Verification

- Focused tests passed:
  `C:\Users\patri\miniconda3\envs\ai-fund\python.exe -m pytest tests/test_export_service.py tests/test_ticker_review_template.py -q`
- The patched VRRM workbook was inspected with `openpyxl`.
- Visible review sheets present: `Cover`, `Output`, `Assumptions`, `DCF_Base`, `DCF_Bear`, `DCF_Bull`, `Equity_Bridge`, `Sensitivity`, `QoE`, `Review Checks`, `Comps`, `Comps Diagnostics`.
- Stale IBM value search across those visible tabs returned no hits.
