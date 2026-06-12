# North Star And Agentic Development Strategy

| Field | Value |
| --- | --- |
| Status | Canonical long-term guidance |
| Audience | The PM (Patrik) and every coding agent working in this repo |
| Horizon | 12-24 months |
| Last updated | 2026-06-12 |

This document answers two questions that no other doc owns:

1. What is Alpha Pod ultimately for, and how do we know it is working?
2. How should a solo PM direct LLM coding agents so the system keeps getting better instead of just bigger?

It sits above the roadmap dashboard. The roadmap says what to build next; this says how to decide what deserves building at all. The destination itself — the PM's settled decisions about what Alpha Pod becomes — lives in [Vision](./vision.md); this document must not contradict it.

## The North Star

Alpha Pod exists to let one PM run a Tiger Cub-style fundamental long/short book with the research throughput of a 15-30 person team. The system is working when it changes real investment decisions, not when it ships features.

The single metric that matters:

> **PM decisions per week that were materially faster or better because of the system, with an auditable trail showing why.**

Every proposed feature, agent, data source, and refactor should be testable against one question: *does this move a real ticker decision, or does it decorate the pipeline?* If the answer is "it might be useful someday," it goes to `docs/plans/future/` and stays there until a real research session demands it.

## The Operating Loop Is The Product

The deliverable is not the codebase. It is this weekly loop running on real capital:

1. **Screen** — universe refresh surfaces ~50 candidates
2. **Value** — batch DCF ranks them; assumption register flags fragile inputs
3. **Investigate** — judgment agents build Evidence Packets; translator creates proposals
4. **Decide** — PM works the Decision Queue: approve, edit, reject, defer
5. **Act** — position changes, scenario overlays, thesis updates
6. **Review** — what did the system get right, wrong, or miss?

Steps 1-4 are largely built. Step 5 is partially manual. Step 6 barely exists; by PM decision it is deliberately deferred until real positions provide ground truth (Phase D) — but it remains on the map, because a system that proposes assumption changes and never learns whether approved proposals were good is a junior analyst who never gets performance reviews.

## Architecture Invariants (Defend These)

These rules already exist and have proven their worth. Agents must treat them as non-negotiable; the PM should reject any plan that bends them:

| Invariant | Why it survives |
| --- | --- |
| LLM code never touches the deterministic computation layer | The entire trust model rests on this; valuations must be reproducible |
| The PM Decision Queue is the only bridge from judgment to model mutation | One auditable choke point instead of scattered overrides |
| Every observation needs an Evidence Anchor | Kills hallucinated inputs at the contract boundary |
| Translator rules are deterministic and testable | Numbers come from code, not prose |
| Contract Boundary validation (Pydantic) at every module/surface crossing | This is what lets LLM-written code be accepted without line-by-line review |
| One canonical home per concept; docs updated in the same change | The doc system *is* the senior engineer onboarding every new agent session |

## How Agentic Development Works Here

The PM's scarce resource is finance judgment and attention, not code review capacity. The development model must reflect that:

### The PM's job in development

- Answer **interview-first spec sessions** (Vision Decision 10): agents extract the goal, acceptance criteria, and sanity checks by interviewing the PM, then write the plan with the `/goals` prompt pattern — the PM approves rather than authors specs cold
- Answer **finance-domain questions immediately when agents block on them** (Vision Decision 11): thresholds, ranges, valuation semantics are PM-only calls; engineering details are not
- Review **behavior, not diffs**: run the manual smoke, look at the exported pack, check whether a valuation moved sensibly
- Own the **finance correctness layer**: translator rule magnitudes, accepted ranges, materiality thresholds, sector defaults
- Enforce **plan hygiene**: one active plan per workstream, stale plans archived, no second tracker

### The agents' job

- Implement against the active plan, task-by-task, with targeted tests per task
- Keep `CONTEXT.md` domain language exact — it is the shared vocabulary that prevents agents from re-inventing concepts
- Update docs in the same change when behavior changes
- Leave `.agent/session-state.md` accurate at handoff

### What makes LLM code trustworthy without reading it

The verification stack, in order of importance:

1. **Architecture boundary tests** (`test_architecture_boundaries.py`) — the layer rule enforced by CI, not convention
2. **Contract tests** — Pydantic models validated at every boundary
3. **Golden valuation regressions** — fixed-input DCF/WACC fixtures whose outputs must not drift without an explicit, PM-acknowledged change (build these out; this is the finance equivalent of snapshot tests)
4. **Agent evals** — fixture-based tests per judgment agent: given this filing excerpt, the observation set must include X and must not include invented Y
5. **Offline-first full suite** — currently ~730 tests; protect the offline property and keep runtime under a budget (target: <5 min for the default gate, full suite nightly)

Items 3 and 4 are the underdeveloped rungs. Invest there before adding new agents.

## Long-Term Phases

### Phase A — Consolidate (now, weeks)

The repo has accumulated parallel surfaces and unfinished merges faster than it has retired them. Before new capability:

- Merge or close `codex/mvp` and the other long-lived branches; get `main` to be the truth again
- Archive stale entries in `docs/plans/active/` (several date from March; the rule is they move out when shipped or abandoned)
- **Retire Streamlit** (settled — Vision Decision 7). Freeze `dashboard/` to bugfix-only with a deletion path; React+FastAPI is the one working surface, limited to irreducibly visual needs (queue review, watchlist, valuation tables, charts)
- Fix the environment drift (`rtk python` resolving the wrong interpreter, ruff missing from the env) — agent sessions burn time rediscovering this

### Phase B — Make the loop real (1-3 months)

- Run the full weekly operating loop on real tickers, every week, and log friction
- Harden the Agentic Handoff per the active plan: no synthetic evidence, visible agent failures, delta/target preview-approve parity
- Expand Agentic Handoff Profiles to cover all judgment agents through the *same* packet/observation/translator/queue mechanics — no per-agent bespoke paths
- Success bar: a full ticker investigation (screen hit → evidence → queue → approved assumptions → updated valuation → exported note) in under one PM hour, with zero manual data surgery

### Phase C — Event-driven autonomy (3-9 months)

Make the daily 30-60 minute session real: the system works overnight so the PM reviews instead of triggers.

- Event triggers on watchlist/portfolio names: filings, earnings, estimate revisions, material price moves → relevant agent profiles run unattended
- Failure visibility: an overnight run that breaks must surface loudly in the morning view, never silently produce nothing
- Queue triage/ranking so event volume fits the daily review budget
- Watch the data tension: unattended runs on manually refreshed CIQ data will eventually force the paid-API decision (Vision, Known Tensions)

### Phase D — Positions, monitoring, and the feedback loop (9-18 months, gated)

- IBKR read-only first: live positions and P&L feeding daily risk and thesis-trigger monitoring
- Staged orders for PM review in IBKR; the system never transmits (Vision Decision 6)
- Risk monitoring (limit breaches, thesis-invalidation alerts) ships before any order staging
- **Then** build the track-record/calibration layer (Vision Decision 8): queue decisions, approved assumption changes, and theses linked to price/fundamental outcomes; calibration reports on which agents, translator rules, and PM habits add value. Real positions provide the ground truth that makes calibration meaningful — and this remains the long-run differentiator no vendor can replicate

### Phase E — Continuous: evaluate the machine itself

- Backtest the alpha-relevant signals (revision momentum, regime weights, factor tilts) against what naive baselines would have done
- Annual strategy review doc: which subsystems earned their complexity; delete the ones that did not. **Deletion is a first-class roadmap outcome.**

## Anti-Goals

Agents and plans must not drift toward these:

- **No multi-user product.** No auth beyond minimal, no tenancy, no compliance scaffolding. Solo operator, own capital.
- **No LLM creep into the deterministic layer.** Not even "just this one helper."
- **No unbounded data-source expansion.** A new source must name the decision it improves before integration starts.
- **No second planning system.** `docs/plans/index.md` is the registry; GitHub issues link to it.
- **No rewrite-first proposals.** Adapters over rewrites (the PM Decision Queue Adapter pattern is the template).
- **No feature work during a broken-main state.** Consolidation outranks novelty.

## How To Use This Document

- New plans in `docs/plans/active/` should state which phase they advance and which north-star behavior they improve
- When two plans compete for attention, the one closer to the weekly operating loop wins
- Revisit this document quarterly; if reality and this doc disagree, update whichever is wrong — in the same change
