# PM Valuation Review Checklist

Use this companion while reading the valuation docs and challenging the current methodology.

The goal is not to polish wording. The goal is to decide whether the valuation stack reflects sound investing logic, where the weakest assumptions live, and what should be improved next.

## How To Use This Checklist

Recommended first-pass review order:

1. [`docs/design-docs/deterministic-valuation-benchmark-and-gap-analysis.md`](../design-docs/deterministic-valuation-benchmark-and-gap-analysis.md)
2. [`01_company-analysis.md`](./01_company-analysis.md)
3. [`03_historical-financial-analysis.md`](./03_historical-financial-analysis.md)
4. [`04_financial-forecasting.md`](./04_financial-forecasting.md)
5. [`06_wacc-and-capital-structure.md`](./06_wacc-and-capital-structure.md)
6. [`07_terminal-value.md`](./07_terminal-value.md)
7. [`08_sensitivity-scenarios-and-reverse-dcf.md`](./08_sensitivity-scenarios-and-reverse-dcf.md)
8. [`09_comps.md`](./09_comps.md)
9. [`10_qoe-and-normalization.md`](./10_qoe-and-normalization.md)

Suggested annotation rule:

- mark `[x]` when you agree the current framing is right
- mark `[ ]` when the current framing feels weak, incomplete, or wrong
- add short notes under each section
- prefer concrete comments like "needs cyclicals handling" over vague comments like "unclear"

## Review Rubric

When a section feels weak, capture these four things explicitly:

- `Status`: strong, weak, or missing
- `Priority`: P0, P1, or P2
- `Blocks underwriting`: yes or no
- `Confidence`: high, medium, or low
- `Owner`: deterministic, LLM-augmented, PM workflow, or docs

Minimum note template for weak areas:

- Observed issue:
- Why it matters for valuation:
- Suggested change:
- Evidence or example:
- Acceptance check:

## 1. Benchmark And Gap Map

Primary doc:

- [`docs/design-docs/deterministic-valuation-benchmark-and-gap-analysis.md`](../design-docs/deterministic-valuation-benchmark-and-gap-analysis.md)

Questions to answer:

- [x] The benchmark reflects how I would evaluate a public-equity valuation process in real life.
- [x] The listed P0 gaps are actually the highest-impact gaps.
- [x] The gap split between data / CIQ problems and model-design problems feels right.
- [x] The recommended issue sequence matches how I would harden the stack.
- [x] The current "what Alpha Pod already does well" section is fair and not overstated.

Notes:

- Strengths I agree with:
  - keeping the main computations deterministic, instead of just using LLMs for the sake of using them
  - strong financial logic compared to other competitors
- Gaps I think are missing:
- Gaps I would reprioritize:

## 2. Company Analysis

Primary doc:

- [`01_company-analysis.md`](./01_company-analysis.md)

Questions to answer:

- [x] The business-framing step asks the right questions before modeling begins.
- [x] The revenue-model section matches how I actually think about business drivers.
- [x] The cost structure and operating leverage sections are decision-useful.
- [x] Capital intensity and reinvestment needs are framed in a way that supports later forecasting.
- [x] Customers, suppliers, and bargaining power are covered at the right level.
- [x] Competitive position and business quality are defined clearly enough to support underwriting.
- [x] Management and capital allocation are included in a useful way instead of as generic checklist filler.
- [ ] The forecast-ready driver map is the right output of company analysis.

Notes:

- The main issue is with the output of this. Right now it looks like it's going to be a summary made by an LLM.
I don't see how this will be passed into the next step of analysis, I think we should add some more quantitative inputs.
We should translate the descriptions into actual numbered recommendations — this is the part where the PM should have to
utilize their judgement most. That is the art of valuation — going from "The company has good bargaining power" -> +1.5% revenue
growth in the next 5 years.

Resolution note:

- Resolved for docs by [`01_company-analysis.md`](./01_company-analysis.md), section 8, which now defines the analysis-to-forecast handoff object and explicitly frames the narrative-to-numbers translation as the PM-owned seam.
- Coding follow-up remains: turn the handoff object into an executable contract in the next PR.

## 3. Historical Financial Analysis

Primary doc:

- [`03_historical-financial-analysis.md`](./03_historical-financial-analysis.md)

Questions to answer:

- [x] Clean multi-year statement assembly is treated as a first-class prerequisite.
- [ ] The reclassification step is valuation-oriented and not just accounting housekeeping.
- [x] Rolling trend views are emphasized enough relative to simple CAGR snapshots.
- [x] Common-size statements are included at the right depth.
- [x] The ratio pack covers the metrics I actually trust.
- [x] Cash conversion and working-capital behavior are covered well enough.
- [ ] Capital intensity and balance-sheet evolution are framed usefully.
- [x] Peer-relative historical benchmarking belongs here and is described well.
- [x] The historical driver map is a real bridge into forecasting.
- [ ] The forecast handoff section is strong enough to support a professional model.

Notes:

- Historical metrics I care about most:
  - I think that there should be a consideration made for the reasons behind certain changes (I think that
  this is mostly disclosed in the Management Discussion section of the 10-Ks), for example: "In 2024 the Crisis in the
  Middle East drastically impacted our transport costs" -> model places less emphasis on metrics from 2024 ...
  - I think here a lot can be pretemplated and calculated from CIQ and some clever excel sheet design and formulas.
  Keep this in mind.
  - The peer analysis has to logically "flow" from the 01_company-analysis and be included into the judgement of peers.
- Historical analyses that feel missing:
  - I think that the section on reclasifying the statements is not exact and detailed enough. It's a difficult and
  important step.
  - More focus should be placed on the Capex and D&A schedules, they have to logically flow into each other and into
  the future balance sheet. We can't just project stable Capex as percent of sales, but not increase the assets later on.
  - We should improve the logic of the forecast handoff to be more numeric and structured. Feels very qualitative.
- Years or period logic that should be handled more explicitly:

Resolution note:

- Partly resolved for docs by [`03_historical-financial-analysis.md`](./03_historical-financial-analysis.md), section 3, which now defines representative-period tags plus deterministic default tag rules before PM override.
- Partly resolved by the historical-to-forecast handoff fields later in the same doc.
- Still open for coding: schedule controls for capex, D&A, working capital, and balance-sheet roll-forward checks.

## 4. Financial Forecasting

Primary doc:

- [`04_financial-forecasting.md`](./04_financial-forecasting.md)

Questions to answer:

- [x] The forecast starts from explicit business drivers, not generic default lines.
- [ ] The assumption register is defined well enough to support disciplined modeling.
- [x] Revenue forecasting is tied to identifiable drivers.
- [x] Margin forecasting reflects operating leverage and business economics.
- [ ] Tax forecasting is good enough for the type of valuation work Alpha Pod is doing.
- [ ] Reinvestment forecasting is tied to growth in a financially credible way.
- [x] The funding-path and balance-sheet implications of growth are handled seriously enough.
- [ ] Scenario design is connected to the business and cycle, not just spreadsheet sensitivity habits.
- [x] The forecast validation step is strong enough to block weak models before valuation output is trusted.

Notes:

- Forecast assumptions I would want sourced more explicitly:
- Places where the model still feels too generic:
- Forecast outputs that should never be automated without review:


- This step is crucial and has to use all the previous inputs to drive the forecasts and include
  the most PM judgement out of all. Also required "smarter" LLM model (possibly RAG to avoid forgetting
  the middle part? This will be very information heavy and difficult to process with LLMs - topic
  segmentation would be useful)!!!
- 1st step remains very vague, how will we deterministically determine the level of detail? and
  "intrinsic value, scenario comparison, downside testing, or thesis monitoring?" <- this has to be
  logically broken down into deterministic logic.

Resolution note:

- Resolved for docs by [`04_financial-forecasting.md`](./04_financial-forecasting.md), section 1, which now defines the weighted forecast-scoping score and numeric thresholds for full, moderate, and light models.
- Still open for coding: implement the scoping scorecard and link it to the eventual assumption register.

## 5. WACC And Capital Structure

Primary doc:

- [`06_wacc-and-capital-structure.md`](./06_wacc-and-capital-structure.md)

Questions to answer:

- [x] The doc starts from business risk, not just formula mechanics.
- [x] Current capital structure is treated accurately enough for equity valuation.
- [ ] Cost of equity logic is economically credible.
- [ ] Cost of debt logic is adequate for this stack.
- [x] Capital-structure evolution is considered seriously enough when growth needs funding.
- [x] The validation section would catch obviously weak discount-rate decisions.

Notes:

- WACC assumptions I distrust most:
  - Weak computations of beta (hamada?, regression?, bottom-up?)
  - Weak computations of cost of debt (interest coverage?, issued debt?, industry cost of debt?, ...)
- This should be the most deterministic of the steps.

Resolution note:

- Resolved for docs by [`06_wacc-and-capital-structure.md`](./06_wacc-and-capital-structure.md), section 6, which now defines WACC policy controls, default bps thresholds, ERP cadence, country-risk materiality, and the Damodaran synthetic-rating spread table.
- Still open for coding: turn those defaults into the WACC evidence ladder and method-disagreement flags.

## 6. Terminal Value

Primary doc:

- [`07_terminal-value.md`](./07_terminal-value.md)

Questions to answer:

- [x] Stable-state thinking is defined clearly enough.
- [x] Stable-growth value is grounded in believable economics.
- [x] Exit-multiple value is used with enough caution.
- [x] The blend logic is disciplined rather than convenient.
- [x] Terminal concentration is treated as a serious risk signal.
- [x] The pressure-testing framework matches how I would challenge terminal assumptions in practice.

Notes:

- Very strong

## 7. Sensitivity, Scenarios, And Reverse DCF

Primary doc:

- [`08_sensitivity-scenarios-and-reverse-dcf.md`](./08_sensitivity-scenarios-and-reverse-dcf.md)

Questions to answer:

- [x] The docs identify the right high-impact assumptions to stress.
- [x] One-variable sensitivities are framed as useful diagnostics, not a full risk framework.
- [x] Multi-variable scenarios are described as coherent business states, not arbitrary math cases.
- [x] Reverse DCF is framed in a way that is truly decision-useful.
- [x] The PM review surface is focused on what would actually change the investment decision.

Notes:

- Strong, possibly we could experiment with changing a lot of variables to see which have the highest impact.
  This could also tie back as a control of the previous assumptions (forecasting, ...)

## 8. Comparable Company Analysis

Primary doc:

- [`09_comps.md`](./09_comps.md)

Questions to answer:

- [x] The definition of "comparable" is strong enough.
- [x] Peer-set construction is described in a way I would trust.
- [ ] The multiple-selection framework fits different business types well.
- [x] Forward vs LTM treatment is right.
- [x] Business-quality differences are normalized thoughtfully enough.
- [x] Outlier handling is disciplined.
- [x] The final comps narrative would help me challenge a DCF rather than just decorate it.

Notes:

- What makes a peer genuinely comparable for me:
- Multiples I trust most by business type:
  - more market based values and less accounting magic values
  - Matching principle is crucial
  - should be somewhat maturity and industry based
- Where the current comps approach still feels weak:

- I feel like the construction of peer set should be done sooner, because it ties into previous steps.

Resolution note:

- Resolved for docs by [`09_comps.md`](./09_comps.md), sections 2 and 3, which now define peer scoring, floor guards, conflict rules, the metric ladder, SaaS checks, and the FCFF / UFCF / FCFE distinction.
- Still open for coding: implement the peer-universe contract and reuse it upstream for beta, historical benchmarking, and comps.

## 9. QoE And Normalization

Primary doc:

- [`10_qoe-and-normalization.md`](./10_qoe-and-normalization.md)

Questions to answer:

- [x] Deterministic QoE signals are the right first layer.
- [x] Normalization candidates are described in a way that reflects real valuation work.
- [x] The recast of operating earnings is useful and disciplined.
- [x] Bridge items and accounting reclassification are taken seriously enough.
- [x] The control boundary for pushing normalization into the model is right.

Notes:

- Good enough already

## Additional Review Areas

Use these when the core stack is strong enough that you want to pressure-test the remaining canon.

### Industry Analysis

Primary doc:

- [`02_industry-analysis.md`](./02_industry-analysis.md)

Questions to answer:

- [ ] The industry structure section is strong enough to support later forecasting.
- [ ] The doc separates structural, cyclical, and macro drivers clearly enough.
- [ ] Industry analysis feeds company analysis and forecasting instead of floating beside them.

Notes:

- Observed issue:
- Why it matters for valuation:
- Suggested change:

Resolution note:

- Partly resolved by [`02_industry-analysis.md`](./02_industry-analysis.md), section 4, which now defines quantitative cycle indicators, FRED-backed macro context, and the forecast-constraint-pack expectation.

### DCF Valuation

Primary doc:

- [`05_dcf-valuation.md`](./05_dcf-valuation.md)

Questions to answer:

- [ ] The DCF section ties FCFF, EV, and equity value together clearly enough.
- [ ] The EV-to-equity bridge is documented rigorously enough.
- [ ] The DCF section is specific enough about where deterministic math ends and approved overrides begin.

Notes:

- Observed issue:
- Why it matters for valuation:
- Suggested change:

### PM Review Framework

Primary doc:

- [`11_pm-review-framework.md`](./11_pm-review-framework.md)

Questions to answer:

- [ ] The PM review sequence matches how I would actually underwrite a name.
- [ ] The decision-state logic is explicit enough.
- [ ] The PM review framework helps convert valuation output into action, not just commentary.

Notes:

- Observed issue:
- Why it matters for decision-making:
- Suggested change:

### Deterministic Vs LLM Boundary

Primary doc:

- [`12_deterministic-vs-llm-boundary.md`](./12_deterministic-vs-llm-boundary.md)

Questions to answer:

- [ ] The boundary is clear enough to prevent accidental model mutation.
- [ ] The allowed role for LLMs is still useful rather than overly restrictive.
- [ ] PM approval points are explicit enough.

Notes:

- Observed issue:
- Why it matters for control:
- Suggested change:

Resolution note:

- Partly resolved by [`12_deterministic-vs-llm-boundary.md`](./12_deterministic-vs-llm-boundary.md), which now includes Beneish / Altman as a worked example of deterministic signals that can trigger review but cannot auto-mutate the model.

## Cross-Step Handoff And Model Contracts

Use this section to review the seams between the docs, not only the docs individually.

Questions to answer:

- [ ] Company analysis outputs are explicit enough to feed historical review and forecasting.
- [ ] Historical analysis produces a structured, numeric handoff rather than only interpretation.
- [ ] Forecasting states clearly which assumptions are deterministic, advisory, and PM-approved.
- [ ] Peer selection is shared early enough to support historical benchmarking, beta, and later comps.
- [ ] WACC, scenarios, and comps all consume artifacts that can be audited later.
- [ ] The docs define enough controls to catch broken schedule logic, weak sourcing, or hidden overrides.

Notes:

- Biggest handoff failure:
- Missing artifact or contract:
- Which step currently leaks narrative where it should pass structure:
- Which control would catch this:

Resolution note:

- Docs now define the main handoff controls, but this remains intentionally open until the next coding PR adds executable contracts for `AssumptionRegisterEntry` and `PeerCandidate`.

## 10. Overall Judgment

After reviewing the stack, try to answer these directly:

- [x] The valuation framework is economically coherent end to end.
- [x] The most important current weaknesses are now explicit in the docs.
- [x] I know which 3 to 5 follow-on issues matter most.
- [x] I can tell what should be deterministic, what should be LLM-augmented, and what should remain PM judgment.
- [ ] I would be comfortable using this doc set as the canon for future valuation hardening.

Final notes:

- Top 3 priorities:
  1. Better pass of numbers and infomration between different steps
  2. More controls should be put in place to make review easier and more reliably, ie:
    - Does the balance sheet balance out?
    - Tax reconciliation tables
    - D&A schedules, WC schedules, ...
  3. More explicit logic breakdown
- Biggest modeling risk: issues with translating from qualitative (from LLMs) and quantitative (for models)
- Biggest data / CIQ risk: Slow loading
- Biggest docs / clarity risk: Mismatch between the finance and coding logic

## Issue Conversion

Use this table to turn your notes into backlog items without doing a second translation pass.

| Issue title | Problem | Desired behavior | Priority | Owner | Dependencies | Acceptance criteria |
| --- | --- | --- | --- | --- | --- | --- |
|  |  |  |  |  |  |  |
|  |  |  |  |  |  |  |
|  |  |  |  |  |  |  |
