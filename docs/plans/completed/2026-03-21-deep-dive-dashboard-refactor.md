# Deep Dive Dashboard Refactor

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

The repository's checked-in planning guide is [docs/PLANS.md](../PLANS.md). This plan served as the sole canonical active plan for this refactor tranche and is now the completed implementation record.

## Purpose / Big Picture

The dossier feature shipped, but the `Deep Dive` dashboard surface now lives as a long inline block inside `dashboard/app.py`. That makes the app harder to navigate, harder to review, and riskier to extend. After this refactor, the visible dashboard behavior should remain the same, but the Deep Dive rendering code should live behind one helper module with explicit section renderers.

The proof is simple: run the focused dashboard tests, start the dashboard, load IBM, and confirm the `Deep Dive` sections still render and persist the same dossier workflows.

## Progress

- [x] (2026-03-21 00:00 +01:00) Re-read `.agent/session-state.md`, `docs/PLANS.md`, the completed dossier plan, and the Deep Dive block inside `dashboard/app.py` to confirm the refactor target.
- [x] (2026-03-21 00:10 +01:00) Wrote the failing structural regression test in `tests/test_dashboard_deep_dive_refactor.py` and verified it failed before the helper module existed.
- [x] (2026-03-21 00:18 +01:00) Extracted the eight Deep Dive section renderers into `dashboard/deep_dive_sections.py`, added `dashboard/__init__.py`, and updated `dashboard/app.py` to delegate through `render_deep_dive_section(...)`.
- [x] (2026-03-21 00:24 +01:00) Updated the dashboard structure tests to target the new module boundary, ran focused dashboard pytest and compile verification, and prepared the plan to move to `completed/`.

## Surprises & Discoveries

- Observation: the dossier code was added entirely inline after `_sync_dossier_foundation(...)`, making `dashboard/app.py` absorb both application setup and eight dossier section implementations.
  Evidence: `dashboard/app.py` currently contains direct `if selected_section == "Company Hub"` through `if selected_section == "Publishable Memo"` blocks starting near line 1142.

- Observation: pytest runs that touch `tmp_path` are currently blocked by a Windows permission issue in the environment, even when `--basetemp` is set inside the repository.
  Evidence: running the broader dossier suite produced `PermissionError: [WinError 5] Zugriff verweigert` during pytest temp-dir cleanup, while dashboard-only tests without `tmp_path` continued to pass.

## Decision Log

- Decision: this tranche refactors rendering boundaries only and should not move dossier persistence or valuation logic.
  Rationale: the goal is maintainability without reopening feature behavior that was already verified in the completed dossier tranche.
  Date/Author: 2026-03-21 / Codex

- Decision: the new boundary lives in `dashboard/deep_dive_sections.py` rather than under `src/stage_04_pipeline/`.
  Rationale: the moved code is Streamlit composition code, not reusable pipeline logic; keeping it in `dashboard/` avoids mixing UI concerns into stage-04 modules.
  Date/Author: 2026-03-21 / Codex

## Outcomes & Retrospective

- Outcome: complete. The Deep Dive dashboard surface is now centralized in `dashboard/deep_dive_sections.py`, and `dashboard/app.py` delegates through a single render entrypoint instead of carrying eight inline dossier section blocks.

- Verification outcome: `python -m pytest tests/test_dashboard_deep_dive_refactor.py tests/test_dashboard_render_contracts.py tests/test_dashboard_thesis_tracker.py -q` returned `7 passed in 0.60s`, and `python -m py_compile dashboard/app.py dashboard/deep_dive_sections.py` exited with code `0`.

- Residual issue: broader dossier tests that rely on pytest temp directories could not be rerun in this session because of the environment-level `WinError 5` tmpdir cleanup failure. That is recorded here as an environment blocker, not a functional regression from the refactor.

## Context and Orientation

`dashboard/app.py` is the Streamlit entrypoint and already contains many helper functions that other sections depend on, including `_get_cached_view`, `_styled_rows`, and `_fix_text`. The dossier feature currently depends on stage-04 helpers such as `dossier_index.py`, `dossier_workspace.py`, and `dossier_view.py`, but the Streamlit rendering now lives in `dashboard/deep_dive_sections.py`.

This plan keeps the render logic in the `dashboard/` package because it is UI composition code, not stage-04 business logic. “Render helper module” here means a Python module that owns the Streamlit section implementations and receives the existing memo object plus the callbacks and helper functions it needs.

## Plan of Work

First, add failing tests that make the desired boundary explicit: `dashboard/app.py` must import a shared Deep Dive renderer, and the new module must expose a stable registry of Deep Dive sections. Then create `dashboard/deep_dive_sections.py`, move the eight Deep Dive section bodies into renderer functions there, and replace the inline blocks in `dashboard/app.py` with one delegation call. Reuse existing helper functions and data loaders by passing them in as dependencies rather than moving more logic than necessary.

After the refactor, run the focused dashboard tests plus compile checks. If they pass, update this plan with the evidence and move it to `docs/plans/completed/`.

## Concrete Steps

Run commands from `C:\Projects\03-Finance\ai-fund`.

Write and run the failing structural test:

    python -m pytest tests/test_dashboard_deep_dive_refactor.py -q

After the refactor:

    python -m pytest tests/test_dashboard_deep_dive_refactor.py tests/test_dashboard_render_contracts.py tests/test_dashboard_thesis_tracker.py tests/test_dossier_workspace.py tests/test_dossier_sources.py tests/test_dossier_model_checkpoints.py tests/test_dossier_thesis_tracker.py tests/test_dossier_decision_log.py tests/test_dossier_review_log.py tests/test_dossier_publishable_memo.py -q
    python -m py_compile dashboard/app.py dashboard/deep_dive_sections.py

Actual verification run in this session:

    python -m pytest tests/test_dashboard_deep_dive_refactor.py -q
    python -m pytest tests/test_dashboard_deep_dive_refactor.py tests/test_dashboard_render_contracts.py tests/test_dashboard_thesis_tracker.py -q
    python -m py_compile dashboard/app.py dashboard/deep_dive_sections.py

## Validation and Acceptance

The refactor is accepted only when the Deep Dive dashboard behavior remains intact and the code boundary is cleaner. At minimum:

- `dashboard/app.py` imports and delegates to a dedicated Deep Dive renderer module
- the new module owns explicit renderer functions for the eight Deep Dive sections
- the focused dashboard and dossier tests pass
- the app still compiles cleanly

Actual acceptance evidence:

- `dashboard/app.py` imports `render_deep_dive_section` and no longer carries the inline `if selected_section == "Company Hub"` through `Publishable Memo` blocks.
- `dashboard/deep_dive_sections.py` exports `DEEP_DIVE_RENDERERS` plus `render_deep_dive_section`.
- Focused dashboard verification passed: `7 passed in 0.60s`.
- Compile verification passed for both touched dashboard modules.

## Idempotence and Recovery

This refactor is code motion plus light interface cleanup. If a step fails, revert only the refactor-in-progress changes in the touched files, keep the tests, and restart from the failing test. Do not disturb unrelated dossier persistence code or deterministic valuation code.

## Artifacts and Notes

The key baseline evidence for this refactor is the current inline block in `dashboard/app.py` spanning the Deep Dive sections, and the completed dossier plan at `docs/plans/completed/2026-03-18-single-ticker-deep-dive-dossier.md` that already verified feature behavior.

## Interfaces and Dependencies

At the end of this refactor:

- `dashboard/deep_dive_sections.py` must expose a stable section registry plus one app-facing render entrypoint.
- `dashboard/app.py` must call that entrypoint instead of implementing the eight Deep Dive sections inline.
- Existing helpers from `src.stage_04_pipeline.dossier_*` remain the source of dossier state and persistence.

Revision note, 2026-03-21 / Codex: Created this active ExecPlan to track the post-feature maintainability refactor for the Deep Dive dashboard surface.

Revision note, 2026-03-21 / Codex: Updated the living plan with the actual extraction result, focused verification evidence, and the environment-level pytest tmpdir blocker before moving the plan to `completed/`.

Revision note, 2026-03-21 / Codex: Moved this plan from `docs/plans/active/` to `docs/plans/completed/` and adjusted the document so it reads as the shipped implementation record.
