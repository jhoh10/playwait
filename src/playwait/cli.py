from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

from playwait.actions import X11Desktop
from playwait.config import load_config
from playwait.service import (
    arm,
    disarm,
    handle_permission,
    handle_permission_done,
    handle_stop,
    handle_submit,
    load,
    persist,
    release,
    setup_logging,
)
from playwait.state import Mode
from playwait.watchers import run_cooldown_wait, run_resume_watch


def _read_hook_payload() -> dict[str, Any]:
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            return {}
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def _conversation_id(payload: dict[str, Any]) -> str | None:
    for key in ("conversation_id", "session_id"):
        value = payload.get(key)
        if value is not None and str(value).strip():
            return str(value)
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="playwait", description="Agent-ready game interrupt")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("arm", help="Arm the currently focused window")
    sub.add_parser("disarm", help="Clear arm state")
    sub.add_parser(
        "release",
        help="Clear waiting chats and return to game if interrupted",
    )
    sub.add_parser("status", help="Print current state as JSON")
    sub.add_parser("on-stop", help="Cursor stop hook (reads JSON on stdin)")
    sub.add_parser(
        "on-submit",
        help="Cursor beforeSubmitPrompt hook (reads JSON on stdin; returns continue)",
    )
    sub.add_parser(
        "on-permission",
        help="Cursor beforeShellExecution / beforeMCPExecution (JSON in, JSON out)",
    )
    sub.add_parser(
        "on-permission-done",
        help="Cursor afterShellExecution / afterMCPExecution — return after approval",
    )
    sub.add_parser("resume-watch", help="Internal: wait for game focus after interrupt")
    sub.add_parser("cooldown-wait", help="Internal: wait out cool-down / deferred yank")

    args = parser.parse_args(argv)
    config = load_config()
    desktop = X11Desktop()

    if args.cmd == "status":
        state = load(config)
        print(json.dumps(state.to_dict(), indent=2))
        return 0

    setup_logging(config)

    if args.cmd == "arm":
        state = arm(desktop, config, load(config))
        persist(config, state)
        return 0 if state.mode == Mode.ARMED else 1

    if args.cmd == "disarm":
        state = disarm(desktop, config, load(config))
        persist(config, state)
        return 0

    if args.cmd == "release":
        state = release(desktop, config, load(config))
        persist(config, state)
        return 0

    if args.cmd == "on-stop":
        payload = _read_hook_payload()
        state = handle_stop(
            desktop,
            config,
            load(config),
            conversation_id=_conversation_id(payload),
        )
        persist(config, state)
        return 0

    if args.cmd == "on-submit":
        payload = _read_hook_payload()
        prompt = payload.get("prompt")
        state = handle_submit(
            desktop,
            config,
            load(config),
            conversation_id=_conversation_id(payload),
            prompt=str(prompt) if prompt is not None else "",
        )
        persist(config, state)
        print(json.dumps({"continue": True}))
        return 0

    if args.cmd == "on-permission":
        payload = _read_hook_payload()
        source = os.environ.get("PLAYWAIT_PERMISSION_SOURCE", "").strip().lower()
        if source not in ("mcp", "shell"):
            event = str(payload.get("hook_event_name") or "").lower()
            if "mcp" in event or payload.get("tool_name"):
                source = "mcp"
            else:
                source = "shell"
        if payload.get("playwait_source") in ("mcp", "shell"):
            source = str(payload["playwait_source"])
        command = payload.get("command")
        tool_name = payload.get("tool_name")
        state, out = handle_permission(
            desktop,
            config,
            load(config),
            source=source,
            command=str(command) if command is not None else None,
            tool_name=str(tool_name) if tool_name is not None else None,
        )
        persist(config, state)
        print(json.dumps(out))
        return 0

    if args.cmd == "on-permission-done":
        _read_hook_payload()  # consume stdin; payload unused for now
        state = handle_permission_done(desktop, config, load(config))
        persist(config, state)
        return 0

    if args.cmd == "resume-watch":
        return run_resume_watch(desktop, config)

    if args.cmd == "cooldown-wait":
        return run_cooldown_wait(desktop, config)

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
