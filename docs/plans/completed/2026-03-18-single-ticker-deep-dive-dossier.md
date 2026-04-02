# Single-Ticker Deep Dive Dossier System

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

The repository's checked-in planning guide is [docs/PLANS.md](../../PLANS.md). This plan was derived from the future roadmap in [../future/2026-03-18-dashboard-ai-investing-feature-roadmap.md](../future/2026-03-18-dashboard-ai-investing-feature-roadmap.md), served as the sole canonical active plan for this tranche during execution, and is now the completed implementation record.

## Purpose / Big Picture

Alpha Pod already produces a strong single-run research memo, but it does not yet preserve a full deep-dive dossier for one company. After this change, the PM should be able to initialize a durable ticker workspace, link the live Excel model and evidence files, preserve source IDs, record model checkpoints, track thesis and catalysts over time, keep a PM decision and review journal, and maintain a publishable memo draft without mixing in private work.

The user-visible proof is straightforward: start the dashboard, load IBM, navigate to `Deep Dive`, initialize the dossier, register a workbook and at least one source, create a checkpoint, record a decision and a review, and confirm that those artifacts persist across reloads while the deterministic valuation engine remains unchanged.

## Progress

- [x] (2026-03-18 21:29 +01:00) Re-read the current planning registry, `docs/PLANS.md`, the roadmap source, `config/config.yaml`, `db/schema.py`, `db/loader.py`, `dashboard/app.py`, `report_archive.py`, `estimate_tracker.py`, `ICMemo`, and `ThesisAgent` to confirm the actual extension points.
- [x] (2026-03-18 21:29 +01:00) Created this canonical active ExecPlan and queued the required registry/docs updates for `docs/plans/index.md`, `docs/plans/active/README.md`, and `mkdocs.yml`.
- [x] (2026-03-18 21:37 +01:00) Milestone 0 completed: registered this plan in `docs/plans/index.md`, updated `docs/plans/active/README.md`, and added the active/future links to `mkdocs.yml`.
- [x] (2026-03-18 21:42 +01:00) Milestone 1 completed: added dossier foundation tests, `research_workspace` config, `dossier_workspace`/`dossier_index`/`dossier_models`, the initial `dossier_profiles` and `dossier_sections` tables, and the `Deep Dive -> Company Hub` dashboard surface; verified the focused tests and compile pass.
- [x] (2026-03-18 22:05 +01:00) Milestone 2 completed: added `dossier_sources` and `dossier_artifacts`, source-note creation under `Notes/Sources/`, artifact-path normalization, source/artifact CRUD helpers, and the `Deep Dive -> Sources` dashboard surface.
- [x] (2026-03-18 22:12 +01:00) Milestone 3 completed: added `dossier_model_checkpoints`, dossier view builders, the `Deep Dive -> Model & Valuation` dashboard surface, and checkpoint persistence tied to current report state.
- [x] (2026-03-18 22:21 +01:00) Milestone 4 completed: extended `ICMemo` and `ThesisAgent` with structured thesis fields, added `dossier_tracker_state` and `dossier_catalysts`, and shipped the `Deep Dive -> Thesis Tracker` UI with archive-backed diffing and PM tracker state.
- [x] (2026-03-18 22:28 +01:00) Milestone 5 completed: added `dossier_decision_log` and `dossier_review_log`, wired `Decision Log` and `Review Log` persistence, and exposed both sections in the dashboard.
- [x] (2026-03-18 22:38 +01:00) Milestone 6 completed: added the publishable memo workspace and handbook page, ignored generated dossier roots in `.gitignore`, ran the focused compile/test bundle, verified the full IBM Deep Dive flow live in Streamlit with Playwright, and prepared the plan to move from `active/` to `completed/`.

## Surprises & Discoveries

- Observation: the repo does not contain `.agent/PLANS.md` even though `AGENTS.md` mentions it.
  Evidence: `Get-Content .agent/PLANS.md` returned `Cannot find path ... .agent\\PLANS.md`.

- Observation: the real checked-in planning rules live in `docs/PLANS.md`, and the canonical plan registry already points there.
  Evidence: `docs/PLANS.md` defines `docs/plans/` as the canonical planning system, and `docs/plans/index.md` currently shows `No active canonical plans at the moment`.

- Observation: the dashboard has a single `SECTION_GROUPS` map and uses `st.segmented_control` for top-level and section-level navigation.
  Evidence: `dashboard/app.py` lines 997-1017 define the groups and selection controls, making a new top-level `Deep Dive` group the cleanest insertion point.

- Observation: archive and revision primitives already exist and are sufficient to support a first dossier implementation without new external services.
  Evidence: `src/stage_04_pipeline/report_archive.py` persists memo/dashboard snapshots, and `src/stage_00_data/estimate_tracker.py` already exposes revision-history logic over `estimate_history`.

- Observation: `dashboard/app.py` still contained several `use_container_width=` call sites despite the earlier remediation tranche claiming the deprecation cleanup had landed.
  Evidence: `rg -n "use_container_width=" dashboard/app.py` returned matches at IV history, portfolio-risk, macro, and factor-exposure blocks before the Milestone 1 patch removed them.

- Observation: the local Python environment could not run the new memo/thesis tests until the `pydantic` and `pydantic-core` versions were realigned.
  Evidence: importing `ICMemo` initially failed because local `pydantic 2.12.5` expected `pydantic-core 2.41.5` while the environment had `2.42.0`; installing `pydantic-core==2.41.5` resolved the mismatch and the focused test bundle then passed.

- Observation: the live Streamlit app needed `openpyxl` to start cleanly in the current environment.
  Evidence: the first live app start failed on an import path until `openpyxl` was installed; the later `streamlit run dashboard/app.py --server.port 8504` session then served the full IBM dossier flow successfully.

- Observation: dossier initialization creates user working data under `data/dossiers/`, which should not remain as untracked repository noise.
  Evidence: after the first live IBM initialization, `git status --short` showed `?? data/dossiers/`; adding `data/dossiers/` to `.gitignore` removed the generated dossier workspace from repo status while preserving the local working files.

## Decision Log

- Decision: `docs/plans/active/2026-03-18-single-ticker-deep-dive-dossier.md` was the sole active implementation plan for this workstream during execution.
  Rationale: `docs/PLANS.md` requires one canonical planning system and one active implementation record rather than parallel live specs.
  Date/Author: 2026-03-18 / Codex

- Decision: V1 will use linked external artifacts rather than attempting native Excel or PDF embedding/editing.
  Rationale: this preserves Excel as the model engine, matches the user’s deep-dive framework, and avoids violating the repo’s data/computation/judgment boundary.
  Date/Author: 2026-03-18 / Codex

- Decision: the dossier will be implemented as file-backed Markdown notes plus SQLite indexing/state, not as a database-only knowledge store.
  Rationale: the user explicitly wants a durable, inspectable research system that can later support publication and external-file workflows.
  Date/Author: 2026-03-18 / Codex

- Decision: the first dossier slice seeds and re-indexes notes directly from the Streamlit app via `_sync_dossier_foundation(...)` rather than introducing a heavier service layer up front.
  Rationale: this keeps Milestone 1 minimal and testable while preserving a clean upgrade path into richer dossier view builders later in the plan.
  Date/Author: 2026-03-18 / Codex

- Decision: generated dossier workspaces under `data/dossiers/` should be treated as local runtime data and ignored by Git by default.
  Rationale: the dossier folders are PM working state created by the application, not source code; keeping them ignored prevents verification and everyday use from polluting repository status.
  Date/Author: 2026-03-18 / Codex

## Outcomes & Retrospective

- Milestone 0 outcome: complete. The repo now has one canonical active dossier plan and the docs/nav acknowledge it.

- Milestone 1 outcome: complete. A ticker can now initialize a file-backed dossier workspace, and the dashboard exposes the first Deep Dive surface for it.

- Milestone 2 outcome: complete. Sources, source notes, and linked artifacts are first-class dossier objects instead of ad hoc files outside the dashboard.

- Milestone 3 outcome: complete. The PM can register model and thesis versions against the current report state without copying the workbook into the database.

- Milestone 4 outcome: complete. Thesis memory now has both immutable archive evidence and current PM tracker state, which was the core product gap identified in the roadmap.

- Milestone 5 outcome: complete. The system now preserves what the PM did and what the PM learned later, instead of treating each ticker run as an isolated memo.

- Milestone 6 outcome: complete. The dossier now supports a publishable memo draft, handbook guidance, and a live end-to-end IBM workflow covering initialization, source linking, checkpointing, thesis tracking, decision logging, review logging, and memo editing.

- Final retrospective: the feature landed as a real dossier system rather than a narrow tracker tab. The main remaining architectural debt is that dossier rendering logic now occupies a large block of `dashboard/app.py`, and the new `ICMemo` structured-thesis types live under a stage-04 template module rather than a more neutral shared-model path. Those are maintainability concerns, not blockers to the shipped behavior.

## Context and Orientation

The existing repository already has strong pieces of the final dossier system. `src/stage_02_valuation/templates/ic_memo.py` defines the final memo contract but lacks structured thesis pillars and structured catalysts. `src/stage_03_judgment/thesis_agent.py` produces the memo. `src/stage_04_pipeline/report_archive.py` archives memo snapshots and selected dashboard views. `src/stage_00_data/estimate_tracker.py` stores and reads analyst revision history. `dashboard/app.py` renders the dashboard and currently organizes it into `Research`, `Valuation`, `Filings`, `Market Intel`, and `Ops`. `db/schema.py` owns all table creation in one idempotent script, and `db/loader.py` owns insert/upsert helpers.

The missing layer is the dossier itself: a file-backed company workspace with notes, sources, artifacts, checkpoints, thesis tracking, decisions, reviews, and a publishable memo surface.

Throughout this plan, “dossier” means one company-specific research workspace rooted under `data/dossiers/`. “Linked external artifacts” means the workbook, PDFs, decks, and transcripts remain normal files on disk and Alpha Pod stores stable links and metadata for them rather than ingesting them wholesale into the database. “Tracker state” means the current PM-maintained thesis/catalyst state, while archived report snapshots remain immutable historical evidence.

## Plan of Work

Milestone 0 updates the planning system itself. Create this active plan, register it in `docs/plans/index.md`, update `docs/plans/active/README.md`, and update `mkdocs.yml` so the documentation reflects the active/future/completed split correctly.

Milestone 1 creates the dossier foundation. Add `research_workspace` defaults to `config/config.yaml` and export them through `config/__init__.py`. Create `src/stage_04_pipeline/templates/dossier_models.py`, `src/stage_04_pipeline/dossier_workspace.py`, and `src/stage_04_pipeline/dossier_index.py`. Add the initial tables for `dossier_profiles` and `dossier_sections` in `db/schema.py`, plus matching insert/upsert/list helpers in `db/loader.py`. Wire a minimal `Deep Dive -> Company Hub` section in `dashboard/app.py` that can initialize the dossier and show the generated paths and note slugs.

Milestone 2 adds the evidence layer. Extend the schema and loader with `dossier_sources` and `dossier_artifacts`, create helpers to normalize external paths and create source notes under `Notes/Sources/`, and add a `Sources` dashboard section for registering and listing sources and artifacts.

Milestone 3 adds model checkpoints. Extend the schema and loader with `dossier_model_checkpoints`, build a lightweight `dossier_view.py` aggregator, and add a `Model & Valuation` section that registers model versions, links exports, and stores a checkpoint tied to the latest memo/archive state.

Milestone 4 absorbs the thesis tracker. Extend `ICMemo` and `ThesisAgent` with structured thesis pillars and catalysts in a backward-compatible way, add `dossier_tracker_state` and `dossier_catalysts`, and render a `Thesis Tracker` section that shows latest-versus-prior thesis changes and PM tracker state.

Milestone 5 adds the PM learning layer. Extend the schema and loader with `dossier_decision_log` and `dossier_review_log`, then wire `Decision Log` and `Review Log` sections in the dashboard.

Milestone 6 adds the outward-facing memo layer and closes the loop. Create `docs/handbook/deep-dive-dossier.md`, add `Publishable Memo` support in the dashboard and dossier view helpers, run the full focused test/compile bundle, record the actual evidence in this plan, and then move the finished plan to `docs/plans/completed/`.

## Concrete Steps

Run commands from the repository root, `C:\Projects\03-Finance\ai-fund`.

For Milestone 0:

    python -c "from pathlib import Path; print(Path('docs/plans/completed/2026-03-18-single-ticker-deep-dive-dossier.md').exists())"

For Milestone 1:

    python -m pytest tests/test_dossier_workspace.py tests/test_dossier_index.py -q

For Milestone 2:

    python -m pytest tests/test_dossier_sources.py tests/test_dossier_artifacts.py -q

For Milestone 3:

    python -m pytest tests/test_dossier_model_checkpoints.py -q

For Milestone 4:

    python -m pytest tests/test_ic_memo.py tests/test_thesis_agent.py tests/test_dossier_thesis_tracker.py -q

For Milestone 5:

    python -m pytest tests/test_dossier_decision_log.py tests/test_dossier_review_log.py -q

For Milestone 6:

    python -m pytest tests/test_dossier_publishable_memo.py tests/test_dashboard_thesis_tracker.py tests/test_dashboard_render_contracts.py -q
    python -m py_compile src/stage_04_pipeline/dossier_workspace.py src/stage_04_pipeline/dossier_index.py src/stage_04_pipeline/dossier_view.py src/stage_04_pipeline/templates/dossier_models.py src/stage_02_valuation/templates/ic_memo.py src/stage_03_judgment/thesis_agent.py dashboard/app.py db/schema.py db/loader.py
    python -m streamlit run dashboard/app.py --server.headless true --server.port 8503

Actual final verification commands:

    python -m pytest tests/test_dossier_workspace.py tests/test_dossier_index.py tests/test_dossier_sources.py tests/test_dossier_artifacts.py tests/test_dossier_model_checkpoints.py tests/test_ic_memo.py tests/test_thesis_agent.py tests/test_dossier_thesis_tracker.py tests/test_dossier_decision_log.py tests/test_dossier_review_log.py tests/test_dossier_publishable_memo.py tests/test_dashboard_render_contracts.py tests/test_dashboard_thesis_tracker.py tests/test_report_archive.py -q
    python -m py_compile config/__init__.py config/settings.py db/schema.py db/loader.py src/stage_04_pipeline/templates/dossier_models.py src/stage_04_pipeline/dossier_workspace.py src/stage_04_pipeline/dossier_index.py src/stage_04_pipeline/dossier_view.py src/stage_02_valuation/templates/ic_memo.py src/stage_03_judgment/thesis_agent.py dashboard/app.py
    python -m streamlit run dashboard/app.py --server.headless true --server.port 8504

## Validation and Acceptance

This work is accepted only when the dashboard exposes a usable `Deep Dive` workspace for a ticker and the dossier state survives reloads. At minimum, the PM must be able to initialize a dossier, see the note skeleton and root paths, register at least one source and one artifact, create a model checkpoint, inspect current versus prior thesis context, write a decision entry, write a review entry, and edit a publishable memo draft without any of that writing back into deterministic valuation inputs.

The full verification bundle at the end of the work must include the focused dossier tests, the compile pass for all touched modules, and a live dashboard path using IBM.

Actual completion evidence:

- `python -m pytest ... -q` for the focused dossier bundle returned `23 passed in 6.01s`.
- `python -m py_compile ...` for all touched dossier, memo, thesis, config, DB, and dashboard modules exited with code `0`.
- Live dashboard verification on `http://127.0.0.1:8504` showed the IBM dossier workflow end to end:
  - loaded IBM from archive
  - initialized dossier workspace
  - saved source `S-001`
  - saved external workbook artifact `ibm_model_v01`
  - saved model checkpoint `v01` / `t01`
  - saved tracker state and catalyst status
  - saved one decision entry and one review entry
  - saved the publishable memo draft
  - refreshed the app, reloaded IBM, and confirmed the dossier still showed `active` plus the saved publishable memo content

## Idempotence and Recovery

All schema changes must be additive and expressed through `CREATE TABLE IF NOT EXISTS`, `CREATE INDEX IF NOT EXISTS`, and guarded compatibility migrations where needed. Dossier workspace initialization must be safe to run repeatedly. If a step fails mid-way, the recovery path is to inspect the diff for the affected files, update the `Progress` section to reflect the actual state, and rerun the milestone-specific test command before continuing. Do not destructively reset the worktree because this repo often carries unrelated local changes.

## Artifacts and Notes

These baseline snippets motivated the current shape of the implementation:

    dashboard/app.py:997-1002
    SECTION_GROUPS = {
        "Research": [...],
        "Valuation": [...],
        "Filings": [...],
        "Market Intel": [...],
        "Ops": [...],
    }

    docs/plans/index.md
    ## Active
    - No active canonical plans at the moment. Start a new one under `docs/plans/active/`.

    src/stage_04_pipeline/report_archive.py
    save_report_snapshot(...)
    list_report_snapshots(...)
    load_report_snapshot(...)

## Interfaces and Dependencies

At the end of Milestone 1, `src/stage_04_pipeline/dossier_workspace.py` must expose `build_dossier_path`, `ensure_dossier_workspace`, `ensure_dossier_note_templates`, `read_dossier_note`, and `normalize_linked_artifact_path`. `src/stage_04_pipeline/dossier_index.py` must expose dossier-profile and dossier-section helpers. `src/stage_04_pipeline/templates/dossier_models.py` must define stable models for dossier profiles, sections, sources, artifacts, checkpoints, thesis pillars, catalysts, decisions, reviews, and publishable memo state.

At the end of Milestone 4, `src/stage_02_valuation/templates/ic_memo.py` must support `thesis_pillars` and `structured_catalysts` without breaking archived memo deserialization, and `src/stage_03_judgment/thesis_agent.py` must emit those fields.

At the end of the full plan, `src/stage_04_pipeline/dossier_view.py` must expose `build_deep_dive_dossier_view`, `build_thesis_diff_view`, `build_model_checkpoint_view`, and `build_publishable_memo_context`, and `dashboard/app.py` must render the `Deep Dive` group using those payloads.

Revision note, 2026-03-18 / Codex: Created this active ExecPlan from the future roadmap because `docs/PLANS.md` requires execution-ready work to live under `docs/plans/active/` as a single canonical plan.

Revision note, 2026-03-18 / Codex: Updated the living plan with Milestones 2-6 completion, environment discoveries, final verification evidence, and the rationale for ignoring generated dossier workspaces before moving the plan to `completed/`.

Revision note, 2026-03-18 / Codex: Moved this ExecPlan from `docs/plans/active/` to `docs/plans/completed/` after live verification, and adjusted references so the document reads as the shipped implementation record rather than an in-flight plan.
