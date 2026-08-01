# Judgment-Authored Drivers — Closing The Decision 13 Gap

| Field | Value |
| --- | --- |
| Status | Superseded 2026-07-26 by the reconciled, direct-driver plan |
| Created | 2026-07-25 |
| Serves | [Vision Decision 13](../../strategy/vision.md#the-division-of-labor) (judgment layer authors forward-looking assumptions), [Decision 14](../../strategy/vision.md#the-division-of-labor) (business → industry → driver ordering), Decision 12 (weekly loop for real) |
| Roadmap | Milestone 1, exit criterion "provenance audit shows agent-reasoned drivers, not `llm_reasoned: 0`" |

## Goal

Make `llm_reasoned > 0` **truthfully** — a shipped model whose qualitative business assessment
was authored by an agent reasoning over real filing evidence, with a named evidence basis, routed
through PM approval.

The emphasis is on *truthfully*. It is trivially easy to make this counter non-zero by having an
agent emit numbers from pretraining recall. That would be worse than the sector default it
replaces, because it looks reasoned and now carries full authority.

> **Supersession note:** Tasks 1–6 remain useful completed evidence-marshalling work. The plan's
> fixed score-to-coefficient mutation path and its decision to defer G4–G7 conflict with the PM's
> newer requirement for direct, evidence-grounded driver targets through the PM Decision Queue.
> Remaining retrieval and direct-driver work now belongs to
> `active/2026-07-25-reconciled-statement-ledger.md`.

## Gap Analysis (code-grounded, 2026-07-25)

### Already built — more than expected

| Component | State |
| --- | --- |
| `ThesisAgent.generate_story_profile()` | Exists. Prompt is good and explicitly says "be rigorous and company-specific — do not default to sector averages" |
| `write_story_driver_pending()` | Exists. Writes `config/story_drivers_pending.yaml` with `status: pending` |
| `resolve_story_driver_profile()` | Consumes approved entries → source `story_ticker_pending_approved` → authority 1.0 |
| `apply_story_driver_adjustments()` | Maps profile onto 8 drivers, clamped, lineage-stamped |
| `assumption_register.py` | Full impact metadata + PM review ranges for all reinvestment/margin/growth fields |
| Evidence packet → observation → translator → PM queue | Shipped and tested |
| `company_analysis` evidence packet | Collects **real 10-K context** with source refs and snippets |
| CLI | `batch_runner --ticker X --story-profile` |

The transmission belt from qualitative judgment to quantitative drivers is complete and working.

### G1 — CRITICAL: the story-profile agent runs on stub context

`batch_runner.py:1463`:

```python
filings = FilingsSummary(raw_summary="No filings context — direct story profile run")
earnings = EarningsSummary(raw_summary="No earnings context — direct story profile run")
```

The agent receives ticker, company name, and sector — and nothing else. It is being asked to
assess a company's moat, pricing power, and competitive durability **with no evidence**, so any
answer it gives is pretraining recall about a well-known company, not analysis of this filing.

This is the gap that matters. It also means the seam would fail hardest exactly where it is most
needed: a small or unfamiliar name, where recall is weak and there is no sector stereotype to
fall back on.

Meanwhile `_collect_company_analysis_inputs()` already assembles precisely the right evidence
(10-K business description, risk factors, MD&A, with `source_ref_id`s) for a different consumer.

### G2 — No evidence anchoring on the profile

`write_story_driver_pending()` persists scores plus a free-text `rationale`. No
`evidence_anchor_ids`, no source refs. This violates the standing invariant that every
observation carries an Evidence Anchor, and makes the profile unauditable: a PM reviewing
`moat_strength: 5` cannot see which disclosure supports it.

### G3 — `notes` not captured

`StoryDriverProfile.notes` (added 2026-07-24) is the open half of the schema — the part carrying
what the six scores cannot express. `generate_story_profile()` returns `rationale`; nothing maps
it into `notes`, so the free-text channel is built but unfed.

### G4 — Profiles run parallel and mutually blind (Decision 14 unmet)

`run_guided_ticker_workup.py:1339` runs profiles in a `ThreadPoolExecutor`;
`_run_profile_payload(deps, ticker, profile)` takes only a ticker and a profile name. There is no
`depends_on`, no ordering, and no mechanism for one profile's output to reach another. Business
and industry analysis therefore cannot serve as upstream context for anything.

### G5 — Second mutation bridge

The story profile reaches the model through `story_drivers_pending.yaml` (PM hand-edits
`status: approved`), not through the PM Decision Queue. That is a real PM gate, so it is not
unsafe — but it is a second review surface, and "the queue is the only bridge" is a stated
invariant. Noted; not resolved in this plan.

### G6 — No per-driver agents

Nothing proposes `ebit_margin_target`, `revenue_growth_mid`, or terminal reinvestment directly
with a driver-specific task. The story profile moves eight drivers *indirectly* through
coefficients. That is a good first lever but it is a blunt one: it cannot express "margin
converges to 38% because of segment mix", only "moat is 5".

### G7 — Queue-apply loop has never closed

`Applied queue items: 0` on every run to date; item 123 failed the preview-fingerprint guard.

## Scope Of This Plan

**In:** G1, G2, G3 — make the existing seam run on real evidence, anchored and auditable.

**Out (named, not silently dropped):** G4 (profile ordering/context passing), G5 (queue
consolidation), G6 (per-driver agents), G7 (fingerprint guard). Each needs its own plan. G1-G3
is the vertical slice that makes the rest worth building — without it, ordering context between
agents that reason from recall just moves recall around.

## Non-negotiables

- No LLM inside the deterministic computation layer; the profile is data, applied by
  `apply_story_driver_adjustments` under clamps.
- Nothing auto-applies. `status: pending` remains the default; the PM approves.
- Evidence-free output must be **detectable and refused**, not silently accepted. If the
  evidence bundle is empty, the run reports that rather than emitting a confident profile.
- Engineering decisions logged here; finance semantics (score→coefficient mapping) already
  PM-approved 2026-07-24.

## Tasks

1. **Deterministic evidence marshalling** — a function that builds story-profile context from the
   real `company_analysis` evidence packet (filing snippets + facts + source refs), returning both
   the agent-facing text and the anchor IDs. Deterministic; no LLM.
2. **Agent contract** — `generate_story_profile()` accepts that context, and returns `notes` plus
   the evidence anchors it used, in addition to the six scores.
3. **Persistence** — `write_story_driver_pending()` records `notes`, `evidence_anchor_ids`, and
   the source refs, so a PM can audit a score back to a disclosure.
4. **Refuse-on-no-evidence** — explicit status when the evidence bundle is empty; no profile is
   written.
5. **CLI wiring** — `--story-profile` uses real evidence instead of stubs.
6. **Tests** — evidence marshalling, notes round-trip, anchor persistence, refusal path.

## Status — 2026-07-25

Tasks 1-6 done. `859 passed / 29 failed` (baseline 29, same modules); +12 tests.

- `src/stage_04_pipeline/story_profile_context.py` — deterministic marshaller with a refusal path
  and relevance ranking.
- `ThesisAgent.generate_story_profile_from_evidence()` — reasons from anchored filing excerpts,
  returns `notes` + `evidence_basis` + `evidence_anchor_ids`. Refuses unusable context.
- `write_story_driver_pending()` — persists notes, evidence basis, anchors, source refs.
- `batch_runner --story-profile` — builds a real `company_analysis` packet instead of stubs.

Verified on MSFT cached filings: `status=ok`, 4 excerpts, 7 facts, 13 anchors, 4 accession-backed
source refs. No LLM dispatched (needs PM cost approval).

### G8 — NEW, and now the binding constraint: retrieval quality

The marshaller can only rank what the packet contains, and the `company_analysis` packet returns
generic front-of-10-K chunks. Measured on MSFT, packet order gave: 1 boilerplate block, 4 generic
business-description blocks, 1 about the sustainability report — **none discussing competitive
position**. Relevance ranking drops the worst (6 → 4 excerpts) but cannot add disclosure the
retrieval never fetched.

So the honest status of this slice: the agent moved from **no evidence** to **weak, generic
evidence**. That is a real improvement — the refusal path and anchoring are now structural, and
an evidence-free profile can no longer be written — but an agent handed those four excerpts would
still score MSFT's moat substantially from recall.

Additional observations: all excerpts came from a single filing despite four refs being
available, and several begin mid-word ("cribe risks", "eploying AI"), so chunk boundaries are not
sentence-aligned.

**Next task (largest remaining):** topic-targeted retrieval for the story profile — fetch Item 1A
competition risk factors and the competitive-position parts of Item 1, the way
`accounting_focus.py` already does for accounting topics. That work is the difference between
"agent-authored" being true on paper and true in substance. Until it lands, do not treat a
generated story profile as decision-grade, and do not read `llm_reasoned > 0` as vindication.

## Acceptance

- Running `--story-profile` on a ticker with cached filings produces a pending profile whose
  `evidence_anchor_ids` point at real accession-backed refs and whose `notes` are non-empty.
- Running it with no filing evidence available writes **no** profile and reports why.
- Approving the entry moves the eight drivers at authority 1.0 with lineage
  `story_ticker_pending_approved`.
- Full suite: no new failures against the 29-failure baseline.
