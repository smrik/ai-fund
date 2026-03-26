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
- [Reference Index](./reference/config-reference.md)
- [Strategy Docs](./strategy/index.md)
- [Plan Registry](./plans/index.md)
- [Execution Artifact Archive](./exec-plans/index.md)
- [General Archive](./archive/index.md)

## Why This Exists

The repo accumulated multiple overlapping plan indexes, duplicated root docs, and scratch material published next to canonical references. This file exists to prevent that drift from returning.
