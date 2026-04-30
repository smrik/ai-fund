# Sensitivity, Scenarios, And Reverse DCF

## Purpose

A valuation is not useful unless it can be challenged.
Sensitivity analysis, scenario analysis, and reverse DCF are the main tools for that challenge.

Their job is not to make the model look sophisticated.
Their job is to show:

- which assumptions matter most
- what range of outcomes is plausible
- what the market is already pricing in
- where the thesis is most fragile

## Ownership Model

### Deterministic

The deterministic layer should own:

- sensitivity math
- scenario reruns
- reverse DCF solving
- driver ranking by modeled impact

### LLM-augmented

LLMs are useful for:

- explaining which stressed cases feel economically plausible
- connecting stressed cases to filing or industry narratives
- helping describe what operationally differentiates scenarios

### Human / PM Judgment

PM judgment is required to decide:

- which scenarios matter
- which sensitivities deserve the most attention
- whether the implied expectations are believable enough to underwrite against

### Hard Boundary

The numeric engine should remain deterministic.
LLM narrative can help interpret the stress outputs, but should not define the math without explicit approval.

## Full Workflow

## 1. Start with the critical assumptions

Sensitivity and scenario work should begin by identifying the assumptions that actually drive value.

Typical high-impact assumptions:

- WACC
- terminal growth
- exit multiple
- near-term growth
- margin path
- capital intensity
- working-capital intensity

Best practice:

- focus on the few assumptions that matter most
- do not build giant grids that hide what is actually important

## 2. Run one-variable sensitivities

Sensitivity analysis should isolate individual assumptions to show direct valuation impact.

Questions to answer:

- Which single variable matters most?
- Which assumptions are low-confidence but high-impact?
- Which assumptions barely matter and can be deprioritized?

Best practice:

- isolate one variable at a time
- keep ranges realistic and interpretable
- use this to guide PM attention

Deterministic outputs:

- sensitivity tables
- one-variable impact ranking

## 3. Build coherent multi-variable scenarios

Scenarios should reflect real business alternatives, not only generic arithmetic shocks.

Useful scenario differences might include:

- cyclical downturn versus soft landing
- execution success versus stalled growth
- pricing power versus competitive margin pressure
- funding stress versus self-funded growth

Best practice:

- move the assumptions that should move together
- define scenarios in business language first, then map to numbers
- keep bear / base / bull tied to company size, maturity, cycle, and industry structure

Deterministic outputs:

- scenario valuation outputs
- scenario assumption packs

### Macro-Regime Overlay

Alpha Pod already computes macro-regime scenario weights in `src/stage_02_valuation/regime_model.py`.
The canonical policy is to show regime-adjusted weights as an alternative view, not to silently replace the unadjusted valuation.

Current regime-weight sets:

| Regime | Bear | Base | Bull |
| --- | ---: | ---: | ---: |
| Risk-On | 10% | 55% | 35% |
| Neutral | 20% | 60% | 20% |
| Risk-Off | 35% | 55% | 10% |

Policy:

- the unadjusted scenario-weighted intrinsic value remains the official base view unless PM-approved
- the regime-adjusted view should be displayed beside it with source and timestamp
- if regime weighting changes expected intrinsic value by more than 5%, the PM decision queue should flag it
- PM approval is required before regime weights change official valuation outputs, sizing, or exported model assumptions

LLM augmentation:

- help articulate the operational meaning of each scenario

PM judgment:

- decide whether the scenarios are worth caring about

## 4. Use reverse DCF to understand implied expectations

Reverse DCF shifts the question from "what is our intrinsic value?" to "what is the market assuming must happen?"

Useful reverse questions:

- what growth is implied?
- what margin path is implied?
- what reinvestment burden is implied?
- which single assumption must be true for the current price to make sense?

Best practice:

- use reverse DCF to identify the core disagreement with the market
- do not stop at only one implied variable forever
- connect implied expectations back to business and industry realities

Deterministic outputs:

- implied growth outputs
- future implied-expectations outputs where added

LLM augmentation:

- explain whether the implied assumptions sound plausible in business terms

PM judgment:

- decide whether the market is embedding a believable or vulnerable story

## 5. Turn stress testing into a PM review surface

Stress testing should not just be saved as output tables.
It should shape the review process.

Questions to answer:

- Which assumption is most dangerous to get wrong?
- Which assumption deserves more research?
- Which stress case most resembles the real downside?
- Which scenario would actually change sizing or position direction?

Best practice:

- make stress work decision-oriented
- use it to prioritize research follow-up

## Recommended Artifact Set

| Artifact | Purpose | Owner |
| --- | --- | --- |
| Sensitivity tables | isolate single-assumption effects | deterministic |
| Scenario pack | shows coherent bear / base / bull alternatives | deterministic |
| Reverse DCF outputs | shows what the market is implying | deterministic |
| One-variable-isolation analysis | ranks critical assumptions by impact | deterministic |
| PM critical-driver shortlist | identifies what deserves most scrutiny | PM-owned |

## What Should Feed Directly Into Valuation Review

The following should feed the deterministic review layer directly:

- sensitivity outputs
- scenario outputs
- reverse DCF outputs
- driver impact rankings

The following should stay advisory until reviewed:

- LLM-generated views on what scenarios feel most plausible
- suggested scenario narratives that imply assumption changes without approval

## Current Implementation Notes

Alpha Pod already has deterministic scenarios and reverse DCF.
The next step is to make them more company-aware and more decision-oriented.

Main gaps:

- scenario framing is still more generic than company-specific
- sensitivity dimensions are still narrower than the full driver set
- reverse DCF is still too one-dimensional
- PM-facing driver-priority output is still thin

## Practical Review Questions For The PM

1. Which assumptions matter most to value?
2. Which of those assumptions are least observable?
3. What does the market need to believe for the current price to make sense?
4. Which stress case would actually change the investment decision?
