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

## GitHub Settings To Enable Manually

These cannot be fully enforced from the repository contents alone and should be set in the GitHub UI.

### Branch Ruleset For `main`

- require a pull request before merging
- require branches to be up to date before merging
- require status checks before merging
- require `CI / pre-commit`
- block force pushes
- restrict branch deletion

### Repository Settings

- prefer squash merge as the default merge method
- enable automatic branch deletion after merge
- keep `main` as the default branch

## Current Audit Findings

### 1. Repo-Wide Ruff Debt Still Exists

The repository still contains a broader backlog of Ruff findings outside the changed-file CI ratchet. At the time of this audit, the main clusters were:

- `scripts/create_ibm_review.py`
- `scripts/build_valuation_template.py`
- `src/stage_02_valuation/templates/ic_memo.py`
- `src/stage_03_judgment/forensic_scores.py`
- several older tests with unused imports and import-order drift

The repo now makes Ruff configuration explicit, but `E501` is intentionally ignored for now so long-line debt does not make the local and CI gates unusable while the rest of the hygiene system is being put in place.

Recommended next step: create a dedicated lint-debt cleanup branch and clear the backlog by directory, not mixed into feature work.

### 2. CI Coverage Is Still Thin

The current required check is intentionally lightweight. It protects the branch, but it does not yet fully exercise the product.

Recommended next additions:

- frontend build job: `npm --prefix frontend run build`
- focused frontend route tests
- focused backend/API pytest job
- optional docs build or `mkdocs build` check once docs navigation drift is addressed

### 3. Docs Navigation Still Has Drift

MkDocs navigation and docs index pages do not yet fully reflect every active plan and newer reference page.

Recommended next step: run a docs-navigation cleanup so `docs/index.md`, `mkdocs.yml`, and the actual tree match exactly.

### 4. Repo Hygiene Is Better, But Not Fully Automated

Local hooks still require per-clone installation, and GitHub UI settings still need to be maintained manually.

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
