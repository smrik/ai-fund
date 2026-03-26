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
          11 Research Notebook.md
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

## Dashboard Operating Model

The dossier no longer lives as a top-level dashboard destination. It now acts as a companion research layer around a simpler app shell.

The main shell is organized into five tabs:

1. `Overview`
   - cross-functional ticker cockpit
   - combines thesis, valuation, market pulse, and audit health

2. `Valuation`
   - grouped around summary, DCF, comparables, and multiples

3. `Market`
   - grouped around macro, news and revisions, sentiment, and factor framing

4. `Research`
   - the working research board
   - combines current stance, tracker context, and durable note blocks

5. `Audit`
   - pipeline review, filings evidence, dossier admin, exports, and operational checks

This is deliberate. The shell is organized around PM jobs rather than internal implementation modules.

## Dossier Companion

The dossier now appears as a global right-side companion rail inside the dashboard instead of a standalone navigation tree.

Use the `Show Notes Rail` toggle in the shell header to open or close the rail without leaving the current page. This keeps note capture context-linked while avoiding a permanent left-navigation burden.

It is available from any loaded-ticker page and has three modes:

1. `Scratchpad`
   - temporary capture layer
   - scoped to the current page context

2. `Notebook`
   - durable ticker notebook grouped by block type
   - each type is sorted newest-first

3. `Pinned`
   - note blocks marked as especially important for the active research board

The scratchpad is intentionally cheap and temporary. It does not enter the durable record until the PM promotes it.

## Research And Audit Pages

The `Research` tab is the working board, not a read-only memo archive.

It should show:

- current stance and tracker context
- notable change since the last archived snapshot
- diligence queue and open questions
- note blocks grouped by type
- the selected evidence context that supports the current view

The `Audit` tab now absorbs operational review, filings evidence, exports, and dossier administration. Keep it auditable, but do not make it the primary thinking surface.

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

## Research Notebook Blocks

Promoted scratchpad entries become durable note blocks.

Each note block stores:

- block type
- title
- body
- timestamp
- page context
- linked snapshot id
- linked source ids
- linked artifact ids
- pinned flag

The notebook is type-first:

- `thesis`
- `risk`
- `catalyst`
- `question`
- `decision`
- `review`
- `evidence`
- `general`

Within each type, blocks are sorted newest-first.

This preserves both semantic organization and time continuity. A pure timeline becomes noisy too quickly, and a pure static note tree hides evolution.

The durable notebook is also mirrored into `11 Research Notebook.md` so the research record remains inspectable outside the app.

## Thesis Tracker V2: PM Cockpit

The tracker is no longer meant to feel like a raw state editor. It is the current operating page for one thesis.

The page is organized around six questions:

1. What is my current stance now?
2. What changed since the last archived run?
3. Which thesis pillars are intact, weakening, validated, or broken?
4. Which catalysts are open, being watched, or resolved?
5. What recent decision, review, and checkpoint context matters?
6. What should I diligence next?

The tracker therefore shows:

- a summary header
- a `What Changed Since Last Snapshot` panel
- a `Next Diligence Queue` panel
- a `Pillars` tab
- a `Catalysts` tab
- a `Continuity` tab

This is a deliberate separation of concerns:

- the archive remains the historical evidence baseline
- the tracker is the PM-maintained current operating view
- the decision and review logs remain adjacent dedicated journals

The tracker uses PM-authored current state for:

- overall thesis status
- PM action
- PM conviction
- summary note
- pillar statuses and notes
- current open questions
- catalyst statuses, dates, and reasons

The tracker uses archive-derived state for:

- latest and prior archived thesis snapshots
- what changed between snapshots
- fallback thesis pillars or catalysts when old memo structure is incomplete
- baseline catalyst definitions when no PM catalyst overrides exist

This means the PM can keep a living operating view without rewriting the historical record.

## Pillar Status And Catalyst Status

Use thesis pillars to track whether the core reasons for owning or shorting the name are still working.

Recommended pillar statuses:

- `intact`
- `monitor`
- `validated`
- `broken`
- `unknown`

Use catalysts to track timing and mechanism.

The tracker groups catalysts into:

- `urgent_open`
- `watching`
- `resolved`

Typical catalyst statuses remain:

- `open`
- `watching`
- `hit`
- `delayed`
- `missed`
- `killed`
- `resolved`

The point is not taxonomy purity. The point is to make the current operating state obvious without forcing the PM to inspect raw tables or old JSON.

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
