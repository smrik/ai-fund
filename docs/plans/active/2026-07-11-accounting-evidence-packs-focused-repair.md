# Accounting Evidence Packs And Focused Repair Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.
> **For Codex:** Use this plan task-by-task with TDD where practical. The PM finance-semantics checkpoint was resolved on 2026-07-25; follow that recorded scope rather than reintroducing fixed treatment rules.

**Vision decisions served:** 1, 2, 10–16.

**Goal:** Make the guided weekly loop produce finance-useful accounting/QoE evidence, support
open-ended classifications and historical recasts, and repair semantically invalid proposals
once before dropping them, while keeping all valuation mutations behind the PM Decision Queue.

**Architecture:** Use broad deterministic discovery over the populated historical record, then
retrieve note-specific filing sections and quantitative facts for narrow judgment questions.
Each call returns typed findings or explicit no-adjustment/missing-evidence results. The validator
checks schema, anchors, completeness, and driver alignment without treating the current model
schema as a ceiling: a sound unsupported treatment becomes a model-change request. Valid findings
merge into an accounting ledger and anchored PM-review candidates enter the queue. Approved
treatments persist separately from flattened numeric overrides and can be revalidated when the
evidence corpus changes.

**Tech Stack:** Python 3.11, typed dataclasses/Pydantic contracts, SQLite evidence-packet persistence, EDGAR section/chunk retrieval, existing CIQ/yfinance valuation inputs, `BaseAgent` Codex routing, pytest offline fixtures, Markdown run artifacts.

## Implementation Status

- **Core focused chain complete:** typed packet/finding/repair contracts, focus projection,
  selector-to-validator adapter, per-item repair, deterministic ledger, conflict preservation,
  and PM Queue translation are connected by `run_accounting_evidence_trial`.
- **Broad CIQ discovery complete:** every latest populated non-zero CIQ line is eligible;
  ranking and paging help review but no fixed topic list or materiality threshold decides what
  the judgment layer may inspect.
- **Open-ended treatment seam complete:** findings can propose a historical recast or an explicit
  `model_change_required` request when no current driver can represent a financially sound
  treatment.
- **Durable treatment register complete:** `treatment_decisions` preserves evidence anchors,
  rationale, approval, corpus hash, active/superseded history, and novel model-change requests.
- **Bridge repair complete:** CIQ structural claims are exposed, all structural EV-to-equity
  fields are registered, and CIQ lease liabilities are not counted twice.
- **Evidence-corpus repair complete:** `sections_v6` parses complete filing text, distinguishes
  note bodies from table-of-contents and auditor/MD&A boundaries, preserves stable raw
  `note_001`...`note_NNN` sections, and processes every cached 10-K and 10-Q in the accounting
  corpus. Topic aliases remain useful for ranking but no longer determine snippet eligibility.
- **XBRL Slice A complete:** structured `FinancialFact` normalization preserves filing vintage, context, dimensions, statement metadata, and accession-index provenance; exact concept filtering and newest-vintage ordering are covered offline.
- **XBRL Slice B complete:** all four persisted accounting packet builders now add topic-bounded XBRL facts and accession-level source refs, while retaining existing note snippets and deterministic accounting facts. Cache-only mode reports `cache_only_unavailable` without constructing an SEC client.
- **Real trial:** cached MSFT bridge packet 213 produced evidence-linked PM Queue advisory 133:
  the packet's $52.626bn lease balance differs from same-period XBRL operating plus finance
  lease liabilities of $85.170bn. The system requested source/convention reconciliation and did
  not mutate the DCF.
- **Fresh cache-only packet trial complete:** packet 214 returned with eight filing snippets from
  annual and quarterly notes/MD&A, including raw numbered-note sections. The packet builder no
  longer filters snippets through a fixed accounting-topic allowlist.
- **Live judgment trial complete:** the Accounting Recast agent received business, industry,
  current-model, and filing context. It proposed no unsupported EBIT normalization and kept lease
  liabilities inside CIQ debt after reconciling the deterministic source lineage. The prompt now
  requires absolute-USD scaling and can return open-ended `model_change_proposals`.
- **Two-pass discovery trial complete:** a standalone live MSFT run exposed all 181 inventory
  entries (141 raw numbered notes plus 40 semantic aliases) to an open-ended discovery call. Six
  company-specific questions drove exact-section, term-ranked retrieval and six narrow recast
  calls. The resulting artifact covers AI/datacenter capital intensity, segment mix, RPO
  conversion, contingencies, debt structure, and SBC/share-count treatment.
- **Double-count guard verified:** the live AI-capacity call rediscovered $85.126bn of lease
  liabilities. A deterministic source-lineage guard now clears that override and its proposed
  driver field because CIQ total debt already includes leases; the reasoning and citations remain
  visible for PM review.
- **Discovery → ledger adapter complete (2026-07-25):** `accounting_discovery_ledger.py` maps each
  focused recast payload onto independent `AccountingFinding` records, validates every one through
  the shared `validate_accounting_finding`, and merges them into the existing ledger/PM Queue path.
  See [Discovery-To-Ledger Adapter](#discovery-to-ledger-adapter-added-2026-07-25).
- **Next:** persist PM-approved treatments from queue actions into `treatment_decisions` and expose
  treatment/revalidation state in the review UI. Exact Inline XBRL DOM anchors remain later work.
  Repeat the two-pass trial on a second company with materially different accounting issues before
  declaring the retrieval strategy general.

## Critical Evidence-Corpus Gate — Added 2026-07-25

Classification and forecasting must not proceed from evidence that only appears complete. The
2026-07-25 repair separated filing inventory, current-parser coverage, raw numbered notes, and
semantic topic aliases.

Verified cache-only MSFT state after rebuilding `v1_sections_v6`:

- filing inventory: 12 documents — four 10-Ks, four 10-Qs, and four 8-Ks;
- accounting corpus: 8/8 required 10-K/10-Q filings parsed, with no failed periods;
- current sections: 217 across the eight accounting filings; stale parser rows are excluded;
- raw numbered-note coverage: 18 notes in the 2025 10-K, 19 in each 2022–2024 10-K, and
  16–17 in each quarterly filing;
- retrieval corpus: 3,831 chunks built from complete filing text;
- 8-Ks remain supplemental business/earnings sources and are not misreported as accounting-note
  coverage.

Implementation order:

1. [x] Add offline regression tests for complete-document parsing, split/malformed headings,
   TOC-versus-body discrimination, annual and quarterly numbered-note inventory, and current
   parser-version filtering.
2. [x] Parse complete cached filing text before applying chunk or rendered-context budgets.
3. [x] Preserve every raw numbered note and heading with stable source identity. Topic aliases and
   ranking may improve retrieval but must never determine eligibility.
4. [x] Process every available historical filing relevant to the populated record rather than one
   hardcoded annual filing; expose missing or failed periods explicitly.
5. [x] Make Stage 0 report filing inventory separately from current-parser coverage, unique semantic
   sections, mapped and unmapped headings, and truncation/parse failures.
6. [x] Rebuild with a new parser version and validate cached MSFT before reconnecting judgment.

Acceptance criteria:

- [x] the 2025 MSFT 10-K exposes all 18 numbered notes as distinct source-backed sections;
- [x] all cached MSFT annual filings are either represented or explicitly reported as failed/missing;
- [x] quarterly notes are inventoried rather than stored only as one opaque block;
- [x] stale parser versions do not inflate current section or source counts;
- [x] no `note_*` label can imply a complete note when its source span is truncated or only a
  subsection of another note;
- [x] classification trials fail closed when required corpus completeness checks fail.

## Discovery-To-Ledger Adapter — Added 2026-07-25

The two-pass trial (discovery → per-question focused retrieval → per-question recast) now reaches
the canonical accounting ledger and PM Decision Queue through
`src/stage_04_pipeline/accounting_discovery_ledger.py`. The ledger and translator themselves are
unchanged; this is an adapter, not a second pipeline.

**Proposable-surface repair (2026-07-25).** The first cached MSFT validation produced 18 queue
items and **zero** assumption change packs. The cause was not the adapter: `AccountingRecastAgent`
could only name five EV-bridge claims (`non_operating_assets`, `lease_liabilities`,
`minority_interest`, `preferred_equity`, `pension_deficit`). Every driver that moves the DCF
forecast — growth, margins, capex/D&A intensity, tax rates, terminal assumptions, WACC, share
count — was unreachable, which is the mechanical cause of the `llm_reasoned: 0` provenance audit
recorded in [docs/valuation/index.md](../../valuation/index.md).

Per [Standing Rule 6](../../strategy/vision.md#standing-rules-for-agents) the deliverable is wiring
the seam, not choosing constants. The recast response contract gained `driver_proposals`:

```json
{"driver_field": "ebit_margin_target", "proposed_value": 0.44,
 "direction": "up", "rationale": "...", "citation_text": "..."}
```

`driver_field` is validated against `AGENT_PROPOSABLE_ASSUMPTION_FIELDS` (all 21 fields); a name
outside that set is dropped rather than remapped onto a neighbouring driver, and a proposal with no
value is not a proposal. The adapter maps each entry to a candidate finding whose claim and
proposed driver match, so it becomes an assumption change pack for PM approval. The lease
source-lineage guard clears a blocked driver proposal exactly as it clears a blocked override.

**Mapping rules.** Every item in a recast payload becomes its own finding carrying its own
`question_id`, so several analyses never collapse into one override map:

| Recast item | Finding status | Valuation treatment | Queue outcome |
|---|---|---|---|
| income-statement adjustment with an EBIT direction | `candidate` + `model_change_required` | `normalized_ebit` | advisory, `queue_reason=model_change_required` |
| income-statement adjustment with direction `none` | `no_adjustment_identified` | `none` | ledger only |
| balance-sheet reclassification naming a driver | `candidate` | `ev_equity_bridge` | assumption change pack |
| balance-sheet reclassification naming no driver | `no_adjustment_identified` | `disclosure_only` | ledger only |
| driver proposal (operating driver) | `candidate` | `historical_recast` | assumption change pack |
| driver proposal (bridge driver) | `candidate` | `ev_equity_bridge` | assumption change pack |
| non-null override candidate | `candidate` | `ev_equity_bridge` | assumption change pack |
| `normalized_ebit` override candidate | `candidate` + `model_change_required` | `normalized_ebit` | advisory |
| any proposed driver in `blocked_override_fields` | `candidate` | `disclosure_only` | advisory, reasoning retained |
| model-change proposal | `candidate` + `model_change_required` | `none` | advisory |
| question producing no items at all | `no_adjustment_identified` | `none` | ledger only |

**Design decisions logged (Vision Decision 11, engineering side).**

1. *Every mapped finding is validated.* The queue translator does not check claim-versus-proposed
   driver alignment; only `validate_accounting_finding` does. The adapter synthesizes a minimal
   packet per question — matched filing sections become `source_refs`, allowed drivers are
   `AGENT_PROPOSABLE_ASSUMPTION_FIELDS` — and runs every finding through it. A failing finding is
   persisted as `rejected_after_repair`, never dropped.
2. *Anchors are matched sections only.* `{accession_no}::{section_key}` from
   `retrieval_summary.matched_section_ids`, so a requested-but-unmatched section can never anchor
   a finding.
3. *`normalized_ebit` is never remapped onto a margin driver.* It is in the recast agent's override
   vocabulary but not in `AGENT_PROPOSABLE_ASSUMPTION_FIELDS`, so it becomes an explicit
   model-change request. Remapping it to `ebit_margin_start`/`ebit_margin_target` is exactly the
   item-123 mismapping this plan froze as a regression.
4. *The guard is re-applied at the adapter, not trusted from upstream.* `AccountingRecastAgent`
   already clears blocked overrides; the adapter independently downgrades any blocked driver to a
   disclosure-only finding. The reasoning, citation, and anchors stay visible for PM review.
5. *Model-change proposals carry a routing-default topic.* Open-ended questions have no parent
   accounting topic; `qoe` is a routing default recorded as `topic_is_routing_default` in metadata,
   and the queue title drops the focus prefix for model-change items.
6. *Period is not inferred.* Recast items carry no period field and the adapter does not parse one
   out of citation prose, so fingerprints and conflict groups use an empty period.

**Fail-closed gate.** `filing_retrieval.get_accounting_corpus_coverage` /
`require_accounting_corpus_coverage` report cached filing inventory against current-parser
accounting coverage as a library call, so the runner no longer depends on the manual inspector.
`stage0_evidence` calls the same helper, so the operator view and the runtime gate cannot drift.

The gate checks **two** conditions, because they fail separately:

1. every cached 10-K/10-Q parsed under the current parser version, and
2. every one of those filings produced at least one raw numbered note.

Condition 2 was added after IBM exposed the hole: four required filings were present and parsed,
but yielded 1–5 sections and **zero** numbered notes between them, so
`get_accounting_section_inventory("IBM")` returned an empty list. A presence-only gate would have
called that corpus complete and handed the discovery agent nothing. *Parsed is not complete.*

Verified: MSFT passes (12 cached filings, 8/8 required parsed at `v1_sections_v6`, all with
16–19 raw notes); IBM fails closed on both conditions.

**Cached MSFT validation (2026-07-25, no LLM call, nothing applied).** Replaying the two live
artifacts through the adapter:

| Artifact | Ledger entries | No-adjustment | Candidates | Queue items | Assumption packs |
|---|---|---|---|---|---|
| `MSFT-20260725T155924Z.json` (unguarded) | 28 | 10 | 18 | 18 advisory | 0 |
| `MSFT-20260725T155924Z-guarded.json` | 27 | 12 | 15 | 15 advisory | 0 |

The three-entry difference is exactly the lease double-count: two reclassifications and one
$85.126bn override candidate. In the unguarded artifact the adapter's own guard downgrades all
three to advisory findings; none becomes an assumption change pack. Nothing was persisted
(`--persist-queue` is opt-in and was not used).

**Open items surfaced by the validation, not fixed here.**

- The recast agent uses `model_change_proposals` as a general notes channel: 14 of the 18 MSFT
  candidates are proposals, and several are explicit *no-change confirmations* ("keep EBIT
  normalization unchanged"). Deterministic code cannot separate "propose a change" from "confirm no
  change" without keyword heuristics. This is a prompt/contract question for the recast agent.
- `_parse_balance_sheet_reclassifications` silently nulls any `proposed_driver_field` outside a
  five-field allowlist (`net_debt` and every income-statement driver are dropped). Widening it is a
  live-revalidation change, not an adapter change.
- Queue volume: one six-question MSFT run yields 15–18 advisory items. The plan says volume is
  handled by ranking and deduplication, not by collapsing accounting reasoning upstream, so no cap
  was added. Whether this fits the daily budget is a PM call.

**Live MSFT run with `driver_proposals` (2026-07-25, `gpt-5.4-mini` @ low, dry run).**
Artifact `output/accounting_discovery/MSFT-20260725T175203Z.json`. Six new questions covering AI
capex/lease intensity, segment CODM recast, unearned revenue/RPO runoff, contingencies, debt
structure/fair value, and goodwill/intangibles.

Result: 37 ledger entries (19 candidates, 16 no-adjustment, 2 conflict), 21 queue items —
20 advisory and **1 assumption change pack**, `non_operating_assets` = $111.955bn anchored to six
filing sections. This is the first time an accounting judgment reached a valuation driver through
the queue. Nothing was persisted or applied.

One genuine conflict group surfaced without being constructed: two questions proposed different
`ebit_margin_target` values. Both stay visible; neither is applicable.

**Two adapter defects the live run exposed, both fixed:**

1. *Phantom self-contradiction.* The recast contract can express one claim through three channels
   — a reclassification naming a driver, a `driver_proposals` entry, and an `override_candidates`
   key. `non_operating_assets` = $111.955bn arrived through all three from one question and was
   flagged as contradicting itself, then produced duplicate packs. One `(driver, value)` pair
   inside one question is now one claim; the reclassification is kept because it carries the
   reported accounting line item, and the dropped channels are recorded in
   `metadata.also_proposed_via`. Cross-question disagreement still conflicts normally.
2. *Nothing else changed* — conflict counts and no-adjustment visibility are unaffected.

**BLOCKING FINANCE QUESTION — `0.0` driver proposals.** The AI-capex question returned
`capex_pct_target: 0.0` and `ebit_margin_target: 0.0` while its own narrative said capital
intensity is structurally elevated. Those are not forecasts; they read as "no opinion" emitted as a
number. `0.0` is legitimate for `terminal_growth` or `preferred_equity` and nonsensical for a
margin or capex ratio, and the repository has no PM-approved sanity band for proposal values —
`_bounded` applies during deterministic assembly only, and per
[trap 2](../../handbook/pipeline-glass-box.md) approved overrides bypass every clamp. Deciding
which drivers may legitimately be zero, and what band each should carry, is finance semantics and
blocks on the PM (Vision Decision 11). Until then the queue is the only protection: the item is
`pending` and cannot self-apply.

**Second-company generality attempt (2026-07-25).** A cache-only IBM corpus build succeeded but
the gate correctly refused the ticker:

- IBM has 17 cached filings, of which 5 are 10-K/10-Q and 4 parse at `v1_sections_v6`;
- the fifth is a synthetic test fixture (`0000123456-26-000001`, `annual.htm`) that tests wrote
  into the live `edgar_filing_cache`, so it can never parse;
- the four real IBM filings yield only 1–5 sections each and **zero** raw numbered notes, versus
  16–19 per MSFT filing — the cached clean text is too thin to support discovery.

So generality remains untested, and the blocker is corpus depth plus fixture pollution in the
research database, not the adapter. `require_accounting_corpus_coverage("IBM")` failing closed on a
real second ticker is itself the first live confirmation of the requirement-9 gate. The live IBM
discovery/recast run needs PM approval for model and cost before it is attempted.

The corpus build wrote 8 new `v1_sections_v6` section rows (319 chunks) for IBM's four real
filings into `data/alpha_pod.db`. It made no LLM call, created no queue item, and changed no
valuation input.

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

This revision serves Vision Decisions 1, 2, 10–16. The previous
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
segment facts simply because they share a filing. These focus keys organize retrieval and
validation; they are not a closed list of permitted accounting treatments or model changes.

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

- **Decision 1:** no agent writes valuation inputs directly; every accounting finding reaches the model through the PM Decision Queue. (Wording narrowed 2026-07-24: this is a routing constraint. Per Decision 13 the judgment layer *does* author proposed assumption values — it simply cannot bypass the queue. "Advisory" here never meant "optional colour".)
- **Decision 2:** focused packets reduce PM review noise and support the daily review cadence.
- **Decision 10:** the contract makes ambiguous accounting claims explicit instead of silently translating them.
- **Decision 11:** finance treatment questions remain PM-owned; engineering validation and retry behavior are conservative and logged here.
- **Decision 12:** real ticker workups should produce decision-ready accounting evidence without manual note-surgery.
- **Decision 13:** the judgment layer authors treatment and forecast proposals from evidence; deterministic code does not replace that judgment with lookup rules.
- **Decision 14:** focused calls must eventually receive durable business and industry context, not only the local accounting facts.
- **Decision 15:** accounting outputs feed the mandatory DCF and comps workup; other valuation methods remain deferred.
- **Decision 16:** discovery is broad and treatments are open-ended, including historical recasts and explicit model changes.

## PM Finance-Semantics Checkpoint — Resolved 2026-07-25

The PM confirmed:

1. DCF and comps are always produced in the current scope; other valuation methods are deferred.
2. The judgment layer may propose any reasonable, logical, financially sound change. Existing
   driver fields must not constrain reasoning.
3. Broad discovery followed by targeted evidence retrieval is the initial evidence strategy;
   tests and real usage should refine it.
4. Both historical recasts and their downstream forecast implications are in scope.
5. No treatment auto-applies. Unsupported treatments become explicit model-change requests, and
   every mutation remains behind PM approval.

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
    -> broad populated-line discovery
    -> deterministic targeted evidence assembly
    -> focused topic packets
    -> one narrow judgment call per focus subpacket
    -> schema + evidence + driver validator
       -> repair prompt once on parse/semantic failure
       -> rejected-with-reason artifact after failed repair
    -> accounting adjustment ledger
    -> dedupe/conflict review
    -> PM Decision Queue candidate or explicit model-change request
    -> PM preview/decision
    -> durable treatment register
    -> deterministic DCF and comps execution; no automatic apply
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
