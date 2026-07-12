# MSFT professional-model sprint handoff ? 2026-07-12

Branch: `codex/professional-model-msft-actual`

## Executive status

This sprint materially expanded the MSFT source, model, workbook, review API, and React workbench, but it did **not** complete a decision-ready run-4 professional model. The correct terminal state is `BLOCKED`, not `FULL`.

The fresh run-4 source layer is reproducible. Finance, API, and frontend contain substantial fail-closed infrastructure, but their final cross-contract migration and acceptance tests remain incomplete.

## Delivered

### Source integrity

- Original workbook SHA-256: `413c51b4e976c6c4c61e7c616c6ff51f839a77ad8443bd0be8883b9d6c630411`.
- Derived repaired workbook SHA-256: `961dbeef146a941cd493394d70838156b16716d5337e1d6d5d3edec538404237`.
- Twenty-four formula repairs in a derived copy; the original stayed byte-identical and cached values were preserved.
- Run `4`, parser `ibm_standard_v4`, 8,601 persisted facts, zero formula/cached errors.
- Preflight hash: `a9d43e37e9d73a21b36c15843fcbc95d84506d40d76eabdbbee1ab3908543a02`.
- Canonical fact digest: `cf6c7c6fa2802069261c76557afdc65dcee8aed5f5562110f67181a0575febc6`.
- Non-PM source handoff SHA-256: `5ba44c7b4187bebd5da9439cf270f0a9046115d6f4114773a40394a0b269c003`.
- Segment revenue/operating income evidence reconciles; undisclosed segment assets/KPIs remain unavailable.

Generated artifacts are machine-local under `output/source_repairs/MSFT/` and `output/professional_models/MSFT/961dbeef146a/`.

### Model, workbook, API, and UI

- Added canonical model contracts, line-item registry, historical normalization, integrated forecast/scenario engine, valuation bundle, workbook adapter/renderer, and isolated recalculation helper.
- Hardened tax, PP&E/intangibles, debt/interest, shares/EPS, FCFF, DCF timing, WACC parity, consensus, QoE, PM-review, and positive-list checks.
- Audited all 26 workbook sheets and reconciled cross-sheet findings.
- Added immutable review events, bounded sheet inspection, review/rebuild/signoff contracts, artifact identity and semantic QA controls.
- Added a React workbench for readiness, decisions, checks, blockers, all 26 sheets, approvals, rebuild, signoff, and download.
- Hardened the focused accounting judgment agent and deterministic validation/repair layer.

## Verification from session logs

| Workstream | Last reliable result | Qualification |
|---|---:|---|
| Source | 60 + 37 + 10 + 28 tests passed; compileall passed | Run-4 handoff complete; unit/timestamp gaps remain explicit |
| Finance | Adapter: 15 passed | Latest renderer not rerun; no run-4 workbook produced |
| API | Compilation passed; 44 passed / 7 failed | Run-4/QA-v2 migration incomplete |
| Frontend | Latest bounded run: CSS 1 passed; panel 10 passed / 10 failed | Fixture/API contract migration incomplete |
| Accounting focus | 36 passed | Independent Codex score 60/100; four P0 paths remain |

Per the user's terminal instruction, further testing was skipped.

## Artifact status

The last delivered workbook is still run 3: `output/professional_models/MSFT/3/MSFT_professional_model_v2.xlsx`, SHA-256 `ed6ba93d7c1d24eb690a9ca0de1b05913ff07831141cab5b9f361b825b625918`. It has 26 sheets and 133 blockers and is not decision-ready.

No run-4 valuation packet, run-4 workbook, native-recalculated candidate, authoritative QA sidecar, or final signoff was produced.

## P0 continuation order

1. Create a typed run-4 valuation packet bound to `961d?`, with separate financial cutoff, market as-of, valuation date, bridge basis, FY26 YTD/Q4 stub, scenario governance, DCF/WACC/g, and current FDSO evidence.
2. Make schedules formula-first and controlling; replace the hardcoded `Scenarios` output dump with a governed driver matrix.
3. Complete March-2026 actual plus Q4-stub bridges for every material flow and ending balance.
4. Freeze canonical definitions for tax units, debt/leases, receivables, D&A/amortization, net claims, FDSO, and price/as-of.
5. Unify renderer, manifest, recalculation, QA, API, and frontend on one versioned positive-list check schema.
6. Finish the seven failing API migrations, hash-bound download, and run-4 lifecycle.
7. Finish frontend fixtures; rerun tests/build/browser and prove summary/review/sheet/download identity atomicity.
8. Close accounting-agent P0s: field-specific evidence binding, envelope-repair integrity, driver-specific forward support, and atomic-item double-count protection.
9. Build from run 4, recalculate in isolated native Excel, verify caches/checks, bind review evidence, and repeat all 26 sheet audits against the final SHA.

## Audit findings to preserve

- Run 3 is not formula-first; schedules/statements largely mirror frozen scenario outputs.
- Sensitivity corners previously understated equity value by about `$30.13/share`; test every cell without a center override.
- Tax, debt/lease, receivables, and D&A definitions change across the actual/forecast boundary.
- DCF timing conflates the March cutoff and valuation date and lacks a complete FY26 bridge.
- Visible comps did not control displayed implied value; SOTP and consensus positive paths remain incomplete.
- Do not repeat the stale interest finding: run 3 has FY25 `-2,425` and LTM `-2,859`.

## Resume commands

```powershell
git switch codex/professional-model-msft-actual
python -m pytest -q tests/test_professional_model_adapter.py tests/test_professional_model_workbook.py
python -m pytest -q tests/test_professional_model_review.py tests/test_professional_model_review_contract.py tests/test_professional_model_review_workflow_contract.py tests/test_api_contracts.py
cd frontend
npm test -- --run src/test/professionalModelResponsiveCss.test.ts src/test/professionalModel.test.tsx
npm run build
```

Keep the repository private: `MSFT_Standard.xlsx` may contain licensed Capital IQ data. Generated databases, caches, repaired workbooks, QA renders, and screenshots remain machine-local/ignored.
