# Agentic Handoff MVP Hardening Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.
> **For Codex:** Use `/goals` with the goal prompt below, then execute this file in order. Use TDD where practical, keep changes small, and verify after each task.

**Goal:** Turn the current Universal Agentic Handoff scaffold into a real MVP that can be safely tested on live ticker workflows without synthetic evidence, silent agent failures, or unsafe valuation override semantics.

**Architecture:** Preserve the existing boundary: deterministic layers build evidence and apply approved values; LLM agents only create anchored observations; the deterministic translator creates PM-reviewable proposals; the PM Queue is the only approval bridge back into deterministic valuation. The first priority is safety and evidence integrity, then broader profile coverage and UI polish.

**Tech Stack:** Python, Pydantic, SQLite, FastAPI, React, TypeScript, Vite, pytest, Vitest, RTK command wrapper.

---

## `/goals` Prompt

Use this as the goal prompt in a fresh Codex session:

```text
Build the Alpha Pod Agentic Handoff MVP hardening pass from docs/plans/active/2026-05-22-agentic-handoff-mvp-hardening.md.

Primary objective: make the current Evidence Packet -> Agent Observation -> Translator -> PM Decision Queue -> Preview/Edit/Approve workflow safe for real-world ticker testing.

Non-negotiables:
- No synthetic placeholder evidence may create PM Queue items.
- Previewed PM Queue values must exactly match approved/applied deterministic overrides.
- Agent failures must be visible, not silently swallowed.
- Evidence packets must persist their generated observations or linked observation run records.
- Every completed task must include targeted tests and verification commands.
- Keep the LLM boundary intact: agents suggest anchored observations only; deterministic code translates and applies approved values.

Work task-by-task. After each task, run the listed verification checks and report pass/fail with file references.
```

## Current Known Problems

- `src/stage_04_pipeline/evidence_packets.py` uses hardcoded placeholder facts and snippets.
- `src/stage_04_pipeline/pm_decision_queue.py` previews delta proposals as `current + delta` but approves the raw delta as the applied value.
- `api/main.py` swallows agent failures and returns empty observations.
- Evidence packets are inserted before observations and are not updated after observations are generated.
- `src/stage_04_pipeline/observation_translator.py` drops agent confidence because enum values are stringified incorrectly.
- The current profile registry is a scaffold, not a complete agent coverage map.
- Frontend PM Queue exists, but it is not yet enough for high-confidence PM workflow testing.

## Global Implementation Rules

- Do not allow LLM output to write directly into deterministic valuation inputs.
- Use existing pending assumption approval machinery, but fix it so deltas are resolved before approval.
- Prefer small adapters over broad rewrites.
- Keep existing tests passing unless a test is intentionally replaced by a stricter contract.
- Use `rtk` for shell commands where possible.
- Stage only intentional files.

## Task 1: Lock Down Delta Approval Safety

**Goal:** Ensure PM Queue preview and approval apply the same absolute value.

**Files:**
- Modify: `src/stage_04_pipeline/pm_decision_queue.py`
- Test: `tests/test_pm_decision_queue_adapter.py`
- Optional test: `tests/test_agentic_handoff_mvp_flow.py`

**Steps:**

1. Add a failing test for a delta proposal where the deterministic driver currently has `revenue_growth_near = 0.07` and the proposal delta is `+0.01`.
2. Assert preview manual values show `revenue_growth_near = 0.08`.
3. Approve the same queue item without PM editing.
4. Assert the approved assumption entry value is `0.08`, not `0.01`.
5. Add a second test for target proposals to ensure target approval still applies the target value unchanged.
6. Implement a shared resolver that converts each active proposal into an absolute proposed value.
7. Use that resolver in both preview and approve.
8. If a delta cannot be resolved because the field is absent from valuation drivers, approval must not apply that proposal.
9. Store skipped/unresolvable fields in `adapter_links` and decision history.

**Verification:**

```powershell
rtk python -m pytest tests/test_pm_decision_queue_adapter.py -q
rtk python -m pytest tests/test_agentic_handoff_mvp_flow.py -q
```

**Expected:** Both commands pass. The test suite must prove delta approval applies absolute values.

**Commit message:**

```text
fix: resolve pm queue deltas before approval
```

## Task 2: Block Synthetic Evidence From Creating Queue Items

**Goal:** Prevent placeholder evidence packets from being treated as real PM insights.

**Files:**
- Modify: `src/contracts/evidence_packet.py`
- Modify: `src/stage_04_pipeline/evidence_packets.py`
- Modify: `api/main.py`
- Test: `tests/test_evidence_packet_builders.py`
- Test: `tests/test_agentic_handoff_mvp_flow.py`

**Steps:**

1. Add packet metadata fields or a clear metadata convention for `source_quality`, with values like `real`, `partial`, and `placeholder`.
2. Add a failing test proving a placeholder packet can be built for UI/demo visibility but cannot create observations or queue items.
3. Remove hardcoded business claims like fake guidance raises, fake peer multiples, and fake WACC debates from default packet creation.
4. For unsupported or insufficient data, return a packet with real metadata explaining the missing source, not invented values.
5. In `run_agentic_handoff_profile_payload`, fail closed when `source_quality = placeholder`.
6. Return a structured API payload with `status = "blocked"` and `reason = "insufficient_real_evidence"` when packet evidence is not real enough.
7. Ensure no queue items are inserted for placeholder packets.

**Verification:**

```powershell
rtk python -m pytest tests/test_evidence_packet_builders.py tests/test_agentic_handoff_mvp_flow.py -q
rtk rg -n "strong demand|Peer average multiple of 18.5|Default evidence placeholder|midpoint_revenue_guidance.*12500" src/stage_04_pipeline/evidence_packets.py
```

**Expected:** Tests pass. The `rg` command should not find invented business claims in production packet builders.

**Commit message:**

```text
fix: block placeholder evidence from pm queue
```

## Task 3: Build Real Evidence Packet Inputs For MVP Profiles

**Goal:** Replace the placeholder packet skeleton with real deterministic packet builders for the minimum useful profile set.

**Files:**
- Modify: `src/stage_04_pipeline/evidence_packets.py`
- Possibly read/use: `src/stage_00_data/filing_retrieval.py`
- Possibly read/use: `src/stage_00_data/edgar_client.py`
- Possibly read/use: `src/stage_02_valuation/input_assembler.py`
- Possibly read/use: `src/stage_04_pipeline/comps_dashboard.py`
- Possibly read/use: `src/stage_04_pipeline/builders.py`
- Test: `tests/test_evidence_packet_builders.py`

**Minimum MVP profiles:**

- `company_analysis`: latest curated filing context, filing source refs, extracted filing snippets, available filing facts.
- `earnings_update`: recent 8-K earnings context when available, EPS/market metadata if available, explicit missing-data metadata otherwise.
- `valuation_review`: deterministic valuation drivers and scenario outputs from existing valuation input/DCF surfaces.
- `comps_analysis`: existing comps dashboard/peer output if available; otherwise real missing-data packet, not invented peer multiple.

**Steps:**

1. Add tests that monkeypatch each deterministic data source and assert packet builders preserve source ids, facts, snippets, and metadata.
2. Add tests for missing source data and assert `source_quality` becomes `partial` or `placeholder`.
3. Implement small per-profile collector functions instead of one large `_collect_profile_inputs`.
4. Keep snippets short and source-located.
5. Include `source_locator` values that a PM can use later to trace the packet.
6. Add `run_metadata` showing which collectors succeeded and failed.
7. Ensure packet IDs remain stable only after DB insert; do not invent persistent IDs.

**Verification:**

```powershell
rtk python -m pytest tests/test_evidence_packet_builders.py -q
rtk python -m pytest tests/test_agentic_handoff_mvp_flow.py -q
```

**Expected:** Tests prove packets are built from monkeypatched real sources and missing data does not create fake facts.

**Commit message:**

```text
feat: build real evidence packets for mvp profiles
```

## Task 4: Persist Observations And Surface Agent Failures

**Goal:** Make agent execution auditable in SQLite and visible through the API/UI.

**Files:**
- Modify: `db/schema.py`
- Modify: `db/loader.py`
- Modify: `api/main.py`
- Modify: `src/stage_04_pipeline/evidence_packets.py`
- Test: `tests/test_pm_decision_queue_store.py`
- Test: `tests/test_api_contracts.py`
- Test: `tests/test_agentic_handoff_mvp_flow.py`

**Steps:**

1. Add a failing test proving generated observations are persisted and returned by `GET /api/tickers/{ticker}/evidence-packets`.
2. Add a failing API contract test where an agent raises and the response contains a structured failure.
3. Add a DB loader helper to update `evidence_packets.observations_json` after agent execution.
4. Consider adding a lightweight `agentic_handoff_runs` table if needed for durable run status; if not, store run status in packet metadata.
5. Replace `except Exception: observations = []` with structured error capture.
6. Return `status`, `errors`, `observation_count`, and `queue_item_count` from the run endpoint.
7. Ensure failed agent runs do not create queue items.

**Verification:**

```powershell
rtk python -m pytest tests/test_pm_decision_queue_store.py tests/test_api_contracts.py tests/test_agentic_handoff_mvp_flow.py -q
```

**Expected:** API tests prove failures are visible and observations persist when successful.

**Commit message:**

```text
feat: persist agentic observations and run errors
```

## Task 5: Fix Translator Enum Handling And Validation

**Goal:** Preserve agent confidence and tighten queue item validation.

**Files:**
- Modify: `src/stage_04_pipeline/observation_translator.py`
- Modify: `src/contracts/pm_decision_queue.py`
- Test: `tests/test_observation_translator.py`
- Test: `tests/test_pm_decision_queue_contracts.py`

**Steps:**

1. Add a failing test where `EvidenceConfidence.high` translates to `QueueConfidence.high`.
2. Fix `_to_queue_confidence` to use `.value` when given enum-like values.
3. Add tests for advisory findings and assumption packs preserving qualitative importance.
4. Add validation that assumption change queue items must include a proposal pack.
5. Add validation that advisory findings must not pretend to have an approved proposal pack.
6. Add validation that queue item evidence packet IDs and anchor IDs are non-empty for items created from observations.

**Verification:**

```powershell
rtk python -m pytest tests/test_observation_translator.py tests/test_pm_decision_queue_contracts.py -q
```

**Expected:** Translator preserves confidence and queue contracts reject malformed items.

**Commit message:**

```text
fix: preserve translator confidence metadata
```

## Task 6: Use A Single Grounded Observation Runner

**Goal:** Make the MVP handoff easy to audit by using one basic LLM runner for every runnable profile while keeping profile-specific evidence payloads, prompt guidance, and translator rules.

**Files:**
- Modify: `src/stage_04_pipeline/agentic_handoff_profiles.py`
- Modify: `api/main.py`
- Modify: `src/stage_03_judgment/agentic_observations.py`
- Create: `src/stage_03_judgment/grounded_observation_agent.py`
- Test: `tests/test_agentic_handoff_profiles.py`
- Test: `tests/test_agentic_observations.py`

**MVP runner ownership:**

- All runnable MVP profiles use `GroundedObservationAgent`.
- Profile-specific collectors still build different deterministic evidence packets.
- Profile-specific prompt guidance, allowed observation types, allowed fields, and translator rule groups stay in `agentic_handoff_profiles.py`.
- Legacy specialist agents remain available for the older dossier/orchestrator pipeline.

**Steps:**

1. Add a test that every runnable profile declares `runner_key = "grounded_observation"`, allowed observation types, allowed fields, and evidence packet kind.
2. Remove MVP handoff routing through `EarningsAgent`, `FilingsAgent`, `IndustryAgent`, `CompsAgent`, `RiskAgent`, and `ValuationAgent`.
3. Add `GroundedObservationAgent` as the single profile-agnostic runner over completed evidence packets.
4. Keep the two-pass extraction then JSON-formatting prompt flow, but make the system prompt profile-aware.
5. Add prompt sections that are profile-specific but share one observation schema.
6. Ensure the runner says observations only, not deterministic model edits.
7. Ensure profile-specific allowed observation types are included in the prompt.

**Verification:**

```powershell
rtk python -m pytest tests/test_agentic_handoff_profiles.py tests/test_agentic_observations.py tests/test_api_contracts.py -q
```

**Expected:** Unknown or incomplete profiles fail closed; all runnable MVP profiles use the same grounded runner.

**Commit message:**

```text
feat: unify agentic handoff observation runner
```

## Task 7: Strengthen PM Queue API Contracts

**Goal:** Make queue operations reliable enough for the React MVP.

**Files:**
- Modify: `api/main.py`
- Modify: `db/loader.py`
- Test: `tests/test_api_contracts.py`
- Test: `tests/test_pm_decision_queue_store.py`

**Steps:**

1. Add API contract tests for list filters: `status`, `item_type`, `qualitative_importance`, and `valuation_impact_bucket`.
2. Add tests for preview/edit/approve/reject/defer returning stable response shapes.
3. Add tests proving approved/rejected/deferred items remain searchable.
4. Add tests proving duplicate queue items are not created for the same packet observation unless explicitly rerun with a new packet.
5. Add stable ordering by importance and updated time.
6. Ensure errors use useful HTTP status codes and messages.

**Verification:**

```powershell
rtk python -m pytest tests/test_api_contracts.py tests/test_pm_decision_queue_store.py -q
```

**Expected:** API response shapes are stable and filters work.

**Commit message:**

```text
test: harden pm queue api contracts
```

## Task 8: Upgrade React PM Queue For MVP Testing

**Goal:** Make the PM Queue usable for real PM review, not just demo flow.

**Files:**
- Modify: `frontend/src/pages/ValuationPage.tsx`
- Modify: `frontend/src/lib/api.ts`
- Modify: `frontend/src/lib/types.ts`
- Test: `frontend/src/test/appRoutes.test.tsx`

**UI requirements:**

- Show run result status for each profile run.
- Distinguish `blocked`, `failed`, `completed_no_items`, and `completed_with_items`.
- Show source quality on evidence packets.
- Show evidence snippets/facts inline for each queue item.
- Show original proposal, PM edited proposal, and approved proposal separately.
- Show preview value and approved value clearly.
- Allow PM to approve only after preview when the item has an assumption change pack.
- Keep reject/defer available for advisory findings.

**Steps:**

1. Add failing UI tests around PM Queue empty states and failed profile run states.
2. Add typed API fields for run status, errors, source quality, and skipped fields.
3. Add visible source-quality badges to evidence packet cards.
4. Add proposal comparison display: original, edited, approved.
5. Disable approve for unpreviewed assumption changes if preview is required by backend state.
6. Add a warning when a proposal has skipped fields.
7. Keep the UI responsive on mobile-width layouts.

**Verification:**

```powershell
rtk npm --prefix frontend run build
rtk npm --prefix frontend test -- appRoutes.test.tsx
```

If the exact frontend test command is not available, inspect `frontend/package.json` and run the project’s existing test command.

**Expected:** Build passes and route tests cover PM Queue states.

**Commit message:**

```text
feat: make pm queue ui mvp-testable
```

## Task 9: Add End-To-End MVP Smoke Verification

**Goal:** Provide one repeatable command that proves the MVP loop is safe enough for manual testing.

**Files:**
- Create: `scripts/manual/smoke_agentic_handoff_mvp.py`
- Test or docs: `docs/handbook/agentic-handoff-mvp.md`
- Modify: `docs/handbook/workflow-end-to-end.md`

**Steps:**

1. Create a script that runs against one or two tickers with local available data.
2. Script should build evidence packets for runnable profiles.
3. Script should fail if any queue item is created from placeholder evidence.
4. Script should fail if an approval applies a value different from preview.
5. Script should print packet count, observation count, queue item count, skipped fields, and failures.
6. Add handbook instructions explaining how the PM should run profiles and inspect the queue.
7. Document known MVP limitations clearly.

**Verification:**

```powershell
rtk python scripts/manual/smoke_agentic_handoff_mvp.py --ticker IBM
rtk python -m pytest tests/test_agentic_handoff_mvp_flow.py -q
```

**Expected:** Smoke script gives a clear pass/fail result and does not require network access for fixture-backed tests.

**Commit message:**

```text
chore: add agentic handoff mvp smoke check
```

## Task 10: Clean Plan And Session Handoff Docs

**Goal:** Leave the repo easy for the next agent to navigate.

**Files:**
- Modify: `docs/plans/index.md`
- Move or remove duplicate lifecycle plan: `docs/plans/active/2026-05-21-agentic-handoff-mvp.md`
- Move or keep completed lifecycle plan: `docs/plans/completed/2026-05-21-agentic-handoff-mvp.md`
- Modify: `.agent/session-state.md`

**Steps:**

1. Ensure each canonical plan exists in exactly one lifecycle folder.
2. Add this hardening plan to the active plan registry.
3. Keep shipped historical implementation notes in `completed/`.
4. Update `.agent/session-state.md` before ending the implementation session.
5. Mention verification commands and remaining known gaps.

**Verification:**

```powershell
rtk rg -n "2026-05-21-agentic-handoff-mvp" docs/plans
rtk powershell -NoProfile -Command "Get-Content docs/plans/index.md | Select-Object -First 80"
```

**Expected:** The old MVP plan is not duplicated across active and completed folders, and this hardening plan appears under active plans.

**Commit message:**

```text
docs: update agentic handoff mvp plan registry
```

## Task 11: v0.1 Alpha Decision-Room Layer

**Goal:** Make the PM Queue usable for daily alpha testing, not only backend debugging.

**Files:**
- Modify: `src/stage_04_pipeline/pm_decision_queue.py`
- Modify: `src/stage_04_pipeline/observation_translator.py`
- Modify: `src/stage_03_judgment/agentic_observations.py`
- Modify: `api/main.py`
- Modify: `frontend/src/pages/ValuationPage.tsx`
- Modify: `frontend/src/lib/types.ts`
- Test: `tests/test_agentic_observations.py`
- Test: `tests/test_observation_translator.py`
- Test: `tests/test_api_contracts.py`
- Test: `frontend/src/test/appRoutes.test.tsx`

**Steps:**

1. Group pending assumption-change queue items by ticker and deterministic assumption field.
2. Expose conflict groups in the PM Queue list API.
3. Stamp packet provenance into queue item metadata during deterministic translation.
4. Require the public handoff translation path to receive the source evidence packet.
5. Persist agent observation artifacts and parser rejection reasons into packet run metadata.
6. Return preview fingerprint and preview timestamp from the preview API.
7. Map stale preview approval attempts to HTTP 409.
8. Add PM Queue UI sections for shared-driver conflicts, observation context, field-level preview details, decision history, and reject/defer reasons.
9. Add source quality, confidence, impact bucket, and status filtering in the UI.

**Verification:**

```powershell
rtk python -m pytest tests/test_agentic_observations.py tests/test_observation_translator.py tests/test_api_contracts.py tests/test_pm_decision_queue_adapter.py -q
rtk npm --prefix frontend test -- appRoutes.test.tsx
rtk npm --prefix frontend run build
```

**Expected:** Backend contracts prove conflict groups, provenance, fail-closed translation, parser diagnostics, preview fingerprints, and stale-preview 409s. Frontend tests prove the decision-room UI renders conflict groups, observation context, preview details, and preview-gated approval.

**Commit message:**

```text
feat: add pm queue alpha decision room
```

## Final Verification Gate

Run these before calling the MVP hardening pass complete:

```powershell
rtk python -m pytest tests/test_pm_decision_queue_contracts.py tests/test_pm_decision_queue_store.py tests/test_agentic_handoff_profiles.py tests/test_evidence_packet_builders.py tests/test_agentic_observations.py tests/test_observation_translator.py tests/test_pm_decision_queue_adapter.py tests/test_api_contracts.py tests/test_agentic_handoff_mvp_flow.py -q
rtk npm --prefix frontend run build
rtk python scripts/manual/smoke_agentic_handoff_mvp.py --ticker IBM
rtk git status -sb
```

Expected final state:

- Backend tests pass.
- Frontend build passes.
- Smoke script passes or reports only documented missing local data.
- No PM Queue item is created from placeholder evidence.
- Delta preview equals approved/applied value.
- Agent failures are visible in API/UI.
- Evidence packets retain observations or linked run records.
- Worktree contains only intentional tracked changes plus known ignored local runtime artifacts.

## Out Of Scope For This MVP

- Fully autonomous portfolio changes.
- LLM-written deterministic valuation assumptions.
- Multi-agent debate workflows.
- News/web ingestion that requires new paid data sources.
- Advanced qualitative “market outlook unstable” classifiers.
- Rich long-term insight search and ranking beyond basic PM Queue filters.

## Suggested Implementation Order

1. Task 1: Delta approval safety.
2. Task 2: Block synthetic evidence.
3. Task 4: Persist observations and failures.
4. Task 5: Translator enum validation.
5. Task 3: Real packet inputs.
6. Task 6: Explicit profiles.
7. Task 7: API contracts.
8. Task 8: React PM Queue.
9. Task 9: Smoke verification.
10. Task 10: Docs and handoff.

This order intentionally fixes safety before expanding capability.
