# Session State

**Updated:** 2026-07-11T12:35:00+02:00
**Agent:** Codex CLI
**Project:** C:/Projects/03-Finance/ai-fund

## Current Task
Work Package 3: final live MSFT guided ticker workup and financial soundness audit.

## Recent Actions
- Ran the exact requested isolated live MSFT workup with OpenRouter free routing; exit code was 0.
- All six profiles failed at the live agent call with HTTP 401 `Missing Authentication header`; no parse-error profile rerun was applicable.
- Audited the run artifacts: deterministic snapshot arithmetic and scenario facts reconcile, SEC metrics use 2025-06-30 with revenue CAGR 0.1530, and current-run evidence map packet IDs are 172-177.
- Found material prep-pack base-IV drift (276.43 claim versus final 274.71), stale cache warnings, an unrendered current queue (0 items), and TODO placeholders in the friction draft.
- Read-only Excel scan found 12 sheets, 308 formulas, and no formula/error strings.

## Next Steps
- Deliver the Work Package 3 run result and PASS/FAIL audit to the PM.
- Do not commit; preserve the existing unrelated dirty worktree changes and database artifacts.

## Known Issues
- Live OpenRouter free routing returned HTTP 401 `Missing Authentication header` for all six profiles.
- Historical financials and market cache entries are flagged stale at about 5.4/5.5 days.
- Analyst prep claim says Base DCF IV 276.43, but final snapshot/valuation JSON use 274.71; friction draft contains TODO placeholders.
- The working tree contains unrelated pre-existing modifications and untracked artifacts. The workup used an isolated DB snapshot; `data/alpha_pod.db` was not directly touched.

## Notes
- Run artifact root: `C:\Users\patri\AppData\Local\Temp\claude\C--Projects-03-Finance-ai-fund\f730ddc5-0ae4-45de-8ceb-51825d8685c2\scratchpad\deliverable\MSFT`.
- Retry requires valid OpenRouter authentication; the user allowed only parse-error profile reruns, so no profile was rerun.
