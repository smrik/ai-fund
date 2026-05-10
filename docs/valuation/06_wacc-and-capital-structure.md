# WACC And Capital Structure

## Purpose

Cost of capital is not just a formula.
It is a statement about:

- business risk
- financing structure
- the opportunity cost of capital
- the realism of the forecast funding path

WACC and capital structure matter because even a strong operating forecast can produce a misleading valuation if the risk and funding assumptions are weak.

## Why This Matters For Valuation

A good cost-of-capital framework should answer:

- what risk the equity holders are taking
- what debt financing realistically costs
- what capital structure is sustainable
- whether that structure should change over the forecast horizon

In practice, this means WACC should be read as part of the valuation story, not only as an input cell.

## Ownership Model

### Deterministic

The deterministic layer should own:

- CAPM mechanics
- beta handling
- size-premium logic where used
- capital-structure weight calculations
- cost-of-debt arithmetic
- scenario perturbations

### LLM-augmented

LLMs can help by:

- summarizing financing plans from filings
- surfacing management discussion of leverage, debt issuance, equity issuance, or buybacks
- highlighting refinancing risk or capital-allocation themes

### Human / PM Judgment

PM judgment is required to decide:

- whether a static capital structure is realistic
- whether current beta and risk assumptions fit the actual business
- whether the funding path should materially affect valuation confidence

### Hard Boundary

LLM commentary may inform the capital-structure narrative, but deterministic math should remain authoritative for numeric outputs.

## Full Workflow

## 1. Start with business risk, not only the formula

Before calculating WACC, define the risk profile of the business.

Questions to answer:

- How cyclical is the company?
- How much operating leverage does it have?
- How much financial leverage does it have?
- How stable are margins and cash flows?
- How exposed is the company to external shocks such as rates, commodities, regulation, or macro demand?

Best practice:

- think about WACC as a risk conclusion, not only a calculation
- pressure-test whether the formula inputs reflect real business risk

## 2. Review current capital structure

Current leverage is part of the valuation story, but it is not always the right long-run anchor.

Questions to answer:

- What is the current debt / equity mix?
- Is the company over- or under-levered relative to peers and business stability?
- Are refinancing needs approaching?
- Is current liquidity strong enough for the forecast path?

Best practice:

- distinguish reported capital structure from sustainable capital structure
- connect balance-sheet review to the forecast, not just the snapshot

Capital-structure weighting policy:

- use current market-value weights when the current structure is credible and likely to persist
- use PM-approved target weights when the current structure is clearly temporary, distressed, or in transition
- document whether leases are treated as debt in both the leverage view and the WACC weights
- document whether excess cash is netted out before assessing leverage and equity risk
- document how convertibles, preferreds, and minority interests are treated in both the bridge and the weighting view

Deterministic outputs:

- debt and equity weights
- leverage summary
- liquidity and debt burden diagnostics

## 3. Estimate cost of equity

Cost of equity should reflect:

- the risk-free rate
- the equity risk premium
- business-specific beta or relevered beta
- size premium where applicable

Questions to answer:

- Is the beta estimate stable and credible?
- Is the peer set relevant for risk estimation?
- Does the size premium make sense for the company and use case?

Best practice:

- keep the components visible
- document the source for each component
- review whether the resulting cost of equity passes a reasonableness test

Beta methodology decision ladder:

1. use bottom-up peer beta as the default institutional method
2. unlever peer betas using a consistent debt and tax convention
3. remove obvious outliers or weak peers before relevering
4. relever the cleaned peer beta to the target or PM-approved capital structure
5. use regression beta only as a secondary sense check, not the default anchor, unless the trading history is unusually clean and relevant

Minimum rules:

- use market-value weights for leverage calculations whenever possible
- state whether leases are treated as debt in the beta and capital-structure view
- state whether excess cash is netted out of leverage
- state whether convertibles, preferreds, or minority interests are included in the bridge and risk view
- record which peer set produced the beta so it can be reviewed alongside comps

Deterministic outputs:

- risk-free rate
- ERP
- beta inputs and outputs
- cost-of-equity build

## 4. Estimate cost of debt

Cost of debt should reflect what financing actually costs the business, not just a generic sector rate.

Questions to answer:

- Is the company investment grade, stressed, or somewhere in between?
- Are current borrowing costs representative?
- Will refinancing conditions change during the forecast horizon?

Best practice:

- use company-specific debt evidence where possible
- review whether tax-adjusted debt cost is reasonable

Cost-of-debt evidence hierarchy:

1. traded debt yield or spread for the company's own debt
2. recent issuance or disclosed borrowing-cost evidence
3. implied interest-rate check from interest expense and average debt balance
4. synthetic rating or interest-coverage-based spread
5. peer-spread fallback only when company evidence is too weak

Minimum rules:

- record which rung of the hierarchy was used
- distinguish current debt cost from target debt cost if refinancing is likely
- use a documented tax rate for the debt shield instead of a hidden shortcut
- surface when the evidence quality is weak enough that WACC confidence should drop

Deterministic outputs:

- pre-tax cost of debt
- after-tax cost of debt
- debt burden diagnostics

LLM augmentation:

- summarize management commentary on refinancing, issuance, and debt strategy

## 5. Decide whether capital structure should evolve

One of the most important forward-looking questions is whether the capital structure should remain static.

Questions to answer:

- If the company grows, how is that growth funded?
- If the company delevers, should the weights and risk profile change?
- If the company is using buybacks or issuance, should the equity story change?

Best practice:

- do not assume today's structure is automatically the future structure
- make any static-structure assumption explicit

Deterministic outputs:

- current-structure WACC
- scenario perturbations

LLM augmentation:

- surface management commentary on funding plans

PM judgment:

- decide whether the valuation narrative needs a more dynamic funding path
- decide whether current or target weights better represent the economics of the forecast period

## 6. Validate the discount-rate conclusion

The final WACC should be treated as a conclusion to audit, not a number to accept automatically.

Validation questions:

- Is the WACC consistent with the business risk profile?
- Is it consistent with the forecast cash flow?
- Is the capital structure sustainable?
- Does the implied discount rate feel too low or too high relative to peers and business quality?

Methodology policy controls:

| Component | Default policy | Required flag |
| --- | --- | --- |
| Risk-free rate | match the cash-flow currency and approximate duration; use US 10-year only as the practical USD long-duration fallback | flag currency mismatch or non-USD exposure without matching local rate logic |
| Equity risk premium | prefer current implied ERP when available; document any fixed or historical fallback | flag stale ERP or hard-coded ERP without source date |
| Country risk premium | add explicit country-risk exposure for material non-US operating exposure, not only foreign listing domicile | flag missing country-risk logic for multinational or emerging-market exposure |
| Beta | default to bottom-up peer beta with transparent unlever / relever assumptions | flag thin peer set, unstable regression beta, or unreconciled peer disagreement |
| Size premium | use only if the methodology stance, data source, and refresh cadence are documented | flag because the empirical size-premium evidence is contested |
| Cost of debt | prefer traded debt / recent issuance / disclosed borrowing cost before synthetic-rating fallback | flag when only generic peer spread is available |
| Synthetic rating spread | record the interest-coverage mapping, spread curve source, and curve date | flag missing curve date or unsupported spread interpolation |
| Method disagreement | compare peer bottom-up, industry proxy, and self-Hamada results | flag when approved methods differ beyond the configured tolerance |

Accepted range rule:

- base WACC should sit inside the approved method-set range unless PM-approved
- the WACC register entry should preserve the full method set, not only the selected value
- a PM override may select a value outside the deterministic range, but the override must record the reason and valuation impact

WACC default parameters:

| Parameter | Default |
| --- | --- |
| ERP source | Damodaran monthly implied ERP if dated within 60 days |
| ERP fallback | 4.6% mature-market ERP, source-stamped and flagged as fallback |
| Country-risk materiality | add country-risk review when non-US operating exposure is greater than 15% of revenue or operating income; use revenue when operating income by geography is unavailable |
| Method disagreement flag | high-low spread greater than 100 bps across approved WACC methods = `review_required`; greater than 200 bps = `critical` |
| Synthetic-rating source | Damodaran interest-coverage-to-rating table, source date recorded |
| Risk-free fallback | US 10-year Treasury only for USD long-duration cash flows when duration-matched curve is unavailable |

Damodaran synthetic-rating table for large non-financial firms, January 2026:

| Interest coverage greater than | Interest coverage less than or equal to | Synthetic rating | Default spread |
| ---: | ---: | --- | ---: |
| -100000 | 0.199999 | D2/D | 19.00% |
| 0.2 | 0.649999 | C2/C | 16.00% |
| 0.65 | 0.799999 | Ca2/CC | 12.61% |
| 0.8 | 1.249999 | Caa/CCC | 8.85% |
| 1.25 | 1.499999 | B3/B- | 5.09% |
| 1.5 | 1.749999 | B2/B | 3.21% |
| 1.75 | 1.999999 | B1/B+ | 2.75% |
| 2 | 2.249999 | Ba2/BB | 1.84% |
| 2.25 | 2.499999 | Ba1/BB+ | 1.38% |
| 2.5 | 2.999999 | Baa2/BBB | 1.11% |
| 3 | 4.249999 | A3/A- | 0.89% |
| 4.25 | 5.499999 | A2/A | 0.78% |
| 5.5 | 6.499999 | A1/A+ | 0.70% |
| 6.5 | 8.499999 | Aa2/AA | 0.55% |
| 8.5 | 100000 | Aaa/AAA | 0.40% |

Primary source: https://pages.stern.nyu.edu/~adamodar/New_Home_Page/datafile/ratings.html

## Recommended Artifact Set

| Artifact | Purpose | Owner |
| --- | --- | --- |
| WACC audit table | shows full build-up of discount-rate components | deterministic |
| Beta and peer-risk table | explains risk inputs and peer anchoring | deterministic |
| Capital-structure review block | shows current and discussed target structure | deterministic + PM |
| Cost-of-debt evidence ladder | records which evidence tier was used and why | deterministic |
| Funding-path note | explains how the company finances the forecast path | mixed |
| Discount-rate validation note | explains whether WACC feels credible enough to trust | PM-owned |

## What Should Feed Directly Into Valuation

The following belong directly in the deterministic layer:

- CAPM and debt-cost mechanics
- weight calculations
- WACC result
- discount-rate scenarios

The following should stay advisory until approved:

- management-intent narratives
- dynamic funding-path interpretations
- suggested changes to structure based on qualitative reasoning alone

## Current Implementation Notes

Alpha Pod's WACC logic is directionally strong, but this area still needs more explicit policy than the current docs provide.
The biggest remaining gap is not only dynamic capital structure. It is the lack of a first-class methodology ladder for beta, debt cost, and bridge-item treatment.

Main gaps:

- beta method precedence is not yet explicit enough
- lease, cash, convertible, and target-structure treatment should be documented more tightly
- cost-of-debt evidence quality and fallback order are not yet first-class artifacts
- limited formal dynamic capital-structure logic
- limited explicit funding-path artifact in the valuation workflow
- limited confidence scoring for discount-rate quality

## Practical Review Questions For The PM

1. Does the WACC fit the actual business risk?
2. Is the current capital structure sustainable?
3. Would growth or de-risking likely change the capital structure materially?
4. Are we valuing the company with a discount rate that matches the cash flow we are modeling?
