# PM Queue Review Checklist

Use this during the Task 7 dry-run session with the PM to exercise the PM Decision Queue on a real ticker. This page is the checklist of record for Weekly Loop v1 Task 5 under the supervisor-reduced scope from 2026-07-03.

Scope note: API/frontend servers, Playwright runs, live queue click-through, and frontend/API code changes were intentionally out of scope for this pass. UI gaps discovered during the live session go to the weekly-loop friction log; product-decision gaps go to the PM under the interview-first rule.

Before claiming UI health, rerun the route-matrix runner during the live checklist session:

```powershell
C:\Users\patri\miniconda3\envs\ai-fund\python.exe scripts/manual/review_react_route_matrix.py
```

| Item | What To Do | Where To Look | Expected Result | Status |
| --- | --- | --- | --- | --- |
| Advisory finding visible with evidence anchors | Open the PM Queue for a ticker with advisory finding items and inspect one advisory row/card. | Route: `/ticker/<TICKER>/valuation?view=PM%20Queue`; files: `frontend/src/pages/ValuationPage.tsx`, `api/main.py`, `src/stage_04_pipeline/pm_decision_queue.py` | The advisory finding title, summary, source quality, evidence packet ids, and evidence anchor ids are visible enough for the PM to trace the claim. | NOT YET RUN — scheduled for the Task 7 dry-run session with the PM |
| Assumption change proposal previews delta and target modes with resolved absolute values | Preview one target-mode proposal and one delta-mode proposal before approval. | Route: `/ticker/<TICKER>/valuation?view=PM%20Queue`; API: `POST /api/tickers/{ticker}/pm-decision-queue/{item_id}/preview`; files: `api/main.py`, `src/stage_04_pipeline/pm_decision_queue.py` | The preview shows the active proposal, resolved absolute target values, skipped fields if any, preview timestamp, and preview fingerprint. Delta proposals resolve to absolute values before approval. | NOT YET RUN — scheduled for the Task 7 dry-run session with the PM |
| PM-edited proposal preserves original magnitude in history | Edit a proposal value, preview again, then inspect the item history before approval. | Route: `/ticker/<TICKER>/valuation?view=PM%20Queue`; API: `POST /api/tickers/{ticker}/pm-decision-queue/{item_id}/edit`; files: `api/main.py`, `src/stage_04_pipeline/pm_decision_queue.py` | The edited proposal is active, the previous proposal remains available through decision history/events, and the PM can see what changed versus the original magnitude. | NOT YET RUN — scheduled for the Task 7 dry-run session with the PM |
| Pack reviewed as a unit | Open an assumption-change pack with multiple proposals and review the whole pack before actioning any item. | Route: `/ticker/<TICKER>/valuation?view=PM%20Queue`; supporting route: `/ticker/<TICKER>/research`; files: `frontend/src/pages/ValuationPage.tsx`, `frontend/src/pages/ResearchPage.tsx` | The PM can review the pack-level title, summary, evidence links, profile context, and all proposals together before approve/reject/defer. | NOT YET RUN — scheduled for the Task 7 dry-run session with the PM |
| Reject/defer with reason | Reject one low-value item and defer one item that needs more evidence, entering a short reason for each. | Route: `/ticker/<TICKER>/valuation?view=PM%20Queue`; API: `POST /api/tickers/{ticker}/pm-decision-queue/{item_id}/reject` and `/defer`; files: `api/main.py`, `src/stage_04_pipeline/pm_decision_queue.py` | Reject and defer actions require a reason, update item status, and preserve the reason in decision history/events. | NOT YET RUN — scheduled for the Task 7 dry-run session with the PM |
| Stale-preview returns 409 and the UI surfaces it | Preview an assumption-change item, edit or otherwise stale the proposal, then attempt approval without re-previewing. | Route: `/ticker/<TICKER>/valuation?view=PM%20Queue`; API: `POST /api/tickers/{ticker}/pm-decision-queue/{item_id}/approve`; file: `api/main.py` | The API returns HTTP 409 for stale preview approval, and the UI displays the conflict clearly enough that the PM knows to preview again. | NOT YET RUN — scheduled for the Task 7 dry-run session with the PM |
| Decided items remain searchable | After approve/reject/defer, filter or search the queue for decided statuses. | Route: `/ticker/<TICKER>/valuation?view=PM%20Queue`; API: `GET /api/tickers/{ticker}/pm-decision-queue?status=approved`, `?status=rejected`, `?status=deferred`; files: `frontend/src/pages/ValuationPage.tsx`, `frontend/src/lib/api.ts`, `api/main.py` | Approved, rejected, and deferred items remain findable after decision and retain enough detail for audit review. | NOT YET RUN — scheduled for the Task 7 dry-run session with the PM |

## Verification

Run from the repository root on 2026-07-03:

```powershell
C:\Users\patri\miniconda3\envs\ai-fund\python.exe -m pytest tests/test_pm_decision_queue_adapter.py tests/test_agentic_handoff_mvp_flow.py tests/test_api_contracts.py -q -p no:cacheprovider
```

Result: PASS. The gate reported `30 passed, 3 warnings in 5.42s`. The warnings were third-party `edgar` deprecation warnings, not queue test failures.

MkDocs strict build for this documentation change must also pass before handoff:

```powershell
C:\Users\patri\miniconda3\envs\ai-fund\python.exe -m mkdocs build --strict
```

Result: PASS. The final run exited `0` and built the docs successfully. It printed the existing Material/MkDocs 2.0 notice and an informational list of docs pages that are not in explicit nav.
