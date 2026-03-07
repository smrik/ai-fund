# Finance Deep Dive

This guide is for analysts and PMs using Alpha Pod outputs for idea triage and conviction building.

## Core Valuation Philosophy

Alpha Pod treats intrinsic value as a deterministic estimate that must be explainable by explicit assumptions.

What this means in practice:
- If a stock ranks high, you should be able to point to exactly which growth, margin, WACC, and terminal assumptions produced that result.
- If you disagree with the result, you should challenge assumptions, not narrative.

## How To Read `latest.csv`

Critical columns to review first:
- `ticker`, `price`, `iv_bear`, `iv_base`, `iv_bull`, `upside_base_pct`
- `wacc`, `cost_of_equity`, `beta_relevered`, `size_premium`, `equity_weight`
- `growth_near`, `growth_source`, `ebit_margin_used`, `ebit_margin_source`
- `capex_pct_used`, `da_pct_used`, `tax_rate_used`
- `tv_pct_of_ev`, `tv_high_flag`, `implied_growth_pct`

Interpretation order:
1. Is upside attractive on base case?
2. Is bear case downside tolerable?
3. Is the valuation dominated by terminal value?
4. Does implied growth look realistic versus business quality?
5. Do assumption sources rely on real history or defaults?

## Assumption Integrity Framework

The model gives stronger confidence when assumptions come from company history rather than defaults.

High-integrity row characteristics:
- `growth_source = 3yr_cagr`
- `ebit_margin_source = 3yr_avg`
- `capex_source = 3yr_avg`
- `da_source = 3yr_avg`
- `tax_source = 3yr_avg`

Lower-integrity row characteristics:
- Heavy reliance on `sector_default`
- Missing/unstable historical fundamentals
- Very high `tv_pct_of_ev`

## Terminal Value Risk

`tv_pct_of_ev` answers a key question: how much of enterprise value comes from terminal assumptions.

Rule of thumb:
- < 60%: usually healthy for mature, cash-generative businesses
- 60% to 75%: acceptable but requires careful review
- > 75% (`tv_high_flag = True`): thesis is mostly long-duration and assumption-sensitive

High terminal value does not mean wrong, but it means the thesis is fragile to WACC and exit multiple changes.

## Reverse DCF: Market-Implied Expectations

`implied_growth_pct` solves for growth needed to justify current price under the base structure.

Use it to classify setup quality:
- Implied growth far above historical reality: market optimism is high; downside on misses can be severe.
- Implied growth near historical trend: valuation is closer to fair.
- Implied growth far below plausible trajectory: potential mispricing if fundamentals persist.

## WACC Interpretation For Finance Users

WACC is not a constant across names.

In this repository, WACC reflects:
- CAPM cost of equity
- Size premium by market cap bucket
- After-tax cost of debt
- Capital structure weights

Review checkpoints:
- `beta_relevered` should make economic sense for the business risk profile.
- `size_premium` should be directionally consistent with market cap.
- Debt weight and equity weight should align with observed balance sheet profile.

## Margin And Growth Reality Checks

Use these realism checks before acting on a high-upside name:

- Growth realism:
  - Is `growth_near` coherent with recent revenue CAGR and industry context?
  - Is high growth paired with reinvestment intensity that makes sense?

- Margin realism:
  - Is `ebit_margin_used` supported by history, or is it default-driven?
  - For cyclicals, avoid extrapolating peak margins as steady state.

- Cash conversion realism:
  - Capex and D&A percentages should not imply implausible free cash flow profiles.

## Quality Of Earnings Overlay (QoE)

`QoEAgent` can adjust reported EBIT for one-time items found in 10-K text.

Output contract:
- `normalized_ebit`
- `reported_ebit`
- `adjustments[]` with signed direction and rationale
- confidence and data source fields

How to use it:
- Treat QoE output as an analyst adjustment layer.
- Keep an audit trail of adjustments before modifying deterministic assumptions.

## Weekly Industry Benchmarks Overlay

`IndustryAgent` stores weekly sector/industry benchmark records in `industry_benchmarks`.

Typical use:
- Cross-check if chosen growth and margin assumptions are in or out of current sector ranges.
- Force refresh only when new structural information changes the view.

## Analyst Review Template (Per Ticker)

1. Thesis in one line: why this can beat/miss expectations
2. Base valuation reasonability: upside vs downside profile
3. Assumption challenge:
- Growth anchor
- Margin anchor
- WACC anchor
- Terminal dependence
4. Expectation mismatch check (reverse DCF)
5. Decision state:
- Promote to deep research
- Keep on watchlist
- Reject for now

## Common Failure Modes In Interpretation

- Treating a high base-case upside as a buy signal without assumption challenge
- Ignoring terminal value dominance
- Ignoring growth-source quality
- Confusing statistical cheapness with fundamental mispricing

## PM Decision Protocol

Use deterministic output to rank and triage.
Use judgment layer to frame scenario quality.
Keep final position sizing and conviction strictly human.

