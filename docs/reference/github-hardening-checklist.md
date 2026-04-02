# GitHub Hardening Checklist

This document is the concrete checklist for making Alpha Pod safer to operate in GitHub and safer to maintain locally.

## Implemented In This Tranche

- `main` workflow documented and aligned around a protected-branch model
- local quality gate added: `python scripts/dev/run_local_quality_gate.py`
- `CODEOWNERS` added so repo ownership is explicit
- issue templates added for bug reports and feature requests
- Dependabot enabled for Actions, pip, and frontend npm updates
- CI action majors upgraded to Node 24 compatible versions
- standard text and merge-safety hooks added to `pre-commit`
- Ruff config made explicit in `pyproject.toml`
- `.gitignore` expanded to cover local agent/tooling noise

## Release-Readiness Additions

- canonical repo version file: `VERSION`
- root `CHANGELOG.md`
- release metadata config: `.github/release.yml`
- minimal `SECURITY.md`
- release-process guide: `docs/reference/release-process.md`
- mock release-note generator: `scripts/release/prepare_mock_release.py`
- CI jobs for frontend build, backend/API contracts, docs build, and release-readiness validation
- repo-level merge settings tightened: squash-only merges and automatic branch deletion on merge
- live branch ruleset updated to require `pre-commit`, `frontend-build`, `backend-api-tests`, `docs-build`, and `release-readiness`

## GitHub Settings Status

These are now enforced live in GitHub for `smrik/ai-fund` and should be periodically re-verified.

### Branch Ruleset For `main`

- require a pull request before merging
- require branches to be up to date before merging
- require status checks before merging
- require `pre-commit`
- require `frontend-build`
- require `backend-api-tests`
- require `docs-build`
- require `release-readiness`
- block force pushes
- restrict branch deletion

### Repository Settings

- allow squash merge
- disable merge commits
- disable rebase merges
- enable automatic branch deletion after merge
- keep `main` as the default branch

## Current Audit Findings

### 1. Repo-Wide Ruff Now Passes

`ruff check .` now passes repo-wide.

One intentional exception remains in config: `scripts/create_ibm_review.py` is covered by a narrow per-file ignore for `E402`, `E701`, and `E702` because it is a legacy one-off workbook generation script with dense layout code rather than maintained library logic.

`E501` is still intentionally ignored to avoid turning long-line cleanup into an unrelated blocker.

Recommended next step: either leave the legacy script ignored, or replace/archive it rather than force style-only rewrites into it.

### 2. CI Coverage Is Better, But Still Not Full Product Coverage

The required checks now cover hygiene, frontend build, backend/API contracts, docs, and release metadata, but they still do not exhaustively exercise every product path.

Recommended next additions:

- focused frontend route tests in CI
- expanded backend pytest coverage beyond `tests/test_api_contracts.py`
- optional smoke workflow for Streamlit/operator flows if that shell remains supported

### 3. Docs Navigation Still Has Drift

MkDocs navigation and docs index pages do not yet fully reflect every active plan and newer reference page.

Recommended next step: run a docs-navigation cleanup so `docs/index.md`, `mkdocs.yml`, and the actual tree match exactly.

### 4. Repo Hygiene Is Strong, But Still Needs Periodic Review

Local hooks still require per-clone installation, and live GitHub settings should be periodically verified against the documented workflow.

Recommended next step: keep `CONTRIBUTING.md` current and periodically verify the live branch ruleset against `docs/reference/github-workflow.md`.

## Operator Routine

Use this sequence before opening or updating a PR:

```bash
git status
git fetch origin
python scripts/dev/run_local_quality_gate.py
git push
```

If `git status` is noisy before new work, stop and clean that up first.
