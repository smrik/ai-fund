# Ultra-mode agent handoff: accounting evidence pipeline

> For a repository-wide improvement sprint, use `docs/agent-prompts/2026-07-11-ai-fund-frontier-improvement-sprint.md`. This file is the accounting-specific deep-dive appendix.

This is a continuation prompt for a strong coding agent that will inspect and improve the Alpha Pod accounting-evidence pipeline. The repository is runnable and the deterministic accounting packet/focus/repair seams are tested, but the focused accounting path is not yet fully wired into the guided runner and PM queue.

## PowerShell command

Run this from any PowerShell session with the repository available locally:

```powershell
Set-Location C:\Projects\03-Finance\ai-fund  # change this path on another device
$repo = (Resolve-Path .).Path
codex exec `
  --cd $repo `
  --model gpt-5.6-sol `
  --config 'model_reasoning_effort="ultra"' `
  --sandbox workspace-write `
  "Read docs/agent-prompts/2026-07-11-accounting-evidence-ultra-handoff.md and follow its instructions exactly."
```

If the installed CLI rejects `gpt-5.6-sol` or `ultra`, keep the same prompt and use the strongest available model/reasoning setting; record the actual model and setting in the final report.

## Background

Alpha Pod is a solo-PM, public-equity long/short research pipeline. Its intended weekly loop is:

```text
data acquisition -> deterministic screening/valuation -> evidence packets
-> selective LLM judgment -> PM Decision Queue -> approved model changes/notes/exports
```

The hard architectural boundary is that deterministic code owns data normalization, valuation, screening, and portfolio math. LLM agents may interpret bounded evidence and draft questions or proposals, but they must not directly alter deterministic valuation state or trade.

The immediate product problem came from a real MSFT MVP run. The generic six-profile workflow ran end-to-end and produced queue items, but the accounting findings were not finance-deep enough: they relied too much on broad business snippets and did not consistently surface note-driven balance-sheet/QoE adjustments such as leases, SBC, contingencies, tax exposures, impairments, or other disclosed items. The working hypothesis is that the agent context and evidence retrieval were too broad/noisy, not that the accounting reasoning problem should be solved by unconstrained prompting.

The current implementation therefore adds:

- note-specific EDGAR retrieval with explicit coverage states;
- provenance-preserving SEC XBRL facts with accession, period, filing, context, dimensions, and source locators;
- four persisted accounting parent packets;
- eight narrower reasoning focuses;
- deterministic focus projection into bounded agent context;
- zero-to-many finding envelopes;
- semantic validation and repair that gives the agent the exact rejection cause;
- preservation of valid siblings when one finding fails.

The implementation is deliberately not declared fully complete. The next important work is wiring these tested seams into the actual guided runner, deterministic ledger/duplicate/conflict handling, PM queue translation, and a real MSFT focus smoke.

## Getting this exact version on another device

The GitHub repository is:

```text
https://github.com/smrik/ai-fund.git
```

The reviewed implementation is currently on the pushed branch:

```text
codex/focused-accounting-evidence-repair
```

The remote `main` branch has not yet absorbed it because GitHub requires a pull request and status checks. To clone the implementation directly on another device:

```powershell
git clone --branch codex/focused-accounting-evidence-repair --single-branch https://github.com/smrik/ai-fund.git
Set-Location ai-fund
git status --short --branch
```

Alternatively, if the repository is already cloned:

```powershell
git fetch origin codex/focused-accounting-evidence-repair
git switch --track origin/codex/focused-accounting-evidence-repair
```

The branch contains the implementation commits `2dad083` and `4a45acb`, plus this handoff prompt once it is published. Local `.env` secrets, SQLite databases, SEC/market caches, and generated `output/` artifacts are machine-local and are not a substitute for a clean checkout. On a new device, configure secrets from `.env.example`, install the project dependencies according to the repository setup docs, and start with offline tests before attempting live retrieval.

## Mission

Make the accounting-evidence loop genuinely useful for a solo public-equity PM. Inspect the repository, prove what works, then implement the smallest high-value vertical slice that connects the existing evidence-pack, focus, repair, ledger, queue, and guided-run surfaces without weakening deterministic valuation boundaries.

Do not assume that passing unit tests means the feature is integrated. Trace the runtime call graph from the guided ticker workup to persisted packets, agent inputs, response validation, repair, queue translation, and exported artifacts.

The target weekly loop is:

```text
real ticker -> deterministic valuation/model inputs
           -> note-specific EDGAR + structured XBRL evidence
           -> narrow accounting focus context
           -> zero-to-many independent findings
           -> item-level semantic repair when needed
           -> deterministic duplicate/conflict handling
           -> PM Decision Queue items with evidence + IV impact preview
           -> persisted/exported review artifacts
```

## Non-negotiable boundaries

1. Read `AGENTS.md`, `.agent/session-state.md`, the active plan, architecture docs, workflow docs, and current git status before editing.
2. Treat `docs/strategy/vision.md` and the active accounting plan as source-of-truth. Do not re-litigate settled PM decisions.
3. Keep LLM code out of deterministic valuation, screening, market-data normalization, and XBRL normalization. Agents may interpret evidence; they must not silently mutate valuation inputs.
4. Do not invent materiality thresholds, accounting-treatment conventions, or automatic adjustment rules. If finance semantics are unresolved, stop at an explicit PM decision checkpoint.
5. Preserve the full persisted accounting packet as an audit artifact. The agent receives a deterministic focus projection, not an arbitrary destructive truncation.
6. A focus response may contain zero, one, or multiple independent findings. Never merge separate SBC, restructuring, impairment, lease, tax, or segment findings merely to satisfy a one-finding schema.
7. A syntax/schema failure gets one whole-envelope retry. A semantic failure retries only the invalid finding and preserves valid siblings. Item 123-style driver mismatch is a repairable proposal-mapping error, not grounds to discard the underlying finding.
8. Do not use destructive git commands. Do not delete untracked databases, review artifacts, outputs, or another agent's changes. Do not commit, push, merge, or open a PR unless the human explicitly asks.
9. Prefer offline/cache-only verification first. Use live SEC or other network calls only when necessary, and record the exact command, data vintage, and fallback behavior.
10. Work task-by-task. After each meaningful slice, run its tests and provide a short checkpoint before expanding scope.

## Repository orientation

Read these in order, then inspect the implementation rather than relying on this prompt:

1. `AGENTS.md`
2. `.agent/session-state.md`
3. `docs/strategy/vision.md`
4. `docs/PLANS.md`
5. `docs/design-docs/architecture-overview.md`
6. `docs/handbook/workflow-end-to-end.md`
7. `docs/plans/active/2026-07-11-accounting-evidence-packs-focused-repair.md`
8. `src/contracts/accounting_evidence.py`
9. `src/stage_00_data/filing_retrieval.py`
10. `src/stage_00_data/xbrl_evidence.py`
11. `src/stage_04_pipeline/evidence_packets.py`
12. `src/stage_04_pipeline/accounting_focus.py`
13. `src/stage_04_pipeline/accounting_validation.py`
14. `src/stage_04_pipeline/accounting_evidence_runner.py`
15. `scripts/manual/run_guided_ticker_workup.py`
16. The queue/observation persistence and export modules reached by the guided runner

Also inspect the current branch and recent commits. The earlier implementation was committed as `2dad083` and the handoff metadata as `4a45acb`, but verify the actual checkout because the branch may have advanced.

## First phase: establish the real baseline

Before changing code:

1. Run `git status --short --branch` and preserve all unrelated work.
2. Identify the actual branch, commit, and whether the current checkout includes the focused accounting implementation.
3. Run the focused baseline tests:

   ```powershell
   python -m pytest tests/test_accounting_evidence_packs.py tests/test_accounting_focus.py tests/test_xbrl_evidence.py tests/test_evidence_packet_builders.py tests/test_filing_retrieval.py -q
   ```

4. Run `python -m compileall src`.
5. Inspect the guided runner's call graph and answer with file/line evidence:
   - Where are the four persisted accounting packets built?
   - Are the eight focus keys actually dispatched, or only defined?
   - Is `select_accounting_focus` called by the live guided path?
   - Is `run_focus_repair_cycle` called by the live guided path?
   - Where do valid findings become ledger entries and PM queue items?
   - Which output files contain the final accounting evidence and queue state?
6. Produce a ranked gap list with severity, evidence, and the smallest safe fix. Do not begin with a broad refactor.

## Deep checks to perform

### A. Evidence quality and finance usefulness

Inspect actual packet fixtures and, if available, the MSFT cache/live artifacts. Check:

- XBRL facts retain concept, taxonomy, unit, value, period, accession, filing date, form, context reference, dimensions, statement metadata, quality metadata, and accession-level locator.
- Current and comparative periods are not silently mixed across filing vintages.
- Segment dimensions survive selection and serialization.
- Note snippets are anchored to source refs and section/note keys.
- The evidence pack contains the disclosures needed for real accounting questions: revenue recognition, deferred revenue/contract assets, SBC, restructuring, impairments, leases, pensions, contingencies, taxes, debt, investments, minority interest, and segment economics.
- Missing retrieval is distinguished from searched-but-absent disclosure and from cache-only unavailability.
- The model can see reported facts and current valuation drivers together, but cannot write into deterministic valuation state.
- A proposed balance-sheet or QoE adjustment can cite the exact evidence that supports it; do not accept generic business prose as accounting evidence.

Flag gaps such as broad-note snippets without relevant anchors, stale/default bridge values, duplicate XBRL facts, incomplete current-period coverage, or packets that look rich numerically but lack explanatory notes.

### B. Focus projection

Review all eight focus definitions:

- `qoe_revenue`
- `qoe_opex_and_compensation`
- `qoe_nonrecurring`
- `qoe_cash_conversion`
- `bridge_cash_debt_investments`
- `bridge_leases_pensions_claims`
- `tax_contingencies`
- `segments_disclosure`

Verify:

- the parent topic is correct;
- relevant fact/concept and note-section matching is deterministic and explainable;
- selected facts are bounded and ranked by filing/period vintage;
- comparative periods are preserved where available;
- 10–25 facts, 2–5 snippets, and 1–3 driver fields are targets rather than reasons to fabricate data;
- empty, partial, unavailable, and missing-evidence states are explicit;
- the original persisted packet is never mutated;
- a focus cannot accidentally consume another parent topic's facts.

Add tests for any discovered failure before fixing it.

### C. Response and repair behavior

Exercise these cases with offline fixtures:

1. zero findings with complete evidence;
2. explicit missing-evidence response;
3. two independent valid findings, retained separately;
4. one valid sibling plus one invalid sibling;
5. invalid envelope shape followed by a successful whole-envelope repair;
6. item 123-style driver mismatch repaired by changing only `proposed_driver_field`;
7. invalid item remaining `rejected_after_repair` while the valid sibling survives;
8. unknown evidence anchor, missing reason, invalid status, and invalid valuation treatment;
9. duplicate findings and contradictory findings with clear provenance.

The repair request must return the original finding, exact validation errors, rejection cause, allowed drivers, and the relevant evidence context. A repair must not invent an anchor or silently downgrade a supported candidate to no-adjustment.

### D. Ledger and PM queue safety

Trace the missing or existing merger. If it is not implemented, add the smallest deterministic seam that:

- assigns stable finding/observation fingerprints from focus, line item, period, proposed driver, and evidence anchors;
- preserves duplicate provenance instead of silently dropping it;
- groups contradictory candidates into an explicit conflict group;
- allows each distinct valid candidate to remain a separate candidate;
- sends only valid, anchored candidates to the PM queue;
- carries proposed treatment, cash/tax/timing context, and an IV-impact preview without applying the adjustment;
- leaves `no_adjustment_identified`, `missing_evidence`, rejected, duplicate, and conflict outcomes auditable;
- never mutates deterministic valuation state before PM approval.

Do not decide whether a treatment is material or should be booked. Make the queue capable of asking the PM.

### E. Guided-run integration

Trace `scripts/manual/run_guided_ticker_workup.py` from CLI parsing through packet creation, agent calls, observation validation, queue persistence, review interaction, and exports. Determine whether the new accounting flow is:

- fully connected;
- connected only in a test seam;
- bypassed by the existing generic six-profile path; or
- partially connected with a silent fallback.

If it is not connected, implement a narrow integration behind an explicit flag or agent mode. Keep the existing path backward-compatible. Do not replace the entire guided runner.

## Required implementation order if gaps are confirmed

1. Fix or add deterministic tests for the observed gap.
2. Implement the narrowest contract/adapter seam.
3. Test the seam with offline fixtures.
4. Integrate one focus or one end-to-end path before expanding to all eight.
5. Run the MSFT cache-only smoke and inspect generated JSON/Markdown rather than trusting exit code alone.
6. Only then expand to the remaining focuses or queue merger.

For an MSFT smoke, prefer the existing local caches first. Record packet IDs, packet status, fact/snippet counts, focus key, finding counts, repair attempts, accepted/rejected/duplicate/conflict counts, queue IDs, and output paths.

## Acceptance criteria

Do not claim completion unless the evidence supports it:

- Baseline and regression tests are green, with warnings explained.
- The live call graph reaches the new accounting focus path rather than only importing its helpers.
- Every agent-facing finding is anchored to packet evidence and a focus key.
- Multiple findings survive independently; valid siblings survive invalid-item repair.
- Item 123's semantic driver mismatch receives the data and rejection cause and can be corrected on retry.
- Duplicate and conflict outcomes are explicit and auditable.
- No automatic accounting adjustment changes deterministic valuation before PM queue approval.
- MSFT cache-only smoke produces inspectable artifacts and the counts reconcile across packet, response, ledger, queue, and export layers.
- Any remaining blocker is named precisely with the file/function, reproduction command, and why it requires a PM finance decision or external data.

## Final report format

End with a compact evidence report:

1. **What was already working** — commands, counts, and artifact paths.
2. **What was missing** — exact call-graph or contract evidence.
3. **Changes made** — files and rationale, grouped by task.
4. **Finance-quality result** — which accounting questions are now answerable and which remain weak.
5. **Verification** — exact test/smoke/compile commands and results.
6. **Remaining risks/blockers** — especially missing notes, stale/default facts, treatment semantics, or ungated valuation mutations.
7. **Next smallest slice** — one concrete task, not a broad wishlist.

Do not report “works completely” unless the guided runner, focus dispatch, repair, ledger, queue, and exported artifacts have all been exercised together.
