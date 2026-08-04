# Deterministic Vs LLM Boundary

> **Amended 2026-07-24 — read this before the rest of the page.**
> This page predates [Vision Decision 13](../strategy/vision.md#the-division-of-labor) and its
> original wording ("LLM outputs are advisory by default", an ownership map giving the judgment
> layer only summarisation and interpretation) caused agents to build the wrong thing.
>
> The corrected position: **the judgment layer authors the forward-looking assumptions**, reasoning
> over filings, management guidance, and history. It proposes; the PM approves; the deterministic
> layer then executes reproducibly. "Advisory" here has always meant *"cannot mutate the model
> without approval"* — a **routing** rule. It must not be read as *"optional colour on a model
> whose numbers come from sector constants."*
>
> The reproducibility rules on this page (Rules 1, 3, 4, 5) are correct and unchanged.

## Purpose

This page makes the valuation ownership boundary explicit.

It exists to answer one structural question:

- what should be computed deterministically
- what should be interpreted with LLM help
- what still belongs to human investment judgment

This boundary is one of Alpha Pod's core design principles.

## Why The Boundary Matters

Without a clear boundary:

- auditability disappears
- model trust degrades
- it becomes harder to explain why a number changed
- the system becomes vulnerable to silent narrative drift

With a clear boundary:

- numeric outputs remain reproducible
- judgment remains visible and reviewable
- PM overrides stay explicit
- the system can benefit from LLM help without losing control of the model

## Deterministic Responsibilities

The deterministic layer should own:

- statement assembly
- common-size statements
- ratio packs
- historical metrics
- DCF math
- WACC math
- comps calculations
- bridge-item calculations where structured data exists
- sensitivities and reverse DCF
- source lineage
- deterministic validation and diagnostics

These outputs must be reproducible, inspectable, and testable.

## Judgment-Layer Responsibilities

The judgment layer's primary job is **authoring the forward-looking assumptions**:

- target EBIT margin and the margin path
- mid-term and terminal revenue growth
- terminal reinvestment — the capex/D&A relationship in steady state
- working-capital targets where the sector default does not describe this business
- the qualitative business assessment (moat, pricing power, cyclicality, capital intensity)
  that drives those numbers

Each of these is a *thesis about this specific company*, derived from filings, management
guidance, disclosed capital programs, competitive position, and history — with a named evidence
basis. A sector constant in one of these slots is a placeholder for missing judgment, not an
answer. See [Core Belief 3](../design-docs/core-beliefs.md).

It also does the supporting interpretive work it always did:

- classification of ambiguous reported items for valuation
- historical normalization, reclassification, and recast proposals
- proposals for financially necessary model structures that do not exist yet
- filing summaries
- business-model summaries
- industry context synthesis
- QoE narrative
- business-description-based peer analysis
- suggested normalization items
- stress-test interpretation
- explanation of why a result may be fragile or why a driver changed

**All of it — authored assumptions included — reaches the model only through the PM Decision
Queue.** That is the routing constraint, not a statement that the output is optional.

## Human / PM Responsibilities

The PM should retain authority for:

- choosing representative periods
- deciding what to normalize
- deciding which drivers matter most
- deciding whether a peer set is credible
- approving overrides
- deciding whether the model is investable
- making the final investment decision

## Boundary Rules

### Rule 1: Deterministic outputs are the official reproducible result

The deterministic layer preserves the reported baseline and computes the official model result
from the fixed, PM-approved assumption and treatment set. This does not mean the unadjusted
reported classification is always the correct analytical treatment.

### Rule 2: Judgment-layer outputs are proposals, never direct writes

Judgment-layer outputs can:

- author a forward-looking assumption, with an evidence basis
- summarize
- explain
- suggest
- challenge

They must never silently mutate the model — every one of them lands as a PM Decision Queue item
first.

Note the distinction this rule is making. "Proposal, not direct write" is about **how a number
travels**, not about how much it is worth. An agent-authored margin target with a cited evidence
basis is the *intended* source for that driver; it simply has to arrive via the queue. Reading
this rule as "the LLM only comments while sector defaults set the model" inverts the design.

### Rule 3: Any judgment-layer change to the model must pass through an explicit approval path

If an LLM suggests:

- a normalized EBIT value
- a historical recast or accounting classification
- a different peer set
- a changed growth assumption
- a different bridge-item treatment
- a new schedule, bridge component, or model structure

the PM must explicitly approve it before it enters the deterministic flow.

### Rule 4: Provenance must survive the handoff

The system should preserve:

- where the original number came from
- what the LLM suggested
- whether the PM approved the suggestion
- what the final deterministic number is

### Rule 5: The boundary should be visible in the docs and product

Users should be able to tell whether a field is:

- retrieved fact
- deterministic derived metric
- LLM-augmented advisory output
- PM-approved override

Worked example:

- Beneish M-Score and Altman Z-Score are deterministic QoE signals.
- They may reduce confidence, trigger PM review, or feed the normalization decision queue.
- They must not automatically change EBIT, WACC, FCF, or valuation.
- Any model mutation from a forensic concern still requires a separate PM-approved override.

## Recommended Ownership Map

| Task | Default owner |
| --- | --- |
| Reported historical statements, ratios, and the unadjusted baseline | deterministic |
| Analytical classification, normalization, and historical recast proposals | judgment layer, PM-approved |
| Forecast *mechanics* and DCF math — executing a given assumption set | deterministic |
| Marshalling the relevant evidence for a specific driver question | deterministic |
| **Forward-looking driver values (`*_target`, terminal growth, terminal reinvestment)** | **judgment layer, PM-approved** |
| **Qualitative business assessment that drives those values** | **judgment layer, PM-approved** |
| Business description and filing interpretation | judgment layer |
| Industry theme synthesis | judgment layer |
| QoE signal computation | deterministic |
| QoE adjustment suggestions | judgment layer |
| Approving, editing, or rejecting any proposed assumption | human / PM |
| Final investment decision | human / PM |

## Recommended Artifact Set

| Artifact | Purpose | Owner |
| --- | --- | --- |
| Source lineage table | shows where deterministic inputs came from | deterministic |
| Advisory note set | stores LLM summaries and suggestions | LLM-augmented |
| Override register | records approved changes to deterministic assumptions | deterministic, PM-approved |
| Treatment register | records approved classifications, recasts, evidence, rationale, and supersession | deterministic persistence, PM-approved |
| Boundary label map | shows what each output field represents | deterministic |

## Current Implementation Notes

This boundary already exists architecturally in Alpha Pod.
The main documentation goal is to make that boundary visible and consistent across the finance methodology set and the downstream product contracts.

Current implementation state (2026-07-25):

- focused accounting evidence now crosses the selector → validator → ledger → PM Queue seam
- unsupported but sound treatments can become explicit model-change advisories instead of being
  forced into an existing driver field
- approved treatments have a durable, superseding `treatment_decisions` register
- the first cache-only MSFT trial produced queue item 133; it did not mutate the DCF
- production LLM dispatch, business/industry context injection, and applying approved structural
  model changes remain incomplete

## Practical Review Questions For The PM

1. Which numbers here are deterministic?
2. Which conclusions are advisory?
3. Which changes require my approval before they affect the model?
4. Can I explain why a number changed from one run to the next?
