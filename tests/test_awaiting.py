from __future__ import annotations

from pathlib import Path

from playwait.actions import RecordingDesktop
from playwait.config import Config
from playwait.service import handle_stop, handle_submit, release
from playwait.state import Mode, State, note_awaiting, prune_stale_awaiting


def _cfg(tmp_path: Path, **kwargs) -> Config:
    base = dict(
        state_dir=tmp_path,
        cooldown_seconds=15,
        cooldown_min_seconds=15,
        cooldown_max_seconds=60,
        awaiting_ttl_seconds=900,
        interrupt_lead_seconds=0.0,
        interrupt_step_seconds=0.0,
        return_lead_seconds=0.0,
    )
    base.update(kwargs)
    return Config(**base)


def test_prune_stale_awaiting() -> None:
    state = State()
    note_awaiting(state, "old", now=1_000.0)
    note_awaiting(state, "fresh", now=2_000.0)
    dropped = prune_stale_awaiting(state, ttl_seconds=600, now=2_000.0)
    assert dropped == ["old"]
    assert state.awaiting_reply == ["fresh"]
    assert "old" not in state.awaiting_activity


def test_submit_prunes_stale_and_returns(tmp_path: Path, monkeypatch) -> None:
    desktop = RecordingDesktop(active_id="0x200")
    monkeypatch.setattr("playwait.service._spawn_self", lambda args: 1)
    monkeypatch.setattr("playwait.service.time.time", lambda: 10_000.0)
    state = State(
        mode=Mode.INTERRUPTED,
        window_id="0xgame",
        awaiting_reply=["stale", "live"],
        awaiting_activity={"stale": 1.0, "live": 10_000.0},
        paused=True,
    )
    state = handle_submit(
        desktop,
        _cfg(tmp_path, awaiting_ttl_seconds=60),
        state,
        conversation_id="live",
        prompt="ok",
    )
    assert state.awaiting_reply == []
    assert state.mode == Mode.COOLDOWN


def test_release_returns_to_game(tmp_path: Path, monkeypatch) -> None:
    desktop = RecordingDesktop(active_id="0x200")
    monkeypatch.setattr("playwait.service._spawn_self", lambda args: 3)
    state = State(
        mode=Mode.INTERRUPTED,
        window_id="0xgame",
        awaiting_reply=["a", "b"],
        awaiting_activity={"a": 1.0, "b": 2.0},
        paused=True,
    )
    state = release(desktop, _cfg(tmp_path), state)
    assert state.awaiting_reply == []
    assert state.awaiting_activity == {}
    assert state.mode == Mode.COOLDOWN
    assert desktop.activated[-1] == "0xgame"


def test_release_while_armed_clears_awaiting(tmp_path: Path) -> None:
    desktop = RecordingDesktop()
    state = State(
        mode=Mode.ARMED,
        window_id="0xgame",
        awaiting_reply=["ghost"],
        awaiting_activity={"ghost": 1.0},
    )
    state = release(desktop, _cfg(tmp_path), state)
    assert state.mode == Mode.ARMED
    assert state.awaiting_reply == []
    assert desktop.activated == []


def test_stop_refreshes_activity(tmp_path: Path, monkeypatch) -> None:
    desktop = RecordingDesktop(active_id="0xgame")
    monkeypatch.setattr("playwait.service._spawn_self", lambda args: 2)
    state = State(mode=Mode.ARMED, window_id="0xgame")
    state = handle_stop(
        desktop, _cfg(tmp_path), state, conversation_id="c1", now=5_000.0
    )
    assert state.awaiting_activity["c1"] == 5_000.0


def test_submit_auto_disarms_when_window_gone(tmp_path: Path) -> None:
    desktop = RecordingDesktop(active_id="0x200", gone_windows={"0xgame"})
    state = State(
        mode=Mode.INTERRUPTED,
        window_id="0xgame",
        awaiting_reply=["c1"],
        awaiting_activity={"c1": 1.0},
        paused=True,
    )
    state = handle_submit(
        desktop, _cfg(tmp_path), state, conversation_id="c1", prompt="ok"
    )
    assert state.mode == Mode.IDLE
    assert state.window_id is None
    assert desktop.activated == []
    assert any("closed" in body.lower() for _, body in desktop.notifications)


def test_stop_auto_disarms_when_window_gone(tmp_path: Path) -> None:
    desktop = RecordingDesktop(gone_windows={"0xgame"})
    state = State(mode=Mode.ARMED, window_id="0xgame")
    state = handle_stop(desktop, _cfg(tmp_path), state, conversation_id="c1")
    assert state.mode == Mode.IDLE
    assert state.awaiting_reply == []
    assert desktop.minimized == []
