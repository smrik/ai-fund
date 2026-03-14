# Accounting Recast Agent Spec

## Purpose

`AccountingRecastAgent` is a judgment-layer helper that proposes:

- EBIT normalization items
- EV-to-equity bridge classifications
- override candidates that a PM may manually copy into `config/valuation_overrides.yaml`

It does not import or affect deterministic valuation code directly.

## Output Contract

The agent returns a structured dict with:

- `ticker`
- `source`
- `confidence`
- `income_statement_adjustments`
- `balance_sheet_reclassifications`
- `override_candidates`
- `approval_required`
- `pm_review_notes`

## Boundary Rule

- LLM output is advisory only.
- Deterministic valuation reads only approved values from `config/valuation_overrides.yaml`.
- The orchestrator may display or summarize the recast proposal, but must not feed it into the DCF automatically.
