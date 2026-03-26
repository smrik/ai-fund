# Risk Impact Agent Spec

## Purpose

`RiskImpactAgent` converts qualitative downside risks into structured advisory scenario overlays that can be revalued by the deterministic DCF engine.

It does not change the base valuation, write to overrides, or feed back into computation-layer assumptions.

## Output Contract

The agent returns `RiskImpactOutput`:

- `overlays`: up to 3 downside scenarios
- `raw_summary`: short narrative summary
- `base_iv`, `risk_adjusted_expected_iv`, `risk_adjusted_delta_pct`, `residual_base_probability`: populated after deterministic quantification

Each `RiskScenarioOverlay` includes:

- `risk_name`
- `source_type`
- `source_text`
- `probability`
- `horizon`
- `revenue_growth_near_bps`
- `revenue_growth_mid_bps`
- `ebit_margin_bps`
- `wacc_bps`
- `exit_multiple_pct`
- `rationale`
- `confidence`

## Downside-Only Guardrails

V1 uses downside-only shifts:

- growth shifts: `<= 0`
- margin shifts: `<= 0`
- WACC shifts: `>= 0`
- exit multiple shift: `<= 0`
- total overlay probability: `<= 1.0`

Deterministic clamp bounds:

- `revenue_growth_near_bps`: `[-1500, 0]`
- `revenue_growth_mid_bps`: `[-1000, 0]`
- `ebit_margin_bps`: `[-1500, 0]`
- `wacc_bps`: `[0, 300]`
- `exit_multiple_pct`: `[-50, 0]`

## Pipeline Placement

The step runs after `RiskAgent` and before `ThesisAgent`.

Inputs:

- filings red flags
- management guidance
- earnings themes
- sentiment risk narratives
- QoE context
- accounting recast context
- deterministic valuation output
- company metadata

## Deterministic Quantification

`src/stage_04_pipeline/risk_impact.py`:

1. assembles baseline valuation inputs
2. computes base IV
3. applies each overlay to copied `ForecastDrivers`
4. reruns deterministic DCF for each overlay
5. computes stressed IV and deltas
6. computes risk-adjusted expected IV as:

`residual_base_probability * base_iv + sum(probability_i * stressed_iv_i)`

## Dashboard Usage

The Streamlit dashboard shows:

- per-risk stressed IV
- probability-weighted risk-adjusted expected IV
- overlay table and charts in `DCF Audit`
- a summary in the `Risk` section

## Auditability

The agent run is cached and logged like other judgment agents.
The exact prompt, raw output, parsed output, and tool trace are viewable in the dashboard `Agent Audit Trail` expander.
