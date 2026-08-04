# Issue tracker: GitHub

Issues and PRDs for this repo live as GitHub issues. Use the `gh` CLI for all operations.

## Conventions

- **Create an issue**: `gh issue create --title "..." --body "..."`
- **Read an issue**: `gh issue view <number> --comments`
- **List issues**: use `gh issue list` with suitable state, label, and JSON filters
- **Comment on an issue**: `gh issue comment <number> --body "..."`
- **Apply or remove labels**: `gh issue edit <number> --add-label "..."` or `--remove-label "..."`
- **Close an issue**: `gh issue close <number> --comment "..."`

Infer the repository from `git remote -v`; `gh` does this automatically when run inside this clone.

## Pull requests as a triage surface

**PRs as a request surface: no.**

External pull requests are not included in the issue-triage queue unless this flag is changed to `yes`.

GitHub shares one number space across issues and pull requests. If a bare reference such as `#42` is ambiguous, try `gh pr view 42` and then `gh issue view 42`.

## When a skill says "publish to the issue tracker"

Create a GitHub issue.

## When a skill says "fetch the relevant ticket"

Run `gh issue view <number> --comments`.

## Wayfinding operations

The map is a single issue with child issues as tickets.

- **Map**: an issue labelled `wayfinder:map`, containing Notes, Decisions-so-far, and Fog
- **Child ticket**: a linked sub-issue labelled `wayfinder:<type>`, where type is `research`, `prototype`, `grilling`, or `task`
- **Blocking**: use GitHub's native issue dependencies; fall back to a `Blocked by: #<n>` line when unavailable
- **Frontier**: find the first open, unblocked, and unassigned child in map order
- **Claim**: `gh issue edit <number> --add-assignee @me`
- **Resolve**: comment with the answer, close the child issue, and add a context pointer to the map's Decisions-so-far
