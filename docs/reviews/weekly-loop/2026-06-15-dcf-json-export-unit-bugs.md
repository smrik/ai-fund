# Weekly Loop Session

- Date: 2026-06-15
- Session number: n/a — implementation friction follow-up
- Tickers: BAH
- Total time: n/a
- Counts toward M1 exit criteria: no

## Per-Phase Times

- Preflight: n/a
- CIQ refresh/ingest: n/a
- EDGAR/evidence acquisition: n/a
- Initial valuation: n/a
- Profile review loop: n/a
- Final bundle/export: n/a

## Queue Decisions

- Approved/applied: 0
- Edited: 0
- Rejected: 0
- Deferred: 0
- Skipped: 0

## Friction Items

| Phase | Severity | Manual data surgery? | What happened | Fix/ticket |
| --- | --- | --- | --- | --- |
| Final bundle/export | High | No | `excel_flat.forecast[].delta_nwc_mm` mixed units: years with sub-$1mm working-capital deltas stayed in dollars while other money fields were `$mm`, breaking the FCFF identity and risking Excel-model drift. | Fixed in `src/stage_02_valuation/json_exporter.py`; regression added in `tests/test_json_exporter.py`. |
| Final bundle/export | Medium | No | `excel_flat.wacc.size_premium` exported legacy percentage-points (`0.6` meaning `0.6%`) while other WACC rates were fractions, making Excel displays and downstream checks inconsistent. | Fixed in `src/stage_02_valuation/json_exporter.py`; regression added in `tests/test_json_exporter.py`. |
| Initial valuation | Low | No | `batch_runner --ticker BAH --json` still attempted SEC companyfacts and SPY/yfinance paths even with market-cache-only settings; the run completed but surfaced noisy cache/database warnings. | Logged for follow-up; not changed in this deterministic exporter task. |

## Keep / Change

- Keep: Build must fail if the workbook Base IV no longer reconciles to backend `iv_base`.
- Change: Add explicit unit-identity checks to exporter coverage whenever a flat Excel table is derived from raw backend projection rows.
