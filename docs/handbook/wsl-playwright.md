# WSL Playwright Fallback

This page is the fallback setup and smoke-test path for Playwright CLI plus the local Streamlit dashboard from WSL.

Use the host PowerShell path first. The canonical local flow lives in `docs/handbook/local-dashboard-validation.md`.

## Why This Exists

Alpha Pod works from WSL, but Playwright has two WSL-specific requirements:

1. Unix sockets must live on the Linux filesystem, not under `/mnt/c`
2. The local Python environment must exist inside WSL before `streamlit run` can work

The failure signatures that led to this runbook were:

- `listen ENOTSUP: operation not supported on socket ... .sock`
- `Chromium distribution 'chrome' is not found at /opt/google/chrome/chrome`
- `ModuleNotFoundError: No module named 'streamlit'`
- `The virtual environment was not created successfully because ensurepip is not available`

## One-Time WSL Setup

Preferred path if conda is installed inside WSL:

```bash
conda env create -f environment.yml
conda activate ai-fund
```

The repo already defines this env in `environment.yml`.

Fallback path if conda is not available inside WSL:

Install Python venv support:

```bash
sudo apt-get update
sudo apt-get install -y python3.12-venv
```

Create the repo virtualenv and install app dependencies:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

Install Playwright browser dependencies and Firefox:

```bash
sudo env PATH="$PATH" npx --yes playwright install-deps firefox
npx --yes playwright install firefox
```

## Per-Session Environment

Before running Playwright CLI from WSL, force temp and session state onto the Linux filesystem:

```bash
export HOME=/tmp/codex-playwright-home
export TMPDIR=/tmp
export TMP=/tmp
export TEMP=/tmp
export CODEX_HOME="${CODEX_HOME:-/mnt/c/Users/patri/.codex}"
export PWCLI="$CODEX_HOME/skills/playwright/scripts/playwright_cli.sh"
export PLAYWRIGHT_CLI_SESSION="${PLAYWRIGHT_CLI_SESSION:-alpha-pod-wsl}"
```

Use Firefox unless there is a deliberate reason to use another browser:

```bash
"$PWCLI" open https://example.com --browser firefox
```

## Generic Playwright Smoke Test

Run this first when validating the WSL browser stack itself:

```bash
"$PWCLI" open https://example.com --browser firefox
"$PWCLI" snapshot
"$PWCLI" screenshot
"$PWCLI" close
```

Expected result:

- `open` returns page title `Example Domain`
- `snapshot` succeeds
- `screenshot` writes a PNG under `.playwright-cli/`

## Local Streamlit Dashboard Smoke Test

### Option A: WSL conda env

If `conda` exists inside WSL, activate the repo env first:

```bash
conda activate ai-fund
python -m streamlit run dashboard/app.py \
  --server.headless true \
  --server.address 127.0.0.1 \
  --server.port 8502 \
  --browser.serverAddress 127.0.0.1 \
  --browser.serverPort 8502
```

### Option B: WSL `.venv`

Start the dashboard from the repo root:

```bash
. .venv/bin/activate
python -m streamlit run dashboard/app.py \
  --server.headless true \
  --server.address 127.0.0.1 \
  --server.port 8502 \
  --browser.serverAddress 127.0.0.1 \
  --browser.serverPort 8502
```

In another WSL shell, confirm the app is serving:

```bash
curl -I http://127.0.0.1:8502
```

Then drive it with Playwright:

```bash
export HOME=/tmp/codex-playwright-home
export TMPDIR=/tmp
export TMP=/tmp
export TEMP=/tmp
export CODEX_HOME="${CODEX_HOME:-/mnt/c/Users/patri/.codex}"
export PWCLI="$CODEX_HOME/skills/playwright/scripts/playwright_cli.sh"
export PLAYWRIGHT_CLI_SESSION=alpha-pod-dashboard

"$PWCLI" open http://127.0.0.1:8502 --browser firefox
"$PWCLI" snapshot
"$PWCLI" screenshot
"$PWCLI" close
```

## Troubleshooting

### `listen ENOTSUP ... .sock`

Cause:
- Playwright is trying to create its session socket under a Windows-mounted path

Fix:
- export `TMPDIR=/tmp`, `TMP=/tmp`, `TEMP=/tmp`
- keep `HOME` on `/tmp` as shown above

### `Chromium distribution 'chrome' is not found`

Cause:
- WSL does not have the Linux Chrome channel installed

Fix:
- use `--browser firefox`
- install Firefox through `npx --yes playwright install firefox`

### `Host system is missing dependencies to run browsers`

Cause:
- Linux browser runtime libraries are missing

Fix:

```bash
sudo env PATH="$PATH" npx --yes playwright install-deps firefox
```

### `ModuleNotFoundError: No module named 'streamlit'`

Cause:
- the repo virtualenv is missing or not activated

Fix:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

### `ensurepip is not available`

Cause:
- the WSL distro is missing `python3.12-venv`

Fix:

```bash
sudo apt-get install -y python3.12-venv
```

### `conda: command not found`

Cause:
- conda is not installed inside WSL
- the available `ai-fund` env may exist only in Windows PowerShell

Fix:
- if you want a pure WSL flow, install conda in WSL and run `conda env create -f environment.yml`
- if you want to use the existing Windows-side env, start Streamlit from a normal PowerShell terminal with `ca ai-fund`; do not assume the WSL shell can invoke that helper
