"""Decide when a Shell/MCP gate should yank focus for approval."""

from __future__ import annotations

import re

# Default: commands that often require a human look while playing.
DEFAULT_SHELL_PATTERNS: tuple[str, ...] = (
    r"\bsudo\b",
    r"\bdoas\b",
    r"\bcurl\b",
    r"\bwget\b",
    r"\bssh\b",
    r"\bscp\b",
    r"\brsync\b",
    r"\bdocker\b",
    r"\bpodman\b",
    r"\bkubectl\b",
    r"\bnpm\s+publish\b",
    r"\bpip\s+install\b",
    r"\bapt(-get)?\s+install\b",
    r"\bdnf\s+install\b",
    r"\bgit\s+push\b",
    r"\bgit\s+commit\b",
    r"\brm\s+(-[a-zA-Z]*r|-[a-zA-Z]*f)",
    r"\bchmod\b",
    r"\bchown\b",
    r"\bkill\b",
    r"\bpkill\b",
    r"\bsystemctl\b",
    r"\bdd\b",
    r"\bmkfs\b",
)


def shell_needs_permission_interrupt(
    command: str,
    *,
    mode: str,
    patterns: list[str] | None = None,
) -> bool:
    """Return True if this shell command should auto-interrupt while armed.

    mode:
      - \"off\": never
      - \"ask-always\": every shell command
      - \"patterns\": only when command matches configured/default regexes
    """
    m = (mode or "patterns").strip().lower()
    if m in {"off", "false", "no", "0"}:
        return False
    if m in {"ask-always", "always", "ask_always"}:
        return True
    if m != "patterns":
        # Unknown mode → fail safe to patterns.
        m = "patterns"

    text = command or ""
    compiled = patterns if patterns is not None else list(DEFAULT_SHELL_PATTERNS)
    for raw in compiled:
        try:
            if re.search(raw, text, flags=re.IGNORECASE):
                return True
        except re.error:
            continue
    return False
