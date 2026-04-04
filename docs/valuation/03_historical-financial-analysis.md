# Historical Financial Analysis

## Purpose

Historical financial analysis builds the factual base for forecasting.
Its job is not only to summarize the past, but to answer a harder question: **which parts of the past are representative enough to inform the future?**

A strong historical-analysis layer should produce:

- clean multi-year statements
- auditable derived metrics
- rolling trend views
- common-size statements
- ratio packs
- peer-relative context
- a clear view on what looks structural versus distorted

Without that, forecasting becomes a loose extrapolation exercise rather than an evidence-based model.

## Why This Matters For Valuation

Best-practice valuation does not begin with a single TTM snapshot or one 3-year CAGR.
Serious modeling work starts by understanding:

- the shape and quality of the historical period
- which accounting items need normal interpretation
- how margins, capital intensity, and working capital behave through time
- whether recent results are representative, cyclical, temporarily distorted, or acquisition-driven

In practice, this historical layer is what should determine:

- which growth and margin anchors deserve weight
- which years should be treated as normalized versus noisy
- which line items need tighter sourcing from CIQ
- which assumptions can be deterministic versus which need judgment

## Research Anchors

This page is aligned with the following general modeling and valuation principles:

- CFA Institute, *Introduction to Financial Statement Modeling*
- CFA Institute, *Company Analysis: Past and Present*
- CFA Institute, *Financial Statement Analysis*
- McKinsey, *How are companies valued?*
- McKinsey, *Balancing ROIC and growth to build value*

The shared methodological thread is straightforward:

- historical analysis should be multi-period
- ratios should be interpreted in business context
- growth, profitability, reinvestment, and capital structure should be evaluated together
- any model should document assumptions, sources, and validation checks

## Where Historical Analysis Sits In Alpha Pod

Historical analysis should sit between:

- statement ingestion and data mapping
- company and industry analysis
- forecast assumption design
- DCF, comps, and PM review

The intended flow is:

1. assemble clean statements
2. produce historical metrics and common-size views
3. identify inflections and representative periods
4. map major historical drivers
5. hand forward only the validated, explainable pieces into forecasting

## Ownership Model

### Deterministic

The following should be deterministic whenever the underlying data is available:

- statement assembly
- sign normalization
- line-item mapping
- rolling windows
- common-size statements
- ratio calculation
- peer-relative numeric comparison
- data-quality and coverage flags

### LLM-augmented

LLMs are useful for:

- explaining why a ratio changed
- identifying likely causes of an inflection from filings
- highlighting accounting or disclosure context that helps interpret a metric
- summarizing management discussion around margin, working capital, and capital allocation

### Human / PM Judgment

PM judgment is still required for:

- deciding which years are representative
- deciding whether an inflection is cyclical, structural, or distorted
- deciding whether a normalization candidate should actually affect the forecast
- deciding whether the historical period supports high-confidence underwriting

### Hard Boundary

The deterministic layer should compute the history.
LLMs may interpret it.
The PM decides what becomes forecast-relevant.

LLM outputs should not silently overwrite historical metrics or push adjusted values into valuation inputs without an explicit review path.

## Full Workflow

## 1. Assemble clean multi-year statements

The starting point is a cleaned historical income statement, balance sheet, and cash flow statement across multiple periods.

Best practice:

- use multiple annual periods, not just TTM
- preserve statement lineage to source systems
- normalize sign conventions
- keep operating items distinct from financing and non-operating items where possible
- flag missing periods, inconsistent labels, and obvious mapping anomalies

Questions to answer:

- Do we have enough history to observe cycles, inflections, and mean reversion?
- Are line items consistently defined across time?
- Are there restatements, acquisitions, or reporting changes that break comparability?

Deterministic outputs:

- cleaned multi-year statements
- standardized line-item mappings
- coverage table by period and metric
- source-lineage and missing-data flags

LLM augmentation:

- highlight disclosure changes that affect comparability
- identify when business restructuring or acquisitions likely changed statement shape

PM judgment:

- decide whether comparability breaks are severe enough to reduce forecast confidence

## 2. Reclassify the statements for valuation use

Raw reported statements are not always organized the way a valuation model needs them.
Historical analysis should explicitly separate:

- operating items
- financing items
- non-operating items
- bridge items that matter for enterprise-to-equity conversion

Best practice:

- keep the historical record faithful to reporting
- add a valuation-oriented reclassification layer rather than losing the original presentation
- isolate items that affect normalized EBIT, invested capital, and the EV bridge

Deterministic outputs:

- valuation-oriented statement views
- operating versus financing separation
- bridge-item table where data exists

LLM augmentation:

- identify possible classification edge cases from footnotes or management explanation

PM judgment:

- decide whether the reported presentation obscures real economics

## 3. Build rolling trend views

Do not rely on a single 3-year CAGR.
Use rolling windows to understand stability, acceleration, and turning points.

Example windows:

- `t-5 to t-2`
- `t-4 to t-1`
- `t-3 to t`

Core rolling views:

- revenue growth
- EBIT / EBITDA growth
- gross, EBIT, EBITDA, and FCF margins
- capex intensity
- D&A intensity
- working-capital intensity
- share-count change
- leverage and liquidity trends

Best practice:

- use windows, not one anchor period
- distinguish central tendency from volatility
- surface the spread between strong and weak years

Deterministic outputs:

- rolling CAGR tables
- volatility and dispersion summaries
- inflection markers for major changes

LLM augmentation:

- explain likely causes of specific inflections from textual evidence

PM judgment:

- decide which windows reflect steady-state behavior versus unusual circumstances

## 4. Create common-size statements

Historical analysis should always include common-size views because they make structural changes easier to see.

Recommended views:

- income statement as percentage of revenue
- balance sheet as percentage of revenue or assets where appropriate
- cash flow statement as percentage of revenue

Why it matters:

- supports internal comparison over time
- improves peer comparison
- exposes cost-structure and capital-intensity shifts that headline growth rates can hide

Deterministic outputs:

- common-size income statement
- common-size balance sheet
- common-size cash flow statement

LLM augmentation:

- summarize which line items moved materially and why

PM judgment:

- decide whether common-size movements reflect business-model evolution or short-term noise

## 5. Build a historical ratio pack

The ratio pack should cover growth, profitability, efficiency, reinvestment, leverage, and per-share behavior together.

Core categories:

- growth rates
- gross / EBIT / EBITDA / FCF margins
- returns on capital and equity where appropriate
- capex / sales
- D&A / sales
- cash conversion
- DSO / DIO / DPO
- leverage and liquidity
- dilution and per-share metrics

Best practice:

- organize ratios by economic purpose, not by accounting line order
- use the ratio pack to explain the business, not just to populate a dashboard
- flag when a ratio is weakly sourced or not comparable

Deterministic outputs:

- historical ratio pack with coverage flags
- period-over-period changes
- peer-relative percentile or rank views where peer data exists

LLM augmentation:

- connect ratio changes to disclosed operating events or accounting changes

PM judgment:

- decide which ratios actually matter for this business model

## 6. Study cash conversion and working-capital behavior

Cash conversion deserves its own review because many apparently strong P&L stories break on working capital.

Questions to answer:

- Does growth consume or release cash?
- Are receivables, inventory, or payables driving cash-flow volatility?
- Does working-capital behavior change through cycles?
- Is the company structurally advantaged or disadvantaged in cash conversion?

Best practice:

- study DSO, DIO, DPO together
- look at both levels and changes
- connect working-capital metrics to the operating model and industry structure

Deterministic outputs:

- DSO / DIO / DPO history
- working-capital as percentage of revenue
- cash-conversion summaries

LLM augmentation:

- explain unusual working-capital movements from filings

PM judgment:

- decide whether a working-capital change is temporary, operational, or structural

## 7. Study capital intensity and balance-sheet evolution

Historical analysis should document how the business funds itself and how much capital it requires.

Questions to answer:

- How has capex evolved relative to sales and depreciation?
- Is the balance sheet getting stronger or weaker?
- Has growth been funded through retained cash flow, debt, or dilution?
- Are there balance-sheet items that should affect valuation confidence or the EV bridge?

Best practice:

- connect growth to reinvestment and funding
- look at balance-sheet evolution alongside margins and ROIC
- separate true operating reinvestment from financing-driven changes

Deterministic outputs:

- capex and D&A trend views
- leverage and liquidity trend views
- share-count evolution
- debt and cash summaries

LLM augmentation:

- highlight disclosed funding plans, refinancing, expansion projects, or balance-sheet stress

PM judgment:

- decide whether future growth assumptions need a different funding path than the recent past

## 8. Compare the history against peers

Historical analysis is stronger when the same company is viewed both through time and against a relevant peer set.

Peer-relative views should include:

- growth
- margins
- capital intensity
- working-capital behavior
- leverage
- dilution
- returns on capital

Best practice:

- compare companies with similar economics, not only industry codes
- use peer comparisons to test whether the company's history is exceptional, average, or weak
- distinguish structural outperformance from temporary timing effects

Deterministic outputs:

- peer-relative historical benchmark pack
- relative ranking or percentile views where coverage allows

LLM augmentation:

- explain why peer economics differ using business-model and disclosure context

PM judgment:

- decide whether the peer set is economically credible
- decide whether relative outperformance is durable

## 9. Identify the historical driver map

Historical analysis should end by identifying the major drivers that actually explain past performance.

This is the bridge into forecasting.

Questions to answer:

- Was revenue growth driven by price, volume, mix, utilization, acquisitions, or macro recovery?
- Were margins driven by scale, mix, pricing, procurement, or temporary relief?
- Did cash conversion improve because of genuine operating efficiency or because of a one-time timing effect?
- Was ROIC supported by durable economics or by an unusually favorable period?

Deterministic outputs:

- historical driver summary with linked numeric evidence
- shortlist of the metrics most relevant to forecasting

LLM augmentation:

- synthesize likely driver explanations from filings and commentary

PM judgment:

- decide which historical drivers deserve to be carried into the forecast

## 10. Produce a forecast handoff and validation block

Historical analysis should end with an explicit modeling handoff, not just tables.

The handoff should document:

- which periods are representative
- which periods are distorted or excluded from anchoring
- what the preferred growth anchors are
- what the preferred margin anchors are
- which capital-intensity and working-capital assumptions look credible
- which line items are too weakly sourced to trust without additional review

This is also where model-validation discipline should begin.
Before a historical series is allowed to anchor the forecast, the system should know:

- what the metric is
- how it was calculated
- what source it came from
- whether coverage is complete
- whether the period is representative

## Recommended Artifact Set

The system should eventually produce these artifacts from historical analysis:

| Artifact | Purpose | Owner |
| --- | --- | --- |
| Cleaned historical statements | baseline multi-year record | deterministic |
| Historical coverage and lineage table | shows where each metric came from | deterministic |
| Rolling growth and margin windows | captures trend and stability | deterministic |
| Common-size statements | reveals structural changes | deterministic |
| Historical ratio pack | organizes economics by category | deterministic |
| Working-capital and cash-conversion block | explains cash behavior | deterministic |
| Balance-sheet and funding review block | summarizes leverage, liquidity, dilution, and funding path | deterministic |
| Peer-relative historical benchmark pack | adds context against competitors | deterministic |
| Historical driver summary | explains likely causes of the numbers | LLM-augmented, PM-reviewed |
| Forecast handoff block | identifies what should feed the model | PM-owned |

## What Should Feed Directly Into Forecasting

The following historical outputs should eventually be eligible to feed the deterministic forecast layer directly:

- rolling growth windows
- historical margin ranges
- capital-intensity ranges
- DSO / DIO / DPO history
- dilution history
- leverage and liquidity history
- peer-relative historical ranges where sourced cleanly

The following should stay advisory until reviewed:

- proposed normalized anchors
- narrative explanations of historical inflections
- suggested representativeness filters
- LLM-generated conclusions about what "really mattered"

## Current Gaps In Alpha Pod

This is still one of the biggest gaps in the product.
Main gaps:

- no first-class cleaned historical statement pack exposed to the user
- no rolling-window system beyond narrow point solutions
- no common-size statement layer
- no rich historical ratio pack
- no explicit representativeness framework
- no robust peer-relative historical benchmark layer
- limited historical driver mapping from statements and filings into forecast assumptions

## Practical Review Questions For The PM

Before trusting the forecast, the PM should be able to answer:

1. Which years in the history are actually representative?
2. What does the rolling history say that a single CAGR would hide?
3. Are margins, cash conversion, and reinvestment structurally strong or temporarily flattered?
4. Does the balance sheet support the forecast path?
5. Which historical patterns are reliable enough to anchor the model, and which still require judgment?
