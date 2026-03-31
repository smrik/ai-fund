I'm using the writing-plans skill to create the implementation plan.
# React UI parity implementation plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to execute this plan task-by-task.

**Goal:** Close the remaining React parity gaps by unifying the page hero/top matter, fixing the valuation charts, polishing the Market/Sentiment/Factor/Audit surfaces, and refreshing the Playwright capture helper.

**Architecture:** Keep the frontend as a thin Vite/React shell over the existing FastAPI transport. Centralize shared layout pieces (hero, defs) under `frontend/src/components`, keep data shaping inside the relevant page files, and leave deterministic valuation logic in the Python helpers.

**Tech Stack:** Vite + React + TanStack Query + Typescript + Playwright CLI + shell helpers.

---

### Task 1: Share a consistent page hero for every ticker route

**Files:**
- Create: `frontend/src/components/PageHero.tsx`
- Modify: `frontend/src/pages/OverviewPage.tsx`, `frontend/src/pages/MarketPage.tsx`, `frontend/src/pages/ResearchPage.tsx`, `frontend/src/pages/AuditPage.tsx`, `frontend/src/pages/ValuationPage.tsx`, `frontend/src/components/TickerLayout.tsx`, `frontend/src/styles/global.css`
- Test: `npm --prefix frontend run test -- --run src/test/appRoutes.test.tsx`

**Step 1:** Author a reusable `PageHero` component that accepts title, subtitle, chip data, and optional panels/actions; rely on `workspace` for shared metrics (`action`, `conviction`, `current_price`, `base_iv`, `upside_pct_base`, `latest_snapshot_date`).
**Step 2:** Drop the duplicated `<section className="page-hero">` blocks in overview/market/research/audit/valuation and wire them to the new component so the entire row keeps the same gradient/background (fix the “black strip” artifact on valuation).
**Step 3:** Update CSS to keep the hero consistent (make `.page-hero` layout grid shared, tighten spacing, keep `hero-chip` look). Ensure the valuation route now renders the hero in the same palette and still exposes the `TickerLayout` actions when the `valuation` query param is active.
**Step 4:** Run the specified frontend tests and commit/record the hero change to confirm `appRoutes` still render.

### Task 2: Make the valuation time-series charts plot time along X

**Files:**
- Modify: `frontend/src/pages/ValuationPage.tsx`, `frontend/src/lib/format.ts` (if needed), `frontend/src/styles/global.css` (if axis labels need tweaks)
- Test: `npm --prefix frontend run test -- --run src/test/appRoutes.test.tsx`

**Step 1:** Extend `normalizeTimeAxisValue` (or equivalent) so numeric years/dates produce a `sortValue` and label derived from the source (without forcing fallback “Point #”).
**Step 2:** Update `renderTimeSeriesChart` to compute `toX` from the normalized sortValue instead of the sequence index, and propagate the x-axis label/footprint so the `Year` labels show up horizontally (FCFF curve and multiples should now run left-to-right). Keep the existing legend/area helpers and ensure the chart gracefully handles sparse points.
**Step 3:** Adjust any supporting styles or helper text so the axis label and footnotes describe the actual time axis (e.g., “Year” and “Date” footers).
**Step 4:** Run the frontend test suite and verify the chart functions still render via story/test snapshots (if any) or by manual review (see Task 5 below).

### Task 3: Enrich Market/Sentiment/Factor exposures so they reflect parity requirements

**Files:**
- Modify: `frontend/src/pages/MarketPage.tsx`, `frontend/src/styles/global.css`, `frontend/src/lib/format.ts` (if new formatting helper needed)
- Test: `npm --prefix frontend run test -- --run src/test/appRoutes.test.tsx`

**Step 1:** Ensure the yield-curve section only renders the ordered chart (no table fallback) and add tooltip text describing maturities vs yield (update `renderOrderedSeriesChart` helper if needed). Confirm the curve insight copy references the latest snapshot so the chart shows data without scrolling.
**Step 2:** Add more explicit sentiment reasoning around the score (pull the `buildSentimentReasoning` copy into a panel, include the numeric score in the hero chips or separate card, and shrink the existing grid cards so the section feels denser rather than sparse).
**Step 3:** Present factor definitions via hoverable badges and a persistent mini-panel (`MetricDefinitionBadge` plus `definition-grid`) so the exposure panel reads as a reference; keep the attribution bars but add short blurbs summarizing the takeaways (e.g., “Market Beta drives 54% of the explanation”).
**Step 4:** Rerun the frontend tests and verify that the Market view still loads via Playwright (see Task 5) with the new layout.

### Task 4: Surface Audit data earlier and keep it from deferring until scroll

**Files:**
- Modify: `frontend/src/pages/AuditPage.tsx`, `frontend/src/styles/global.css`
- Test: `npm --prefix frontend run test -- --run src/test/appRoutes.test.tsx`

**Step 1:** Reorganize the audit summary so the most important panels appear above the fold (move the `SummaryPanel` content into a `grid-cards` stack that renders even before the tab groups, and ensure `FlagsPanel` sections are prepared with sanitized titles so they appear once the query resolves).
**Step 2:** Double-check that the `selectedView` tab buttons are sticky and that data for DCF/Filings/Comps/Flags loads without needing extra scroll events (pull heavy tables into collapsible panels or default placeholders with nav anchors).
**Step 3:** Validate via Playwright (Task 5) that the Audit route now shows data in the initial screenshot.

### Task 5: Refresh the quiet Playwright capture helper and docs

**Files:**
- Modify: `scripts/manual/capture_react_dev_pages.py`, `docs/handbook/react-playwright-review-loop.md`
- Test: `python scripts/manual/capture_react_dev_pages.py --one-page watchlist`

**Step 1:** Rewrite the capture helper so it keeps the same flag set (`--full`, `--one-page`, `--browser`, `--wait-ms`, `--output-dir`, `--session`) but centralizes the Playwright loop in a short script that only prints the final screenshot filenames (and errors if any). Use `shutil.which` once per run, reuse the same session, avoid printing command-by-command noise, and document the helper’s behavior at the bottom of `docs/handbook/react-playwright-review-loop.md` (update the doc snippet if the behavior or output path changed).
**Step 2:** Run the new script for a single route (Smoke set or `--one-page watchlist`) to verify it still produces PNGs under `output/playwright/dev-verify/<stamp>/` and prints only the file list.
**Step 3:** Mention the new helper in the same doc section so the workflow instructions stay current.

---

After these tasks, run `npm --prefix frontend run build` (if the hero or chart changes affect the bundle) and capture at least one Playwright screenshot set (via Task 5) before claiming the work is complete.
