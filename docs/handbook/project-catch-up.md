# Alpha Pod — Project Catch-Up

> Status snapshot: 2026-07-26. This note was written after auditing `.agent/session-state.md`,
> the active valuation plan, Git history, and the current worktree. It is an orientation document,
> not a release claim.

## The short version

Alpha Pod is an AI-assisted fundamental long/short equity research pipeline. It combines filing and
Capital IQ evidence, deterministic valuation math, judgment agents, and a PM Decision Queue.

The recent work is a major architectural push toward a reconciled, judgment-authored valuation path:

```text
filings + CIQ
    -> complete statement/evidence ledger
    -> focused primary + critic judgment packs
    -> PM approval
    -> deterministic DCF + comps + bridge replay
    -> ticker terminal outcome
```

The important caveat is that this path is not cut over. MSFT is the tracer bullet, and its honest
isolated run is currently `blocked` because source coverage and statement reconciliation are not
complete. Do not treat the current valuation output as decision-grade yet.

## Current repository state

| Item | Current state |
| --- | --- |
| Branch | `codex/focused-accounting-evidence-repair` |
| `HEAD` | `be6b0c7` — `data: publish reproducible research state` |
| Latest committed work | 2026-07-11; most recent work is still in the working tree |
| Tracked files changed | 91, excluding the large LFS database from the count |
| Untracked paths | 125, including new source/tests, caches, generated artifacts, and `ssh-debug.txt` |
| Deleted path | `docs/plans/2026-05-06-assumption-register-contract.md` (replaced by the completed copy) |
| Database | `data/alpha_pod.db` is modified and has a Git LFS permission problem in this Windows checkout |

This is not a clean handoff or a reviewable single commit. Preserve the worktree and inspect the
new slices before staging or committing anything.

## What changed

### 1. Evidence and historical statements

- Added accession-specific XBRL presentation/calculation ingestion and source reconciliation.
- Added filing-presentation and section-inventory support so discovery can request exact evidence,
  rather than receiving broad snippets.
- Expanded CIQ ingestion and workbook parsing toward complete three-statement manifests.
- Added coverage gates that distinguish “parsed” from “complete enough to use.”
- Added statement-source refresh, operating reconciliation, and statement reconciliation services.
- Source lineage, filing anchors, period metadata, dimensions, and provider inputs are carried into
  downstream contracts.

Key areas:

- `src/stage_00_data/filing_presentation.py`
- `src/stage_00_data/source_reconciliation.py`
- `src/stage_00_data/filing_retrieval.py`
- `src/stage_00_data/xbrl_evidence.py`
- `src/stage_00_data/ciq_adapter.py`

### 2. Accounting discovery now reaches the PM queue

The old focused accounting flow could produce useful prose but did not reliably reach valuation
drivers. The new path is:

```text
complete filing inventory
    -> open-ended accounting questions
    -> exact-section retrieval
    -> focused recast
    -> typed findings
    -> duplicate/conflict handling
    -> PM queue candidates
```

Notable changes:

- `AccountingDiscoveryAgent` can ask company-specific questions instead of using only a fixed
  adjustment taxonomy.
- Every focused call receives business, industry, quantitative, and current-model context.
- `accounting_discovery_ledger.py` adapts recast output into the existing ledger and translator;
  it does not replace them.
- Every mapped finding is validated before merge. Invalid findings are preserved as rejected,
  not silently discarded.
- `driver_proposals` exposes the full proposable forward-driver surface, so the agent can propose
  evidence-grounded growth, margin, capex/D&A, tax, terminal, WACC, and share-count values.
- Bridge reclassifications identify reported lines and treatments; deterministic code derives the
  amount from the claim ledger instead of trusting an agent-authored bridge number.

Key areas:

- `src/stage_03_judgment/accounting_recast_agent.py`
- `src/stage_04_pipeline/accounting_discovery_ledger.py`
- `src/stage_04_pipeline/accounting_ledger.py`
- `src/stage_04_pipeline/accounting_validation.py`
- `src/stage_04_pipeline/pm_decision_queue.py`

### 3. Reconciled valuation foundation

The new valuation work is trying to make double-counting structurally impossible:

- New typed contracts cover analysis snapshots, judgment runs, driver families, model-change
  requests, ticker runs, valuation readiness, and assumption registries.
- A claim ledger records which reported balance-sheet lines are consumed by which EV-to-equity
  bridge component.
- Exactly-once and component tie-out checks can fail closed before a valuation reaches the PM.
- Operating reconciliation and statement reconciliation are being added as dependencies rather
  than hiding missing data behind clamps.
- Approved-case replay persists the frozen evidence/assumption context and replays deterministically
  without calling a provider.
- Provider bindings and the workup CLI/service provide one execution contract across supported
  judgment backends.
- Ticker batching isolates failures and stores terminal outcomes instead of dropping names.

Key areas:

- `src/stage_02_valuation/claim_ledger.py`
- `src/stage_02_valuation/approved_case_replay.py`
- `src/stage_02_valuation/operating_reconciliation.py`
- `src/stage_04_pipeline/ticker_valuation_execution.py`
- `src/stage_04_pipeline/ticker_batch.py`
- `src/stage_04_pipeline/ticker_terminal_store.py`
- `src/stage_04_pipeline/valuation_provider_bindings.py`
- `src/stage_04_pipeline/valuation_workup_service.py`
- `src/stage_04_pipeline/valuation_workup_cli.py`

### 4. Judgment/provider hardening

- Judgment calls now use provider-neutral structured envelopes with immutable request/context
  fingerprints, finite timeouts, validation, retry/repair limits, and provenance.
- Primary and critic driver-family packs are represented explicitly; conflicts remain visible and
  are not averaged.
- The PM Decision Queue is still the only path that can mutate approved assumptions/treatments.
- Story scores and canned numeric translator deltas are being removed from the authoritative
  valuation path.

Key areas:

- `src/stage_03_judgment/judgment_backends.py`
- `src/stage_03_judgment/judgment_gateway.py`
- `src/contracts/judgment_runs.py`
- `src/contracts/driver_families.py`
- `src/stage_04_pipeline/driver_family_workflow.py`
- `src/stage_04_pipeline/valuation_judgment_pipeline.py`

### 5. API and operator surface

The API now has a thin trigger for a reconciled valuation workup and a terminal-outcomes read path:

- `POST /api/tickers/{ticker}/valuation/run`
- `GET /api/tickers/{ticker}/valuation/outcomes`

The API remains transport-only; orchestration belongs in `src/stage_04_pipeline/`.

## What has been verified

The session handoff reports:

- 215 focused production-path tests green across ingestion, reconciliation, provider contracts,
  PM approvals, replay, batching, terminal storage, and API exposure.
- Ruff clean on the touched Python files.
- Strict MkDocs verification passed when the output was redirected away from the locked `site/`
  tree.
- Full offline run: **916 passed, 21 failed, 5 errors, 2 deselected**. Twenty failures are tied
  to permission-locked `.tmp-tests/`; the remaining assertion is a pre-existing source-reference
  ordering expectation in `test_evidence_packet_builders.py`.

Those results come from the other agent’s handoff log; this catch-up pass did not rerun the full
test suite. The current worktree is too dirty to infer that all slices compose cleanly.

## The critical blockers

### 1. Cash is still double-counted in the bridge

The active plan identifies a live bug:

```text
net_debt = total_debt - all cash
non_operating_assets += excess cash
```

For MSFT, that overstates equity by approximately **$25.74bn / $3.45 per share**. The required
split convention is:

```text
net_debt             = debt excluding leases - operating cash buffer
lease_liabilities    = separate claim
non_operating_assets = excess cash + investments
```

The claim ledger is intended to enforce this, but the production cutover is not complete. This is
the first finance-critical item to resolve.

### 2. The operating layer is under-sourced

The current CIQ snapshot has working-capital ratios but not the reported AR/inventory/AP balances,
and has capex/D&A scalars but not the supporting cash-flow lines. The model therefore cannot yet
reconcile NWC or cash flow. The plan calls for complete consolidated income-statement,
balance-sheet, and cash-flow history: five annual periods plus LTM, with three annual periods as
the minimum for `decision_grade`.

### 3. Ticker generality is not proven

- MSFT is the first tracer and is currently blocked on source coverage and statement readiness.
- CALM has a non-calendar CIQ workbook but no matching XBRL presentation source.
- IBM’s cache-only corpus was refused by the gate because one filing is a synthetic fixture and
  the real filings yield almost no raw numbered notes.
- BAH, LYFT, and IESC remain source-blocked in the handoff.

### 4. Interrupted slices need review

The stop log explicitly says the following are mid-handoff or not production-safe:

- `valuation_workup_service.py` had an identity-mismatch test failure in the last combined run.
- The Codex CLI backend hardening was interrupted after host-file/tool exposure was identified.
- Provider bindings, workup CLI, and the thin API trigger have focused tests but have not received
  independent review.

### 5. Finance semantics still block guessing

The live run produced zero-valued `capex_pct_target` and `ebit_margin_target` despite narrative
evidence that the values should not be zero. No PM-approved semantic bands exist yet for which
drivers may be zero or what their acceptable ranges mean. Do not solve this with a generic clamp.

## Recommended next order

1. Keep the branch/worktree frozen enough to review the interrupted slices and their focused tests.
2. Finish the exactly-once bridge and cash/lease convention on an isolated database; prove the
   MSFT bridge tie-out before exposing the result as decision-grade.
3. Refresh complete MSFT and CALM source bundles, then inspect a structurally different issuer
   before spending a live judgment budget on a broad universe run.
4. Independently review provider bindings, `valuation_workup_service.py`, the CLI, API trigger, and
   Codex isolation. Resolve the identity-mismatch test before wiring a UI or batch cutover.
5. Ask the PM to settle zero-value semantics and DCF/comps/per-share materiality thresholds.
6. Run a legacy-versus-new shadow comparator across eligible tickers, then cut over only after
   terminal outcomes are explicit for every requested ticker.

## Useful entry points

```powershell
# Inspect source completeness before classification
python scripts/manual/inspect_classification.py --ticker MSFT --stage 0

# Discovery only
python scripts/manual/run_accounting_discovery.py --ticker MSFT

# Discovery plus focused recasts and a dry-run ledger/queue translation
python scripts/manual/run_accounting_discovery.py --ticker MSFT --with-recast

# Add --persist-queue only when PM-approved persistence is intended

# Focused offline regression; avoid the locked pytest cache
python -m pytest tests/test_accounting_discovery_ledger.py -q -p no:cacheprovider
```

## Read these next

1. [Reconciled Statement Ledger plan](../plans/active/2026-07-25-reconciled-statement-ledger.md)
2. [Pipeline glass-box walkthrough](./pipeline-glass-box.md)
3. [Deterministic vs LLM boundary](../valuation/12_deterministic-vs-llm-boundary.md)
4. [Valuation methodology index](../valuation/index.md)
5. The session handoff lives at `.agent/session-state.md` in the repository root.

The single sentence to remember: **the project is moving from “agents can suggest valuation
changes” to “agents propose evidence-grounded treatments and drivers, while a reconciled,
provider-independent deterministic pipeline decides what can actually reach the PM.”**
