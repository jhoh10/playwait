from __future__ import annotations

import logging
import time

from playwait.actions import Desktop
from playwait.config import Config
from playwait.service import load, on_cooldown_expiry, on_resume_focus, persist, setup_logging
from playwait.state import Mode

log = logging.getLogger("playwait")


def run_resume_watch(desktop: Desktop, config: Config) -> int:
    """Poll until armed window is focused, then resume + start cool-down."""
    setup_logging(config)
    deadline = time.time() + 24 * 3600  # safety cap
    while time.time() < deadline:
        state = load(config)
        if state.mode != Mode.INTERRUPTED or not state.window_id:
            return 0
        active = desktop.active_window_id()
        if active and active == state.window_id:
            state = on_resume_focus(desktop, config, state)
            persist(config, state)
            log.info("resumed; cool-down until %s", state.cooldown_until)
            return 0
        time.sleep(config.poll_interval_seconds)
    log.warning("resume-watch timed out")
    return 1


def run_cooldown_wait(desktop: Desktop, config: Config) -> int:
    """Sleep until cool-down ends; interrupt once if pending."""
    setup_logging(config)
    while True:
        state = load(config)
        if state.mode != Mode.COOLDOWN:
            return 0
        if state.cooldown_until is None:
            return 0
        remaining = state.cooldown_until - time.time()
        if remaining <= 0:
            break
        time.sleep(min(remaining, 1.0))

    state = load(config)
    if state.mode != Mode.COOLDOWN:
        return 0
    state = on_cooldown_expiry(desktop, config, state)
    persist(config, state)
    log.info("cool-down ended; mode=%s pending_cleared=%s", state.mode, not state.pending)
    return 0
