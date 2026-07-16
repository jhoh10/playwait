from __future__ import annotations

import logging
import time

from playwait.actions import Desktop
from playwait.config import Config
from playwait.service import (
    load,
    on_cooldown_expiry,
    on_cooldown_left_game,
    on_resume_focus,
    persist,
    setup_logging,
)
from playwait.state import Mode

log = logging.getLogger("playwait")


def run_resume_watch(desktop: Desktop, config: Config) -> int:
    """Poll until armed window is focused, then resume (+ cool-down unless skipped).

    Require stable game focus briefly so a momentary activate-for-Esc does not
    count as the user returning to the game.
    """
    setup_logging(config)
    deadline = time.time() + 24 * 3600  # safety cap
    focused_since: float | None = None
    settle = max(0.5, float(config.poll_interval_seconds))
    while time.time() < deadline:
        state = load(config)
        if state.mode != Mode.INTERRUPTED or not state.window_id:
            return 0
        active = desktop.active_window_id()
        if active and active == state.window_id:
            if focused_since is None:
                focused_since = time.time()
            elif time.time() - focused_since >= settle:
                state = on_resume_focus(desktop, config, state)
                persist(config, state)
                log.info(
                    "resumed; mode=%s cool-down_until=%s",
                    state.mode.value,
                    state.cooldown_until,
                )
                return 0
        else:
            focused_since = None
        time.sleep(config.poll_interval_seconds)
    log.warning("resume-watch timed out")
    return 1


def run_cooldown_wait(desktop: Desktop, config: Config) -> int:
    """Sleep until cool-down ends; abandon early if user left the game."""
    setup_logging(config)
    left_since: float | None = None
    abandon_after = max(0.0, float(config.cooldown_abandon_seconds))

    while True:
        state = load(config)
        if state.mode != Mode.COOLDOWN:
            return 0
        if state.cooldown_until is None:
            return 0

        active = desktop.active_window_id()
        if state.window_id and active and active != state.window_id:
            if left_since is None:
                left_since = time.time()
            elif time.time() - left_since >= abandon_after:
                state = on_cooldown_left_game(desktop, config, state)
                persist(config, state)
                log.info(
                    "cool-down left-game; mode=%s pending_was_handled=%s",
                    state.mode.value,
                    state.mode == Mode.INTERRUPTED,
                )
                return 0
        else:
            left_since = None

        remaining = state.cooldown_until - time.time()
        if remaining <= 0:
            break
        time.sleep(min(remaining, config.poll_interval_seconds, 1.0))

    state = load(config)
    if state.mode != Mode.COOLDOWN:
        return 0
    state = on_cooldown_expiry(desktop, config, state)
    persist(config, state)
    log.info("cool-down ended; mode=%s pending_cleared=%s", state.mode, not state.pending)
    return 0
