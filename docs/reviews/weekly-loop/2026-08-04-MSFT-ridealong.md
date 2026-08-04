# Weekly Loop Ride-Along — MSFT

- Date: 2026-08-04
- Session number: pre-M1 ride-along
- Tickers: MSFT
- Total time: in progress
- Counts toward M1 exit criteria: no — guided dry run and hardening session

## Fixed Run Contract

- Database: `output/ridealong_msft_20260804/_isolated_db/MSFT-20260804T173819Z-step2.db`
- Ticker: `MSFT`
- Resolved CIQ run: `20`
- Financial as-of date: `2026-06-30`

## Step 1 And Step 2 Checkpoint

- Statement readiness: `decision_grade`
- Annual periods: `5`
- LTM status: `source_provided`
- Operating reconciliation: `reconciled`
- Operating reconciliation reason codes: none
- Revenue: USD 331.839bn
- EBIT margin: 45.68%
- Capex: USD 115.948bn, or 34.94% of revenue
- D&A: USD 34.300bn, or 10.34% of revenue
- DSO / DIO / DPO: 88.96 / 4.79 / 145.54 days

The deterministic DCF remains a provisional diagnostic. Forecast targets are not yet
judgment-authored and the exit multiple is still the Technology default.

## Step 3 Business-Analysis Packet Checkpoint

The cache-only packet build persisted `company_analysis` evidence packet `228` in the isolated
database. No LLM call was made.

- Source quality label: `real`
- Source references: `9`
- Facts: `10`
- Filing snippets: `6`
- Extraction-prompt size: `11,775` characters
- Filing collector: `12` chunks found, `6` included

The packet is structurally valid but not analytically ready:

1. The numerical history ends at FY2025 although the FY2026 10-K dated 2026-07-29 is cached.
2. The selected snippets are mostly older-file boilerplate and accounting, tax, or debt fragments;
   they do not provide a coherent description of Microsoft's current business, segments,
   competitive position, or operating drivers.
3. The packet exposes only near-term growth, starting EBIT margin, and target EBIT margin from the
   model. The target margin is explicitly default-authored.
4. `source_quality=real` currently means that real snippets exist, not that they are relevant or
   sufficient for the analytical question.
5. The packet builder still calls the legacy `build_valuation_inputs(ticker)` seam. This ride-along
   constrained it with the isolated database and cache-only environment, but Step 3 should consume
   the same explicit `db_path + ticker` run contract as Step 2.

## Friction Items

| Phase | Severity | Manual data surgery? | What happened | Fix/ticket |
| --- | --- | --- | --- | --- |
| Business analysis | High | No | Cached FY2026 filing exists, but the quantitative series stops at FY2025 | Make the packet use the latest canonical financial period from the run database |
| Business analysis | High | No | Retrieval selected six weak or irrelevant excerpts | Define and verify a focused business-analysis retrieval contract before LLM dispatch |
| Business analysis | Medium | No | A packet with snippets is labeled `real` even when the evidence is not sufficient for the question | Separate source authenticity from evidence sufficiency/relevance |
| Step 2 → Step 3 boundary | High | No | Packet assembly relies on process-global DB configuration and the legacy input assembler | Add an explicit DB-bound packet-build entrypoint |

## Keep / Change

- Keep: the ride-along pause before every LLM call, packet persistence, exact evidence anchors, and
  deterministic status-quo reconciliation.
- Change: do not dispatch `company_analysis` until the packet contains current-period numbers and
  focused evidence about the business, segments, competition, demand, pricing power, and capital
  intensity.
