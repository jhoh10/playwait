#!/usr/bin/env bash
# Cursor afterMCPExecution / afterShellExecution → clear permission gate (stay in Cursor).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PATH="${HOME}/.local/bin:${PATH}"

if command -v playwait >/dev/null 2>&1; then
  exec playwait on-permission-done
fi
if [[ -x "${ROOT}/.venv/bin/playwait" ]]; then
  exec "${ROOT}/.venv/bin/playwait" on-permission-done
fi
if [[ -d "${ROOT}/src/playwait" ]]; then
  export PYTHONPATH="${ROOT}/src${PYTHONPATH:+:$PYTHONPATH}"
  exec python3 -m playwait on-permission-done
fi
exit 0
