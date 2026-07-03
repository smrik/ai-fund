# Weekly Loop Friction Draft - 2026-07-03 - MSFT

- Ticker: MSFT
- Total time: ~4 min (non-interactive rehearsal smoke; agent-assisted, PM absent)
- Session number: pre-session rehearsal (does not count toward the four July sessions)

## Run Configuration

`--agent-mode heuristic --isolated-db --non-interactive --skip-ciq-stage --edgar-summary-only --market-cache-only --edgar-cache-only --no-export-xlsx`

## Per-Phase Times

- CIQ stage/ingest: skipped (`--skip-ciq-stage`)
- EDGAR prefetch: seconds (all cache hits, 12 filings, latest 2026-06-05)
- Initial valuation: seconds (base IV $283.16 from 2026-06-12 market cache)
- Profile review loop: ~3 min for all six profiles, heuristic mode
- Final export: skipped (`--no-export-xlsx`)

## Queue Decisions

- Approved/applied: 0
- Edited: 0
- Rejected: 0
- Deferred: 0
- Skipped: 6 (items 92-97, all `non_interactive` — correct rehearsal behavior; isolated DB, live DB untouched)

## Friction Items

| Phase | Severity | Manual data surgery? | What happened | Fix/ticket |
| --- | --- | --- | --- | --- |
| DB safety rail | Critical | Yes (live DB restore) | `--isolated-db` did not isolate. Top-level imports in `run_guided_ticker_workup.py` load `config`/`db.schema` before `configure_isolated_db()` sets `ALPHA_POD_DB_PATH`; `db.schema.get_connection()` freezes the live `DB_PATH` at import time. Two rehearsal runs wrote 12 PM queue items (ids 92-103) and 12 evidence packets (160-171) into the LIVE `data/alpha_pod.db` while the run JSON claimed `mode=isolated_snapshot`. Confirmed empirically (live had the rows; snapshot had none). Zero decisions/assumption changes occurred (non-interactive rail held). Live DB restored from the pre-pollution 18:05 snapshot with PM approval; polluted state kept at `data/alpha_pod.db.polluted-20260703.bak`. Independently flagged by Codex GitHub review on PR #77 (P1). | Fix dispatched 2026-07-03: `get_connection()` resolves `ALPHA_POD_DB_PATH` dynamically at call time; DB-touching imports deferred until after isolation setup; regression tests assert isolation regardless of import order. |
| Profile review / outputs | High | No | PM-facing outputs (run markdown + all six per-profile review packets) contain no data-freshness information. The run consumed 21-day-old market data (fetched 2026-06-12) and presented IV and proposal previews ($283.16 -> $291.83, +3.1%) with no visible staleness warning. The `data_freshness` block exists in the run JSON but the PM never reads the JSON. | Fix dispatched 2026-07-03: surface a Data Freshness section (with stale markers past preflight thresholds) in the run markdown and every per-profile review packet. Display-only for M1; blocking on staleness is M3's data-freshness-gate scope. FIXED — verified rendering in the 22:49 UTC live run. |
| Agent LLM routing | High | No | `--use-openrouter-free --openrouter-model openai/gpt-oss-120b:free` silently did NOT switch providers: `configure_openrouter_free()` uses `os.environ.setdefault`, a no-op for any LLM_* var already set by `.env`. The model name changed but `LLM_BASE_URL` stayed on the Gemini endpoint, which 404'd the OpenRouter model id ("not supported for generateContent"), failing the profile on primary and fallback. The PM could believe agents run on free routing while every call goes to the `.env` provider. Verified in the 22:49 UTC live run; isolation held (live DB max queue id still 91). | Fix dispatched 2026-07-04: force-assign LLM_* env vars when the flag is explicitly passed; print effective model + endpoint in the run banner and outputs so the PM always sees the routing. |
| Output hygiene | Medium | No | The workup unconditionally overwrites `docs/reviews/weekly-loop/<UTC-date>-<ticker>-friction-draft.md`; the 22:49 UTC validation run clobbered this file's completed entries back to the TODO template (recovered from git history). Two same-day runs on one ticker cannot coexist. | Fix dispatched 2026-07-04: never overwrite an existing friction draft; append a numeric suffix instead (engineering default, logged). |

## Keep / Change

- Keep: the `--non-interactive` rail held perfectly — zero approvals, zero applies, zero assumption mutations even while writing to the wrong database.
- Change: every PM-facing surface that shows a number must also show how old the data behind it is; and safety claims in run output (`mode=isolated_snapshot`) must be verified against reality, not inferred from configuration intent.
