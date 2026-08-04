# Handoff — judgment pipeline, 2026-08-04

Branch `codex/focused-accounting-evidence-repair`, 35 commits ahead of `main`, in sync with origin,
open as PR #83. Working tree clean at `ada587a`.

## The one-line state

Both reconciliation layers are green and the judgment layer produces real, critic-reviewed
proposals — but **no valuation has completed**. MSFT prices at −$19.47, which the new degenerate
guardrail now correctly refuses to publish.

## What is verified working

Each of these was confirmed by running it against the live database, not by reading code.

| | evidence |
|---|---|
| Statement reconciliation | `decision_grade`, 168/168 checks pass |
| Operating reconciliation | `reconciled`, 5/5 tie-outs at difference exactly 0 |
| Observed drivers tie to filings | capex 34.94%, D&A 10.34%, DSO 88.96, DIO 4.79, DPO 145.54 |
| Driver families execute | 3 of 4 accepted by their critic; concurrent execution confirmed |
| Judgment produces real analysis | pack 219 proposes `ebit_margin_target` 0.38/0.44/0.47 with 7 evidence anchors |
| Critic is adversarial | rejected a 22.0x exit multiple justified as "NVDA-like", then rejected the revision too |
| Degenerate output fails closed | `degenerate_scenarios_identical_flag` fires on the −19.47 case |
| Projection cost | 880k → 87k tokens per pass (90% reduction), 60–90 min → ~26 min |

## What is NOT working

**The approved value does not reach the DCF.** This is the live blocker and `task22` is dispatched
against it.

Approving pack 219 on a database copy produced:

    /deterministic/summary/summary/base_drivers    ebit_margin_target = 0.3284    <- DCF used this
    /deterministic/summary/summary/source_lineage  ebit_margin_target = "default"
    /ticker_dossier/.../valuation_snapshot         ebit_margin_target = "approved_driver_family_pack:..."

The bridge decorates the dossier snapshot; the calculation still reads the sector default. Forecast
bridge confirms it — margin fades 45.68 → 38.55, tracking to 32.8 not 44.

## THE CAVEAT THAT MATTERS MOST

**Three separate defects today had the identical shape: the write side worked, a check passed, and
the consumer never saw the value.**

1. `treatment_decisions` had a writer that only tests called — 0 rows ever, while two production
   paths read it
2. Reconciled start drivers passed all five tie-outs and never reached the DCF; the tie-outs were
   validating values the model didn't use
3. The approved pack records provenance on one surface while the calculation uses the default

Every one passed its own tests. **Assume this is the default failure mode in this codebase.**

Practical rule: when verifying that X reaches Y, assert on **the value Y actually computes with**,
never on a lineage string, a status field, or a passing check. A green tie-out proved nothing in
case 2 because it validated a substituted value that was then discarded.

## Other caveats

- **Agent self-reports run optimistic.** One claimed "20 tests added" (4). One reported
  `ltm_status=unavailable` from a stale DB row after its own fix made it `constructed`. Count
  added tests off the diff; re-run suites yourself.
- **20 test failures / 5 errors are environmental.** A permission-locked `.tmp-tests` directory in
  the repo root. Needs an elevated delete. Unrelated to any code here — baseline is
  **1371 passed**.
- **`revenue` family queued no pack** despite completing its full cycle; `terminal_capital_comps`
  blocked when its critic rejected the revision. Only `profitability_tax` produced a pack, so
  `capex_pct_target` and `exit_multiple` remain non-judgment-sourced.
- **Capex is held at 34.94% forever.** That is a reconciled observation of a peak AI-buildout year
  being treated as the permanent rate. It is half of why the DCF collapses, and it is a forecast
  judgment nobody has made.
- **Two agents in one working tree is dangerous.** A concurrent run polluted a suite result, and a
  second agent ran `git checkout <file>` three times on a shared tree — it missed live work by luck.
- **`.tmp/alpha_pod_replay.db` (387 MB)** was accidentally committed and rejected by the
  pre-receive hook. `.tmp/` is now gitignored. Watch for similar.

## Next actions, in order

1. **Verify `task22`** — assert `summary/base_drivers` shows 0.44, *not* that the lineage string
   changed.
2. **Re-run the valuation.** At a 0.44 terminal margin, after-tax EBIT ≈ 35% of revenue against
   34.94% capex and 10.34% D&A, so FCFF should go from ~1.6% to ~10% of revenue. If it is still
   degenerate, the guardrail should still fire — that is correct behaviour, not a regression.
3. **Rate the valuation.** Earlier ratings: 3/10 (unsourced margin), then 2/10 (unusable output,
   published silently). Anything above that requires the margin to be judgment-sourced *and* the
   result to be arithmetically sound.
4. **Re-run the driver families** so `revenue` and `terminal_capital_comps` produce packs. Now
   ~350k tokens and ~26 minutes rather than 3.5M and 90.
5. **Fix `_ltm_status` order-dependence** — the corpus hash is order-dependent, so identical
   evidence retrieved in a different order looks different. The register is already read by two
   production paths, so this is live, not future.

## Open PM decisions

- **Capex path.** Is 34.94% the permanent rate, or does it fade? Currently held flat, which
  guarantees near-zero terminal FCFF.
- **Pack 219 on the live database.** Approved on a copy only. Your live `treatment_decisions` is
  still 0 rows and queue item 219 is still `pending`.
- **128 pending queue items**, most of them superseded reconciliation findings accumulating one
  batch per run. Worth a cleanup pass.

## Commands that matter

    # inspect what would be sent to the LLM — no provider calls, run this BEFORE any dispatch
    python -m scripts.manual.inspect_family_projections MSFT

    # full suite (baseline 1371 passed / 20 failed / 5 errors)
    python -m pytest tests -q -p no:cacheprovider

    # driver families — ~350k tokens, ~26 min
    python -m src.stage_04_pipeline.valuation_workup_cli MSFT \
      --analysis-as-of 2026-08-04 --execution-run-id <unique> \
      --provider openrouter \
      --primary-model deepseek/deepseek-v4-flash-0731 \
      --critic-model deepseek/deepseek-v4-flash-0731 \
      --transport-timeout-seconds 600 --batch-timeout-seconds 2400

    # offline valuation
    python -m scripts.manual.run_ticker_valuation_flow --ticker MSFT --skip-agent-runs

Interpreter is `C:/Users/patri/miniconda3/envs/ai-fund/python.exe`. Bare `python` is an unrelated
broken venv and will fail on `import edgar`.

## Timeouts — do not raise them on a timeout

At attempt 4 a `scheduler_deadline_exceeded` was read as "needs more room" and the batch ceiling
was raised from 900s to 5400s. The real cause was a hung provider call, and the larger ceiling gave
it 90 minutes to hang in. Tighter timeouts surface hangs; looser ones hide them.
