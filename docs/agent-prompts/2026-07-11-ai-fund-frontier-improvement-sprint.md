# Ultra-mode agent handoff: Alpha Pod frontier improvement sprint

This is the primary handoff prompt for a frontier coding agent with a day of high-capability, high-usage execution. The objective is not only to improve accounting evidence. The objective is to inspect the entire `ai-fund` repository, identify the highest-leverage weaknesses against the product vision, and implement as many safe, tested improvements as the available time allows.

The agent must leave behind working code, tests, documentation, reproducible commands, and an honest list of what remains. It must not produce a large speculative rewrite or claim that an unconnected helper is a finished feature.

## PowerShell command

Run this from the repository root on the device where the sprint will execute:

```powershell
$repo = (Resolve-Path .).Path
New-Item -ItemType Directory -Force output\agent-runs | Out-Null
codex exec `
  --cd $repo `
  --model gpt-5.6-sol `
  --config 'model_reasoning_effort="ultra"' `
  --sandbox workspace-write `
  --output-last-message output\agent-runs\2026-07-11-frontier-improvement-sprint-final.md `
  "Read docs/agent-prompts/2026-07-11-ai-fund-frontier-improvement-sprint.md and execute the sprint."
```

If this CLI does not expose `gpt-5.6-sol` or `ultra`, use the strongest available frontier model and reasoning setting, and record the actual setting in the final report. Do not silently fall back to a weak model while claiming an ultra run.

## Getting the repository on another device

Repository:

```text
https://github.com/smrik/ai-fund.git
```

The current reviewed implementation is on:

```text
codex/focused-accounting-evidence-repair
```

The remote `main` branch has not absorbed that branch because the repository requires a pull request and status checks. Clone the reviewed implementation, then create a separate sprint branch:

```powershell
git clone --branch codex/focused-accounting-evidence-repair --single-branch https://github.com/smrik/ai-fund.git
Set-Location ai-fund
git switch -c codex/frontier-improvement-sprint
git status --short --branch
```

If the repository is already cloned:

```powershell
git fetch origin codex/focused-accounting-evidence-repair
git switch --track origin/codex/focused-accounting-evidence-repair
git switch -c codex/frontier-improvement-sprint
```

Local `.env` secrets, SQLite databases, SEC/market caches, and generated `output/` artifacts are machine-local. Configure the new device from `.env.example` and the setup documentation; never copy secrets into Git or send them to a delegated worker.

## Project background

Alpha Pod is an AI-augmented fundamental long/short equity research system for a solo PM. The intended weekly loop is:

```text
market/company data -> deterministic screening and valuation
                    -> evidence packets and provenance
                    -> selective LLM judgment
                    -> PM Decision Queue
                    -> approved model changes, notes, and exports
```

The system has three hard layers:

1. **Data layer:** deterministic acquisition, normalization, filing retrieval, XBRL provenance, and caching.
2. **Computation layer:** deterministic screening, WACC, DCF, bridge math, and portfolio calculations.
3. **Judgment layer:** bounded LLM agents for narrative, accounting interpretation, qualitative risk, and PM questions.

LLM code must not directly mutate deterministic valuation inputs. Nothing trades automatically. The PM Decision Queue is the safety boundary.

The latest real MVP run on MSFT proved that the generic weekly path can execute end-to-end and export decision artifacts. It also exposed the central quality problem: the findings were operationally real but not consistently finance-deep. The repository has since added retrieval hardening, provenance-preserving XBRL facts, accounting packets, deterministic focus projection, and multi-finding semantic repair. Those additions are tested, but some are still seams rather than live guided-run integrations.

## What to read before changing anything

Read in this order and use the repository—not this prompt—as the final authority:

1. `AGENTS.md` — engineering rules, architecture boundaries, Git workflow, and handoff rules.
2. `.agent/session-state.md` — latest work, tests, blockers, current branch context, and next steps.
3. `docs/strategy/vision.md` — settled PM decisions; do not re-litigate them.
4. `docs/PLANS.md` — plan taxonomy and documentation rules.
5. `docs/plans/index.md` — active and historical plan map.
6. `docs/plans/active/2026-07-11-accounting-evidence-packs-focused-repair.md` — current accounting plan and remaining Tasks 4–9.
7. `docs/design-docs/architecture-overview.md` and `docs/design-docs/core-beliefs.md` — layer boundaries and design principles.
8. `docs/handbook/workflow-end-to-end.md` — actual operator workflow and evidence/XBRL behavior.
9. `docs/handbook/react-frontend-setup.md` and `docs/handbook/react-playwright-review-loop.md` if touching frontend/API/browser surfaces.
10. `src/`, `api/`, `db/`, `config/`, `tests/`, and the manual runners reached by the workflow.
11. This sprint prompt and `docs/agent-prompts/2026-07-11-accounting-evidence-ultra-handoff.md` for the accounting-specific appendix.

Do not assume that plan text describes reality. Confirm important claims by tracing imports/callers and running a focused test or smoke command.

## Plan and current status

### Already implemented or substantially implemented

- MVP MSFT weekly-loop run with deterministic valuation, EDGAR preparation, six generic judgment profiles, queue review, analyst prep, and exports.
- EDGAR retrieval hardening: section parsing, split-heading repair, section-diverse selection, topic filtering, source locators, and explicit coverage states.
- XBRL Slice A/B: normalized facts with filing/accession/period/context/dimension/quality provenance and additive persistence into four accounting packets.
- Four persisted accounting parent packets: QoE, EV/equity bridge, contingencies/taxes, and segments/disclosure.
- Eight accounting focus keys and deterministic agent-facing context projection.
- Zero-to-many accounting response envelope, stable finding IDs, whole-envelope schema retry, and item-level semantic repair preserving valid siblings.
- Offline focused tests are green; the known Windows `.pytest_cache` permission warning is non-blocking.

### Still open and high priority

The active accounting plan identifies these remaining slices:

- **Task 4:** connect the eight focus calls to the real accounting packet/guided-run dispatch; persist per-focus artifacts and latency/status metadata.
- **Task 5 integration:** ensure the repair seam is actually used by live structured agent calls, with original/repaired/rejected traces persisted.
- **Task 6:** translate distinct valid findings into dedicated PM Queue items; preserve duplicates and contradiction/conflict groups.
- **Task 7:** integrate the accounting pass into the guided workup and analyst-prep exports without changing the PM approval/apply boundary.
- **Task 8:** run and document a cache-first MSFT accounting comparison.
- **Task 9:** full offline/live verification and architectural safety checks.

The sprint is broader than accounting. Use these as the initial backlog, then add newly discovered high-value issues only when backed by repository evidence:

- deterministic valuation bridge consistency, WACC/source-lineage drift, stale or live-only dependencies inside deterministic assembly, and fallback behavior;
- market/EDGAR/CIQ cache reliability, data vintage consistency, missing-data states, and reproducible reruns;
- generic judgment-agent packet quality, observation-type correctness, numeric formatting, evidence anchoring, and response-schema robustness;
- stale preview fingerprints, approval/apply ordering, batching approved changes safely, queue deduplication, and operator friction;
- guided-run orchestration, failure recovery, timing instrumentation, artifact naming, and export completeness;
- API/React watchlist and queue surfaces, if they are in the actual critical path; use the documented browser review workflow and inspect screenshots/payloads, not only HTTP status;
- test coverage, offline determinism, import-time side effects, error messages, performance bottlenecks, docs drift, and agent legibility.

## Sprint operating protocol

### Phase 1: baseline and triage

Before editing:

```powershell
git status --short --branch
git log --oneline --decorate -12
python -m compileall src api db
python -m pytest -m "not live" -q
```

If the full offline suite is too slow or blocked by the Windows cache warning, run focused suites first and document the exact blocker. Do not hide failures by weakening tests.

Build a ranked table:

| Rank | Surface | Evidence of problem | User/PM impact | Smallest safe fix | Verification |
|---|---|---|---|---|---|

Prioritize issues that are high-impact, locally reproducible, and independently verifiable. Fixing a silent wrong result outranks polishing a low-traffic UI.

### Phase 2: parallel audit lanes

Use subagents or parallel read-only passes when available. Give each lane a disjoint question and file scope; do not let multiple workers edit the same files. The main agent must review all returned findings against the repository before acting.

1. **Data/evidence lane:** EDGAR, XBRL, CIQ, market caches, provenance, vintage handling, missing evidence, and packet quality.
2. **Valuation/computation lane:** DCF, WACC, bridge math, source lineage, deterministic fallbacks, and mutation boundaries.
3. **Judgment/harness lane:** agent prompts, profile packets, structured response contracts, repair loops, observation validation, cost/latency, and model routing.
4. **Queue/workflow lane:** ledger, duplicate/conflict semantics, PM approval/apply behavior, guided-run state transitions, output artifacts, and timing.
5. **Frontend/API/devex lane:** watchlist/queue surfaces, API contracts, browser review, testability, setup, and documentation drift.

Each lane must report exact files/functions, a minimal reproduction, and a proposed test. Do not accept vague “could be improved” suggestions.

### Phase 3: implementation loop

For each selected improvement:

1. State the invariant and the smallest vertical slice.
2. Add or update a regression test first when practical.
3. Implement with clear boundaries and explicit failure states.
4. Run focused tests immediately.
5. Review the diff for unrelated changes and silent behavior changes.
6. Update the canonical plan/docs when behavior or architecture changes.
7. Commit logical slices to `codex/frontier-improvement-sprint` if the work is cleanly verified. Do not push or merge without human direction.

Do not bundle a dozen speculative refactors into one commit. If an improvement is blocked by a finance-semantic decision, record the decision request and continue with independent engineering work.

## Deep verification checklist

### Data and evidence

- Every meaningful numeric claim has source, period, filing/accession vintage, unit, and locator metadata.
- XBRL dimensions and context are preserved; fuzzy concept matching cannot silently select a related concept.
- Current and comparative facts do not mix filing vintages without an explicit marker.
- Note retrieval distinguishes unavailable, not retrieved, searched-absent, and genuinely absent evidence.
- Cache-only behavior never constructs a network client or presents unavailable data as real.
- Accounting evidence includes note-driven balance-sheet/QoE candidates rather than generic company prose.

### Deterministic finance

- Reconcile revenue, EBIT, cash flow, net debt, equity bridge, shares, enterprise value, and implied value across producers/consumers.
- Check WACC inputs, source lineage, dates, units, signs, and fallback paths.
- Look for live network calls or mutable external state inside deterministic assembly.
- Confirm agents cannot mutate DCF, WACC, bridge, screening, or portfolio inputs.
- Add invariants where a mismatch can be detected mechanically.

### Judgment and agent harness

- Each agent sees the smallest relevant evidence context with explicit focus, period, status, and allowed drivers.
- Responses can contain zero-to-many independent findings.
- Schema failures retry at envelope level; semantic failures retry at item level.
- Repair requests contain original item, exact errors, rejection cause, allowed fields, and evidence context.
- Item 123-style driver mismatch is repaired rather than discarded.
- Numeric formatting, observation types, directions, materiality fields, and evidence anchors are validated before queue creation.
- Prompts remain stable and cache-friendly; updates are appended rather than mutating the core contract unnecessarily.

### Queue and weekly loop

- One distinct valid candidate becomes one auditable queue item.
- Duplicate findings retain provenance; contradictory findings become explicit conflict groups.
- No-adjustment and missing-evidence results remain visible without becoming accidental model mutations.
- Preview fingerprints, approve/apply ordering, and apply-at-end batching are safe and testable.
- The guided run records latency, model, status, packet IDs, repair attempts, queue IDs, and output paths.
- A real MSFT cache-first run is inspectable in JSON/Markdown/XLSX/export artifacts.

### API/UI and developer experience

- API responses match the actual persisted payloads and contracts.
- Browser checks inspect rendered screenshots and empty/error states, not only `200 OK`.
- CLI help, setup docs, environment examples, and active plans match behavior.
- Tests run offline by default and failures identify the relevant stage.

## Guardrails for an aggressive sprint

- Maximize verified improvements, not changed-line count.
- Prefer several small, reversible vertical slices over a rewrite.
- Never delete data or “clean up” another agent's artifacts without explicit authorization.
- Do not commit secrets, `.env`, local databases, raw caches, or generated output unless the repository explicitly tracks that artifact.
- Do not loosen a failing test merely to get green.
- Do not add finance semantics by guessing. Ask or leave an explicit PM checkpoint.
- If a high-value change needs external data, first implement an offline fixture and a cache-only path.
- Before claiming completion, run a final review agent or a separate read-only diff review and reconcile its findings.

## Sprint acceptance criteria

The sprint is successful when it leaves measurable improvement across the repository, not merely an audit report:

- at least one high-value end-to-end path is more integrated or reliable;
- every changed behavior has focused regression coverage;
- the accounting focus/repair work is either connected to the live guided path or has a precise blocker;
- deterministic valuation and mutation boundaries remain intact;
- the offline suite and relevant smoke tests pass;
- generated artifacts and docs explain what the next agent/PM should inspect;
- remaining gaps are ranked by impact and not hidden behind a generic “future work” list.

## Final report format

Write the final report to the path supplied by `--output-last-message` and summarize:

1. **Baseline:** branch, commit, tests, warnings, and runtime.
2. **Parallel audit findings:** only evidence-backed findings.
3. **Changes shipped:** file-level summary grouped by workstream and commit.
4. **Verification:** exact commands and results, including cache/live status.
5. **Finance-quality assessment:** what is now decision-useful and what remains weak.
6. **Integration assessment:** which paths are truly live versus test-only seams.
7. **Remaining blockers:** precise file/function, reproduction, and whether PM input or external data is required.
8. **Next sprint queue:** the top five concrete follow-up tasks.

Do not say “everything works” unless the relevant call path has been exercised end-to-end and the artifacts reconcile.
