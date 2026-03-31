# GitHub Workflow (Simple)

This repo uses a trackable, review-first workflow.

See also: [GitHub Hardening Checklist](./github-hardening-checklist.md) and [Contributing Guide](../../CONTRIBUTING.md).

## Branch Protection For `main`

Configure `main` with these rules:

1. Require a pull request before merging.
2. Require branches to be up to date before merging.
3. Require status checks to pass before merging.
4. Require the GitHub Actions check `CI / pre-commit`.
5. Restrict direct pushes to `main`.
6. Disable force pushes to `main`.

The required check name matches the workflow/job names in [`.github/workflows/ci.yml`](/mnt/c/Projects/03-Finance/ai-fund/.github/workflows/ci.yml): workflow `CI`, job `pre-commit`, status check `CI / pre-commit`.

The `pre-commit` job currently ratchets on changed files in CI:

- pull requests run hooks from the PR base SHA to the PR head SHA
- pushes run hooks from the previous pushed SHA to the current SHA
- non-diffable cases fall back to `--all-files`

This keeps `main` protected without forcing every feature PR to clear unrelated legacy lint debt across the entire repository in one step.

## Local Guardrails

Set up local hooks once per clone:

```bash
python -m pip install pre-commit ruff pytest
python -m pre_commit install
python -m pre_commit install --hook-type pre-push
```

Before pushing, run:

```bash
python scripts/dev/run_local_quality_gate.py
```

That helper runs:

- `ruff check` on changed Python files versus `origin/main`
- `pytest tests/test_architecture_boundaries.py -q`

Use `python scripts/dev/run_local_quality_gate.py --all-files` when you intentionally want a full-repo Ruff pass.

## Default Flow

1. Update local `main`.
2. Create one focused branch.
3. Commit in logical chunks.
4. Open PR early (draft is fine).
5. Keep branch updated with `main`.
6. Merge only after review + green checks.
7. Delete merged branch.

## If Multiple Features Are In Progress

Use one branch per feature and one PR per branch.

### Case A: Features are independent

- Build on separate branches from current `main`.
- Merge whichever is ready first.
- Rebase other branches on latest `main` before merge.

### Case B: Features depend on each other

Use stacked PRs:

1. `feat/base` -> PR A
2. `feat/base-plus` based on `feat/base` -> PR B
3. Merge PR A first.
4. Rebase PR B onto `main`.
5. Merge PR B.

### Case C: One large feature takes weeks

Use feature flags:

- Merge small safe slices to `main` behind disabled flags.
- Turn flag on only when end-to-end is ready.

This avoids long-lived branches and painful merge conflicts.

## Practical Merge Rules

1. Small PRs merge faster and conflict less.
2. Prefer squash merge for noisy commits.
3. Keep commit history meaningful when changes are tightly structured.
4. Never mix unrelated features in one PR.

## Fast Conflict Routine

1. `git switch <feature-branch>`
2. `git fetch origin`
3. `git rebase origin/main`
4. Resolve conflicts, run tests, push.

## Definition of Done for PR Merge

- Review comments resolved
- CI green
- Tests run locally
- Docs updated for behavior changes
- Rollback path understood for risky changes

