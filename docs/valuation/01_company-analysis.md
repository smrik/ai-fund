# Company Analysis

## Purpose

Company analysis comes before forecasting and before valuation.
Its job is to answer a basic question: **what kind of economic machine is this business?**

That means understanding:

- what the company sells
- who pays for it and why
- what drives volume, price, mix, and retention
- what the cost structure looks like
- how much capital the model consumes
- which variables actually matter enough to drive valuation

Without that work, a DCF is just a spreadsheet with assumptions attached.

## Why This Matters For Valuation

Best-practice public-equity analysis does not jump straight from raw statements to a discount rate.
Analysts first build a view of the business model, competitive position, and value-driver structure, then use that view to decide:

- whether the company is even suitable for a standard DCF
- whether growth, margins, capital efficiency, or normalization should dominate the valuation narrative
- which historical periods are representative
- which forecast variables deserve the most attention

This follows the same general logic emphasized across CFA financial statement modeling and company-analysis guidance: understand the business and its environment first, then use that understanding to identify the drivers of revenues, margins, cash flows, and financial position.

## Research Anchors

This page is aligned with the following methodology sources:

- CFA Institute, *Business Models*
- CFA Institute, *Company Analysis: Past and Present*
- CFA Institute, *Introduction to Financial Statement Modeling*
- CFA Institute, *Industry and Competitive Analysis*
- McKinsey, *How are companies valued?*
- McKinsey, *Balancing ROIC and growth to build value*

These matter here because they reinforce the same core idea: valuation depends on growth, profitability, and capital efficiency together, and those are only understandable in context of the business model and industry structure.

## Where Company Analysis Sits In Alpha Pod

The intended flow is:

1. company analysis
2. industry analysis
3. historical financial analysis
4. financial forecasting
5. DCF / comps / PM review

In Alpha Pod terms, company analysis should become the bridge between:

- retrieved facts and filings
- deterministic historical metrics
- forecast assumptions
- LLM-augmented narrative interpretation
- PM-approved valuation judgment

## Ownership Model

### Deterministic

Good deterministic company-analysis outputs include:

- segment mix tables
- geography / product / channel mix when disclosed numerically
- customer concentration percentages when disclosed numerically
- historical price / volume / mix proxy calculations when the data exists
- margin, capital-intensity, working-capital, and dilution summaries
- balance-sheet and capital-allocation diagnostics

### LLM-augmented

LLMs are useful for:

- summarizing business descriptions from filings
- surfacing likely revenue-model characteristics from text
- extracting management commentary on pricing, backlog, bookings, churn, utilization, and expansion
- identifying plausible business drivers from MD&A and earnings-call text
- comparing business descriptions across peer companies

### Human / PM Judgment

PM judgment is still required for:

- deciding what the true economic engine is
- deciding which drivers matter enough to forecast explicitly
- deciding whether management framing is credible
- deciding whether historical performance reflects real business quality or temporary distortion
- deciding whether the company is understandable enough to underwrite confidently

### Hard Boundary

LLM outputs may inform company analysis, but they should not directly rewrite deterministic valuation inputs.
Any move from advisory interpretation into forecast assumptions should happen through explicit PM approval or a structured override path.

## Full Workflow

## 1. Frame the business before reading the statements

The first step is to describe the company in plain economic terms.
This is not a prose exercise for its own sake; it determines what the later financial analysis should emphasize.

Questions to answer:

- What is the company actually selling?
- Who is the customer?
- What pain point or job-to-be-done is being monetized?
- Is the company selling a product, a service, access, software, capacity, distribution, financing, or some hybrid?
- Is value creation driven mainly by brand, scale, switching costs, regulation, intellectual property, network effects, or commodity position?

Best practice:

- do not rely only on management's framing
- translate the business description into a small set of economic drivers
- identify early whether the business is asset-light, asset-heavy, cyclical, regulated, or structurally hard to model with a standard DCF

Deterministic outputs:

- legal entity and listing identity
- segment, geography, and product mix tables where numerically disclosed
- concentration ratios where numerically disclosed

LLM augmentation:

- summarize the business model from filings
- identify unusual or hybrid business models
- extract stated strategic priorities, customer groups, and go-to-market structure

PM judgment:

- define the real business model in analyst language, not management language
- decide which segment or unit should anchor the forecast

## 2. Map the revenue model

Revenue analysis should move beyond "sales grew x%."
The job is to identify what the company needs to do operationally to generate more revenue.

Common revenue-model archetypes:

- price x volume
- seats x ARPU
- users x conversion x monetization
- backlog x conversion
- capacity x utilization x yield
- stores x same-store sales
- subscribers x retention x net adds x price
- units sold x mix x price

Questions to answer:

- What are the practical revenue drivers?
- Is growth driven by new customers, wallet share, pricing, mix, utilization, acquisitions, or macro exposure?
- How much pricing power does the business appear to have?
- What evidence exists for recurring versus transactional behavior?

Best practice:

- use bottom-up driver analysis where possible
- supplement with top-down drivers such as market growth, market share, and macro exposure
- distinguish company-specific drivers from industry-wide or macro drivers

Deterministic outputs:

- historical revenue by segment or geography when available
- revenue concentration metrics
- historical sales growth by period and rolling window
- simple price / volume / mix proxies if data supports them

LLM augmentation:

- explain likely drivers of revenue changes from filings
- identify whether revenue growth seems volume-led, price-led, mix-led, or M&A-led
- surface language around bookings, backlog, churn, net retention, or utilization

PM judgment:

- decide which drivers are truly forecastable
- decide whether a top-down or bottom-up forecast should dominate

## 3. Understand the cost structure and operating leverage

The next step is to ask how revenue turns into EBIT and cash.

Questions to answer:

- Which costs are structurally variable and which are fixed or semi-fixed?
- Does the company benefit from scale?
- Are margins driven by mix, pricing power, utilization, procurement, or capital intensity?
- Are reported margins distorted by one-offs, acquisitions, or accounting treatment?

Best practice:

- analyze gross, EBIT, EBITDA, and FCF margins together
- identify whether margin change is structural, cyclical, or accounting-driven
- connect operating leverage to the business model, not just to historical percentage changes

Deterministic outputs:

- historical gross, EBIT, EBITDA, and FCF margin tables
- operating leverage proxies from cost-line behavior
- common-size income statement outputs from the historical-analysis layer

LLM augmentation:

- explain major margin inflections from filings
- identify management commentary on cost reduction, mix change, or pricing

PM judgment:

- decide which margin inflections are durable
- decide what should be treated as normalized versus transient

## 4. Assess capital intensity and reinvestment needs

A strong company analysis should tell us how expensive growth is.
This is one of the biggest links between business understanding and DCF quality.

Questions to answer:

- How much capital is required to support incremental growth?
- Is reinvestment mainly capex, working capital, R&D-like expense, acquisitions, or customer acquisition cost?
- Is growth likely to improve returns on capital or dilute them?

Best practice:

- connect growth to reinvestment explicitly
- analyze capital intensity in both accounting and economic terms
- distinguish maintenance investment from expansion investment where possible

Deterministic outputs:

- capex / sales
- D&A / sales
- working-capital intensity
- invested-capital trend proxies
- share-count and acquisition dependence

LLM augmentation:

- identify management commentary about capacity expansion, new facilities, product investment, or go-to-market scaling
- summarize whether management appears focused on growth, margin, or capital efficiency

PM judgment:

- decide which reinvestment mechanism matters most
- decide whether growth should be viewed as value-accretive or value-destructive at current returns

## 5. Analyze customers, suppliers, and bargaining power

Company quality is partly determined by who holds the power in the value chain.

Questions to answer:

- Does the company have concentrated customers or suppliers?
- Are contracts long-term or spot-like?
- Are switching costs high or low?
- Is pricing set by the company, negotiated, indexed, or market-clearing?
- Is the company exposed to key suppliers, distributors, or platforms?

Best practice:

- combine concentration data with business-model interpretation
- link bargaining power directly to margin stability and cash-flow predictability

Deterministic outputs:

- disclosed concentration percentages
- dependence on a small set of segments or geographies

LLM augmentation:

- summarize supplier and customer risk from filings
- identify recurring mentions of renegotiation, channel conflict, dependence, or contract concentration

PM judgment:

- decide whether concentration is a feature, a risk, or both
- decide whether apparent bargaining power is structural or temporary

## 6. Evaluate competitive position and business quality

This step asks whether the company has a defendable economic advantage or is just enjoying a favorable period.

Questions to answer:

- What appears to protect margins or returns on capital?
- Is the company gaining share because of product quality, price, network, brand, regulation, distribution, or execution?
- Does historical ROIC look durable?
- Does the company benefit from scale or suffer from competition?

Best practice:

- tie business quality to evidence in margins, ROIC, and cash conversion
- evaluate quality relative to peers and industry economics, not only absolute levels

Deterministic outputs:

- margin stability
- ROIC / capital-efficiency metrics
- peer-relative historical comparison tables

LLM augmentation:

- compare business descriptions and strategic language across peers
- explain likely competitive moats or weaknesses from text

PM judgment:

- decide what the moat is, if any
- decide whether the current economics are sustainable

## 7. Review management and capital allocation

For public-equity underwriting, management behavior matters because it shapes dilution, acquisitions, leverage, buybacks, and reinvestment quality.

Questions to answer:

- Has management historically created value through reinvestment?
- Has per-share value benefited or been diluted?
- Are acquisitions disciplined or empire-building?
- Has management used leverage prudently?

Best practice:

- evaluate management through outcomes, not only narratives
- focus on capital allocation, dilution, balance-sheet risk, and guidance quality

Deterministic outputs:

- share-count trend
- acquisition intensity proxies
- leverage and liquidity trend summaries

LLM augmentation:

- summarize guidance language and management priorities
- identify repeated themes around capital return, M&A, or strategic repositioning

PM judgment:

- decide whether management deserves the benefit of the doubt in the forecast
- decide whether the capital-allocation record changes valuation confidence

## 8. Produce a forecast-ready driver map

The end goal of company analysis is not a memo for its own sake.
It is a **driver map** that feeds historical analysis, forecasting, comps, and PM review.

That driver map should answer:

- What is the dominant revenue engine?
- What are the two to five most important variables for the next three to five years?
- Which variables are company-specific, industry-driven, or macro-driven?
- Which assumptions are safe to automate?
- Which assumptions need LLM support?
- Which assumptions require explicit PM judgment?

## Recommended Artifact Set

The system should eventually produce these artifacts from company analysis:

| Artifact | Purpose | Owner |
| --- | --- | --- |
| Business model card | concise description of the economic engine | LLM-augmented, PM-reviewed |
| Revenue model map | documents price / volume / mix / retention logic | mixed |
| Cost-structure summary | captures fixed vs variable and operating leverage implications | mixed |
| Capital-intensity profile | shows how growth consumes capital | deterministic |
| Working-capital profile | explains cash conversion and operating drag/release | deterministic |
| Customer / supplier concentration block | summarizes concentration risk | deterministic + LLM |
| Competitive-position summary | explains moat, rivalry, and advantage durability | LLM-augmented, PM-reviewed |
| Management capital-allocation notes | captures dilution, leverage, and reinvestment behavior | mixed |
| Forecast driver shortlist | identifies the key assumptions that must carry into the model | PM-owned |

## Forecast Handoff And Validation Block

Company analysis should end with a concise handoff into modeling.
That handoff should document:

- the primary business model classification
- the dominant revenue engine
- the main cost and margin drivers
- the capital-intensity profile
- the working-capital profile
- the likely industry and macro exposures
- the two to five variables that deserve the most forecast attention

It should also document modeling confidence:

- how understandable the business is
- how reliable the driver map appears
- whether the company looks DCF-suitable
- which areas still require human judgment before assumptions are locked

This follows a simple professional modeling rule: do not pass vague narrative into a forecast.
Pass a small, explicit assumption framework with evidence attached.

## What Should Feed Directly Into Valuation

The following should eventually feed the deterministic layer directly when the data quality is sufficient:

- segment mix and revenue composition facts
- historical capital-intensity metrics
- working-capital characteristics
- dilution history
- leverage and liquidity facts
- operating-margin history

The following should stay advisory unless explicitly approved:

- LLM-inferred qualitative driver weighting
- suggested normalization adjustments
- management-credibility conclusions
- moat or business-quality narratives

## Validation Questions

Before company analysis is allowed to influence the model, we should be able to answer:

- Is the business model described in analyst language rather than copied from management?
- Are the major revenue, margin, and reinvestment drivers explicit?
- Are the drivers supported by both numbers and disclosures?
- Are company-specific, industry, and macro drivers separated clearly enough to forecast them differently?
- Is the proposed driver set small enough to be useful rather than encyclopedic?

## Current Gaps In Alpha Pod

The current stack is stronger on valuation computation than on company-analysis artifacts.
Main gaps to close:

- no first-class business model card
- limited explicit revenue-driver framework
- limited integration between company analysis and historical-analysis artifacts
- weak direct mapping from company analysis into forecast assumptions
- limited structured distinction between company-specific, industry, and macro drivers
- no clear PM review object capturing what the analyst actually believes about the business

## Practical Review Questions For The PM

Before relying on any valuation, the PM should be able to answer:

1. What does this company actually do in economic terms?
2. What are the two to five variables that matter most for value?
3. Is growth mainly a function of price, volume, mix, utilization, or capital deployment?
4. Are margins and returns on capital structurally defensible?
5. Is growth likely to create value or merely consume capital?
6. Which assumptions are based on evidence, and which are still judgment calls?
