# Deterministic Vs LLM Boundary

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

## LLM-Augmented Responsibilities

LLMs are valuable for:

- filing summaries
- business-model summaries
- revenue-driver hypotheses
- industry context synthesis
- QoE narrative
- business-description-based peer analysis
- suggested normalization items
- stress-test interpretation
- explanation of why a result may be fragile or why a driver changed

These outputs may inform the PM, but they must remain advisory until explicitly approved through a deterministic transform or override path.

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

### Rule 1: Deterministic outputs are the official numeric truth

If the product needs an official number for ranking, export, or reproducible review, that number should come from the deterministic layer.

### Rule 2: LLM outputs are advisory by default

LLM outputs can:

- summarize
- explain
- suggest
- challenge

They should not silently mutate the model.

### Rule 3: Any judgment-layer change to the model must pass through an explicit approval path

If an LLM suggests:

- a normalized EBIT value
- a different peer set
- a changed growth assumption
- a different bridge-item treatment

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
| Historical statements and ratios | deterministic |
| Forecast mechanics and DCF math | deterministic |
| Business description and filing interpretation | LLM-augmented |
| Industry theme synthesis | LLM-augmented |
| QoE signal computation | deterministic |
| QoE adjustment suggestions | LLM-augmented |
| Override approval | human / PM |
| Final investment decision | human / PM |

## Recommended Artifact Set

| Artifact | Purpose | Owner |
| --- | --- | --- |
| Source lineage table | shows where deterministic inputs came from | deterministic |
| Advisory note set | stores LLM summaries and suggestions | LLM-augmented |
| Override register | records approved changes to deterministic assumptions | deterministic, PM-approved |
| Boundary label map | shows what each output field represents | deterministic |

## Current Implementation Notes

This boundary already exists architecturally in Alpha Pod.
The main documentation goal is to make that boundary visible and consistent across the finance methodology set and the downstream product contracts.

Main gaps:

- the boundary is still clearer in architecture docs than in product-facing valuation artifacts
- some future dossier and export fields still need explicit ownership labeling
- the PM override trail should become more visible in downstream review surfaces

## Practical Review Questions For The PM

1. Which numbers here are deterministic?
2. Which conclusions are advisory?
3. Which changes require my approval before they affect the model?
4. Can I explain why a number changed from one run to the next?
