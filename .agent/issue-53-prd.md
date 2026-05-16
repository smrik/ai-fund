## Problem Statement

Alpha Pod produces deterministic valuation outputs, but the PM does not yet have a first-class Assumption Register that shows which valuation assumptions were used, where they came from, whether they sit inside accepted ranges, which ones need review, and which PM approvals may have gone stale.

Today, review context is spread across source lineage, override history, WACC workbench state, DCF diagnostics, and export payloads. This makes it too easy for fragile assumptions to appear beside clean valuations without a clear model trust signal.

## Solution

Build a deterministic V1 Assumption Register for each ticker valuation.

The register should capture Effective Ticker Assumptions, including core DCF drivers, WACC Assumption Inputs, and Terminal Value Drivers. It should expose flag severity, approval state, source lineage, accepted ranges, model trust state, and a compact attention-focused summary for dossier/export/ranking surfaces.

The full register belongs in valuation JSON. Compact summaries should show only trust state, flag counts, max flag, and flagged entries. PM-approved changes continue to flow through the existing override path, with Approval References pointing only to durable PM-applied audit records.

## User Stories

1. As a PM, I want to see every effective ticker assumption used in a valuation, so that I can review the model without hunting through multiple artifacts.
2. As a PM, I want WACC components to be first-class assumptions, so that I can review the economic story behind the discount rate.
3. As a PM, I want terminal value drivers to be first-class assumptions, so that I can scrutinize the inputs that often dominate valuation.
4. As a PM, I want terminal value outputs to remain diagnostics, so that the register does not confuse assumptions with computed results.
5. As a PM, I want out-of-range assumptions to flag review without blocking computation, so that valuation runs remain reproducible.
6. As a PM, I want a model trust state, so that fragile valuations are visibly downgraded in ranking and export surfaces.
7. As a PM, I want trust state to account for selected diagnostics, so that terminal concentration can affect review priority without becoming an assumption.
8. As a PM, I want PM approvals to become stale when material components change, so that old approvals do not silently remain trusted.
9. As a PM, I want WACC approvals checked at the component level, so that beta, ERP, size premium, cost of debt, weights, or methodology changes trigger review.
10. As a PM, I want Approval References to point only to durable PM-applied audit records, so that official approval state is not confused with advisory notes.
11. As a PM, I want advisory references reserved but not populated in V1, so that future agent context can attach without changing official values.
12. As a PM, I want source quality to be recognized as important but deferred, so that V1 stays focused while V2 can distinguish strong sources from fallbacks.
13. As a PM, I want first-seen audit events only for review-relevant entries, so that audit history is meaningful rather than noisy.
14. As a PM, I want audit rows to store concise diffs, so that material changes are easy to scan.
15. As a PM, I want override audit and assumption-register audit to remain separate audit families, so that different event types are not mixed.
16. As a PM, I want valuation impact recorded for override preview/apply paths, so that I can see the effect of approved changes.
17. As a PM, I do not want automatic per-flag sensitivity runs in V1, so that register generation remains cheap and deterministic.
18. As a PM, I want accepted ranges to be review ranges rather than hard model clamps, so that bounded values can still be flagged as questionable.
19. As a PM, I want stable field names, stages, scopes, and affected forecast lines, so that the register is filterable and testable.
20. As a PM, I want compact dossier/export summaries to show only attention items, so that review surfaces remain focused.
21. As a developer, I want the public contract to be typed, so that downstream consumers can rely on a stable payload shape.
22. As a developer, I want internal builders to remain lightweight, so that batch valuation performance is not harmed by unnecessary object construction.
23. As a developer, I want materiality thresholds centralized, so that provisional rules are inspectable and easy to revise.
24. As a developer, I want flag semantics defined, so that UI, API, and tests do not invent conflicting meanings.
25. As a developer, I want owner semantics defined separately from lineage, so that official authority is not confused with provenance.
26. As a developer, I want scenario assumption packs deferred to V2, so that V1 does not flatten multi-assumption cases into misleading single rows.
27. As a developer, I want sector/global policy rows deferred to V2, so that V1 stays focused on effective ticker assumptions.
28. As a downstream consumer, I want the full register in valuation JSON, so that detailed drill-down is available.
29. As a downstream consumer, I want the ticker dossier to carry only a compact summary, so that payloads stay lightweight.
30. As a reviewer, I want tests around contract round-trips, builder output, flagging, trust state, audit diffs, and export/API payloads, so that regressions are caught at the behavior boundary.

## Implementation Decisions

- Build one coherent V1 PR with internally sliced commits/checkpoints.
- Define a shared Assumption Register contract at the public boundary.
- Let valuation-specific builder logic construct lightweight internal payloads, then validate once against the shared contract.
- Populate V1 entries as Effective Ticker Assumptions.
- Preserve sector/global origins in lineage and scope, but do not create sector/global policy entries in V1.
- Include core DCF drivers already shown in the assumptions workbench.
- Include WACC Assumption Inputs: final WACC, risk-free rate, equity risk premium, beta, size premium, cost of debt, equity/debt weights, and selected methodology when available.
- Include Terminal Value Drivers: terminal growth, terminal RONIC, exit multiple, and terminal blend weights.
- Exclude scenario probabilities and context scenario outputs from V1.
- Reserve advisory attachment fields, but leave them empty in V1.
- Keep Source Quality State in V2.
- Keep automatic sensitivity-driven Valuation Impact scoring in V2.
- Use `owner` only for official authority: deterministic, PM override, or system flag.
- Keep detailed provenance in source lineage, Approval References, and Advisory References.
- Make Approval References point only to durable PM-applied audit rows.
- Define deterministic Flag Level semantics for none, watch, review required, and critical.
- Define Model Trust State as a deterministic rollup of assumption flags plus selected valuation diagnostics.
- Define stable naming conventions for assumption names, stages, scopes, and affected forecast lines.
- Treat accepted ranges as PM-review ranges for effective values, not necessarily the same as numerical hard clamps.
- Keep raw/pre-clamp value diagnostics out of V1 unless they are easy to mention in notes or evidence references.
- Add append-only assumption-register audit for review-relevant material events.
- Store concise audit diffs, not full entry snapshots or full-register snapshots.
- Keep override audit rows and assumption-register audit rows as separate API families.
- Put the full Assumption Register in valuation JSON.
- Add compact Assumption Register Summary to dossier/export/ranking surfaces.
- Compact summaries include trust state, flag counts, max flag, and flagged entries only.
- Preserve deterministic valuation output even when flags are critical.

## Testing Decisions

- Test external behavior and contracts, not implementation details.
- Test JSON round-trip behavior for the shared Assumption Register contract.
- Test that the builder validates final payloads against the shared contract.
- Test deterministic builder output for numeric effective ticker assumptions.
- Test WACC components as first-class entries.
- Test terminal value drivers as entries and terminal outputs as diagnostics.
- Test static accepted-range flagging.
- Test that out-of-range values do not block valuation.
- Test flag-level semantics for none, watch, review required, and critical.
- Test model trust rollup from flags and selected diagnostics.
- Test materiality rules by field class.
- Test component-level stale approval behavior for WACC inputs.
- Test that audit rows store concise diffs.
- Test that first-seen audit logging is review-relevant only.
- Test valuation result includes the register.
- Test valuation JSON includes the full register.
- Test assumptions API payload includes separate override and assumption-register audit families.
- Test override preview/apply paths can include valuation-impact metadata.
- Test ticker dossier/export surfaces include compact summaries only.
- Use existing API contract, JSON exporter, override workbench, batch runner, and ticker dossier tests as prior art.

## Out of Scope

- LLM or judgment-layer population of official register entries.
- Automatic mutation of deterministic valuation inputs from advisory output.
- Source Quality State implementation.
- Scenario Assumption Packs.
- Sector, industry, or global policy-entry population.
- Damodaran data ingestion or range-policy integration.
- Historical, peer, industry, or scale-aware accepted ranges.
- Automatic per-flag sensitivity or valuation-impact scoring.
- Raw/pre-clamp value fields in the V1 contract.
- Broad React redesign.
- Config editor for range rules or assumptions.

## Further Notes

The key invariant remains unchanged: LLMs and advisory agents may inform PM review, but they must not mutate official valuation inputs except through a PM-approved override path.

V1 should make the deterministic valuation easier to audit without turning the register into a second valuation engine. The register is the PM-facing map of assumptions and review state; the existing valuation math remains the system of record for computed outputs.
