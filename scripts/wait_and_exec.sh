#!/usr/bin/env bash
# Wait for an executable to appear and then exec it with provided args.
# Usage:
#   ./wait_and_exec.sh /app/.venv/bin/python3 /app/scripts/watcher.py --watch-dir /app/markdown_files ...
#
# Environment:
#   WAIT_TIMEOUT - seconds to wait before trying fallbacks (default 180)
#   POLL_INTERVAL - seconds between checks (default 1)

set -euo pipefail

TARGET="$1"
shift || true

WAIT_TIMEOUT="${WAIT_TIMEOUT:-180}"   # total seconds to wait for TARGET
POLL_INTERVAL="${POLL_INTERVAL:-1}"   # seconds between polls

start=$(date +%s)
end=$((start + WAIT_TIMEOUT))

echo "wait_and_exec: waiting for target executable: ${TARGET} (timeout ${WAIT_TIMEOUT}s)"

while :; do
  if [ -x "${TARGET}" ]; then
    echo "wait_and_exec: found executable ${TARGET}, running..."
    exec "${TARGET}" "$@"
  fi

  now=$(date +%s)
  if [ "${now}" -ge "${end}" ]; then
    echo "wait_and_exec: timeout waiting for ${TARGET} after ${WAIT_TIMEOUT}s" >&2
    break
  fi

  sleep "${POLL_INTERVAL}"
done

# Fallback: try container system python3
if command -v python3 >/dev/null 2>&1; then
  echo "wait_and_exec: falling back to system python3"
  exec python3 "$@"
fi

echo "wait_and_exec: no python runtime available to run: $*" >&2
exit 1
