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
from playwait.effort import cooldown_seconds_for_effort, score_effort
from playwait.state import Mode, State, clear_awaiting, load_state, note_awaiting, save_state

log = logging.getLogger("playwait")


def quiet_confirm(desktop: Desktop, config: Config, title: str, body: str) -> None:
    desktop.notify(title, body)
    desktop.play_sound(config.resolve_sound("confirm"), wait=False)


def interrupt_notify(desktop: Desktop, config: Config, body: str) -> None:
    desktop.notify("playwait", body)
    desktop.play_sound(config.resolve_sound("interrupt"), wait=False)


def do_interrupt(desktop: Desktop, config: Config, state: State) -> State:
    """Chime, then staged pause → minimize → raise Cursor (less abrupt)."""
    if not state.window_id:
        log.warning("interrupt skipped: no armed window")
        return state

    wid = state.window_id
    # Lead with peaceful chime + notify while still in the game.
    interrupt_notify(desktop, config, "Agent ready — easing back to Cursor")
    if config.interrupt_lead_seconds > 0:
        time.sleep(config.interrupt_lead_seconds)

    if desktop.send_key(wid, config.pause_key):
        state.paused = True
    else:
        log.warning("pause key failed; continuing with minimize")
        state.paused = False

    if config.interrupt_step_seconds > 0:
        time.sleep(config.interrupt_step_seconds)

    desktop.minimize(wid)
    # Give the compositor a beat for its minimize animation.
    if config.interrupt_step_seconds > 0:
        time.sleep(config.interrupt_step_seconds)

    cursor = desktop.find_cursor_window(config.cursor_name, config.cursor_class)
    if cursor:
        desktop.activate(cursor)
    else:
        log.warning("Cursor window not found")

    state.mode = Mode.INTERRUPTED
    state.pending = False
    state.peak_effort = 0.0
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
    state.peak_effort = 0.0
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
    cid = conversation_id or "_unscoped"
    if state.mode == Mode.IDLE or not state.window_id:
        log.info(
            "stop: ignored (disarmed) conversation=%s mode=%s",
            cid,
            state.mode.value,
        )
        return state

    note_awaiting(state, cid)
    log.info(
        "stop: conversation=%s mode=%s awaiting=%s",
        cid,
        state.mode.value,
        state.awaiting_reply,
    )

    # Reconcile overdue cool-down (e.g. after sleep).
    if state.mode == Mode.COOLDOWN and state.cooldown_overdue(now):
        if state.pending:
            log.info("stop: cool-down overdue with pending → interrupt")
            return do_interrupt(desktop, config, state)
        state.mode = Mode.ARMED
        state.cooldown_until = None
        # Fall through if a stop just arrived while overdue without pending —
        # treat as normal armed interrupt below.

    if state.cooldown_active(now):
        state.pending = True
        log.info(
            "stop: cool-down active → pending; awaiting=%s",
            state.awaiting_reply,
        )
        return state

    if state.mode == Mode.INTERRUPTED:
        # Already yanked; still track this chat as needing a reply.
        log.info(
            "stop: already interrupted; awaiting=%s",
            state.awaiting_reply,
        )
        return state

    log.info("stop: interrupting → Cursor; awaiting=%s", state.awaiting_reply)
    return do_interrupt(desktop, config, state)


def handle_submit(
    desktop: Desktop,
    config: Config,
    state: State,
    *,
    conversation_id: str | None = None,
    prompt: str | None = None,
) -> State:
    """Cursor beforeSubmitPrompt: clear this chat; return to game when none remain."""
    cid = conversation_id or "_unscoped"
    if state.mode == Mode.IDLE or not state.window_id:
        log.info(
            "submit: ignored (disarmed) conversation=%s mode=%s",
            cid,
            state.mode.value,
        )
        return state

    before = list(state.awaiting_reply)
    if state.mode == Mode.INTERRUPTED or state.awaiting_reply:
        effort = score_effort(prompt or "")
        state.peak_effort = max(state.peak_effort, effort)
    else:
        effort = 0.0

    cleared = clear_awaiting(state, cid)
    log.info(
        "submit: conversation=%s cleared=%s mode=%s effort=%.2f peak=%.2f "
        "awaiting_before=%s awaiting_after=%s",
        cid,
        cleared,
        state.mode.value,
        effort,
        state.peak_effort,
        before,
        state.awaiting_reply,
    )

    if state.awaiting_reply:
        n = len(state.awaiting_reply)
        desktop.notify(
            "playwait",
            f"{n} chat{'s' if n != 1 else ''} still need a reply — staying in Cursor",
        )
        log.info(
            "submit: staying in Cursor; still awaiting %s",
            state.awaiting_reply,
        )
        return state

    if state.mode != Mode.INTERRUPTED:
        # Already back in game / cool-down / armed — nothing to raise.
        log.info(
            "submit: all chats clear but mode=%s — no return-to-game",
            state.mode.value,
        )
        return state

    log.info("submit: last chat answered → return to game")
    return return_to_game(desktop, config, state)


def return_to_game(desktop: Desktop, config: Config, state: State) -> State:
    """Raise the armed game with a short soft lead-in."""
    if not state.window_id or state.mode != Mode.INTERRUPTED:
        log.info(
            "return_to_game: skipped mode=%s window_id=%s",
            state.mode.value,
            state.window_id,
        )
        return state

    seconds = cooldown_seconds_for_effort(
        state.peak_effort,
        minimum=config.cooldown_min_seconds,
        maximum=config.cooldown_max_seconds,
    )
    log.info(
        "return_to_game: activate=%s cool-down=%ss peak_effort=%.2f",
        state.window_id,
        seconds,
        state.peak_effort,
    )
    quiet_confirm(
        desktop,
        config,
        "playwait",
        f"Back to game — {seconds}s cool-down",
    )
    if config.return_lead_seconds > 0:
        time.sleep(config.return_lead_seconds)

    desktop.activate(state.window_id)
    return on_resume_focus(desktop, config, state, cooldown_seconds=seconds)


def on_resume_focus(
    desktop: Desktop,
    config: Config,
    state: State,
    *,
    cooldown_seconds: int | None = None,
) -> State:
    """Game focused again after interrupt."""
    if state.mode != Mode.INTERRUPTED or not state.window_id:
        return state
    if state.paused:
        desktop.send_key(state.window_id, config.resume_key)
        state.paused = False
    duration = (
        cooldown_seconds
        if cooldown_seconds is not None
        else config.cooldown_seconds
    )
    duration = max(1, int(duration))
    state.mode = Mode.COOLDOWN
    state.cooldown_until = time.time() + duration
    state.peak_effort = 0.0
    # Stop resume-watch if it was still running; start cool-down waiter.
    if state.resume_watch_pid:
        _kill_pid(state.resume_watch_pid)
        state.resume_watch_pid = None
    state.cooldown_wait_pid = _spawn_self(["cooldown-wait"])
    log.info("cool-down %ss (until %s)", duration, state.cooldown_until)
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
    # Force=True so each hook process always attaches the file handler
    # (basicConfig is a no-op if something else configured logging first).
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(config.log_path),
            logging.StreamHandler(sys.stderr),
        ],
        force=True,
    )
