# MSFT Valuation Credibility Review — 2026-07-24

**Trigger:** the 2026-07-11 guided workup reported base IV $225.33 against a $385.10 price
(−41.5% upside) while the comps cross-check said $496.73 and the 55-analyst consensus target
said $559.93. A 2x divergence between two valuation methods on the same company is a model
defect signal, not an investment signal. This review separates what was broken from what is
a methodology choice the PM has to settle.

Split follows AGENTS.md Decision 11: wiring/unit defects get fixed with a regression test;
finance semantics block on the PM.

---

## 1. Engineering defect — FIXED

### CIQ workbook parser silently zeroed D&A on every ticker

`ciq_valuation_snapshot.da_mm` was `0.0` and `da_pct_avg_3yr` was `0.0` for MSFT, while the
same workbook's `historical_financials` showed D&A at 5.2–7.8% of revenue every year since FY16.

**Root cause.** Real CIQ exports carry the label `Depreciation & Amort.` twice on the
`Financial Statements` sheet: the cash-flow line with the real value, and a zero-filled
placeholder. Both rows produce identical `(metric_key, period_date, column_index)` keys, so
they collided in the `_series()` dedupe in `ciq/workbook_parser.py`. The dedupe kept whichever
sorted first and it kept the zero.

The zero then hit the clamp in `input_assembler.py:583`:

```python
da_start = _bounded(da_raw, 0.005, 0.20, defaults["da_pct"])
```

which converted it into a plausible-looking **0.5% of revenue**. That is why this survived
multiple full-ticker runs and a PM review — it never looked like a null, it looked like a
small number.

**Consequence.** The DCF subtracted capex at 18.1% of revenue while adding back depreciation
at 0.5%. On $318B of revenue that understated FCFF by roughly $23B in year one, compounding
across the 10-year forecast and into terminal value.

**Blast radius.** Not MSFT-specific. The same zero/non-zero collision affects, across all four
committed workbooks:

| Ticker | Metrics silently zeroed |
| --- | --- |
| MSFT | `da`, `stock_based_compensation`, `amort_of_goodwill_and_intangibles` |
| IBM | + `gain_loss_on_sale_of_invest`, `minority_int_in_earnings` |
| BAH | `amort_of_goodwill_and_intangibles`, `stock_based_compensation`, `gain_loss_on_sale_of_invest`, `minority_int_in_earnings` |
| CALM | `da`, and the same cash-flow addback set |

**Fix.** `_series()` now prefers the row carrying a value when duplicates collide on
`(period, column)`. `PARSER_VERSION` bumped `ibm_standard_v2` → `ibm_standard_v3`.

The version bump is **load-bearing, not cosmetic**: `run_key` is
`f"{file_hash}:{parser_version}"`, so an unchanged workbook is skipped on re-ingest. Without
the bump the parser fix is inert against already-ingested data — verified directly
(`processed=0 skipped=3` before the bump, `processed=3 skipped=0` after).

**Regression test.** `tests/test_ciq_workbook_parser.py::test_valuation_snapshot_prefers_real_row_over_zero_placeholder_duplicate`
injects a zero-filled duplicate D&A row and asserts the real value survives.

### Verified end to end

| Hop | Before | After |
| --- | --- | --- |
| Parser output | `da_mm = 0.0` | `da_mm = 30,300` |
| DB snapshot `da_pct_avg_3yr` | `0.0` | `0.0640` |
| Assembled `da_pct_start` | `0.005` (clamp floor) | `0.0640` |
| `source_lineage.da_pct_start` | `ciq` | `ciq` (unchanged — value now real) |

0.0640 matches the FY23–25 historical average of 6.4%, independently computed.

### Valuation impact (controlled A/B)

Same code, same environment, same WACC (9.71%); the only difference is whether the DB was
re-ingested with the fixed parser:

| | base IV | upside vs $385.10 |
| --- | --- | --- |
| Before (D&A 0.5%) | $253.18 | −33.7% |
| After (D&A 6.4%) | **$299.09** | **−21.6%** |

**+$45.91/share, +18.1%.**

> Note: the $225.33 in the 2026-07-11 artifact is not the right "before" number — that run
> used WACC 10.44% from live market data. The A/B above holds WACC constant so the delta is
> attributable to the D&A fix alone.

---

## 2. Finance methodology — PM DECISION REQUIRED

These are not bugs. They are valuation-logic choices currently baked into the deterministic
layer, and each materially moves IV. Per Decision 11 I have quantified but **not changed** them.

### 2a. Terminal capex and D&A never converge — RESOLVED ARCHITECTURALLY, see §5

In the terminal year the model assumes capex of **16.7% of revenue** against D&A of
**5.9% of revenue**, held apart in perpetuity. Both fade *downward* together
(`da_target = da_start * 0.95`, same for capex), so the gap never closes.

That is economically incoherent in a steady state: sustaining 16.7% reinvestment forever
while depreciating 5.9% implies an asset base compounding to infinity. Standard practice is
for terminal D&A to converge toward terminal capex (net of the growth-capex wedge implied by
terminal growth).

Sized, holding everything else at the corrected base:

| Terminal assumption | base IV | upside |
| --- | --- | --- |
| Current (no convergence) | $263.78 | −31.5% |
| D&A → 60% of capex | $298.94 | −22.4% |
| D&A → 80% of capex | $317.01 | −17.7% |
| D&A → 100% of capex | $335.08 | −13.0% |

**PM answer (2026-07-24):** *"this should be determined by the llm in the pipeline... that's the
entire point of it. the llm should receive the info and the management guidance and 10-Ks and
decide this."*

Correct, and it exposed a structural gap rather than a missing constant — see §5. The ratios
above stay useful as the expected range for sanity-checking whatever the agent proposes, but
the number is not mine or the PM's to hardcode.

### 2b. EBIT margin mean-reverts 44% → 33% — see §6; the seam is now widened but unfed

`input_assembler.py:551` sets `margin_target = 0.5 * margin_start + 0.5 * sector_default`.
For MSFT that fades a 44.0% operating margin to 33.2% over the forecast, purely because the
Technology sector default is lower.

**PM question:** should a wide-moat compounder with `moat_strength = 4` and
`pricing_power = 4` (already in its story profile) be forced halfway to the sector mean? The
story profile is computed but does not currently damp this reversion.

### 2c. Inventory days go 5 → 26 for a software company

`dio_start = 5.0` (MSFT actual) fades to `dio_target = 26.0` via the 70% sector / 30% company
NWC blend. This books a working-capital drain that has no operational basis for a business
with effectively no inventory. `nwc_driver_quality_flag` is already `True` on this run.

**PM question:** should the sector NWC blend be suppressed when the company's own driver is
this far from the sector, or is the blend intentional?

### 2d. Beta peer set includes non-comparables

Unlevered peer beta is **1.30** against MSFT's own raw beta of **1.13**, because the peer set
is `ORCL, GOOGL, NVDA, CRM, AMZN, SNOW, S`. NVDA, SNOW and SentinelOne are materially
higher-beta than MSFT.

This is *not* the Hamada bug it first looks like — the model correctly takes a peer-median
unlevered beta and relevers to MSFT's capital structure, which legitimately can exceed the
company's own beta. The question is peer selection, not math.

**PM question:** should the comps peer set be shared between the beta calculation and the
trading-comps calculation, or should beta use a tighter mega-cap set?

---

## 3. Residual — still unexplained

Even with the D&A fix and full terminal convergence, the DCF tops out near $335 while:

- trading comps imply **$496.73**
- 55-analyst consensus target is **$559.93**
- market price is **$385.10**

Items 2b–2d plausibly account for part of this, but the DCF-vs-comps spread has not been
reconciled and should not be treated as an investment signal until it is. `tv_pct_of_ev` is
73.3% with `tv_high_flag = True`, so the terminal assumptions dominate the answer.

**Recommendation:** do not act on MSFT upside/downside from this model until 2a is settled.
The direction of every open item points the same way (IV too low), so the current −21.6%
reading is a floor, not an estimate.

---

## 4. Operational note

Any parser-semantics change must bump `PARSER_VERSION`, or already-ingested workbooks keep
serving stale values forever. Worth treating as a checklist item on `ciq/workbook_parser.py`.

Separately: `IBM_Standard.xlsx` and `CALM_Standard.xlsx` parse to identical `da_mm = 105.814`
and identical `capex_pct_avg_3yr`. That looks like one workbook is a stale copy of the other.
Not investigated — flagged only.

---

## 5. Reinvestment is now a judgment-layer decision

Item 2a was originally written as "pick a convergence ratio." The PM rejected that framing:
the ratio depends on where a company is in its build-out cycle, what management has guided to,
and the asset lives in its depreciation policy. That is judgment work, and the pipeline exists
to route judgment through evidence.

Investigating the ask surfaced the actual defect: **the judgment layer could not see or act on
reinvestment at all.**

- `AGENT_PROPOSABLE_ASSUMPTION_FIELDS` listed 17 assumptions. None were `capex_pct_*` or
  `da_pct_*`. The entire reinvestment side of the DCF was outside the agent's vocabulary.
- The `valuation_review` evidence packet carried five drivers — growth, margin, WACC, exit
  multiple. Capex and D&A were absent, so an agent could not have reasoned about them even
  if it were allowed to.
- Nothing in the packet stated the terminal capex-vs-D&A relationship, so the incoherence was
  invisible rather than merely unaddressed.

Notably the *deterministic* layer was already ready: `assumption_register.py` has full impact
metadata and PM review ranges for all four fields under `scope: "reinvestment"`. Only the
agent-facing bridge was missing.

### What changed

1. **Vocabulary** — `capex_pct_start/target` and `da_pct_start/target` added to
   `AGENT_PROPOSABLE_ASSUMPTION_FIELDS`; `capex_pct_target` and `da_pct_target` added to the
   `valuation_review` profile.
2. **Evidence** — the `valuation_review` packet now carries the four reinvestment drivers plus
   `revenue_growth_terminal`, and two deterministic derived facts that state the problem
   directly:
   - `terminal_reinvestment_gap_pct` — capex minus D&A, in percentage points of revenue
   - `terminal_da_to_capex_ratio` — the ratio the agent is being asked to judge

   For MSFT these read **10.82pp** and **0.352**. The deterministic layer describes the gap;
   it does not decide what the ratio should be.
3. **Mandate** — new `terminal_reinvestment_incoherence` observation type, and prompt guidance
   directing the agent to ground its call in management capex guidance, stated build-out phase,
   asset useful lives, and depreciation policy from the filing text — and to name the evidence
   and the ratio it is proposing.
4. **Bridge** — a translator rule maps that observation to an `assumption_change_pack` on
   `da_pct_target`, with percent-of-revenue delta bounds (0.5–8pp) rather than the basis-point
   defaults used for margin drivers.

### Boundary preserved

The LLM still never writes to the deterministic layer. The flow is unchanged:

```text
Evidence Packet -> Agent Observation -> Translator -> PM Decision Queue -> Approve -> Deterministic Rerun
```

Verified: a `terminal_reinvestment_incoherence` observation produces one pending
`assumption_change_pack` queue item on `da_pct_target`, carrying the agent's rationale and the
evidence anchor, awaiting PM approval. Nothing mutates the model until the PM approves.

### Still open

The agent has not actually been run against this — no LLM was dispatched this session pending
cost approval. What is proven is the plumbing: facts reach the packet, the observation type is
accepted, and the translator produces a correctly-bounded queue proposal. The first real run
is what will show whether the prompt guidance is good enough to produce a defensible ratio.

---

## 6. The real finding: reasoning has no authority over the model

Sections 1–5 treat individual assumptions. Stepping back one level shows the structural issue.

Classifying every assumption in the shipped MSFT model by where it came from:

| provenance | count |
| --- | --- |
| company evidence (CIQ historical extract) | 21 |
| sector default or mechanical transform | 8 |
| **LLM-reasoned** | **0** |

Not one assumption was set by reasoning. And the split runs the wrong way round: every
`*_start` value is a historical fact (correct — no judgment needed), while every
forward-looking `*_target` is arithmetic:

| driver | how it is set today |
| --- | --- |
| `ebit_margin_target` | 50/50 blend with a sector constant |
| `capex_pct_target`, `da_pct_target` | `start × 0.95` |
| `dso/dio/dpo_target` | 70/30 sector blend |
| `revenue_growth_mid` | `growth_near × sector fade ratio` |
| `revenue_growth_terminal`, `ronic_terminal` | sector constant |

The `*_target` values *are* the investment thesis — does the moat hold margin, does the
build-out normalize, does this business consume working capital. All of them are answered by
formula.

### The profiles cannot fix this, because they cannot see each other

`run_guided_ticker_workup.py:1339` runs the six regular profiles in a `ThreadPoolExecutor`.
`_run_profile_payload(deps, ticker, profile)` receives a ticker and a profile name and nothing
else. There is no `depends_on`, no ordering, and no mechanism for one profile's output to
become another's input. `analyst_prep_synthesis` is the only sequenced step and it is terminal.

So six agents each read a slice of the same filing in isolation and a seventh writes up what
they said. An agent asked to judge EBIT margin has no access to the business overview or the
industry analysis — the two things a human analyst would insist on before answering.

### What already exists

`story_drivers.py` is a working transmission belt from qualitative assessment to quantitative
drivers:

```text
story_profile (moat_strength, pricing_power, cyclicality,
               capital_intensity, governance_risk, advantage_years)
  -> apply_story_driver_adjustments()
  -> revenue_growth_near/mid, ebit_margin_target, wacc, cost_of_equity,
     capex_pct_target, da_pct_target, terminal blend weights, exit_multiple
```

Eight drivers, clamped and lineage-stamped. It is fed by a YAML sector lookup, so MSFT's
`moat_strength = 4` is the Technology row rather than a judgment about Microsoft — every
technology ticker in the universe scores identically. `_load_approved_pending` already routes
a per-ticker profile through PM approval.

**This is the highest-leverage insertion point in the codebase**, and it is not a greenfield
build: having `business_analysis` populate the story profile replaces a lookup at a junction
that is already load-bearing.

### Changed this session

Per PM direction ("coefficients can be larger"; "keep a base and then comments that can be
considered later by other agents"):

1. **A free-text half.** `StoryDriverProfile.notes` holds what the closed vocabulary cannot
   express — a patent cliff, a founder transition, a segment unlike the consolidated entity.
   Bounded at the boundary (12 notes, 600 chars) since it is agent-authored. Surfaced to
   downstream agents as `qualitative_notes`; **absent from every calculation**. Free text must
   never move a number implicitly, or an agent could edit the model through prose and bypass
   the PM queue. Regression-tested.
2. **Coefficients widened ~2.5–3x.** Previously a perfect 5/5 franchise could add 2.4pp of
   margin against a sector blend removing ~10pp — reasoning outvoted by arithmetic roughly
   4:1. A 5/5 now adds 6.6pp, a 4/4 adds 3.3pp.
3. **Authority scaled by provenance.** Widening alone would have amplified a *stereotype* on
   every ticker with no reasoned profile — strictly worse. `story_global`/`story_sector` get
   0.4 authority (≈ the original coefficients); `story_ticker` and
   `story_ticker_pending_approved` get 1.0. Multiplicative factors scale around 1.0, so
   `authority = 0` is a true no-op rather than zeroing the exit multiple.

Measured through the real pipeline (MSFT, single application):

| profile | authority | base IV | upside |
| --- | --- | --- | --- |
| 4/4 via `story_sector` | 0.4 | $291.02 | −23.8% |
| same 4/4, reasoned | 1.0 | $378.20 | −0.9% |
| 5/5 reasoned wide-moat, 15y | 1.0 | $449.99 | +17.9% |
| 2/2 reasoned weak franchise | 1.0 | $109.31 | −71.4% |

Sector-default tickers move $299 → $291, i.e. materially unchanged. Reasoned assessments now
span $109–$450.

> **Do not remove the provenance damping without re-timing the coefficients.** The widening is
> only safe because sector stereotypes stay damped. Removing
> `story_authority_for_source(...)` from the `apply_story_driver_adjustments` call in
> `input_assembler.py` would hand every unreasoned ticker a 2.5x amplified guess.

### Still missing

The seam is widened but **unfed**. Nothing populates the profile by reasoning yet, so MSFT's
live number remains the damped sector case. The next step is the `business_analysis` agent
writing a reasoned profile — scores plus notes — from Item 1/1A/7 and the industry read,
landing as `story_ticker_pending_approved` through the queue. After that, `industry_analysis`
as its upstream context, then `depends_on` ordering so Stage A context reaches Stage B driver
agents.
