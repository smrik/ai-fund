# Session State

**Updated:** 2026-08-01 20:25 +02:00
**Agent:** Codex CLI
**Project:** C:/Projects/03-Finance/ai-fund

## Current Task

Propagate genuine evidence corpus hashes through accounting producers so PM-approved treatments can
be persisted.

## Recent Actions

- Traced the canonical SHA-256 corpus hash from filing retrieval through discovery retrieval
  summaries and persisted evidence-packet metadata/source references.
- Propagated discovery hashes into findings and queue metadata; propagated focused source-packet
  hashes into the transient focused packet, validated findings, and queue metadata.
- Added end-to-end approval and fail-closed regressions. The requested accounting suites pass:
  56 passed including the focused runner tests.
- Full tracked offline suite: 1,307 passed, 9 failed, 2 deselected. Eight failures are the known
  advanced workbook Windows-temp permission issue; one is an unrelated concurrent API contract
  change in `tests/test_api_contracts.py`.

## Next Steps

- Review/stage the five requested source/test files and commit on the feature branch when `.git`
  write access is available.
- If the base evidence-packet producer is later changed, propagate its retrieval bundle hash into
  persisted `run_metadata` or source refs; the current persisted packet-213 path has no genuine
  corpus hash and correctly remains fail closed.

## Known Issues

- The managed sandbox denies `.git/index` writes, so the implementation could not be committed.
- The worktree also contains unrelated concurrent valuation/API/docs/frontend changes and generated
  cache/export/debug artifacts; none were staged or reverted.

## Notes

- Runtime: `C:/Users/patri/miniconda3/envs/ai-fund/python.exe`.
- Current branch: `codex/focused-accounting-evidence-repair`.
- Corpus hashes come from SHA-256 over the filing retrieval corpus's chunk-identity records with
  deterministic JSON key ordering. An unchanged corpus is stable when retrieval order is unchanged;
  the current hash is not order-independent, so retrieval-order changes produce a new hash.

## First end-to-end valuation attempt — 2026-07-31

Provider: OpenRouter, `deepseek/deepseek-v4-flash-0731`, via
`src.stage_04_pipeline.valuation_workup_cli`. **No LLM call was made** — the run stops at the trust
gate before dispatching judgment.

**Production DB was empty.** All verified ingestion lived in the scratch DB under `C:/tmp`.
`refresh_statement_sources(['MSFT','CALM'])` was run against `data/alpha_pod.db`: 0 → **15,449
statement facts**, both tickers `provisional` there as well.

**Gates 3 and 4 are cleared.** Nothing in the materials layer was unbuilt:

- **Comps** — the data was always there (MSFT: 702 rows at `2026-03-31`).
  `_fetch_ciq_comps_rows` required an **exact** `as_of_date` match, so an analysis on any other day
  returned empty. It now resolves to the latest snapshot at or before the analysis date. A later
  snapshot is still never used by an earlier analysis. Regression in `tests/test_ciq_adapter.py`.
- **Valuation policy** — `bootstrap_valuation_policy()` existed in code and
  `get_valuation_policy()` fell back to it, but `valuation_policy_versions` had **0 rows** and the
  workup service reads the table directly. Persisted as version 1 via
  `save_valuation_policy(..., actor="bootstrap")`.

**Gate 2 (company analysis) cleared 2026-08-01.** First real LLM spend of the project:
`run_guided_ticker_workup.py --ticker MSFT --profiles company_analysis --agent-mode live
--openrouter-model deepseek/deepseek-v4-flash-0731`. Returned `quality=real`, 10 facts, 6 snippets,
8 refs, 2 observations, and PM queue items 178/179. All `materials.*` blockers are gone.

The agent's own output is the point of the project — it flagged that the model's 32.0% long-run
EBIT margin target is 1,200 bps below the 44.0% three-year average, and that the 11.4% near-term
growth assumption sits under a 15.3% three-year CAGR. Both are sector-constant `*_target` slots,
exactly what Vision Decision 13 names.

**Cash bridge cleared on both tickers.** Two fixes: the opening balance may be presented under the
other cash variant (MSFT bridges on `cash_including_restricted` while its 2021-06-30 opening is
`cash_and_equivalents`), and the **earliest period in a window has no in-window predecessor** —
MSFT's 2021-06-30 consolidated close is not ingested, only a dimensioned variant. Requiring a
bridge there blocked permanently on structurally absent data. `_bridge_required_for_period()`.

Current readiness: **MSFT `provisional`** — `source_calculation_rollup_not_ready`, `ltm_not_ready`.
**CALM `provisional`** — `source_overlap_inventory_incomplete`, `source_calculation_rollup_not_ready`.

Original gate list (for history):

1. `preparation.statement_reconciliation_incomplete` — requires **decision_grade**; both tickers
   are `provisional`. MSFT's three residual reasons: `cash_flow_to_cash_bridge_not_ready`,
   `source_calculation_rollup_not_ready`, `ltm_not_ready`.
2. `materials.company_analysis.{run_incomplete,observations_missing,agent_artifact_missing}` — the
   company-analysis agent has never run for this snapshot. Existing machinery; needs a real LLM
   run producing an evidence packet with `source_quality == "real"`, a successful
   `handoff_run_status`, non-empty observations, and an `agent_observation_artifact`.

Original gate list (for history):

1. `preparation.statement_reconciliation_incomplete` — `ticker_valuation_execution.py:450` requires
   statement reconciliation to be **decision_grade**, and both tickers are `provisional`. MSFT's
   three residual reasons are `cash_flow_to_cash_bridge_not_ready`,
   `source_calculation_rollup_not_ready`, `ltm_not_ready`.
2. `materials.company_analysis.{run_incomplete,observations_missing,agent_artifact_missing}` — the
   company-analysis agent has not run for this snapshot.
3. `materials.comps.missing` — `valuation_workup_service.py:538`, no comps payload.
4. `materials.valuation_policy.missing` — `valuation_workup_service.py:387`.

The data layer is no longer the blocker. The remaining work is the materials layer plus closing
MSFT's three non-blocking readiness reasons.

## CALM workbook refresh — 2026-07-31 19:37

PM re-exported `CALM_Standard.xlsx` on the as-reported calendar. FY2026 and FY2025 now pair;
FY2024 (2d) and FY2023 (6d, 53-week year) still do not — Capital IQ normalizes those historically
and a re-export does not change them. They are now `non_comparable_fiscal_window` **warnings**.

**Finding severity now gates status.** `severity` was recorded but never read
(`status = "review_required" if findings else "pass"`), so a warning blocked exactly as hard as a
real disagreement. Only blocking-severity findings force `review_required`.

CALM now blocks on **7 genuine figure disagreements** — the machinery working, not a defect:
`operating_income` FY2026/FY2025/FY2022 (6.8m / 21.5m / 5.1m), `net_income` FY2026/FY2025
(1.4m / 1.8m), `da` FY2026/FY2025 (6.8m / 2.2m). The net-income gaps look like
attributable-to-parent versus including-NCI; the others look like classification differences.

**RESOLVED — PM chose "filing wins, gap logged" for the DCF path.** The PM's counterpoint (Capital
IQ is cross-company consistent, which matters for comparables) is correct and does not conflict:
**comparables read `ciq_comps_snapshot` through a separate path** (`ciq_adapter.py:418`) and never
touch statement reconciliation. DCF uses the filing; comps keeps Capital IQ untouched.

`material_disagreement` is now advisory. **Two patterns still block**, each a parse/convention
failure that has shipped a wrong valuation before: one side zero while the other is non-zero (the
D&A=0 bug, ~18% IV understatement), and opposite signs (sign-convention error).

**Superseded LTM windows.** CALM derives an LTM ending 2026-02-28 while FY2026 closes 2026-05-30,
and CIQ publishes its LTM on different dates. A trailing window closing before the latest complete
annual period no longer raises cross-source expectations. MSFT unaffected — its LTM matches CIQ.

**RESULT: both tickers are now `provisional`. Neither is blocked.**

## Status — 2026-07-31 end of session

| Ticker | Status | Annual periods | Statement checks |
|---|---|---|---|
| MSFT | **`provisional`** (was `blocked`, 0 periods, 0 checks) | 4 | **149 pass**, 0 fail |
| CALM | `blocked` | 5 | 95 pass, 0 fail |

MSFT reaches a terminal non-blocked state; residual reasons (`ltm_not_ready`,
`cash_flow_to_cash_bridge_not_ready`, `source_calculation_rollup_not_ready`) are all
non-blocking. **CALM's only remaining blocker is the CIQ workbook re-pull on the as-reported
fiscal calendar** — a manual Excel step per the PM decision.

Late-session fixes beyond the source-gate work below:

- CIQ row names `cash_from_ops` / `net_change_in_cash` added to the canonical alias table; they
  were absent, so CIQ read as "missing" `operating_cash_flow` and net-change on every period.
- `net_income` is now statement-agnostic for cross-source matching — CIQ prints it atop the
  indirect cash flow statement, XBRL on the income statement.
- The two net-change-in-cash variants are alternates, so the value tolerance arbitrates instead of
  reporting a silent "missing".
- The combined-D&A rule now also applies to LTM expectations, not just annual periods.
- **Rollup ambiguity:** a concept presented twice under one parent with *different* values (MSFT
  `us-gaap_CommercialPaper` at 2024-06-30: 6,700,000,000 vs 6,693,000,000) is reported `not_ready`
  naming the conflicting concepts, rather than summed or guessed. Cleared MSFT's 2 and CALM's 4
  rollup failures.

## Checkpoint — 2026-07-31 (Claude): source layer unblocked

Three systemic blockers were found by re-running reconciliation on current code and fixed. All
were false blockers: real data was present and correct, the gates were wrong.

1. **LTM readiness was all-or-nothing.** `ltm_status` required exact set equality over every
   presented line item. MSFT built 74/91 identities, CALM 38/120, so both reported `partial`,
   which cascaded `xbrl_source_incomplete` → `source_coverage_not_attested` → blocked. This
   contradicted Decision 7 (dimensioned facts never gate the consolidated view) and Decision 6
   (LTM is built only from period-compatible facts). Extracted as a pure
   `filing_presentation.resolve_ltm_status()`: dimensioned identities excluded, and readiness
   measured against `LTM_REQUIRED_CANONICAL_KEYS` **scoped to keys the source actually presents
   annually**. New shared constant lives in `source_reconciliation.py`.
   Result: MSFT and CALM both `status=completed`, `ltm_status=constructed` (45/48 and 34/50).
2. **Manifest selection had no recency preference.** `load_statement_source_manifests` orders by
   `evidence_cutoff DESC` first, but that is a filter bound, not recency: stale manifests carried a
   run-date cutoff (2026-07-26) while fresh ones carry filing-date cutoffs (2022–2025), so stale
   always won and re-ingestion could never supersede them. Selection now breaks ties on
   `created_at`.
3. **An orphaned incomplete manifest poisoned attestation permanently.** MSFT kept a FY2021
   manifest from an earlier, wider ingestion window that no current refresh reaches. Selection now
   skips manifests that are not contract-complete; coverage and period checks still fail closed on
   what remains.

`source_coverage_not_attested` is now cleared for both tickers.

**Current state:** CALM has 5 annual periods, LTM constructed, 90 passing checks. MSFT is blocked
on exactly one thing — `pure_da_evidence_missing`.

### Cross-source pairing repair (4th fix)

`missing_source_overlap` fired for every duration key on every period while balance-sheet instants
paired fine. Cause: CIQ dates a fiscal year from the prior year-end, XBRL from the day after
(CALM `2024-06-01` vs `2024-06-02`; MSFT already agreed at `2024-07-01`).
`_period_starts_describe_one_window()` now allows exactly one day, applied to both the
amount-to-amount and expected-to-amount matchers. CALM overlap findings 47 → 39, MSFT → 3.

### CALM 53-week years — a SECOND PM finance decision

Residual CALM gaps are real, not conventional. CIQ normalizes to ~52 weeks; XBRL reports the actual
calendar: FY2023 is 365d (CIQ) vs **371d** (XBRL, 53-week year), FY2024 366d vs 364d. Those windows
differ by a week of trading. The system correctly refuses to pair them. Whether CIQ's normalized
window counts as comparable to the as-reported fiscal year is finance semantics — do not widen the
tolerance to make it pass.

### Treatment seam wired — the D&A gate is now resolvable (2026-07-31)

`pure_da_evidence_missing` was previously **unresolvable in code**: `treatment_decisions` existed
but nothing consulted it for source coverage, so approving any D&A option would have changed
nothing. `_treatment_supplies()` now honours an active PM-approved treatment supplying a canonical
key (from `driver_field`, or explicit `canonical_key`), threaded through
`_semantic_source_reason_codes`, `_annual_period_count`, `_expected_source_quantities`, and
**`_bounded_selected_view`** — the last mattered most, because the bounded view derives its bound
from the complete annual periods and without treatments collapsed MSFT's 2,559 manifest-bound facts
to 179 covering one period, making every downstream check report "missing".

Verified on cached MSFT (demo treatment in a throwaway DB; the real DB is untouched and still
correctly blocked):

| MSFT | annual periods | checks | reasons |
|---|---|---|---|
| no treatment (real DB) | 0 | none run | 7, incl. `pure_da_evidence_missing` |
| approved treatment (demo) | **5** | **166 pass** / 7 not_ready / 2 fail | 5 |

Also fixed a latent `TypeError` in `_expected_source_quantities`: it sorted tuple keys containing
an optional `period_start`, which raised as soon as a ticker had both duration and instant
expectations.

### PM decisions RESOLVED 2026-07-31

**1. MSFT D&A → source `da` from CIQ, log the disagreement.** Implemented as a generic rule keyed
on the disclosure shape, never on a ticker: where XBRL presents only a combined "depreciation,
amortization, and other" line and CIQ supplies `da` for the same period, `da` comes from CIQ.
`_combined_da_resolved_by_ciq()` is honoured by `_semantic_source_reason_codes`,
`_annual_period_count`, and `_expected_source_quantities`; the XBRL-side `da` expectation is
dropped for such filers. Fail-closed survives — with no CIQ D&A, `pure_da_evidence_missing` still
blocks.

**2. CALM 53-week years → non-comparable; re-pull CIQ on the as-reported calendar.** The
non-comparable half is already the implemented behaviour (the one-day tolerance covers the
convention gap only). **The re-pull is a manual Excel action and is the remaining CALM blocker** —
it also clears the FY2026 period the current workbook does not cover.

Two further defects surfaced once MSFT actually carried periods, both fixed:
- `_expected_source_quantities` raised `TypeError` sorting tuple keys with an optional
  `period_start`, once a ticker had both duration and instant expectations.
- The cash expectation is looked up on the balance sheet but chose its key from *all* statements.
  MSFT and CALM both report `CashCashEquivalents...RestrictedCashAndRestrictedCashEquivalents` on
  the **cash flow** statement while the balance sheet carries plain cash and equivalents.

Result: MSFT **0 → 4 annual periods, 0 → 149 passing checks**. CALM 5 periods, 95 passing.

### MSFT D&A — original analysis (kept for context)

MSFT's cash-flow face reports only the extension `msft_DepreciationAmortizationAndOther`. There is
**no pure D&A concept anywhere in the ingested MSFT XBRL** (note-level facts are not ingested), so
`_cash_flow_coverage` fails on `da` for every period and MSFT counts 0 annual periods. CALM passes
because it reports standard `us-gaap_DepreciationDepletionAndAmortization`.

The impurity is material and growing: FY25 CIQ D&A $28.0bn vs XBRL combined $34.15bn = **+$6.15bn
(+22%)**; FY24 +11%; FY23 +2.7%. Options, none of which should be picked without the PM:

- source pure D&A from the PP&E note (requires ingesting note-level XBRL — a new slice);
- accept the combined line under a recorded treatment carrying the known bias;
- source `da` from CIQ where XBRL only has a combined line, with the disagreement recorded.

### CALM calculation rollup — FIXED (three defects)

CALM checks moved from **90 pass / 48 not_ready / 6 fail** to **95 pass / 3 not_ready / 4 fail**.

1. **Rollup ran on the vintage-collapsed selected view.** `_selected_consolidated_xbrl_facts`
   keeps the newest vintage per concept — right for restatements, wrong for a linkbase. CALM's
   2022-05-28 balance sheet took `Liabilities` from the FY2023 filing and
   `StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest` from the FY2025
   comparative, so the equity child grouped under a different accession than its parent
   (`parent_fact_count=0` → `not_ready`) and the parent's own group summed short → `failure`.
   `_statement_checks` now takes `rollup_facts` and the reconciler passes the full fact set.
2. **Abbreviated comparatives were held to a full rollup.** Each (statement, role, period) now
   uses the filing that presents it most completely — in practice the filing that reported it as
   its current year.
3. **Repeated presentation occurrences were double-counted.** A concept presented twice under one
   parent was summed twice: parent 1,427,489,000 vs components summing 2,531,834,000, the
   difference being exactly one duplicated child. Parents and children are now deduped on
   (concept, value); two *different* concepts sharing a value are still both counted.

Five regressions added in `tests/test_statement_reconciliation_service.py`.

### Original diagnosis (kept for context)

6 `source_calculation_rollup_failure` findings block CALM. Not accession mixing (that guard works).
Worked case — CALM 2022-05-28, accession `0001562762-23-000287`, ConsolidatedBalanceSheets:

- reported: only `us-gaap_Liabilities` = 323,144,000 matched against parent
  `us-gaap_LiabilitiesAndStockholdersEquity` = 1,427,489,000;
- the filed calculation linkbase **has** all three edges including
  `StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest` (weight 1.0);
- an **undimensioned** fact for that child exists on the same statement/role/accession/period =
  1,104,345,000;
- concept strings are byte-identical and `_concept_token()` agrees;
- 323,144,000 + 1,104,345,000 = 1,427,489,000 **exactly**.

So component-to-fact matching in `_calculation_rollup_checks` is dropping the equity fact. Lead:
2022-05-28 is the *comparative* period inside the FY2023 filing — check whether the manifest's
`presented_fact_ids` inventory covers comparative facts for every child concept (`Liabilities` is
found for the same period, so the filter is not uniformly excluding comparatives). The same period
also fails `assets` with a 4.4006e+07 gap, so one root cause likely covers several parents.
**Do not widen the 1e+06 tolerance** — the components tie exactly.

## Damage — action required

`tests/test_filing_presentation.py::test_extract_filing_presentation_emits_complete_lineage_and_manifest`
was **destroyed** on 2026-07-31 by an over-broad regex edit during a fixture revert. The file is
untracked, so there is no git copy and no backup was found on disk. `_period_xbrl` was
reconstructed exactly from context and the other 14 tests pass; the lost test is now an explicit
`@pytest.mark.skip` that raises `NotImplementedError` so it cannot pass silently. If the Codex
session transcript or worktree still holds the file, restoring it is a copy-paste.

## Current Implementation Checkpoint — 2026-07-26

This section supersedes the older implementation notes below.

- Added accession-specific XBRL presentation/calculation ingestion, complete CIQ three-statement
  manifests, authoritative source reconciliation, bounded statement views, and operating-model
  reconciliation.
- Added four provider-neutral judgment families with one strict schema for OpenAI-compatible,
  OpenRouter, Codex, and fixture backends; all calls now carry finite timeouts and immutable
  envelopes.
- Added exact-snapshot four-family approval loading, frozen-case compilation, deterministic
  provider-free DCF/comps/bridge replay, provenance validation, and immutable replay persistence.
- Added `ticker_valuation_execution.py`: every prepared ticker enters the same path; official
  inputs explicitly disable ticker overrides, story overlays, and public peer fallbacks.
- Added bounded no-drop batch execution and a heterogeneous MSFT/CALM/IBM/BAH/LYFT/IESC contract
  test. Exact duplicate contexts are deduplicated instead of aborting the universe.
- Added durable `ticker_terminal_outcomes` checkpoints and
  `GET /api/tickers/{ticker}/valuation/outcomes`.
- Closed the public replay bypass: `decision_grade` execution reloads the persisted replay and
  binds its replay key, ticker, snapshot, readiness, result, and output hash to the frozen context.
- Serena 1.6.1 is running through the local project server on port 9121. Its generated data cache
  is ignored in `.serena/project.yml`; the temporary `uv`/Pyright runtime is under `C:/tmp`.

Focused production-path verification is green: 215 tests covering XBRL/CIQ ingestion, statement and
operating reconciliation, provider conformance, timeouts, PM approvals, replay, batching, terminal
storage, and API exposure. Ruff is clean on the touched Python files. `.git/lfs/tmp` is empty.

The honest isolated MSFT tracer is currently `blocked` with no provider call:
`source_coverage_not_attested`, `balance_sheet_identity_missing`,
`cash_flow_to_cash_bridge_missing`, `insufficient_annual_history`,
`complete_presentation_history_missing`, and `ltm_not_ready`.

Remaining work is source-bound, not a finance fallback: cache complete filing linkbase bundles and
a current MSFT CIQ workbook, refresh a structurally different second issuer, run the real
cross-sector shadow comparator, then decide cutover. CALM has a valid non-calendar CIQ workbook but
no matching XBRL presentation source; IBM/BAH/LYFT/IESC also remain explicitly source-blocked.

## Recent Actions

- Added `src/stage_04_pipeline/accounting_discovery_ledger.py`: the adapter from per-question
  recast payloads to `AccountingFinding` records, the existing `merge_findings_into_ledger`, and
  `translate_accounting_ledger_to_queue_items`. The ledger and translator themselves are unchanged.
  Mapping table and logged engineering decisions are in the canonical plan under
  "Discovery-To-Ledger Adapter".
- Every mapped finding is run through the shared `validate_accounting_finding` before merge, using
  a synthesized per-question packet whose `source_refs` are the matched
  `{accession_no}::{section_key}` sections. A finding that fails validation is kept as
  `rejected_after_repair`, never dropped.
- `run_discovery_accounting_pass` moved the per-question loop out of the CLI so the
  business/industry/quantitative/current-model context contract is testable offline. It persists
  nothing unless a connection is supplied.
- Added `quantitative_context` to `AccountingRecastAgent.analyze` and its prompt. Focused recast
  calls previously received business/industry/current-model context but **not** the quantitative
  block; requirement 5 was not actually met before this.
- `_apply_override_guards` now records only fields it actually cleared. Every one of the six MSFT
  recasts previously reported `guarded_override_fields: ["lease_liabilities"]` even though one call
  proposed the override.
- Added `filing_retrieval.get_accounting_corpus_coverage` / `require_accounting_corpus_coverage` so
  the fail-closed corpus gate is a library call instead of a `scripts/manual` import. Verified
  against cached MSFT: 12 cached filings, 8/8 required 10-K/10-Q parsed at `v1_sections_v6`.
- `_queue_title` drops the focus prefix for `model_change_required` findings, which were being
  labelled "Accounting: qoe revenue — ..." for structural proposals unrelated to revenue.
- `_finding_metadata` now carries producer metadata (the discovery `question_id`) onto the queue
  item under `finding_metadata`.
- `scripts/manual/run_accounting_discovery.py --with-recast` now prints ledger/queue counts and
  writes them into the artifact. Queue persistence is opt-in behind `--persist-queue`.

## Verification

- `tests/test_accounting_discovery_ledger.py`: 15 offline regressions covering multi-question
  fan-out, cross-question duplicates and conflicts, no-adjustment visibility, unsupported
  treatments becoming model-change requests, the guard never producing a queue candidate, the
  four-context contract on every focused call, the fail-closed corpus gate, and no-persistence
  without a connection.
- Cached MSFT replay of both live artifacts, no LLM call, nothing persisted:
  unguarded 28 ledger entries / 18 advisory queue items / **0 assumption packs**;
  guarded 27 / 15 / **0**. The three-entry difference is exactly the lease double-count.
- Full offline suite: **916 passed, 21 failed, 5 errors, 2 deselected**. 20 of the 21 failures are
  the permission-locked `.tmp-tests/` directory (`test_ciq_adapter`, `test_export_service`,
  `test_release_readiness`, `test_ticker_dossier_persistence`, `test_industry_agent`). The one real
  assertion failure is pre-existing:
  `test_evidence_packet_builders.py::test_accounting_packet_collects_retrieval_profile_sections_and_source_locators`
  expects the 10-K document URL at `source_refs[0]`, but XBRL Slice B put the SEC accession-index
  ref first. `evidence_packets.py` was not touched in this session.
- Strict MkDocs build passed to `output/mkdocs-claude-verify`.
- Second-company generality attempt (IBM): the corpus build ran cache-only and the gate correctly
  refused the ticker — one of IBM's five cached 10-K/10-Q filings is a synthetic test fixture
  (`0000123456-26-000001`, `annual.htm`), and the four real ones yield only 1–5 sections and zero
  raw numbered notes versus 16–19 for MSFT. Generality is still untested; the blocker is corpus
  depth and fixture pollution, not the adapter. **This build wrote 8 new `v1_sections_v6` section
  rows (319 chunks) for IBM into `data/alpha_pod.db`.** No LLM call, no queue item, no valuation
  change. A live IBM discovery/recast run needs PM approval for model and cost.

## Proposable-Surface Repair (the reason classification reached valuation)

The first validation produced 18 queue items and **zero** assumption change packs. The cause was
not the adapter: `AccountingRecastAgent` could only name five EV-bridge claims. Every driver that
moves the DCF forecast was unreachable — the mechanical cause of the `llm_reasoned: 0` provenance
audit. Per Standing Rule 6 the deliverable was wiring the seam:

- `driver_proposals` added to the recast response contract, validated against all 21
  `AGENT_PROPOSABLE_ASSUMPTION_FIELDS`. A name outside the set is dropped rather than remapped; a
  proposal without a value is not a proposal; the lease guard clears a blocked driver proposal.
- The adapter maps each entry to a candidate whose claim and proposed driver match, so it becomes
  an assumption change pack for PM approval.
- Live MSFT rerun (`gpt-5.4-mini` @ low, dry run,
  `output/accounting_discovery/MSFT-20260725T175203Z.json`): 37 ledger entries, 21 queue items,
  **1 assumption change pack** (`non_operating_assets` = $111.955bn, six filing anchors), and one
  genuine unconstructed conflict group on `ebit_margin_target`.
- Two adapter defects the live run exposed were fixed: one `(driver, value)` pair inside one
  question is now one claim across all three channels (reclassification / driver proposal /
  override candidate), which removed a phantom self-contradiction and duplicate packs.

## New Canonical Plan — Reconciled Statement Ledger

`docs/plans/active/2026-07-25-reconciled-statement-ledger.md` (registered in the plan index).

The PM chose reconciliation over sanity bands after a fourth double-count surfaced. Applying the
idea by hand immediately found a **live bug on every ticker holding cash**: `net_debt` nets all
cash while `_derive_non_operating_assets` credits excess cash again, so MSFT equity is overstated
by $25.74bn = **$3.45/share**. Both defensible conventions give -93,327m; only the code gives
-67,587m. Not yet fixed — Phase 1 Task 1.3, and it moves shipped IV on every name.

PM decisions recorded (settled, do not re-open): XBRL *and* CIQ reconciled against each other;
split operating-versus-excess cash convention; fail closed with tolerance. Scope was resolved by
evidence rather than preference — see below.

Why the operating layer is Phase 2/3 rather than optional: the CIQ snapshot ingests **no**
balance-sheet working-capital levels (only `dso`/`dio`/`dpo` ratios) and **no** cash-flow lines
(only `capex_ttm`/`da_ttm` scalars). NWC is derived from ratios with nothing to tie against, which
is exactly why the D&A=0 bug survived into a clamp. You cannot run double-entry on a ledger that
was never ingested, so statement ingestion is a dependency, not a nice-to-have.
`input_assembler.py` has **36 `_bounded()` clamp sites**, each able to turn a parse error into a
plausible number silently.

## Resolved Finance Decisions — 2026-07-26

Agents author direct low/base/high values for every applicable forward driver. Structural schema
and reconciliation failures reject; broad plausibility ranges warn and never clamp. The historical
foundation targets five annual periods plus LTM, with three annual periods required. Source ties
use the greater of USD 1m or 0.05% of gross balance. Operating cash defaults to 2% of revenue with
lineage and later evidence-backed PM adjustment. Story-score arithmetic is context-only. WACC
remains deterministic. Model-change requests are explicit and blocking when material.

## Next Steps

- Finish repository/test-baseline stabilization without disturbing the existing research work.
- Add the provider-independent structured-run and replay contract.
- Build the complete statement ledger and source reconciliation before shipping the bridge repair.
- Implement direct driver-family packs and remove numeric story/canned translator paths.
- Validate cross-sector names and then every eligible ticker; every requested ticker must return a
  valuation state or an explicit blocker.

## Known Issues

- The worktree contains extensive pre-existing edits; preserve them. Current branch:
  `codex/focused-accounting-evidence-repair`.
- Queue volume: one six-question MSFT run produces 15–18 advisory items. No cap was added — the
  plan says volume is handled by ranking, not by collapsing accounting reasoning upstream. Whether
  that fits the daily budget is a PM call.
- The repository `site/` tree is permission-locked. Strict docs verification succeeds when built
  to `output/mkdocs-codex-verify`.
- `.pytest_cache` is permission-locked; run pytest with `-p no:cacheprovider`.

## Notes

- Runtime: `C:/Users/patri/miniconda3/envs/ai-fund/python.exe`.
- Canonical plan:
  `docs/plans/active/2026-07-25-reconciled-statement-ledger.md`.
- Live artifacts: `output/accounting_discovery/MSFT-20260725T155924Z.json` (unguarded) and
  `-guarded.json`. Both replay through the adapter with zero assumption packs.
- Discovery command:
  `python scripts/manual/run_accounting_discovery.py --ticker MSFT --with-recast`.
- Serena resume memory: `mem:workstreams/accounting_classification`.
- 2026-07-27 personal Codex-skill review: only personal skills under
  `C:\Users\patri\.codex\skills` were updated; no repository code or repo-local skills were
  changed.
- Deep follow-up scanned and deduplicated historical direct sessions, separated subagent/system
  noise, and left all repo-local skills untouched. All 24 personal skills now pass structural
  validation; no new personal skill was created.

## Stop Log — 2026-07-26

- PM ordered an immediate stop. All three active subagents were interrupted; the temporary Serena
  project server is no longer listening.
- Added an explicit provider-binding factory and scalable valuation CLI:
  `valuation_provider_bindings.py` and `valuation_workup_cli.py`. Their 9 focused tests pass and
  Ruff is clean, but the slice has not received independent review.
- The interrupted production-wiring slice added `valuation_workup_service.py`. Its focused work was
  nearly complete, but the last observed combined run still had one failing identity-mismatch test;
  treat the file as mid-handoff.
- On isolated DB `C:\tmp\alpha_pod_reconcile_20260726_1.db`, real MSFT and CALM XBRL + CIQ ingestion
  succeeded. Serena traced readiness collapse to canonical statement mappings. Further work found a
  finance-semantic blocker: MSFT `DepreciationAmortizationAndOther` is materially larger than pure
  CIQ D&A and must not be silently mapped to D&A.
- Codex CLI backend hardening was interrupted mid-edit after review identified host-file/tool
  exposure. Do not treat that backend as production-safe until its diff and focused tests are
  inspected.

## Immediate TODO

1. Inspect the three interrupted slices for partial edits; run their focused tests before changing
   anything.
2. Finish source refresh/reconciliation generically for MSFT and CALM, keeping the combined
   D&A-and-other line fail-closed unless a true D&A source or PM-approved treatment is supplied.
3. Finish and independently review Codex isolation, provider bindings, workup service, CLI, and the
   thin API trigger.
4. Ask the PM to settle DCF/comps/per-share comparator materiality thresholds, then implement the
   legacy/new delta comparator and cutover.
5. Run full verification, update the active plan/docs, and only then attempt an honest end-to-end
   MSFT plus second-issuer production run.
