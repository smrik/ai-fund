# Alpha Pod API

Thin FastAPI surface for the quote-terminal migration.

## Purpose

`api/` exposes UI-friendly HTTP endpoints over existing Python pipeline helpers. It is not allowed to become a second business-logic layer.

Permitted dependencies:

- `src/stage_04_pipeline/`
- `src/stage_03_judgment/`
- `src/stage_02_valuation/`
- `db/`
- `config/`

## Run

```bash
python -m uvicorn api.main:app
```

For the stable WSL review path, the API is normally started through:

```bash
bash scripts/manual/launch-react-wsl.sh
```

That launcher serves the built frontend and proxies `/api` to this FastAPI app.

## Current v1 endpoints

- `GET /api/watchlist`
- `POST /api/watchlist/refresh`
- `GET /api/watchlist/exports`
- `POST /api/watchlist/exports`
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
- `GET /api/exports/{export_id}`
- `GET /api/exports/{export_id}/download`
- `GET /api/exports/{export_id}/artifacts/{artifact_key}`
- `POST /api/tickers/{ticker}/analysis/run`
- `POST /api/tickers/{ticker}/snapshot/open-latest`

## Export Surface

React is now the primary export client for the migration path.

- `Audit` is the canonical ticker export hub for Excel and HTML
- `Valuation` exposes a contextual Excel shortcut
- `Research` exposes a contextual HTML memo shortcut
- `/watchlist` exposes explicit batch Excel and HTML export actions

The backend stores completed export bundles plus artifact metadata, while `/download` and `/artifacts/*` expose the primary file and sidecars for browser download.
