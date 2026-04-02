# Internal Release Readiness And Mock Publish

## Goal

Prepare Alpha Pod for an internal `v0.1.0` checkpoint with canonical versioning, changelog discipline, release metadata, and a mock-release flow that can generate release notes without publishing externally.

## Scope

- add canonical repo versioning via `VERSION`
- add `CHANGELOG.md` and release-process documentation
- add a mock-release prep script and release-readiness checks
- extend CI with frontend build, docs build, and release-readiness validation
- align documentation and repo metadata with the new release flow

## Deliverables

- `VERSION`
- `CHANGELOG.md`
- `.github/release.yml`
- `SECURITY.md`
- `docs/reference/release-process.md`
- `scripts/release/prepare_mock_release.py`
- CI jobs: `frontend-build`, `docs-build`, `release-readiness`

## Verification

- focused tests for release metadata and helper behavior
- local release-readiness check passes
- frontend build passes
- mkdocs strict build passes

## Remaining Follow-Up

- decide when to create the first actual Git tag / GitHub Release
- expand CI into richer frontend/backend test jobs
- continue paying down repo-wide Ruff debt outside the changed-file ratchet
