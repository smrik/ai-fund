# PM Review Framework

## Purpose

This page turns valuation output into a PM decision process.

Its job is to answer:

- whether the name is understandable enough to underwrite
- whether the valuation is supported by evidence rather than defaults
- where the thesis is fragile
- what still needs more work before capital should be committed

## Why This Matters

A good model is not the same thing as a good investment decision.
The PM review layer exists to connect:

- company understanding
- historical evidence
- forecast quality
- valuation outputs
- market expectations
- decision quality

## Review Order

1. understand the business
2. understand the industry and cycle
3. inspect the historical record
4. inspect forecast drivers
5. challenge DCF fragility
6. compare against comps
7. review QoE and normalization flags
8. decide whether the setup is good enough to underwrite

## Core PM Questions

- What must be true for this valuation to work?
- Which assumptions matter most?
- Which assumptions are evidence-backed versus default-driven?
- Where is the thesis most fragile?
- Is the market already pricing the obvious version of the story?
- What still feels unresolved enough to block conviction?

## Decision States

- reject
- watchlist
- promote to deep research
- actionable

These states should reflect decision readiness, not only attractiveness.

## Ownership Model

### Deterministic

The deterministic layer should provide:

- ranking outputs
- diagnostics
- base / bear / bull math
- reverse DCF outputs
- source lineage
- fragility flags

### LLM-augmented

LLMs can help with:

- pushback arguments
- filing and QoE summaries
- stress narratives
- explanation of where the story may be weak

### Human / PM Judgment

Only the PM can decide:

- conviction
- sizing
- go / no-go
- whether more research is required before action

## Full Workflow

## 1. Confirm the business is understandable

Questions to answer:

- Do we actually understand how the company makes money?
- Are the main drivers clear enough to forecast?
- Is this a business the current valuation framework can handle?

If not, stop early.
This is a legitimate output.

## 2. Check whether the history supports the story

Questions to answer:

- Do the historical statements support the business narrative?
- Are margins, cash conversion, and capital intensity coherent with the stated thesis?
- Which years are representative and which are distorted?

The PM should know whether the forecast is anchored in a credible base.

## 3. Inspect the assumptions before the output

Questions to answer:

- Are growth, margin, tax, reinvestment, and discount-rate assumptions clearly sourced?
- How much of the model is using defaults?
- Which assumptions rely on weak coverage or heuristic fallbacks?

Best practice:

- never review the final IV before reviewing the assumptions that create it

## 4. Challenge the DCF result

Questions to answer:

- How much of value comes from the terminal period?
- Which assumptions carry the valuation?
- Does the EV-to-equity bridge look complete?
- Are the scenarios decision-useful?

The PM should not only ask "what is IV?" but also "what has to be true for IV to matter?"

## 5. Use comps as a market reality check

Questions to answer:

- Does the company screen above or below peers for understandable reasons?
- Do comps support the DCF or raise a challenge?
- Is the company priced for better or worse economics than the peer group?

## 6. Review QoE and normalization risk

Questions to answer:

- Is reported EBIT trustworthy?
- Are there unresolved normalization candidates?
- Are bridge items complete enough to trust the equity value?

If QoE is weak, valuation confidence should drop even if upside looks large.

## 7. Decide whether more research is needed

Useful escalation questions:

- Which assumption is most dangerous to get wrong?
- Which input is too uncertain to accept without more work?
- Would another filing pass, a specialized agent, or a data audit materially improve confidence?

## Recommended Artifact Set

| Artifact | Purpose | Owner |
| --- | --- | --- |
| PM review checklist | structured decision flow | PM-owned |
| Valuation fragility summary | shows what could break the thesis | deterministic |
| Critical-driver shortlist | shows what matters most | deterministic + PM |
| Override review list | shows pending judgment calls | deterministic |
| Decision-state record | captures reject / watchlist / deep research / actionable | PM-owned |

## What Should Feed Directly Into PM Review

The following belong directly in the PM review surface:

- deterministic outputs and diagnostics
- source lineage
- sensitivity and reverse DCF results
- comps outputs
- QoE and normalization flags

The following should stay advisory:

- LLM pushback narratives
- thesis-stress summaries
- suggested research directions

## Current Implementation Notes

Alpha Pod already has much of the raw material needed for a strong PM review process, but it is still spread across valuation outputs, QoE outputs, and optional judgment-layer work.

Main gaps:

- no single PM review artifact yet
- no explicit decision-state object
- limited structured link between fragility diagnostics and next-step research

## Practical Review Questions For The PM

1. What has to go right for this name to work?
2. What is most fragile?
3. Is the upside real, or just a product of weak assumptions?
4. Is this ready for action, or does it need deeper research first?
