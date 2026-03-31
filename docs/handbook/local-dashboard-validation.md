# Local Dashboard Validation

This page is the canonical local validation path for Alpha Pod's Streamlit dashboard and Playwright smoke tests.

Use the host PowerShell environment first. Use WSL only as a secondary fallback.

## Canonical Environment

Start from a normal PowerShell terminal in the repo root and activate the project env:

```powershell
ca ai-fund
```

Expected prompt:

```text
(ai-fund) PS C:\Projects\03-Finance\ai-fund>
```

This is the intended local operator path for the dashboard.

## Start The Dashboard

Run Streamlit from the activated host env:

```powershell
python -m streamlit run dashboard/app.py --server.headless true --server.address 127.0.0.1 --server.port 8502 --browser.serverAddress 127.0.0.1 --browser.serverPort 8502
```

## Verify Local Serving

In a second PowerShell terminal:

```powershell
ca ai-fund
Invoke-WebRequest http://127.0.0.1:8502 -UseBasicParsing
```

Successful output confirms the local app is bound on the canonical port.

## Playwright Smoke Test

From the same host environment:

```powershell
playwright-cli open http://127.0.0.1:8502
playwright-cli snapshot
playwright-cli screenshot
playwright-cli close
```

Expected result:

- the browser opens the local dashboard
- `snapshot` succeeds
- `screenshot` writes a PNG artifact
- `close` ends the session cleanly

## Scripted Host Flow

The launcher script is the scripted form of the same canonical path:

```powershell
pwsh -File .\scripts\manual\launch-streamlit-playwright-cli.ps1
```

Useful variants:

```powershell
pwsh -File .\scripts\manual\launch-streamlit-playwright-cli.ps1 -Preview
pwsh -File .\scripts\manual\launch-streamlit-playwright-cli.ps1 -Stop
```

## When To Use WSL

Use WSL only if the host PowerShell flow is unavailable or if you explicitly need Linux-side Playwright behavior.

The WSL fallback is documented here:

- `docs/handbook/wsl-playwright.md`

If you are validating the React quote-terminal instead of Streamlit, use these docs instead:

- [React Frontend Setup And Runtime Map](./react-frontend-setup.md)
- [React Playwright Review Loop](./react-playwright-review-loop.md)

## Current Limitation In Codex

This Codex runtime can inspect the app terminal and confirm when the host prompt is already active as `(ai-fund)`, but it cannot currently launch host-side PowerShell subprocesses from the bash execution sandbox because Windows interop fails with:

```text
UtilBindVsockAnyPort:307: socket failed 1
```

That means host-side Streamlit and Playwright commands should be run in the visible PowerShell terminal, not through WSL command execution.
