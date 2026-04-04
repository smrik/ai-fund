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

## 6. Validate the discount-rate conclusion

The final WACC should be treated as a conclusion to audit, not a number to accept automatically.

Validation questions:

- Is the WACC consistent with the business risk profile?
- Is it consistent with the forecast cash flow?
- Is the capital structure sustainable?
- Does the implied discount rate feel too low or too high relative to peers and business quality?

## Recommended Artifact Set

| Artifact | Purpose | Owner |
| --- | --- | --- |
| WACC audit table | shows full build-up of discount-rate components | deterministic |
| Beta and peer-risk table | explains risk inputs and peer anchoring | deterministic |
| Capital-structure review block | shows current and discussed target structure | deterministic + PM |
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

Alpha Pod's WACC logic is already relatively strong.
The main future improvement is tying capital structure more explicitly to the forecast path instead of treating it as mostly static.

Main gaps:

- limited formal dynamic capital-structure logic
- limited explicit funding-path artifact in the valuation workflow
- limited confidence scoring for discount-rate quality

## Practical Review Questions For The PM

1. Does the WACC fit the actual business risk?
2. Is the current capital structure sustainable?
3. Would growth or de-risking likely change the capital structure materially?
4. Are we valuing the company with a discount rate that matches the cash flow we are modeling?
