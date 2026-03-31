# Alpha Pod Frontend Scaffold

Thin React + TypeScript + Vite frontend for Alpha Pod.

Detailed docs:

- [React Frontend Setup And Runtime Map](../docs/handbook/react-frontend-setup.md)
- [React Playwright Review Loop](../docs/handbook/react-playwright-review-loop.md)
- [Quote-Terminal UI And API Dev Guide](../docs/handbook/quote-terminal-ui.md)

## Commands

```bash
cd frontend
npm install
npm run dev
npm run test
npm run build
```

If you are running the test/build commands in WSL and the shell inherits a Windows temp path, prefix the command with `TMPDIR=/tmp TMP=/tmp TEMP=/tmp`.

## WSL launcher

To run the React frontend and FastAPI backend together on the WSL side:

```bash
bash scripts/manual/launch-react-wsl.sh
```

The launcher builds the frontend with an explicit API base, serves the built `dist/` bundle through a lightweight Python SPA server, and runs FastAPI directly. It does not depend on the Vite dev server staying alive.

Preview or stop the stack with:

```bash
bash scripts/manual/launch-react-wsl.sh --preview
bash scripts/manual/launch-react-wsl.sh --stop
```

If you change `.env`, restart the stack so the FastAPI backend reloads the updated keys:

```bash
bash scripts/manual/launch-react-wsl.sh --stop
bash scripts/manual/launch-react-wsl.sh
```

For the canonical screenshot-based review workflow, do not invent a custom loop. Use:

```bash
python3 scripts/manual/review_react_route_matrix.py
```

Artifacts are written to `output/playwright/route-matrix/<timestamp>/`.

For a quieter dev-mode screenshot sweep against a running Vite server, use:

```bash
python scripts/manual/capture_react_dev_pages.py
python scripts/manual/capture_react_dev_pages.py --full
python scripts/manual/capture_react_dev_pages.py --one-page market
```

This helper:

- assumes the React dev server is already running on `http://127.0.0.1:4173`
- uses `playwright-cli` through `npx`
- prints only the final screenshot filenames on success
- writes screenshots and a small manifest to `output/playwright/dev-verify/<timestamp>/`

Default mode is a smoke set:

- `watchlist`
- `overview`
- `valuation-summary`
- `market`
- `research`
- `audit`

Use `--full` to add the heavier valuation detail routes like `valuation-dcf`, `valuation-multiples`, and `valuation-recommendations`, or `--one-page <route>` to capture just one route by name.

## API Contract

The app expects a thin FastAPI backend at `/api` with watchlist, ticker workspace, overview, valuation, market, research, audit, refresh, and snapshot endpoints.

## Route Model

- `/watchlist`
- `/ticker/:ticker/overview`
- `/ticker/:ticker/valuation`
- `/ticker/:ticker/market`
- `/ticker/:ticker/research`
- `/ticker/:ticker/audit`

The React shell is the strategic direction for the operator UI. The Streamlit app remains in the repo as a transitional surface while these routes gain parity.
