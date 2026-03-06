# Valuation Task Breakdown (Granular)

This is a step-by-step task board for running and reviewing one valuation cycle.

## A. Data Prep Tasks

1. Run Stage 1 screener.
2. Confirm `config/universe.csv` exists and is non-empty.
3. Spot-check 5 random tickers for sector and market cap sanity.
4. If using CIQ Stage 2, refresh CIQ export and confirm expected columns.

## B. Batch Execution Tasks

1. Run:
```bash
python -m src.valuation.batch_runner --top 50
```
2. Confirm no fatal errors in terminal output.
3. Confirm `data/valuations/latest.csv` is regenerated.
4. Confirm SQLite `batch_valuations_latest` row count is greater than zero.

## C. Schema Gate Tasks

1. Open `latest.csv` and verify required fields:
- `growth_source`
- `ebit_margin_source`
- `implied_growth_pct`
- `tv_high_flag`

2. Confirm numeric fields parse as numeric in your analysis tool.
3. Confirm there are no duplicate tickers.

## D. First-Pass Ranking Tasks

1. Sort by `upside_base_pct` descending.
2. Exclude rows with missing price or intrinsic values.
3. Mark all rows where `tv_high_flag = True` for extra scrutiny.
4. Mark rows where assumption sources are mostly `sector_default`.

## E. Per-Ticker Validation Tasks

For each candidate in top bucket:

1. Review valuation range:
- `iv_bear`, `iv_base`, `iv_bull`
- downside in bear case vs current price

2. Review expectation risk:
- `implied_growth_pct` vs historical growth context

3. Review discount rate logic:
- `wacc`, `cost_of_equity`, `beta_relevered`, `size_premium`

4. Review model dependence:
- `tv_pct_of_ev`

5. Decide status:
- promote to deep research
- keep watchlist
- reject

## F. QoE Overlay Tasks (Optional)

1. Pull latest 10-K text (or let QoE agent fetch).
2. Run QoE normalization.
3. Confirm structured output contract.
4. Manually approve/reject each adjustment.
5. If approved, log revised EBIT assumption for explicit rerun.

## G. Industry Overlay Tasks (Optional)

1. Run industry benchmark lookup for sector/industry.
2. Compare current growth and margin assumptions to weekly benchmark.
3. Note where assumptions are outside benchmark ranges and why.
4. Apply judgment notes for PM review.

## H. PM Review Tasks

1. Read top ranked set with all assumption and quality flags visible.
2. Identify top 3 value drivers per idea.
3. Define disconfirming evidence for each thesis.
4. Set priority queue for deeper work.

## I. Post-Run Hygiene Tasks

1. Archive or snapshot selected outputs if needed.
2. Record major assumption challenges found this cycle.
3. Capture pipeline issues (missing fields, bad sectors, odd betas) in tech debt tracker.
4. Update docs if any output schema/process changed.

## J. Engineering Follow-Through Tasks

1. Add/adjust tests for any recurring data edge case discovered.
2. Improve fallback logic only with explicit tests.
3. Keep deterministic and judgment layers separated in implementation.
4. Re-run `python -m pytest -q` before merge.
