#!/usr/bin/env bash
# Cursor beforeMCPExecution → playwait on-permission (source=mcp)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PATH="${HOME}/.local/bin:${PATH}"
export PLAYWAIT_PERMISSION_SOURCE=mcp

run_playwait() {
  if command -v playwait >/dev/null 2>&1; then
    exec playwait on-permission
  fi
  if [[ -x "${ROOT}/.venv/bin/playwait" ]]; then
    exec "${ROOT}/.venv/bin/playwait" on-permission
  fi
  if [[ -d "${ROOT}/src/playwait" ]]; then
    export PYTHONPATH="${ROOT}/src${PYTHONPATH:+:$PYTHONPATH}"
    exec python3 -m playwait on-permission
  fi
  echo '{}'
  exit 0
}

run_playwait
