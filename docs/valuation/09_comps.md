# Comparable Company Analysis

## Purpose

Comps are not a shortcut around understanding the business.
They are a second valuation lens that should confirm, challenge, or contextualize the DCF.

Their job is to answer:

- what similar businesses are worth in the market
- whether the DCF result looks directionally credible
- whether the market is rewarding or punishing specific business qualities
- whether the target company deserves to trade above, near, or below relevant peers

## Why This Matters For Valuation

Comps are especially useful when:

- terminal assumptions are fragile
- market expectations matter for timing and framing
- the company is strongly shaped by peer-relative narratives
- the DCF needs a market-based cross-check

But comps only help when the peer set and metric choice are credible.
Bad comps are often worse than no comps because they import false precision.

## Ownership Model

### Deterministic

The deterministic layer should own:

- multiple calculations
- peer metric tables
- outlier handling
- target-versus-peer metric comparisons
- explainability flags where structured

### LLM-augmented

LLMs are useful for:

- business-description comparison
- qualitative peer relevance reasoning
- explaining why a multiple may or may not be appropriate
- surfacing important business-model differences that the numeric screen misses

### Human / PM Judgment

PM judgment is required to decide:

- whether the peer set is credible
- which metrics deserve the most weight
- whether comps should override, frame, or merely sanity-check the DCF

### Hard Boundary

LLM reasoning may help explain peer selection, but the deterministic peer table and multiple math should remain authoritative for official outputs.

## Full Workflow

## 1. Define what "comparable" should mean

Peer selection should begin with economic comparability, not only industry labels.

Relevant dimensions:

- business model
- revenue model
- growth profile
- margin structure
- capital intensity
- leverage
- cyclicality
- market maturity

Questions to answer:

- Are these companies really monetizing similar economics?
- Do they operate under similar industry and cycle conditions?
- Would investors naturally compare them?

Best practice:

- start broad, then narrow based on economics
- treat industry classification as a starting point, not the answer

## 2. Build the peer set deliberately

Peer-set design should be explainable.

Questions to answer:

- Which peers are core comparables?
- Which peers are useful but imperfect reference points?
- Which names should be excluded despite surface similarity?

Best practice:

- distinguish core peers from peripheral peers
- record why each peer is included
- flag peers with incomplete metric coverage

Deterministic outputs:

- peer table
- inclusion / exclusion flags
- metric availability flags

LLM augmentation:

- compare business descriptions and strategic positioning across peers

PM judgment:

- approve the final peer set

## 3. Choose the right multiples

Metric choice should reflect the business model and capital structure.

Examples:

- EV / EBITDA
- EV / EBIT
- P / E
- FCF-based metrics
- revenue multiples where profitability is not yet meaningful

Questions to answer:

- Which metric best matches the target's economics?
- Is enterprise or equity framing more appropriate?
- Are current earnings distorted enough that forward multiples deserve priority?

Best practice:

- use metrics that match the target's business quality and capital structure
- avoid mechanically applying the same multiple across all sectors
- document when a metric is weak or misleading

Deterministic outputs:

- target and peer multiple table
- metric suitability table

## 4. Prefer forward-looking metrics when the thesis is forward-looking

Forward multiples often deserve precedence when:

- earnings are moving materially
- cyclicality is distorting LTM numbers
- the thesis is explicitly about where the business is going rather than where it just was

Best practice:

- match the multiple horizon to the thesis horizon
- keep forward and LTM views both visible when the difference matters

Deterministic outputs:

- forward and LTM comparison views
- precedence flags

## 5. Normalize for business-quality differences

Even good peers are rarely identical.
The analysis should explain why the target deserves a premium or discount.

Relevant differences:

- growth quality
- margin quality
- reinvestment burden
- returns on capital
- leverage
- cyclicality
- business-model durability

Best practice:

- do not assume the median is fair by default
- explain quality-based premium or discount reasoning

Deterministic outputs:

- target-versus-peer differential table

LLM augmentation:

- explain qualitative reasons the target may deserve a premium or discount

PM judgment:

- decide whether the market's relative pricing looks justified

## 6. Handle outliers and weak data carefully

Comps are especially vulnerable to false precision.

Questions to answer:

- Are some peers missing usable metrics?
- Are some metrics distorted by temporary losses, one-offs, or capital structure anomalies?
- Are extreme outliers telling the truth about the sector, or just contaminating the median?

Best practice:

- use robust outlier handling
- surface metric coverage explicitly
- treat poor data quality as a confidence issue

Deterministic outputs:

- outlier-filtered medians
- metric coverage flags
- peer-quality diagnostics

## 7. Turn comps into a valuation narrative

Comps should not end with a table.
They should answer:

- where the target screens versus peers
- what the market appears to reward
- whether the target is priced for better or worse economics than the peer group
- whether the relative valuation supports or challenges the DCF

## Recommended Artifact Set

| Artifact | Purpose | Owner |
| --- | --- | --- |
| Peer selection note | explains why the chosen peers are relevant | mixed |
| Peer table | target and peer metrics | deterministic |
| Metric suitability table | explains which multiples matter and why | mixed |
| Multiple range summary | shows median, range, and filtered views | deterministic |
| Explainability and inclusion flags | shows peer quality and metric coverage | deterministic |
| Premium / discount note | explains why the target may deserve relative re-rating | PM-owned |

## What Should Feed Directly Into Valuation Review

The following belong in the deterministic review layer:

- peer multiple tables
- filtered medians
- implied valuation outputs
- metric coverage and outlier flags

The following should stay advisory until reviewed:

- LLM-generated peer-relevance arguments
- business-description-based premium / discount narratives

## Current Implementation Notes

Alpha Pod's comps engine is stronger than a simple median-table approach, but peer explainability and business-description-based similarity still need hardening.

Main gaps:

- peer selection is still too dependent on upstream CIQ curation
- business-description-based similarity is still thin
- metric suitability and peer-quality explanations are not yet first-class artifacts
- PM-facing premium / discount reasoning is still underdeveloped

## Practical Review Questions For The PM

1. Are these really the right peers?
2. Are the chosen multiples appropriate for this business?
3. Does the company deserve a premium or discount, and why?
4. Do comps support the DCF, challenge it, or point to a different framing?
