# Engineering Validation — 2026-07-05

- Date: 2026-07-05
- Session number: 0 (engineering validation, not PM dry run)
- Tickers: MSFT
- Total time: ~12 min (non-interactive; no PM queue review)
- Counts toward M1 exit criteria: **no** — PM was AFK; non-interactive mode; no queue decisions made

This is the automated engineering pre-flight that ran while the PM was away. It confirms the
full pipeline executes cleanly end-to-end. The actual Task 7 dry run (PM present, interactive)
still needs to happen and will be Session 1.

## What Was Run

Three passes in sequence:

1. **Heuristic smoke** — all 6 profiles, `--agent-mode heuristic`, isolated DB, all caches → exit 0
2. **Routing validation** — single profile (`valuation_review`), `--use-openrouter-free`, isolated DB → exit 0; routing banner confirmed `model=openrouter/free base_url=openrouter.ai`
3. **Full free-model run** — all 6 profiles, `--use-openrouter-free`, isolated DB, all caches → exit 0

## Per-Phase Times (automated, non-interactive)

- Preflight: <1 min
- EDGAR prefetch: ~10 s (cache hit)
- Initial valuation: ~20 s
- Profile review loop (all 6, live LLM): ~8 min
- Final export: <10 s

## Queue Decisions

- Approved/applied: 0 (non-interactive — no decisions made)
- Edited: 0
- Rejected: 0
- Deferred: 0
- Items generated: 7 (queue items 92–98 in isolated DB)

## Friction Items

| Phase | Severity | Manual data surgery? | What happened | Fix/ticket |
| --- | --- | --- | --- | --- |
| comps_analysis (live model) | Low — expected | No | `comps_analysis` returns `completed_no_items` with live model. Root cause confirmed: comps evidence packet has 12 facts but 0 snippets and 1 ref. Live model correctly declines to produce observations with thin anchors per prompt guidance ("do not invent peer multiples"). Heuristic mode produces items because it applies deterministic rules regardless of evidence richness — its comps output is a workflow demonstration, not investment-grade. Behaviour is correct. | None needed. For richer comps evidence, refresh CIQ workbook at session start (gives multi-year peer data). |
| CIQ workbook | Low | No | BAH workbook is 21.2 days old (preflight WARN). Expected — PM refreshes CIQ at start of a real session. | Not a fix — operator workflow. |
| Git dirty | Low | No | 3 uncommitted files (session state, plan doc). Expected during active engineering. | Clean up post-session. |

## Live LLM Observations (notable, not decisions)

All from `openrouter/free` via EDGAR filing evidence:

- `earnings_update`: Revenue +18.3% YoY ($82.9B) — supports raising near-term growth forecast
- `company_analysis`: IRS audit proposing $28.9B tax adjustment + AI goodwill impairment risk — advisory finding
- `industry_analysis`: Competitors' marketplace rules restricting MSFT distribution → margin compression risk
- `risk_review`: Regulatory enforcement, cybersecurity cost/liability, reputation risk (3 advisory findings)
- `valuation_review`: Terminal value = 79.7% of EV flagged as high — sensitivity to terminal assumptions

## Keep / Change

- Keep: Evidence quality=real on all profiles; routing banner on first line of output; isolated DB isolation working; artifact paths consistent
- Change: Investigate `comps_analysis` blank output with live models — should surface a queue item or explain why it chose not to
