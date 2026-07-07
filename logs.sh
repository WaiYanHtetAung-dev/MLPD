#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

LOG="server.log"
FOLLOW="false"

while [[ $# -gt 0 ]]; do
  case "$1" in
    -e|--error)
      LOG="server-error.log"
      shift
      ;;
    -f|--follow)
      FOLLOW="true"
      shift
      ;;
    *)
      echo "Usage: ./logs.sh [-e|--error] [-f|--follow]"
      exit 1
      ;;
  esac
done

touch "$LOG"
echo "Showing $ROOT/$LOG"
if [[ "$FOLLOW" == "true" ]]; then
  tail -n 80 -f "$LOG"
else
  tail -n 120 "$LOG"
fi
