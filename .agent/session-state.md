# Session State

**Updated:** 2026-07-04 (post-merge handoff)
**Agent:** Claude Code (supervisor) + Codex CLI (implementation)
**Project:** C:/Projects/03-Finance/ai-fund

## Current Task
M1 Weekly Loop v1 engineering surface is COMPLETE and merged to main via PR #77
(squash commit `4d3fbe8`, all 7 CI checks green including the new
backend-full-tests deep gate). Local repo is on a clean `main`;
`plan/m1-weekly-loop-v1` is deleted.

## What Shipped (PR #77 highlights)
- CI deep gate (`backend-full-tests`: full offline suite on fresh runner)
- `scripts/manual/weekly_preflight.py` (+ edgartools check) and runbook/friction-log/queue-checklist docs
- Guided ticker workup CLI with: verified `--isolated-db` (all write paths resolve DB at call time), Data Freshness sections with [STALE] markers, working `--use-openrouter-free` routing (BaseAgent resolves LLM_BASE_URL/LLM_MODEL from env at construction), persisted per-run valuation JSON with CIQ historicals, friction-draft no-clobber
- Five Codex-bot review rounds fully addressed (9 threads replied + resolved)
- Systemic fix theme: import-time binding → use-time resolution (db/schema get_connection, BaseAgent, edgar_client, filing_retrieval, edgar_prefetch)
- Semantic cache: fallback-scored filing bundles are never persisted

## Next Steps (PM-facing, in order)
1. Task 7 dry run: PM runs `docs/handbook/weekly-loop-session.md` end-to-end on one
   ticker with an agent session open; use `docs/handbook/pm-queue-review-checklist.md`
   for the queue click-through (all items currently NOT YET RUN).
2. Sessions 1-4 (July): the M1 exit criteria clock. Real tickers, friction log per session.
3. Suggested agent routing for live sessions:
   `--use-openrouter-free --openrouter-model "openai/gpt-oss-120b:free" --openrouter-fallback-models "openai/gpt-oss-120b"`
   (requires OPENROUTER_API_KEY in env; run banner now displays effective routing).
   Standing PM rule (2026-07-03): state the model and expected cost and get PM
   confirmation BEFORE any live-agent run or coding-agent dispatch; the PM prefers
   free/cheap models for the analysis agents and does not want surprise API bills.
4. Optional final validation: rerun the single-profile live-agent isolated smoke to
   confirm agents now actually reach OpenRouter post-BaseAgent-fix (last attempt
   pre-fix failed with Gemini 404s).

## Known Issues / Machine-local
- `.tmp-tests/`, `.codex-pytest-temp/`, `.pytest_cache/` have broken ACLs from
  sandboxed agent runs (owned by another principal). Cleanup needs an elevated
  PowerShell, run from the repo root:

  ```powershell
  foreach ($d in ".tmp-tests", ".codex-pytest-temp", ".pytest_cache") {
    takeown /f $d /r /d y
    icacls $d /reset /t /c /q
    Remove-Item -Recurse -Force $d
  }
  ```

  Until then the full suite locally fails ~25 tests on `.tmp-tests` permissions (CI unaffected).
- `data/alpha_pod.db.polluted-20260703.bak` (293MB, untracked) is the forensic backup
  from the 2026-07-03 isolation-leak incident; live DB was restored and verified clean
  (max queue id 91). Delete the .bak when no longer wanted.
- Codex GitHub review bot is quota-exhausted; final head f53720d had supervisor review + CI only.

## Carry-over open items (from 2026-06-15 session, still valid)
- Bridge-mode guard: if a ticker returns `gordon_formula_mode == "bridge"`, add support in
  `_Context.reconcile()` / `_build_dcf_base` before removing the guard.
- Needs PM sign-off: retire legacy openpyxl writer; keep-or-drop PowerQuery staging path.
  Do not rip out `src/stage_04_pipeline/export_service.py` without sign-off.
- TTWO CIQ history (optional): pull a CIQ Standard workbook to populate its trend tab.
