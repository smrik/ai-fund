# GitHub Workflow (Simple)

This repo uses a trackable, review-first workflow.

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

