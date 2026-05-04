# Session State

**Updated:** 2026-05-05 00:44:36 +02:00
**Agent:** Codex CLI
**Project:** C:\Projects\03-Finance\ai-fund

## Current Task
Implement GitHub issue #22: align API, React preload, and export consumers to the canonical `TickerDossier` envelope under Epic #14.

## Recent Actions
- Synced local `main` to `origin/main` after PR #39 and created branch `22-canonical-dossier-consumers`.
- Updated `api/main.py` so workspace, overview, and valuation summary payloads reuse one loaded dossier and prefer canonical company, market, valuation, as-of, and snapshot metadata while preserving PM action/conviction, memo, tracker, market narrative, readiness, and DCF audit fields.
- Added frontend canonical normalization in `frontend/src/lib/canonical.ts` and routed workspace, overview, valuation summary, and opened snapshot payloads through it.
- Updated HTML export context in `src/stage_04_pipeline/export_service.py` to derive scalar company/valuation/source metadata from the attached `ticker_dossier`.
- Updated dossier contract docs and the Epic #14 note for #22 consumer alignment.
- Added backend, export, and React tests with intentionally divergent legacy vs canonical fixture values.

## Next Steps
- Review the diff, then commit and open the issue #22 PR when ready.
- After merge, do the Epic #14 closure check for #19, #20, #21, and #22 before closing the epic.

## Known Issues
- Pytest still emits the known local `.pytest_cache` permission warning.
- MkDocs strict build still reports pre-existing nav warnings for `docs/other/Valuation pseudo-code.md` and `docs/other/deterministic-valuation-workflow.md`, but exits successfully.
- Vitest and Vite build need elevated/sandbox-external execution on this machine because esbuild helper spawn fails with `EPERM` inside the default sandbox.

## Notes
- No DB schema changes, contract version bump, API routes, live fetches, valuation math changes, or LLM calls were added.
- Verification run in this session:
  - `rtk python -m pytest tests/test_api_contracts.py tests/test_export_service.py tests/test_ticker_dossier_contract_runtime.py tests/test_ticker_dossier_contract_docs.py -q` -> 29 passed
  - `rtk npm --prefix frontend run test -- appRoutes.test.tsx exportFlows.test.tsx` -> 14 passed
  - `rtk npm --prefix frontend run build` -> passed
  - `rtk git diff --check` -> passed
  - `rtk python -m mkdocs build --strict` -> passed with the pre-existing docs/other nav warnings above
  - `$env:PRE_COMMIT_HOME = "$PWD\.pre-commit-cache-run-codex"; rtk pre-commit run --all-files` -> passed
