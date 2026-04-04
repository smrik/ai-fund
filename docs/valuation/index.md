# Valuation

This section is the finance-first home for how Alpha Pod should think about valuation.

Use these pages to understand the investment process in analyst order, not code order.
The design docs and handbook remain important, but they should increasingly derive from this methodology layer rather than replace it.

## Suggested Reading Order

1. [Company Analysis](./01_company-analysis.md)
2. [Industry Analysis](./02_industry-analysis.md)
3. [Historical Financial Analysis](./03_historical-financial-analysis.md)
4. [Financial Forecasting](./04_financial-forecasting.md)
5. [DCF Valuation](./05_dcf-valuation.md)
6. [WACC And Capital Structure](./06_wacc-and-capital-structure.md)
7. [Terminal Value](./07_terminal-value.md)
8. [Sensitivity, Scenarios, And Reverse DCF](./08_sensitivity-scenarios-and-reverse-dcf.md)
9. [Comparable Company Analysis](./09_comps.md)
10. [QoE And Normalization](./10_qoe-and-normalization.md)
11. [PM Review Framework](./11_pm-review-framework.md)
12. [Deterministic Vs LLM Boundary](./12_deterministic-vs-llm-boundary.md)

## Mental Model

Alpha Pod valuation should be built in layers:

1. understand the business
2. understand the industry
3. understand the historical financial record
4. translate that history into forecast drivers
5. value the business through DCF and comps
6. stress the result and challenge it before acting

## How These Docs Relate To The Rest Of The Repo

- `docs/valuation/` explains the finance method
- `docs/design-docs/` explains architecture and implementation design
- `docs/handbook/` explains operator workflow and practical usage

Current implementation references that remain important:

- `docs/design-docs/deterministic-valuation-flow-spec.md`
- `docs/design-docs/deterministic-valuation-inputs-and-ciq-retrieval-spec.md`
- `docs/design-docs/deterministic-valuation-benchmark-and-gap-analysis.md`
- `docs/handbook/valuation-dcf-logic.md`

## Ownership Rule

Every page in this section should make three things explicit:

- what can be done deterministically
- what can be augmented by LLMs
- what still requires PM judgment
