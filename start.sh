#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

PORT="${PORT:-8000}"
HOST_URL="http://127.0.0.1:${PORT}"
PUBLIC_HOST="${PUBLIC_HOST:-52.76.141.146}"
READY_TIMEOUT="${READY_TIMEOUT:-300}"

if command -v curl >/dev/null 2>&1; then
  if curl -fsS "${HOST_URL}/health" >/dev/null 2>&1; then
    echo "MLPD server is already running."
    echo "Local URL: ${HOST_URL}"
    echo "Browser URL: http://${PUBLIC_HOST}:${PORT}"
    echo "Bind address: 0.0.0.0:${PORT}"
    echo "Logs: ./logs.sh -f"
    exit 0
  fi
fi

if [[ ! -x ".venv/bin/python" ]]; then
  echo "Missing .venv. Run ./setup_ubuntu.sh first."
  exit 1
fi

mkdir -p captures data .runtime-temp .cache .paddle

nohup .venv/bin/python server_daemon.py \
  --root "$ROOT" \
  --port "$PORT" \
  --stdout-log "$ROOT/server.log" \
  --stderr-log "$ROOT/server-error.log" \
  --pid-file "$ROOT/server.pid" \
  >/dev/null 2>&1 &

echo "$!" > server-launcher.pid

echo "Starting MLPD server in background..."
for _ in $(seq 1 "$READY_TIMEOUT"); do
  if command -v curl >/dev/null 2>&1 && curl -fsS "${HOST_URL}/health" >/dev/null 2>&1; then
    echo "Server is running."
    echo "Local URL: ${HOST_URL}"
    echo "Browser URL: http://${PUBLIC_HOST}:${PORT}"
    echo "Bind address: 0.0.0.0:${PORT}"
    echo "Logs: ./logs.sh -f"
    exit 0
  fi
  sleep 1
done

echo "Server did not become ready in time."
echo "Check logs:"
echo "  ./logs.sh"
echo "  ./logs.sh -e"
echo "--- recent server.log ---"
if [[ -f "$ROOT/server.log" ]]; then tail -n 80 "$ROOT/server.log"; fi
echo "--- recent server-error.log ---"
if [[ -f "$ROOT/server-error.log" ]]; then tail -n 80 "$ROOT/server-error.log"; fi
exit 1
