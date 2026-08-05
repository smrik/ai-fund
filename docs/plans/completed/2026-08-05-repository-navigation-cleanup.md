# Repository Navigation Cleanup

| Field | Value |
| --- | --- |
| Status | Complete |
| Date | 2026-08-05 |
| Vision decisions | 10, 11, 12, 13, and 14 |

## Goal

Make the repository easy to follow in analyst-workflow order.

Keep all working paths and system behavior unchanged.

## Completed Work

- Added the six-step workflow to `docs/learn-codebase.md`.
- Added short guides to `src/`, `data/`, `ciq/`, and `templates/`.
- Shortened the storage guide and docs home.
- Marked the main CIQ and PM review templates.
- Corrected old text about LLM agent roles.
- Added simple-English rules to `AGENTS.md` and `CLAUDE.md`.
- Removed unsafe advice to delete all of `data/exports/`.
- Marked the workflow as a selected-ticker workflow after screening.
- Added the saved CIQ archive to the storage map.

## Checks

| Check | Result |
| --- | --- |
| Changed-file review | Only Markdown and approved agent instruction files changed |
| `mkdocs build --strict` | Passed with a separate temporary output folder |
| Architecture tests | 4 passed |
| Pre-commit | All hooks passed |

The local `site/` folder had a Windows permission error. The strict build passed in a new temporary folder.

## Result

The repository now shows this order:

```text
Get data
  -> Build the current-state model
  -> Analyze the business and industry
  -> Propose forecast inputs
  -> Run DCF and comps
  -> Review as PM
```

The change did not move or delete a working file.
