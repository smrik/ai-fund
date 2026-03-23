# Thesis Tracker V2: PM Cockpit

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

The repository's checked-in planning guide is [docs/PLANS.md](../PLANS.md). This plan served as the sole canonical active plan for this tranche during execution and is now the completed implementation record.

## Purpose / Big Picture

The original dossier thesis tracker proved that archive-backed thesis state, PM tracker state, and catalyst state could all be stored. It did not provide a good operating workflow. The page behaved like a thin admin form over raw JSON: current stance had to be inferred manually, pillar state was mostly unused, catalyst editing was one row at a time, and decisions or reviews felt disconnected from the thesis context.

After this tranche, `Deep Dive -> Thesis Tracker` should behave like a PM cockpit for a single ticker. The PM should be able to open a name and immediately see current stance, what changed since the last snapshot, pillar health, catalyst status, continuity from recent decisions and reviews, and the current diligence queue. The user-visible proof is loading IBM in the dashboard, opening the tracker, updating overview state, updating multiple pillars in one pass, updating catalyst statuses in one pass, refreshing the app, and seeing the tracker persist without mutating archived report evidence.

## Progress

- [x] (2026-03-23 13:25 +01:00) Re-read `.agent/session-state.md`, `docs/PLANS.md`, the dossier handbook, the future roadmap, and the current tracker code in `src/stage_04_pipeline/dossier_view.py` and `dashboard/deep_dive_sections.py`.
- [x] (2026-03-23 13:32 +01:00) Confirmed the current tracker mismatch: raw `st.json(...)` output, minimal diffing, one-catalyst-at-a-time editing, and no effective use of `pillar_states_json`.
- [x] (2026-03-23 13:44 +01:00) Wrote the failing tracker-v2 tests in `tests/test_dossier_thesis_tracker.py` and `tests/test_dashboard_thesis_tracker.py` to lock the cockpit contract, legacy shim behavior, and dashboard source expectations.
- [x] (2026-03-23 14:02 +01:00) Replaced the thin diff builder with `build_thesis_tracker_view(...)`, added normalized cockpit blocks for stance/change/pillars/catalysts/continuity/queue, and kept `build_thesis_diff_view(...)` as a compatibility shim.
- [x] (2026-03-23 14:18 +01:00) Rebuilt `render_thesis_tracker(...)` into a cockpit layout with summary header, what-changed panel, diligence queue, batch overview save, batch pillar save, batch catalyst save, and read-only continuity tab.
- [x] (2026-03-23 14:29 +01:00) Updated `.gitignore`, refreshed the dossier handbook, ran focused tracker/dashboard pytest and compile verification, and recorded the environment-level pytest temp-dir cleanup blocker for broader suites.
- [x] (2026-03-23 14:56 +01:00) Applied post-implementation review fixes: stabilized fallback tracker matching by title slug, corrected legacy single-snapshot shim semantics, added explicit reruns after tracker saves, and extended tracker tests to cover those cases.

## Surprises & Discoveries

- Observation: the current schema already contained almost everything needed for a much better tracker.
  Evidence: `dossier_tracker_state` already had `pillar_states_json` and `open_questions_json`, while `dossier_catalysts` already stored status, priority, date/window fields, reason text, and evidence metadata. The main problem was view-model and UI quality, not missing tables.

- Observation: the existing tracker UI was dropping PM nuance even though the persistence layer could hold it.
  Evidence: the old `render_thesis_tracker(...)` saved `pillar_states_json` as `{}` on every tracker-state save and overwrote `open_questions_json` directly from `memo.open_questions`.

- Observation: pytest temp-dir behavior is still unreliable in this Windows environment.
  Evidence: broader runs using pytest temp directories still hit `PermissionError: [WinError 5] Zugriff verweigert` during temp-root setup or cleanup. Focused tracker tests were rewritten to use an in-memory SQLite fixture instead, and broader runs with `--basetemp=.pytest-tmp` still produced cleanup warnings/errors outside the touched code.

- Observation: the first tracker-v2 pass still had continuity bugs even though the focused payload/UI looked correct.
  Evidence: independent review found that fallback IDs were not stable enough across legacy-to-structured snapshot transitions, the legacy diff shim reported false changes for single-snapshot histories, and Streamlit saves could leave the visible tracker state stale until another interaction forced a rerun.

## Decision Log

- Decision: make this a UX-first tracker tranche and avoid schema expansion.
  Rationale: the product problem was workflow quality, not persistence capability. Reusing the existing archive/tracker/catalyst/decision/review/checkpoint tables delivered most of the value with much lower risk.
  Date/Author: 2026-03-23 / Codex

- Decision: `build_thesis_tracker_view(...)` is now the primary tracker builder and `build_thesis_diff_view(...)` remains only as a compatibility shim.
  Rationale: the dashboard needed a richer normalized contract, but older tests and adjacent callers could still rely on the legacy shape during migration.
  Date/Author: 2026-03-23 / Codex

- Decision: open questions in the tracker remain PM-owned current state, not a union of all historical archive questions.
  Rationale: the tracker should reflect the current diligence queue, while archive deltas already preserve what changed historically.
  Date/Author: 2026-03-23 / Codex

- Decision: continuity from recent decisions, reviews, and checkpoints should be embedded into the tracker as read-only summaries rather than turning the tracker into a full journal editor.
  Rationale: this preserves context and continuity on one page without collapsing the boundaries between tracker, decision log, and review log.
  Date/Author: 2026-03-23 / Codex

- Decision: preserve PM pillar and catalyst continuity across legacy-to-structured snapshot transitions by matching on stable title slugs when exact IDs do not line up.
  Rationale: exact archive IDs are not always present or stable in older snapshots, and the tracker cannot silently drop PM state when a later archived memo becomes more structured.
  Date/Author: 2026-03-23 / Codex

## Outcomes & Retrospective

- Outcome: complete. The tracker now behaves like a PM cockpit rather than a raw state dump.

- Backend outcome: `src/stage_04_pipeline/dossier_view.py` now produces a normalized tracker payload with:
  - `stance`
  - `what_changed`
  - `pillar_board`
  - `catalyst_board`
  - `continuity`
  - `next_queue`
  - `audit_flags`
  while preserving archive immutability and keeping the old diff builder as a shim.

- UI outcome: `dashboard/deep_dive_sections.py` now renders:
  - a summary header
  - `What Changed Since Last Snapshot`
  - `Next Diligence Queue`
  - batch overview editing
  - batch pillar editing
  - batch catalyst editing
  - read-only continuity summaries
  and no longer emits raw `st.json(...)` blocks for tracker state or diff payloads.

- Verification outcome: focused tracker and dashboard verification passed.

- Residual issue: broader dossier suites that rely on pytest temp-dir behavior remain partially blocked by the local environment’s `WinError 5` temp-root cleanup problem. That is recorded as an environment issue rather than a regression in the tracker-v2 code.

## Context and Orientation

The dossier system already existed before this tranche. `src/stage_04_pipeline/dossier_view.py` was responsible for building dashboard-facing dossier payloads. `dashboard/deep_dive_sections.py` rendered the Streamlit `Deep Dive` surfaces. `dossier_tracker_state` stored one current PM tracker row per ticker, and `dossier_catalysts` stored one current row per tracked catalyst. Archived memo snapshots continued to live in `pipeline_report_archive`.

In this plan, “PM cockpit” means a tracker page that helps the PM answer five practical questions quickly:

1. What is my current stance?
2. What changed since the last archived run?
3. Are my thesis pillars intact or weakening?
4. Which catalysts matter now, and what status are they in?
5. What should I monitor next?

The tracker still does not rewrite deterministic valuation logic. It is a judgment and memory surface layered on top of immutable archive evidence.

## Plan of Work

First, lock the desired behavior with tests. Expand the tracker tests so they assert the new cockpit payload, empty-history behavior, legacy diff-shim behavior, and dashboard-level structural expectations. Use an in-memory SQLite setup to avoid the current Windows temp-dir issues.

Second, replace the old thin tracker builder in `src/stage_04_pipeline/dossier_view.py` with a normalized cockpit view builder. It should load the latest and prior archive snapshots, current tracker state, tracked catalysts, latest checkpoint, latest decision, and latest review; normalize them into one view model; and keep `build_thesis_diff_view(...)` as a compatibility wrapper.

Third, replace the old Streamlit tracker rendering in `dashboard/deep_dive_sections.py`. Remove raw JSON output, batch overview state into one form, make pillar state actually editable through `pillar_states_json`, move catalyst editing into a board-style batch surface, and surface continuity summaries inline.

Fourth, update the handbook and plan registry so the docs match the shipped behavior, then run the focused verification bundle and move the plan to `completed/`.

## Concrete Steps

Run commands from the repository root, `C:\Projects\03-Finance\ai-fund`.

Focused tracker verification:

    python -m pytest tests/test_dossier_thesis_tracker.py tests/test_dashboard_thesis_tracker.py -q --basetemp=.pytest-tmp

Focused Deep Dive/dashboard regression bundle:

    python -m pytest tests/test_dossier_thesis_tracker.py tests/test_dashboard_thesis_tracker.py tests/test_dashboard_render_contracts.py tests/test_dashboard_deep_dive_refactor.py -q --basetemp=.pytest-tmp

Compile check:

    python -m py_compile src/stage_04_pipeline/dossier_view.py dashboard/deep_dive_sections.py

Actual verification run in this session:

    python -m pytest tests/test_dossier_thesis_tracker.py tests/test_dashboard_thesis_tracker.py -q --basetemp=.pytest-tmp
    python -m pytest tests/test_dossier_thesis_tracker.py tests/test_dashboard_thesis_tracker.py tests/test_dashboard_render_contracts.py tests/test_dashboard_deep_dive_refactor.py -q --basetemp=.pytest-tmp
    python -m py_compile src/stage_04_pipeline/dossier_view.py dashboard/deep_dive_sections.py

## Validation and Acceptance

This tranche is accepted only when the tracker is materially easier to operate as a PM surface. At minimum:

- the tracker shows current stance without raw JSON
- the tracker explains what changed since the last snapshot in structured prose-like blocks
- pillar status and notes can be saved in one pass
- catalyst statuses and timing can be saved in one pass
- open questions remain PM-owned state rather than being blindly overwritten from the latest memo
- continuity from recent decisions, reviews, and checkpoints is visible on the tracker page
- archived report snapshots remain unchanged

Actual completion evidence:

- `python -m pytest tests/test_dossier_thesis_tracker.py tests/test_dashboard_thesis_tracker.py -q --basetemp=.pytest-tmp` returned `4 passed`.
- `python -m pytest tests/test_dossier_thesis_tracker.py tests/test_dashboard_thesis_tracker.py tests/test_dashboard_render_contracts.py tests/test_dashboard_deep_dive_refactor.py -q --basetemp=.pytest-tmp` returned `12 passed` with only the pre-existing pytest cache warning.
- `python -m py_compile src/stage_04_pipeline/dossier_view.py dashboard/deep_dive_sections.py` exited with code `0`.

## Idempotence and Recovery

This work is additive at the view-model and UI layer. If a step fails, keep the new tests, revert only the in-progress tracker-builder or tracker-renderer edits, and rerun the focused tracker suite before continuing. Do not alter the dossier schema in this tranche, and do not mutate historical archive rows.

The pytest temp-dir issue is environmental. If broader verification fails during temp-root setup or cleanup, use the focused in-memory tracker tests and document the blocker rather than forcing unrelated code changes into this tranche.

## Artifacts and Notes

The old tracker surface that motivated this work consisted of:

    - three top metrics
    - `st.json(thesis_view["snapshot_diff"])`
    - optional `st.json(current_tracker_state)`
    - a simple catalysts table
    - one overview form
    - one single-catalyst status form

The shipped tracker replaces that with:

    - summary header
    - what-changed panel
    - diligence queue
    - pillar board
    - catalyst board
    - continuity tab

## Interfaces and Dependencies

At the end of this tranche:

- `src/stage_04_pipeline/dossier_view.py` must expose:
  - `build_thesis_tracker_view(...)`
  - `build_thesis_diff_view(...)` as a compatibility shim
  - `build_model_checkpoint_view(...)`
  - `build_publishable_memo_context(...)`
- `dashboard/deep_dive_sections.py` must render the tracker from `build_thesis_tracker_view(...)`
- `dossier_tracker_state` remains the persistence layer for current PM tracker state
- `dossier_catalysts` remains the persistence layer for current catalyst state
- `pipeline_report_archive` remains immutable evidence

Revision note, 2026-03-23 / Codex: Created this active ExecPlan for the tracker-v2 tranche and completed it in the same session, leaving this file as the final implementation record under `completed/`.
