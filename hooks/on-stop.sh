#!/usr/bin/env bash
# Cursor stop hook wrapper for playwait.
# Configure in ~/.cursor/hooks.json under "stop".
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PATH="${HOME}/.local/bin:${PATH}"

if command -v playwait >/dev/null 2>&1; then
  exec playwait on-stop
fi

if [[ -x "${ROOT}/.venv/bin/playwait" ]]; then
  exec "${ROOT}/.venv/bin/playwait" on-stop
fi

# Fallback: run module from repo checkout
if [[ -d "${ROOT}/src/playwait" ]]; then
  export PYTHONPATH="${ROOT}/src${PYTHONPATH:+:$PYTHONPATH}"
  exec python3 -m playwait on-stop
fi

echo "playwait: not installed; skipping" >&2
exit 0
