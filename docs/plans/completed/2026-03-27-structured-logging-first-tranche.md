# Structured Logging First Tranche

## Summary

This plan starts Epic 3 from the infrastructure roadmap with the smallest safe tranche:

- introduce shared CLI logging configuration in `src/logging_config.py`
- migrate `src/stage_02_valuation/batch_runner.py` off bare `print()` for progress, warnings, and error reporting
- preserve operator-facing batch output shape while improving debug traceability

This is not the full logging migration. `daily_refresh.py`, `refresh.py`, and agent infrastructure remain follow-on work.

## Scope

In scope:

- shared `configure_logging()` helper for command-line entry points
- JSON file logging support for machine-readable diagnostics
- `batch_runner.py` migration from bare `print()` to logging for lifecycle, export-path, warning, and error paths
- focused tests for logging config and batch runner logging behavior
- docs and tech-debt updates that keep the repo guidance truthful

Out of scope:

- full repo-wide logging migration
- dashboard logging changes
- removal of current raw `sqlite3.connect()` debt
- CI changes beyond existing Epic 2 hardening

## Verification

Minimum verification for this tranche:

1. `python3 -m py_compile src/logging_config.py src/stage_02_valuation/batch_runner.py tests/test_logging_config.py tests/test_batch_runner_storage.py`
2. `python3 -m pytest tests/test_logging_config.py tests/test_batch_runner_storage.py tests/test_architecture_boundaries.py -q`
3. `ruff check src/logging_config.py src/stage_02_valuation/batch_runner.py tests/test_logging_config.py tests/test_batch_runner_storage.py tests/test_architecture_boundaries.py`

## Runtime Controls

Machine-local overrides added in this tranche:

- `ALPHA_POD_LOG_LEVEL`
- `ALPHA_POD_LOG_FILE`

## Next Steps

After this tranche lands:

1. migrate `src/stage_04_pipeline/daily_refresh.py`
2. migrate `src/stage_04_pipeline/refresh.py`
3. decide whether `src/stage_03_judgment/base_agent.py` should join the shared logging path in the same epic or a follow-on infra pass
