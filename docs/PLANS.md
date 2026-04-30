# Repository Guidance And Planning System

This file is the top-level documentation guide for Alpha Pod. Keep it current at all times.

The repository follows a harness-style structure:

- `AGENTS.md` is the short operating map for coding agents.
- `.agent/session-state.md` is the lightweight handoff log for the next session.
- `docs/` is the system of record for humans and agents.
- `docs/plans/active/` holds the single canonical implementation plan for each non-trivial workstream.
- each important concept should have one canonical home
- finished work should move out of `active` areas quickly
- stale docs should be archived, not left next to current guidance

If code changes and the docs no longer describe reality, the docs are wrong and must be updated in the same change.

## Documentation Model

Use these doc types consistently:

- `docs/valuation/`
  - finance methodology and explanation
  - answers: how should Alpha Pod think about valuation?
- `docs/handbook/`
  - how-to and operator / engineer workflow guidance
  - answers: how do I run, review, or use this safely?
- `docs/design-docs/`
  - architecture, boundaries, data flow, implementation truth
  - answers: how is the system designed and where should logic live?
- `docs/reference/`
  - stable setup, config, glossary, and workflow references
  - answers: what are the durable facts?
- `docs/plans/`
  - current work, future work, shipped plans, and archived plan history
  - answers: what are we building and what already shipped?

This is intentionally close to a Diataxis-style split:

- methodology / explanation -> `docs/valuation/`
- how-to -> `docs/handbook/`
- reference -> `docs/reference/`
- implementation design -> `docs/design-docs/`

## What Lives Where

Use these buckets consistently:

- `docs/design-docs/`
  - architecture, system behavior, agent contracts, and stable design specs
- `docs/handbook/`
  - operator and engineer how-to guides
- `docs/reference/`
  - stable references such as config rules, glossaries, and workflow references
- `docs/strategy/`
  - product direction and quality-scoring documents
- `docs/plans/`
  - the canonical planning system
  - `active/` for plans currently being executed
  - `future/` for queued work and backlog docs
  - `completed/` for shipped plans that still matter as historical implementation records
  - `archive/` for superseded or legacy plans that are no longer canonical
- `docs/exec-plans/`
  - archived execution artifacts and older status trackers
  - this is not the primary planning system anymore
- `docs/archive/`
  - scratch notes, deprecated top-level docs, and historical material kept only for posterity
- `api/`
  - thin FastAPI transport surface for UI clients; never the source of business logic
- `frontend/`
  - React + TypeScript + Vite quote-terminal client and its test/build config

## Authoring Rules

Keep docs simpler by default:

- one page, one job
- front-load purpose and audience
- keep index and landing pages short
- prefer links over repeated prose
- do not duplicate valuation-method explanation in handbook or design docs when `docs/valuation/` already owns it
- do not put detailed plan lists on the docs home page; link to `docs/plans/index.md` instead
- move stale or superseded material to archive locations instead of leaving it next to canonical pages

## Canonical Entry Points

Read these first:

1. [Docs Home](./index.md)
2. [Architecture Overview](./design-docs/architecture-overview.md)
3. [Core Beliefs](./design-docs/core-beliefs.md)
4. [Workflow End To End](./handbook/workflow-end-to-end.md)
5. [Plan Registry](./plans/index.md)

## Planning Rules

Alpha Pod has one canonical planning registry: [docs/plans/index.md](./plans/index.md).

When creating or maintaining plans:

- create new canonical plans under `docs/plans/`
- put current work in `docs/plans/active/`
- keep exactly one active canonical plan per live workstream
- update the active plan as implementation reality changes; do not leave the plan frozen while code moves
- move shipped plans to `docs/plans/completed/`
- move superseded planning material to `docs/plans/archive/`
- keep future ideas and backlog docs in `docs/plans/future/`
- do not create a second live planning index elsewhere

Historical execution notes may remain under `docs/exec-plans/`, but they are supporting artifacts rather than the main source of truth.

## Human-Friendly Plan Format

Use a small set of planning document shapes so the docs stay easy to read in raw Markdown, GitHub, and MkDocs:

- roadmap dashboard pages
  - scan-first pages with tables for `Now`, `Next`, `Later`, releases, and linked epic pages
- short epic pages
  - one-screen summaries with status, priority, release target, scope, dependencies, and acceptance criteria
- active implementation plans
  - detailed execution documents only after work starts

Do not let roadmap docs become execution journals. If a future plan starts reading like a work log, it belongs in `active/` or `completed/`, not in the future backlog.

Recommended editing style:

- start with a compact metadata table
- prefer short sections, tables, and checklists
- keep one idea per section
- link outward instead of duplicating detail
- reserve long narrative for design docs and completed implementation records

Session continuity rules:

- read `.agent/session-state.md` at the start of each session if it exists
- update `.agent/session-state.md` before handoff or when stopping mid-stream
- treat session state as a resume note, not as a replacement for the canonical plan and docs

Branch hygiene rules:

- before creating a new branch, check whether `main` is both clean and pushed to GitHub
- if `main` is dirty or ahead of `origin/main`, surface that explicitly instead of silently branching off stale state
- when the user says they want to start fresh branch work, prefer getting `main` fully up to date first unless they explicitly choose stacked or deferred integration

## Maintenance Standard

These rules are mandatory:

- `AGENTS.md` must stay concise and point to canonical docs instead of duplicating them
- `AGENTS.md` should explain how to find the current plan and handoff state, not restate plan content
- `docs/index.md` must reflect the actual structure on disk
- `mkdocs.yml` must match the current published documentation structure
- stale active plans must be moved to `completed/` or `archive/`
- active plans must include current scope, verification expectations, and next steps that match the codebase
- duplicate root-level docs should be removed once a canonical docs copy exists
- setup docs must match the actual environment files and ignore rules

## Current Structure

- [Design Docs Index](./design-docs/index.md)
- [Handbook Index](./handbook/index.md)
- [Reference Index](./reference/index.md)
- [Strategy Docs](./strategy/index.md)
- [Plan Registry](./plans/index.md)
- [Alpha Pod Product Roadmap Dashboard](./plans/future/2026-04-02-alpha-pod-roadmap-dashboard.md)
- [Execution Artifact Archive](./exec-plans/index.md)
- [General Archive](./archive/index.md)

## Why This Exists

The repo accumulated multiple overlapping plan indexes, duplicated root docs, and scratch material published next to canonical references. This file exists to prevent that drift from returning.
