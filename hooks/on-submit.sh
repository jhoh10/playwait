#!/usr/bin/env bash
# Cursor beforeSubmitPrompt hook wrapper for playwait.
# Configure in ~/.cursor/hooks.json under "beforeSubmitPrompt".
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PATH="${HOME}/.local/bin:${PATH}"

run_playwait() {
  if command -v playwait >/dev/null 2>&1; then
    exec playwait on-submit
  fi
  if [[ -x "${ROOT}/.venv/bin/playwait" ]]; then
    exec "${ROOT}/.venv/bin/playwait" on-submit
  fi
  if [[ -d "${ROOT}/src/playwait" ]]; then
    export PYTHONPATH="${ROOT}/src${PYTHONPATH:+:$PYTHONPATH}"
    exec python3 -m playwait on-submit
  fi
  # Fail open: allow the prompt if playwait is missing.
  echo '{"continue":true}'
  exit 0
}

run_playwait
