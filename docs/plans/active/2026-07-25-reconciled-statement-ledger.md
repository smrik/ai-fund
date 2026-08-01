# Reconciled Statement Ledger Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: use superpowers:executing-plans to implement this plan
> task-by-task.
> **For Codex:** work task-by-task with TDD. The PM decisions in
> [PM Decisions](#pm-decisions--recorded-2026-07-25) are settled; do not re-open them.

**Vision decisions served:** 1, 2, 10, 11, 12, 13, 14, 15, 16.

**Goal:** Produce a complete, reconciled, judgment-authored DCF and comps workup through one
provider-independent pipeline that behaves consistently for every ticker. MSFT is the first
tracer bullet, never a ticker-specific implementation.

**Scale contract:** every requested ticker reaches a terminal result: `decision_grade`,
`provisional`, or `blocked` with machine-readable reasons. No ticker may disappear through a
broad exception, acquire a symbol-specific finance rule, or depend on which supported LLM API
transport happened to execute the judgment call.

## CALM Workbook Refresh — 2026-07-31 19:37

The PM re-exported `CALM_Standard.xlsx` on the as-reported fiscal calendar. Outcome:

- FY2026 and FY2025 now pair (1-day convention gap); CIQ picked up the new FY2026 year.
- FY2024 (2-day gap) and FY2023 (6-day, the 53-week year) still do not pair — Capital IQ
  normalizes those historically and the re-export does not change them. They are now recorded as
  `non_comparable_fiscal_window` **warnings** rather than blocking failures, which is the second
  half of the PM's "non-comparable" decision.
- **Finding severity now gates status.** `severity` was recorded but never read, so
  `status = "review_required" if findings else "pass"` treated a warning exactly like a real
  disagreement. Only blocking-severity findings force `review_required`; warnings stay visible and
  still hold a ticker short of decision-grade.

CALM now blocks on **seven genuine figure disagreements**, which is the machinery working rather
than a defect:

| Period | Figure | SEC filing | Capital IQ | Gap |
|---|---|---|---|---|
| FY2026 | `operating_income` | 350,186,000 | 343,352,000 | 6.8m |
| FY2025 | `operating_income` | 1,536,539,000 | 1,558,036,000 | 21.5m |
| FY2022 | `operating_income` | 143,537,000 | 138,428,000 | 5.1m |
| FY2026 | `net_income` | 318,112,000 | 316,682,000 | 1.4m |
| FY2025 | `net_income` | 1,218,232,000 | 1,220,048,000 | 1.8m |
| FY2026 | `da` | 124,342,000 | 117,577,000 | 6.8m |
| FY2025 | `da` | 94,021,000 | 91,863,000 | 2.2m |

The `net_income` gaps look like attributable-to-parent versus including noncontrolling interests;
`operating_income` and `da` look like classification differences. Each needs a PM ruling, or a
standing precedence rule.

**RESOLVED 2026-07-31 — PM chose "filing wins, gap logged" for the DCF path.**

The PM raised a real counterpoint while deciding: Capital IQ's value is cross-company *consistent*,
which matters more than per-filing fidelity when building comparables. That is correct, and the two
requirements do not conflict — **comparables read `ciq_comps_snapshot` through a separate path**
(`ciq_adapter.py:418`) and never touch statement reconciliation. So:

| Consumer | Authoritative source | Rationale |
|---|---|---|
| DCF (this pipeline) | SEC filing | the company's own reported figures |
| Comparables (separate table) | Capital IQ, unchanged | cross-company consistency across the peer set |

`material_disagreement` is therefore advisory: the filing value is used and the gap is recorded for
review. **Two patterns still block**, because each is a parse or convention failure rather than a
difference of opinion, and each has shipped a wrong valuation before:

1. one side reports zero while the other reports a real amount — the D&A=0 parse bug that
   understated base intrinsic value by roughly 18%;
2. the two values carry opposite signs — a sign-convention error.

**Superseded LTM windows.** CALM derives an LTM ending 2026-02-28 while FY2026 closes 2026-05-30,
and Capital IQ publishes its own LTM on different dates (2025-11-29, 2026-05-30). A trailing window
closing before the most recent complete annual period carries nothing the annual data does not
already cover more recently, so it no longer raises cross-source expectations.
MSFT is unaffected — its LTM window matches Capital IQ's exactly.

## Status — 2026-07-31

| Ticker | Status | Annual periods | LTM | Statement checks |
|---|---|---|---|---|
| MSFT | **`provisional`** (was `blocked`, 0 periods, 0 checks) | 4 | unavailable | **149 pass, 0 fail** |
| CALM | **`provisional`** (was `blocked`) | 5 | constructed | **95 pass, 0 fail** |

**Neither ticker is blocked.** Both reach a terminal, usable state under the scale contract.
Residual reasons on both are non-blocking: `cash_flow_to_cash_bridge_not_ready`,
`source_calculation_rollup_not_ready`, plus `ltm_not_ready` on MSFT and
`source_overlap_inventory_incomplete` on CALM.

CALM retains 7 `material_disagreement` findings and 14 `non_comparable_fiscal_window` warnings as
visible review items — the filing value is used and the gaps are recorded, per the PM decision.

### Cross-source pairing repairs

After the fiscal-window fix, MSFT's residual overlap findings were traced to four separate
defects, all fixed:

| Defect | Effect |
|---|---|
| CIQ row names `cash_from_ops` and `net_change_in_cash` were absent from the canonical alias table | CIQ reported "missing" `operating_cash_flow` and net-change on every period although the workbook carries both |
| `net_income` required an identical statement on both sides | CIQ prints it at the top of the indirect cash flow statement, XBRL on the income statement — the same quantity never paired |
| The two net-change-in-cash variants were treated as different quantities | Declaring one "missing" hid the comparison; they are now alternates so the value tolerance arbitrates, and a filer with material restricted-cash movement surfaces as a disagreement instead of a silent gap |
| The XBRL `da` expectation was still raised for LTM windows | The combined-line rule was applied to annual periods only |

### Calculation-rollup ambiguity

A concept presented more than once under one parent with **different** values is ambiguity, not a
sum. MSFT presents `us-gaap_CommercialPaper` twice at 2024-06-30 (6,700,000,000 and 6,693,000,000);
summing both failed the rollup by exactly the extra occurrence. Which figure is correct is not
something deterministic code can decide, so the check now reports `not_ready` naming the
conflicting concepts rather than guessing or manufacturing a failure. This cleared MSFT's 2 and
CALM's 4 rollup failures.

## Source-Gate Repair — 2026-07-31

Re-running reconciliation on current code exposed three **false** blockers. In every case the
underlying data was present and correct; the gate was wrong. All three are fixed with regressions.

| Blocker | Cause | Fix |
|---|---|---|
| `source_coverage_not_attested` on every ticker | `ltm_status` demanded exact set equality over every presented line item — MSFT built 74/91 identities, CALM 38/120 | `resolve_ltm_status()`: exclude dimensioned identities (Decision 7), measure against `LTM_REQUIRED_CANONICAL_KEYS` scoped to keys the source actually presents (Decision 6) |
| Re-ingestion could never supersede stale manifests | Selection ordered by `evidence_cutoff DESC`, but that is a filter bound, not recency — stale manifests carry run-date cutoffs, fresh ones filing-date cutoffs | Break ties on `created_at` |
| One orphaned manifest blocked a ticker permanently | MSFT kept a FY2021 manifest from an earlier wider window that no current refresh reaches | Selection skips manifests that are not contract-complete; coverage still fails closed on the remainder |

Result: MSFT and CALM both reach `xbrl status=completed`, `ltm_status=constructed`, and
`source_coverage_not_attested` is cleared for both. CALM now carries 5 annual periods, LTM
constructed, and 90 passing statement checks.

### Cross-source pairing repair

`missing_source_overlap` fired for every duration key on every period (revenue, operating income,
net income, D&A, capex, operating cash flow) while balance-sheet instants paired fine. Cause:
providers disagree on how a duration is *dated*. CIQ starts a fiscal year on the prior year-end;
XBRL starts it the day after:

| ticker | CIQ period_start | XBRL period_start |
|---|---|---|
| MSFT (fixed 6/30 year end) | `2024-07-01` | `2024-07-01` — already agreed |
| CALM (52/53-week calendar) | `2024-06-01` | `2024-06-02` |

`_period_starts_describe_one_window()` now allows a one-day difference, which is the whole
convention gap. A 53-week year differs by seven days, so the tolerance cannot merge genuinely
different windows. Applied to both the amount-to-amount and expected-to-amount matchers.
CALM's overlap findings fell 47 → 39 and MSFT's to 3.

### Calculation-rollup repair

CALM's rollup checks were dominated by noise from three separate defects, all fixed:

| Defect | Effect | Fix |
|---|---|---|
| Rollup ran on the vintage-collapsed *selected* view | `Liabilities` came from the FY2023 filing and `StockholdersEquity…` from the FY2025 comparative, so the equity child grouped under a different accession than its parent — parent matched zero children | Roll up on the full fact set; the identity tuple already partitions by accession |
| Every vintage was rolled up, including abbreviated comparatives | A later filing repeats prior periods in reduced form; holding those to a full rollup manufactured failures | Each (statement, role, period) uses the filing that presents it most completely |
| Repeated presentation occurrences were summed twice | A concept presented twice under one parent counted twice — parent 1,427,489,000 vs components summing 2,531,834,000, the difference being exactly one duplicated child | Dedupe parents and children on (concept, value); genuinely different concepts sharing a value are kept |

CALM statement checks moved from **90 pass / 48 not_ready / 6 fail** to **95 pass / 3 not_ready /
4 fail**.

The residual four are small and genuine, not systematic: differences of 1.9m, 1.9m, 1.4m and 6.2m
against parents of 126m, 22m, 48m and 67m, three of them on CALM's oldest annual period
(2022-05-28), whose cash bridge also lacks a prior-year opening balance. They are real
presentation quirks in the filings, so the fail-closed gate is behaving correctly.

**Open design question (not yet a PM decision):** `assess_statement_readiness` blocks on *any*
failing check on *any* period. Decision 6 sets five annual periods as the target and **three** as
the decision-grade minimum, so a defect confined to the fourth or fifth period arguably should not
block a ticker that has three clean ones. Relaxing this would touch the settled fail-closed rule
(Decision 3), so it is recorded here rather than implemented.

### CALM 53-week years — a second PM finance decision

The residual CALM gaps are **not** a convention mismatch and must not be tolerated away:

| CALM FY | CIQ window | XBRL window | gap |
|---|---|---|---|
| 2023 | 365d | **371d** (53-week year) | 6d |
| 2024 | 366d | 364d | 2d |
| 2025 | 365d | 364d | 1d — now paired |

CIQ normalizes to a ~52-week window while XBRL reports the actual fiscal calendar including the
53rd week. Those are different economic windows — FY2023 contains an extra week of trading. The
system correctly refuses to pair them. **Whether CIQ's normalized window may be treated as
comparable to the as-reported fiscal year is a finance decision (Decision 11), not an engineering
tolerance.**

### MSFT is blocked on one finance decision

`_cash_flow_coverage` requires a `da` key. MSFT's cash-flow face reports only the extension
`msft_DepreciationAmortizationAndOther`, and **no pure D&A concept exists anywhere in the ingested
MSFT XBRL** — note-level facts are not ingested. So MSFT counts 0 annual periods. CALM passes
because it reports standard `us-gaap_DepreciationDepletionAndAmortization`.

The impurity is material and growing, so the combined line must not be silently mapped to `da`:

| FY | CIQ D&A | XBRL "D&A and other" | gap |
|---|---|---|---|
| 2025 | $28.0bn | $34.15bn | **+$6.15bn (+22%)** |
| 2024 | $20.0bn | $22.29bn | +$2.29bn (+11%) |
| 2023 | $13.5bn | $13.86bn | +$0.36bn (+2.7%) |

**RESOLVED 2026-07-31 — PM chose option 3: source `da` from CIQ and log the disagreement.**

Implemented as a **generic rule keyed on the shape of the disclosure, never on a ticker** (the
scale contract forbids symbol-specific finance rules): where XBRL presents only a combined
"depreciation, amortization, and other" line and CIQ supplies `da` for the same period,
`da` is sourced from CIQ. `_combined_da_resolved_by_ciq()` is honoured by
`_semantic_source_reason_codes`, `_annual_period_count`, and `_expected_source_quantities`.
The XBRL-side `da` expectation is dropped for such filers, because demanding a pure D&A the filer
never reports raised a blocking `missing_source_overlap` on every period for a gap the decision
already resolves. Fail-closed survives: with no CIQ D&A either, `pure_da_evidence_missing` still
blocks.

Two further defects surfaced and were fixed once MSFT actually carried periods:

- `_expected_source_quantities` sorted tuple keys containing an optional `period_start`, raising
  `TypeError` as soon as a ticker had both duration and instant expectations.
- The cash expectation is looked up on the balance sheet but its key was chosen from *all*
  statements' keys. MSFT and CALM both report
  `CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents` on the **cash flow** statement
  while the balance sheet carries plain cash and equivalents, so the check demanded a
  balance-sheet line that never exists.

MSFT moved from **0 annual periods and no checks executed** to **4 annual periods and 149 passing
statement checks**.

Original options, retained for context:

1. **Ingest note-level XBRL** and source pure D&A from the PP&E note. Most correct; a new slice.
2. **Accept the combined line** under a recorded treatment that carries the known bias forward.
3. **Source `da` from CIQ** where XBRL has only a combined line, recording the disagreement.

#### The treatment seam is now wired (2026-07-31)

The gate was previously *unresolvable in code*: `pure_da_evidence_missing` had no path past it, so
approving any of the three options above would have changed nothing. `treatment_decisions` existed
but nothing consulted it for source coverage.

`_treatment_supplies()` now honours an active, PM-approved treatment that supplies a canonical key
(read from `driver_field`, or an explicit `canonical_key`), and it is threaded through
`_semantic_source_reason_codes`, `_annual_period_count`, `_expected_source_quantities`, and
`_bounded_selected_view`. The last one mattered most: the bounded view derives its bound from the
complete annual periods, so without treatments it collapsed MSFT's 2,559 manifest-bound facts to
179 covering a single period — every downstream check then reported "missing" rather than the real
reason.

Deterministic code still never picks the convention. Verified on cached MSFT:

| MSFT | annual periods | statement checks | reason codes |
|---|---|---|---|
| no treatment (current, correct) | 0 | none run | 7, incl. `pure_da_evidence_missing` |
| with an approved treatment | **5** | **166 pass** / 7 not_ready / 2 fail | 5 |

The approval itself remains the PM's. The mechanism to act on it now exists.

A latent ordering defect surfaced once MSFT carried multiple periods:
`_expected_source_quantities` sorted tuple keys containing an optional `period_start`, raising
`TypeError` as soon as a ticker had both duration and instant expectations. Fixed by coercing
`None` for ordering only.

## Why This Plan Exists

Three bugs of the same shape have now been found by hand, one at a time:

| Bug | Size | Found |
|---|---|---|
| Lease liabilities counted in CIQ debt *and* as a separate claim | ~$7/share | 2026-07-25, by hand |
| D&A parsed as `0`, then floored by a clamp to 0.5% of revenue | ~18% of base IV | 2026-07-25, by hand |
| Cash netted inside `net_debt` *and* credited again as excess cash in `non_operating_assets` | $3.45/share, **still live on every ticker** | 2026-07-25, by reconciliation |

A fourth was caught before it reached the model: the accounting agent proposed
`non_operating_assets = $111.955bn` ("cash plus debt and equity investments…") on top of a
`net_debt` that had already netted that cash — **+$11.56/share** of phantom equity value.

Every one of these numbers is *individually plausible*. $85bn is a correct lease balance. $25.7bn
is a correct excess-cash figure. $112bn is a correct sum of the fair-value note. Magnitude checks
and sanity bands cannot catch any of them, because the failure is not magnitude — it is
**identity**: one reported balance credited to equity twice.

The current defence is `blocked_override_fields`, a hand-maintained set with exactly one entry
(`lease_liabilities`), added after someone found that bug manually. It could not catch bugs 2, 3,
or 4. This plan replaces enumeration with derivation.

## Current-State Diagnosis

### The bridge can be reconciled today

`net_debt`, `cash`, `total_debt`, `lease_liabilities`, `minority_interest`, and
`shares_outstanding` are all present in the CIQ snapshot. The bug is that two derivations both
consume cash:

```python
# input_assembler.py — net_debt
net_debt = ciq["total_debt"] - ciq["cash"]                    # all cash credited here

# input_assembler.py::_derive_non_operating_assets
excess_cash = max(cash - 0.02 * revenue_base, 0.0)            # same cash credited again
```

`professional_dcf` then computes `equity = EV + non_operating_assets - claims`, where `claims`
includes `net_debt`. MSFT: `-93,327m + 25,740m = -67,587m` where either defensible convention
gives `-93,327m`. Equity is overstated by exactly the excess-cash figure.

### The operating layer cannot be reconciled at all yet

This is the answer to "are there no bugs in working capital?" — there are, and it is worse there,
because **nothing is ingested to reconcile against**. The CIQ snapshot exposes:

| Statement | What is ingested | Reconcilable? |
|---|---|---|
| EV→equity bridge | `cash`, `total_debt`, `lease_liabilities`, `minority_interest`, `shares_outstanding` | **yes** |
| Working capital | `dso`, `dio`, `dpo` — *ratios only*. No AR, no inventory, no AP, no total assets, no equity | **no** |
| Cash flow | `capex_ttm`, `da_ttm` — scalars only. No CFO, no reported capex or D&A lines | **no** |

NWC is derived as `ratio × revenue / 365` and never compared to a reported balance. That is
precisely why the D&A bug survived: there was no reported D&A line to tie against, so a `0` passed
through `_bounded()` and became a plausible 0.5% of revenue.

`input_assembler.py` contains **36 `_bounded()` clamp sites**. Each one converts an out-of-range or
missing input into a plausible in-range number with no record that it did so. Every clamp over an
unreconciled input is a place a parse error becomes a valuation.

**You cannot run double-entry on a ledger you never ingested.** Reconciling the operating layer
therefore requires ingesting real statements first — which is why the phasing below is not
optional sequencing but a dependency.

## PM Decisions — Recorded 2026-07-25

Interview-first per Decision 10; these are settled and must not be re-litigated.

1. **Ledger of record: XBRL *and* CIQ, reconciled against each other.** Filing XBRL facts are
   authoritative; CIQ is reconciled against them and any disagreement becomes a PM item. This is
   itself a double-entry check and is the only option that would have caught the D&A parse bug.
2. **Bridge convention: split operating versus excess.** `net_debt` nets the *operating cash
   buffer* only; excess cash sits in `non_operating_assets`; leases are a separate claim. More
   analytically explicit than folding everything into net debt, at the cost of more moving parts —
   which is exactly what the reconciliation is there to police.
3. **Failure behaviour: fail closed, with a rounding tolerance.** No valuation ships until the
   bridge ties. This matches the existing posture of the accounting corpus gate and is the only
   option under which a plausible-but-wrong number cannot silently reach a model.
4. **Scope: resolved by evidence rather than preference.** The bridge is reconcilable now; working
   capital and cash flow are not reconcilable until the statements are ingested. Phases 1–3 below
   deliver bridge reconciliation, then statement ingestion, then operating reconciliation.
5. **Ship the full statement foundation, not a bridge-only repair.** The bridge may be developed
   first as a tracer bullet, but it stays shadow-only until complete consolidated income,
   balance-sheet, and cash-flow history is persisted and the operating model reconciles.
6. **History target: five annual periods plus LTM.** Three complete annual periods is the minimum
   for decision-grade status. LTM is built only from period-compatible facts.
7. **Statement coverage: every presented consolidated line.** Dimensioned facts are retained with
   lineage but do not enter the consolidated calculation view implicitly.
8. **Tolerance: dual rounding rule.** A comparison ties when the difference is no more than the
   greater of USD 1m or 0.05% of the larger gross reported balance. Currency and scale must match
   before this test is applied.
9. **Operating cash policy: 2% of selected revenue.** The value is centrally configured and
   lineage-bearing; an evidence-backed alternative requires a PM-approved treatment.
10. **Forward assumptions are agent-authored directly.** Each focused driver family returns
    low/base/high values, horizon, conditions, rationale, and evidence anchors. Deterministic code
    validates and computes but never chooses the magnitude.
11. **Primary plus critic.** One focused agent authors a family pack and a second grounded agent
    challenges it. Conflicts remain visible; they are never averaged.
12. **Story scores are context only.** Fixed story-score arithmetic and canned translator deltas
    have no numeric role, including on OpenRouter or fallback paths.
13. **Provider and ticker independence.** OpenRouter, direct OpenAI-compatible APIs, and Codex
    backends share one versioned request/response contract and one validator. Every ticker uses
    the same fact-selection, applicability, queue, and valuation path.
14. **Shadow then cut over.** Legacy and new results are compared across the eligible universe;
    there is no permanent feature flag.

### Consequence of Decision 2 that must be implemented, not assumed

Under the split convention the current `net_debt` derivation is wrong in both terms:

```text
net_debt = total_debt(incl. leases) - ALL cash          # today
net_debt = total_debt(ex leases)   - operating_cash     # required
lease_liabilities = leases as a separate claim          # required (currently forced to 0)
non_operating_assets = excess cash + investments        # required
```

`lease_liabilities` is currently pinned to `0.0` with lineage `already_in_ciq_net_debt`. Under the
chosen convention it becomes a live claim, and the `blocked_override_fields` lease guard must be
*removed* rather than kept — keeping it would block a claim the model now needs.

**Equity value must not move as a side effect of the convention change alone.** The only intended
value change in Phase 1 is removing the cash double-count.

## Architecture

### The claim ledger

One deterministic structure per ticker: every reported balance-sheet quantity, and which bridge
component consumes it, with what sign.

```text
reported line              claimed by              sign    source
-------------------------  ----------------------  ------  ---------------------
total_debt_ex_leases       net_debt                +       xbrl:LongTermDebt...
operating_cash_buffer      net_debt                -       derived from revenue
excess_cash                non_operating_assets    +       xbrl:CashAndCashEquiv...
operating_leases           lease_liabilities       +       xbrl:OperatingLease...
finance_leases             lease_liabilities       +       xbrl:FinanceLease...
investments, derivatives   non_operating_assets    +       xbrl:MarketableSecur...
minority_interest          minority_interest       +       xbrl:MinorityInterest
```

Two invariants, both machine-checked:

1. **Exactly-once.** No reported line may be claimed by two components. A second claim is the
   double-count bug and is rejected with both claimants named.
2. **Tie-out.** For each component, `component_value == sum(claimed lines × sign)` within
   tolerance. A component that does not tie is unreconciled and fails closed.

### How agents propose adjustments

A judgment-layer proposal does not name a driver and a number. It names **which reported lines it
consumes and how it reclassifies them**. The value is then *derived* from the ledger rather than
asserted by the model:

```json
{
  "reclassify": [
    {"reported_line": "xbrl:MarketableSecuritiesNoncurrent",
     "from_component": "unclaimed",
     "to_component": "non_operating_assets",
     "rationale": "...", "citation_text": "..."}
  ]
}
```

This makes the four known bugs *structurally unreachable*: a proposal that consumes a line already
claimed by `net_debt` is rejected by invariant 1 before it can become a queue item, and a proposal
whose arithmetic does not foot is rejected by invariant 2. The agent keeps full freedom over
*treatment* — which is Decision 16 — while losing the freedom to assert an unreconciled number.

Proposals that genuinely require a component the model does not have remain
`model_change_required` advisories, exactly as they do today.

### What stays unchanged

- The PM Decision Queue remains the only mutation bridge. Reconciliation rejects incoherent
  proposals; it never approves one.
- No LLM runs inside the deterministic layer.
- The existing accounting ledger, validator, and translator
  (`accounting_ledger.py`, `accounting_validation.py`, `accounting_discovery_ledger.py`) are
  reused; the reclassification contract becomes a new finding type flowing through them.

### Provider-independent replay envelope

Provider prose is not expected to be byte-identical. Reproducibility means that the same evidence
snapshot plus the same approved assumption pack produces the same deterministic valuation, and
that every supported provider is held to the same judgment contract.

Each judgment call persists an `AgentRunEnvelope` containing:

- ticker and agent role
- contract, prompt, and model-policy versions
- provider, requested model, actual model, and supported sampling controls
- evidence, statement-ledger, upstream-context, tool-schema, and model-version fingerprints
- normalized request, raw response, validated payload, validation errors, retry/repair count
- timing, token, and cost metadata where the provider supplies them
- a deterministic idempotency key derived from the immutable request inputs

All transports implement one `generate_structured()` boundary. Native schema output is preferred;
otherwise text is parsed and passed through the exact same Pydantic validator. One structured
repair attempt may receive validator errors; a second invalid response fails closed. OpenRouter
must not bypass schema validation.

Validated envelopes are replayable and cacheable. A replay never calls the provider and must
reproduce the same proposal, preview fingerprint, and deterministic valuation. A fresh provider
run is a new envelope and can differ analytically, but it cannot bypass the schema, evidence,
critic, PM approval, or reconciliation gates.

### Ticker-independent execution

- Source adapters normalize identifiers, fiscal calendars, currencies, units, and US-GAAP/IFRS
  taxonomy aliases into shared fact roles; finance rules never branch on a ticker symbol.
- Applicability is explicit per fact and driver. A non-inventory business can approve DIO as not
  applicable; missing data cannot silently become a sector constant.
- A structurally unsuitable or under-sourced ticker returns a blocking reason and model-change
  request instead of a fabricated industrial-company valuation.
- Batch execution uses bounded concurrency, per-provider rate limits, idempotent checkpoints, and
  per-ticker isolation. One failed name does not abort or disappear from the batch summary.

## Phase 1 — Bridge Reconciliation Tracer (shadow-only until Phase 3)

### Task 1.1: Freeze the cash double-count as a failing test

**Files:** `tests/test_valuation_input_assembler.py`, `tests/test_bridge_reconciliation.py` (create)

1. Assert that for a fixture with `total_debt=125,432`, `cash=32,105`, `revenue=318,273`, the sum
   of equity-bridge effects credits cash exactly once.
2. Assert the current assembler fails that check. Record the expected `-93,327m`.
3. Do not fix yet.

### Task 1.2: Build the claim ledger over the bridge

**Files:** create `src/stage_02_valuation/claim_ledger.py`; test `tests/test_bridge_reconciliation.py`

1. Define `ClaimedLine(reported_line, component, sign, value, source_ref)` and
   `ClaimLedger.reconcile() -> ReconciliationResult` with `double_claimed`, `unclaimed`,
   `untied_components`, and `tolerance`.
2. Pure functions only: no DB, no network, no LLM.
3. Tests for exactly-once violation, tie-out failure, tolerance boundary, and a clean ledger.

### Task 1.3: Emit the ledger from the assembler and fail closed

**Files:** `src/stage_02_valuation/input_assembler.py`, `src/contracts/assumption_register.py`

1. Have `build_valuation_inputs` construct the claim ledger alongside the drivers.
2. Apply the PM's split convention: operating cash buffer to `net_debt`, excess cash to
   `non_operating_assets`, leases to `lease_liabilities`, debt ex-leases to `net_debt`.
3. Fail closed on an unreconciled bridge, with the offending lines named.
4. Expose the ledger on the valuation result so the PM and the React surface can read it.
5. Task 1.1's test must now pass, and MSFT equity must fall by exactly the excess-cash figure.

**Finance boundary:** the operating cash buffer is currently `2% of revenue`, a constant with no
recorded provenance. Surface the current value and its effect as a *range* to the PM; do not
silently keep or change it.

### Task 1.4: Retire `blocked_override_fields`

**Files:** `src/stage_03_judgment/accounting_recast_agent.py`,
`src/stage_04_pipeline/accounting_discovery_ledger.py`, `scripts/manual/run_accounting_discovery.py`

1. Replace the hand-maintained blocklist with a reconciliation check against the claim ledger.
2. The existing guard regressions must keep passing: the $85bn lease override and the $111.955bn
   `non_operating_assets` proposal must both still be rejected — now by invariant 1, not by name.
3. Delete the blocklist only once both are covered by reconciliation.

### Task 1.5: Reclassification proposals

**Files:** `src/stage_03_judgment/accounting_recast_agent.py`,
`src/stage_04_pipeline/accounting_discovery_ledger.py`

1. Add the `reclassify` response shape; keep `driver_proposals` for genuinely forward-looking
   drivers, which have no reported line to claim.
2. Derive the proposed component value from the ledger rather than trusting the model's arithmetic.
3. Reject a reclassification that double-claims, naming the incumbent claimant.

### Task 1.6: Validate across tickers

Run the bridge reconciliation over every ticker with an available source snapshot. Record a
result or structured blocker for every requested symbol. Do not fix individual tickers by hand —
a systematic failure is a resolver, taxonomy, or applicability defect.

## Phase 2 — Statement Ingestion (prerequisite for Phase 3)

Working capital and cash flow cannot be reconciled until they exist in the system.

### Task 2.1: Persist complete statements from XBRL and CIQ

**Files:** `src/stage_00_data/xbrl_evidence.py`, `db/schema.py`, `db/loader.py`

1. Persist every presented consolidated income-statement, balance-sheet, and cash-flow line, not a
   curated concept shortlist.
2. Store stable fact ID, source, statement, concept and label, period semantics, fiscal calendar,
   filing vintage/accession, unit, currency, scale, context, dimensions, presentation hierarchy,
   source locator, and ingestion fingerprint.
3. Preserve statement hierarchy and dimensional facts; do not collapse dimensioned facts into
   undimensioned totals.
4. Select up to five annual periods and construct LTM from compatible current/prior YTD facts.
5. Make ingestion additive and idempotent so the same source payload produces the same fact set.

### Task 2.2: Reconcile CIQ against XBRL

**Files:** create `src/stage_00_data/source_reconciliation.py`

1. For every overlapping quantity, compare CIQ against XBRL at the same period.
2. A material disagreement becomes a PM queue item naming both values and both sources.
3. **Regression:** a CIQ D&A of `0` against a non-zero XBRL D&A must be caught here. This is the
   check that would have prevented the 18% IV understatement.
4. Validate balance-sheet identity, the cash-flow-to-cash bridge, and available source calculation
   rollups before the statement set can become decision-grade.

## Phase 3 — Operating Reconciliation

### Task 3.1: Tie working capital to the balance sheet

1. DSO/DIO/DPO-derived AR, inventory, and AP must tie to reported balances within tolerance.
2. A drift beyond tolerance means the ratio is stale or mis-parsed; fail closed.

### Task 3.2: Tie capex and D&A to the cash flow statement

1. `capex_pct_*` and `da_pct_*` must tie to reported capex and D&A over revenue.
2. Judgment-layer *forward* proposals for these drivers remain free; only the historical starting
   point must tie.

### Task 3.3: Make every clamp auditable

1. Each of the 36 `_bounded()` sites records whether it clamped, the raw value, and the bound hit.
2. A clamp that fires on a reconciled input is a finding, not a silent correction.
3. Surface clamp events in the valuation result and the PM review surface.

## Phase 4 — Judgment-Authored Forecast Packs

### Task 4.1: Central assumption registry

Define one static registry for canonical names, aliases, units, deterministic versus judgment
ownership, applicability, preview/apply support, and structural checks. Remove scattered
allowlists and fix `terminal_growth` versus `revenue_growth_terminal`.

### Task 4.2: Focused primary and critic calls

Run four focused families after durable business, industry, and reconciled-history context:

1. revenue: near, mid, and terminal growth
2. profitability/tax: target COGS ratio, EBIT margin, and tax
3. reinvestment/working capital: capex, D&A, DSO, DIO, and DPO
4. terminal/capital/comps: terminal RONIC, dilution/buyback, and exit multiple

Each primary returns direct low/base/high values and evidence. The critic may flag unsupported
leaps, inconsistency, or reconciliation risk and the primary may revise once. Deterministic WACC
remains sourced and calculated; a challenge to its method becomes a model-change request.

### Task 4.3: Remove deterministic authorship

Delete canned deltas, story-score coefficient application, duplicate suppression, silent
clamping, and unsupported-field remapping from the official numeric path. Mechanical inputs may
power a clearly labeled provisional diagnostic but cannot satisfy the decision-grade gate.

## Phase 5 — Atomic PM Approval And Replay

1. Queue each coherent family as one editable low/base/high pack.
2. Preview all approved values through DCF, comps, and the common EV bridge.
3. Recheck evidence, statement, treatment, peer-set, prompt, contract, and model fingerprints
   before approval.
4. Persist explicit model-change requests. Accepting one records implementation intent; it never
   applies a numeric proxy.
5. Replay an approved run without provider access and assert identical assumptions, DCF, comps,
   bridge, and trust status.

## Phase 6 — Universe Validation And Cutover

1. Use MSFT only as the first red/green tracer.
2. Add materially different cached issuers covering different sectors, balance-sheet shapes,
   fiscal calendars, and taxonomy patterns.
3. Run every eligible universe ticker through the same batch contract and emit a complete manifest
   of decision-grade, provisional, and blocked results with reason codes.
4. Compare legacy/new statements, assumptions, bridge, DCF, comps, and per-share value. Every
   material delta must decompose to a source correction, bridge correction, approved treatment,
   or approved judgment.
5. Cut over only when there are no ticker-specific finance branches, no silent dropped names, and
   provider conformance plus replay suites pass. Remove the temporary comparator.

## Implementation Checkpoint — 2026-07-26

The common production seam now exists and serves Vision Decisions 1, 2, 10–16:

- accession-bound XBRL presentation/calculation evidence and CIQ three-statement manifests feed
  the authoritative statement service;
- statement, claim-ledger, operating-model, DCF/comps, and EV-to-equity bridge gates fail closed;
- four focused provider-neutral primary/critic families emit immutable run envelopes and atomic PM
  queue packs;
- exact four-family approvals compile a frozen case, replay without a provider, validate against
  the persisted snapshot and approval provenance, and persist immutably;
- the official runner disables ticker overrides, story arithmetic, and public peer fallbacks;
- the bounded batch runner accounts for duplicates, provider limits, timeouts, retries, and every
  requested identity;
- terminal `decision_grade`, `provisional`, and `blocked` records persist once per execution run and
  are readable at `GET /api/tickers/{ticker}/valuation/outcomes`.

The offline MSFT tracer now returns `blocked` before any provider call when authoritative statement
sources are absent. Its current isolated reason set is
`source_coverage_not_attested`, `balance_sheet_identity_missing`,
`cash_flow_to_cash_bridge_missing`, `insufficient_annual_history`,
`complete_presentation_history_missing`, and `ltm_not_ready`. This is the intended fail-closed
behavior, not a valuation result.

Phase 6 cutover is **not complete**. The local cache contains no complete filing presentation /
calculation linkbase bundle, the current MSFT CIQ workbook is not committed, and the valid CALM CIQ
workbook has no matching accession-bound XBRL presentation source. IBM, BAH, LYFT, and IESC likewise
remain explicitly blocked for source depth or source-contract reasons. A real cross-sector
decision-grade run therefore requires source refreshes, not ticker-specific assumptions or relaxed
gates.

## Exit Criteria

1. No reported balance can be credited to equity twice; the attempt fails closed with both
   claimants named.
2. The MSFT cash double-count is gone and the fix is covered by a regression test.
3. All four known bugs are rejected by reconciliation rather than by any named blocklist.
4. A judgment-layer proposal that double-claims is rejected before it becomes a queue item.
5. A CIQ-versus-XBRL disagreement produces a PM item instead of a silent winner.
6. Every clamp that fires is visible in the valuation artifact.
7. The PM Decision Queue is still the only mutation bridge and no LLM runs in the deterministic
   layer.
8. The complete consolidated statement history exists for every decision-grade ticker, with at
   least three annual periods and explicit LTM status.
9. Every applicable forward driver is directly agent-authored, critic-reviewed, evidence-linked,
   and PM-approved.
10. OpenRouter, direct OpenAI-compatible, and Codex fixture responses pass the same schema and
    failure tests.
11. Replaying a stored approved run is provider-free and byte-identical at the normalized
    assumption and deterministic valuation layers.
12. A universe batch accounts for every requested ticker and contains no symbol-specific valuation
    treatments.

## Deferred

- Automatic repair of an unreconciled ledger; Phase 1–3 report and fail closed, they do not guess.
- Retiring CIQ in favour of XBRL alone; Decision 9 governs that and it is not this plan's call.
- Formal segment rollup schedules; dimensional facts are persisted now, but consolidated
  statements are the first calculation view.
- New valuation methodologies beyond the mandatory DCF and comps. Structurally unsuitable names
  return a model-change request instead of being forced through an invalid model.

## Superseded Decisions

- The older judgment plan's instruction to retain `apply_story_driver_adjustments()` is
  superseded by the PM's 2026-07-26 instruction that agents make evidence-based adjustments rather
  than predetermined ones.
- The older assumption-register V1 restriction against judgment-authored values is complete
  historical context, not a current product constraint. Every mutation still requires PM
  approval.
