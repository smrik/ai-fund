# Valuation

> **Current state vs intended state — read before acting on any page here.**
> These pages describe how valuation *should* work. As of 2026-07-24 the implementation does not
> match on the single most important point: a provenance audit of the shipped MSFT model found
> **`llm_reasoned: 0`** — every forward-looking driver was a sector constant or a mechanical
> transform. Per [Vision Decision 13](../strategy/vision.md#the-division-of-labor) those should be
> authored by the judgment layer from evidence.
>
> So when a page here says the judgment layer sets a driver, read that as the target design and
> assume it is **not yet wired** unless you have verified otherwise. Closing that gap is the
> current highest-priority work; see `vision.md` Standing Rule 6 for how (wire the seam, don't
> pick a constant).

This section is the finance-first home for how Alpha Pod should think about valuation.

Use these pages to understand the investment process in analyst order, not code order.
The design docs and handbook remain important, but they should increasingly derive from this methodology layer rather than replace it.

For the current product objective, every full workup includes both DCF and comparable-company
analysis. Other valuation methodologies are intentionally deferred. Reported history remains an
auditable factual baseline, but its analytical classification and any historical recast may be
judgment-layer proposals that flow through PM approval before affecting the forecast.

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
13. [PM Valuation Review Checklist](./13_pm-valuation-review-checklist.md)

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

- what is computed deterministically
- what the judgment layer authors from evidence
- what the PM approves or decides

> **Reading these pages (amended 2026-07-24).** Most of this series predates
> [Vision Decision 13](../strategy/vision.md#the-division-of-labor) and uses the phrasing
> "LLM-augmented" and "advisory". Read those as **"authored by the judgment layer, pending PM
> approval"** — not as "commentary on numbers something else chose". The judgment layer sets the
> forward-looking assumptions (`*_target` drivers, terminal growth, terminal reinvestment) from
> filings and management guidance; the deterministic layer marshals evidence and executes; the
> PM approves. Sector constants and mechanical transforms in those slots are fallbacks that
> signal missing judgment.
>
> The series order is not accidental — company analysis → industry analysis → historical →
> forecasting mirrors the intended agent ordering (Decision 14): upstream context is durable and
> flows into every downstream driver decision.

If you want to review the whole valuation stack and annotate the weak points, use the companion [PM Valuation Review Checklist](./13_pm-valuation-review-checklist.md).
