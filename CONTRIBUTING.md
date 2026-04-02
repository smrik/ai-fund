# Contributing

This repository uses a review-first workflow with a protected `main` branch.

## Before You Start

1. Make sure `main` is clean and current:
   - `git switch main`
   - `git fetch origin`
   - `git pull --ff-only origin main`
2. Create one focused branch:
   - `feat/...`
   - `fix/...`
   - `chore/...`
3. Keep the scope tight. If the branch starts mixing concerns, split it.

## Local Setup

Install the local quality tools once per clone:

```bash
python -m pip install pre-commit ruff pytest
python -m pre_commit install
python -m pre_commit install --hook-type pre-push
```

## Before Every Push

Run the local quality gate:

```bash
python scripts/dev/run_local_quality_gate.py
```

This runs Ruff on changed Python files versus `origin/main` and then runs the architecture-boundary test.

If you intentionally want a full-repo Ruff pass:

```bash
python scripts/dev/run_local_quality_gate.py --all-files
```

## Pull Request Expectations

- one branch per change stream
- one PR per branch
- docs updated when behavior changes
- version/changelog updated when the change affects a release checkpoint
- no secrets in the diff
- local quality gate passed
- CI green before merge

Use the PR template in [.github/pull_request_template.md](./.github/pull_request_template.md) and include concrete verification evidence.

## Merge Discipline

- prefer squash merge unless you intentionally preserved a structured commit history
- delete merged branches
- do not push directly to `main`
- do not merge red PRs

For branch protection and GitHub settings, see [docs/reference/github-workflow.md](./docs/reference/github-workflow.md) and [docs/reference/github-hardening-checklist.md](./docs/reference/github-hardening-checklist.md).

For versioning and internal release-candidate prep, see [docs/reference/release-process.md](./docs/reference/release-process.md).
