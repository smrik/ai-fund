# Alpha Pod Valuation Context

This context captures the domain language for Alpha Pod's valuation workflow. It exists so agents, docs, and implementation plans use the same words for assumptions, approvals, and PM review.

## Language

**Assumption Register**:
The official map of valuation assumptions, accepted ranges, source lineage, flags, and approval state.
_Avoid_: Override register, assumption table

**Override Register**:
The narrower record of PM-approved changes that may mutate deterministic valuation assumptions.
_Avoid_: Assumption register, approval queue

**PM Decision Queue**:
The review workflow surface where flagged assumptions, advisory suggestions, and material valuation changes are triaged by the PM.
_Avoid_: Override register, assumption register

**WACC Assumption Inputs**:
The PM-reviewable cost-of-capital assumptions and components that explain the final WACC used in a valuation.
_Avoid_: WACC audit internals, single WACC assumption

**Stale Approval**:
A previously approved assumption state that requires PM review because the approved value or one of its material components changed.
_Avoid_: Still approved, expired approval

**Model Trust State**:
The valuation-level review state that tells the PM whether computed outputs are clean, review-required, or critical-review-required.
_Avoid_: Block status, pass/fail

**Advisory Reference**:
A reserved pointer from an official assumption to non-authoritative judgment-layer context that may inform PM review later.
_Avoid_: Official action, approval status, LLM input

**Source Quality State**:
The PM-facing confidence class for where an assumption came from, separate from whether the numeric value is inside its accepted range.
_Avoid_: Range flag, source lineage

**Review-Relevant Audit Event**:
An assumption-register event worth preserving because it affects PM attention, approval state, flags, source, range rule, or material value movement.
_Avoid_: Snapshot row, every generated assumption

**Valuation Impact**:
The measured change in intrinsic value or expected value from a proposed assumption change.
_Avoid_: Flag severity, source quality

**Effective Ticker Assumption**:
The final assumption value used for one ticker valuation after deterministic defaults, lineage, and approved overrides are resolved.
_Avoid_: Sector policy entry, global policy entry

**Scenario Assumption Pack**:
A coherent multi-assumption valuation case, such as bear, base, bull, or context-aware scenarios.
_Avoid_: Single assumption, ordinary DCF driver

**Terminal Value Driver**:
A PM-reviewable assumption that defines the mature-state economics or terminal valuation method for a DCF.
_Avoid_: Terminal diagnostic, terminal output

**Approval Reference**:
A pointer from an official assumption state to the durable PM-applied audit record that authorized it.
_Avoid_: Advisory reference, pending recommendation

**Flag Level**:
The deterministic severity label that tells the PM how urgently an assumption or valuation state needs review.
_Avoid_: Error status, approval state

**Assumption Owner**:
The authority responsible for the official assumption value: deterministic system logic, PM override, or system-generated flag.
_Avoid_: Source lineage, data source

**Assumption Field Name**:
The machine-stable key for an assumption, preferably matching the valuation driver or WACC input field name.
_Avoid_: Display label, prose name

**Assumption Register Summary**:
The compact attention-focused rollup of register state for dossier, export, and ranking surfaces.
_Avoid_: Full assumption register, clean assumption list

**Contract Boundary**:
The point where a payload is validated against the shared public model before crossing module or surface boundaries.
_Avoid_: Internal builder representation, every intermediate object

**Accepted Range**:
The PM-review range used to assess whether an effective assumption deserves attention, distinct from numerical clamps used to keep the model computable.
_Avoid_: Hard clamp, validation bound

**Audit Diff**:
The minimal before/after change payload recorded for a review-relevant assumption event.
_Avoid_: Full entry snapshot, full register snapshot

**Materiality Rule**:
A centralized threshold rule that determines whether an assumption change is meaningful enough to affect audit, approval, or review state.
_Avoid_: Inline threshold, scattered if-branch

**Audit Family**:
A named group of audit events with a shared source and meaning, such as PM override history or assumption-register material diffs.
_Avoid_: Generic audit rows, mixed audit list

## Relationships

- The **Assumption Register** includes deterministic assumptions and their review state.
- The **Override Register** records PM-approved mutations that can affect entries in the **Assumption Register**.
- The **PM Decision Queue** consumes **Assumption Register** flags and advisory suggestions but is not the source of truth for official model inputs.
- **WACC Assumption Inputs** are included in the **Assumption Register** because cost of capital components are material to PM review.
- **Stale Approval** is assessed at the component level for **WACC Assumption Inputs**, even when final WACC has not moved materially.
- **Model Trust State** is derived from **Assumption Register** flags and affects review priority without preventing deterministic computation.
- **Model Trust State** may also incorporate valuation diagnostics, such as terminal concentration, without turning diagnostics into assumptions.
- An **Advisory Reference** may point from an **Assumption Register** entry to judgment-layer context, but it does not change official assumption state.
- **Source Quality State** is a future review dimension for the **Assumption Register**, not a V1 field.
- A **Review-Relevant Audit Event** is appended only when an assumption needs PM attention or its meaningful review state changed.
- **Valuation Impact** is recorded in V1 when the PM previews or applies an override, not automatically for every flagged assumption.
- V1 **Assumption Register** entries are **Effective Ticker Assumptions** even when their lineage points to sector or global policy inputs.
- **Scenario Assumption Packs** are future objects separate from V1 single-value **Assumption Register** entries.
- **Terminal Value Drivers** are first-class V1 **Assumption Register** entries; terminal value outputs remain diagnostics.
- An **Approval Reference** points to PM-applied override audit history, while an **Advisory Reference** points to non-authoritative judgment context.
- A **Flag Level** is separate from approval state: flags describe review severity, while approval state describes PM authorization.
- **Assumption Owner** identifies official authority, while source lineage records detailed provenance.
- **Assumption Field Names**, stages, scopes, and affected forecast lines should use stable vocabulary so register entries remain filterable.
- The **Assumption Register Summary** includes trust state, flag counts, max flag, and flagged entries; full clean entries remain in the full register.
- The **Contract Boundary** for the assumption register is the shared Pydantic model; internal builders may use lighter representations before final validation.
- An **Accepted Range** is a review boundary for the final effective value, not necessarily the same as the hard clamps used during input assembly.
- A **Review-Relevant Audit Event** stores an **Audit Diff**, while the full current state remains in the **Assumption Register**.
- **Materiality Rules** are centralized so provisional thresholds can be inspected, tested, and revised.
- Different **Audit Families** should remain separate in API payloads unless a surface explicitly asks for a merged timeline.

## Example dialogue

> **Dev:** "Should the QoE agent write this EBIT adjustment into the **Assumption Register**?"
> **Domain expert:** "No. It should appear in the **PM Decision Queue** first. If approved, the **Override Register** records the PM-approved change, and the **Assumption Register** reflects the resulting official assumption state."

## Flagged ambiguities

- "Register" was used for both the full assumption map and the PM override trail. Resolved: **Assumption Register** is the full official assumption map; **Override Register** is only the PM-approved mutation trail.
- "WACC" was initially treated as possibly one assumption plus audit detail. Resolved: **WACC Assumption Inputs** are first-class review entries because the PM considers each cost-of-capital component material.
- "Approval" for WACC was ambiguous between final-WACC approval and component approval. Resolved: component-level changes can create **Stale Approval** even when headline WACC movement is small.
- "Blocking" was considered for out-of-range assumptions. Resolved: V1 computes and exports valuations, while **Model Trust State** downgrades fragile outputs for ranking and review.
- **Model Trust State** was ambiguous between a pure max-flag rollup and a broader valuation-quality signal. Resolved: it is a deterministic rollup of assumption flags plus selected valuation diagnostics.
- `driver_assessments.py` workflow states were considered for V1. Resolved: V1 reserves **Advisory Reference** fields only; official approval state remains deterministic and PM-owned.
- "In range" was considered as possibly enough to trust an assumption. Resolved: **Source Quality State** should eventually distinguish strong sources from fallbacks, but stays V2.
- `first_seen` audit logging was ambiguous. Resolved: V1 logs first-seen events only when they are **Review-Relevant Audit Events**, not for every generated baseline assumption.
- `valuation_impact` was ambiguous between static register metadata and preview/apply evidence. Resolved: **Valuation Impact** is required for PM override preview/apply paths in V1; automatic per-flag sensitivity belongs in V2.
- `entity_type` was ambiguous for values sourced from sector/global policy. Resolved: V1 entries are **Effective Ticker Assumptions** with `entity_type = ticker`; sector/global policy entries are V2.
- Scenario probabilities and context scenario outputs were considered for V1. Resolved: scenarios become **Scenario Assumption Packs** in V2, not flattened V1 assumption entries.
- Terminal value could mean assumptions or computed outputs. Resolved: **Terminal Value Drivers** are V1 assumption entries, while terminal concentration and value outputs are diagnostics.
- `approval_ref` could have pointed to pending recommendations or advisory files. Resolved: **Approval Reference** points only to durable PM-applied records such as override or WACC methodology audit rows.
- `FlagLevel` was underdefined. Resolved: **Flag Level** values must have deterministic semantics: `none`, `watch`, `review_required`, and `critical`.
- `owner` was ambiguous between authority and provenance. Resolved: **Assumption Owner** is coarse official authority; detailed origin stays in source lineage and approval/advisory references.
- Naming fields were at risk of becoming free-form labels. Resolved: V1 uses stable **Assumption Field Names** and controlled stage/scope/forecast-line vocabularies.
- Compact dossier/export content was ambiguous. Resolved: **Assumption Register Summary** is attention-focused and does not include clean-but-important assumptions in V1.
- Pydantic usage was ambiguous between public contract and every builder step. Resolved: validate at the **Contract Boundary**, while internal construction may stay lightweight.
- Accepted ranges were at risk of duplicating hard clamps. Resolved: **Accepted Range** is a PM-review concept; V1 records effective values and may mention raw/pre-clamp evidence in notes or evidence refs when readily available.
- Audit payload shape was ambiguous between full snapshots and diffs. Resolved: V1 audit rows store **Audit Diff** payloads, not full entry or full-register snapshots.
- Materiality thresholds were at risk of becoming scattered conditionals. Resolved: V1 uses centralized **Materiality Rules** keyed by field class or scope.
- API audit rows were ambiguous between override history and assumption-register history. Resolved: V1 exposes separate **Audit Families** rather than one mixed list.
