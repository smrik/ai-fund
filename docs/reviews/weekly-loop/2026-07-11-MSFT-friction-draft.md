# Weekly Loop MVP Run - 2026-07-11 - MSFT

- Ticker: MSFT
- Run status: MVP run completed
- Session number: 1 attended full-ticker run
- Run stamp: `20260711T145754Z`
- Agent mode: live Codex (`gpt-5.6-luna`, low effort)
- Total time: not persisted by the runner; timing must be captured manually for the next run
- Verdict: end-to-end path works; weekly-loop timing and queue ergonomics remain open MVP measurements

## Evidence

- Run JSON: `output/guided_workups/MSFT/MSFT-20260711T145754Z.json`
- Run summary: `output/guided_workups/MSFT/MSFT-20260711T145754Z.md`
- Analyst prep pack: `output/guided_workups/MSFT/MSFT-20260711T145754Z-analyst-prep.md`
- Valuation export: `output/guided_workups/MSFT/20260711T145754Z-valuation.json`
- Profile review packets: six `*-review.md` files in `output/guided_workups/MSFT/`

## MVP Assessment

This qualifies as an MVP weekly-loop run because one real ticker completed the intended path:

`CIQ refresh/ingest -> deterministic valuation -> EDGAR evidence -> six judgment profiles -> PM queue review -> analyst prep/export`

The run used the Codex subscription backend, completed without recorded runtime errors, and produced decision-ready queue artifacts. It does not yet prove the one-PM-hour requirement because the runner does not persist total wall-clock time.

## Per-Phase Times

- CIQ stage/ingest: completed; `NASDAQ:MSFT`, 8,601 rows processed, 0 failed
- EDGAR prefetch: completed; 12 filings cached, latest filing date `2026-06-05`
- Initial valuation: completed
- Profile review loop: completed across six profiles
- Final export: completed
- Timing: not captured in persisted output

## Profile Results

| Profile | Status | Observations | Queue items |
| --- | --- | ---: | ---: |
| earnings_update | completed_no_items | 0 | 0 |
| company_analysis | completed_with_items | 4 | 4 |
| industry_analysis | completed_with_items | 1 | 1 |
| comps_analysis | completed_with_items | 3 | 2 |
| risk_review | completed_with_items | 2 | 2 |
| valuation_review | completed_with_items | 2 | 2 |

- Total observations: 12
- Total queue items: 11
- Runtime errors: 0
- Source quality: real for all profiles

## Queue Decisions

- Approved/applied: 0
- Edited: 0
- Rejected: 0
- Deferred: 2
- Skipped: 9
- Deferred items: 124 (IRS tax exposure), 126 (AI competition/margin pressure)
- Item 123 was attempted as approve+apply but failed the preview-fingerprint guard and was then skipped.

## Friction Items

| Phase | Severity | Manual data surgery? | What happened | Fix/ticket |
| --- | --- | --- | --- | --- |
| Queue review | Medium | No | Advisory findings such as item 124 correctly had no apply action; they require a PM judgment before becoming model changes. | Keep advisory items non-mutating; optionally add a guided “create assumption change” path later. |
| Queue review | Medium | No | Item 123 displayed a valid preview but approve+apply failed with “must be previewed after the latest edit”. | Fix preview fingerprint lifecycle and add a regression test. |
| Queue application | Low/Medium | No | Applying an assumption pack immediately is slower than batching independent approved changes. | Add approve-now/apply-at-end mode with one combined preview and one deterministic rebuild. |
| Output quality | Low | No | Some generated comps values contained excessive floating-point precision. | Formatting cleanup; not an MVP blocker. |

## Keep / Change

- Keep: six-profile evidence-to-queue pipeline, real evidence anchoring, Codex routing provenance, deterministic preview before model mutation, exported prep packet.
- Change later: capture wall-clock timing, repair stale preview handling, batch independent assumption applications, improve numeric formatting.

## MVP Conclusion

The run is accepted as the first documented MVP run. It demonstrates that the core weekly loop can execute on a real ticker and leave durable PM-review artifacts. The next milestone is repeated use on another real ticker with timing captured, not additional feature expansion.
