# Layered Architecture Rollout Plan (Deterministic First)

## Summary
- Your proposed sequence is correct: `standalone batch valuation` → `CIQ pipeline` → `judgment agents one-by-one`.
- For batch valuation, proceed with a full sector playbook now (your selected direction), not uniform assumptions.
- Milestone 1 scope is the Stage 1 survivor universe (`config/universe.csv`, currently ~104 names as of 2026-03-06).
- Migration strategy is feature-flagged parallel run, then replacement of the legacy 6-agent flow.

## Key Changes
1. Deterministic Batch Valuation Hardening
- Externalize sector/subsector assumptions (growth, margins, WACC bands, exit multiples, capex/D&A norms).
- Add deterministic guardrails and explicit flags for extreme outputs and low-data cases.
- Add audit columns (`assumption_source`, `flag_codes`, `data_quality_score`, fallback reason) to ranking outputs.
- Keep deterministic-only computation and separate LLM logic entirely from this layer.
- Acceptance gate: >=95% ticker coverage, <=15 min runtime on current Stage 1 universe, no silent failures.

2. CIQ Pipeline Completion
- Implement canonical CIQ schema mapping via config + strict validation (fail fast on missing required fields).
- Complete CIQ export ingestion into DB with normalized fields for downstream valuation/screening.
- Refactor Stage 2 filter to consume normalized canonical fields, not rigid raw headers.
- Add pipeline metadata logging (row counts, timestamps, staleness).

3. Judgment Layer Rollout (Order Locked)
- Roll out agents in this order: `Quality of Earnings` → `Comps Matching` → `Scenario/Catalyst` → `Industry Research`.
- Trigger defaults:
- QoE: per ticker after CIQ refresh.
- Comps Matching: per ticker after QoE.
- Scenario/Catalyst: per ticker after QoE+Comps, plus news-trigger reruns.
- Industry Research: weekly per sector.
- Define strict per-agent input/output contracts so orchestration stays deterministic outside LLM calls.

4. Orchestrator Migration
- Add new layered orchestrator path behind a feature flag.
- Run legacy and layered outputs side-by-side for a validation window.
- Track deltas on valuation range, conviction, and recommendation consistency.
- Cut over to layered path once gates pass, then deprecate legacy path.

## Test Plan
- Unit tests: assumption resolution, fallback precedence, guardrails, output flags.
- Integration tests: CIQ mapping validation, DB upserts, normalized schema consumption.
- End-to-end deterministic batch test: full Stage 1 universe with coverage and runtime assertions.
- Agent contract tests: required fields, schema conformance, graceful failure behavior.
- Parallel-run regression tests: fixed benchmark ticker set comparing legacy vs layered outputs.

## Assumptions
- Stage 1 survivors remain the canonical Milestone 1 run set (not a fixed 332-list yet).
- CIQ is primary fundamentals source once integrated; yfinance remains deterministic fallback.
- Data and computation layers remain strictly non-LLM.
- Existing duplicate architecture markdown is treated as stale and replaced with the layered architecture spec during implementation.

