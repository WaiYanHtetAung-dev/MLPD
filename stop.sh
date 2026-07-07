#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

PIDS=()
for f in server.pid server-launcher.pid; do
  if [[ -f "$f" ]]; then
    pid="$(head -n 1 "$f" | tr -dc '0-9')"
    if [[ -n "$pid" ]]; then
      PIDS+=("$pid")
    fi
  fi
done

if [[ "${#PIDS[@]}" -eq 0 ]]; then
  echo "No MLPD pid files found."
  exit 0
fi

for pid in "${PIDS[@]}"; do
  if kill -0 "$pid" >/dev/null 2>&1; then
    echo "Stopping PID $pid..."
    kill "$pid" >/dev/null 2>&1 || true
  fi
done

sleep 2

for pid in "${PIDS[@]}"; do
  if kill -0 "$pid" >/dev/null 2>&1; then
    echo "Force stopping PID $pid..."
    kill -9 "$pid" >/dev/null 2>&1 || true
  fi
done

rm -f server.pid server-launcher.pid
echo "Stopped."
