# GitHub Hygiene And Repo Hardening

## Goal

Make the repository safer to operate by tightening GitHub workflow discipline, documenting local/CI quality gates, and adding lightweight governance files that reduce avoidable process mistakes.

## Scope

- add repo-native GitHub hygiene files such as `CODEOWNERS`, issue templates, and Dependabot config
- harden CI and local workflow documentation so checks are predictable
- add explicit Ruff configuration and ignore local automation artifacts that should never be committed
- record the remaining hardening backlog that still requires follow-up

## Deliverables

- `.github/CODEOWNERS`
- `.github/ISSUE_TEMPLATE/`
- `.github/dependabot.yml`
- `CONTRIBUTING.md`
- explicit Ruff config in `pyproject.toml`
- improved `.gitignore`
- updated workflow/docs references
- a written hardening checklist and backlog in `docs/reference/`

## Verification

- focused tests covering repo-hygiene files and local-quality helpers
- local quality gate passes
- CI workflow remains valid after action-version updates

## Remaining Follow-Up

- split broader repo lint debt into its own cleanup tranche
- add dedicated frontend/backend CI jobs beyond `pre-commit`
- finish aligning MkDocs navigation with the current docs tree
