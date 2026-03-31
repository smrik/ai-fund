# React Frontend Setup And Runtime Map

This is the canonical setup and architecture guide for the React quote-terminal stack.

Use this document when you need to:

- run the React UI locally
- understand how `frontend/` and `api/` fit together
- decide whether to use Vite dev mode or the WSL review launcher
- find the right file to edit for a route, transport helper, or runtime issue

## Purpose

The React stack is the strategic UI direction for Alpha Pod.

It is intentionally thin:

- `frontend/` renders routes, tables, and action surfaces
- `api/` exposes UI-friendly HTTP payloads
- deterministic business logic remains in `src/stage_04_pipeline/`, `src/stage_02_valuation/`, `db/`, and `config/`

The frontend must not become a second valuation engine. It renders and triggers; the Python pipeline remains the system of record.

## Current Runtime Topology

```text
React Router UI
  frontend/src/
      |
      v
TanStack Query transport
  frontend/src/lib/api.ts
      |
      v
FastAPI surface
  api/main.py
      |
      v
Existing Python helpers
  src/stage_04_pipeline/
  src/stage_02_valuation/
  src/stage_03_judgment/
  db/
  config/
```

### Important constraint

`api/` is transport only. If a change is fundamentally about valuation logic, archive loading, tracker state, CIQ ingestion, or dossier assembly, fix it in the existing Python layers instead of hiding logic in the API or frontend.

## Route Model

Client routes live in [`frontend/src/app/router.tsx`](/mnt/c/Projects/03-Finance/ai-fund/frontend/src/app/router.tsx).

Current primary routes:

- `/watchlist`
- `/ticker/:ticker/overview`
- `/ticker/:ticker/valuation`
- `/ticker/:ticker/market`
- `/ticker/:ticker/research`
- `/ticker/:ticker/audit`

Routing rules:

- `/watchlist` is the landing route
- `/ticker/:ticker` redirects to `overview`
- unknown paths redirect back to `/watchlist`
- `Valuation` owns its own second-level nav using the `view` query param

## File Map

### Frontend shell

- [`frontend/src/components/RootLayout.tsx`](/mnt/c/Projects/03-Finance/ai-fund/frontend/src/components/RootLayout.tsx)
  - top-level shell
  - app header
  - top nav
- [`frontend/src/components/TickerLayout.tsx`](/mnt/c/Projects/03-Finance/ai-fund/frontend/src/components/TickerLayout.tsx)
  - compact ticker strip for non-valuation ticker routes
  - snapshot/deep-analysis actions
  - outlet context for child routes
- [`frontend/src/components/TickerTabs.tsx`](/mnt/c/Projects/03-Finance/ai-fund/frontend/src/components/TickerTabs.tsx)
  - ticker-level tab navigation
  - must always use absolute `/ticker/:ticker/...` links

### Frontend pages

- [`frontend/src/pages/WatchlistPage.tsx`](/mnt/c/Projects/03-Finance/ai-fund/frontend/src/pages/WatchlistPage.tsx)
  - saved deterministic universe landing page
  - focus pane
  - refresh/deep-analysis actions
- [`frontend/src/pages/OverviewPage.tsx`](/mnt/c/Projects/03-Finance/ai-fund/frontend/src/pages/OverviewPage.tsx)
  - expanded narrative hero
- [`frontend/src/pages/ValuationPage.tsx`](/mnt/c/Projects/03-Finance/ai-fund/frontend/src/pages/ValuationPage.tsx)
  - `Summary`, `DCF`, `Comparables`, `Multiples`, `Assumptions`, `WACC`, `Recommendations`
  - route-specific query loading
  - assumptions apply mutation
- [`frontend/src/pages/MarketPage.tsx`](/mnt/c/Projects/03-Finance/ai-fund/frontend/src/pages/MarketPage.tsx)
- [`frontend/src/pages/ResearchPage.tsx`](/mnt/c/Projects/03-Finance/ai-fund/frontend/src/pages/ResearchPage.tsx)
- [`frontend/src/pages/AuditPage.tsx`](/mnt/c/Projects/03-Finance/ai-fund/frontend/src/pages/AuditPage.tsx)

### Transport and data shaping

- [`frontend/src/lib/api.ts`](/mnt/c/Projects/03-Finance/ai-fund/frontend/src/lib/api.ts)
  - all frontend HTTP calls
  - uses `VITE_API_BASE` when set, otherwise `/api`
- [`frontend/src/lib/types.ts`](/mnt/c/Projects/03-Finance/ai-fund/frontend/src/lib/types.ts)
  - frontend payload contracts
- [`frontend/src/lib/format.ts`](/mnt/c/Projects/03-Finance/ai-fund/frontend/src/lib/format.ts)
  - currency, percent, text, and date formatting
- [`frontend/src/lib/snapshot.ts`](/mnt/c/Projects/03-Finance/ai-fund/frontend/src/lib/snapshot.ts)
  - snapshot-open cache hydration helpers

### Backend transport

- [`api/main.py`](/mnt/c/Projects/03-Finance/ai-fund/api/main.py)
  - FastAPI app
  - run-status handling
  - endpoint-to-helper wiring
- [`api/README.md`](/mnt/c/Projects/03-Finance/ai-fund/api/README.md)
  - endpoint inventory

### Local runtime scripts

- [`scripts/manual/launch-react-wsl.sh`](/mnt/c/Projects/03-Finance/ai-fund/scripts/manual/launch-react-wsl.sh)
  - canonical one-command WSL review launcher
  - creates `.venv-wsl`
  - installs `requirements-api.txt`
  - builds the frontend bundle
  - starts FastAPI and the lightweight SPA server
- [`scripts/manual/serve_frontend_dist.py`](/mnt/c/Projects/03-Finance/ai-fund/scripts/manual/serve_frontend_dist.py)
  - serves `frontend/dist`
  - SPA fallback to `index.html`
  - proxies `/api/*` to FastAPI

## Run Modes

There are two valid local run modes.

### 1. Inner-loop development mode

Use this when editing frontend code rapidly and you want the standard Vite workflow.

Run the backend:

```bash
python -m uvicorn api.main:app --reload
```

Run the frontend:

```bash
npm --prefix frontend install
npm --prefix frontend run dev
```

Notes:

- this is the simplest mode for frontend implementation
- it depends on Vite staying healthy in your shell
- in WSL/Codex environments, it is more fragile than the review launcher

### 2. Stable WSL review mode

Use this when you want a reliable same-side stack for visual review, Playwright, and end-to-end verification.

```bash
bash scripts/manual/launch-react-wsl.sh
```

This mode:

- creates or reuses `.venv-wsl/`
- installs only the lighter API review dependencies from [`requirements-api.txt`](/mnt/c/Projects/03-Finance/ai-fund/requirements-api.txt)
- builds the frontend with `VITE_API_BASE=http://127.0.0.1:8000/api`
- serves the built bundle through [`serve_frontend_dist.py`](/mnt/c/Projects/03-Finance/ai-fund/scripts/manual/serve_frontend_dist.py)

Useful variants:

```bash
bash scripts/manual/launch-react-wsl.sh --preview
bash scripts/manual/launch-react-wsl.sh --status
bash scripts/manual/launch-react-wsl.sh --stop
bash scripts/manual/launch-react-wsl.sh --bootstrap
```

Why this mode became canonical for review:

- it avoids depending on Vite dev-server stability in WSL
- it keeps frontend and API on the same side
- the SPA server proxies `/api` directly, so Playwright sees the same routing shape as the real UI

## Ports And Health Checks

Default URLs:

- frontend: `http://127.0.0.1:4173`
- API: `http://127.0.0.1:8000`

Quick checks:

```bash
curl -I http://127.0.0.1:4173/watchlist
curl http://127.0.0.1:8000/api/watchlist
```

If the frontend is up but data is missing, check:

1. the API is actually returning `200`
2. the served frontend is using the expected `VITE_API_BASE`
3. you are not mixing a WSL frontend with a Windows-host API or vice versa

## Environment And Secrets

- `.env` is still the local secret source
- restarting the backend is required after changing `.env`
- in WSL review mode, restart with:

```bash
bash scripts/manual/launch-react-wsl.sh --stop
bash scripts/manual/launch-react-wsl.sh
```

Do not read or commit `.env`.

## Verification Commands

### Frontend-only

```bash
npm --prefix frontend run test -- --run src/test/appRoutes.test.tsx
npm --prefix frontend run build
```

### Backend/API

```bash
python -m pytest tests/test_api_contracts.py -q
```

### Script sanity

```bash
python3 -m py_compile scripts/manual/serve_frontend_dist.py scripts/manual/review_react_route_matrix.py
bash -n scripts/manual/launch-react-wsl.sh
```

### Full visual review

Use the dedicated runbook:

- [React Playwright Review Loop](./react-playwright-review-loop.md)

## Common Failure Modes

### 1. Route loads but data cards are empty

Possible causes:

- API payload really is empty
- frontend is reading the wrong payload shape
- screenshot was taken before async route data settled

Do not guess. Check both:

- the direct API response
- the screenshot artifact

### 2. Console is clean but UI is still wrong

This happened repeatedly during the route sweep.

Examples:

- placeholder text captured before valuation data settled
- `Research` rendered a technically valid page but mapped the wrong payload fields

A clean console is necessary, not sufficient.

### 3. Vite works locally but Playwright review is flaky

Prefer the WSL review launcher for screenshot-based verification. The built bundle plus SPA proxy path is more stable in this repo than relying on the dev server for long verification loops.

## Canonical References

- [Quote-Terminal UI And API Dev Guide](./quote-terminal-ui.md)
- [React Playwright Review Loop](./react-playwright-review-loop.md)
- [WSL Playwright Fallback](./wsl-playwright.md)
- [Frontend README](../../frontend/README.md)
- [API README](../../api/README.md)
