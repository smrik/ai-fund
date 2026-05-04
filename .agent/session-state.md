# Session State

**Updated:** 2026-05-04 17:36:50 +02:00
**Agent:** Codex CLI
**Project:** C:\Projects\03-Finance\ai-fund

## Current Task
Persist canonical `TickerDossier` payloads in a SQL-friendly JSON snapshot table and make the API prefer persisted dossiers before read-only builder fallbacks.

## Recent Actions
- Added `ticker_dossier_snapshots` to `db/schema.py` with lookup columns, unique `(ticker, source_mode, source_key, contract_version)`, and ticker/source/date indexes.
- Added `db/ticker_dossier.py` helpers to validate `TickerDossier` payloads on write/read, upsert snapshots, compute `source_key`, and load the latest persisted dossier.
- Updated `api/main.py` so `/api/tickers/{ticker}/dossier` and additive dossier attachments load persisted `latest_snapshot` rows first, then build `latest_snapshot`, then fall back to `loaded_backend_state`; explicit `source_mode` is respected.
- Updated `src/stage_04_pipeline/export_service.py` so ticker XLSX/HTML export creation persists attached current or archived `ticker_dossier` payloads, while the API read path does not write.
- Documented the JSON-first persistence rule in `docs/design-docs/ticker-dossier-contract.md`.
- Added persistence, API preference/fallback, export persistence, schema/index, upsert, round-trip, and no-backfill tests.
- Moved `tests/test_export_service.py` temp directories from `.codex/memories` to the repo-ignored `.tmp-tests/` area and avoided `tempfile.mkdtemp` because it produced unwritable Windows temp dirs in this environment.

## Next Steps
- Review the final diff and decide how to split the pre-existing runtime/docs changes from this persistence layer for commit/PR purposes.
- Consider whether `.pytest_cache` ACL cleanup is worth doing separately; tests pass despite the warning.

## Known Issues
- `rtk pytest ...` shorthand still fails to import local packages in this repo; use `rtk python -m pytest ...`.
- Pytest still emits a local `.pytest_cache` permission warning under `C:\Projects\03-Finance\ai-fund\.pytest_cache`.
- MkDocs strict build reports pre-existing nav warnings for `docs/other/Valuation pseudo-code.md` and `docs/other/deterministic-valuation-workflow.md`, but exits successfully.

## Notes
- No valuation math was changed.
- No v1 backfill was added; existing archive rows remain untouched until a new ticker export is built.
- Verification run in this session:
  - `rtk python -m pytest tests/test_ticker_dossier_contract_runtime.py tests/test_ticker_dossier_contract_docs.py tests/test_api_contracts.py -q` -> 19 passed
  - `rtk python -m pytest tests/test_export_service.py tests/test_ticker_dossier_persistence.py -q` -> 10 passed
  - `rtk git diff --check` -> passed
  - `rtk python -m mkdocs build --strict` -> passed with the pre-existing docs/other nav warnings above
