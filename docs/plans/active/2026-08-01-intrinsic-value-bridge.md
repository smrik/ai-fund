# Intrinsic-Value Bridge Implementation Plan

> **For agentic workers:** Execute this plan task-by-task with focused tests and commits.

**Goal:** Make the persisted Gordon, exit, and blended intrinsic values visible together on the API, React valuation, and PM markdown surfaces without changing valuation math.

**Vision decisions served:** Decision 7 (React + FastAPI is the working UI), Decision 12 (the weekly PM review loop), and Decision 15 (DCF remains a mandatory current valuation method).

**Architecture:** `api/extracted.py` will read the existing batch row values and `drivers_json`, while taking `method_used` from the existing DCF audit payload. It will expose one backward-compatible top-level presentation contract on both valuation endpoints. React and the two PM markdown renderers will consume that contract or the persisted batch row directly; no surface will recompute or re-round intrinsic values.

**Tech Stack:** FastAPI/Python, pytest, React 19 + TypeScript + Vitest/Testing Library, Markdown documentation.

## Global Constraints

- Keep `base_iv` as the existing headline and add `iv_base` as its canonical alias.
- Expose `iv_gordon`, `iv_exit`, `method_used`, and configured blend weights on summary and DCF payloads.
- Weights are non-null only when `method_used == "blend"`; missing source data remains null.
- Keep the 60% Gordon / 40% Exit blend and do not modify valuation math or the off-limits valuation engine files.
- Cover `blend`, `gordon_only`, and `exit_only` presentation cases; unavailable component values render as an em dash in React.
- Do not write to `data/alpha_pod.db` and do not touch the concurrently edited accounting files or `.agent/session-state.md`.
- Watchlist and compact quote strip remain headline-only.

---

### Task 1: API bridge contract

**Files:**
- Modify: `api/extracted.py`
- Modify: `frontend/src/lib/types.ts`
- Test: `tests/test_api_contracts.py`

**Interfaces:**
- Consumes: `watchlist_row["iv_gordon"]`, `watchlist_row["iv_exit"]`, `watchlist_row["iv_base"]`/`["iv_blended"]`, `watchlist_row["drivers_json"]`, and DCF audit `terminal_bridge.method_used`.
- Produces: top-level `base_iv`, `iv_base`, `iv_gordon`, `iv_exit`, `method_used`, `gordon_weight`, and `exit_weight` on both valuation payloads.

- [x] Add a failing API contract test using a fake persisted row and DCF audit payload. Assert the three values are preserved, `base_iv == iv_base`, `method_used == "blend"`, and weights are `0.6`/`0.4`; add degenerate assertions that weights become null.
- [x] Run the focused API test and observe the expected missing-field failure.
- [x] Add the smallest shared presentation helper in `api/extracted.py` that parses only the stored JSON and reads the persisted values without recomputation.
- [x] Add the optional bridge fields to the TypeScript valuation payload interfaces.
- [x] Run the focused API tests; the contract commit is blocked by the managed sandbox's `.git/index.lock` permission error.

### Task 2: PM markdown bridge

**Files:**
- Modify: `scripts/manual/run_ticker_valuation_flow.py`
- Modify: `scripts/manual/run_guided_ticker_workup.py`
- Test: `tests/test_ticker_valuation_flow.py`
- Test: `tests/test_guided_ticker_workup.py`

**Interfaces:**
- Consumes: the persisted `batch_row` values and `drivers_json`; method status comes from the persisted DCF audit payload already present in each deterministic result.
- Produces: bridge lines in `## PM Verdict Prep` and `## Final Model Snapshot`.

- [x] Add failing renderer tests with `161.40`, `330.11`, and `228.89`, plus `blend` and stored 60/40 weights.
- [x] Add failing degenerate renderer assertions for Gordon-only and Exit-only status.
- [x] Render the three direct row values, method status, and applied/not-applied weight status in both markdown sections.
- [x] Run the focused renderer tests; the markdown commit is blocked by the managed sandbox's `.git/index.lock` permission error.

### Task 3: React valuation bridge

**Files:**
- Modify: `frontend/src/pages/ValuationPage.tsx`
- Test: `frontend/src/test/appRoutes.test.tsx`

**Interfaces:**
- Consumes: summary and DCF payload bridge fields from Task 1.
- Produces: an `Intrinsic Value Bridge` panel on Summary and DCF with the blended headline, Gordon/Exit components, exact weight status, and degenerate-run copy.

- [x] Add failing route assertions for all three values and `60% Gordon / 40% Exit` on Summary and DCF.
- [x] Add failing assertions for Gordon-only and Exit-only rendering, including an em dash and “blend weights were not applied”.
- [x] Implement a small shared bridge panel and render it from both existing surfaces without adding watchlist columns or changing the hero headline.
- [x] Run the focused Vitest test and the frontend build; the React commit is blocked by the managed sandbox's `.git/index.lock` permission error.

### Task 4: Methodology documentation

**Files:**
- Modify: `docs/handbook/excel-template-guide.md`
- Modify: `docs/handbook/valuation-dcf-logic.md`
- Modify: `docs/valuation/05_dcf-valuation.md`
- Modify: `docs/valuation/07_terminal-value.md`
- Modify: `docs/reference/valuation-glossary.md`
- Modify: `docs/design-docs/deterministic-valuation-flow-spec.md`

- [x] Replace stale exit-only/story-derived wording with the actual 60% Gordon / 40% Exit blend.
- [x] Record that the weighting is a PM-level decision and 60/40 is the standing default pending PM review, without inventing a rationale.
- [x] Run a docs text check and strict MkDocs build; MkDocs completed with pre-existing nav/link warnings.

### Task 5: Full verification and handoff

- [x] Run the focused offline Python tests with `C:/Users/patri/miniconda3/envs/ai-fund/python.exe`.
- [x] Run `npm --prefix frontend run test` and `npm --prefix frontend run build`.
- [x] Run `git diff --check`; the worktree still contains the concurrent accounting/session changes and generated artifacts, and Git staging/commit is blocked by `.git/index.lock` permissions.
- [x] Report any other intrinsic-value surfaces found, and note the approved watchlist/compact-strip omission.

## Verification Snapshot

- Affected Python files: 54 passed.
- Frontend: 19 passed; production build passed.
- Python `tests/` suite: 1312 passed, 8 unrelated failures caused by Windows temp-directory permissions in `tests/test_advanced_dcf_model.py`.
