# Valuation Methodology Critical Review And Action Plan

This memo replaces the earlier multi-doc methodology review pack.

The finance instincts in the current valuation canon are sound, but the review layer became too abstract. The next version should be smaller, more executable, and more tightly reconciled with the actual code.

## Verdict

The core direction is right:

- keep official valuation math deterministic
- use LLMs for interpretation, proposal generation, and challenge
- require PM approval before judgment changes official model inputs
- treat company analysis, historical analysis, forecasting, WACC, comps, and PM review as one connected workflow

The weak point is precision.

Several docs name the right artifacts, but do not define them tightly enough:

- `assumption_register`
- `analysis_to_forecast_handoff`
- `historical_to_forecast_handoff`
- `peer_universe_artifact`
- `wacc_policy_ladder`
- `pm_decision_queue`
- `override_register`

The immediate fix is not more meta-process. It is to specify the first contract and then let the remaining docs derive from that.

## What The Review Got Right

### The meta-doc layer was too large

The previous split across research program, stage review, checklist resolution, recommendations, and review packet was too much for a solo operator.

Going forward:

- keep this memo as the single methodology review and action plan
- keep the canonical finance pages under `docs/valuation/`
- use issues for execution tracking once the methodology is approved

### The contracts were under-specified

Markdown tables are useful for thinking, but not enough for implementation.

The first contract to specify is the `assumption_register`, because it is the bottleneck between:

- company analysis
- industry analysis
- historical analysis
- PM judgment
- deterministic valuation

### Accepted ranges need rules, not only PM discretion

The accepted-range concept is useful only if the default range rules are deterministic.

PM approval should override or widen a range, but it should not be the first source of the range.

### Existing code and methodology docs are not fully reconciled

The docs should explicitly bless, restrict, or remove existing implementation behavior.

Important examples:

- macro-regime scenario weights exist in `src/stage_02_valuation/regime_model.py`
- Beneish M-Score and Altman Z-Score exist in `src/stage_03_judgment/forensic_scores.py`
- terminal value already has value-driver logic in `src/stage_02_valuation/professional_dcf.py`
- WACC already computes multiple methods in `src/stage_02_valuation/wacc.py`

The docs need to reflect these instead of speaking as if they are future ideas.

## What The Review Overstated Or Needs Refinement

### Terminal value is not purely qualitative in code

The review is right that the terminal-value doc should show the value-driver identity more explicitly.

But the implementation already computes a value-driver terminal FCFF path:

```text
reinvestment_rate_terminal = terminal_growth / ronic_terminal
fcff_11_value_driver = nopat_11 * (1 - reinvestment_rate_terminal)
tv_gordon = fcff_11_for_gordon / (wacc - terminal_growth)
```

The fix is documentation and validation clarity, not inventing the concept from scratch.

### WACC is not single-method only

The WACC module already exposes:

- `peer_bottom_up`
- `industry_proxy`
- `self_hamada`
- blended WACC results

The critique remains valid because the docs do not define enough policy around:

- ERP source and refresh cadence
- country and currency risk
- risk-free duration matching
- size-premium stance
- synthetic-rating spread curves
- method disagreement diagnostics

## P0 Fixes

### 1. Define the assumption register as an executable contract

The `assumption_register` should be the first real contract.

Draft Pydantic shape:

```python
from enum import Enum
from pydantic import BaseModel, Field


class AssumptionOwner(str, Enum):
    deterministic = "deterministic"
    llm_advisory = "llm_advisory"
    pm_approved = "pm_approved"
    blocked = "blocked"


class FlagLevel(str, Enum):
    none = "none"
    watch = "watch"
    review_required = "review_required"
    critical = "critical"


class EvidenceSource(str, Enum):
    ciq = "ciq"
    filing = "filing"
    market_data = "market_data"
    peer_universe = "peer_universe"
    industry_context = "industry_context"
    macro_context = "macro_context"
    pm_override = "pm_override"
    derived = "derived"


class AssumptionRegisterEntry(BaseModel):
    ticker: str
    assumption_name: str
    affected_forecast_lines: list[str]
    proposed_value: float
    accepted_low: float
    accepted_high: float
    range_rule_id: str
    range_rule_description: str
    evidence_sources: list[EvidenceSource]
    evidence_refs: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    valuation_impact: float | None = None
    flag_level: FlagLevel
    owner: AssumptionOwner
    approval_required: bool
    approval_state: str
    notes: str = ""
```

Minimum rule:

- if `proposed_value` falls outside `[accepted_low, accepted_high]`, `flag_level` must be at least `review_required`
- if valuation impact is high and confidence is low, `flag_level` must be `critical`
- `pm_override` can approve an out-of-range value, but it must preserve the original range and reason

### 2. Make accepted ranges deterministic by default

Default range rules should be metric-specific.

| Metric | Default accepted range rule |
| --- | --- |
| Revenue growth | trailing 5-year p25-p75, excluding distorted years, cross-checked against industry growth range |
| EBIT margin | trailing 5-year p25-p75, excluding distorted years, capped by peer p75 unless PM-approved |
| ROIC / RONIC | trailing 5-year p25-p75, excluding distorted years, cross-checked against peer and industry range |
| Capex / sales | trailing 5-year p25-p75, excluding M&A-distorted years, with minimum asset-maintenance floor |
| D&A / sales | trailing 5-year p25-p75, tied to PP&E / intangible roll-forward |
| Working-capital days | trailing 5-year p25-p75 by DSO / DIO / DPO, excluding shock years |
| Tax rate | normalized cash-tax or adjusted ETR range, excluding discrete tax items |
| WACC | method-set p25-p75 across approved methods, plus floor / ceiling from market context |
| Terminal growth | bounded by long-run nominal growth and industry maturity |
| Terminal margin | mature peer range plus company-specific quality adjustment |

PM judgment should be visible as an override, not hidden inside the range definition.

### 3. Reconcile macro-regime scenario weights with the canon

`regime_model.py` applies scenario weights:

- Risk-On: 10 / 55 / 35
- Neutral: 20 / 60 / 20
- Risk-Off: 35 / 55 / 10

This is a deterministic adjustment to scenario probabilities.

The canon must decide one of three policies:

1. approve regime weights as a deterministic overlay with source and confidence labels
2. make regime weights advisory until PM-approved
3. remove them from official valuation weighting

Recommended policy:

- regime detection may adjust displayed scenario context
- official valuation probability weights should show both unadjusted and regime-adjusted views
- the PM decision queue should flag when regime weighting materially changes expected IV

### 4. Add forensic scores to QoE canon

`forensic_scores.py` and `qoe_signals.py` already compute and expose:

- Beneish M-Score
- Altman Z-Score
- combined forensic flag

The QoE page should explicitly treat these as deterministic QoE signals.

Recommended policy:

- forensic scores do not automatically change EBIT, WACC, or valuation
- forensic red / amber flags feed PM review and confidence scoring
- severe forensic flags can require approval before normalized earnings are trusted

### 5. Tighten WACC policy

WACC should keep the existing methodology set, but add policy around it.

Required additions:

- ERP source hierarchy:
  - current implied ERP where available
  - documented fallback ERP
  - historical ERP only as a disclosed fallback
- country and currency risk:
  - country risk premium required for non-US operating exposure when material
  - cash-flow currency and discount-rate currency must match
- risk-free rate:
  - duration-matched rate preferred
  - 10-year Treasury is a practical fallback for US-dollar long-duration cash flows
- size premium:
  - explicit stance required because empirical support is contested
  - if used, source and refresh cadence must be documented
- synthetic rating:
  - spread curve source and date must be recorded
  - interest coverage mapping must be explicit
- method disagreement:
  - if WACC methods differ beyond a threshold, flag for review

### 6. Make terminal value enforce the value-driver identity

The terminal-value doc should explicitly show:

```text
Terminal FCFF = NOPAT_1 * (1 - g / RONIC)
Terminal Value = Terminal FCFF / (WACC - g)
```

Required checks:

- `RONIC > g`
- `g <= long-run nominal growth cap`
- terminal margin is within mature peer / industry range unless PM-approved
- value-driver terminal FCFF and bridge terminal FCFF are reconciled

### 7. Make peer-universe construction concrete

The peer universe should be a shared upstream artifact, not only a comps input.

Minimum fields:

```python
class PeerCandidate(BaseModel):
    target_ticker: str
    peer_ticker: str
    sources: list[str]
    sector_match: bool
    industry_match: bool
    business_description_similarity: float = Field(ge=0.0, le=1.0)
    metric_similarity: float = Field(ge=0.0, le=1.0)
    size_similarity: float = Field(ge=0.0, le=1.0)
    growth_similarity: float = Field(ge=0.0, le=1.0)
    margin_similarity: float = Field(ge=0.0, le=1.0)
    capital_intensity_similarity: float = Field(ge=0.0, le=1.0)
    composite_score: float = Field(ge=0.0, le=1.0)
    inclusion_state: str
    inclusion_reason: str
    approval_state: str
```

Default scoring:

- business description similarity: 35%
- metric similarity: 35%
- industry / sector match: 15%
- size and maturity similarity: 15%

Thresholds:

- `>= 0.75`: core peer candidate
- `0.55-0.75`: peripheral peer candidate
- `< 0.55`: exclude unless PM-approved

### 8. Make forecast scoping deterministic

The current forecast-scoping matrix needs a rule.

Default scoring dimensions:

- disclosure quality
- historical stability
- profitability
- capital intensity
- cyclicality
- M&A distortion
- data coverage

Output:

- full driver model
- moderate driver model
- light model with stronger scenarios
- blocked / needs PM review

Rule:

- if data coverage is weak or history is distorted, do not default to a fuller model just because the company is important

## P1 Fixes

### Industry constraint pack

Industry analysis should define quantitative constraints.

Candidate indicators:

- peer growth distribution
- peer margin distribution
- peer capital intensity
- valuation multiple ranges
- capacity utilization where sector-relevant
- inventory days versus trend
- PMI / ISM for industrial cyclicality
- commodity prices for commodity-exposed sectors
- yield curve and credit spreads for rate-sensitive sectors
- FRED macro indicators already available through `src/stage_00_data/fred_client.py`

### Comps metric ladder

The comps page should distinguish:

- EV / Sales
- EV / gross profit
- EV / EBITDA
- EV / EBIT
- unlevered FCF yield
- equity FCF yield
- P / E

Rule:

- use enterprise metrics for operating enterprise value
- use equity metrics only when capital structure and per-share claims are central and comparable
- do not call all cash-flow multiples "FCF-based" without specifying FCFF, FCFE, or UFCF

For SaaS and similar businesses, the page should add:

- Rule of 40
- net revenue retention
- gross margin
- Magic Number / CAC payback where available
- growth-adjusted revenue multiple context

### PM decision queue

The PM review object should be built during the workflow.

Minimum fields:

- decision_id
- stage
- decision_text
- affected_assumptions
- confidence
- valuation_impact
- flag_level
- recommendation
- PM decision
- reason
- timestamp

High-impact / low-confidence items should be surfaced first.

## Source Additions

Add these to the research basis:

- CFA Institute / Pinto equity valuation readings, especially free cash flow valuation and market-based valuation
- Damodaran, *Narrative and Numbers*, for qualitative-to-quantitative translation
- Damodaran implied ERP data, country risk data, synthetic-rating spreads, and lifecycle valuation materials
- Koller / Goedhart / Wessels value-driver framing from McKinsey Valuation

Useful source entry points:

- Damodaran current data page: `https://pages.stern.nyu.edu/adamodar/New_Home_Page/datacurrent.html`
- Damodaran historical implied ERP page: `https://pages.stern.nyu.edu/~adamodar/New_Home_Page/datafile/histimpl.html`
- Damodaran country risk premium page: `https://pages.stern.nyu.edu/adamodar/New_Home_Page/datafile/ctryprem.html`
- Damodaran synthetic ratings and default spreads: `https://pages.stern.nyu.edu/~adamodar/New_Home_Page/datafile/ratings.html`
- Damodaran country-risk methodology note: `https://pages.stern.nyu.edu/~adamodar/New_Home_Page/valquestions/CountryRisk.htm`
- McKinsey valuation explainer on growth and return on capital: `https://www.mckinsey.com/featured-insights/mckinsey-explainers/how-are-companies-valued`
- Wiley / CFA Institute Equity Asset Valuation page: `https://www.wiley-vch.de/en/areas-interest/finance-economics-law/finance-investments-13fi/investments-securities-13fi3/equity-asset-valuation-978-1-119-62810-1`

## Next Coding PR Scope

Do not create seven more specification docs.
The docs are now specific enough to start implementing the first contract layer.

The next coding PR should ship:

1. `src/contracts/assumption_register.py`
   - executable `AssumptionRegisterEntry`
   - accepted-range validation
   - PM override preservation
   - one round-trippable JSON example
2. `src/contracts/peer_universe.py`
   - executable `PeerCandidate`
   - composite scoring
   - text / metric floor guards
   - inclusion-state validation
3. Contract tests under `tests/contracts/`
   - JSON round-trip
   - out-of-range assumption flagging
   - PM override handling
   - peer scoring edge cases

The remaining items should become follow-on implementation issues only after these two contracts exist:

- WACC evidence ladder and method-disagreement flags
- terminal value-driver reconciliation output
- QoE forensic and reclassification decision queue
- macro-regime weighting display versus official valuation policy
- forecast scoping scorecard
