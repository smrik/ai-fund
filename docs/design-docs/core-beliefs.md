# Core Beliefs

These are the non-negotiable design principles for Alpha Pod.
Every architectural decision should be traceable to one of these.
When you disagree with a decision, check here first — if the belief is wrong, update it here and propagate.

---

## 1. LLM sets the assumptions; it never executes the math

The DCF model, WACC calculator, and screening filters produce numbers. Numbers must be reproducible.
An LLM must never be **inside the execution path** — no agent call during a computation, no prose
feeding a formula, no run that cannot be replayed from a fixed assumption set.

That is a constraint on *where code runs*, not a claim about who authors the assumptions.
Authoring them is exactly the LLM's job (Vision Decision 13): reasoning over filings, management
guidance, and history to set the forward-looking drivers, routed through the PM Decision Queue.

> **Read this carefully — it has been misread before.** "LLM is not in the valuation path" does
> **not** mean "the LLM only provides colour while sector constants set the model." A system whose
> forward-looking drivers all come from lookup tables satisfies the letter of this belief and
> defeats the purpose of the project.

**In practice:** `src/stage_02_valuation/` and `src/stage_02_valuation/templates/` have zero imports from `src/stage_03_judgment/`.
Agents produce typed dataclasses (QoEResult, CompsResult, etc.) and queue proposals that the PM
approves; the batch runner then re-runs deterministically over the approved set. The choice is
explicit, logged, and reversible.

**Why:** If the model changes, hallucinations creep in, or the API is unavailable, the valuation
pipeline must still run. The deterministic layer is the floor — but a floor is not the building.

---

## 2. The human is the PM, not a reviewer of agent output

The system is not a recommendation engine. It is a research acceleration engine.
The LLM agents do the analyst work — including reasoning to the key assumptions. The human
approves those assumptions, forms the variant perception, and makes the bet.

**In practice:** No agent produces a "buy" or "sell" signal. No agent sets position size.
Every pipeline ends at a human checkpoint before any capital is committed.

**Why:** Variant perception — knowing why the consensus is wrong — is irreducibly human.
An agent that says "buy" is not a PM, it's a liability.

---

## 3. Sector defaults are fallbacks, not primaries

The batch runner has `SECTOR_ASSUMPTIONS` for growth, margins, capex, and exit multiples.
These exist to prevent silent failures when yfinance data is missing.
They are not the intended source of assumptions.

The intended source is **reasoned judgment over evidence** (Vision Decision 13). A sector constant
is what the system uses when it has nothing better, and it should say so.

This applies to mechanical transforms too, not just literal sector lookups. `margin_target =
0.5 × margin_start + 0.5 × sector_default`, `capex_target = capex_start × 0.95`, and
`growth_mid = growth_near × sector_fade` are all sector defaults wearing arithmetic. A formula
that cannot express a fact about *this* company is a placeholder for missing judgment.

**In practice:** Every assumption in the output includes an `assumption_source` audit field.
When reviewing output, `source = "sector_default"` is a flag that the underlying data is missing —
not a guarantee that the assumption is appropriate.

Where a qualitative assessment does drive numbers (`story_drivers.py`), its influence is scaled by
provenance: a sector-derived profile is damped, because it scores every ticker in the sector
identically and therefore carries no company-specific information. Only a reasoned, ticker-specific
profile gets full authority. Amplifying an undifferentiated default is worse than ignoring it — it
produces sector momentum disguised as business-quality analysis.

**Why:** A 15% EBIT margin assumption applied uniformly to Industrials and SaaS is not an input —
it's noise. The system should make it visible when it's guessing.

> **Known violation as of 2026-07-24.** Every forward-looking `*_target` driver is currently a
> sector constant or a mechanical transform; a provenance audit of the shipped MSFT model found
> `llm_reasoned: 0`. The belief is right and the code does not yet honour it. See
> `docs/reviews/weekly-loop/2026-07-24-MSFT-valuation-credibility-review.md` §6.

---

## 4. What the agent can't see doesn't exist

Design decisions, architectural patterns, and constraints that live only in chat or in someone's head
are invisible to Codex and future Claude sessions. They will be violated.

**In practice:** Every significant design decision gets a doc. Architecture is in `docs/design-docs/architecture-overview.md`.
Principles are here. Plans are in `docs/exec-plans/`. When a decision is made in conversation,
it gets committed to the repo before the next agent task runs.

**Why:** The article that inspired this structure (OpenAI Harness Engineering, 2026) showed that
"repository-local, versioned artifacts are all it can see." This repo is the agent's entire world.

---

## 5. Boring technology over clever technology

The codebase should be easy for an agent to reason about. Technologies with stable APIs, good
training-set coverage, and composable primitives are preferred over novel or opaque ones.

**In practice:** yfinance, pandas, sqlite3, openpyxl, Anthropic SDK. Not ORMs, not async frameworks,
not bleeding-edge libraries with sparse documentation.

**Why:** An agent that can fully internalize a dependency can use it correctly without surprises.
Opaque behavior compounds into bugs that are hard to diagnose and fix.

---

## 6. Enforce constraints mechanically, allow autonomy inside them

Architectural boundaries (which modules can import which), audit fields, and output schemas
are enforced structurally — not by documentation asking nicely.

**In practice:** Import/architecture lints (`tests/test_architecture_boundaries.py`, CI-enforced),
typed dataclasses for all inter-layer interfaces, required fields that raise at construction if
missing.

**Why:** An agent will follow the path of least resistance. If the architecture can be violated
without failing a test, it will be violated eventually. Encode the rules in the code.

---

## 7. Technical debt is a high-interest loan — pay it continuously

Pattern drift in an agent-generated codebase compounds faster than in a human-written one
because the agent replicates whatever patterns already exist.

**In practice:** Weekly doc-gardening task. `docs/strategy/quality-score.md` is updated per sprint.
When a bad pattern is spotted, it gets fixed that day — not queued for a cleanup sprint.

**Why:** One bad pattern becomes 50 bad patterns inside a week if the agent sees it as "the way
this codebase does things." The cost of fixing 1 is trivially lower than fixing 50.

---

## 8. CIQ is the primary fundamentals source; yfinance is the fallback

Once CIQ is flowing, multi-year financials, estimate revisions, and peer lists come from CIQ.
yfinance provides TTM snapshots and is the fallback when CIQ data is absent or stale.

**In practice:** The batch runner checks the `ciq_fundamentals` table first for each ticker.
If the CIQ record is > 7 days old or missing, it falls back to yfinance with a quality flag.

**Why:** yfinance has TTM-only data and no peer lists. The quality of the valuation is directly
proportional to the quality of the input data.
