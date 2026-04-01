# Changelog

All notable repository-level changes should be recorded here.

The format is intentionally lightweight and internal-first. Keep one `Unreleased` section at the top, then append versioned release sections below it.

## [Unreleased]

- No unreleased changes yet.

## [0.1.0] - 2026-04-01

### Added

- React/API-driven Excel and HTML export workflows with saved export history and download surfaces.
- Richer comps appendix export contract with `comps_analysis` and staged workbook diagnostics.
- Local quality gate, diff-scoped CI pre-commit flow, `CODEOWNERS`, issue templates, Dependabot config, and contribution/process docs.
- Internal release-readiness workflow with canonical repo versioning, mock release notes generation, and release-process documentation.

### Changed

- Canonical `ticker_review.xlsx` comps surfaces now consume backend-generated workbook data instead of relying on thin legacy Excel-only median logic.
- CI now uses Node 24 compatible action majors and includes dedicated frontend, docs, and release-readiness checks.

### Fixed

- Removed stray debug output from the base agent path that was failing architecture-boundary checks.
- Tightened repo ignore rules and workflow docs so local agent/tooling noise stays out of version control.
