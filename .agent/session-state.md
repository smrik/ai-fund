# Session State

**Updated:** 2026-04-02 23:09:01 +02:00
**Agent:** Codex CLI
**Project:** C:\Projects\03-Finance\ai-fund

## Current Task
Reshape the repo planning docs into a more human-friendly roadmap dashboard plus short epic pages, while keeping the repo-native docs system canonical.

## Recent Actions
- Switched back to clean, up-to-date `main`, then created the new branch `codex/roadmap-docs-cleanup` for the documentation tranche.
- Added a new future roadmap dashboard and five short epic pages under `docs/plans/future/` covering dossier integrity, research/RAG, PM web cockpit, solo PM state, and platform reliability/DevOps.
- Updated `docs/PLANS.md`, `docs/index.md`, `docs/plans/index.md`, and `mkdocs.yml` so the new dashboard-plus-short-pages pattern is the visible default.
- Moved the older future roadmap docs (`2026-03-18-dashboard-ai-investing-feature-roadmap.md` and `2026-03-15-xbrl-and-rag-chatbot.md`) into `docs/plans/archive/` because they are now superseded.
- Fixed one stale historical link in `docs/plans/completed/2026-03-18-single-ticker-deep-dive-dossier.md` to point at the archived roadmap path.
- Verified the docs with `python -m mkdocs build --strict`; the build passed, with only existing informational absolute-link notices in handbook pages.

## Next Steps
- Stage the docs changes and commit them on `codex/roadmap-docs-cleanup`.
- Push the branch and open a PR if the user wants the planning-system cleanup reviewed/merged.
- After merge, use the new roadmap dashboard as the single scan-first entry point for future product planning.

## Known Issues
- `mkdocs build --strict` still emits existing informational absolute-link notices in `docs/handbook/react-frontend-setup.md` and `docs/handbook/react-playwright-review-loop.md`, but the build succeeds.
- The current branch has uncommitted docs changes until the cleanup tranche is committed.

## Notes
- Recommended human workflow for docs remains: edit in VS Code, read via `python -m mkdocs serve` in the browser.
- The new planning model is intentionally simple:
  - roadmap dashboard for scanning
  - short epic pages for scope
  - active plans only when implementation starts
