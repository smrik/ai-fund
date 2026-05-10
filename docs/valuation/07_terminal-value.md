# Terminal Value

## Purpose

Terminal value is where many valuation errors hide.
It deserves its own framework rather than being treated as an appendix.

For many businesses, terminal value contributes most of total enterprise value.
That means poor terminal assumptions can dominate the model while looking deceptively tidy.

## Why This Matters For Valuation

Terminal value should answer a serious economic question:

- what does the business look like once it reaches a more stable state?

That requires consistency among:

- stable growth
- reinvestment
- returns on capital
- capital intensity
- competitive position
- exit multiple logic where used

## Ownership Model

### Deterministic

The deterministic layer should own:

- Gordon value
- exit value
- blended value
- terminal diagnostics
- terminal value as a percentage of EV

### LLM-augmented

LLMs can help explain why terminal assumptions may be fragile or contextually implausible, but they should not set the numeric terminal framework.

### Human / PM Judgment

PM judgment is required to decide:

- which terminal framing is credible
- whether the implied stable-state economics are believable
- whether the terminal contribution is too large to trust comfortably

### Hard Boundary

Terminal mechanics should remain deterministic.
Narrative challenge is helpful, but it should not rewrite terminal assumptions without explicit approval.

## Full Workflow

## 1. Define the stable-state concept

Before calculating terminal value, define what the mature business is supposed to look like.

Questions to answer:

- Is the company converging toward a stable mature state, or staying structurally cyclical?
- What long-run growth range is credible?
- What margin and reinvestment profile are sustainable in that state?
- What return on capital is plausible in the mature phase?

Best practice:

- think of terminal value as a stable-state economics question first
- do not begin with the multiple and work backward

## 2. Build the stable-growth value

The Gordon framework is useful because it forces economic discipline.

Questions to answer:

- Is the growth rate below a believable long-run ceiling?
- Is the reinvestment burden consistent with the growth assumption?
- Are returns on capital consistent with competition and industry structure?

Best practice:

- prefer a stable-growth value when it reflects the economics more honestly
- treat implausibly high long-run growth as a model-quality problem
- use the value-driver identity so growth, reinvestment, and return on capital reconcile instead of floating independently

Value-driver terminal identity:

```text
terminal_reinvestment_rate = terminal_growth / terminal_RONIC
terminal_FCFF = terminal_NOPAT_next_year * (1 - terminal_reinvestment_rate)
terminal_value = terminal_FCFF / (WACC - terminal_growth)
```

This follows the Koller / Goedhart / Wessels value-driver framing: growth, return on invested capital, reinvestment, and WACC must reconcile rather than being selected independently.
Reference: https://www.mckinsey.com/featured-insights/mckinsey-explainers/how-are-companies-valued

Required checks:

- `terminal_RONIC > terminal_growth`
- `terminal_growth < WACC`
- `terminal_growth` stays below the approved long-run nominal growth cap
- terminal margin and terminal RONIC sit inside mature peer / industry ranges unless PM-approved
- value-driver terminal FCFF reconciles to the bridge terminal FCFF, with the variance shown

Dual-track terminal FCFF:

- `value_driver_FCFF` = `NOPAT_T+1 * (1 - terminal_growth / terminal_RONIC)`, used when `terminal_RONIC > terminal_growth + 50 bps`
- `bridge_FCFF` = last explicit forecast-year FCFF projected one period forward, used as the fallback when the value-driver path fails its guards
- the variance between the two should be reported; large variance is a terminal fragility flag

Deterministic outputs:

- stable-growth terminal value
- implied stable-state economics

## 3. Build the exit-multiple value

An exit multiple can be useful, but it needs economic support.

Questions to answer:

- Is the chosen multiple consistent with peer quality and industry structure?
- Is it a forward or LTM multiple, and does that match the logic of the model?
- Does the terminal business deserve that multiple, not just the company today?

Best practice:

- do not use the multiple as a hidden plug
- connect the multiple to terminal business quality, not only current market convention

Deterministic outputs:

- exit-value terminal output
- exit-multiple audit

## 4. Use a blend only when it improves discipline

Blending Gordon and exit value can be useful, but only if it improves robustness.

Questions to answer:

- Does the blend reduce concentration risk?
- Or does it merely hide weak assumptions in both methods?

Best practice:

- explain why a blend is being used
- do not assume blending automatically makes the result safer

Deterministic outputs:

- blended terminal value
- contribution weights

## 5. Audit terminal concentration

One of the most important diagnostics is how much of total value comes from the terminal period.

Questions to answer:

- What percentage of enterprise value comes from terminal value?
- Is the valuation still investable if terminal value dominates?
- Would a modest change in terminal assumptions erase the thesis?

Best practice:

- surface terminal concentration prominently
- treat very high concentration as a fragility warning

Deterministic outputs:

- terminal value as % of EV
- concentration flags

## 6. Pressure-test the terminal framework

Terminal value should be challenged explicitly.

Useful stress questions:

- What if stable growth is lower?
- What if returns on capital fade faster?
- What if the business deserves a lower multiple at maturity?
- What if the current cycle is flattering margins into the terminal year?

Best practice:

- link terminal stress to business and industry realities
- treat terminal sensitivity as a PM review tool, not an afterthought

## Recommended Artifact Set

| Artifact | Purpose | Owner |
| --- | --- | --- |
| Stable-growth audit | checks long-run growth, reinvestment, and return consistency | deterministic |
| Exit-multiple audit | checks metric choice and multiple defensibility | deterministic |
| Terminal bridge | shows Gordon, exit, and blended values | deterministic |
| Terminal concentration diagnostics | shows how much of EV is terminal-driven | deterministic |
| Terminal review note | explains whether the terminal framing is investable | PM-owned |

## What Should Feed Directly Into Valuation

The following belong in the deterministic core:

- Gordon mechanics
- exit mechanics
- blending mechanics
- terminal diagnostics

The following should stay advisory until approved:

- LLM-generated challenge narratives
- Monte Carlo or probabilistic terminal overlays that are not yet formalized

## Current Implementation Notes

Alpha Pod already has a good Gordon / exit / blend structure.
Near-term follow-up should include richer exploration of exit distributions and Monte Carlo-style terminal scenario work, but that is not current implementation.

## Practical Review Questions For The PM

1. Is the terminal growth assumption economically plausible?
2. Is the required reinvestment consistent with that growth?
3. Does the exit multiple fit the terminal business, not just today's market mood?
4. How much of the valuation depends on terminal assumptions?
