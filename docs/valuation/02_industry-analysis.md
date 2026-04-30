# Industry Analysis

## Purpose

A company is never forecast in a vacuum.
Industry analysis defines the economic environment that company analysis and financial forecasting must live inside.

Its job is to answer:

- what market the company actually competes in
- how that market creates and distributes economic value
- what the normal industry economics look like
- which forces are structural versus cyclical
- how much of the forecast should be company-specific versus industry- or macro-driven

Without this layer, analysts often mistake a favorable cycle for a durable business-quality advantage, or treat a structurally weak industry as though company execution alone can solve it.

## Why This Matters For Valuation

Industry analysis should shape:

- valuation method selection
- forecast ranges
- margin expectations
- reinvestment norms
- WACC interpretation
- comps peer selection
- scenario design

A strong company can still deserve a constrained valuation if the industry is structurally low return, cyclical, regulated, or capital intensive.
Likewise, a high-quality industry can justify more confidence in long-duration value if the company has a defendable position within it.

## Ownership Model

### Deterministic

Good deterministic industry-analysis outputs include:

- peer growth, margin, multiple, and capital-intensity distributions
- historical industry benchmark tables where structured peer data exists
- cycle-sensitive benchmark ranges
- sector / sub-industry reference metrics

### LLM-augmented

LLMs are useful for:

- summarizing market structure and value-chain dynamics
- identifying secular themes and cyclical drivers from filings, industry reports, and earnings commentary
- comparing business descriptions across peer companies
- surfacing regulation, substitution, disruption, and technological change themes

### Human / PM Judgment

PM judgment is still required for:

- deciding what the real industry frame is
- deciding which peer set is economically relevant
- deciding how much of current industry strength or weakness is cyclical
- deciding whether the company's edge is structural or temporary

### Hard Boundary

Industry analysis can inform deterministic assumptions, but it should not directly rewrite them without explicit approval.
LLM-generated industry narratives should remain advisory until the PM converts them into forecast choices or scenario framing.

## Full Workflow

## 1. Define the relevant market

The first job is to decide what market the company actually competes in.

Questions to answer:

- What market is this company really in?
- Is the useful frame a sector, a niche sub-industry, a value-chain position, or an end-market exposure?
- Is the company competing across multiple markets with different economics?

Best practice:

- avoid relying only on headline classifications
- define the market in a way that helps explain revenue drivers, margin structure, and capital intensity
- separate broad sector labels from the actual competitive arena

Deterministic outputs:

- peer-set candidates
- basic market and sub-industry grouping data

LLM augmentation:

- summarize how filings and company descriptions position the market
- identify business-model differences hidden inside one formal industry code

PM judgment:

- decide which market frame is the right one for underwriting

## 2. Map the value chain and profit pool

Industry analysis should identify where value is created and who captures it.

Questions to answer:

- Where in the value chain does the company sit?
- Who has the bargaining power?
- Which layers tend to capture the best returns?
- Is the company closer to a commodity position, a branded position, a platform, a distributor, or a regulated operator?

Best practice:

- think in terms of profit pools, not just reported revenue
- identify where price competition is strongest and where differentiation matters most
- connect value-chain position to margin durability

Deterministic outputs:

- none beyond structured peer classifications and concentration data

LLM augmentation:

- summarize the value chain
- explain who appears to earn the best economics and why

PM judgment:

- decide whether the company occupies a favorable or vulnerable position in the chain

## 3. Identify industry economics and normal ranges

This step asks what "normal" looks like in the industry.

Questions to answer:

- What growth range is typical?
- What margin range is typical?
- What reinvestment burden is typical?
- What working-capital profile is typical?
- What multiples are generally paid for the better and weaker businesses in the group?

Best practice:

- benchmark operating and valuation ranges across peers
- separate high-quality industry members from the median
- use ranges, not just a single peer median

Deterministic outputs:

- benchmark tables for growth, margins, capital intensity, leverage, and multiples
- peer distributions and percentiles where data exists

LLM augmentation:

- explain why industry ranges look the way they do

PM judgment:

- decide which benchmark range is most relevant for the target company

## 4. Separate secular from cyclical drivers

This is one of the most important jobs of industry analysis.

Examples:

- secular:
  - cloud migration
  - aging demographics
  - digitization
  - outsourcing
  - premiumization
- cyclical:
  - commodity prices
  - freight cycles
  - industrial utilization
  - ad budgets
  - housing activity

Questions to answer:

- Which demand drivers are durable structural shifts?
- Which are cyclical tailwinds or headwinds?
- Is the current environment above, below, or near mid-cycle?

Best practice:

- do not let cyclical peaks anchor long-term forecasts
- keep secular and cyclical effects separate in the story
- use this distinction to shape scenarios

Deterministic outputs:

- cycle-aware benchmark ranges where structured history supports them
- quantitative cycle indicators where relevant, including capacity utilization, inventory days versus trend, ISM / PMI, OECD CLI, commodity prices, credit spreads, yield-curve shape, and sector-specific demand indicators
- FRED-backed macro context where Alpha Pod already has a structured source available

LLM augmentation:

- synthesize management and peer commentary on cyclical versus secular factors

PM judgment:

- decide whether the present period is representative or distorted by the cycle

Cycle-indicator policy:

- industry analysis should produce a forecast-constraint pack, not only prose
- each relevant indicator should be tagged as structural, cyclical, or noise
- the forecast should show whether revenue growth, margin, working capital, or capex assumptions are constrained by those indicators
- macro-regime labels may inform scenario context, but official scenario weights need explicit methodology approval when they materially change expected intrinsic value

## 5. Analyze competitive intensity and moat conditions

Industry structure shapes how hard it is to sustain margins and returns on capital.

Questions to answer:

- Is the industry concentrated or fragmented?
- Are products differentiated or commoditized?
- Is price competition severe?
- Are switching costs meaningful?
- Are network effects, regulation, or scale advantages present?

Best practice:

- connect industry structure directly to margin durability and ROIC
- use industry analysis to pressure-test company-analysis conclusions about moat

Deterministic outputs:

- peer concentration and dispersion summaries where available

LLM augmentation:

- summarize rivalry, differentiation, substitution, and entry risk

PM judgment:

- decide whether the industry supports durable excess returns

## 6. Review regulation and exogenous constraints

Some industries are heavily shaped by regulation, reimbursement, commodity exposure, or other external constraints.

Questions to answer:

- How important is regulation?
- Are margins capped or politically sensitive?
- Are there licensing, reimbursement, environmental, or safety rules that shape returns?
- Do commodity inputs or macro rates dominate economics?

Best practice:

- treat these as core valuation inputs when material, not side notes

Deterministic outputs:

- limited, mostly through sector and peer benchmarks

LLM augmentation:

- summarize regulatory and external risk themes from filings and industry commentary

PM judgment:

- decide how much external constraints should reduce valuation confidence

## 7. Translate industry analysis into forecast and valuation implications

Industry analysis should not end as a memo.
It should produce a usable constraint set for the forecast.

That should answer:

- what long-run growth range is plausible
- what margin range is plausible
- what reinvestment burden is plausible
- what cycle-aware bear and bull cases should look like
- what peers are economically comparable enough for comps
- whether the company deserves above-, in-line, or below-industry assumptions

## Recommended Artifact Set

| Artifact | Purpose | Owner |
| --- | --- | --- |
| Industry structure note | defines the relevant market and value-chain position | LLM-augmented, PM-reviewed |
| Value-chain map | shows where economics are captured | LLM-augmented |
| Industry economics benchmark table | growth, margin, capital-intensity, leverage, and multiple ranges | deterministic |
| Secular vs cyclical driver table | separates durable themes from cycle noise | mixed |
| Competitive-intensity note | explains rivalry, substitution, and concentration | mixed |
| Regulatory and exogenous-risk note | captures non-company constraints | mixed |
| Forecast constraint pack | translates industry analysis into forecast ranges | PM-owned |

## What Should Feed Directly Into Valuation

The following should eventually feed deterministic valuation directly when sourced cleanly:

- peer benchmark ranges
- cycle-aware margin and multiple ranges
- capital-intensity and leverage norms
- peer distributions used by comps and scenario framing

The following should stay advisory until explicitly converted into assumptions:

- narrative views on industry disruption
- moat narratives
- secular-theme weighting
- management-credibility judgments based on industry framing

## Current Implementation Notes

Industry context exists today mostly through judgment-layer work such as the `IndustryAgent`.
It is useful, but it is not yet a deep canonical finance layer that directly structures forecasting, scenarios, and comps.

Main gaps:

- no first-class industry benchmark pack inside the valuation workflow
- limited direct mapping from industry analysis to forecast ranges
- limited cycle-aware scenario framing
- limited structured integration between industry context and peer-set construction

## Practical Review Questions For The PM

Before relying on any forecast, the PM should be able to answer:

1. What industry is this company actually competing in?
2. What are the normal economics of that industry?
3. Which current conditions are cyclical and which are structural?
4. Does the company's edge survive a realistic industry framing?
5. Are the forecast and comps assumptions consistent with industry reality?
