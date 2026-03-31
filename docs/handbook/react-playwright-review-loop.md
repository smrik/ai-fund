# React Playwright Review Loop

This is the canonical visual verification workflow for the React quote-terminal UI.

Use it when:

- validating a route change
- checking whether a UI bug is a render issue or a data issue
- reviewing the full watchlist plus ticker route matrix
- gathering screenshot evidence before claiming the frontend is healthy

## Core Lessons

These are the main things learned while stabilizing the current React shell.

### 1. `200 OK` is not enough

A route can return `200` and still be wrong:

- placeholder text may still be on screen
- the page may be reading the wrong payload field
- the view may look “loaded” but still be showing empty fallback content

Always inspect screenshots, not just HTTP status.

### 2. Clean browser console is not enough

The browser console can show `0` errors and `0` warnings while the UI is still wrong.

Examples already hit in this repo:

- valuation screenshots captured before the async query settled
- `Research` rendering a raw memo blob or fallback state because it was mapped to the wrong payload shape

Console cleanliness is one signal, not the verdict.

### 3. Same-side stack matters

Playwright review is most reliable when frontend and API are on the same side.

Best path in this repo:

```bash
bash scripts/manual/launch-react-wsl.sh
```

This runs both services on WSL and avoids cross-side proxy failures.

### 4. The served `dist/` bundle is the stable review target

For this repo, the best review path is not the Vite dev server.

The current stable review path is:

- build `frontend/dist`
- serve it through [`serve_frontend_dist.py`](/mnt/c/Projects/03-Finance/ai-fund/scripts/manual/serve_frontend_dist.py)
- proxy `/api/*` to FastAPI

That is what [`launch-react-wsl.sh`](/mnt/c/Projects/03-Finance/ai-fund/scripts/manual/launch-react-wsl.sh) does.

### 5. Use required and forbidden text

For screenshot automation, wait for both:

- required markers that prove the view actually loaded
- forbidden markers that prove the placeholder state is gone

Examples:

- `Valuation Summary` should include real scenario content
- it should not still contain fallback copy like “Scenario summary will appear here”

### 6. Distinguish data-empty from render-broken

If a card is blank, check the API payload before changing UI code.

Good debugging sequence:

1. load the route
2. capture screenshot
3. inspect the direct API response
4. compare the rendered page against the payload shape

This is how the `Research` mapping bug was separated from legitimate empty-state cards.

## Recommended Workflow

### Step 1: Start the stable review stack

```bash
bash scripts/manual/launch-react-wsl.sh --stop
bash scripts/manual/launch-react-wsl.sh
bash scripts/manual/launch-react-wsl.sh --status
```

Expected URLs:

- frontend: `http://127.0.0.1:4173`
- API: `http://127.0.0.1:8000`

### Step 2: Set the Playwright environment

```bash
export HOME=/tmp/codex-playwright-home
export TMPDIR=/tmp
export TMP=/tmp
export TEMP=/tmp
export PWCLI=/mnt/c/Users/patri/.codex/skills/playwright/scripts/playwright_cli.sh
```

This avoids temp-path problems inherited from Windows paths.

### Step 3: Run the full route matrix

```bash
python3 scripts/manual/review_react_route_matrix.py
```

Current canonical matrix:

- watchlist
- overview
- valuation-summary
- valuation-dcf
- valuation-comparables
- valuation-multiples
- valuation-assumptions
- valuation-wacc
- valuation-recommendations
- market
- research
- audit

Artifacts are written to:

```text
output/playwright/route-matrix/<timestamp>/
```

Each run contains:

- one `manifest.json`
- one folder per route
- route-local `snapshot`, `console`, and `screenshot` files

## Artifact Review

### Manifest

Start with:

- [`manifest.json`](/mnt/c/Projects/03-Finance/ai-fund/output/playwright/route-matrix/20260329-130142/manifest.json)

Check:

- route count
- page URL
- screenshot path
- `console_clean`

### Screenshots

Review at least:

- landing page
- one representative valuation view
- research
- audit

Current clean reference set:

- watchlist: [`page-2026-03-29T11-01-49-785Z.png`](/mnt/c/Projects/03-Finance/ai-fund/output/playwright/route-matrix/20260329-130142/watchlist/page-2026-03-29T11-01-49-785Z.png)
- overview: [`page-2026-03-29T11-01-59-896Z.png`](/mnt/c/Projects/03-Finance/ai-fund/output/playwright/route-matrix/20260329-130142/overview/page-2026-03-29T11-01-59-896Z.png)
- valuation summary: [`page-2026-03-29T11-02-10-640Z.png`](/mnt/c/Projects/03-Finance/ai-fund/output/playwright/route-matrix/20260329-130142/valuation-summary/page-2026-03-29T11-02-10-640Z.png)
- research: [`page-2026-03-29T11-04-09-011Z.png`](/mnt/c/Projects/03-Finance/ai-fund/output/playwright/route-matrix/20260329-130142/research/page-2026-03-29T11-04-09-011Z.png)
- audit: [`page-2026-03-29T11-04-15-811Z.png`](/mnt/c/Projects/03-Finance/ai-fund/output/playwright/route-matrix/20260329-130142/audit/page-2026-03-29T11-04-15-811Z.png)

## Manual Smoke Commands

If you only need one route:

```bash
"$PWCLI" open http://127.0.0.1:4173/watchlist --browser firefox
"$PWCLI" snapshot
"$PWCLI" screenshot
"$PWCLI" console
"$PWCLI" close
```

Or directly on a ticker route:

```bash
"$PWCLI" open "http://127.0.0.1:4173/ticker/CALM/valuation?view=Assumptions" --browser firefox
```

## Quiet Dev Capture Helper

For repeated local screenshot sweeps against a running dev server, use the short helper that now prints only the final filenames after the sweep:

```bash
python scripts/manual/capture_react_dev_pages.py
python scripts/manual/capture_react_dev_pages.py --full
python scripts/manual/capture_react_dev_pages.py --one-page overview
```

What it does:

- assumes the frontend dev server is already running on `http://127.0.0.1:4173`
- reuses a single `playwright-cli` session, waits for `networkidle`, and takes a PNG for each route
- writes a light `manifest.json` next to the screenshots in `output/playwright/dev-verify/<timestamp>/`
- prints nothing until completion, then lists each route’s screenshot path; errors include the failed command’s stdout/stderr

Default mode captures a smoke set:

- `watchlist`
- `overview`
- `valuation-summary`
- `market`
- `research`
- `audit`

Use `--full` when you also want:

- `valuation-dcf`
- `valuation-multiples`
- `valuation-recommendations`

Use `--one-page <route>` for targeted inspection while iterating on one page.

This helper is for fast dev loops. The full `review_react_route_matrix.py` flow remains the canonical verification path when you need route markers, console artifacts, and a review manifest for the full route matrix.

## Debugging Checklist

When a route looks wrong:

1. Confirm the API route returns `200`
2. Inspect the payload shape directly
3. Inspect the screenshot
4. Inspect the console artifact
5. Check whether the route matrix waited for the right markers
6. Decide whether the issue is:
   - render timing
   - payload mapping
   - genuine empty-state data

## When To Trust The Result

Call a route “verified” only when all of these are true:

- the page URL is correct
- required text is present
- forbidden placeholder text is absent
- console artifact is clean
- screenshot looks correct by human review

If any of those are missing, the route is not done.

## Related Files

- [`scripts/manual/review_react_route_matrix.py`](/mnt/c/Projects/03-Finance/ai-fund/scripts/manual/review_react_route_matrix.py)
- [`scripts/manual/launch-react-wsl.sh`](/mnt/c/Projects/03-Finance/ai-fund/scripts/manual/launch-react-wsl.sh)
- [`scripts/manual/serve_frontend_dist.py`](/mnt/c/Projects/03-Finance/ai-fund/scripts/manual/serve_frontend_dist.py)
- [`frontend/src/test/appRoutes.test.tsx`](/mnt/c/Projects/03-Finance/ai-fund/frontend/src/test/appRoutes.test.tsx)
- [React Frontend Setup And Runtime Map](./react-frontend-setup.md)
