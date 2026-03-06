# Branch Naming Convention

Use one branch per change.

## Format

`<type>/<ticket-or-area>-<short-slug>`

Examples:

- `feat/123-qoe-normalized-ebit`
- `fix/wacc-tax-rate-bounds`
- `refactor/config-loader-cleanup`
- `docs/github-workflow-guide`
- `chore/ci-pytest-cache`

## Allowed Types

- `feat`: new behavior
- `fix`: bug fix
- `refactor`: internal code change, same behavior
- `docs`: documentation only
- `test`: tests only
- `chore`: maintenance/build/infra
- `spike`: throwaway exploration (do not merge directly)

## Rules

1. Lowercase, hyphen-separated slug.
2. Keep branch names under ~60 chars.
3. No mixed concerns in one branch.
4. Delete branch after merge.
