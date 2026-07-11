# Accounting Evidence Packs And Focused Repair Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.
> **For Codex:** Use this plan task-by-task with TDD where practical. Stop at the PM finance-semantics checkpoint before implementing unresolved treatment rules.

**Goal:** Make the guided weekly loop produce finance-useful accounting/QoE evidence and repair semantically invalid proposals once before dropping them, while keeping all valuation mutations behind the PM Decision Queue.

**Architecture:** Add a deterministic accounting evidence assembly layer that retrieves note-specific filing sections and existing balance-sheet/QoE facts, then dispatch several narrow topic packets to focused judgment calls. Each call returns a small typed finding or an explicit no-adjustment/missing-evidence result. A deterministic validator checks schema, evidence anchors, accounting-topic completeness, and proposed-driver alignment; parse or semantic failures receive one targeted repair prompt with the exact rejection reason before the finding is discarded. Valid findings merge into an accounting adjustment ledger and only material PM-review candidates enter the queue.

**Tech Stack:** Python 3.13, typed dataclasses/Pydantic contracts, SQLite evidence-packet persistence, EDGAR section/chunk retrieval, existing CIQ/yfinance valuation inputs, `BaseAgent` Codex routing, pytest offline fixtures, Markdown run artifacts.

## Implementation Status

- **Tasks 1–3 complete:** the item-123 semantic failure is frozen in offline tests; typed accounting packet/finding/repair contracts exist; and four deterministic topic packet builders now preserve filing locators, selected section keys, bridge facts, QoE signals, and explicit retrieval coverage states.
- **Retrieval hardening complete:** parser version `sections_v5` repairs split `FINANCI AL` headings, avoids the broad TOC span, extracts body headings such as leases/taxes/fair value/revenue/SBC, and query version `v5` uses section-diverse focused selection. Packet collectors filter unrelated topic sections before handoff.
- **XBRL Slice A complete:** structured `FinancialFact` normalization preserves filing vintage, context, dimensions, statement metadata, and accession-index provenance; exact concept filtering and newest-vintage ordering are covered offline.
- **XBRL Slice B complete:** all four persisted accounting packet builders now add topic-bounded XBRL facts and accession-level source refs, while retaining existing note snippets and deterministic accounting facts. Cache-only mode reports `cache_only_unavailable` without constructing an SEC client.
- **Checkpoint:** focused verification is green (`83 passed, 1 warning`; the warning is the existing Windows `.pytest_cache` permission issue). Focused dispatch, repair integration, queue translation, guided-run wiring, and exact Inline XBRL DOM anchors remain pending review.

## XBRL Provenance Direction (Exploration Outcome)

The repository already uses SEC Company Facts through `edgartools` for deterministic
numeric fallbacks, but the current path is not evidence-grade: it converts
`FinancialFact` objects to a reduced DataFrame and drops dimensions, context refs,
taxonomy, accession, filing vintage, and statement hierarchy before the accounting
packets see them. The installed `edgartools` version exposes those fields on
`FinancialFact`, plus `EntityFiling.filing_url`, `EntityFiling.html()`,
`EntityFiling.document`, `EntityFiling.xbrl()`, and `XBRL.footnotes`.

The bounded direction is XBRL-first for numeric facts and filing provenance, with
Inline XBRL/HTML retained for note headings, narrative explanation, and exact
surrounding disclosure text. XBRL is not a wholesale replacement for qualitative
note retrieval: company extensions, dimensions, block tags, and narrative context
still require the source document. This slice must not change valuation treatment
or introduce automatic accounting adjustments.

### XBRL Slice A: Preserve structured fact provenance before packet integration

**Files:**
- Create: `src/stage_00_data/xbrl_evidence.py`
- Test: `tests/test_xbrl_evidence.py`
- Modify: `docs/handbook/workflow-end-to-end.md` only after the adapter contract is verified

**Steps:**

1. Write offline tests using small `FinancialFact` fixtures. Assert that normalized
   records retain concept/taxonomy/label/value/unit/period, accession/filing date/form,
   context ref/dimensions, statement metadata, and a stable SEC accession-index
   locator.
2. Implement a pure normalizer that accepts `FinancialFact` objects and produces
   evidence records without applying accounting judgments or collapsing dimensioned
   facts into an undimensioned total.
3. Implement a live adapter that calls `Company(ticker).get_facts()`, uses
   `query().by_concept(...).execute()` rather than the reduced DataFrame path, and
   returns explicit `no_facts`/`error` status instead of silently fabricating values.
4. Keep source locators at filing-index level for this slice. Exact fact anchors are
   a later HTML/Inline XBRL task because the current `edgartools` fact model retains
   `context_ref` but not the source DOM element id.
5. Run the focused XBRL tests and the existing accounting packet tests. Stop for
   review before wiring the adapter into packet persistence or guided dispatch.

### XBRL Slice B: Add structured facts to the four persisted accounting packets

**Files:**
- Modify: `src/stage_04_pipeline/evidence_packets.py`
- Test: `tests/test_evidence_packet_builders.py`
- Test: `tests/test_xbrl_evidence.py`

**Steps:**

1. Add bounded, topic-specific XBRL concept lists to the four accounting packet
   configurations. Keep segment facts dimensioned and do not infer litigation,
   guarantee, or policy conclusions from missing XBRL concepts.
2. Add one additive collector that converts normalized XBRL records into ordinary
   `EvidencePacketFact` rows while retaining the normalized fact ID and provenance.
3. Add one SEC accession-index `EvidenceSourceRef` per XBRL filing vintage and record
   adapter status, fact count, concept list, and errors in packet metadata.
4. Make cache-only mode skip `Company.get_facts()` and report
   `cache_only_unavailable`; this is not equivalent to `no_matching_facts`.
5. Verify all four packet builders, packet persistence round-trip, cache-only MSFT
   behavior, and the live adapter path without running agents or applying queue items.
6. Stop for review before adding exact Inline XBRL DOM anchors or changing guided-run
   dispatch.

**Verified 2026-07-11:** cache-only MSFT packets 200–203 reported
`cache_only_unavailable` with zero XBRL facts; the live four-packet smoke persisted
packets 204–207 with 84/96/60/36 XBRL facts for QoE/bridge/taxes/segments. A direct
live adapter probe returned six recent MSFT facts and exact concept filtering.

## Focused Subpacket Dispatch Revision

This revision serves Vision Decisions 1, 2, 10, 11, and 12. The previous
discussion of “one finding per call” was too restrictive and is replaced here:

- The full accounting packet remains the persisted audit artifact.
- A deterministic selector projects that packet into small agent-facing focus
  subpackets.
- Each focus call may return zero, one, or multiple independent findings. The
  system must not merge separate SBC, restructuring, and impairment issues merely
  to satisfy an artificial one-finding limit.
- Engineering guards may cap response size (initially six findings or the normal
  payload limit). An overflow is a diagnosable response requiring a narrower retry
  or a further focus split; it must never silently truncate findings.
- Validation and repair operate per finding where possible. Valid sibling findings
  survive an invalid sibling's repair attempt.

### Focus Registry

The four existing accounting families become summary/grouping labels. Dispatch is
performed at the following focus level:

| Focus key | Primary evidence | Typical driver fields |
|---|---|---|
| `qoe_revenue` | revenue, contract assets/liabilities, receivables, deferred revenue, recognition notes | `revenue_growth_near`, `revenue_growth_mid` |
| `qoe_opex_and_compensation` | COGS, R&D, S&M, G&A, SBC, compensation notes | `ebit_margin_start`, `ebit_margin_target` |
| `qoe_nonrecurring` | restructuring, impairment, acquisition, severance, auditor flags | `ebit_margin_target` |
| `qoe_cash_conversion` | CFO, capex, D&A, accruals, DSO/DIO/DPO, working-capital notes | advisory/disclosure first; no hidden universal driver |
| `bridge_cash_debt_investments` | cash, investments, debt, net-debt reconciliation | `net_debt`, `non_operating_assets` |
| `bridge_leases_pensions_claims` | operating/finance leases, pension, minority interest, preferred equity | `lease_liabilities`, `pension_deficit`, `minority_interest`, `preferred_equity` |
| `tax_contingencies` | tax expense/rate, uncertain tax positions, litigation, guarantees, commitments | `tax_rate_start`, `tax_rate_target`, `net_debt`, scenario-only treatment |
| `segments_disclosure` | segment revenue/profit/margins, mix, recast/discontinued disclosure | `revenue_growth_near`, `revenue_growth_mid`, `ebit_margin_target` |

This is a reasoning split, not just a statement-section split. Two facts belong in
the same subpacket when they support the same accounting question and valuation
treatment. Segment facts retain their dimensions; bridge facts do not become
segment facts simply because they share a filing.

### Agent-Facing Context Contract

Add a deterministic focus projection to the existing
`FocusedAccountingEvidencePacket` rather than sending the full persisted packet to
the model. Each projection should target:

- 10–25 selected facts, with the latest relevant filing and comparable periods
  retained together;
- 2–5 topic-matched filing snippets;
- 1–3 allowed driver fields;
- explicit `focus_key`, parent packet id, period/vintage metadata, and missing-data
  status.

The full 96-fact bridge packet remains available for audit/replay. The agent sees a
smaller, current-period-oriented view. Facts omitted from the prompt are not deleted
from the persisted evidence artifact.

### Multi-Finding Response And Repair Contract

The response envelope should contain:

```json
{
  "focus_key": "qoe_nonrecurring",
  "packet_status": "complete",
  "findings": [
    { "...": "AccountingFinding 1" },
    { "...": "AccountingFinding 2" }
  ],
  "coverage_notes": []
}
```

Rules:

1. A focus call can return multiple findings when they are separately anchored and
   separately actionable. For example, SBC and restructuring may be two findings.
2. Each finding gets a stable `finding_id` and `focus_key`; add these to the typed
   contract before dispatch is implemented.
3. A syntax/schema failure retries the whole envelope once.
4. A semantic failure identifies the invalid finding by `finding_id`, sends that
   finding plus the exact rejection reason/evidence/allowed drivers for repair, and
   retains valid sibling findings.
5. A failed repair persists the invalid finding and both attempts as
   `rejected_after_repair`; it does not erase the other findings.
6. `no_adjustment_identified` and `missing_evidence` remain explicit per-finding or
   per-focus outcomes and do not silently become queue mutations.

### Deterministic Merge And Conflict Handling

After validation, merge findings into an accounting ledger using a deterministic
fingerprint based on focus, line item, period, proposed driver, and evidence
anchors. Do not merge merely because two findings mention “margin.”

- Duplicate findings from overlapping focus packets are marked as duplicates with
  their provenance retained.
- Contradictory findings remain visible in a conflict group and are not silently
  resolved by the agent or translator.
- Each distinct valid candidate may produce its own PM Queue item; queue volume is
  handled by ranking/deduplication, not by collapsing accounting reasoning upstream.

### Implementation Batch Before Guided-Run Integration

1. **Focus registry and contract:** add focus keys, parent topics, concept/note maps,
   allowed drivers, `finding_id`, and response-envelope models.
2. **Deterministic selector:** write failing tests for current/comparative period
   selection, dimension preservation, exact concept filtering, fact/snippet budgets,
   and explicit missing evidence; then implement the selector.
3. **Multi-finding repair:** write tests for two valid findings, one valid plus one
   invalid finding, syntax retry, item-level semantic retry, and failed repair; then
   implement per-item validation/repair preservation.
4. **Ledger/queue translation:** write tests for duplicate fingerprints, conflicts,
   multiple queue candidates, and no-adjustment outcomes; then add deterministic
   merge and translation.
5. **MSFT focus smoke:** run the eight focus projections, inspect prompt-sized
   artifacts, and compare the findings against the current broad packet before
   enabling the guided weekly loop.

---

## Vision Decisions Served

- **Decision 1:** accounting judgment remains advisory; no agent writes valuation inputs directly.
- **Decision 2:** focused packets reduce PM review noise and support the daily review cadence.
- **Decision 10:** the contract makes ambiguous accounting claims explicit instead of silently translating them.
- **Decision 11:** finance treatment questions remain PM-owned; engineering validation and retry behavior are conservative and logged here.
- **Decision 12:** real ticker workups should produce decision-ready accounting evidence without manual note-surgery.

## PM Finance-Semantics Checkpoint

Before implementation reaches proposal sizing or queue materiality, confirm these choices with the PM:

1. The first version proposes accounting treatments but never auto-applies them.
2. `SBC`, leases, pension, tax contingencies, investments, and minority interest remain separate candidate categories; the system does not assume an adjustment direction merely because a line exists.
3. A finding can be `no_adjustment_identified` or `missing_evidence`, and neither state creates a valuation override.
4. Contingencies may be flagged for scenario treatment without being forced into normalized EBIT.
5. Peer/EV convention questions, especially lease treatment, are surfaced for PM review rather than resolved by a hidden universal rule.

If any of these finance meanings change, update this plan before implementation.

## Current-State Diagnosis

The 2026-07-11 MSFT guided run exposed the boundary problem:

- `company_analysis` received revenue/margin facts and six snippets selected from `business`; it did not receive a dedicated accounting packet.
- The guided profile registry contains no `accounting_recast` or `qoe` handoff profile, even though the older orchestrator has both agents.
- `filing_retrieval.py` already has accounting-specific priorities for `note_leases`, `note_pension`, `note_debt`, `note_taxes`, `note_contingencies`, and `note_segments`; the guided evidence path does not use them.
- Existing accounting/QoE schemas lack a complete adjustment ledger: period, currency, booked-versus-proposed status, cash timing, tax effect, valuation treatment, and exact source locator are not first-class fields.
- Generic observation validation checks evidence overlap and required prose, but not whether the proposed driver matches the accounting claim. This allowed the item-123 pattern: the claim questioned the margin target while the proposal changed starting margin.
- The current translator uses broad observation types and fixed proposal rules. Accounting candidates need dedicated types and a contract that can preserve `no_adjustment_identified` without creating a queue item.

## Target Flow

```text
    CIQ/yfinance/EDGAR
    -> deterministic accounting evidence assembly
    -> focused topic packets
    -> one narrow judgment call per focus subpacket
    -> schema + evidence + driver validator
       -> repair prompt once on parse/semantic failure
       -> rejected-with-reason artifact after failed repair
    -> accounting adjustment ledger
    -> dedupe/conflict review
    -> PM Decision Queue candidates only
    -> PM preview/decision; no automatic apply
```

The first implementation should use four review families, decomposed into focus subpackets rather than one call over the whole balance sheet or queue:

1. **QoE and revenue recognition:** accruals, cash conversion, revenue recognition, stock compensation, restructuring, impairment, acquisition costs, auditor flags.
2. **EV-to-equity bridge:** cash/investments, debt, leases, minority interest, preferred equity, pension/post-retirement claims.
3. **Contingencies and taxes:** litigation, tax disputes, guarantees, commitments, reserves, probability/timing questions.
4. **Segments and disclosure quality:** segment revenue/margins, mix shifts, discontinued/recast presentation, missing disclosure evidence.

Each focus call receives only its focus-specific facts, note chunks, current model fields, and allowed driver map. It does not receive the entire PM queue or unrelated valuation narrative. A focus response may contain multiple independently anchored findings.

## Target Finding Contract

Each focused call returns a list containing zero or more findings. Every finding must include:

- `topic`
- `finding_status`: `candidate`, `no_adjustment_identified`, or `missing_evidence`
- `finding_type`
- `line_item`
- `reported_value`, `currency`, and `period` when known
- `booked_or_disclosed_status`: `booked`, `disclosed_not_booked`, `unclear`, or `not_applicable`
- `accounting_treatment`
- `valuation_treatment`: `normalized_ebit`, `ev_equity_bridge`, `scenario_only`, `disclosure_only`, or `none`
- `claim_driver_field`: the valuation field the finding is actually about
- `proposed_driver_field` and `direction` only when a candidate is supportable
- `cash_impact`, `tax_impact`, and timing when relevant
- `materiality_rationale`
- `evidence_anchor_ids` and exact `citation_text`
- `confidence`
- `pm_question`
- `what_would_change_mind`

The contract must explicitly prevent a finding from silently becoming an adjustment when the evidence only supports a risk flag. For candidate findings, `claim_driver_field` and `proposed_driver_field` must match unless the finding is explicitly scenario-only or disclosure-only; the validator must compare these fields directly rather than infer intent from prose.

## Repair Contract

Repair is part of the normal agent boundary, not an exception:

1. Run the focused call.
2. Parse and validate the response.
3. If parsing fails, send one formatting retry containing the parser error and the required schema.
4. If semantic validation fails, identify the invalid `finding_id` and send one item-level repair retry containing:
   - the original finding;
   - the exact validation error;
   - the cited evidence available to the call;
   - the allowed driver fields for that focus;
   - the instruction to preserve the underlying finding when valid and change only the invalid field.
5. Revalidate the repaired finding while preserving valid sibling findings from the original response.
6. If it still fails, persist `rejected_after_repair` with the reason, both attempts, and evidence provenance. Do not silently drop it.

For the item-123 pattern, the repair message should say that the claim concerns `ebit_margin_target` but the proposal names `ebit_margin_start`; the agent should either change the proposal to the target field if supported or return the finding as advisory without a proposal. It must not be treated as redundant merely because the first proposal mapping was wrong.

## Tasks

### Task 1: Freeze the current failure as an offline contract test

**Files:**
- Test: `tests/test_accounting_evidence_packs.py` (create)
- Test: `tests/test_observation_translator.py`
- Test: `tests/test_guided_ticker_workup.py`

**Steps:**

1. Create a minimal fixture containing a target-margin claim with an incorrect starting-margin proposal.
2. Assert the validator rejects the mapping with a machine-readable reason naming both fields.
3. Assert the repair payload contains the original finding, validation reason, allowed fields, and evidence anchors.
4. Assert a repaired target-margin proposal is accepted and an unrepaired response becomes `rejected_after_repair` rather than disappearing.
5. Run the focused tests and confirm they fail because the validator/repair seam does not yet exist.

**Verification:**

```powershell
python -m pytest tests/test_accounting_evidence_packs.py tests/test_observation_translator.py tests/test_guided_ticker_workup.py -q
```

### Task 2: Define the accounting evidence and finding contracts

**Files:**
- Create or modify: `src/contracts/accounting_evidence.py`
- Modify: `src/contracts/evidence_packet.py`
- Test: `tests/test_accounting_evidence_packs.py`

**Steps:**

1. Define topic, finding status, accounting treatment, valuation treatment, and repair-status enums.
2. Define typed models for accounting source facts, focused packets, findings, validation errors, and repair attempts.
3. Require exact evidence anchors for `candidate` findings; permit `no_adjustment_identified` only with a reason; permit `missing_evidence` only with a missing-source explanation.
4. Add fields for period, currency, booked/disclosed status, cash impact, tax impact, and valuation treatment.
5. Add serialization tests that preserve raw attempts and validation reasons for audit artifacts.

**Finance boundary:** do not encode universal materiality thresholds or automatic adjustment direction in the contract.

### Task 3: Build deterministic topic-specific evidence packets

**Files:**
- Modify: `src/stage_04_pipeline/evidence_packets.py`
- Modify: `src/stage_00_data/filing_retrieval.py` only where retrieval metadata or topic filtering is missing
- Modify: `src/stage_02_valuation/input_assembler.py` or the existing bridge view only if a required existing field is not exposed
- Test: `tests/test_evidence_packets.py`

**Steps:**

1. Add an accounting packet collector that calls the existing `accounting_recast` retrieval profile instead of the generic `filings` profile.
2. Preserve selected section keys and source locators in packet metadata.
3. Add deterministic facts for current bridge fields already available in the model: net debt, non-operating assets, lease liabilities, minority interest, preferred equity, pension deficit, shares, and cash/investments.
4. Add deterministic QoE facts: accruals, cash conversion, DSO/DIO/DPO drift, Capex/D&A, forensic flags, and reported EBIT.
5. Add note-topic coverage facts for leases, pensions, taxes, contingencies, segments, revenue recognition, restructuring, impairment, acquisitions, and fair value.
6. Ensure the packet distinguishes “topic searched and no evidence found” from “topic not retrieved.”
7. Add fixture tests asserting a packet contains accounting section keys and bridge facts without requiring a live SEC/CIQ call.

### Task 4: Implement focused topic dispatch

**Files:**
- Create or modify: `src/stage_04_pipeline/accounting_evidence_runner.py`
- Modify: `src/stage_04_pipeline/agentic_handoff_profiles.py`
- Modify: `scripts/manual/run_guided_ticker_workup.py`
- Test: `tests/test_accounting_evidence_packs.py`

**Steps:**

1. Register the four parent topic families and eight focus profiles with narrow prompts and allowed driver fields.
2. Dispatch one call per focus subpacket with only its selected context.
3. Keep the call count bounded and record per-topic latency, model, evidence size, and status.
4. Do not pass the whole PM queue or unrelated profiles into the focus prompt.
5. Persist each topic packet and finding artifact so the PM can inspect what the agent actually saw.
6. Add a guided-run flag for the accounting pass, defaulting on for the full weekly loop but allowing an isolated offline smoke.

### Task 5: Add parse, semantic, and repair validation

**Files:**
- Create or modify: `src/stage_04_pipeline/accounting_validation.py`
- Modify: `src/stage_03_judgment/base_agent.py` only if a reusable structured-repair seam is missing
- Test: `tests/test_accounting_evidence_packs.py`

**Steps:**

1. Validate the response envelope and each finding independently.
2. Validate every evidence anchor exists in the supplied focus packet.
3. Validate topic-specific accounting treatment and valuation treatment combinations.
4. Validate proposed driver alignment against claim, finding type, and focus allowed-driver map.
5. Validate units, sign, period, and booked/disclosed status where present.
6. Implement one whole-envelope retry for syntax/schema failure and one item-level retry for semantic failure.
7. Preserve valid sibling findings when one finding fails validation.
8. Persist original output, repair prompt, repaired output, validation result, and final status for each finding.
9. Add tests for multi-finding success, mixed valid/invalid findings, syntax failure, missing anchor, wrong driver, invalid unit, successful item repair, and failed item repair.

### Task 6: Translate valid accounting findings into PM Queue items

**Files:**
- Modify: `src/stage_04_pipeline/observation_translator.py`
- Modify: `src/stage_04_pipeline/agentic_handoff_profiles.py`
- Modify: `src/contracts/pm_decision_queue.py` if the existing item metadata cannot retain the ledger fields
- Test: `tests/test_observation_translator.py`, `tests/test_pm_decision_queue_contracts.py`

**Steps:**

1. Add dedicated accounting finding types rather than routing them through `execution_risk_increased`.
2. Create one queue item per distinct valid `candidate` finding that has evidence, treatment, and a supported driver or explicit scenario-only treatment.
3. Keep `no_adjustment_identified` and `missing_evidence` in the accounting artifact but out of the mutation queue unless they become explicit diligence items.
4. Preserve the full adjustment ledger, duplicate links, and conflict groups in queue metadata and decision history.
5. Add a semantic regression test proving the item-123 pattern triggers repair before queue creation.

### Task 7: Integrate the accounting pass into the guided workup

**Files:**
- Modify: `scripts/manual/run_guided_ticker_workup.py`
- Modify: `src/stage_04_pipeline/analyst_prep_pack.py`
- Modify: `docs/handbook/workflow-end-to-end.md`
- Test: `tests/test_guided_ticker_workup.py`, `tests/test_analyst_prep_pack.py`

**Steps:**

1. Run the accounting evidence pass after deterministic model construction and before the general queue review.
2. Render a compact accounting review section showing topic status, candidate count, rejected-after-repair count, and missing evidence.
3. Include links/paths to topic packets and repair traces in the run JSON and Markdown artifacts.
4. Keep PM review focused: candidates are shown with accounting treatment, valuation treatment, evidence, and proposed driver; generic narrative stays in the existing profile packets.
5. Ensure approved accounting changes remain pending until the existing PM preview/approval/apply workflow handles them.

### Task 8: Validate on MSFT and document the comparison

**Files:**
- Create: `docs/reviews/weekly-loop/2026-07-11-MSFT-accounting-evidence-baseline.md`
- Modify: `docs/reviews/weekly-loop/README.md` if the review naming convention needs an accounting supplement

**Steps:**

1. Run the focused accounting pass on MSFT using cached EDGAR/market data and the existing refreshed CIQ workbook.
2. Confirm the packet includes note-specific coverage for taxes, leases, contingencies, segments, and QoE signals.
3. Compare the four topic outputs against the original 2026-07-11 run.
4. Record which findings are candidates, no-adjustment conclusions, missing evidence, repaired outputs, and unresolved PM questions.
5. Do not approve or apply any accounting change during the validation run.

### Task 9: Full offline and live verification

**Files:**
- Modify: relevant tests/docs only if verification exposes a contract mismatch

**Steps:**

1. Run the focused accounting/translator/guided-workup tests.
2. Run the existing focused gate.
3. Run the full offline suite with the documented Windows cache workaround if needed.
4. Run one live MSFT accounting pass and inspect the persisted artifacts manually.
5. Confirm no LLM call occurs in `src/stage_00_data` or `src/stage_02_valuation`.
6. Confirm no accounting finding directly mutates deterministic inputs.

**Verification:**

```powershell
python -m pytest tests/test_accounting_evidence_packs.py tests/test_observation_translator.py tests/test_guided_ticker_workup.py tests/test_analyst_prep_pack.py -m "not live" -q
python -m pytest -m "not live" -q
python scripts/manual/run_guided_ticker_workup.py --ticker MSFT --agent-mode live --use-codex --codex-model gpt-5.6-luna --codex-effort low --skip-ciq-stage --market-cache-only --edgar-cache-only --output-dir output/guided_workups/MSFT-accounting-validation
```

## Exit Criteria

1. A guided MSFT run produces four topic-specific accounting packets, not one generic filing context.
2. The packets expose note-section coverage, deterministic bridge fields, and QoE signals.
3. At least one malformed or semantically misaligned proposal receives a structured repair attempt and retains the failure reason if repair fails.
4. A corrected proposal is not discarded merely because its first driver mapping was wrong.
5. Accounting candidates have exact evidence, explicit accounting/valuation treatment, and PM questions.
6. No-adjustment and missing-evidence outcomes are visible and are not mistaken for successful clean review.
7. No automatic valuation mutation occurs.
8. The live validation artifact demonstrates materially better accounting coverage than the original MSFT MVP run.

## Deferred Work

- Automatic application batching remains a separate queue ergonomics plan.
- Full workbook-to-note table extraction is deferred until the focused EDGAR packet proves insufficient.
- PM-specific materiality thresholds and treatment conventions are not invented in this plan; they require explicit finance decisions.
