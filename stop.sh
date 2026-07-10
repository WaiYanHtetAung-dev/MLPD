#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

PORT="${PORT:-8000}"
PIDS=()
for f in server.pid server-launcher.pid; do
  if [[ -f "$f" ]]; then
    pid="$(head -n 1 "$f" | tr -dc '0-9')"
    if [[ -n "$pid" ]]; then
      PIDS+=("$pid")
    fi
  fi
done

if command -v ss >/dev/null 2>&1; then
  while IFS= read -r pid; do
    if [[ -n "$pid" ]]; then
      PIDS+=("$pid")
    fi
  done < <(ss -ltnp "( sport = :${PORT} )" 2>/dev/null | sed -n 's/.*pid=\([0-9][0-9]*\).*/\1/p')
fi

if [[ "${#PIDS[@]}" -gt 0 ]]; then
  mapfile -t PIDS < <(printf '%s\n' "${PIDS[@]}" | awk 'NF && !seen[$0]++')
fi

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
