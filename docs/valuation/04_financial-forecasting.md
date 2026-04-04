# Financial Forecasting

## Purpose

Forecasting is the translation layer between:

- company analysis
- industry analysis
- historical financial analysis

and the forward assumptions used in valuation.

Its job is to convert business understanding into a small set of explicit, auditable assumptions that can drive:

- DCF
- reverse DCF
- scenario analysis
- sensitivity analysis
- comps interpretation

Forecasting should not be a vague narrative exercise, and it should not be a spreadsheet filled with unexamined defaults.
It should be a disciplined assumption framework.

## Why This Matters For Valuation

A valuation model is only as good as its forward assumptions.
That means forecasting is where most of the real analytical judgment lives.

A strong forecasting process should answer:

- what is being forecast and why
- which variables are the true drivers of value
- how those drivers connect to history, company economics, industry structure, and macro conditions
- what is deterministic versus judgment-based
- which assumptions are most worth debating because they matter most to intrinsic value

In practice, good forecasting should reduce two common failures:

- mechanically extrapolating recent trends
- hiding weak business thinking behind a lot of spreadsheet detail

## Core Principles

### Forecast identified business drivers, not generic lines in isolation

Growth should come from a view on:

- demand
- pricing
- mix
- capacity
- market share
- retention

Margins should come from a view on:

- cost structure
- operating leverage
- mix
- procurement
- inflation
- utilization

Reinvestment should come from the growth path.

Balance-sheet evolution should reflect how that growth is funded.

### Keep assumptions explicit and sourced

Every important assumption should have:

- a current value
- a target value or path
- a rationale
- a source or evidence base
- a sensitivity range

### Tie growth to reinvestment and returns

Growth is not free.
A serious forecast should connect revenue growth to:

- capex
- working capital
- acquisitions where relevant
- dilution or leverage if required to fund that growth

### Use scenarios deliberately

Scenarios are not decoration.
They should reflect real alternative business outcomes, not only generic numeric perturbations.

## Where Forecasting Sits In Alpha Pod

The intended flow is:

1. company analysis identifies the business model and key drivers
2. industry analysis identifies structural, cyclical, and macro context
3. historical analysis identifies representative ranges and inflections
4. forecasting converts that into explicit forward assumptions
5. DCF and comps consume those assumptions

In Alpha Pod, forecasting should become the main bridge between:

- deterministic historical metrics
- LLM-augmented evidence synthesis
- PM-approved valuation assumptions

## Ownership Model

### Deterministic

Deterministic forecasting should own:

- projection math
- fade mechanics
- scenario mechanics once assumptions are chosen
- ratio-driven line-item projections
- explicit assumption storage
- forecast bridge artifacts
- validation checks

### LLM-augmented

LLMs are useful for:

- extracting likely revenue and margin drivers from filings
- summarizing industry and macro context relevant to the forecast
- explaining why a margin path might improve or deteriorate
- highlighting disclosed management plans, backlog, utilization, expansion projects, pricing commentary, or capital programs
- surfacing contradictions between management commentary and historical evidence

### Human / PM Judgment

PM judgment is still required for:

- choosing the dominant driver model
- deciding what is realistic, conservative, or aggressive
- choosing representative periods
- approving any normalization or override that changes the forecast base
- deciding which scenario framing best fits the business

### Hard Boundary

LLM outputs may inform assumptions, but they should not directly mutate the deterministic forecast driver set.
Any LLM-suggested assumption change should remain advisory until it is explicitly approved.

## Full Workflow

## 1. Scope the forecast before building it

Before forecasting, define what the model is trying to support.

Questions to answer:

- Is this forecast for intrinsic value, scenario comparison, downside testing, or thesis monitoring?
- What level of detail is actually useful for this company?
- Which outputs matter most: EV, equity value, implied growth, scenario range, or a driver bridge?
- Is the business stable enough for a standard DCF framework?

Best practice:

- choose the level of detail intentionally
- do not build a highly detailed forecast for a business that is not forecastable with confidence
- make the forecast fit the decision, not the other way around

Deterministic outputs:

- forecast horizon
- scenario structure
- standard line-item layout

LLM augmentation:

- summarize where management and disclosures indicate high uncertainty

PM judgment:

- decide whether the business is forecastable enough for a full DCF

## 2. Build the assumption register

Before projecting, define the assumptions that will control the model.

Required categories:

- operating assumptions
- valuation assumptions
- capital-structure assumptions
- timing assumptions
- scenario assumptions

A clean assumption register should document:

- assumption name
- current value
- forecast path or target
- source
- rationale
- sensitivity range

Examples:

- near-term revenue growth
- mid-term growth fade
- terminal growth
- EBIT margin start and target
- capex intensity start and target
- working-capital day assumptions
- tax rate
- WACC components
- exit multiple or terminal framework

Best practice:

- avoid hidden assumptions inside formulas
- make source and rationale visible
- separate assumption selection from projection mechanics

## 3. Forecast revenue from explicit drivers

Revenue should be driven by a model that fits the business.

Possible driver frames:

- price x volume
- customers x ARPU
- units x ASP
- utilization x capacity x yield
- same-store growth plus footprint expansion
- subscribers x retention x net adds x price
- backlog x conversion

Questions to answer:

- Is revenue mainly company-driven, industry-driven, or macro-driven?
- Are growth drivers bottom-up, top-down, or mixed?
- Is the near term constrained by capacity, demand, competition, or funding?
- Is growth coming from price, volume, mix, or acquisition?

Best practice:

- tie revenue assumptions to the business model
- use history as evidence, not as an autopilot
- separate near-term visibility from medium-term and terminal assumptions
- document when a forecast is more narrative-driven than data-driven

Deterministic outputs:

- revenue growth path by forecast year
- explicit near / mid / terminal growth structure
- historical-to-forecast bridge tables

LLM augmentation:

- extract disclosed growth drivers from filings
- summarize backlog, utilization, price realization, pipeline, retention, or market-growth commentary

PM judgment:

- choose the dominant revenue-driver model
- decide how much weight to place on management guidance versus historical evidence

## 4. Forecast profitability and operating leverage

Margin forecasting should be linked to the economics of the business, not just to a target percentage.

Questions to answer:

- Are margins primarily driven by scale, mix, pricing, cost inflation, or utilization?
- Which costs are variable, fixed, or semi-fixed?
- Is the current margin above, below, or near a normalized level?
- Should the margin path mean-revert, improve, or compress?

Best practice:

- forecast gross, EBIT, EBITDA, and FCF logic consistently
- explain margin change rather than just setting a target
- distinguish structural improvement from cyclical recovery

Deterministic outputs:

- EBIT margin path
- margin bridge by year or stage
- operating leverage diagnostics

LLM augmentation:

- summarize management commentary on mix, pricing, productivity, inflation, cost savings, and utilization

PM judgment:

- decide whether margin expansion or compression is durable
- decide whether current margins need normalization before being projected

## 5. Forecast taxes

Tax should not be ignored just because it looks small relative to the rest of the model.

Questions to answer:

- Is the recent effective tax rate representative?
- Are there geographic, legal-entity, NOL, or one-time effects distorting the recent rate?
- Should the model converge to a more stable tax profile than the latest reported year?

Best practice:

- use historical context, not only the latest point
- bound extreme values
- distinguish reported tax distortion from the normalized operating tax burden

Deterministic outputs:

- tax start rate
- tax target rate
- tax convergence path

LLM augmentation:

- explain unusual recent tax behavior from filings

PM judgment:

- decide whether recent tax outcomes are meaningful enough to carry into the forecast

## 6. Forecast reinvestment

Growth requires reinvestment.
This is one of the most important areas where valuation quality often breaks down.

The forecasting process should define:

- capex needs
- working-capital needs
- acquisition dependence where relevant
- maintenance versus growth capex where possible
- the implied capital required to support the growth path

Questions to answer:

- How much capital does the business need for each unit of growth?
- Is growth working-capital-intensive?
- Is management likely to reinvest efficiently?
- Does the model imply returns on new capital above the cost of capital?

Best practice:

- connect growth and reinvestment explicitly
- use historical capital-intensity evidence as an anchor
- do not let aggressive growth assumptions coexist with unrealistically light reinvestment

Deterministic outputs:

- capex path
- D&A path
- working-capital day paths
- reinvestment bridge

LLM augmentation:

- summarize disclosed expansion plans, facilities, product investments, or go-to-market spend

PM judgment:

- decide whether the implied reinvestment burden is realistic
- decide whether growth is likely to create value or dilute returns

## 7. Forecast the balance sheet and funding path

If the company wants to grow, the money has to come from somewhere.
Forecasting should eventually reflect:

- retained cash flow
- incremental debt
- dilution or buybacks
- capital-structure evolution

Questions to answer:

- Can the current balance sheet support the planned growth path?
- Does the model implicitly require more debt or equity than the current structure suggests?
- Should WACC and capital structure evolve with the forecast?

Best practice:

- treat funding as part of the forecast, not a separate afterthought
- make sure the balance sheet and forecast story are coherent
- watch for cases where optimistic growth quietly requires external funding

Deterministic outputs:

- funding-path review
- debt, cash, and share-count assumptions
- capital-structure bridge where implemented

LLM augmentation:

- summarize management commentary on leverage, refinancing, capital return, or funding plans

PM judgment:

- decide whether the funding path is credible
- decide whether capital-structure changes should alter valuation confidence

## 8. Design scenarios and sensitivities

Scenario design should reflect real business alternatives, not only generic up and down cases.

Scenario questions:

- What does bear really mean for this business?
- What does bull require operationally?
- Which assumptions should move together?
- Which single variables matter enough to isolate?

Sensitivity questions:

- Which assumptions change intrinsic value the most?
- Which assumptions are least observable and most error-prone?

Best practice:

- make scenarios thesis-specific where possible
- separate multi-variable scenarios from one-variable sensitivities
- prioritize assumptions that matter most for PM decision-making

Deterministic outputs:

- scenario valuation outputs
- sensitivity grids
- implied-expectation outputs

LLM augmentation:

- help articulate what operationally differentiates scenarios

PM judgment:

- decide which scenarios are credible enough to matter
- decide which sensitivities deserve the most weight in the review

## 9. Validate the forecast before using it

A forecast should be validated before it is trusted.

Validation questions:

- Does the forecast line up with the stated business model?
- Do growth, margin, and reinvestment move coherently together?
- Does the balance sheet support the operating plan?
- Are the assumptions explicit and sourced?
- Are the scenario ranges reasonable?
- Do the outputs look plausible relative to peers and history?

Best practice:

- test reasonableness, not only formula correctness
- do not rationalize a weak assumption just because the spreadsheet still computes
- identify the assumptions that are carrying the valuation

## Recommended Artifact Set

The system should eventually produce these forecasting artifacts:

| Artifact | Purpose | Owner |
| --- | --- | --- |
| Assumption register | documents all model inputs with rationale and source | deterministic, PM-reviewed |
| Revenue-driver map | links business drivers to forecast growth | mixed |
| Historical-to-forecast bridge | shows how the forecast departs from history | deterministic |
| Margin and profitability bridge | explains the path from current to target profitability | mixed |
| Reinvestment bridge | links growth to capex and working capital | deterministic |
| Funding-path review | explains how the company finances the plan | mixed |
| Scenario definitions | documents what bear / base / bull mean operationally | PM-owned |
| Sensitivity summary | highlights which assumptions matter most | deterministic |
| Forecast review checklist | structured PM review before using the model | PM-owned |

## What Should Feed Directly Into Valuation

The following forecast outputs should eventually feed the deterministic valuation layer directly:

- revenue growth path
- margin path
- tax path
- capex and D&A path
- working-capital paths
- funding-path assumptions where explicitly modeled
- scenario parameter sets

The following should stay advisory until approved:

- LLM-suggested driver emphasis
- suggested macro overlays
- management-credibility conclusions
- qualitative scenario narratives that imply changing assumptions without approval

## Current Implementation Notes

Alpha Pod already has a deterministic forecast engine and a useful assumption assembler.
What it still lacks is a richer finance-first forecasting framework that makes the bridge from:

- company analysis
- industry analysis
- historical analysis
- normalization and QoE review

into forecast assumptions much more explicit.

Current gaps include:

- no first-class assumption register exposed to the user
- limited formal driver mapping from company analysis into forecast design
- limited explicit funding-path logic
- scenario design that is still more generic than company-specific
- incomplete documentation of which assumptions are genuinely evidence-based versus heuristic fallbacks

## Practical Review Questions For The PM

Before relying on a forecast, the PM should be able to answer:

1. What are the main drivers of revenue, margins, and reinvestment?
2. Why should the forecast differ from the recent historical period?
3. Is the growth path economically coherent with the required reinvestment?
4. Does the balance sheet support the operating story?
5. Which assumptions matter most to value, and how confident are we in each of them?
