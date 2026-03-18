# Deep Dive Dossier

This page explains the single-ticker deep-dive dossier system in Alpha Pod.

The dossier is the research control plane for one company. It is where the PM keeps the durable thinking layer around a name: note structure, linked workbook, sources, model checkpoints, thesis changes, decisions, reviews, and the publishable memo draft.

The dossier does not replace Excel. Excel remains the model engine. The dossier also does not replace the deterministic valuation pipeline. The dossier records context, evidence, and PM judgment around the model.

## What The Dossier Contains

Each dossier is created under `data/dossiers/` and uses one company folder as the unit of work.

The default structure is:

    data/dossiers/
      IBM International Business Machines/
        Notes/
          00 Company Hub.md
          01 Business & Industry.md
          02 Financial History.md
          03 Management & Capital Allocation.md
          04 Valuation.md
          05 Risks & Catalysts.md
          06 Thesis.md
          07 Decision Log.md
          08 Review Log.md
          09 KPI Tracker.md
          10 Publishable Memo.md
          Sources/
        Model/
        Exports/
        Filings/
        Decks/
        Transcripts/
        Private/

The Markdown notes are file-backed. They are meant to be durable and inspectable outside the app. SQLite stores the structured index and state around those files so the dashboard can query and render them quickly.

The dossier root is runtime user data. It should be treated like other generated working-state folders in this repository and maintained continuously, but not versioned as source code by default.

## What Is Automated Versus PM-Authored

Alpha Pod creates and maintains the dossier shell automatically:

- the dossier folder structure
- the standard note templates
- the SQLite profile and section index
- archive-backed thesis diffs
- source and artifact registries
- model checkpoints

The PM authors or approves the judgment layer:

- note contents
- why a source matters
- workbook and artifact linking
- tracker status
- catalyst status
- decisions
- reviews
- publishable memo draft

This split is intentional. The system should help the PM preserve thinking and evidence, not hide decisions behind automation.

## Deep Dive Sections In The Dashboard

The `Deep Dive` group exposes eight sections:

1. `Company Hub`
   - initializes the dossier
   - shows root paths and note skeleton

2. `Business`
   - edits the long-form working notes for business, financial history, management, and KPI tracking

3. `Model & Valuation`
   - saves checkpoint snapshots of the current valuation state
   - ties checkpoint history to model versions

4. `Sources`
   - registers source IDs such as `S-001`
   - creates source-note files under `Notes/Sources/`
   - links workbook or file artifacts without copying them into the database

5. `Thesis Tracker`
   - compares the latest archived thesis against the prior one
   - stores current PM tracker state and catalyst status

6. `Decision Log`
   - preserves what action the PM took and why

7. `Review Log`
   - preserves what happened later and what was learned

8. `Publishable Memo`
   - stores the outward-facing memo draft
   - excludes private artifacts from the rendered public context

## Source IDs And Artifact Discipline

Every important source should get a stable ID such as `S-001`, `S-002`, and so on.

Use source rows for:

- filings
- transcripts
- decks
- external articles
- internal model exports

Use artifact rows for linked files such as:

- the live Excel model
- exported PNG charts
- exported PDFs
- memo HTML exports

The key rule is that linked artifacts remain normal files on disk. Alpha Pod stores stable metadata and relationships around them. It does not ingest the workbook as the calculation engine.

## Tracker State Versus Archived Evidence

The dossier keeps two different kinds of thesis memory:

1. archived memo snapshots from `pipeline_report_archive`
2. current PM-maintained tracker state and catalyst state

The archive is immutable evidence. The tracker is the current operating view.

This matters because the PM needs to know both:

- what the system believed at the time of an old run
- what the PM believes now after reviewing new evidence

The tracker does not rewrite archived memos.

## Private Versus Publishable

The dossier separates private working material from publishable material.

- `Private/` is for non-publishable working files
- `10 Publishable Memo.md` is the outward-facing draft
- private artifacts are excluded from the publishable memo context

This is non-negotiable. The dossier must support deep private work and later public-quality synthesis without forcing those layers into the same note.

## Deterministic Valuation Boundary

The dossier does not auto-edit deterministic valuation inputs.

This remains true even when:

- tracker state changes
- catalyst statuses change
- decisions are logged
- reviews conclude that the PM was wrong

Those records are context for the PM. They do not bypass the repo’s main invariant that deterministic valuation logic remains explicit and reviewable.

## Maintenance Standard

This system must be maintained continuously.

When the dossier behavior changes:

- update the active or completed plan under `docs/plans/`
- update this handbook page if the operating model changed
- update dashboard docs and navigation if new sections were added or renamed

If the code and docs disagree, the docs are wrong and must be updated in the same change.
