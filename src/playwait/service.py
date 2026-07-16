from __future__ import annotations

import logging
import os
import signal
import subprocess
import sys
import time
from typing import Any

from playwait.actions import Desktop
from playwait.config import Config
from playwait.effort import cooldown_seconds_for_effort, score_effort
from playwait.permission import shell_needs_permission_interrupt
from playwait.state import (
    Mode,
    State,
    clear_all_awaiting,
    clear_awaiting,
    load_state,
    note_awaiting,
    prune_stale_awaiting,
    save_state,
)

log = logging.getLogger("playwait")


def quiet_confirm(desktop: Desktop, config: Config, title: str, body: str) -> None:
    if config.desktop_notifications:
        desktop.notify(title, body)
    desktop.play_sound(config.resolve_sound("confirm"), wait=False)


def interrupt_notify(desktop: Desktop, config: Config, body: str) -> None:
    if config.desktop_notifications:
        desktop.notify("playwait", body)
    desktop.play_sound(config.resolve_sound("interrupt"), wait=False)


def do_interrupt(
    desktop: Desktop,
    config: Config,
    state: State,
    *,
    body: str = "Agent ready — easing back to Cursor",
    activate_game_for_pause: bool = True,
    skip_cooldown: bool | None = None,
) -> State:
    """Chime, then staged pause → minimize → raise Cursor (less abrupt)."""
    if not state.window_id:
        log.warning("interrupt skipped: no armed window")
        return state

    # Cancel an in-progress cool-down so permission/turn interrupts are not deferred.
    if state.mode == Mode.COOLDOWN:
        if state.cooldown_wait_pid:
            _kill_pid(state.cooldown_wait_pid)
            state.cooldown_wait_pid = None
        state.cooldown_until = None

    wid = state.window_id
    interrupt_notify(desktop, config, body)
    if config.interrupt_lead_seconds > 0:
        time.sleep(config.interrupt_lead_seconds)

    if desktop.send_key(wid, config.pause_key, activate=activate_game_for_pause):
        state.paused = True
    else:
        log.warning("pause key failed; continuing with minimize")
        state.paused = False

    if config.interrupt_step_seconds > 0:
        time.sleep(config.interrupt_step_seconds)

    minimized = desktop.minimize(wid)
    log.info("interrupt: minimize %s ok=%s", wid, minimized)
    if config.interrupt_step_seconds > 0:
        time.sleep(config.interrupt_step_seconds)

    focused = desktop.focus_cursor(config.cursor_name, config.cursor_class)
    if not focused:
        log.warning("Cursor window not focused after interrupt")
    else:
        log.info("interrupt: Cursor focused")

    state.mode = Mode.INTERRUPTED
    state.pending = False
    state.peak_effort = 0.0
    if skip_cooldown is not None:
        state.skip_cooldown = skip_cooldown
    if not state.skip_cooldown:
        state.permission_gate_active = False
    pid = _spawn_self(["resume-watch"])
    state.resume_watch_pid = pid
    return state


def soft_interrupt_already_away(
    desktop: Desktop,
    config: Config,
    state: State,
    *,
    body: str = "Agent ready — you are already in Cursor",
    skip_cooldown: bool | None = None,
) -> State:
    """Pending/attention while focus is not on the game — do not raise the game."""
    if not state.window_id:
        return state

    if state.mode == Mode.COOLDOWN:
        if state.cooldown_wait_pid:
            _kill_pid(state.cooldown_wait_pid)
            state.cooldown_wait_pid = None
        state.cooldown_until = None

    interrupt_notify(desktop, config, body)
    wid = state.window_id
    # Avoid windowactivate on the game — that steals focus from Cursor.
    if desktop.send_key(wid, config.pause_key, activate=False):
        state.paused = True
    else:
        state.paused = False
    desktop.minimize(wid)

    state.mode = Mode.INTERRUPTED
    state.pending = False
    state.peak_effort = 0.0
    if skip_cooldown is not None:
        state.skip_cooldown = skip_cooldown
    if state.resume_watch_pid:
        _kill_pid(state.resume_watch_pid)
    state.resume_watch_pid = _spawn_self(["resume-watch"])
    log.info("soft interrupt (already away from game); awaiting=%s", state.awaiting_reply)
    return state


def arm(desktop: Desktop, config: Config, state: State) -> State:
    wid = desktop.active_window_id()
    if not wid:
        if config.desktop_notifications:
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
    state.awaiting_activity = {}
    state.peak_effort = 0.0
    state.skip_cooldown = False
    state.permission_gate_active = False
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

    note_awaiting(state, cid, now=now)
    # Turn-end always wants effort cool-down on eventual return, even if a
    # permission gate had set skip_cooldown while already interrupted.
    state.skip_cooldown = False
    dropped = prune_stale_awaiting(
        state, ttl_seconds=config.awaiting_ttl_seconds, now=now
    )
    if dropped:
        log.info("stop: pruned stale awaiting %s", dropped)
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
            return _interrupt_respecting_focus(desktop, config, state)
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
        log.info(
            "stop: already interrupted; awaiting=%s",
            state.awaiting_reply,
        )
        return state

    log.info("stop: interrupting → Cursor; awaiting=%s", state.awaiting_reply)
    # Never raise the game if the user is already in Cursor (avoids game↔Cursor flicker).
    return _interrupt_respecting_focus(desktop, config, state)


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
    # Touch activity for any remaining chats is not needed; prune abandoned ones.
    dropped = prune_stale_awaiting(state, ttl_seconds=config.awaiting_ttl_seconds)
    if dropped:
        log.info("submit: pruned stale awaiting %s", dropped)
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
        if config.desktop_notifications:
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
        log.info(
            "submit: all chats clear but mode=%s — no return-to-game",
            state.mode.value,
        )
        return state

    log.info("submit: last chat answered → return to game")
    return return_to_game(desktop, config, state)


def handle_permission(
    desktop: Desktop,
    config: Config,
    state: State,
    *,
    source: str,
    command: str | None = None,
    tool_name: str | None = None,
) -> tuple[State, dict[str, Any]]:
    """beforeShellExecution / beforeMCPExecution: auto-interrupt for approvals.

    Returns (state, hook_stdout_json). Does not track awaiting_reply. Bypasses
    cool-down; resume skips cool-down so the next approval can yank immediately.
    """
    empty: dict[str, Any] = {}
    if state.mode == Mode.IDLE or not state.window_id:
        log.info("permission: ignored (disarmed) source=%s", source)
        return state, empty

    should = False
    if source == "mcp":
        should = config.mcp_permission_interrupt
    elif source == "shell":
        patterns = config.shell_permission_patterns or None
        should = shell_needs_permission_interrupt(
            command or "",
            mode=config.shell_permission_interrupt,
            patterns=patterns,
        )
    else:
        log.warning("permission: unknown source=%s", source)
        return state, empty

    if not should:
        log.info(
            "permission: pass-through source=%s tool=%s cmd=%r",
            source,
            tool_name,
            (command or "")[:120],
        )
        return state, empty

    label = tool_name or (command[:80] if command else source)
    body = f"Tool needs approval — {label}"
    log.info(
        "permission: interrupt source=%s mode=%s label=%r",
        source,
        state.mode.value,
        label,
    )

    if state.mode == Mode.INTERRUPTED:
        # Already yanked; still nudge with a chime and force ask for shell/MCP.
        interrupt_notify(desktop, config, body)
        state.skip_cooldown = True
        state.permission_gate_active = True
        return state, {"permission": "ask"}

    # Full yank unless focus is already on a Cursor window (not merely
    # "active != armed id" — Proton games often focus a child window).
    if _cursor_has_focus(desktop, config):
        state = soft_interrupt_already_away(
            desktop,
            config,
            state,
            body=body,
            skip_cooldown=True,
        )
    else:
        state = do_interrupt(
            desktop,
            config,
            state,
            body=body,
            activate_game_for_pause=True,
            skip_cooldown=True,
        )
    state.permission_gate_active = True
    return state, {"permission": "ask"}


def handle_permission_done(
    desktop: Desktop,
    config: Config,
    state: State,
) -> State:
    """afterShellExecution / afterMCPExecution: return to game after an approval.

    Fires after Allow (tool finished) or may not fire on Deny. Only auto-returns
    when this interrupt was for a permission gate and no chats still need a reply.
    """
    if state.mode == Mode.IDLE or not state.window_id:
        return state
    dropped = prune_stale_awaiting(state, ttl_seconds=config.awaiting_ttl_seconds)
    if dropped:
        log.info("permission-done: pruned stale awaiting %s", dropped)
    if not state.permission_gate_active:
        log.info("permission-done: ignore (no active permission gate)")
        return state
    if state.awaiting_reply:
        log.info(
            "permission-done: stay in Cursor; still awaiting %s",
            state.awaiting_reply,
        )
        # Gate handled; don't yank back while turn-end replies are outstanding.
        state.permission_gate_active = False
        return state
    if state.mode != Mode.INTERRUPTED:
        state.permission_gate_active = False
        log.info("permission-done: mode=%s — clear gate only", state.mode.value)
        return state

    log.info("permission-done: returning to game (no cool-down)")
    state.permission_gate_active = False
    state.skip_cooldown = True
    return return_to_game(desktop, config, state)


def release(
    desktop: Desktop,
    config: Config,
    state: State,
) -> State:
    """Clear awaiting chats and return to the game if interrupted.

    Use when you're done in Cursor but won't send another message in a waiting chat.
    """
    if state.mode == Mode.IDLE or not state.window_id:
        log.info("release: ignored (disarmed)")
        return state

    cleared = clear_all_awaiting(state)
    state.pending = False
    state.permission_gate_active = False
    log.info("release: cleared awaiting %s mode=%s", cleared, state.mode.value)

    if state.mode == Mode.INTERRUPTED:
        quiet_confirm(desktop, config, "playwait", "Released — back to game")
        return return_to_game(desktop, config, state)

    if state.mode == Mode.COOLDOWN:
        # Stop waiting out cool-down bookkeeping for old chats; keep playing.
        quiet_confirm(
            desktop,
            config,
            "playwait",
            f"Released {len(cleared)} waiting chat(s)",
        )
        return state

    quiet_confirm(
        desktop,
        config,
        "playwait",
        f"Released {len(cleared)} waiting chat(s)",
    )
    return state


def return_to_game(desktop: Desktop, config: Config, state: State) -> State:
    """Raise the armed game with a short soft lead-in."""
    if not state.window_id or state.mode != Mode.INTERRUPTED:
        log.info(
            "return_to_game: skipped mode=%s window_id=%s",
            state.mode.value,
            state.window_id,
        )
        return state

    if state.skip_cooldown:
        log.info("return_to_game: activate=%s (no cool-down)", state.window_id)
        quiet_confirm(desktop, config, "playwait", "Back to game")
        if config.return_lead_seconds > 0:
            time.sleep(config.return_lead_seconds)
        desktop.activate(state.window_id)
        return on_resume_focus(desktop, config, state)

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
        desktop.send_key(state.window_id, config.resume_key, activate=True)
        state.paused = False

    if state.resume_watch_pid:
        _kill_pid(state.resume_watch_pid)
        state.resume_watch_pid = None

    if state.skip_cooldown:
        state.skip_cooldown = False
        state.permission_gate_active = False
        state.mode = Mode.ARMED
        state.cooldown_until = None
        state.cooldown_wait_pid = None
        state.peak_effort = 0.0
        log.info("resume: skip cool-down → armed")
        return state

    duration = (
        cooldown_seconds
        if cooldown_seconds is not None
        else config.cooldown_seconds
    )
    duration = max(1, int(duration))
    state.mode = Mode.COOLDOWN
    state.cooldown_until = time.time() + duration
    state.peak_effort = 0.0
    state.cooldown_wait_pid = _spawn_self(["cooldown-wait"])
    log.info("cool-down %ss (until %s)", duration, state.cooldown_until)
    return state


def on_cooldown_left_game(
    desktop: Desktop,
    config: Config,
    state: State,
) -> State:
    """User left the game during cool-down (e.g. back to Cursor).

    Do not raise the game. If a deferred stop is pending, enter interrupted
    quietly without a focus dance so the user can keep working in Cursor.
    """
    if state.mode != Mode.COOLDOWN:
        return state
    state.cooldown_wait_pid = None
    state.cooldown_until = None
    if state.pending and state.window_id:
        log.info("cool-down abandoned with pending → soft interrupt (stay put)")
        return soft_interrupt_already_away(desktop, config, state)
    state.mode = Mode.ARMED
    state.pending = False
    log.info("cool-down abandoned; armed (left game early, no focus change)")
    return state


def on_cooldown_expiry(desktop: Desktop, config: Config, state: State) -> State:
    if state.mode != Mode.COOLDOWN:
        return state
    state.cooldown_wait_pid = None
    state.cooldown_until = None
    if state.pending and state.window_id and state.mode != Mode.IDLE:
        return _interrupt_respecting_focus(desktop, config, state)
    state.mode = Mode.ARMED
    state.pending = False
    return state


def _cursor_has_focus(desktop: Desktop, config: Config) -> bool:
    active = desktop.active_window_id()
    if not active:
        return False
    return active in set(desktop.cursor_window_ids(config.cursor_name, config.cursor_class))


def _interrupt_respecting_focus(
    desktop: Desktop, config: Config, state: State
) -> State:
    """Full yank unless the user is already focused on Cursor."""
    if _cursor_has_focus(desktop, config):
        log.info("interrupt: Cursor already focused → soft path")
        return soft_interrupt_already_away(desktop, config, state)
    return do_interrupt(desktop, config, state)


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
        force=True,
    )
