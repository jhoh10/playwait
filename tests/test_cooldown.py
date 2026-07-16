from __future__ import annotations

from pathlib import Path

from playwait.actions import RecordingDesktop
from playwait.config import Config
from playwait.service import (
    do_interrupt,
    handle_stop,
    handle_submit,
    on_cooldown_expiry,
    on_resume_focus,
)
from playwait.state import Mode, State


def _cfg(tmp_path: Path) -> Config:
    return Config(state_dir=tmp_path, cooldown_seconds=120)


def test_on_stop_disarmed_noop(tmp_path: Path) -> None:
    desktop = RecordingDesktop()
    state = handle_stop(desktop, _cfg(tmp_path), State())
    assert state.mode == Mode.IDLE
    assert desktop.minimized == []
    assert desktop.keys_sent == []


def test_on_stop_interrupts_when_armed(tmp_path: Path, monkeypatch) -> None:
    desktop = RecordingDesktop(active_id="0xgame")
    monkeypatch.setattr("playwait.service._spawn_self", lambda args: 555)
    armed = State(mode=Mode.ARMED, window_id="0xgame")
    state = handle_stop(
        desktop, _cfg(tmp_path), armed, conversation_id="chat-a"
    )
    assert state.mode == Mode.INTERRUPTED
    assert state.paused is True
    assert state.awaiting_reply == ["chat-a"]
    assert desktop.keys_sent == [("0xgame", "Escape")]
    assert desktop.minimized == ["0xgame"]
    assert desktop.activated == ["0x200"]
    assert state.resume_watch_pid == 555
    assert any("Agent ready" in b for _, b in desktop.notifications)


def test_second_stop_tracks_chat_without_re_yank(tmp_path: Path, monkeypatch) -> None:
    desktop = RecordingDesktop()
    monkeypatch.setattr("playwait.service._spawn_self", lambda args: 1)
    state = State(
        mode=Mode.INTERRUPTED,
        window_id="0xgame",
        awaiting_reply=["chat-a"],
        paused=True,
    )
    state = handle_stop(
        desktop, _cfg(tmp_path), state, conversation_id="chat-b"
    )
    assert state.mode == Mode.INTERRUPTED
    assert state.awaiting_reply == ["chat-a", "chat-b"]
    assert desktop.minimized == []


def test_submit_one_of_two_stays_in_cursor(tmp_path: Path) -> None:
    desktop = RecordingDesktop()
    state = State(
        mode=Mode.INTERRUPTED,
        window_id="0xgame",
        awaiting_reply=["chat-a", "chat-b"],
        paused=True,
    )
    state = handle_submit(
        desktop, _cfg(tmp_path), state, conversation_id="chat-a"
    )
    assert state.mode == Mode.INTERRUPTED
    assert state.awaiting_reply == ["chat-b"]
    assert desktop.activated == []
    assert any("still need a reply" in b for _, b in desktop.notifications)


def test_submit_last_chat_returns_to_game(tmp_path: Path, monkeypatch) -> None:
    desktop = RecordingDesktop()
    monkeypatch.setattr("playwait.service._spawn_self", lambda args: 999)
    monkeypatch.setattr("playwait.service.time.time", lambda: 10_000.0)
    state = State(
        mode=Mode.INTERRUPTED,
        window_id="0xgame",
        awaiting_reply=["chat-b"],
        paused=True,
        resume_watch_pid=111,
    )
    killed: list[int] = []
    monkeypatch.setattr("playwait.service._kill_pid", lambda pid: killed.append(pid))
    state = handle_submit(
        desktop, _cfg(tmp_path), state, conversation_id="chat-b"
    )
    assert state.awaiting_reply == []
    assert state.mode == Mode.COOLDOWN
    assert state.paused is False
    assert state.cooldown_until == 10_000.0 + 120
    assert desktop.activated == ["0xgame"]
    assert ("0xgame", "Escape") in desktop.keys_sent
    assert 111 in killed
    assert any("Back to game" in b for _, b in desktop.notifications)


def test_stop_during_cooldown_sets_pending(tmp_path: Path) -> None:
    desktop = RecordingDesktop()
    now = 1_000_000.0
    state = State(
        mode=Mode.COOLDOWN,
        window_id="0xgame",
        cooldown_until=now + 60,
        pending=False,
    )
    state = handle_stop(
        desktop, _cfg(tmp_path), state, conversation_id="chat-c", now=now
    )
    assert state.pending is True
    assert state.mode == Mode.COOLDOWN
    assert state.awaiting_reply == ["chat-c"]
    assert desktop.minimized == []


def test_double_stop_during_cooldown_one_pending(tmp_path: Path) -> None:
    desktop = RecordingDesktop()
    now = 1_000_000.0
    state = State(
        mode=Mode.COOLDOWN,
        window_id="0xgame",
        cooldown_until=now + 60,
    )
    state = handle_stop(desktop, _cfg(tmp_path), state, now=now)
    state = handle_stop(desktop, _cfg(tmp_path), state, now=now)
    assert state.pending is True
    assert desktop.minimized == []


def test_cooldown_expiry_with_pending_interrupts(tmp_path: Path, monkeypatch) -> None:
    desktop = RecordingDesktop()
    monkeypatch.setattr("playwait.service._spawn_self", lambda args: 777)
    state = State(
        mode=Mode.COOLDOWN,
        window_id="0xgame",
        pending=True,
        cooldown_until=1.0,
    )
    state = on_cooldown_expiry(desktop, _cfg(tmp_path), state)
    assert state.mode == Mode.INTERRUPTED
    assert state.pending is False
    assert desktop.minimized == ["0xgame"]


def test_disarm_clears_pending_no_interrupt_on_expiry(tmp_path: Path) -> None:
    desktop = RecordingDesktop()
    # Simulate disarm before expiry: idle state.
    state = State()
    state = on_cooldown_expiry(desktop, _cfg(tmp_path), state)
    assert state.mode == Mode.IDLE
    assert desktop.minimized == []


def test_resume_starts_cooldown(tmp_path: Path, monkeypatch) -> None:
    desktop = RecordingDesktop()
    monkeypatch.setattr("playwait.service._spawn_self", lambda args: 888)
    monkeypatch.setattr("playwait.service.time.time", lambda: 5_000.0)
    state = State(
        mode=Mode.INTERRUPTED,
        window_id="0xgame",
        paused=True,
    )
    state = on_resume_focus(desktop, _cfg(tmp_path), state)
    assert state.mode == Mode.COOLDOWN
    assert state.paused is False
    assert state.cooldown_until == 5_000.0 + 120
    assert state.cooldown_wait_pid == 888
    assert desktop.keys_sent == [("0xgame", "Escape")]


def test_do_interrupt_continues_if_key_fails(tmp_path: Path, monkeypatch) -> None:
    desktop = RecordingDesktop(fail_keys=True)
    monkeypatch.setattr("playwait.service._spawn_self", lambda args: 1)
    state = State(mode=Mode.ARMED, window_id="0xgame")
    state = do_interrupt(desktop, _cfg(tmp_path), state)
    assert state.mode == Mode.INTERRUPTED
    assert state.paused is False
    assert desktop.minimized == ["0xgame"]
