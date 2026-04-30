# Deterministic Valuation Benchmark And Gap Analysis

Methodology-first valuation docs now live in [`docs/valuation/`](../valuation/index.md).
Use this document for benchmark analysis and implementation-oriented gap mapping.
Use [`valuation-methodology-critical-review-and-action-plan.md`](./valuation-methodology-critical-review-and-action-plan.md) for the current consolidated action memo.
This file remains the benchmark/gap register; the critical review memo is the live sequencing layer for the docs PR and next coding PR.

## 1. Purpose

This document extends the current-state valuation audit with a best-practice benchmark.

It answers five questions:

1. What does a rigorous public-equity valuation process need to cover?
2. Where does Alpha Pod's deterministic valuation process already align well?
3. Where is the current process partial, heuristic, or under-documented?
4. Which gaps are really **data / CIQ retrieval** gaps versus **model-design** gaps?
5. Which follow-on GitHub issues should exist before API, JSON export, and Excel work harden further?

This document is a companion to:

- `docs/design-docs/deterministic-valuation-flow-spec.md`
- `docs/design-docs/deterministic-valuation-workflow.md`
- `docs/design-docs/deterministic-valuation-inputs-and-ciq-retrieval-spec.md`
- `docs/handbook/valuation-dcf-logic.md`

Those documents explain the implemented flow.
This document benchmarks that flow against external valuation practice and records the resulting gap register.

## 2. Research Lens And Sources

This research uses a **public-equity PM lens**.
It is not trying to design a full sell-side QoE process or a private-equity LBO diligence workflow.

It does, however, pull in external valuation principles that matter for:

- DCF integrity
- comparable-company quality
- capital structure and bridge treatment
- normalized operating metrics
- scenario and implied-expectation analysis

Primary source set:

| Source | Topic | Why it matters here |
| --- | --- | --- |
| Damodaran, `dcfX.pdf` | DCF mechanics and value-driver framing | anchors growth, cash flow, and terminal-value logic |
| Damodaran, `growthandtermvalue.pdf` | stable growth and terminal assumptions | relevant to terminal growth, reinvestment, and long-run economics |
| McKinsey, "How are companies valued?" | growth + ROIC as joint value drivers | useful for benchmarking Alpha Pod's driver emphasis |
| McKinsey, "Balancing ROIC and growth to build value" | durability of ROIC vs transient growth | relevant to fade assumptions and reinvestment logic |
| McKinsey, "The right role for multiples in valuation" | peer selection and multiple hygiene | directly relevant to current comps design |
| McKinsey, "How to value cyclical companies" | scenario-based valuation for cyclicals | relevant to current bear/base/bull engine |
| CFA Institute, "Market-Based Valuation: Price and Enterprise Value Multiples" | multiple selection and interpretation | useful benchmark for EV vs equity multiples |
| IFRS IAS 36 | value-in-use discipline and discounting | useful benchmark for cash-flow and discount-rate consistency |
| IFRS 16 | lease obligations and operating / financing treatment | relevant to bridge-item rigor |
| Deloitte / Big 4 working-capital and adjusted EBITDA materials | practical normalization and working-capital quality | useful benchmark for QoE and normalization gaps |

Reference links:

- https://people.stern.nyu.edu/adamodar/pdfiles/execval/dcfX.pdf
- https://people.stern.nyu.edu/adamodar/pdfiles/ovhds/dam2ed/growthandtermvalue.pdf
- https://www.mckinsey.com/featured-insights/mckinsey-explainers/how-are-companies-valued
- https://www.mckinsey.com/business-functions/strategy-and-corporate-finance/our-insights/balancing-roic-and-growth-to-build-value
- https://www.mckinsey.com/capabilities/strategy-and-corporate-finance/our-insights/the-right-role-for-multiples-in-valuation
- https://www.mckinsey.com/capabilities/strategy-and-corporate-finance/our-insights/how-to-value-cyclical-companies
- https://www.cfainstitute.org/insights/professional-learning/refresher-readings/2026/market-based-valuation-price-enterprise-value-multiples
- https://www.ifrs.org/issued-standards/list-of-standards/ias-36-impairment-of-assets/
- https://www.ifrs.org/issued-standards/list-of-standards/ifrs-16-leases/
- https://www.deloitte.com/us/en/services/consulting/articles/working-capital-improvement.html
- https://www.deloitte.com/us/en/what-we-do/capabilities/mergers-acquisitions-restructuring/articles/sell-side-value-creation.html

## 3. Benchmark: What A Strong Public-Equity Valuation Process Should Cover

### 3.1 Business understanding and valuation gating

A strong process should decide **before modeling**:

- whether the business is DCF-suitable at all
- which value driver should dominate the narrative:
  - growth
  - margin improvement
  - capital efficiency / ROIC
  - normalization / turnaround
- whether an alternative model is more appropriate

Alpha Pod current state:

- good:
  - deterministic applicability gate for Financials / REITs
  - sector-based exit metric policy
- partial:
  - limited explicit gating for cyclicals, hyper-growth, negative-margin firms, or structurally asset-heavy models
  - no explicit "model confidence tier" output

### 3.2 Historical base and normalization

A strong process should build from a normalized base, not blindly from raw TTM figures.
That usually means understanding:

- revenue seasonality or cyclicality
- EBIT / EBITDA normalization
- one-offs and accounting noise
- working-capital distortions
- lease and pension effects
- dilution and capital-allocation behavior

Alpha Pod current state:

- good:
  - uses multi-year averages where available
  - bounded tax logic
  - some bridge-item support
- partial:
  - no first-class deterministic normalization framework for EBIT / EBITDA
  - QoE exists, but mainly downstream and optional
  - cyclical "normalized earnings" treatment is still weak
  - historical analysis is still too thin relative to what a strong normalized base requires:
    - no first-class multi-year statement pack exposed as a valuation artifact
    - no dedicated rolling historical-analysis layer
    - no common-size statement framework versus peers
    - no full historical ratio pack
    - weak explicit balance-sheet build and forecast handoff
    - no first-class historical revenue-driver identification step

### 3.3 Forecast value drivers

Best-practice valuation emphasizes that cash flow value is driven jointly by:

- growth
- operating profitability
- reinvestment intensity
- return on invested capital
- cost of capital

The key implication is that growth should not be modeled in isolation.
Growth requires reinvestment, and value is created only when returns exceed the cost of capital.

Alpha Pod current state:

- good:
  - explicit growth, margin, tax, capex, D&A, and working-capital driver set
  - `invested_capital_start`, `ronic_terminal`, EP cross-check, and terminal diagnostics exist
- partial:
  - reinvestment logic is present but not yet the organizing mental model of the stack
  - invested-capital sourcing is still partially heuristic
  - `cogs_pct_of_revenue` remains weakly sourced
  - the forecast-driver framework still needs a stronger bridge from:
    - company analysis
    - historical driver identification
    - industry analysis
    - macro-aware demand context
  - the stack still does not make revenue-driver identification a first-class historical-analysis output that then flows into forecast design

### 3.4 Cost of capital

Best-practice expectations:

- explicit capital-structure assumptions
- transparent peer beta / relevering logic
- discount-rate consistency with the forecast cash flow
- clarity on when WACC vs cost of equity is the right discount rate

Alpha Pod current state:

- good:
  - transparent WACC methodology set
  - bottom-up beta logic exists
  - FCFE and EP cross-checks are present
- partial:
  - debt-cost and capital-structure assumptions are still somewhat coarse
  - no formal "WACC confidence" or "discount-rate quality" diagnostic
  - capital structure is still treated too statically relative to the forecast path:
    - if growth requires new funding, that should eventually be visible in the funding-path logic, capital-structure evolution, and discount-rate narrative

### 3.5 Terminal value

Best-practice guidance is clear that terminal value should be economically plausible, not just mechanically computed.
That requires:

- stable growth consistent with macro limits
- reinvestment consistent with the assumed growth
- ROIC / RONIC consistency
- no casual dependence on a single exit multiple

Alpha Pod current state:

- good:
  - Gordon + exit + blend structure
  - terminal guardrails
  - `tv_pct_of_ev` and EP reconciliation
- partial:
  - exit-multiple dependence is still very significant for many use cases
  - stable-growth economics are not yet surfaced as the dominant valuation narrative in docs and exports
  - richer terminal stress work is still missing:
    - future hardening should include distribution-style exploration of exit scenarios, potentially including Monte Carlo-style terminal analysis where that adds decision value

### 3.6 Comparable-company valuation

Strong comps methodology should:

- choose peers with similar growth, risk, and economics, not only industry labels
- prefer forward-looking multiples when the forecast anchor is forward-looking
- use enterprise multiples for enterprise claims and equity multiples for equity claims
- adjust for business-model, margin, capital-intensity, and leverage differences

Alpha Pod current state:

- good:
  - forward vs LTM precedence is explicit
  - enterprise-value and equity-value multiples are kept distinct
  - richer `comps_analysis` payload exists
- partial:
  - peer selection quality is still dependent on upstream CIQ workbook curation
  - similarity logic is still not rich enough on business description / model quality
  - EBITDA / EBIT / EPS coverage and bridge consistency still need hardening
  - peer selection should become more explainable and business-description-aware rather than leaning mostly on upstream peer curation

### 3.7 Reverse DCF and implied expectations

Strong public-equity process should not stop at "our IV."
It should also answer:

- what growth / margin / capital assumptions are implied by the market price?
- where does the market's expectation differ from our normalized thesis?

Alpha Pod current state:

- good:
  - reverse DCF exists and is deterministic
- partial:
  - reverse DCF currently solves only one dimension cleanly: near-term growth
  - there is no broader implied-expectations framework across growth, margins, or reinvestment
  - reverse DCF should eventually support multiple implied-expectation views based on the PM's question, not only one implied growth output
  - one-variable-isolation analysis should become a first-class output so the PM can see which assumptions matter most and decide where deeper research or specialized LLM investigation is justified

### 3.8 Sensitivity and scenario design

Best-practice sensitivity design should stress:

- discount rate
- terminal growth
- exit multiple
- near-term growth
- margin path
- capital intensity / working-capital intensity

Alpha Pod current state:

- good:
  - probabilistic bear/base/bull engine
  - WACC vs growth and WACC vs multiple export grids
- partial:
  - sensitivity dimensions are still narrower than the real driver set
  - scenario probabilities are generic rather than thesis-specific or sector-specific
  - scenarios are still too generic relative to:
    - company size and maturity
    - business-cycle position
    - industry structure
    - historical profile and operating leverage

## 4. What Alpha Pod Already Does Well

The current deterministic process is stronger than a "simple retail DCF" in several ways:

- explicit deterministic boundary between valuation and LLM judgment
- typed driver object instead of ad hoc spreadsheet logic
- source lineage for many assumptions
- WACC methodology transparency
- EP and FCFE cross-check support
- terminal-value diagnostics
- comparable-company model with outlier handling and similarity weighting
- export-aware orchestration rather than a terminal-only CLI

These are real strengths and should be preserved during follow-on work.

## 5. Gap Register

### P0 Gaps: Highest impact on model quality or contract design

| Gap | Why it matters | Type |
| --- | --- | --- |
| Invested capital and reinvestment sourcing remain partially heuristic | weakens ROIC / EP / value-driver integrity | model + data |
| Historical operating series are still too thin on the CIQ side | blocks stronger dossier/API/Excel history surfaces and auditability | CIQ retrieval |
| Non-equity claims and bridge items are not fully CIQ-backed | weakens EV-to-equity rigor | CIQ retrieval + model |
| QoE / normalized operating metrics are not part of the canonical valuation contract | normalized economics are important but only partly structured today | contract + model |
| Comps peer-quality logic remains upstream-manual and only partly explainable | weakens confidence in relative valuation outputs | model + data |

### P1 Gaps: Important, but not immediate blockers

| Gap | Why it matters | Type |
| --- | --- | --- |
| `cogs_pct_of_revenue` is weakly sourced | inventory / payables forecasting quality is capped | CIQ retrieval + model |
| Reverse DCF is too one-dimensional | implied-expectations analysis is underpowered | model |
| Sensitivity analysis does not yet cover margin or capital intensity | real model risk can hide outside current grids | model + export |
| Applicability / model-confidence tiering is thin | difficult to communicate when the model is less reliable | contract |

### P2 Gaps: Future hardening / broader roadmap

| Gap | Why it matters | Type |
| --- | --- | --- |
| Sector-specific alternative methods for Financials / REITs are excluded rather than explicitly roadmap-owned | future expansion clarity | future model |
| Executive / listing / identity metadata are not integrated into the valuation retrieval contract | Overview and dossier completeness | product contract |

## 6. CIQ-Focused Research Findings

### 6.1 CIQ should be the primary owner for company-specific valuation history

The current stack still leans on yfinance for important historical context.
For a more audit-ready valuation system, CIQ should become the preferred owner for:

- multi-period revenue
- EBIT / EBITDA
- capex
- D&A
- effective tax history
- shares outstanding history
- invested capital or its direct components

### 6.2 CIQ should support denominator quality, not only headline ratios

The current system has some ratios but still lacks the denominator support needed to trust them fully.
Research and retrieval requirements should include:

- COGS or close equivalent for DIO / DPO denominator logic
- direct working-capital account balances across periods
- operating lease and other financing obligation detail
- direct invested-capital components

### 6.3 CIQ comps should support explainability, not just outputs

The current comps stack has good output shaping but still needs stronger raw peer support:

- why each peer belongs
- what peer economics look like
- which metrics are usable / unusable for each peer
- how forward vs LTM coverage differs by peer

That means CIQ retrieval and storage should support:

- peer metadata
- business description or similarity support
- per-peer metric availability flags
- clearer target / peer lineage fields

## 7. Benchmark-To-Product Evidence Matrix

| Benchmark principle | Current Alpha Pod status | Main gap | Downstream implication |
| --- | --- | --- | --- |
| Growth must be tied to reinvestment and ROIC | partially present | invested-capital and reinvestment sourcing are weak | DCF confidence and API explanation gaps |
| Terminal value should be economically plausible, not just spreadsheet-valid | mostly present | stable-growth economics still under-emphasized in outputs | workbook / dossier narrative gap |
| Multiples require peers with similar fundamentals | partially present | peer quality remains weakly explainable | comps trust gap |
| EV-to-equity bridge must capture all material claims | partially present | bridge-item retrieval is incomplete | IV precision and audit gap |
| Normalized operating performance matters materially | partially present | QoE normalization is not a first-class contract | mismatch between research and valuation contracts |
| Sensitivity should stress the real major drivers | partially present | margin and reinvestment sensitivity thin | incomplete PM review surface |

## 8. Recommended GitHub Issue Breakdown

Recommended next implementation issues after this research tranche:

1. **Spike: Audit CIQ historical operating-field coverage against valuation driver requirements**
2. **Feature: Harden invested-capital and reinvestment sourcing in deterministic valuation inputs**
3. **Feature: Add canonical bridge-item contract for leases, pensions, minority interest, preferreds, options, and convertibles**
4. **Feature: Expand comps peer-detail contract with explainability and metric-availability flags**
5. **Feature: Define QoE / normalized operating metrics contract for dossier, JSON export, and workbook use**
6. **Feature: Expand sensitivity and implied-expectations outputs beyond current WACC / growth / multiple surfaces**
7. **Feature: Define canonical ticker dossier contract separating retrieved facts, deterministic drivers, outputs, and advisory enrichments**

## 9. Recommended Research-to-Implementation Sequence

1. Lock the canonical ticker dossier contract.
2. Audit CIQ schema coverage against that contract.
3. Harden invested capital, bridge items, and denominator support.
4. Improve comps input quality and explainability.
5. Promote QoE / normalization outputs into a cleaner downstream contract.
6. Expand sensitivity and implied-expectation surfaces.

## 10. Scope Boundary

This document does **not** recommend:

- moving LLM judgment into deterministic valuation
- broadening the current deterministic model to Financials or REITs in this tranche
- replacing DCF with a purely multiples-driven workflow
- treating Excel as the source of valuation truth

The goal is to improve the deterministic public-equity valuation stack, not to change its core architecture.
