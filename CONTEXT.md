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
This is the canonical handoff object between judgment-layer agents and any deterministic valuation mutation.
_Avoid_: Override register, assumption register

**PM Decision Queue Adapter**:
An MVP compatibility layer that maps existing recommendation and pending-assumption flows into canonical PM Decision Queue items without replacing the current working plumbing.
_Avoid_: Rewrite-first queue implementation, parallel approval system

**Canonical Queue Store**:
The SQLite-backed source of truth for PM Decision Queue items, Evidence Packets, PM edits, decision states, and searchable insight metadata.
_Avoid_: YAML source of truth, transient UI state

**Queue Adapter Link**:
A foreign-key-style pointer from a PM Decision Queue item to an existing compatibility object, such as a pending assumption change row created by the MVP adapter.
_Avoid_: Duplicated approval authority, metadata-only linkage

**Queue Export**:
A human-readable export or compatibility copy of PM Decision Queue or Evidence Packet data for inspection, debugging, or migration.
_Avoid_: Canonical queue store, approval authority

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

**Advisory Finding**:
A non-mutating PM Decision Queue item that captures judgment-layer evidence, concern, or opportunity without proposing an official model input change yet.
_Avoid_: Recommendation, override, approved assumption

**Evidence Packet**:
A durable bundle of source snippets, structured observations, agent outputs, citations, and run metadata that supports one or more PM Decision Queue items.
_Avoid_: Queue item, approval record, raw prompt dump

**Evidence Packet Bundle**:
A run-level grouping that links multiple source- or event-specific Evidence Packets used in one ticker analysis run.
_Avoid_: Single all-purpose evidence packet, PM Decision Queue item

**Evidence Packet Kind**:
The source or event family for an Evidence Packet, such as filing update, earnings call, market context, valuation snapshot, or industry context.
_Avoid_: Agent name, queue item type

**Agentic Handoff Profile**:
The per-agent configuration that defines which Evidence Packet Kinds an agent consumes, which prompt to use, which observation types it may emit, and which translator rules can turn those observations into PM Decision Queue items.
_Avoid_: One-off agent workflow, hardcoded prompt path

**Earnings Update Evidence Packet**:
The MVP Evidence Packet Kind for a recent earnings event, combining earnings-release or transcript source references, mechanically gathered earnings facts, and agent observations about tone, guidance, demand, pricing, and disclosure changes.
_Avoid_: Full ticker analysis packet, market context packet

**Company Analysis Evidence Packet**:
An Evidence Packet Kind for filings, business description, segment disclosure, accounting quality, management guidance, and company-specific operating facts.
_Avoid_: Earnings-only packet, industry packet

**Industry Analysis Evidence Packet**:
An Evidence Packet Kind for sector growth, peer operating metrics, capacity, pricing, cyclicality, regulation, and industry structure.
_Avoid_: Company-specific packet, market-regime packet

**Comps Analysis Evidence Packet**:
An Evidence Packet Kind for peer universe, peer similarity, valuation multiples, business-model comparability, and relative valuation context.
_Avoid_: Base-case override, raw peer table only

**Observation-To-Assumption Translator**:
A deterministic adapter that converts anchored Evidence Packet Observations into conservative, whitelisted Assumption Change Proposals or Assumption Change Packs.
_Avoid_: LLM-written model mutation, free-form agent override

**Translator Rule**:
A fixed, testable MVP mapping from specific observation types and confidence levels to conservative assumption proposal deltas.
_Avoid_: Prompt-only numeric judgment, hidden heuristic

**Symmetric Assumption Proposal**:
An Assumption Change Proposal that may move an official model input either upward or downward when anchored evidence supports the direction and the PM approves it.
_Avoid_: Downside-only translator policy, optimism without evidence

**Proposal Mode**:
The way an Assumption Change Proposal expresses its intended change: as a delta from the current effective assumption or as a target value.
_Avoid_: Implicit value semantics, prose-only magnitude

**PM-Edited Proposal**:
An Assumption Change Proposal whose PM-approved value differs from the original agent or translator proposal while preserving the original evidence, rationale, and proposed magnitude for audit.
_Avoid_: Silent overwrite, approve-only workflow

**Searchable PM Insight**:
A PM Decision Queue item or Evidence Packet Observation that remains discoverable later because it captures a material insight, evidence anchor, valuation impact, and PM disposition.
_Avoid_: Ephemeral chat note, buried agent output

**Qualitative Importance**:
A PM-facing importance label for an insight or queue item based on evidence strength, thesis relevance, and decision usefulness, separate from measured valuation impact.
_Avoid_: Valuation impact, confidence score

**Agent Confidence**:
The judgment-layer agent's confidence that an observation follows from its evidence anchors.
_Avoid_: Translator confidence, PM confidence

**Translator Confidence**:
The deterministic translator's confidence that an anchored observation maps cleanly to a specific assumption proposal.
_Avoid_: Agent confidence, PM confidence

**PM Confidence**:
The PM's confidence after reviewing, editing, approving, rejecting, or deferring a queue item.
_Avoid_: Agent confidence, translator confidence

**Evidence Packet Source Reference**:
A stable pointer to the underlying source used by an Evidence Packet, such as a filing accession, transcript path, news URL, market snapshot id, or agent run id.
_Avoid_: Loose prose citation, prompt-only reference

**Evidence Packet Fact**:
A mechanically gathered or normalized input in an Evidence Packet, such as filing metadata, transcript path, price move, valuation snapshot, analyst revision snapshot, macro indicator value, or source timestamp.
_Avoid_: Agent interpretation, qualitative conclusion

**Evidence Packet Observation**:
A normalized claim extracted from evidence, such as pricing commentary deterioration, DSO/revenue divergence, guidance tone shift, or peer-margin pressure.
_Avoid_: Raw excerpt, mechanically gathered fact, proposed assumption change

**Evidence Anchor**:
The Evidence Packet Fact or Evidence Packet Source Reference that supports an Evidence Packet Observation or PM Decision Queue item.
_Avoid_: Unsupported agent claim, generic rationale

**Text Evidence Snippet**:
A short quoted excerpt from a filing, transcript, release, article, or note that anchors a qualitative Evidence Packet Observation.
_Avoid_: Full raw document, structured numeric fact

**Assumption Change Proposal**:
A PM Decision Queue item that proposes one or more official model input changes, with rationale, evidence, confidence, and valuation impact preview before approval.
_Avoid_: Advisory finding, automatic model update

**Assumption Change Pack**:
A coherent multi-field Assumption Change Proposal whose driver changes represent one economic claim and should be previewed, approved, rejected, or edited together.
_Avoid_: Unrelated field bundle, scenario pack, row-by-row recommendation list

**Agent-Proposable Assumption**:
A whitelisted valuation input that judgment-layer agents may propose changing through the PM Decision Queue.
V1 examples include growth, margin, terminal-value, WACC, and EV-bridge fields that can be reasoned about from qualitative or analytical evidence.
_Avoid_: Raw source data, market data correction, unrestricted ForecastDrivers mutation

**Data Correction Workflow**:
A separate workflow for fixing wrong ingested facts such as shares outstanding, market price, raw revenue base, or source identifiers.
_Avoid_: Assumption change proposal, agent judgment

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

**Base-Case Assumption Change**:
An approved change to the official base-case valuation inputs consumed by the deterministic model.
_Avoid_: Scenario overlay, stress case

**Scenario Overlay**:
A non-base-case stress or alternative-world valuation pack used to test risk, upside, or event outcomes without changing official base-case assumptions.
_Avoid_: Base-case override, approved assumption entry

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
- MVP should introduce a **PM Decision Queue Adapter** around the existing recommendation and pending-assumption flow before replacing legacy objects such as `Recommendation` or `PendingAssumptionChange`.
- New PM Decision Queue and Evidence Packet state should use the **Canonical Queue Store** as source of truth. **Queue Exports** may exist for inspection, debugging, or compatibility, but should not carry approval authority.
- The **Canonical Queue Store** should use dedicated tables for Evidence Packets and PM Decision Queue items. The MVP adapter may add **Queue Adapter Links** to existing pending assumption changes when a queue item becomes a numeric assumption proposal.
- Judgment-layer agents may create **PM Decision Queue** items, but only PM-approved items may write to the **Override Register** or approved assumption entries.
- The **PM Decision Queue** accepts both **Advisory Findings** and **Assumption Change Proposals** so qualitative evidence can remain visible without forcing premature numeric precision.
- Multiple PM Decision Queue items may reference the same **Evidence Packet**, but each queue item has its own approval state, valuation impact, and outcome.
- A V1 **Evidence Packet** should separate **Evidence Packet Facts** from **Evidence Packet Observations**. The deterministic pipeline builds the factual skeleton; judgment-layer agents may add observations and parsed outputs tied back to facts and source references.
- V1 **Evidence Packets** should be source- or event-specific and linked by an **Evidence Packet Bundle** for each ticker analysis run, so evidence with different refresh cadences can age independently.
- The MVP should implement one unified agentic handoff framework across judgment agents using **Agentic Handoff Profiles**. Earnings, company analysis, industry analysis, comps, QoE, risk, and valuation review should share Evidence Packet, observation, translator, queue, preview, approval, and search mechanics; only packet inputs, observation taxonomy, prompts, and translator rules vary by profile.
- Judgment agents should produce anchored observations rather than numeric driver edits. An **Observation-To-Assumption Translator** should create conservative, testable driver proposals from those observations to reduce hallucination and context-fog risk.
- The MVP **Observation-To-Assumption Translator** should use fixed **Translator Rules** first. If the loop works, those constants can later move into editable policy.
- MVP **Translator Rules** may create **Symmetric Assumption Proposals**. Upside and downside proposals use the same safety boundary: anchored evidence, conservative deltas, valuation preview, and separate PM approval.
- **Assumption Change Proposals** may use either delta or target **Proposal Mode**. The preview layer must resolve both modes into concrete proposed values before PM approval.
- PM review must support **PM-Edited Proposals** so the PM can approve a different magnitude without losing the original proposal audit trail.
- A **PM-Edited Proposal** updates the existing PM Decision Queue item rather than creating a separate decision item. The item should preserve the original proposal, PM-edited value, final approved value, and decision history.
- The PM Decision Queue should also act as a searchable insight layer. Material observations and proposals should remain discoverable as **Searchable PM Insights**, especially when they carry high valuation impact or changed the PM's decision.
- **Searchable PM Insights** include material approved, rejected, and deferred items. Discoverability is based on materiality, evidence quality, and PM relevance rather than approval outcome alone.
- Insight search and ranking should keep **Valuation Impact** and **Qualitative Importance** separate, because some PM-relevant insights are material before they can be cleanly quantified.
- Queue items should store **Agent Confidence**, **Translator Confidence**, and **PM Confidence** separately when available rather than collapsing them into one ambiguous confidence field.
- Every **Evidence Packet Observation** and PM Decision Queue item must have at least one **Evidence Anchor** in V1.
- Structured numeric or machine-readable **Evidence Packet Facts** can serve as anchors by themselves. Qualitative text observations require at least one **Text Evidence Snippet**.
- **Assumption Change Proposals** are limited to **Agent-Proposable Assumptions**. Raw ingested facts belong to a **Data Correction Workflow**, not agent judgment.
- An **Assumption Change Pack** is used when several driver changes express one economic claim; the PM reviews the pack as a unit rather than as unrelated rows.
- **Base-Case Assumption Changes** and **Scenario Overlays** are separate PM decisions. The former can mutate official deterministic inputs after approval; the latter preserves base-case clarity while stress-testing alternative worlds.
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
- Evidence-driven automatic **Stale Approval** invalidation is a post-MVP/V2 concern. V1 may record evidence timestamps and packet kinds, but it does not automatically stale approved base-case changes when newer evidence arrives.
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
- Scenario probabilities and context scenario outputs were considered for V1. Resolved: scenarios become **Scenario Assumption Packs** in V2, not flattened V1 assumption entries, and must remain distinct from **Base-Case Assumption Changes**.
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
