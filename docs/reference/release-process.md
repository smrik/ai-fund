# Release Process

This repository is not packaged as a single public artifact today, so releases are tracked at the repository level.

## Canonical Version Source

The canonical version lives in the repo-root `VERSION` file.

Secondary version surfaces must stay in sync with it:

- `frontend/package.json`
- `frontend/package-lock.json`
- `CHANGELOG.md`
- release-note artifacts

## Release Shape

Current release policy is internal-first:

- use semantic versions
- treat the current milestone as pre-1.0
- use GitHub Releases and tags later, after the repo is release-ready and the workflow is stable

## Preparing An Internal Release Candidate

1. Make sure `main` is clean and current.
2. Confirm the version in `VERSION`.
3. Update `CHANGELOG.md` with the release section.
4. Sync versioned surfaces such as `frontend/package.json`.
5. Run:

```bash
python scripts/dev/run_local_quality_gate.py
python scripts/release/prepare_mock_release.py --check-only
```

6. If the repo is clean and checks pass, generate draft notes:

```bash
python scripts/release/prepare_mock_release.py
```

This writes a versioned draft release-notes artifact under `output/mock-releases/`.

## When To Bump Versions

- patch: small fixes or low-risk process changes
- minor: meaningful new capability or workflow surface
- major: breaking workflow changes or a significant stability/policy reset

## Future Real Release Flow

When the repo is ready for actual GitHub Releases:

1. merge the release PR
2. create a tag matching `v<version>`
3. create the GitHub Release using the changelog section and `.github/release.yml`
4. keep the next work under `Unreleased`
