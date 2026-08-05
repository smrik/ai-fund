# Repository Navigation Cleanup Specification

| Field | Value |
| --- | --- |
| Status | Approved design |
| Date | 2026-08-05 |
| Serves | Vision Decisions 10, 11, 12, 13, and 14 |
| Implementation branch | `codex/repository-navigation-cleanup` |

## Goal

Make the repository explain Alpha Pod in analyst-workflow order without moving runtime modules or
breaking the working MSFT weekly loop.

The first mergeable cleanup should let the PM answer these questions without hunting through the
tree:

1. What stage of the investment workflow am I looking at?
2. Which folder owns that stage?
3. Is this file an input, durable state, a template, or generated output?
4. What is the canonical CIQ Standard template and where does a refreshed workbook go?
5. Which layer authors assumptions, which layer executes them, and where does PM approval occur?

## Product And Architecture Fit

This work serves the real weekly loop in Vision Decision 12 by reducing navigation friction while
leaving the validated execution path unchanged. It serves Decisions 13 and 14 by documenting the
actual analytical sequence and correcting stale wording that limits the judgment layer to
narrative commentary.

The required workflow map is:

```text
01 Get data
02 Build reported-history and status-quo model
03 Analyze the business and industry
04 Propose forecast-driver adjustments
05 Run deterministic DCF and comparable-company valuation
06 Review decisions and exports as PM
```

This is an analyst-order map, not a proposal to make numbered Python packages. Existing importable
modules remain at their current paths.

## Design

### 1. Keep Runtime Modules Stable

The first cleanup does not relocate `config/`, `db/`, `ciq/`, `api/`, `frontend/`, or any package
under `src/`. It does not delete `dashboard/`, `ibkr/`, `skills/`, root governance files, tests, or
workbooks.

This conservative seam keeps existing imports, commands, CI configuration, and operator habits
working while the repository gains a clearer interface for human and agent navigation.

### 2. Make The Workflow The Primary Navigation Interface

Update `docs/learn-codebase.md` so its first map follows the six-stage analyst workflow. For every
stage, the map must name:

- the purpose in plain language;
- the canonical source folders;
- the principal input and output;
- the owning layer: deterministic, judgment, or PM;
- the next stage.

The guide must preserve the deeper folder-by-folder reference for readers who need implementation
detail.

### 3. Add Local Folder Signposts

Add concise README files at the confusing entry points:

- `src/README.md`
- `data/README.md`
- `ciq/README.md`
- `templates/README.md`

Each README is a signpost, not a second manual. It must point to the canonical detailed docs and
answer only what belongs here, what does not, and where the adjacent workflow stage lives.

### 4. Use One Storage Vocabulary

Documentation must consistently distinguish these roles:

| Path | Role |
| --- | --- |
| `ciq/templates/ciq_cleandata.xlsx` | Canonical CIQ Standard source template |
| `ciq/templates/financials_input.json` | Power Query ticker/date/currency control file |
| `data/exports/{TICKER}_Standard.xlsx` | Refreshed vendor-data workbook used for SQLite ingestion |
| `data/alpha_pod.db` | Durable local operational state and canonical DB boundary |
| `templates/` | PM-facing valuation and review workbook templates |
| `data/exports/generated/` | Generated PM-facing export bundles |
| `output/` | Generated run diagnostics, packets, and other workflow artifacts |

The Power Query control file must remain at `ciq/templates/financials_input.json`. The current
workbook reads the fixed local path
`C:\Projects\03-Finance\ai-fund\ciq\templates\financials_input.json`; relocating it is outside
this PR because it would break the validated Excel refresh path.

### 5. Correct Stale Judgment-Layer Wording

Navigation documentation must match Vision Decision 13:

- deterministic code ingests facts, marshals evidence, and executes reproducible calculations;
- the judgment layer reasons over qualitative and quantitative evidence and authors proposed
  forward-looking assumptions;
- the PM approves, edits, rejects, or defers proposals through the PM Decision Queue;
- only approved assumptions may affect deterministic valuation execution.

The cleanup must not change finance semantics or runtime behavior while correcting this wording.

## Alternatives Considered

### Repair The Prototype Branch In Place

Rejected for the first PR. `codex/my-task` combines a useful mental model with hundreds of tracked
deletions and incomplete relocations. Repairing it would make scope difficult to audit and risk
losing working behavior.

### Relocate All Packages Now

Deferred. A physical relocation could eventually improve locality, but it would require updating
Python imports, packaging, scripts, tests, CI, documentation, Excel paths, and operator commands in
one wide change. That does not serve the immediate goal of running the weekly loop reliably.

### Navigation-First Cleanup

Selected. It captures the prototype's useful workflow model, is independently valuable, and
creates a stable vocabulary for later module-by-module refactors.

## Non-Goals

- Renaming or moving Python packages.
- Moving the CIQ Power Query control file or Standard workbook template.
- Changing database schemas, valuation calculations, agent prompts, or PM Queue behavior.
- Deleting legacy surfaces or bundled skills.
- Creating numbered source directories.
- Reorganizing generated files on disk.
- Fixing unrelated documentation or technical debt.

## Verification

The implementation is acceptable when:

1. A reader can start at `docs/learn-codebase.md` and trace the six-stage workflow to concrete
   repository paths.
2. `src/`, `data/`, `ciq/`, and `templates/` each contain a concise README pointing to canonical
   documentation.
3. The CIQ template, control, staged workbook, database, review template, and generated-export
   roles are named consistently.
4. No existing runtime file is relocated or deleted.
5. No Python, TypeScript, YAML, JSON, or workbook behavior changes.
6. `mkdocs build --strict` passes.
7. Pre-commit passes for the changed files.
8. Targeted architecture-boundary tests pass.

## Follow-On Work

After this PR has been used during a real MSFT run, navigation friction should be logged as
specific evidence. A later PR may then deepen one module or relocate one cohesive slice at a time.
The `codex/my-task` prototype remains a visual exploration aid; it is not an implementation base.
