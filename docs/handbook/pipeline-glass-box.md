# Pipeline Glass-Box Walkthrough

Run the backend pipeline one stage at a time and inspect the artifact passed to the next stage. Every command here was executed and verified on 2026-06-12 (MSFT, offline/cache flags). UI surfaces are intentionally out of scope.

Use `C:\Users\patri\miniconda3\envs\ai-fund\python.exe` (shown as `python` below) until `rtk python` resolution is fixed.

## The Chain And Its Handoff Artifacts

```text
Stage 1 screen ──> config/universe.csv
Stage 2 batch  ──> data/alpha_pod.db: batch_valuations_latest, valuations
                   data/valuations/latest.csv
[CIQ refresh]  ──> data/alpha_pod.db: CIQ snapshot/long-form/comps tables
Ticker flow    ──> evidence_packets ─> observations ─> translator
                   ─> pm_decision_queue_items (+ pending_assumption_changes link)
PM approve     ──> approved_assumption_entries
Next valuation ──> input_assembler.build_valuation_inputs() reads approved entries
Exports        ──> output/ticker_flows/, output/analyst_prep/, data/exports/
```

## Step 1 — Universe Screen

```powershell
python -m src.stage_01_screening.stage1_filter
```

- **Consumes:** seed listing universe + yfinance (cached in `data/cache/yfinance_info.json`)
- **Produces:** `config/universe.csv`
- **Inspect:** `Get-Content config/universe.csv -TotalCount 5` and check the file date. As of 2026-06-12 it was dated **2026-03-06** — rerun before a real session; this step is network-dependent.

## Step 2 — Deterministic Valuation

Single ticker (print-only — see gotcha):

```powershell
python -m src.stage_02_valuation.batch_runner --ticker MSFT
```

Batch (the persisting path):

```powershell
python -m src.stage_02_valuation.batch_runner --top 50
```

- **Consumes:** `config/universe.csv` (batch), yfinance market/financial snapshots, CIQ tables when present, sector defaults
- **Produces (batch only):** `batch_valuations_latest` (replace), `valuations` (history upsert), `data/valuations/latest.csv`
- **Gotcha (verified):** `--ticker` prints the full valuation row but persists nothing. The canonical watchlist row only updates via batch.
- **Inspect the row contract:** the printed JSON includes assumption values with `_source` lineage fields, WACC decomposition, bear/base/bull IVs, `tv_pct_of_ev`, reverse-DCF implied growth, and `context_scenario_policy_json` (regime-aware scenario weights with the official fixed policy alongside).
- **Inspect the DB:**

```powershell
python -c "import sqlite3;c=sqlite3.connect('data/alpha_pod.db');print(c.execute('select ticker, snapshot_date, wacc from batch_valuations_latest limit 5').fetchall())"
```

## Step 3 — Optional CIQ Refresh

Host-Windows Excel path; see [workflow-end-to-end.md](./workflow-end-to-end.md#optional-ciq-workbook-refresh-path). After a manual workbook refresh, ingest intentionally with `--ingest-ciq-template` on the ticker flow. CIQ rows beat yfinance in the input assembler's source priority.

## Step 4 — Evidence → Observations → Translator → Queue (the glass box)

```powershell
python scripts/manual/run_ticker_valuation_flow.py --ticker MSFT --agent-mode heuristic --isolated-db --market-cache-only --edgar-cache-only
```

- **Consumes:** DB valuation state, market cache, EDGAR filing cache, CIQ comps
- **Produces:** `output/ticker_flows/MSFT-<ts>.json` + `.md`, and (because of `--isolated-db`) a copied SQLite DB under `output/ticker_flows/_isolated_db/` holding the new Evidence Packets and PM Queue items
- **Flags:** `--isolated-db` keeps rehearsals out of the live queue; drop it only when you intend real review state. `--agent-mode heuristic` uses deterministic stub observations (workflow checks, not insights). Drop `--edgar-cache-only` to allow live SEC fetches.

The JSON artifact is the handoff bundle. Top-level keys worth reading in order:

| Key | What it shows |
| --- | --- |
| `deterministic` | valuation summary/dcf/comps/assumption payloads the agents saw |
| `profile_runs` | per-profile status; `blocked` + `insufficient_real_evidence` means fail-closed on missing sources |
| `evidence_packets` | facts vs observations per packet kind, with anchors |
| `queue_items` | advisory findings and assumption change packs, three confidence fields |
| `previews` | resolved proposal values and status transition `pending → previewed` |
| `data_freshness` | cache ages — check `edgar_filing_cache.filing_count` first |

**Verified 2026-06-12:** with an empty EDGAR cache, 4 of 6 profiles (`earnings_update`, `company_analysis`, `industry_analysis`, `risk_review`) blocked correctly; `comps_analysis` and `valuation_review` produced one observation and one queue item each.

**Inspect the canonical queue store** (point at the isolated DB from the run output):

```powershell
python -c "import sqlite3;c=sqlite3.connect('output/ticker_flows/_isolated_db/<run>.db');print(c.execute('select item_id, item_type, title, status, agent_confidence, translator_confidence from pm_decision_queue_items order by item_id desc limit 5').fetchall())"
python -c "import sqlite3;c=sqlite3.connect('output/ticker_flows/_isolated_db/<run>.db');print(c.execute('select id, ticker, assumption_name, proposed_value, status, approval_ref from pending_assumption_changes').fetchall())"
```

## Step 5 — PM Decisions And The Apply Loop

Decisions go through `src/stage_04_pipeline/pm_decision_queue.py` (`preview_pm_decision_queue_item`, `approve_pm_decision_queue_item`, `apply_pm_decision_queue_item`), exposed via the FastAPI layer. On approve+apply:

1. The proposal's delta/target is resolved to an absolute value (preview and approval use the same resolver)
2. A `pending_assumption_changes` row moves to `approved` with an `approval_ref`
3. The value lands in `approved_assumption_entries`
4. The next deterministic run reads it: `input_assembler.build_valuation_inputs()` → `get_approved_assumption_overrides(ticker)` (`src/stage_02_valuation/input_assembler.py:354`)

**Inspect the audit trail:** `valuation_override_audit` and `assumption_register_audit` tables.

## Step 6 — Analyst Prep Pack And Exports

```powershell
python scripts/manual/run_analyst_prep_pack.py --ticker MSFT --agent-mode heuristic --isolated-db --export-xlsx --skip-agent-runs --market-cache-only --edgar-cache-only
```

- **Produces:** `output/analyst_prep/MSFT/<ts>.json|.md` and, with `--export-xlsx`, a review workbook under `data/exports/generated/ticker/MSFT/`
- This is a read-only aggregation of everything above — it proposes nothing and mutates nothing.

## Known Gaps (verified 2026-06-12)

| Gap | Effect | Owner fix |
| --- | --- | --- |
| `config/universe.csv` stale (2026-03-06) | Batch ranks a 3-month-old universe | Rerun Stage 1 in each weekly session (runbook) |
| Single-ticker valuation not persisted | Deep-dive output is ephemeral; watchlist row stays stale | Decide: batch-refresh the name, or add an explicit promote step |
| No operator command to prefetch EDGAR filings | Empty cache → 4/6 profiles fail closed offline; acquisition only happens implicitly in live runs | Add a small prefetch CLI or a runbook step that runs one live (non-cache-only) flow first |
| No transcript source for `earnings_update` | Earnings evidence limited to EDGAR releases | Data-source decision for the PM (Vision Decision 9 territory) |
| Packet `source_quality` serializes as `None` in the flow JSON | Export shows less than the DB knows | Small export-contract fix |
| Pending queue items have no aging surface | DUOL QoE proposal sat pending since 2026-06-08 unnoticed | M3 morning digest owns this; until then, check `pending_assumption_changes` in sessions |

---

## Classification And Treatment (added 2026-07-25)

Everything above walks the six *generic* profiles. None of them is accounting, and classification
— deciding how a reported number should be treated for valuation — runs on a different path with
its own failure modes.

Classification errors do not raise. They produce a plausible number. Two were found this week by
pairing CIQ figures against the note that governs them:

- D&A parsed as `0`, then floored to 0.5% of revenue by a clamp. Base IV understated ~18%.
- Lease liabilities counted twice — once inside CIQ's `debt`, once as a separate claim. ~$7/share.

Both were invisible in every existing artifact.

### The inspector

```bash
python scripts/manual/inspect_classification.py --ticker MSFT
```

Six stages. Stages 0/1/4/5 are read-only (`mode=ro`); stages 2/3 persist an `evidence_packets`
row and are opt-in behind `--with-packet`. Use `--stage N` for one stage.

| Stage | Question it answers | Look for |
| --- | --- | --- |
| 0 evidence | Did CIQ parse, and is the filing corpus complete? | filing inventory; current-parser coverage; `FAILED`; raw numbered notes versus topic aliases |
| 1 discovery | Which CIQ lines might require classification, and is exact note evidence available? | `NOTE`/`MISS`; page counts; adjustment-language signals |
| 2 packet | What did the packet collect? | fact_role mix; snippet sections |
| 3 focus | What does one topic hand the agent? | selected vs dropped; coverage notes |
| 4 bridge | Where does each EV→equity claim come from? | `NO <-- no range/flag`; double-count warnings |
| 5 model | What is trusted, what is overridden? | `model_trust_state`; active approved overrides |

Stage 4 is the one that surfaces bridge classification errors on sight.

To exercise the connected selector → validator → ledger → queue path without an LLM call, use
the latest cached accounting packet:

```bash
python scripts/manual/run_accounting_trial.py --ticker MSFT
python scripts/manual/run_accounting_trial.py --ticker MSFT --persist
```

The first command is a dry run. `--persist` writes the evidence-linked advisory to the PM
Decision Queue but never changes valuation inputs. The built-in judgment is deliberately a
small lease-source reconciliation smoke case; production treatment reasoning remains an
injectable judgment callable and is not constrained to leases.

To run the open-ended two-pass trial, first use discovery only:

```bash
python scripts/manual/run_accounting_discovery.py --ticker MSFT
```

Then run one narrow recast call per discovered question:

```bash
python scripts/manual/run_accounting_discovery.py --ticker MSFT --with-recast
```

This reads the cached company, industry, accounting, and complete filing-section inventory;
the LLM chooses the questions and exact sections; deterministic code retrieves the requested
chunks. Every focused recast call receives business, industry, quantitative, and
current-model/source-lineage context. Results are written under `output/accounting_discovery/`.

With `--with-recast` the run also builds the accounting ledger and translates it into PM Decision
Queue items, and prints entry/queue counts. It is still a dry run: nothing is written to the queue
unless you add `--persist-queue`, and no treatment is ever applied.

To replay a saved artifact through the adapter without any LLM call:

```bash
python -c "import json;from src.stage_04_pipeline.accounting_discovery_ledger import build_discovery_accounting_ledger as b;a=json.load(open('output/accounting_discovery/MSFT-20260725T155924Z.json'));r=b(ticker=a['ticker'],focused_analyses=a['focused_analyses'],blocked_override_fields={'lease_liabilities'},evidence_packet_id=214);print(len(r.ledger.entries),len(r.queue_items))"
```

### Where each thing lives

| Question | File | Symbol |
| --- | --- | --- |
| Did CIQ parse correctly? | `ciq/workbook_parser.py` | `_series`, `PARSER_VERSION` |
| Which notes can be extracted? | `src/stage_00_data/filing_retrieval.py` | `_extract_numbered_note_sections`, `_extract_sections_for_filing`, `_NOTE_TOPIC_PATTERNS` |
| Which chunks were chosen? | same | `_select_profile_chunks`, `retrieval_summary` |
| Which filing versions count as current? | `scripts/manual/inspect_classification.py` | `stage0_evidence`, `SECTION_PARSER_VERSION` |
| What lets the LLM choose company-specific accounting questions? | `src/stage_03_judgment/accounting_recast_agent.py` | `AccountingDiscoveryAgent.discover` |
| How do those questions retrieve exact filing sections? | `src/stage_00_data/filing_retrieval.py` | `get_discovery_filing_context` |
| What can the open-ended recast agent propose? | `src/stage_03_judgment/accounting_recast_agent.py` | `AccountingRecastAgent.analyze`, `model_change_proposals` |
| Which populated lines are available for classification? | `src/stage_04_pipeline/ciq_note_matching.py` | `find_classification_candidates` |
| What does one topic hand the agent? | `src/stage_04_pipeline/accounting_focus.py` | `select_accounting_focus` |
| Is a finding valid? | `src/stage_04_pipeline/accounting_validation.py` | `validate_accounting_finding` |
| What connects focus, judgment, validation, ledger, and queue? | `src/stage_04_pipeline/accounting_evidence_runner.py` | `run_accounting_evidence_trial` |
| What connects *discovery* questions to the ledger and queue? | `src/stage_04_pipeline/accounting_discovery_ledger.py` | `run_discovery_accounting_pass`, `recast_to_findings` |
| Is the filing corpus complete enough to classify? | `src/stage_00_data/filing_retrieval.py` | `require_accounting_corpus_coverage` |
| How does a finding become a proposal? | `src/stage_04_pipeline/accounting_ledger.py` | `translate_accounting_ledger_to_queue_items` |
| Where does an approved treatment and rationale persist? | `db/loader.py`, `src/stage_04_pipeline/treatment_register.py` | `insert_treatment_decision`, `assess_treatment_revalidation` |
| Where does a claim value come from? | `src/stage_02_valuation/input_assembler.py:651-796` | `_pick` + `source_lineage` |
| How is equity value computed? | `src/stage_02_valuation/professional_dcf.py:119-128` | `_claims_total` |
| Where do approvals persist? | `db/loader.py:1264-1300` | `approved_assumption_entries` (`active=1`) |

### Trap points

All confirmed by reading the code, not inferred.

1. **`_pick` is first-non-None-wins.** A stale CIQ value silently outranks fresher XBRL. The
   lineage string is the only way to tell which tier won.
2. **Overrides bypass every clamp.** `_apply` is a raw `setattr` (`input_assembler.py:337-341`),
   while normal assembly bounds each claim to `0..2x revenue`.
3. **The DB register beats the YAML.** `approved_assumption_entries` is applied last
   (`input_assembler.py:363`). The inline comment at `:349` claiming ticker overrides win is
   wrong.
4. **Raw note numbers are source identity, not accounting meaning.** `note_014` may be a
   different topic at another company or filing. Topic aliases improve ranking, but the agent
   must reason from the heading and disclosure text.
5. **`parser_version` gates re-ingest.** The ingest `run_key` is `f"{file_hash}:{parser_version}"`,
   so changing parser behaviour without bumping the version leaves every already-ingested
   workbook serving stale values forever.
6. **Numeric overrides still flatten treatment at model execution.**
   `get_approved_assumption_overrides` returns `{name: float}`. The separate
   `treatment_decisions` register now preserves the approved classification, evidence, rationale,
   supersession, and corpus hash, but queue approval is not yet wired to create that treatment
   row or apply a structural model change automatically.
7. **The generic retrieval profile is a fallback, not exhaustive judgment.** The two-pass
   discovery runner is the analytical path when coverage matters: the LLM sees every heading,
   requests exact source sections and search terms, and then receives focused evidence.
8. **A plausible agent override can still duplicate a deterministic claim.** The recast boundary
   accepts `blocked_override_fields`; CIQ lease-inclusive debt blocks a standalone
   `lease_liabilities` override and clears the corresponding proposed driver field. The
   discovery→ledger adapter applies the same guard independently, so a stale or hand-edited
   artifact still cannot produce a lease assumption pack.
9. **`normalized_ebit` is not a proposable driver.** It appears in the recast agent's override
   vocabulary but not in `AGENT_PROPOSABLE_ASSUMPTION_FIELDS`. An EBIT normalization is therefore a
   `model_change_required` advisory; it must never be remapped onto `ebit_margin_start` or
   `ebit_margin_target` to make it fit. To propose a margin, the agent uses `driver_proposals`
   with its own evidence and value — that is a different claim from normalizing history.
11. **A reclassification-only recast changes nothing in the DCF.** Balance-sheet reclassifications
    and EV-bridge overrides move the equity bridge, not the forecast. `driver_proposals` is the
    only path from accounting evidence to a forward-looking driver, and it was added on
    2026-07-25 — runs and artifacts from before that date cannot contain one.
12. **"Parsed" is not "complete".** `require_accounting_corpus_coverage` fails closed both when a
    required 10-K/10-Q is unparsed *and* when a parsed filing yields zero raw numbered notes. IBM
    had four filings that parsed to 1–5 sections with no notes at all; a presence-only check called
    that corpus complete while discovery would have received an empty inventory.
10. **`model_change_proposals` is currently also used for no-change confirmations.** In the MSFT
    run several "proposals" say to keep a treatment unchanged. Read the proposal text before
    treating a model-change advisory as a requested change.

### Inspect the stores directly

```bash
python -c "import sqlite3;c=sqlite3.connect('data/alpha_pod.db');print(c.execute('select assumption_name,value,source_ref from approved_assumption_entries where ticker=\"MSFT\" and active=1').fetchall())"
```

```bash
python -c "import sqlite3;c=sqlite3.connect('data/alpha_pod.db');print(c.execute('select id,assumption_name,status,proposed_value from pending_assumption_changes where ticker=\"MSFT\"').fetchall())"
```

### Known state (2026-07-25)

`sections_v6` rebuilt the cached MSFT corpus from complete documents: four 10-Ks and four 10-Qs,
217 current sections, 3,747 chunks, and 16–19 raw numbered notes per filing. Stage 0 reports all
12 cached filings but correctly treats the four 8-Ks as supplemental rather than accounting-note
coverage. It fails closed before packet/focus trials if any required 10-K or 10-Q is missing from
the current parser version.

Cache-only packet 214 retained eight annual/quarterly filing snippets, including raw numbered
notes that are not on a fixed treatment list. The two-pass runner then exposed 181 inventory
entries to a live MSFT discovery call: 141 raw numbered notes plus 40 semantic aliases. Six
company-specific questions requested exact sections and produced six narrow recast analyses
covering AI/datacenter capital intensity, segment mix, RPO conversion, contingencies, debt
structure, and SBC/share-count treatment.

The trial also demonstrated why deterministic guards remain necessary. One focused call proposed
an $85.126bn standalone lease override even though CIQ debt already includes leases. The
source-lineage guard cleared the override and proposed driver while retaining the disclosure,
classification, and PM notes. The guarded artifact is
`output/accounting_discovery/MSFT-20260725T155924Z-guarded.json`.

The two-pass trial is now connected to the canonical ledger and PM Queue translator through
`accounting_discovery_ledger.py`. Each recast item becomes its own finding tagged with the
discovery `question_id`, so six analyses stay six analyses; contradictions surface as conflict
groups instead of being resolved silently; explicit no-adjustment conclusions stay in the ledger
and out of the mutation queue; and treatments the current model cannot express become
`model_change_required` advisories rather than being remapped onto a nearby driver.

Replaying the unguarded live artifact produces 28 ledger entries and 18 advisory queue items with
**zero** assumption change packs — the adapter re-applies the lease source-lineage guard itself
rather than trusting the agent to have done it. See the plan's
[Discovery-To-Ledger Adapter](../plans/active/2026-07-11-accounting-evidence-packs-focused-repair.md#discovery-to-ledger-adapter-added-2026-07-25)
section for the full mapping table and the open items.

PM approval still does not write the treatment register, and structural model-change requests
still require implementation after approval.

### Debug the corpus before debugging the agent

1. Run `python scripts/manual/inspect_classification.py --ticker MSFT --stage 0`. Do not continue
   if accounting coverage is below the required filing count or any source says `FAILED`.
2. Run `python scripts/manual/inspect_classification.py --ticker MSFT --stage 2 --profile accounting_ev_equity_bridge`.
   This writes one packet. Inspect the snippet section keys: raw
   `note_NNN` sections should be eligible alongside broad notes and MD&A.
3. If a filing or note is missing, start in `filing_retrieval.py`; if a fact is missing, start in
   `evidence_packets.py`; if the answer is financially wrong despite correct evidence, inspect
   the assembled prompt and parsed result in `accounting_recast_agent.py`.
4. Before accepting a bridge proposal, inspect `source_lineage` in `input_assembler.py`. A
   plausible agent answer can still double count a claim already embedded in CIQ debt.
