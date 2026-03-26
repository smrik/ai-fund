---
name: local-dashboard-playwright
description: Use when validating the local Streamlit dashboard from the host PowerShell `ai-fund` environment in this repo, especially when `ca ai-fund` is available and the default local Playwright flow should not go through WSL
---

# Local Dashboard Playwright

Use this as the canonical local validation path for Alpha Pod.

## Default Environment

Run the local dashboard from a normal PowerShell session with the repo env active:

```powershell
ca ai-fund
```

The terminal prompt should show:

```text
(ai-fund) PS C:\Projects\03-Finance\ai-fund>
```

## Canonical Local Flow

Start Streamlit:

```powershell
python -m streamlit run dashboard/app.py --server.headless true --server.address 127.0.0.1 --server.port 8502 --browser.serverAddress 127.0.0.1 --browser.serverPort 8502
```

Verify the app is serving:

```powershell
Invoke-WebRequest http://127.0.0.1:8502 -UseBasicParsing
```

Drive it with Playwright:

```powershell
playwright-cli open http://127.0.0.1:8502
playwright-cli snapshot
playwright-cli screenshot
playwright-cli close
```

## Scripted Path

The script below is the scripted version of the same host-side flow:

```powershell
pwsh -File .\scripts\manual\launch-streamlit-playwright-cli.ps1
```

## When To Use WSL Instead

Only use the WSL fallback if the host PowerShell path is unavailable or if you specifically need the Linux-side Playwright environment.

See `docs/handbook/local-dashboard-validation.md` for the main runbook and `docs/handbook/wsl-playwright.md` for the fallback path.
