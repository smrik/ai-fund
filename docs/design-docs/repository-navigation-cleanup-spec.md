# Repository Navigation Cleanup Specification

| Field | Value |
| --- | --- |
| Status | Approved design |
| Date | 2026-08-05 |
| Vision decisions | 10, 11, 12, 13, and 14 |
| Branch | `codex/repository-navigation-cleanup` |

## Goal

Make the repository easy to understand in analyst-workflow order.

Do not move files that run the system. Do not break the working MSFT process.

The repository must give clear answers to these questions:

1. Which workflow step am I in?
2. Which folder contains this step?
3. Is this file an input, saved data, a template, or an output?
4. Where is the main CIQ Standard template?
5. Where does the system put a refreshed workbook?
6. Who makes each type of decision?

## Product Fit

This work supports the weekly process in Vision Decision 12. It makes the repository easier to use.

This work also supports Vision Decisions 13 and 14. The documentation must show the correct analysis order.

The documentation must also show these roles:

- Code gets data and does repeatable calculations.
- LLM agents study evidence and propose future assumptions.
- The PM approves, changes, rejects, or delays each proposal.

## Workflow Map

Use this workflow in the repository guide:

```text
01 Get data
02 Build the reported history and current-state model
03 Analyze the business and industry
04 Propose changes to forecast inputs
05 Run the DCF and comparable-company valuation
06 Review decisions and outputs as PM
```

The numbers show the analysis order. They are not Python package names.

Keep the current Python package paths.

## Design

### 1. Keep Working Paths

Do not move these folders in this change:

- `config/`
- `db/`
- `ciq/`
- `api/`
- `frontend/`
- `src/`

Do not delete `dashboard/`, `ibkr/`, `skills/`, tests, workbooks, or root policy files.

This rule keeps current imports, commands, tests, and CI jobs working.

### 2. Put The Workflow First

Update `docs/learn-codebase.md`. Put the six workflow steps near the start.

Give this information for each step:

- its purpose
- its main folders
- its main input
- its main output
- its owner
- the next step.

The owner is deterministic code, an LLM agent, or the PM.

Keep the detailed folder guide after the workflow map.

### 3. Add Folder Guides

Add these short files:

- `src/README.md`
- `data/README.md`
- `ciq/README.md`
- `templates/README.md`

Each file must answer three questions:

1. What belongs in this folder?
2. What does not belong in this folder?
3. Which detailed document gives more information?

Do not copy large parts of other documents into these files.

### 4. Use The Same Storage Terms

Use the terms in this table in all changed documents:

| Path | Purpose |
| --- | --- |
| `ciq/templates/ciq_cleandata.xlsx` | Main CIQ Standard source template |
| `ciq/templates/financials_input.json` | Power Query control file for ticker, date, and currency |
| `data/exports/{TICKER}_Standard.xlsx` | Refreshed CIQ workbook for database loading |
| `data/alpha_pod.db` | Saved local data and the main database input |
| `templates/` | Templates for valuation and PM review workbooks |
| `data/exports/generated/` | Generated files for PM review |
| `output/` | Generated run records, evidence packets, and diagnostic files |

Do not move `ciq/templates/financials_input.json`.

The workbook reads this fixed path:

```text
C:\Projects\03-Finance\ai-fund\ciq\templates\financials_input.json
```

A path change will break the current Excel refresh process.

### 5. Correct Old LLM Descriptions

Some documents say that LLM agents only write comments or summaries. This description is incorrect.

Use this description:

- Deterministic code gets facts, prepares evidence, and does repeatable calculations.
- LLM agents study the evidence and propose future assumptions.
- The PM decides if the system can use each proposal.
- Deterministic code uses approved assumptions in the valuation.

Do not change financial rules or system behavior in this work.

## Other Options

### Fix The Prototype Branch

Do not use this option for the first pull request.

The `codex/my-task` branch has a useful folder model. It also has hundreds of incomplete deletions and file moves.

### Move All Packages Now

Do not use this option for the first pull request.

This option requires changes to imports, scripts, tests, CI jobs, documentation, and Excel paths.

### Improve Navigation First

Use this option.

It keeps the working system stable. It also gives future changes a clear set of terms.

## Not In This Work

- Do not move or rename Python packages.
- Do not move the CIQ control file or CIQ source template.
- Do not change database tables or valuation calculations.
- Do not change agent prompts or PM Queue behavior.
- Do not delete old user interfaces or bundled skills.
- Do not add numbered source folders.
- Do not reorganize generated files.
- Do not fix unrelated problems.

## Checks

The work is complete when all these statements are true:

1. `docs/learn-codebase.md` shows the six workflow steps and their repository paths.
2. `src/`, `data/`, `ciq/`, and `templates/` each have a short README file.
3. All changed documents use the storage terms in this specification.
4. The change does not move or delete a working file.
5. The change does not modify Python, TypeScript, YAML, JSON, or workbook behavior.
6. `mkdocs build --strict` passes.
7. Pre-commit passes for all changed files.
8. The architecture tests pass.

## Later Work

Use this folder guide during a real MSFT run. Record each remaining navigation problem.

A later pull request can move one related set of files. Each move must have its own tests.

Keep `codex/my-task` as a visual example. Do not use it as the code base for this work.
