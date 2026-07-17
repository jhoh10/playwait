from __future__ import annotations

import json
from pathlib import Path

from playwait.config import Config
from playwait.state import Mode, State, load_state, save_state


def test_arm_stores_window(tmp_path: Path) -> None:
    from playwait.actions import RecordingDesktop
    from playwait.service import arm

    desktop = RecordingDesktop(active_id="0xabc")
    cfg = Config(state_dir=tmp_path, desktop_notifications=True)
    state = arm(desktop, cfg, State())
    assert state.mode == Mode.ARMED
    assert state.window_id == "0xabc"
    assert state.pid == 4242
    assert desktop.notifications
    assert "Armed" in desktop.notifications[-1][1]


def test_second_arm_replaces(tmp_path: Path) -> None:
    from playwait.actions import RecordingDesktop
    from playwait.service import arm

    desktop = RecordingDesktop(active_id="0x1")
    cfg = Config(state_dir=tmp_path)
    state = arm(desktop, cfg, State())
    desktop.active_id = "0x2"
    desktop.pid_by_window["0x2"] = 99
    state = arm(desktop, cfg, state)
    assert state.window_id == "0x2"
    assert state.pid == 99


def test_disarm_clears_pending(tmp_path: Path) -> None:
    from playwait.actions import RecordingDesktop
    from playwait.service import disarm

    desktop = RecordingDesktop()
    cfg = Config(state_dir=tmp_path, desktop_notifications=True)
    prior = State(
        mode=Mode.COOLDOWN,
        window_id="0x1",
        pending=True,
        cooldown_until=9999999999.0,
    )
    state = disarm(desktop, cfg, prior)
    assert state.mode == Mode.IDLE
    assert state.window_id is None
    assert state.pending is False
    assert "Disarmed" in desktop.notifications[-1][1]


def test_corrupt_state_fails_soft(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    path.write_text("{not-json", encoding="utf-8")
    state = load_state(path)
    assert state.mode == Mode.IDLE


def test_missing_state_is_idle(tmp_path: Path) -> None:
    state = load_state(tmp_path / "missing.json")
    assert state.mode == Mode.IDLE


def test_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    original = State(mode=Mode.ARMED, window_id="42", pending=True)
    save_state(path, original)
    loaded = load_state(path)
    assert loaded.mode == Mode.ARMED
    assert loaded.window_id == "42"
    assert loaded.pending is True
    assert json.loads(path.read_text())["mode"] == "armed"
