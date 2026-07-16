from __future__ import annotations

import argparse
import json
import sys

from playwait.actions import X11Desktop
from playwait.config import load_config
from playwait.service import arm, disarm, handle_stop, load, persist, setup_logging
from playwait.state import Mode
from playwait.watchers import run_cooldown_wait, run_resume_watch


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="playwait", description="Agent-ready game interrupt")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("arm", help="Arm the currently focused window")
    sub.add_parser("disarm", help="Clear arm state")
    sub.add_parser("status", help="Print current state as JSON")
    sub.add_parser("on-stop", help="Cursor stop hook (reads JSON on stdin)")
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

    if args.cmd == "on-stop":
        try:
            raw = sys.stdin.read()
            if raw.strip():
                json.loads(raw)
        except json.JSONDecodeError:
            pass
        state = handle_stop(desktop, config, load(config))
        persist(config, state)
        return 0

    if args.cmd == "resume-watch":
        return run_resume_watch(desktop, config)

    if args.cmd == "cooldown-wait":
        return run_cooldown_wait(desktop, config)

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
