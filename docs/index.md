# Docs Index

This directory is the start of the project wiki.

## Handbook (Start Here)

- [Handbook Index](./handbook/index.md)
- [End-to-End Workflow](./handbook/workflow-end-to-end.md)
- [Finance Deep Dive](./handbook/finance-deep-dive.md)
- [Engineering Deep Dive](./handbook/engineering-deep-dive.md)
- [Valuation And DCF Logic](./handbook/valuation-dcf-logic.md)
- [Valuation Task Breakdown](./handbook/valuation-task-breakdown.md)
- [Operations Runbook](./handbook/operations-runbook.md)
- [Quality And Verification](./handbook/quality-and-verification.md)

## Core

- [Design Docs](./design-docs/index.md)
- [Deterministic Valuation Workflow](./design-docs/deterministic-valuation-workflow.md)
- [Config Reference](./reference/config-reference.md)
- [GitHub Workflow](./reference/github-workflow.md)
- [Local Wiki Setup](./reference/local-wiki.md)
- [Plan Index](./plans/index.md)
- [Execution Plans](./exec-plans/index.md)

## Research And Product

- [Product Sense](./PRODUCT_SENSE.md)
- [Quality Score](./QUALITY_SCORE.md)
- [Plan Overview](./PLAN.md)
- [Legacy Plans](./PLANS.md)
- [Patrik's Notes](./Patrik'sNotes.md)

## Documentation Direction

Use this structure going forward:
- `docs/handbook/` for operator and engineer how-to docs
- `docs/design-docs/` for architecture and system behavior
- `docs/reference/` for stable operator references and configuration docs
- `docs/plans/` for scoped implementation plans
- `docs/exec-plans/` for active/completed execution tracking

If a document explains how the system works today, it belongs in `handbook`, `design-docs`, or `reference`. If it explains what to build next, it belongs in `plans`.

## Local docs preview

Run `python -m mkdocs serve` from the repository root to view this folder as a local wiki.

