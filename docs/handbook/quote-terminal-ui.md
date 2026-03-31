# Quote-Terminal UI And API Dev Guide

This is the orientation guide for the transitional UI stack while Alpha Pod moves from the Streamlit shell toward the quote-terminal frontend.

Use it as the high-level map, then go deeper with:

- [React Frontend Setup And Runtime Map](./react-frontend-setup.md)
- [React Playwright Review Loop](./react-playwright-review-loop.md)

## Current State

There are now two UI surfaces in the repository:

1. `dashboard/`

- Streamlit remains available as a transitional shell
- use it for legacy PM workflow paths and dossier-backed deep dives that have not moved yet

2. `frontend/` plus `api/`

- `frontend/` is the React + TypeScript + Vite quote-terminal shell
- `api/` is the thin FastAPI transport layer over the existing Python pipeline
- this is the strategic shell and the primary export surface
- this is the migration path, not a second business-logic stack

The deterministic valuation code, archived snapshots, and stage orchestration remain the system of record.

## Run The Stack

### Streamlit operator shell

```bash
python -m streamlit run dashboard/app.py --server.headless true --server.address 127.0.0.1 --server.port 8502
```

### FastAPI backend

```bash
python -m uvicorn api.main:app --reload
```

### React frontend

```bash
npm --prefix frontend install
npm --prefix frontend run dev
```

The Vite dev server proxies `/api` to `http://127.0.0.1:8000`.

### WSL one-command launcher

If you want the React shell and FastAPI backend on the same WSL side, use:

```bash
bash scripts/manual/launch-react-wsl.sh
```

Useful variants:

```bash
bash scripts/manual/launch-react-wsl.sh --preview
bash scripts/manual/launch-react-wsl.sh --stop
```

After the stack is up, you can review it visually from WSL with Playwright CLI:

```bash
export HOME=/tmp/codex-playwright-home
mkdir -p "$HOME"
playwright-cli open http://127.0.0.1:4173/watchlist
playwright-cli snapshot
playwright-cli screenshot
```

For the current canonical review method, use the dedicated route-matrix loop in [React Playwright Review Loop](./react-playwright-review-loop.md).

## Route Model

The quote-terminal frontend uses client-side routes:

- `/watchlist`
- `/ticker/:ticker/overview`
- `/ticker/:ticker/valuation`
- `/ticker/:ticker/market`
- `/ticker/:ticker/research`
- `/ticker/:ticker/audit`

Behavior rules:

- watchlist is the landing route
- watchlist keeps a selected-row focus pane so the PM can compare names before drilling into a ticker route
- non-`Overview` ticker pages use the compact sticky quote strip
- the sticky quote strip is intentionally limited to action, conviction, current price, base IV, and upside
- only `Overview` gets the expanded narrative hero
- valuation keeps visible sub-navigation for `Summary`, `DCF`, `Comparables`, `Multiples`, `Assumptions`, `WACC`, and `Recommendations`
- valuation is now the first fully differentiated quote-terminal workbench, with distinct DCF, comps, multiples, assumptions, WACC, and recommendation surfaces
- audit now includes a dedicated `Exports` view and is the canonical ticker export hub
- watchlist exposes explicit batch Excel and HTML export actions
- valuation and research expose contextual export shortcuts for Excel and HTML memo output

## API Surface

Current v1 endpoints:

- `GET /api/watchlist`
- `POST /api/watchlist/refresh`
- `GET /api/runs/{run_id}`
- `GET /api/tickers/{ticker}/workspace`
- `GET /api/tickers/{ticker}/overview`
- `GET /api/tickers/{ticker}/valuation/summary`
- `GET /api/tickers/{ticker}/valuation/assumptions`
- `POST /api/tickers/{ticker}/valuation/assumptions/apply`
- `GET /api/tickers/{ticker}/valuation/wacc`
- `GET /api/tickers/{ticker}/market`
- `GET /api/tickers/{ticker}/research`
- `GET /api/tickers/{ticker}/audit`
- `GET /api/tickers/{ticker}/exports`
- `POST /api/tickers/{ticker}/exports`
- `GET /api/watchlist/exports`
- `POST /api/watchlist/exports`
- `GET /api/exports/{export_id}`
- `GET /api/exports/{export_id}/download`
- `GET /api/exports/{export_id}/artifacts/{artifact_key}`
- `POST /api/tickers/{ticker}/analysis/run`
- `POST /api/tickers/{ticker}/snapshot/open-latest`

The API layer may call `stage_04`, `stage_03`, `stage_02`, `db`, and `config`, but lower layers must not depend on `api/`.

## Verification

Before claiming the quote-terminal scaffold is healthy, run:

```bash
python -m pytest tests/test_api_contracts.py tests/test_dashboard_runtime_contracts.py tests/test_dashboard_render_contracts.py -q
npm --prefix frontend run test
npm --prefix frontend run build
```

For full UI verification of the React shell, also run the route-matrix workflow documented in [React Playwright Review Loop](./react-playwright-review-loop.md).

For the Streamlit stabilization tranche, also validate the host shell with Playwright against the running Streamlit app.
