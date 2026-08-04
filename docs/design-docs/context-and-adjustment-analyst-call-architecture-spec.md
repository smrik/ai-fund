# Context And Adjustment Analyst Call Architecture Spec

> **Vision decisions served:** Decision 12 (learn through real weekly-loop usage), Decision 13
> (judgment authors forward assumptions), Decision 14 (business analysis precedes industry
> analysis, which precedes driver analysis), and the PM Decision Queue boundary.

## Problem Statement

Alpha Pod can assemble a reconciled historical model, but its judgment workflows currently mix two
incompatible designs. Older Agentic Handoff Profiles extract observations and let deterministic
translator rules choose conservative numeric deltas. Newer driver-family workflows correctly let
the judgment layer author low/base/high assumptions, but they ask one model call to perform
financial reasoning and satisfy a strict JSON schema at the same time.

The result is difficult to operate and audit. Broad qualitative analysis receives weak or stale
evidence projections, while numerically sensitive calls can fail because reasoning, formatting,
units, evidence anchoring, and schema compliance are coupled. A formatting error can look like an
analytical error, and a formatting model could silently change a number unless the system proves
that compilation was lossless.

The PM needs an MVP that runs on a real ticker now, exposes every model input and output, and lets
practice determine later hardening priorities. The immediate goal is therefore a robust,
inspectable call architecture rather than perfect MSFT analysis content.

## Solution

Split judgment work into two analyst types and split every numeric adjustment into distinct
reasoning and compilation stages.

1. **Context Analysts** make broad, evidence-anchored assessments. A Business Context Analyst runs
   first. An Industry Context Analyst then receives both industry evidence and the validated
   Business Context Report. Context Analysts may quote reported numbers and identify relevant
   drivers, but they do not author forecast values or create model-mutation proposals.
2. **Adjustment Reasoning Analysts** receive small, purpose-built evidence projections for one
   economically coherent Adjustment Micro-Family. They author the financial logic and explicitly
   declare low/base/high values, units, conditions, rationale, and evidence anchors.
3. A cheaper **Proposal Compiler** converts one Adjustment Reasoning Draft into the strict proposal
   JSON contract. It is a lossless compiler: it may not infer, calculate, repair, reinterpret, or
   change a value.
4. A deterministic **Proposal Verifier** proves that the compiled fields, values, units, and anchors
   match the reasoning draft and the allowed micro-family contract.
5. A **Critic Analyst** reviews the evidence, reasoning draft, and verified proposal. It accepts,
   requests one analytical revision, or blocks the proposal. It never edits values itself.
6. Only verified, critic-accepted proposals enter the PM Decision Queue. PM approval remains the
   only route to deterministic model mutation.

All model calls use the existing provider-neutral judgment gateway and durable Agent Run Envelope.
The packet header, run identity, source fingerprints, prompt/schema versions, raw response,
validated response, errors, model identity, timing, token usage, and cost metadata are common.
Role-specific projections and output contracts differ.

## User Stories

1. As the PM, I want business context analyzed before forecast values are proposed, so that model
   changes reflect an understanding of the company rather than isolated numbers.
2. As the PM, I want industry context to build on the validated business analysis, so that industry
   conclusions remain relevant to the specific company.
3. As the PM, I want context analysis to cover broad qualitative evidence, so that important themes
   are not excluded by a narrow driver prompt.
4. As the PM, I want context reports anchored to exact evidence, so that I can inspect why a claim
   was made.
5. As the PM, I want context analysts barred from directly setting forecast values, so that broad
   narrative calls cannot silently mutate the model.
6. As the PM, I want context claims to name relevant drivers or micro-families, so that downstream
   adjustment calls receive useful upstream context.
7. As the PM, I want source authenticity and evidence sufficiency reported separately, so that the
   presence of real filing text is not mistaken for adequate analytical evidence.
8. As the PM, I want every adjustment call limited to a tightly related set of assumptions, so that
   its mandate and evidence are easy to understand.
9. As the PM, I want unrelated assumptions handled in separate calls, so that tax, dilution,
   terminal economics, and exit multiples do not become one opaque decision.
10. As the PM, I want the reasoning analyst to state the complete economic argument in readable
    language, so that I can audit the proposal without decoding JSON.
11. As the PM, I want every proposed value explicitly declared in the reasoning draft, so that no
    later stage can invent a number.
12. As the PM, I want proposed scenario conditions and what-would-change-the-view statements, so
    that low/base/high values represent understandable economic cases.
13. As the PM, I want a cheaper model to handle formatting, so that expensive reasoning capacity is
    not spent on JSON syntax.
14. As the PM, I want the Proposal Compiler prohibited from changing numbers, so that compilation
    cannot become a hidden second analytical opinion.
15. As the PM, I want an ambiguous reasoning draft returned to the reasoning analyst, so that the
    compiler never guesses.
16. As the PM, I want deterministic verification of the compiled proposal, so that model-generated
    assurances are not the only protection against numeric drift.
17. As the PM, I want every compiled number matched to its field, scenario, and unit declaration in
    the reasoning draft, so that an unrelated number cannot satisfy a superficial text search.
18. As the PM, I want invented or unknown evidence anchors rejected, so that every adjustment
    remains traceable to the frozen evidence set.
19. As the PM, I want invalid scenario ordering and non-finite values rejected, so that malformed
    proposals never reach valuation.
20. As the PM, I want a critic to review both the reasoning and compiled proposal, so that the critic
    can distinguish analytical weakness from transcription correctness.
21. As the PM, I want the critic to request a new reasoning draft rather than edit the proposal, so
    that authorship remains clear.
22. As the PM, I want failed calls to stop only their current path with an explicit reason, so that
    the system never manufactures a fallback proposal.
23. As the PM, I want prompts, raw responses, validated payloads, errors, and model identities
    persisted per call, so that the full judgment chain can be replayed and reviewed.
24. As the PM, I want each MSFT ride-along call paused and displayed before the next call, so that I
    can learn what the system actually sends and receives.
25. As the PM, I want accepted proposals to enter the existing PM Decision Queue, so that the new
    architecture does not create a parallel approval system.
26. As the PM, I want approval to remain separate from proposal generation, so that agents cannot
    mutate deterministic valuation without my decision.
27. As an engineer, I want all analyst roles to use one call envelope and gateway, so that provider
    routing, validation, retries, replay, and audit behavior remain consistent.
28. As an engineer, I want role-specific evidence projections over one frozen run contract, so that
    small calls receive relevant context without duplicating acquisition logic.
29. As an engineer, I want failures represented as stable reason codes, so that the guided workflow
    can stop and explain the exact failing boundary.
30. As an engineer, I want old deterministic translator deltas removed from numeric authority, so
    that provenance correctly identifies the reasoning analyst as the author of forecast values.

## Implementation Decisions

- The production direction is to extend the newer provider-neutral judgment pipeline. The older
  fixed-delta translator remains compatibility code only and cannot author decision-grade forward
  assumptions.
- The fixed run contract remains `db_path + ticker`. The system resolves source runs, financial
  as-of dates, and evidence cutoffs internally and carries them through every call envelope.
- The context stage contains two ordered calls: Business Context Analyst, then Industry Context
  Analyst. The second call receives the validated Business Context Report as upstream context.
- A Context Analysis Report contains a report identity, role, as-of date, narrative sections,
  anchored claims, relevant driver or micro-family tags, uncertainties, and evidence gaps. It
  cannot contain an actionable assumption proposal.
- Context input projections may be broad but remain frozen, bounded, source-linked, and free of
  provider retrieval inside the model call. Deterministic acquisition owns filings, transcripts,
  news, structured history, and source lineage.
- `source_quality` describes authenticity. A separate `evidence_sufficiency` state describes
  whether the selected evidence supports the requested analysis. A context call with inadequate
  evidence returns `insufficient_evidence` instead of generic prose.
- Adjustment work uses these initial micro-families:
  1. near- and mid-term revenue growth;
  2. operating profitability (`ebit_margin_target` and `cogs_pct_of_revenue`);
  3. target tax rate;
  4. capital intensity (`capex_pct_target` and `da_pct_target`);
  5. working capital (`dso_target`, `dio_target`, and `dpo_target`);
  6. terminal economics (`revenue_growth_terminal` and `ronic_terminal`);
  7. exit multiple; and
  8. annual dilution.
- A micro-family must contain every applicable field assigned to it and no field outside it.
  Conditional fields may be explicitly marked not applicable with evidence and rationale.
- Each Adjustment Reasoning Draft contains narrative reasoning plus an explicit proposal declaration
  for every field: canonical field name, low/base/high values, canonical unit, scenario conditions,
  rationale, evidence anchors, and what would change the view.
- The Proposal Compiler receives only the reasoning draft, the allowed micro-family definition,
  canonical units, permitted anchor IDs, and the strict output schema. It does not receive extra
  evidence that could encourage new analysis.
- The compiler output is either a complete Compiled Adjustment Proposal or a structured
  `ambiguous_input` failure. It cannot return a partial proposal.
- The Proposal Verifier matches every compiled value to the uniquely labelled field/scenario/unit
  declaration in the reasoning draft. Mere appearance of the same number elsewhere in the draft is
  insufficient.
- Verification also enforces schema completeness, field whitelist, canonical units, scenario
  direction, finite numbers, applicability, and evidence-anchor membership.
- Compiler or verifier failure permits one reasoning clarification cycle. A second failure blocks
  the micro-family with a stable reason code.
- After successful verification, the Critic Analyst receives the frozen evidence projection,
  upstream context reports, reasoning draft, compiled proposal, and verification result.
- A critic verdict is `accept`, `revise`, or `block`. `revise` permits one analytical revision cycle
  followed by recompilation, reverification, and one final critic call. The critic never supplies
  replacement values.
- Every model interaction is an independent Agent Run Envelope linked by parent/child run IDs. The
  system persists prompts, raw responses, structured payloads, validation failures, routing data,
  and usage metadata before advancing.
- A formatter role may default to a cheaper configured model. Reasoning and critic roles retain
  their independent provider/model configuration. All roles use the same contract validator and
  fail-closed behavior.
- Only verified and critic-accepted proposals become PM Decision Queue items. The queue item retains
  references to the context reports, reasoning run, compiler run, verification result, and critic
  run.
- PM approval, editing, rejection, and deferral continue through the existing queue. Approval is
  required before deterministic replay consumes any proposed value.
- Unsupported but financially sound adjustments produce a model-change request rather than being
  forced into an unrelated existing field.
- The guided MSFT ride-along pauses after every call boundary and renders the exact input packet,
  prompt identity, raw response, validated output, and next permitted transition.

## Testing Decisions

- Verification is per call, matching the PM's ride-along workflow. This spec does not require a new
  synthetic end-to-end test of the entire judgment pipeline.
- Context calls are checked for a frozen input identity, valid evidence anchors, report-schema
  compliance, explicit sufficiency status, and persisted prompt/response artifacts.
- Reasoning calls are checked for complete proposal declarations for their micro-family and no
  fields outside that family.
- Compiler calls are checked for strict-schema output or an explicit ambiguity failure. They are
  not judged on analytical quality.
- The deterministic verifier is tested directly against altered numbers, swapped scenarios,
  changed units, invented anchors, missing fields, duplicate fields, non-finite values, and values
  that appear in the draft but are not attached to the correct field/scenario declaration.
- Critic calls are checked for valid verdicts, grounded issues, no direct value edits, and correct
  revision/block behavior.
- Queue translation is checked at the call boundary: only verified, critic-accepted proposals may
  create pending items, and no item is automatically approved or applied.
- The principal integration evidence is the MSFT ride-along on the isolated Step 2 database. Each
  call is inspected before continuing; observed friction is logged for later hardening.
- Existing contract, gateway, driver proposal, queue, approval, and replay tests provide prior art.
  Tests should assert public contract behavior rather than prompt wording or internal helper calls.

## Out of Scope

- Perfecting the substantive MSFT business, industry, or forecast conclusions in the first pass.
- Adding new data providers or allowing model calls to browse or fetch evidence directly.
- Expanding the assumption registry beyond the currently supported judgment-owned fields.
- Replacing the PM Decision Queue, approval register, deterministic DCF, comps engine, or valuation
  replay system.
- Automatically approving or applying any agent proposal.
- Building a broad synthetic end-to-end test suite before the per-call MSFT ride-along works.
- Optimizing concurrency, batch throughput, or provider cost before the single-ticker flow is
  inspectable and reliable.
- Removing all legacy Agentic Handoff Profile code in the first implementation; compatibility code
  may remain so long as it cannot claim numeric authority for the new workflow.

## Further Notes

- This design deliberately separates financial authorship from serialization. The reasoning
  analyst owns the values; the compiler owns only schema translation; deterministic verification
  proves fidelity; the critic owns challenge; the PM owns authorization.
- “Similar packets” means a shared run envelope and provenance model, not one oversized universal
  payload. Each role receives a projection sized to its analytical question.
- The context reports are durable upstream evidence. Driver calls may quote and cite their claims,
  but the underlying source anchors remain available for inspection.
- The current glossary language that gives fixed Translator Rules numeric authority is superseded by
  Vision Decision 13 and this spec. The legacy translator is compatibility-only.

