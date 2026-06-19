# Weekly Loop v1 Implementation Plan (Milestone 1)

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.
> **For Codex:** Use `/goals` with the goal prompt below, then execute this file in order. Use TDD where practical, keep changes small, and verify after each task.

| Field | Value |
| --- | --- |
| Status | Active |
| Milestone | M1 — Weekly Loop v1 ([Six-Month Execution Roadmap](../future/2026-06-12-six-month-execution-roadmap.md)) |
| Vision decisions served | 12 (loop runs for real), 2 (cadence), 10/11 (workflow rules in practice) |
| Created | 2026-06-12 |

**Goal:** The PM runs the full research loop — screen → batch valuation → pick names → Analyst Prep Pack → evidence → PM Decision Queue → decisions → exported note — on real tickers, every week, with friction captured and fixed between sessions.

**Architecture:** No new subsystems. M1 is enablement and operations: a session runbook, a preflight check, a friction log, full-suite CI, and a recurring fix cycle driven by what real sessions expose. The deterministic/LLM boundary and the PM Decision Queue approval bridge are unchanged.

**Context:** The Agentic Handoff Hardening and Analyst Prep Pack plans shipped (verified 2026-06-12: hardening gate 26/26 green, synthetic-evidence markers absent, full suite 726 passed + 2 local-only skips in a clean worktree). The loop machinery exists; M1 proves it in weekly use.

---

## `/goals` Prompt

```text
Implement the Alpha Pod Weekly Loop v1 plan from docs/plans/active/2026-06-12-weekly-loop-v1.md.

Primary objective: make the weekly PM research loop runnable end-to-end with one runbook, one preflight check, and a friction log, so four consecutive real weekly sessions can happen in July.

Non-negotiables:
- No new Streamlit features (dashboard/ is frozen; Vision Decision 7).
- LLM code never touches the deterministic computation layer.
- Engineering ambiguities: decide conservatively and log in the plan/PR. Finance semantics (thresholds, ranges, metric meaning): stop and ask the PM.
- Every task ships with verification commands and targeted tests where code changes.
- Smallest working version first; the runbook documents existing commands before anyone builds new orchestration.

Work task-by-task. After each task, run the listed verification and report pass/fail with file references.
```

## Exit Criteria (from the roadmap — PM-verifiable)

1. Four consecutive weekly sessions completed and logged
2. One full ticker investigation fits in ≤1 PM-hour
3. Every manual-data-surgery incident is logged with a fix or a ticket
4. Queue workflow (PM-edited proposals, advisory findings, packs) exercised on real names

## Task 1: Full Offline Suite In CI

**Why first:** Today (2026-06-12) proved CI's three-file pytest subset hides fresh-checkout breakage. Every later task's verification is only trustworthy once CI runs the real gate. Suite runtime is ~2:15 — well within CI budget.

**Files:**
- Modify: `.github/workflows/ci.yml`
- Test: existing suite (no new tests)

**Steps:**

1. Add a `backend-full-tests` job: checkout, set up Python per existing jobs, `pip install -r requirements.txt pytest`, then `python -m pytest tests -q -p no:cacheprovider`.
2. Keep the existing fast jobs unchanged (they gate quickly; the full job is the deep gate).
3. If any test needs network or local-only assets, it must already skip cleanly — fix with skip-with-reason, never delete the test.
4. Confirm the job passes on the PR for this plan.

**Verification:**

```powershell
gh pr checks <pr-number>
```

**Expected:** All jobs including `backend-full-tests` green.

**Commit message:** `ci: run full offline pytest suite as a deep gate`

## Task 2: Session Preflight Check

**Why:** Sessions must not die mid-flight on stale data or a broken env. This also closes the M0 "environment drift" item by making drift visible instead of tribal knowledge.

**Files:**
- Create: `scripts/manual/weekly_preflight.py`
- Test: `tests/test_weekly_preflight.py`

**Steps:**

1. Write a deterministic preflight that checks and reports PASS/WARN/FAIL per item:
   - Python interpreter is the `ai-fund` env (warn with the documented path if not)
   - required packages importable (pytest, ruff optional-warn, core deps)
   - SQLite DB reachable and schema tables present
   - CIQ workbook present; staleness in days (warn beyond a threshold constant)
   - market-data cache freshness (warn-only)
   - `FRED_API_KEY` presence (warn-only)
   - git: current branch, dirty/clean, ahead/behind origin
2. Exit code 0 on PASS/WARN, 1 on FAIL. Output is a compact table, no side effects.
3. Threshold constants live at the top of the script with comments; they are engineering defaults — log them in the PR for PM review, do not block on asking.
4. Unit-test the check functions with temp fixtures (missing DB, stale file timestamps); no live network in tests.

**Verification:**

```powershell
C:\Users\patri\miniconda3\envs\ai-fund\python.exe -m pytest tests/test_weekly_preflight.py -q
C:\Users\patri\miniconda3\envs\ai-fund\python.exe scripts/manual/weekly_preflight.py
```

**Expected:** Tests pass; preflight runs on this machine and reports honestly.

**Commit message:** `feat: add weekly session preflight check`

## Task 3: Weekly Session Runbook

**Why:** The loop already works as separate commands; nobody (including the PM) should re-derive the sequence each Saturday. Documentation before orchestration.

**Files:**
- Create: `docs/handbook/weekly-loop-session.md`
- Modify: `docs/handbook/index.md` (link it)
- Modify: `mkdocs.yml` if nav lists handbook pages explicitly

**Steps:**

1. Write a time-boxed operator guide with exact commands for each phase:
   - Preflight (Task 2 script)
   - Screen: `python -m src.stage_01_screening.stage1_filter`
   - Batch valuation: `python -m src.stage_02_valuation.batch_runner --top 50`
   - Pick 1-2 names (PM judgment — the runbook only says where to look: ranked output, assumption register flags)
   - Analyst Prep: `scripts/manual/run_analyst_prep_pack.py --ticker <T>` with the flag set that worked in the 2026-06-08 MSFT smoke
   - App review: `pwsh -File scripts/manual/launch-mvp-app.ps1`, queue review route
   - Decisions: preview → edit/approve/reject/defer in the PM Queue
   - Export: research note / Excel via the export flow
   - Close: friction log entry (Task 4 template)
2. Each phase gets a target time box summing to ≤60 min for one name.
3. Verify each documented command actually runs before committing (cache-only/offline flags where applicable); fix the doc, not the code, unless the command is genuinely broken — broken commands become friction-log entries plus a fix task.
4. Keep it one page; link out to deeper docs instead of duplicating.

**Verification:**

```powershell
C:\Users\patri\miniconda3\envs\ai-fund\python.exe -m mkdocs build --strict
```

**Expected:** Strict docs build passes; every command in the runbook was executed once during authoring.

**Commit message:** `docs: add weekly loop session runbook`

## Task 4: Friction Log Scaffold

**Files:**
- Create: `docs/reviews/weekly-loop/README.md`
- Create: `docs/reviews/weekly-loop/_template.md`

**Steps:**

1. Template fields: date, session number, tickers, total time, per-phase times, friction items (each: what happened, phase, severity, manual-data-surgery yes/no), queue items decided (approved/edited/rejected/deferred counts), one keep/one change.
2. README states the convention: one file per session named `YYYY-MM-DD-session-NN.md`; top friction item becomes the next fix task; manual-data-surgery incidents must each get a fix or a tech-debt-tracker entry (exit criterion 3).
3. Link the folder from the runbook's close phase and from `docs/reviews/` usage in `docs/PLANS.md` if wording needs it.

**Verification:**

```powershell
C:\Users\patri\miniconda3\envs\ai-fund\python.exe -m mkdocs build --strict
```

**Commit message:** `docs: add weekly loop friction log scaffold`

## Task 5: Queue-In-Anger Checklist And Gap Fixes

**Why:** Exit criterion 4. The queue passed its tests; M1 needs proof the PM-facing flow works on a real name, and a place to record what doesn't.

**Files:**
- Create: `docs/handbook/pm-queue-review-checklist.md`
- Possibly modify: `frontend/src/pages/*`, `api/main.py` (only for gaps the checklist exposes)

**Steps:**

1. Write a one-page checklist covering: advisory finding visible with evidence anchors; assumption change proposal previews delta AND target modes with resolved absolute values; PM-edited proposal preserves original magnitude in history; pack reviewed as a unit; reject/defer with reason; stale-preview returns 409 and the UI surfaces it; decided items remain searchable.
2. Run the checklist against a real ticker run (isolated DB acceptable) using the runbook flow.
3. Each checklist failure becomes either a small fix in this task (if mechanical) or a friction-log entry plus follow-up (if scope-bearing). UI gaps that require new product decisions: stop and ask the PM (this is where the interview-first rule bites).
4. Re-run the route matrix before claiming UI health: `scripts/manual/review_react_route_matrix.py`.

**Verification:**

```powershell
C:\Users\patri\miniconda3\envs\ai-fund\python.exe -m pytest tests/test_pm_decision_queue_adapter.py tests/test_agentic_handoff_mvp_flow.py tests/test_api_contracts.py -q
rtk npm --prefix frontend test -- --run
```

**Expected:** Gates green; completed checklist committed with pass/fail per item and links to follow-ups.

**Commit message:** `docs: add pm queue review checklist with verified pass/fail state`

## Task 6: Guided Full-Ticker Workup CLI

**Why:** The separate commands now work, but the weekly loop needs one PM-driven operator shell that pauses after each analyst profile and routes every model mutation through the PM Decision Queue.

**Files:**
- Create: `scripts/manual/run_guided_ticker_workup.py`
- Create: `scripts/manual/pm_decision_queue.py`
- Test: `tests/test_guided_ticker_workup.py`
- Modify: `docs/handbook/workflow-end-to-end.md`
- Create/modify: `docs/handbook/weekly-loop-session.md`
- Create/modify: `docs/reviews/weekly-loop/README.md`, `docs/reviews/weekly-loop/_template.md`

**Steps:**

1. Add a guided single-ticker CLI:
   - stages the CIQ workbook and pauses for manual refresh/save;
   - ingests the refreshed workbook;
   - prefetches/checks EDGAR filings;
   - builds the initial deterministic valuation;
   - runs one Agentic Handoff Profile at a time;
   - writes a per-profile review packet with Evidence Packet observations, PM questions, new Queue items, proposed changes, preview impact, and standalone queue decision commands before prompting for a decision;
   - pauses after each profile for PM review of the packet and new Queue items;
   - supports approve+apply, inline target edit, reject, defer, and skip;
   - rebuilds valuation after approved/applied assumption changes;
   - writes JSON, Markdown, per-profile review Markdown, Analyst Prep Markdown, optional Excel export, and a friction-log draft.
2. Defaults are live-agent/live-DB for real use, but every apply requires explicit `APPLY` confirmation. `--isolated-db`, `--agent-mode heuristic`, and `--non-interactive` exist for safe rehearsal; non-interactive mode never approves or applies.
3. Keep Quartr transcripts optional for this task. Core success is CIQ + EDGAR + live agents; transcript availability can enrich `earnings_update` once the evidence-acquisition plan's transcript tasks land.
4. Document the command as the preferred CLI-first weekly ticker workup path; keep UI work out unless the CLI exposes a hard blocker.

**Verification:**

```powershell
C:\Users\patri\miniconda3\envs\ai-fund\python.exe -m pytest tests/test_guided_ticker_workup.py -q
C:\Users\patri\miniconda3\envs\ai-fund\python.exe -m pytest tests/test_ciq_refresh.py tests/test_pm_decision_queue_adapter.py tests/test_agentic_handoff_mvp_flow.py tests/test_evidence_packet_builders.py -q
C:\Users\patri\miniconda3\envs\ai-fund\python.exe scripts/manual/run_guided_ticker_workup.py --ticker MSFT --agent-mode heuristic --isolated-db --non-interactive --skip-ciq-stage --edgar-summary-only --market-cache-only --edgar-cache-only --no-export-xlsx
```

**Expected:** Tests pass; smoke run writes a guided workup bundle with per-profile review packets under `output/guided_workups/MSFT/` and a friction draft under `docs/reviews/weekly-loop/` without approving any queue item.

**Commit message:** `feat: add guided ticker workup CLI for PM-driven weekly loop`

## Task 7: First Session Dry Run (agent-assisted, PM present)

**Why:** Before session 1 counts toward the exit criteria, one dry run shakes out runbook errors cheaply.

**Steps:**

1. PM runs the runbook end-to-end on one ticker with an agent session open for immediate fixes.
2. Agent fixes mechanical breakage on the spot (wrong flags, missing paths); anything judgment-shaped goes to the friction log.
3. Produce the first friction log entry from the template and update the runbook's time boxes with observed reality.

**Verification:** First file exists in `docs/reviews/weekly-loop/`; runbook updated in the same change.

**Commit message:** `docs: record weekly loop dry run and calibrate runbook`

## Recurring Cycle (sessions 1-4, July)

Not numbered tasks — this is the operating rhythm after Task 6:

1. **PM:** run the weekly session per runbook; write the friction log entry.
2. **Agent:** between sessions, take the top friction items as small fix tasks (interview-first if a fix is scope-bearing; conservative-and-logged if mechanical).
3. **Both:** after session 4, score the exit criteria and update this plan's status. If criteria pass, M1 closes and Milestone 2 (React parity scoped by what these sessions actually used) starts with its own plan.

## Out Of Scope (M1)

- New Streamlit anything (frozen)
- Event triggers, schedulers, overnight runs (M3)
- New data sources; CIQ staleness is *reported* by preflight, not solved (Vision Decision 9)
- React parity work beyond gaps that block the loop (M2 owns parity)
- IBKR, calibration layer (Phase D)
