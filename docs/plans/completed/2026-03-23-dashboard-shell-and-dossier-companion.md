# Dashboard Shell And Dossier Companion Workspace Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the current fragmented dashboard IA with a five-tab shell and a persistent dossier companion rail that supports scratch capture and durable note blocks.

**Architecture:** The app shell will collapse into five top-level routes: `Overview`, `Valuation`, `Market`, `Research`, and `Audit`. The existing dossier system remains the canonical durable research layer, but it will stop being a first-class destination. Instead, a global right-rail companion surface will expose a scratchpad plus a durable note-block notebook backed by SQLite and linked to current page context.

**Tech Stack:** Streamlit, SQLite, existing dossier workspace/index/view helpers, report archive, pytest.

---

## Scope

This tranche implements:

- top-of-page dashboard routing with five primary tabs
- `Overview` cockpit with drilldown actions
- `Research` as a working research board instead of fragmented dossier pages
- `Audit` as the merged operational/evidence/export page
- global dossier companion rail with:
  - scratchpad
  - note-block promotion
  - notebook grouped by type and sorted chronologically within type
- handbook and plan updates

This tranche does not attempt a full redesign of every detailed valuation or market sub-surface. Those will be regrouped under the new shell, not re-authored from first principles.

## Planned Files

**Create:**
- `docs/plans/active/2026-03-23-dashboard-shell-and-dossier-companion.md`

**Modify:**
- `docs/plans/index.md`
- `docs/handbook/deep-dive-dossier.md`
- `db/schema.py`
- `db/loader.py`
- `src/stage_04_pipeline/dossier_index.py`
- `src/stage_04_pipeline/dossier_view.py`
- `dashboard/design_system.py`
- `dashboard/app.py`
- `dashboard/deep_dive_sections.py`
- `tests/test_dashboard_render_contracts.py`
- `tests/test_dossier_thesis_tracker.py`
- `tests/test_dossier_workspace.py`
- add focused note-block tests if needed

## Milestones

1. Add durable dossier note-block persistence and view helpers.
2. Add the global dossier companion rail with scratchpad and promotion flow.
3. Replace the current workspace/section IA with the five-tab shell.
4. Recompose page groupings into `Overview`, `Valuation`, `Market`, `Research`, and `Audit`.
5. Update handbook and plan registry, then verify with focused tests and compile checks.

## Acceptance

- The dashboard shows five primary top tabs: `Overview`, `Valuation`, `Market`, `Research`, `Audit`.
- The old `Deep Dive` and `Ops` top-level groupings are gone from the main shell.
- A dossier companion rail can be opened from any loaded-ticker page.
- Scratchpad text can be promoted into a durable note block.
- Durable note blocks are grouped by type and sorted newest-first within a type.
- Each promoted block carries page-context metadata.
- The `Research` page renders as a working board rather than a fragmented section list.
- Focused dashboard/dossier tests pass.
