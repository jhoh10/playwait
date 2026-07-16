from __future__ import annotations

import logging
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from playwait.actions import Desktop
from playwait.config import Config
from playwait.state import Mode, State, clear_awaiting, load_state, note_awaiting, save_state

log = logging.getLogger("playwait")


def quiet_confirm(desktop: Desktop, config: Config, title: str, body: str) -> None:
    desktop.notify(title, body)
    desktop.play_sound(config.resolve_sound("confirm"))


def interrupt_notify(desktop: Desktop, config: Config, body: str) -> None:
    desktop.notify("playwait", body)
    desktop.play_sound(config.resolve_sound("interrupt"))


def do_interrupt(desktop: Desktop, config: Config, state: State) -> State:
    """Pause game, minimize, raise Cursor, sound, spawn resume watcher."""
    if not state.window_id:
        log.warning("interrupt skipped: no armed window")
        return state

    wid = state.window_id
    if desktop.send_key(wid, config.pause_key):
        state.paused = True
    else:
        log.warning("pause key failed; continuing with minimize")
        state.paused = False

    desktop.minimize(wid)

    cursor = desktop.find_cursor_window(config.cursor_name, config.cursor_class)
    if cursor:
        desktop.activate(cursor)
    else:
        log.warning("Cursor window not found")

    interrupt_notify(desktop, config, "Agent ready — game paused")
    state.mode = Mode.INTERRUPTED
    state.pending = False
    pid = _spawn_self(["resume-watch"])
    state.resume_watch_pid = pid
    return state


def arm(desktop: Desktop, config: Config, state: State) -> State:
    wid = desktop.active_window_id()
    if not wid:
        desktop.notify("playwait", "Could not read active window")
        return state
    _cancel_watchers(state)
    state.mode = Mode.ARMED
    state.window_id = wid
    state.pid = desktop.window_pid(wid)
    state.pending = False
    state.cooldown_until = None
    state.paused = False
    state.resume_watch_pid = None
    state.cooldown_wait_pid = None
    state.awaiting_reply = []
    quiet_confirm(desktop, config, "playwait", f"Armed window {wid}")
    return state


def disarm(desktop: Desktop, config: Config, state: State) -> State:
    _cancel_watchers(state)
    state = State()
    quiet_confirm(desktop, config, "playwait", "Disarmed")
    return state


def handle_stop(
    desktop: Desktop,
    config: Config,
    state: State,
    *,
    conversation_id: str | None = None,
    now: float | None = None,
) -> State:
    """Cursor stop hook entry: interrupt, set pending, or no-op."""
    now = time.time() if now is None else now
    if state.mode == Mode.IDLE or not state.window_id:
        return state

    note_awaiting(state, conversation_id or "_unscoped")

    # Reconcile overdue cool-down (e.g. after sleep).
    if state.mode == Mode.COOLDOWN and state.cooldown_overdue(now):
        if state.pending:
            return do_interrupt(desktop, config, state)
        state.mode = Mode.ARMED
        state.cooldown_until = None
        # Fall through if a stop just arrived while overdue without pending —
        # treat as normal armed interrupt below.

    if state.cooldown_active(now):
        state.pending = True
        log.info("cool-down active; set pending attention")
        return state

    if state.mode == Mode.INTERRUPTED:
        # Already yanked; still track this chat as needing a reply.
        log.info(
            "already interrupted; awaiting_reply=%s",
            state.awaiting_reply,
        )
        return state

    return do_interrupt(desktop, config, state)


def handle_submit(
    desktop: Desktop,
    config: Config,
    state: State,
    *,
    conversation_id: str | None = None,
) -> State:
    """Cursor beforeSubmitPrompt: clear this chat; return to game when none remain."""
    if state.mode == Mode.IDLE or not state.window_id:
        return state

    clear_awaiting(state, conversation_id or "_unscoped")

    if state.awaiting_reply:
        n = len(state.awaiting_reply)
        desktop.notify(
            "playwait",
            f"{n} chat{'s' if n != 1 else ''} still need a reply — staying in Cursor",
        )
        log.info("submit cleared one chat; still awaiting %s", state.awaiting_reply)
        return state

    if state.mode != Mode.INTERRUPTED:
        # Already back in game / cool-down / armed — nothing to raise.
        log.info("all chats answered; mode=%s — no return-to-game needed", state.mode)
        return state

    return return_to_game(desktop, config, state)


def return_to_game(desktop: Desktop, config: Config, state: State) -> State:
    """Raise the armed game so resume-watch (or we) can unpause and start cool-down."""
    if not state.window_id or state.mode != Mode.INTERRUPTED:
        return state

    desktop.activate(state.window_id)
    # Apply resume + cool-down immediately so we do not depend on polling focus.
    state = on_resume_focus(desktop, config, state)
    quiet_confirm(desktop, config, "playwait", "Back to game — all chats answered")
    return state


def on_resume_focus(desktop: Desktop, config: Config, state: State) -> State:
    """Game focused again after interrupt."""
    if state.mode != Mode.INTERRUPTED or not state.window_id:
        return state
    if state.paused:
        desktop.send_key(state.window_id, config.resume_key)
        state.paused = False
    state.mode = Mode.COOLDOWN
    state.cooldown_until = time.time() + config.cooldown_seconds
    # Stop resume-watch if it was still running; start cool-down waiter.
    if state.resume_watch_pid:
        _kill_pid(state.resume_watch_pid)
        state.resume_watch_pid = None
    state.cooldown_wait_pid = _spawn_self(["cooldown-wait"])
    return state


def on_cooldown_expiry(desktop: Desktop, config: Config, state: State) -> State:
    if state.mode != Mode.COOLDOWN:
        return state
    state.cooldown_wait_pid = None
    state.cooldown_until = None
    if state.pending and state.window_id and state.mode != Mode.IDLE:
        return do_interrupt(desktop, config, state)
    state.mode = Mode.ARMED
    state.pending = False
    return state


def _spawn_self(args: list[str]) -> int | None:
    """Spawn `python -m playwait …` detached; return pid."""
    cmd = [sys.executable, "-m", "playwait", *args]
    try:
        proc = subprocess.Popen(  # noqa: S603 — controlled argv
            cmd,
            start_new_session=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=os.environ.copy(),
        )
        return proc.pid
    except OSError as exc:
        log.warning("failed to spawn %s: %s", cmd, exc)
        return None


def _cancel_watchers(state: State) -> None:
    for attr in ("resume_watch_pid", "cooldown_wait_pid"):
        pid = getattr(state, attr)
        if pid:
            _kill_pid(pid)
            setattr(state, attr, None)


def _kill_pid(pid: int) -> None:
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    except PermissionError:
        log.warning("could not signal pid %s", pid)


def persist(config: Config, state: State) -> None:
    save_state(config.state_path, state)


def load(config: Config) -> State:
    return load_state(config.state_path)


def setup_logging(config: Config) -> None:
    config.state_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(config.log_path),
            logging.StreamHandler(sys.stderr),
        ],
    )
