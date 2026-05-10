# Product Sense

## What This Is

Alpha Pod is a solo-operator fundamental equity research system.
It automates the work of a 15-30 person hedge fund team down to one human + code.

## The Human's Job (PM role)

- Variant perception: why is the consensus wrong?
- Catalyst identification: what event closes the gap and when?
- Sizing conviction: how much to bet, and holding through drawdowns
- Strategy review: is the system adding value?

The system never makes investment decisions. It surfaces ranked opportunities with structured analysis so the PM can make faster, better-informed decisions.

## The System's Job (everything else)

- Screen 3,000+ US equities down to ~50 worth researching
- Run WACC + DCF on all survivors, rank by upside
- Normalize reported earnings for one-time items (QoE agent)
- Calibrate assumptions from actual peer data (Comps + Industry agents)
- Build named scenarios from risk factors and news (Scenario agent)
- Monitor positions daily, flag risk limit breaches
- Execute trades via IBKR API (Phase 3)

## Target Universe

- US-domiciled equities, $500M–$10B market cap
- Profitable (ROE > 12%), tradeable (avg volume > 100K shares/day)
- Excludes: Financial Services, Utilities, Real Estate (different valuation frameworks)

## The Economics

The junior analyst role at a real fund costs $150–300K/year in salary.
This system replaces that work for ~$50–150/month in API costs.
The edge compounds over time: better data, faster processing, no cognitive biases from fatigue.

## Current Phase

**Phase 1** — Data foundation and deterministic valuation engine.
Running: Stage 1 screen → batch DCF ranking of ~300 stocks.

**Phase 2** (next) — LLM agents layered on top.
QoE normalization → Comps calibration → Industry context → Scenario modeling.

**Phase 3** (later) — Execution and monitoring.
IBKR API, daily risk reports, position monitoring, alerts.
