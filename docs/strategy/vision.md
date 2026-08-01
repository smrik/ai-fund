# Alpha Pod Vision

| Field | Value |
| --- | --- |
| Status | Canonical vision — PM-authored decisions |
| Source | Structured PM interview, 2026-06-12; amended by the PM 2026-07-24 and 2026-07-25 (Decisions 13-16, [The Division Of Labor](#the-division-of-labor)) |
| Audience | Every coding agent session and the PM |
| Review | Quarterly, or when a decision below stops matching reality |

This is the destination document. It records the PM's actual decisions about what Alpha Pod becomes, in interview-resolved form. Agents must treat these as settled — do not re-litigate them in plans or sessions. If implementation reality contradicts a decision here, surface the conflict to the PM instead of quietly working around it.

[North Star And Agentic Development Strategy](./north-star-and-agentic-development.md) explains how development serves this vision; this page says what the vision *is*.

## The Destination (2-3 years)

Alpha Pod is the **analyst team for a one-person fund**: it does all junior-analyst, ops, and risk-support work for a concentrated fundamental long/short book, while the PM makes every investment decision. The system never trades on its own — not as a temporary safety measure, but as the permanent design.

A mature week looks like:

- **Daily, 30-60 minutes:** the PM reviews overnight output — event-triggered Evidence Packets, PM Decision Queue items, position and thesis flags — and clears the queue.
- **Weekly deep dive:** new idea investigations, full ticker workups, thesis reviews, assumption maintenance.
- **Unattended, in between:** filings, earnings, estimate revisions, and price moves on watchlist and portfolio names automatically trigger the relevant judgment agents. The PM arrives to finished evidence, never to a blank screen.

Everything that does not fit inside that time budget must run without the PM.

## Settled Decisions

| # | Decision | Choice | Consequence for development |
| --- | --- | --- | --- |
| 1 | End state | Analyst team copilot — system never makes investment decisions | PM Decision Queue is the permanent center of gravity; no autonomous-trading workstreams, ever |
| 2 | Operating cadence | Daily 30-60 min + weekly deep dive | Unattended reliability and a sharp morning review surface are hard requirements, not polish |
| 3 | PM's protected edge | Variant perception, high-level trade idea generation, and continuously improving the workflow itself | Idea sourcing stays human; catalyst handicapping and sizing *support* are fair game for heavy system assistance |
| 4 | The book | Concentrated L/S, 10-20 names, multi-month+ horizons (Tiger Cub style) | Deep per-name dossiers and thesis tracking over breadth; ranking engine feeds the funnel, doesn't run the book |
| 5 | Agent autonomy | Event-driven autonomous runs on watchlist/portfolio names only | Build event triggers (filings, earnings, revisions, price moves); agents do NOT autonomously source new names |
| 6 | Execution | IBKR monitoring + staged orders; the system never transmits | Read positions/P&L, monitor risk and thesis triggers, stage orders for PM review — order transmission is out of scope permanently |
| 7 | UI | Retire Streamlit now; React+FastAPI is the working surface; conversational interface is very long-term | Freeze `dashboard/` to bugfix-only with a deletion path; React investment limited to irreducibly visual surfaces (queue, watchlist, valuation, charts) |
| 8 | Feedback/calibration layer | Later — after real positions exist | Decision-outcome calibration waits for Phase D ground truth; keep cheap decision logging that the queue already does, build nothing more yet |
| 9 | Data backbone | CIQ now, proper API when it breaks | Don't pre-solve; revisit when CIQ access ends or manual refresh blocks event-driven autonomy (see Known Tensions) |
| 10 | Spec workflow | Interview-first, mandated | Non-trivial features start with the agent interviewing the PM until ambiguity is resolved, then a plan with goal/non-negotiables/acceptance criteria; the PM never writes specs cold |
| 11 | Mid-execution ambiguity | Split by domain | Finance semantics (thresholds, ranges, valuation logic, metric meaning) → stop and ask the PM, always. Engineering details → agent decides conservatively and logs the decision in the plan/PR |
| 12 | Next 6-12 months | The weekly loop runs for real | The PM uses the system every week on real tickers — screen → valuation → evidence → queue → decisions → exported notes — in under an hour per name with no manual data surgery. Feature work pauses until real-loop friction demands it |
| 13 | Who sets the key assumptions | **The judgment layer, reasoning over qualitative + quantitative evidence** | Forward-looking drivers are agent-derived from filings, management guidance, and history — not sector constants or mechanical transforms. Deterministic code marshals evidence and executes; it does not author the thesis. See [The Division Of Labor](#the-division-of-labor) |
| 14 | Analysis ordering | Business analysis → industry analysis → driver agents | Upstream context is durable and flows into every downstream agent, the way an analyst works. Driver agents never reason about a number without the business and industry read |
| 15 | Current valuation methods | DCF and comparable-company analysis are mandatory; other methods are deferred | Every current full workup produces both DCF and comps. Do not expand into other valuation methodologies until real usage shows the need |
| 16 | Accounting classification and treatment | Open-ended, evidence-based judgment | Start from the complete populated historical record, then retrieve evidence for the specific question. The judgment layer may propose any financially sound classification, historical recast, forecast implication, or model change. Existing driver fields are current implementation capability, not a ceiling on reasoning; every mutation still requires PM approval |

## The Division Of Labor

*Added 2026-07-24 after the PM found agents were building the wrong thing. This is the point of
the project, and it was previously implicit enough to be misread.*

Alpha Pod is **not a DCF template with a chat layer attached**. Anyone can build a spreadsheet
that mean-reverts a margin to a sector average. The product is that an LLM reasons over
qualitative *and* quantitative evidence to set the key assumptions, and those reasoned
assumptions drive everything downstream.

The correct split:

| Layer | Owns | Does not own |
| --- | --- | --- |
| Deterministic | Ingestion, reported-history extraction, computation, broad candidate discovery, marshalling the *relevant* evidence for a specific question, executing the model reproducibly | Deciding the analytical treatment of ambiguous history or what a forward-looking driver should be |
| Judgment (LLM) | Reasoning over filings, management guidance, competitive position, industry context, and history to classify ambiguous items, propose historical recasts or model changes, and set the key forward-looking assumptions | Writing to the model directly, or making the investment decision |
| PM | Approving, editing, or rejecting every proposed assumption; the variant perception; the bet | Authoring specs cold, or hand-tuning constants the system should derive |

**A specific task beats a general one.** "Given ten years of margin history, the segment mix,
what management said about operating leverage, and these comps — what does EBIT margin converge
to in year 10, and why?" is answerable and checkable. "Review this valuation" is not.

**Reported historical values are facts; their valuation treatment may be judgment.** Preserve the
reported baseline exactly, but do not confuse extraction with analysis. Classification,
normalization, capitalization, reclassification, and historical recasts can require judgment
over the notes and business economics. An approved recast can change the normalized historical
starting point and therefore the forecast. Every `*_target` driver is a thesis and should be
reasoned. A sector constant or a `start × 0.95` transform in a `*_target` slot is a placeholder
for missing judgment, not an answer — see [Core Belief 3](../design-docs/core-beliefs.md).

**Discovery is broad; judgment calls are focused.** Deterministic code should expose the full
populated history and rank it for review without using a fixed topic shortlist or materiality
threshold to decide what is eligible. It then gathers targeted quantitative and qualitative
evidence for one question. The focused contract makes reasoning inspectable; it does not limit
the treatment to fields the current model already supports. Unsupported but sound proposals
return an explicit model-change request to the PM Decision Queue.

**This does not weaken the architecture invariants.** The LLM still never executes inside the
computation layer and still cannot mutate the model outside the PM Decision Queue. It sets
assumptions *through* that bridge. Reproducibility is preserved because the model runs
deterministically from a fixed, approved assumption set — the question is only who authored the
set, and the answer is reasoning, not a lookup table.

## What Success Looks Like

The system is succeeding when, in order:

1. The PM actually runs the weekly loop on real tickers, every week (Decision 12)
2. A full ticker investigation fits in one PM-hour with zero manual data surgery
3. **The key forward-looking assumptions in a shipped model are agent-reasoned from evidence, with a named evidence basis — not sector constants (Decision 13)**
4. Event-driven runs mean the daily session starts with fresh evidence, not button-pressing
5. Real positions exist and are monitored against their theses daily
6. The calibration layer (post-positions) shows which agents, rules, and PM habits add value

Feature count, agent count, and data-source count are explicitly **not** success measures.

A useful diagnostic for #3: classify every assumption in a shipped model by provenance. If
`llm_reasoned` is zero, the system is a sector-default DCF with an advisory chat layer,
regardless of how many agents ran.

## Known Tensions (flagged, not resolved)

- **Event-driven autonomy vs manual CIQ refresh (Decisions 5 + 9).** Unattended agent runs need fresh data without the PM's workbook ritual. This will eventually force the paid-API question. Trigger to revisit: the first time an overnight run produces stale-data queue items or autonomy work blocks on refresh.
- **30-60 min daily sessions vs queue volume.** If event-driven runs generate more queue items than the daily budget can clear, the fix is better triage/ranking of queue items — not longer sessions and not auto-approval.

## Standing Rules For Agents

1. Read this document and the repo-root `AGENTS.md` before proposing any plan; new plans must state which settled decision(s) they serve.
2. Never propose work that contradicts a settled decision without explicitly naming the conflict and asking the PM.
3. Interview-first (Decision 10): for non-trivial work, interview the PM to resolve ambiguity before writing the plan.
4. Split-by-domain (Decision 11): finance questions block on the PM; engineering questions get a conservative decision plus a logged rationale.
5. The architecture invariants in [North Star And Agentic Development Strategy](./north-star-and-agentic-development.md) (LLM never *executing inside* the deterministic layer, queue as the only mutation bridge, evidence anchoring, contract boundaries) are non-negotiable.
6. Before hardcoding a constant for a forward-looking driver, or asking the PM to pick one, check whether the judgment layer can derive it (Decision 13). If it cannot, the deliverable is usually wiring that seam — evidence into the packet, field into the proposable set, translator rule to the queue — not choosing a number. Surface a *range* to the PM as a sanity band, not a menu to pick from.
