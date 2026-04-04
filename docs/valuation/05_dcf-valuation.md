# DCF Valuation

## Purpose

DCF valuation converts forecasted business economics into intrinsic value.
It should never be treated as a black box or as a plug-and-play formula.

Its job is to answer:

- what the operating business is worth
- what equity is worth after accounting for non-equity claims and non-operating assets
- which assumptions are carrying the valuation
- whether value is driven by near-term cash generation or terminal assumptions

## Why DCF Matters

DCF is the cleanest framework for forcing consistency between:

- growth
- margins
- reinvestment
- returns on capital
- discount rate
- terminal economics

That is why it remains the core deterministic valuation method in Alpha Pod.
But it only works well when it is embedded in:

- credible company analysis
- credible historical analysis
- explicit forecast design
- a disciplined enterprise-to-equity bridge

## Ownership Model

### Deterministic

DCF math, bridge math, scenario math, and diagnostic outputs should be fully deterministic and auditable.

### LLM-augmented

LLMs can help explain why a result looks fragile, contradictory, or unusually sensitive, but they should not control the numeric engine.

### Human / PM Judgment

PM judgment is required to decide:

- whether DCF is the right primary method for the name
- whether the assumptions are investable
- whether the output should be trusted, discounted, or overruled

### Hard Boundary

The deterministic DCF remains authoritative for official numeric outputs.
Judgment-layer outputs may explain, challenge, or recommend overrides, but they must not silently change the model.

## Full Workflow

## 1. Start with the right valuation object

The first step is deciding what exactly is being valued.

Questions to answer:

- Are we valuing operating assets, total enterprise value, or equity value directly?
- Is FCFF the correct base, or does the company require an alternative framing?
- Are the bridge items understood well enough to convert enterprise value into equity value credibly?

Best practice:

- value the operating business first
- then bridge to equity carefully
- avoid mixing operating value with financing effects

## 2. Build the explicit forecast period

The explicit forecast period should translate the forecast assumptions into year-by-year economics.

Core lines:

- revenue
- EBIT
- taxes / NOPAT
- D&A
- capex
- working capital
- FCFF

Questions to answer:

- Is the explicit period long enough for margins and reinvestment to move toward a more stable state?
- Are the cash-flow mechanics internally coherent?
- Is growth supported by the reinvestment burden implied by the model?

Best practice:

- use a horizon long enough for meaningful fade
- make each major line economically interpretable
- avoid unexplained jumps between years

Deterministic outputs:

- explicit year-by-year forecast bridge
- FCFF path
- operating and reinvestment schedules

## 3. Convert operating earnings into free cash flow

DCF quality depends on getting from accounting earnings to cash flow in a disciplined way.

The basic FCFF build is:

- start from EBIT
- tax to NOPAT
- add non-cash charges like D&A
- subtract capex
- subtract working-capital investment

Questions to answer:

- Is EBIT normalized enough to use?
- Are D&A and capex treated consistently?
- Is working-capital investment being modeled with enough realism?

Best practice:

- keep the transformation auditable
- flag when key components are heuristic rather than directly sourced
- avoid letting weak denominator support hide in the model

## 4. Build the terminal value as an economic endpoint

Terminal value should represent a plausible long-run state, not merely a convenient way to make the model work.

Questions to answer:

- What stable growth rate is credible?
- What reinvestment is needed to support that growth?
- What returns on capital are implied in the stable state?
- Is an exit multiple defensible given industry and business quality?

Best practice:

- treat terminal value as an economic destination
- make Gordon, exit, and blended approaches all interpretable
- monitor terminal value as a percentage of total enterprise value

Deterministic outputs:

- Gordon value
- exit-multiple value
- blended terminal value
- terminal concentration diagnostics

## 5. Discount the cash flows consistently

Discounting should be consistent with the cash flow being valued and the risk the forecast represents.

Questions to answer:

- Is WACC the right rate for these cash flows?
- Are the discount-rate assumptions aligned with the risk profile of the business and capital structure?
- Does the forecast implicitly assume a different risk level than the discount rate suggests?

Best practice:

- do not treat discounting as a mechanical last step
- connect the discount rate to business and financing risk

## 6. Bridge enterprise value to equity value carefully

This is one of the most important places where apparently small mistakes can create false confidence.

Bridge items to review:

- net debt
- minority interest
- preferred equity
- pensions
- leases
- options and convertibles where material
- non-operating assets

Questions to answer:

- Are all material non-equity claims captured?
- Are bridge items well sourced or still partially heuristic?
- Are non-operating assets being treated consistently?

Best practice:

- bridge explicitly
- preserve source lineage for each major claim
- treat missing bridge items as a valuation-confidence issue, not just a modeling detail

## 7. Cross-check the result

A DCF should not stand alone.
It should be challenged from multiple angles.

Useful cross-checks include:

- FCFE
- economic profit / residual value
- reverse DCF
- comps
- PM sanity checks relative to history and peers

Best practice:

- use cross-checks to identify fragile or contradictory outputs
- do not use them as excuses to average away a weak model

## Recommended Artifact Set

| Artifact | Purpose | Owner |
| --- | --- | --- |
| DCF summary | high-level value output and key assumptions | deterministic |
| Explicit forecast bridge | shows the operating path year by year | deterministic |
| Terminal bridge | shows Gordon, exit, and blended value logic | deterministic |
| EV-to-equity bridge | shows how enterprise value becomes equity value | deterministic |
| Diagnostic flag pack | surfaces fragility and quality issues | deterministic |
| Cross-check block | compares DCF with EP, FCFE, reverse DCF, and comps | deterministic |
| DCF review note | explains whether the result is trustworthy enough to act on | PM-owned |

## What Should Feed Directly Into The DCF

The following belong directly in the deterministic core:

- explicit operating forecast lines
- tax, reinvestment, and working-capital paths
- discount-rate mechanics
- terminal value mechanics
- EV-to-equity bridge
- diagnostics and cross-checks

The following should stay advisory until approved:

- LLM-generated fragility narratives
- suggested normalization changes
- qualitative views on whether a result "feels too high" or "too low"

## Current Implementation Notes

Alpha Pod already has a strong deterministic DCF core.
The main opportunity is not to replace it, but to embed it in a stronger surrounding analysis framework and improve the documentation and sourcing around:

- terminal-value interpretation
- bridge-item completeness
- reinvestment consistency
- output explainability

## Practical Review Questions For The PM

1. Is DCF the right primary valuation tool for this business?
2. What assumptions are doing the most work?
3. How much of value comes from the terminal period?
4. Are bridge items well enough sourced to trust the equity value?
5. Does the DCF tell a coherent economic story, or just a mathematically valid one?
