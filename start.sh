#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

PORT="${PORT:-8000}"
PUBLIC_HOST="${PUBLIC_HOST:-127.0.0.1}"
READY_TIMEOUT="${READY_TIMEOUT:-900}"
SSL_CERTFILE="${SSL_CERTFILE:-}"
SSL_KEYFILE="${SSL_KEYFILE:-}"
SCHEME="http"

if [[ -n "$SSL_CERTFILE" && -n "$SSL_KEYFILE" && -f "$SSL_CERTFILE" && -f "$SSL_KEYFILE" ]]; then
  SCHEME="https"
fi

HOST_URL="${SCHEME}://127.0.0.1:${PORT}"

SERVER_ARGS=(
  --root "$ROOT"
  --port "$PORT"
  --stdout-log "$ROOT/server.log"
  --stderr-log "$ROOT/server-error.log"
  --pid-file "$ROOT/server.pid"
)

if [[ "$SCHEME" == "https" ]]; then
  SERVER_ARGS+=(--ssl-certfile "$SSL_CERTFILE" --ssl-keyfile "$SSL_KEYFILE")
fi

health_ready() {
  if command -v curl >/dev/null 2>&1; then
    if [[ "$SCHEME" == "https" ]]; then
      if curl -fsSk "${HOST_URL}/health" >/dev/null 2>&1; then
        return 0
      fi
    elif curl -fsS "${HOST_URL}/health" >/dev/null 2>&1; then
      return 0
    fi
  fi
  if [[ -x ".venv/bin/python" ]]; then
    if [[ "$SCHEME" == "https" ]]; then
      .venv/bin/python -c "import ssl, urllib.request; urllib.request.urlopen('${HOST_URL}/health', context=ssl._create_unverified_context(), timeout=3).read()" >/dev/null 2>&1
    else
      .venv/bin/python -c "import urllib.request; urllib.request.urlopen('${HOST_URL}/health', timeout=3).read()" >/dev/null 2>&1
    fi
    return $?
  fi
  return 1
}

pid_running() {
  local pid="$1"
  [[ -n "$pid" ]] && kill -0 "$pid" >/dev/null 2>&1
}

read_pid_file() {
  local file="$1"
  [[ -f "$file" ]] && head -n 1 "$file" | tr -dc '0-9' || true
}

port_pid() {
  if command -v ss >/dev/null 2>&1; then
    ss -ltnp "( sport = :${PORT} )" 2>/dev/null \
      | sed -n 's/.*pid=\([0-9][0-9]*\).*/\1/p' \
      | head -n 1
  fi
}

print_ready() {
  echo "Server is running."
  echo "Local URL: ${HOST_URL}"
  echo "Browser URL: ${SCHEME}://${PUBLIC_HOST}:${PORT}"
  echo "Bind address: 0.0.0.0:${PORT}"
  echo "Logs: ./logs.sh -f"
}

wait_for_ready() {
  local message_every=15
  for second in $(seq 1 "$READY_TIMEOUT"); do
    if health_ready; then
      local listening_pid
      listening_pid="$(port_pid)"
      if [[ -n "$listening_pid" ]]; then
        echo "$listening_pid" > server.pid
      fi
      print_ready
      return 0
    fi
    if (( second % message_every == 0 )); then
      echo "Still waiting for startup... (${second}s/${READY_TIMEOUT}s)"
    fi
    sleep 1
  done
  return 1
}

if health_ready; then
  echo "MLPD server is already running."
  listening_pid="$(port_pid)"
  if [[ -n "$listening_pid" ]]; then
    echo "$listening_pid" > server.pid
  fi
  print_ready
  exit 0
fi

if [[ ! -x ".venv/bin/python" ]]; then
  echo "Missing .venv. Run ./setup_ubuntu.sh first."
  exit 1
fi

mkdir -p captures data .runtime-temp .cache .paddle

existing_pid="$(read_pid_file server.pid)"
if pid_running "$existing_pid"; then
  echo "MLPD server process is already starting or running (PID ${existing_pid})."
  echo "Waiting for it to become ready..."
  if wait_for_ready; then
    exit 0
  fi

  echo "Existing MLPD process did not become ready in time."
  echo "Use ./stop.sh, then run ./start.sh again if you want a clean restart."
  echo "--- recent server.log ---"
  if [[ -f "$ROOT/server.log" ]]; then tail -n 80 "$ROOT/server.log"; fi
  echo "--- recent server-error.log ---"
  if [[ -f "$ROOT/server-error.log" ]]; then tail -n 80 "$ROOT/server-error.log"; fi
  exit 1
fi

listening_pid="$(port_pid)"
if [[ -n "$listening_pid" ]]; then
  echo "Port ${PORT} is already in use by PID ${listening_pid}, but MLPD health is not ready."
  echo "Use PORT=8001 ./start.sh, or stop the process using port ${PORT}."
  exit 1
fi

nohup .venv/bin/python server_daemon.py "${SERVER_ARGS[@]}" >/dev/null 2>&1 &

echo "$!" > server-launcher.pid

echo "Starting MLPD server in background..."
if wait_for_ready; then
  exit 0
fi

echo "Server did not become ready in time."
echo "Check logs:"
echo "  ./logs.sh"
echo "  ./logs.sh -e"
echo "--- recent server.log ---"
if [[ -f "$ROOT/server.log" ]]; then tail -n 80 "$ROOT/server.log"; fi
echo "--- recent server-error.log ---"
if [[ -f "$ROOT/server-error.log" ]]; then tail -n 80 "$ROOT/server-error.log"; fi
exit 1
