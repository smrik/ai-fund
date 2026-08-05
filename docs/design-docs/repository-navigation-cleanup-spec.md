# Repository Navigation Cleanup

| Field | Value |
| --- | --- |
| Status | Approved |
| Date | 2026-08-05 |
| Vision decisions | 10, 11, 12, 13, and 14 |

## Goal

Make the repository easy to follow in analyst-workflow order.

Do not move working files. Do not change system behavior.

## Workflow

```text
01 Get data
02 Build reported history and the current-state model
03 Analyze the business and industry
04 Propose changes to forecast inputs
05 Run DCF and comparable-company valuation
06 Review decisions and outputs as PM
```

The numbers show analysis order. They are not Python package names.

## Roles

- Deterministic code gets facts and does repeatable calculations.
- LLM agents study evidence and propose future assumptions.
- The PM approves, changes, rejects, or delays each proposal.
- Deterministic code uses approved assumptions in the valuation.

## Changes

1. Put the six-step workflow in `docs/learn-codebase.md`.
2. Add short README files to `src/`, `data/`, `ciq/`, and `templates/`.
3. Use the same storage terms in all changed documents.
4. Correct old text that says LLM agents only write summaries.
5. Make the changed documents short and simple.

## Storage Terms

| Path | Purpose |
| --- | --- |
| `ciq/templates/ciq_cleandata.xlsx` | Main CIQ Standard source template |
| `ciq/templates/financials_input.json` | Power Query control file |
| `data/exports/{TICKER}_Standard.xlsx` | Refreshed CIQ workbook for database loading |
| `data/alpha_pod.db` | Main local SQLite database |
| `templates/ticker_review.xlsx` | Main PM review template |
| `data/exports/generated/` | Generated PM review files |
| `output/` | Generated run records and diagnostic files |

Power Query reads this fixed path:

```text
C:\Projects\03-Finance\ai-fund\ciq\templates\financials_input.json
```

Do not move this file in this work.

## Not In This Work

- Do not move or rename Python packages.
- Do not change database tables or valuation calculations.
- Do not change agent prompts or PM Queue behavior.
- Do not delete old user interfaces or bundled skills.
- Do not reorganize generated files.

The `codex/my-task` branch is a visual example. It is not the code base for this work.

## Checks

The work is complete when:

1. The six-step guide points to the correct repository paths.
2. The four folder guides point to the main documents.
3. No working file moves or changes behavior.
4. MkDocs passes in strict mode.
5. Pre-commit passes.
6. Architecture tests pass.
