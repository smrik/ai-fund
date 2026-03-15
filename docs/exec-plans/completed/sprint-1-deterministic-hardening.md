# Sprint 1: Deterministic Engine Hardening

**Status:** ACTIVE
**Started:** 2026-03-06
**Goal:** Batch runner produces defensible, human-reviewable valuations using 3yr historical data, real capex/D&A, derived cost of debt, reverse DCF, and TV% warning. No LLM, no CIQ.
**Done when:** 95%+ ticker coverage, all audit columns present, <15 min runtime on Stage 1 universe.

## Full Implementation Plan

See [`docs/plans/2026-03-06-dcf-pipeline.md`](../../plans/2026-03-06-dcf-pipeline.md) — Sprint 1 tasks.

## Tasks

- [ ] Task 1.1 — `get_historical_financials()` in `src/stage_00_data/market_data.py`
- [ ] Task 1.2 — Wire 3yr data into `batch_runner.py` assumptions + audit columns
- [ ] Task 1.3 — Reverse DCF + TV% warning in batch output
- [ ] Task 1.4 — Derived cost of debt in `wacc.py`
- [ ] Task 1.5 — End-to-end acceptance gate run

## Decision Log

- 2026-03-06: Sector-specific defaults confirmed as the right approach (not uniform). See `batch_runner.SECTOR_ASSUMPTIONS`.
- 2026-03-06: Margin trajectory (expansion modeling) deferred to Sprint 3 (QoE agent). Flat margin for now.
- 2026-03-06: NWC change derived from balance sheet actuals (not hardcoded 1%) in Task 1.2.

