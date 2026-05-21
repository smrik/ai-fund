# Universal Agentic Handoff MVP Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build the first real-world-testable unified loop where any judgment agent can turn anchored evidence into searchable PM Decision Queue items, previewable assumption proposals, and PM-approved deterministic valuation changes.

**Architecture:** Add a SQLite-backed Canonical Queue Store for Evidence Packets and PM Decision Queue items, then adapt it to the existing `pending_assumption_changes` approval path instead of replacing working plumbing. The MVP uses one shared framework across agent-specific handoff profiles: company analysis, industry analysis, earnings, comps, QoE, risk, and valuation review share evidence, observation, translator, queue, preview, approval, and search mechanics; only prompts, input packet kinds, observation taxonomies, and translator rules vary by profile.

**Tech Stack:** Python 3, Pydantic v2 contracts, SQLite via existing `db/schema.py` and `db/loader.py`, FastAPI in `api/main.py`, React + TypeScript in `frontend/`, pytest, existing RTK command wrapper.

---

## Decisions Already Resolved

- `PM Decision Queue` is the canonical handoff between judgment agents and deterministic model mutation.
- Agents may create queue items; only PM approval can create official overrides or approved assumption entries.
- Queue items may be `Advisory Findings` or `Assumption Change Proposals`.
- Evidence is represented as source/event-specific `Evidence Packets`, linked by an optional run-level bundle.
- Evidence separates mechanically gathered `facts` from agent-created `observations`.
- Every observation and queue item needs an `Evidence Anchor`.
- Numeric facts can anchor numeric claims; qualitative claims require text snippets.
- MVP framework is universal across judgment agents, not earnings-only.
- Each agent uses an `Agentic Handoff Profile` that defines inputs, prompt, allowed observations, and translator rules.
- Judgment agents produce anchored observations, not direct numeric driver edits.
- A deterministic Observation-To-Assumption Translator creates fixed-rule, conservative, symmetric proposals.
- Proposals may be `delta` or `target`; preview resolves both into concrete values.
- PM can edit proposals before approval; edits update the same queue item and preserve the original proposal.
- Searchable PM insights include approved, rejected, and deferred material items.
- Search/ranking separates valuation impact from qualitative importance.
- Store agent, translator, and PM confidence separately.
- SQLite is canonical; YAML/export is optional compatibility or inspection.
- Dedicated queue/evidence tables are needed; `pending_assumption_changes` remains the numeric approval adapter.
- Automatic stale-evidence invalidation is post-MVP/V2.
- Base-case assumption changes and scenario overlays stay separate.

## Handoff Guidance For 5.3-Codex

The user wants Alpha Pod to become a fast human-in-the-loop research machine, not just a valuation calculator with some agent summaries bolted on. The core speed benefit should come from agents finding important evidence-backed insights across company analysis, industry analysis, earnings, comps, risk, and valuation review, then pushing those insights into one searchable PM workflow where the PM decides what matters and what changes the model.

The implementation should optimize for this loop:

```text
Evidence Packet -> Agent Observation -> Translator -> PM Decision Queue -> Preview/Edit/Approve -> Deterministic Rerun
```

The important idea is that this loop must be universal. Do not build an earnings-only special case. Earnings is a useful first profile for testing, but the same mechanics must work for every judgment agent. The agent-specific parts should be limited to:

- which evidence packet kinds are assembled
- which prompt/system instructions are used
- which observation types the agent may emit
- which translator rules can map observations to assumption proposals

Everything else should be shared:

- Pydantic contracts
- SQLite persistence
- evidence anchoring
- queue item lifecycle
- PM edit and approval semantics
- valuation preview
- searchable insight listing
- API shape
- React PM Queue / Insights surface

The PM Decision Queue is both an approval surface and a memory/search layer. It should preserve material approved, rejected, and deferred items because rejected/deferred insights are often still useful later. The PM should be able to search by ticker, evidence kind, agent/profile, status, qualitative importance, valuation impact, affected assumption, and source.

The safest mental model is:

- agents are analysts
- translator rules are deterministic policy
- PM is the decision maker
- deterministic valuation is the official model
- approved assumption entries are the only way judgment changes model inputs

## Tricky Logic And Guardrails

Do not let agents write numeric model changes directly. Agents produce anchored observations. The deterministic Observation-To-Assumption Translator may convert those observations into proposed driver changes using fixed, testable rules.

Do not collapse facts and observations. Evidence Packet Facts are mechanically gathered or normalized inputs. Evidence Packet Observations are interpretive claims. Numeric facts can stand alone as anchors, but qualitative claims need text snippets.

Do not collapse confidence. Keep `agent_confidence`, `translator_confidence`, and `pm_confidence` separate. They answer different questions.

Do not collapse base-case changes and scenarios. Base-case approved proposals can mutate official deterministic inputs. Scenario overlays are alternative-world stress tests and should remain separate; MVP may store scenario-related advisory findings but should not route them into base-case apply.

Do not replace the existing pending-assumption plumbing at first. Add a PM Decision Queue Adapter that links queue items to `pending_assumption_changes` when a proposal becomes a concrete numeric model change.

Do not make YAML canonical for the new queue. SQLite is the Canonical Queue Store. YAML or JSON exports can exist for debugging or inspection only.

Do not force every insight into a numeric proposal. Some important work should remain an Advisory Finding, especially when the evidence is meaningful but the model change is not yet obvious.

Do not lose the original proposal when the PM edits it. Store original proposed value, PM-edited value, final approved value, and decision history on the same queue item.

Do not overbuild stale-evidence invalidation in MVP. Store packet kind and timestamps so V2 can stale approvals later, but do not auto-stale approved changes yet.

## What The First Real MVP Should Feel Like

For a ticker, the PM should be able to run one or more profiles such as `company_analysis`, `industry_analysis`, `earnings_update`, `comps_analysis`, or `valuation_review`.

The system should then show a unified queue of insights:

- what the agent noticed
- what evidence supports it
- why it matters
- whether it affects the model
- what assumption changes are proposed, if any
- what valuation impact the proposed change has
- whether the PM approved, edited, rejected, or deferred it

The UI does not need to be fancy for MVP, but it must make evidence and decisions easy to inspect. A working PM should be able to answer:

- "What did agents find that actually matters?"
- "What evidence supports this?"
- "What would happen to IV if I accepted it?"
- "What did I reject last time and why?"
- "Which high-impact insights are still deferred?"

This is the heart of the feature.

## Issues To Resolve For MVP

| ID | Issue | MVP Decision / Required Resolution |
| --- | --- | --- |
| MVP-01 | Contract shape is missing for Evidence Packets and queue items. | Add Pydantic contracts in `src/contracts/`. |
| MVP-02 | SQLite schema has pending assumption changes but no canonical queue/evidence store. | Add dedicated tables and loader helpers. |
| MVP-03 | Agent workflows are currently bespoke. | Add `Agentic Handoff Profile` registry so each agent uses the same packet -> observation -> translator -> queue shape. |
| MVP-04 | Existing agents return summary fields, not anchored observations. | Add structured observation output paths while preserving current summary outputs. |
| MVP-05 | No deterministic builders exist for unified evidence skeletons. | Build generic Evidence Packet service with profile-specific builders for company, industry, earnings, comps, QoE/risk, and valuation review. |
| MVP-06 | No translator maps observations to assumption proposals. | Add fixed translator rules keyed by profile and observation type. |
| MVP-07 | Existing recommendation flow is field-level, not queue-item-level. | Add adapter that creates queue items and links numeric proposals to pending assumption changes. |
| MVP-08 | Current apply path does not preserve original proposal vs PM-edited value. | Add queue decision event/update fields before applying to pending changes. |
| MVP-09 | No API exposes evidence packets, queue items, PM edit, reject, defer, approve, or search. | Add thin FastAPI endpoints over stage_04 services. |
| MVP-10 | React has assumptions/recommendations tabs, but no canonical insight queue. | Add PM Decision Queue review/search surface. |
| MVP-11 | No valuation impact preview for queue packs independent of legacy recommendation YAML. | Reuse `preview_pending_assumption_stack()` and add queue-level preview resolver. |
| MVP-12 | Searchable insight ranking does not exist. | Add list filters by ticker, status, item type, valuation impact, qualitative importance, evidence kind. |
| MVP-13 | Scenario overlays must stay separate from base-case changes. | MVP may display scenario-related advisory findings but must not route them into base-case apply. |
| MVP-14 | Evidence freshness/stale approval is hard. | Log packet timestamps and kind only; defer auto-staling to V2. |
| MVP-15 | Tests need to enforce the safety boundary. | Add contract, translator, loader, API, and integration tests before UI polish. |

## MVP User Flow

1. PM opens a ticker and chooses or runs an agentic analysis profile.
2. System builds profile-specific Evidence Packets with source refs, facts, and snippets.
3. The selected judgment agent adds anchored observations using the shared observation contract.
4. Translator maps supported observations into queue items:
   - advisory findings for qualitative insight
   - assumption change packs for model-relevant changes
5. PM reviews queue items in React:
   - inspect evidence anchors
   - preview valuation impact
   - edit proposed values
   - approve, reject, or defer
6. Approved base-case proposals create/update pending assumption changes and then approved assumption entries through the existing apply path.
7. Next valuation run consumes approved entries via `input_assembler.py`.
8. All material items remain searchable, including rejected and deferred insights.

## MVP Agentic Handoff Profiles

All profiles use the same contracts, store, queue, preview, approval, and search mechanics.

| Profile | Primary Agent / Source | Evidence Packet Kinds | Example Observations | Example Proposal Families |
| --- | --- | --- | --- | --- |
| `earnings_update` | `EarningsAgent` | earnings release, earnings 8-K, transcript, latest valuation snapshot | guidance raised/lowered, pricing pressure, demand softness/strength, tone shift | revenue growth, EBIT margin |
| `company_analysis` | `FilingsAgent`, `QoEAgent`, `AccountingRecastAgent` | 10-K/10-Q filing context, XBRL facts, QoE signals, accounting recast context | revenue recognition concern, margin quality issue, accounting reclass candidate, disclosure change | EBIT margin, EV bridge fields, growth |
| `industry_analysis` | `IndustryAgent` | sector context, peer operating metrics, industry events | industry growth improving/deteriorating, peer margins compressing, capacity/pricing shift | revenue growth, target margin, terminal growth |
| `comps_analysis` | comps/valuation review path | peer universe, peer similarity, multiples, business descriptions | weak peer comparability, multiple premium/discount unsupported, peer set drift | exit multiple, advisory finding |
| `risk_review` | `RiskAgent`, `RiskImpactAgent` | risk factors, sentiment risks, QoE risk context | risk severity increased, downside scenario needs review | advisory finding first; scenario overlay later |
| `valuation_review` | `ValuationAgent`, assumption register diagnostics | DCF output, source lineage, assumption register, valuation health flags | model assumption inconsistent with evidence, terminal value fragile, WACC method disagreement | growth, margin, WACC, terminal drivers |

## MVP Non-Goals

- No automatic stale approval invalidation.
- No fully bespoke workflow per agent; profiles must use the shared framework.
- No scenario overlay approval implementation in MVP, though scenario-related advisory findings may be stored.
- No replacement of `Recommendation` or `PendingAssumptionChange`; add adapter links first.
- No agent-created direct mutation of `ForecastDrivers`.
- No unrestricted model field proposal scope.

## Agent-Proposable Assumption Whitelist

MVP whitelist:

- `revenue_growth_near`
- `revenue_growth_mid`
- `ebit_margin_start`
- `ebit_margin_target`
- `exit_multiple`
- `terminal_growth`
- `ronic_terminal`
- `wacc`
- `lease_liabilities`
- `pension_deficit`
- `non_operating_assets`

Explicitly excluded from agent judgment:

- `shares_outstanding`
- raw `revenue_base`
- market price
- source identifiers
- raw CIQ/yfinance/SEC facts

## Translator Rules For First Pass

Use fixed rules with conservative default deltas. Exact values can be revised after testing.

| Observation Type | Direction | Proposal |
| --- | --- | --- |
| `guidance_revenue_raised` | upside | `revenue_growth_near +100 bps` |
| `guidance_revenue_lowered` | downside | `revenue_growth_near -100 bps` |
| `pricing_pressure_improved` | upside | `ebit_margin_start +50 bps` |
| `pricing_pressure_worsened` | downside | `ebit_margin_start -50 bps` |
| `demand_strength_broad` | upside | pack: `revenue_growth_near +100 bps`, `ebit_margin_target +50 bps` |
| `demand_softness_broad` | downside | pack: `revenue_growth_near -100 bps`, `ebit_margin_target -50 bps` |
| `execution_risk_increased` | downside | advisory finding only in MVP unless evidence gives a direct WACC/driver target |
| `margin_target_disclosed` | target | `ebit_margin_target = disclosed midpoint` |
| `revenue_growth_guidance_disclosed` | target | `revenue_growth_near = disclosed midpoint` |

## Task 1: Add Contracts

**Files:**
- Create: `src/contracts/evidence_packet.py`
- Create: `src/contracts/pm_decision_queue.py`
- Test: `tests/test_pm_decision_queue_contracts.py`

**Steps:**

1. Write failing tests for:
   - evidence packet facts vs observations
   - qualitative observation requiring text snippet anchor
   - queue item requiring at least one evidence anchor
   - delta and target proposal modes
   - PM-edited proposal preserving original and approved values
2. Implement Pydantic models:
   - `EvidencePacket`
   - `EvidencePacketFact`
   - `EvidencePacketObservation`
   - `EvidenceSourceRef`
   - `TextEvidenceSnippet`
   - `PMDecisionQueueItem`
   - `AssumptionChangeProposal`
   - `AssumptionChangePack`
   - enums for kind, item type, status, proposal mode, importance, confidence
3. Run:
   ```powershell
   rtk python -m pytest tests/test_pm_decision_queue_contracts.py -q
   ```

## Task 2: Add SQLite Store

**Files:**
- Modify: `db/schema.py`
- Modify: `db/loader.py`
- Test: `tests/test_pm_decision_queue_store.py`

**Tables:**

- `evidence_packets`
- `pm_decision_queue_items`
- `pm_decision_queue_events`

Use JSON columns for V1 payloads where full normalization would slow the MVP.

**Steps:**

1. Write loader tests for insert/load/list/update.
2. Add schema with indexes on:
   - ticker
   - evidence kind
   - queue status
   - item type
   - qualitative importance
   - valuation impact bucket or generated timestamp
3. Add loader helpers:
   - `insert_evidence_packet`
   - `load_evidence_packet`
   - `insert_pm_decision_queue_item`
   - `list_pm_decision_queue_items`
   - `update_pm_decision_queue_item`
   - `insert_pm_decision_queue_event`
4. Run:
   ```powershell
   rtk python -m pytest tests/test_pm_decision_queue_store.py -q
   ```

## Task 3: Add Agentic Handoff Profile Registry

**Files:**
- Create: `src/stage_04_pipeline/agentic_handoff_profiles.py`
- Test: `tests/test_agentic_handoff_profiles.py`

**Steps:**

1. Write failing tests for profile lookup and allowed packet/observation/proposal configuration.
2. Define profiles for:
   - `earnings_update`
   - `company_analysis`
   - `industry_analysis`
   - `comps_analysis`
   - `risk_review`
   - `valuation_review`
3. Each profile should declare:
   - source agent or service
   - Evidence Packet Kinds
   - allowed observation types
   - allowed assumption proposal fields
   - prompt key or prompt builder name
   - translator rule group
4. Run:
   ```powershell
   rtk python -m pytest tests/test_agentic_handoff_profiles.py -q
   ```

## Task 4: Build Generic Evidence Packet Service

**Files:**
- Create: `src/stage_04_pipeline/evidence_packets.py`
- Test: `tests/test_evidence_packet_builders.py`

**Steps:**

1. Write failing tests using stubbed filing, 8-K, industry, comps, valuation, and QoE/risk data.
2. Implement `build_evidence_packet(ticker, profile_name)` and profile-specific builder functions.
3. Include shared fields:
   - ticker
   - packet kind
   - source refs
   - facts
   - text snippets when qualitative observations will be allowed
   - run metadata
4. Minimum MVP builders:
   - earnings update
   - company analysis
   - industry analysis
   - comps analysis
   - valuation review
5. Persist via SQLite store.
6. Run:
   ```powershell
   rtk python -m pytest tests/test_evidence_packet_builders.py -q
   ```

## Task 5: Add Anchored Agent Observations

**Files:**
- Modify: `src/stage_03_judgment/earnings_agent.py`
- Modify: `src/stage_03_judgment/filings_agent.py`
- Modify: `src/stage_03_judgment/industry_agent.py`
- Modify: `src/stage_03_judgment/valuation_agent.py`
- Create: `src/stage_03_judgment/agentic_observations.py`
- Test: `tests/test_agentic_observations.py`

**Steps:**

1. Preserve current `analyze()` behavior for all agents.
2. Add shared helper(s) for packet-based observation generation.
3. Add a new method shape such as `analyze_evidence_packet(packet, profile)`.
4. Make the LLM return structured observations:
   - observation type
   - direction
   - qualitative importance
   - agent confidence
   - evidence anchors
   - text snippets for qualitative claims
5. Validate through `EvidencePacketObservation`.
6. Fail closed: invalid or unanchored observations are dropped or marked invalid, not promoted.
7. MVP should support at least earnings, company analysis, industry analysis, and valuation/comps review observations through the same contract.
8. Run:
   ```powershell
   rtk python -m pytest tests/test_agentic_observations.py -q
   ```

## Task 6: Add Observation-To-Assumption Translator

**Files:**
- Create: `src/stage_04_pipeline/observation_translator.py`
- Test: `tests/test_observation_translator.py`

**Steps:**

1. Write tests for each MVP translator rule.
2. Support `delta` and `target` proposal modes.
3. Enforce agent-proposable whitelist.
4. Select translator rules by `Agentic Handoff Profile`.
5. Create queue items for advisory findings and assumption change packs.
6. Store agent confidence and translator confidence separately.
7. Run:
   ```powershell
   rtk python -m pytest tests/test_observation_translator.py -q
   ```

## Task 7: Add Queue Adapter To Pending Assumptions

**Files:**
- Create: `src/stage_04_pipeline/pm_decision_queue.py`
- Modify: `src/stage_04_pipeline/pending_assumption_changes.py`
- Test: `tests/test_pm_decision_queue_adapter.py`

**Steps:**

1. Implement queue-level preview:
   - load queue item or pack
   - resolve delta/target to concrete values
   - call existing valuation preview helpers
2. Implement PM actions:
   - approve
   - reject
   - defer
   - edit proposed values
3. On approve, create linked `pending_assumption_changes` rows for base-case proposals.
4. Store adapter link back on the queue item.
5. Preserve:
   - original proposal
   - PM-edited proposal
   - final approved value
   - approval event history
6. Run:
   ```powershell
   rtk python -m pytest tests/test_pm_decision_queue_adapter.py -q
   ```

## Task 8: Add API Endpoints

**Files:**
- Modify: `api/main.py`
- Test: `tests/test_api_contracts.py`

**Endpoints:**

- `POST /api/tickers/{ticker}/agentic-handoff/{profile_name}/run`
- `GET /api/tickers/{ticker}/evidence-packets`
- `GET /api/tickers/{ticker}/pm-decision-queue`
- `POST /api/tickers/{ticker}/pm-decision-queue/{item_id}/preview`
- `POST /api/tickers/{ticker}/pm-decision-queue/{item_id}/edit`
- `POST /api/tickers/{ticker}/pm-decision-queue/{item_id}/approve`
- `POST /api/tickers/{ticker}/pm-decision-queue/{item_id}/reject`
- `POST /api/tickers/{ticker}/pm-decision-queue/{item_id}/defer`

**Steps:**

1. Add request/response models.
2. Keep API as transport only; route into `src/stage_04_pipeline/`.
3. Add contract tests with monkeypatched services.
4. Run:
   ```powershell
   rtk python -m pytest tests/test_api_contracts.py -q
   ```

## Task 9: Add React PM Decision Queue Surface

**Files:**
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/pages/ValuationPage.tsx`
- Modify or create focused components under `frontend/src/components/`
- Test/build: `npm --prefix frontend run build`

**UI Requirements:**

- Add a `PM Queue` or `Insights` subview under ticker valuation/research.
- Add profile run controls for earnings, company analysis, industry analysis, comps analysis, risk review, and valuation review.
- Show queue items with:
   - status
   - item type
   - qualitative importance
   - valuation impact
   - affected assumptions
   - evidence anchors
   - original proposed value
   - editable PM value
   - approve/reject/defer actions
- Search/filter:
   - status
   - item type
   - evidence kind
   - qualitative importance
   - high valuation impact
- Show evidence snippets inline or in an expandable evidence drawer.
- Do not hide rejected/deferred material insights.

**Steps:**

1. Add client methods.
2. Add queue data query.
3. Add preview/edit/approve/reject/defer mutations.
4. Invalidate valuation assumptions and summary after approval.
5. Run:
   ```powershell
   npm --prefix frontend run build
   ```

## Task 10: Add End-To-End Smoke Test

**Files:**
- Create: `tests/test_agentic_handoff_mvp_flow.py`

**Steps:**

1. Stub evidence packet inputs.
2. Stub observations for at least two profiles, one earnings profile and one non-earnings profile.
3. Run translator.
4. Persist queue item.
5. Preview valuation impact.
6. PM edits value.
7. Approve item.
8. Assert linked pending assumption row and approved entry path works.
9. Run:
   ```powershell
   rtk python -m pytest tests/test_agentic_handoff_mvp_flow.py -q
   ```

## Task 11: Documentation And Verification

**Files:**
- Modify: `docs/design-docs/agent-feedback-loop-and-comps-gaps.md`
- Modify: `docs/handbook/workflow-end-to-end.md`
- Modify: `docs/design-docs/index.md` if a new design doc is created
- Keep: `CONTEXT.md`

**Steps:**

1. Document the MVP flow and non-goals.
2. Document PM review semantics and evidence anchoring.
3. Add operator instructions for running agentic handoff profiles.
4. Run:
   ```powershell
   rtk python -m mkdocs build --strict
   rtk python -m pytest tests/test_pm_decision_queue_contracts.py tests/test_pm_decision_queue_store.py tests/test_agentic_handoff_profiles.py tests/test_evidence_packet_builders.py tests/test_agentic_observations.py tests/test_observation_translator.py tests/test_pm_decision_queue_adapter.py tests/test_api_contracts.py tests/test_agentic_handoff_mvp_flow.py -q
   npm --prefix frontend run build
   ```

## Acceptance Criteria

- A ticker can generate Evidence Packets through the shared profile-driven builder.
- At least two profiles, including one non-earnings profile, can produce anchored observations through the shared contract.
- Unanchored observations cannot become queue items.
- Translator creates symmetric, conservative assumption proposals from fixed rules.
- Translator rules are selected by Agentic Handoff Profile, not hardcoded to one agent.
- PM can preview, edit, approve, reject, or defer a queue item.
- Approved base-case proposals route through existing pending/approved assumption path.
- Deterministic valuation consumes only approved values.
- Queue/search surface shows approved, rejected, and deferred material insights.
- React build passes.
- Focused pytest suite passes.
- MkDocs strict build passes.

## Follow-On After MVP

- Add market context packets.
- Broaden profile coverage and translator rules after real PM testing.
- Add scenario overlay queue type and separate approval path.
- Add evidence-driven stale approval invalidation.
- Promote translator constants into editable policy.
- Add ranking by learned PM preferences.
- Add better full-text search over evidence snippets and PM notes.
