---
name: playwright-wsl
description: Use when running `playwright-cli` from WSL in this repo, especially for local Streamlit dashboard checks, socket errors under `/mnt/c/.../Temp`, missing browser channel errors, or WSL-only Playwright setup issues
---

# Playwright In WSL

Use this with the global `playwright` skill when browser automation is running from WSL in Alpha Pod.
This is the fallback path, not the default local dashboard path.

## Core Rule

Keep Playwright temp and session files on the Linux filesystem, not under `/mnt/c`.

If `playwright-cli` creates its socket under `/mnt/c/.../Temp`, WSL fails with:

```text
listen ENOTSUP: operation not supported on socket ... .sock
```

## Session Setup

```bash
export HOME=/tmp/codex-playwright-home
export TMPDIR=/tmp
export TMP=/tmp
export TEMP=/tmp
export CODEX_HOME="${CODEX_HOME:-/mnt/c/Users/patri/.codex}"
export PWCLI="$CODEX_HOME/skills/playwright/scripts/playwright_cli.sh"
export PLAYWRIGHT_CLI_SESSION="${PLAYWRIGHT_CLI_SESSION:-alpha-pod-wsl}"
```

## Browser Choice

Use Firefox by default in WSL.

```bash
sudo env PATH="$PATH" npx --yes playwright install-deps firefox
npx --yes playwright install firefox
```

Do not assume the Chrome channel exists in WSL. If Playwright says:

```text
Chromium distribution 'chrome' is not found at /opt/google/chrome/chrome
```

switch to `--browser firefox`.

## Local Dashboard

Prefer the host PowerShell path first:

- `ca ai-fund`
- run Streamlit in PowerShell
- verify `127.0.0.1:8502`
- drive it with `playwright-cli`

Only use this WSL path when the host-side flow is unavailable.

The repo expects local Streamlit at `http://127.0.0.1:8502`.

If conda is available inside WSL, prefer the repo env file:

```bash
conda env create -f environment.yml
conda activate ai-fund
```

Then run Streamlit from that activated env.

If WSL Python is not ready yet:

```bash
sudo apt-get install -y python3.12-venv
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

Then start the app:

```bash
. .venv/bin/activate
python -m streamlit run dashboard/app.py \
  --server.headless true \
  --server.address 127.0.0.1 \
  --server.port 8502 \
  --browser.serverAddress 127.0.0.1 \
  --browser.serverPort 8502
```

## Smoke Test

```bash
curl -I http://127.0.0.1:8502
"$PWCLI" open http://127.0.0.1:8502 --browser firefox
"$PWCLI" snapshot
"$PWCLI" screenshot
"$PWCLI" close
```

## Known Failure Modes

- `listen ENOTSUP ... .sock`: temp dir is on `/mnt/c`; export `TMPDIR=/tmp`, `TMP=/tmp`, `TEMP=/tmp`
- `browserType.launch: Chromium distribution 'chrome' is not found`: use `--browser firefox`
- `Host system is missing dependencies to run browsers`: run `sudo env PATH="$PATH" npx --yes playwright install-deps firefox`
- `conda: command not found`: conda is not installed inside WSL; either create the WSL env from `environment.yml` or run the Windows-side env from a normal PowerShell session
- `ModuleNotFoundError: No module named 'streamlit'`: activate `.venv` and install `requirements.txt`
- `ensurepip is not available`: install `python3.12-venv`

## Reference

See `docs/handbook/local-dashboard-validation.md` for the canonical host flow and `docs/handbook/wsl-playwright.md` for the WSL fallback.
