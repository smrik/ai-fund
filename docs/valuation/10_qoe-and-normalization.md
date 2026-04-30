# QoE And Normalization

## Purpose

Before valuing a business, the analyst needs to ask whether reported earnings reflect the underlying economics well enough.

Quality of earnings and normalization work exist to answer:

- whether reported EBIT or EBITDA is trustworthy
- whether one-offs or accounting choices are distorting the operating picture
- whether bridge items are complete enough to trust the move from enterprise value to equity value

This area is where accounting detail and valuation judgment meet.

## Why This Matters For Valuation

A DCF can be directionally wrong even when the math is perfect if it starts from the wrong operating base.
QoE and normalization are what keep the deterministic model from treating noisy reported earnings as clean economics.

This matters especially for:

- normalized EBIT / EBITDA
- cash-conversion interpretation
- working-capital distortions
- bridge-item completeness
- capital structure and EV-to-equity precision

## Ownership Model

### Deterministic

The deterministic layer should own:

- numeric QoE signal computation
- accruals and cash-conversion metrics
- DSO / DIO / DPO drift
- bridge-item calculations where structured data exists
- data-quality and materiality flags

### LLM-augmented

LLMs are useful for:

- text-based normalization suggestions
- note and MD&A interpretation
- accounting classification suggestions
- explaining whether unusual items appear non-recurring

### Human / PM Judgment

PM judgment is required for:

- deciding what to normalize
- deciding whether a suggested override is material and appropriate
- deciding whether bridge-item uncertainty materially reduces valuation confidence

### Hard Boundary

No LLM output should directly change deterministic valuation inputs.
Any proposed normalization that affects the model must remain an explicit override decision.

## Full Workflow

## 1. Start with deterministic signals

QoE should begin with a structured signal layer that can run consistently across names.

Useful signal categories:

- accruals
- cash conversion
- forensic scores such as Beneish M-Score and Altman Z-Score
- DSO / DIO / DPO drift
- capex versus D&A
- leverage and bridge-item completeness
- dilution and acquisition dependence

Best practice:

- let deterministic signals identify where the accounting deserves scrutiny
- do not begin with narrative adjustment hunting

Deterministic outputs:

- QoE signal pack
- forensic score pack
- traffic-light or severity flags
- bridge-item completeness flags

Forensic-score policy:

- Beneish M-Score and Altman Z-Score are deterministic risk signals, not automatic valuation adjustments
- red or amber forensic flags should reduce confidence and enter the PM decision queue
- severe forensic flags should require approval before normalized EBIT, EBITDA, or FCF is used as the official anchor
- score inputs, missing-data fallbacks, and year coverage should be visible in the QoE artifact

## 2. Identify normalization candidates

Once the signal layer points to areas of concern, the next step is to identify whether reported EBIT or EBITDA should be adjusted.

Possible candidates:

- restructuring charges
- litigation items
- gains or losses on asset sales
- acquisition-related costs
- impairments
- unusual stock compensation or retention grants
- working-capital movements that flatter or depress near-term cash conversion

Best practice:

- treat normalization as a proposal, not a default
- keep the itemized rationale visible

Deterministic outputs:

- structured candidate list where signals support it

LLM augmentation:

- extract candidate items and rationale from filings

PM judgment:

- decide what is truly non-recurring

## 3. Recast operating earnings for valuation use

The analyst needs a view on what EBIT or EBITDA should mean for valuation purposes.

Questions to answer:

- Is reported EBIT a good operating anchor?
- Should certain items be added back or excluded?
- Are the proposed adjustments large enough to affect intrinsic value materially?

Best practice:

- keep reported and normalized views both visible
- do not lose the reported baseline
- document every adjustment with source and rationale

Deterministic outputs:

- reported-versus-normalized comparison block

LLM augmentation:

- item-level normalization suggestions
- signal explanations

PM judgment:

- approve or reject the normalization

## 4. Review bridge items and accounting reclassification

Normalization is not only about EBIT.
It also affects the quality of the EV-to-equity bridge.

Relevant items:

- leases
- pensions
- minority interest
- preferred equity
- options and convertibles
- non-operating assets

Best practice:

- separate operating performance normalization from bridge completeness
- treat missing bridge items as valuation-confidence issues

Deterministic outputs:

- bridge-item table
- completeness and fallback flags

LLM augmentation:

- suggest classification edge cases from notes

PM judgment:

- decide whether bridge uncertainty materially weakens the valuation

## 5. Control how normalization reaches the model

The workflow should end with a controlled override gate.

Questions to answer:

- Is the difference between reported and normalized EBIT material?
- Is the evidence strong enough to justify an override?
- Has the PM explicitly approved it?

Best practice:

- never auto-write LLM adjustments into the deterministic model
- preserve the full approval trail

Deterministic outputs:

- approved override record
- default use of reported numbers unless an override is approved

## Recommended Artifact Set

| Artifact | Purpose | Owner |
| --- | --- | --- |
| Deterministic QoE signal pack | identifies where accounting quality needs review | deterministic |
| Forensic score pack | records Beneish, Altman, and related deterministic accounting-risk signals | deterministic |
| Normalization candidate list | records proposed adjustments | mixed |
| Accounting recast note | explains classification and valuation-use treatment | mixed |
| Bridge-item completeness table | shows which claims are captured and how well | deterministic |
| Approved override record | preserves PM-approved model changes | deterministic, PM-approved |

## What Should Feed Directly Into Valuation

The following should feed the deterministic review layer directly:

- QoE signal pack
- bridge-item calculations
- completeness and confidence flags

The following should stay advisory until approved:

- text-based normalization suggestions
- classification suggestions
- proposed EBIT overrides

## Current Implementation Notes

Alpha Pod already has a strong QoE boundary concept and a good split between deterministic signals and judgment-layer interpretation.
The main future task is to make normalization outputs first-class in the valuation contract without letting judgment-layer work silently mutate the deterministic model.

Main gaps:

- normalization outputs are not yet a first-class dossier contract
- bridge-item completeness is still partly heuristic
- PM-facing adjustment review artifacts should become more explicit

## Practical Review Questions For The PM

1. Is reported EBIT trustworthy enough to value directly?
2. Which adjustments are truly non-recurring versus recurring under a different label?
3. Are bridge items complete enough to trust the equity value?
4. Is any proposed normalization material enough to justify an override?
