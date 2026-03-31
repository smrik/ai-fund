#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
STATE_DIR="${REPO_ROOT}/.pwtmp"
STATE_FILE="${STATE_DIR}/react-wsl-stack.env"
VENV_DIR="${REPO_ROOT}/.venv-wsl"
REQ_FILE="${REPO_ROOT}/requirements-api.txt"
FRONTEND_DIR="${REPO_ROOT}/frontend"
FRONTEND_DIST_DIR="${FRONTEND_DIR}/dist"
FRONTEND_SERVER="${REPO_ROOT}/scripts/manual/serve_frontend_dist.py"

API_HOST="127.0.0.1"
API_PORT="8000"
WEB_HOST="127.0.0.1"
WEB_PORT="4173"

API_URL="http://${API_HOST}:${API_PORT}"
WEB_URL="http://${WEB_HOST}:${WEB_PORT}"
API_HEALTH_PATH="/api/watchlist"

API_LOG="${STATE_DIR}/react-wsl-api.log"
WEB_LOG="${STATE_DIR}/react-wsl-frontend.log"

API_PID=""
WEB_PID=""
UPDATED_AT=""

PREVIEW=0
STOP=0
BOOTSTRAP=0
STATUS=0

die() {
  echo "Error: $*" >&2
  exit 1
}

log() {
  echo "[launch-react-wsl] $*"
}

usage() {
  cat <<EOF
Usage:
  bash scripts/manual/launch-react-wsl.sh
  bash scripts/manual/launch-react-wsl.sh --preview
  bash scripts/manual/launch-react-wsl.sh --bootstrap
  bash scripts/manual/launch-react-wsl.sh --status
  bash scripts/manual/launch-react-wsl.sh --stop
  bash scripts/manual/launch-react-wsl.sh --help

Options:
  --preview    Show what would run without starting services.
  --bootstrap  Force reinstall/update of the WSL venv and frontend dependencies.
  --status     Print the current API/frontend PID, port, and health state.
  --stop       Stop both services, clear the saved state, and free the ports.
  --help       Show this help message.
EOF
}

require_command() {
  local name="$1"
  command -v "$name" >/dev/null 2>&1 || die "Required command not found: ${name}"
}

port_pid() {
  local port="$1"
  lsof -ti "tcp:${port}" -sTCP:LISTEN 2>/dev/null | head -n 1 || true
}

kill_port() {
  local port="$1"
  local pid
  pid="$(port_pid "$port")"
  [[ -n "$pid" ]] || return 0
  kill "$pid" 2>/dev/null || true
  for _ in {1..20}; do
    if [[ -z "$(port_pid "$port")" ]]; then
      return 0
    fi
    sleep 0.25
  done
  kill -9 "$pid" 2>/dev/null || true
}

is_pid_alive() {
  local pid="${1:-}"
  if [[ -z "$pid" ]]; then
    return 1
  fi
  if kill -0 "$pid" 2>/dev/null; then
    return 0
  fi
  return 1
}

_quote_state_value() {
  printf '"%s"' "${1//\"/\\\"}"
}

write_state() {
  mkdir -p "$STATE_DIR"
  {
    printf 'API_PID=%s\n' "$(_quote_state_value "${API_PID:-}")"
    printf 'WEB_PID=%s\n' "$(_quote_state_value "${WEB_PID:-}")"
    printf 'API_LOG=%s\n' "$(_quote_state_value "$API_LOG")"
    printf 'WEB_LOG=%s\n' "$(_quote_state_value "$WEB_LOG")"
    printf 'API_URL=%s\n' "$(_quote_state_value "$API_URL")"
    printf 'WEB_URL=%s\n' "$(_quote_state_value "$WEB_URL")"
    printf 'UPDATED_AT=%s\n' "$(_quote_state_value "$(date -Iseconds)")"
  } > "$STATE_FILE"
}

load_state() {
  [[ -f "$STATE_FILE" ]] || return 0
  while IFS='=' read -r key raw_value; do
    raw_value="${raw_value%\"}"
    raw_value="${raw_value#\"}"
    case "$key" in
      API_PID) API_PID="$raw_value" ;;
      WEB_PID) WEB_PID="$raw_value" ;;
      API_LOG) API_LOG="$raw_value" ;;
      WEB_LOG) WEB_LOG="$raw_value" ;;
      API_URL) API_URL="$raw_value" ;;
      WEB_URL) WEB_URL="$raw_value" ;;
      UPDATED_AT) UPDATED_AT="$raw_value" ;;
    esac
  done < "$STATE_FILE"
}

ensure_venv() {
  if [[ ! -d "$VENV_DIR" ]]; then
    log "Creating ${VENV_DIR}"
    python3 -m venv "$VENV_DIR"
    BOOTSTRAP=1
  fi

  if [[ ! -f "$REQ_FILE" ]]; then
    die "Missing ${REQ_FILE}"
  fi

  if [[ "$BOOTSTRAP" -eq 1 ]] || ! "$VENV_DIR/bin/python" -c "import fastapi, uvicorn, pandas, yfinance, edgar" >/dev/null 2>&1; then
    log "Installing API review dependencies from requirements-api.txt"
    "$VENV_DIR/bin/python" -m pip install --upgrade pip
    "$VENV_DIR/bin/python" -m pip install -r "$REQ_FILE"
  fi
}

ensure_node_modules() {
  if [[ "$BOOTSTRAP" -eq 1 ]] || [[ ! -d "$FRONTEND_DIR/node_modules" ]]; then
    log "Installing frontend dependencies"
    (
      cd "$FRONTEND_DIR"
      TMPDIR=/tmp TMP=/tmp TEMP=/tmp npm install
    )
  fi
}

build_frontend() {
  log "Building frontend bundle"
  (
    cd "$FRONTEND_DIR"
    TMPDIR=/tmp TMP=/tmp TEMP=/tmp VITE_API_BASE="${API_URL}/api" npm run build
  )
}

wait_for_ready() {
  local url="$1"
  local attempts="${2:-40}"
  local delay="${3:-1}"
  local attempt

  for ((attempt=1; attempt<=attempts; attempt+=1)); do
    if curl -fsS "$url" >/dev/null 2>&1; then
      return 0
    fi
    sleep "$delay"
  done

  die "Timed out waiting for ${url}"
}

start_api() {
  local pid
  pid="$(port_pid "$API_PORT")"

  if [[ -n "$pid" ]]; then
    if curl -fsS "${API_URL}${API_HEALTH_PATH}" >/dev/null 2>&1; then
      API_PID="$pid"
      log "Reusing API on ${API_URL} (pid ${API_PID})"
      return 0
    fi
    log "Clearing stale API listener on port ${API_PORT}"
    kill_port "$API_PORT"
  fi

  : > "$API_LOG"
  cd "$REPO_ROOT"
  nohup "$VENV_DIR/bin/python" -m uvicorn api.main:app --host "$API_HOST" --port "$API_PORT" >"$API_LOG" 2>&1 &
  API_PID="$!"
  wait_for_ready "${API_URL}${API_HEALTH_PATH}" 60 1
  log "Started API on ${API_URL} (pid ${API_PID})"
}

start_frontend() {
  local pid
  pid="$(port_pid "$WEB_PORT")"

  if [[ -n "$pid" ]]; then
    if curl -fsS "$WEB_URL" >/dev/null 2>&1; then
      WEB_PID="$pid"
      log "Reusing frontend on ${WEB_URL} (pid ${WEB_PID})"
      return 0
    fi
    log "Clearing stale frontend listener on port ${WEB_PORT}"
    kill_port "$WEB_PORT"
  fi

  build_frontend
  : > "$WEB_LOG"
  cd "$REPO_ROOT"
  nohup "$VENV_DIR/bin/python" "$FRONTEND_SERVER" --root "$FRONTEND_DIST_DIR" --host "$WEB_HOST" --port "$WEB_PORT" >"$WEB_LOG" 2>&1 &
  WEB_PID="$!"
  wait_for_ready "$WEB_URL" 60 1
  log "Started frontend on ${WEB_URL} (pid ${WEB_PID})"
}

stop_all() {
  load_state

  if is_pid_alive "$WEB_PID"; then
    kill "$WEB_PID" 2>/dev/null || true
  fi
  if is_pid_alive "$API_PID"; then
    kill "$API_PID" 2>/dev/null || true
  fi

  kill_port "$WEB_PORT"
  kill_port "$API_PORT"
  rm -f "$STATE_FILE"
  log "Stopped React WSL stack."
}

show_status() {
  load_state
  local live_api_pid live_web_pid api_state web_state

  live_api_pid="$(port_pid "$API_PORT")"
  live_web_pid="$(port_pid "$WEB_PORT")"

  api_state="down"
  web_state="down"
  if [[ -n "$live_api_pid" ]] && curl -fsS "${API_URL}${API_HEALTH_PATH}" >/dev/null 2>&1; then
    api_state="healthy"
  elif [[ -n "$live_api_pid" ]]; then
    api_state="listening-unhealthy"
  fi

  if [[ -n "$live_web_pid" ]] && curl -fsS "$WEB_URL" >/dev/null 2>&1; then
    web_state="healthy"
  elif [[ -n "$live_web_pid" ]]; then
    web_state="listening-unhealthy"
  fi

  cat <<EOF
Alpha Pod React WSL status
State file: ${STATE_FILE}
Updated: ${UPDATED_AT:-not written}

API:
  saved_pid: ${API_PID:-}
  live_pid: ${live_api_pid:-}
  url: ${API_URL}
  health: ${api_state}
  log: ${API_LOG}

Frontend:
  saved_pid: ${WEB_PID:-}
  live_pid: ${live_web_pid:-}
  url: ${WEB_URL}
  health: ${web_state}
  log: ${WEB_LOG}
EOF
}

show_preview() {
  cat <<EOF
Alpha Pod React WSL launcher preview
Repository root: ${REPO_ROOT}
Virtualenv: ${VENV_DIR}
Requirements: ${REQ_FILE}
State file: ${STATE_FILE}

Bootstrap commands:
  python3 -m venv "${VENV_DIR}"
  "${VENV_DIR}/bin/python" -m pip install --upgrade pip
  "${VENV_DIR}/bin/python" -m pip install -r "${REQ_FILE}"
  npm --prefix frontend install
  TMPDIR=/tmp TMP=/tmp TEMP=/tmp VITE_API_BASE="${API_URL}/api" npm --prefix frontend run build

Launch commands:
  "${VENV_DIR}/bin/python" -m uvicorn api.main:app --host ${API_HOST} --port ${API_PORT}
  TMPDIR=/tmp TMP=/tmp TEMP=/tmp VITE_API_BASE="${API_URL}/api" npm --prefix frontend run build
  "${VENV_DIR}/bin/python" "${FRONTEND_SERVER}" --root "${FRONTEND_DIST_DIR}" --host ${WEB_HOST} --port ${WEB_PORT}

URLs:
  API: ${API_URL}
  Web: ${WEB_URL}

Playwright:
  export HOME=/tmp/codex-playwright-home
  export TMPDIR=/tmp
  export TMP=/tmp
  export TEMP=/tmp
  playwright-cli open ${WEB_URL}/watchlist
  playwright-cli snapshot
  playwright-cli screenshot

Status:
  bash scripts/manual/launch-react-wsl.sh --status

Stop:
  bash scripts/manual/launch-react-wsl.sh --stop
EOF
}

print_ready_banner() {
  cat <<EOF
React WSL stack ready.
API:  ${API_URL}
Web:  ${WEB_URL}
Logs:
  ${API_LOG}
  ${WEB_LOG}

Playwright:
  export HOME=/tmp/codex-playwright-home
  export TMPDIR=/tmp
  export TMP=/tmp
  export TEMP=/tmp
  playwright-cli open ${WEB_URL}/watchlist
  playwright-cli open ${WEB_URL}/ticker/IBM/overview
  playwright-cli open ${WEB_URL}/ticker/IBM/valuation
  playwright-cli snapshot
  playwright-cli screenshot

Status:
  bash scripts/manual/launch-react-wsl.sh --status

Stop:
  bash scripts/manual/launch-react-wsl.sh --stop
EOF
}

for arg in "$@"; do
  case "$arg" in
    --preview) PREVIEW=1 ;;
    --stop) STOP=1 ;;
    --bootstrap) BOOTSTRAP=1 ;;
    --status) STATUS=1 ;;
    -h|--help) usage; exit 0 ;;
    *) die "Unknown argument: ${arg}" ;;
  esac
done

require_command python3
require_command npm
require_command curl
require_command lsof

mkdir -p "$STATE_DIR"

if [[ "$PREVIEW" -eq 1 ]]; then
  show_preview
  exit 0
fi

if [[ "$STOP" -eq 1 ]]; then
  stop_all
  exit 0
fi

if [[ "$STATUS" -eq 1 ]]; then
  show_status
  exit 0
fi

ensure_venv
ensure_node_modules
start_api
start_frontend
write_state
print_ready_banner
