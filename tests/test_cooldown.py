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
    return Config(
        state_dir=tmp_path,
        cooldown_seconds=15,
        cooldown_min_seconds=15,
        cooldown_max_seconds=60,
        awaiting_ttl_seconds=900,
        interrupt_lead_seconds=0.0,
        interrupt_step_seconds=0.0,
        return_lead_seconds=0.0,
    )


def test_stop_while_in_cursor_does_not_raise_game(tmp_path: Path, monkeypatch) -> None:
    """Manual Cursor focus during armed/cool-down must not flash the game."""
    desktop = RecordingDesktop(active_id="0x200")  # already in Cursor
    monkeypatch.setattr("playwait.service._spawn_self", lambda args: 7)
    state = State(mode=Mode.ARMED, window_id="0xgame")
    state = handle_stop(
        desktop, _cfg(tmp_path), state, conversation_id="chat-z"
    )
    assert state.mode == Mode.INTERRUPTED
    assert state.awaiting_reply == ["chat-z"]
    # Soft path: Esc without activating the game, then Cursor stays put.
    assert "0xgame" not in desktop.activated
    assert desktop.keys_sent == [("0xgame", "Escape")]
    assert desktop.minimized == ["0xgame"]


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
    assert desktop.activated[0] == "0xgame"  # pause focuses game first
    assert desktop.activated[-1] == "0x200"
    assert state.resume_watch_pid == 555
    assert any("Agent ready" in b for _, b in desktop.notifications)


def test_stop_while_interrupted_clears_skip_cooldown(tmp_path: Path) -> None:
    desktop = RecordingDesktop()
    state = State(
        mode=Mode.INTERRUPTED,
        window_id="0xgame",
        awaiting_reply=["chat-a"],
        skip_cooldown=True,
        permission_gate_active=True,
    )
    state = handle_stop(
        desktop, _cfg(tmp_path), state, conversation_id="chat-b"
    )
    assert state.mode == Mode.INTERRUPTED
    assert state.awaiting_reply == ["chat-a", "chat-b"]
    assert state.skip_cooldown is False
    assert desktop.minimized == []


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
        peak_effort=0.0,
    )
    killed: list[int] = []
    monkeypatch.setattr("playwait.service._kill_pid", lambda pid: killed.append(pid))
    state = handle_submit(
        desktop,
        _cfg(tmp_path),
        state,
        conversation_id="chat-b",
        prompt="yes",
    )
    assert state.awaiting_reply == []
    assert state.mode == Mode.COOLDOWN
    assert state.paused is False
    assert state.cooldown_until == 10_000.0 + 15  # low-effort → min cool-down
    assert desktop.activated[0] == "0xgame"
    assert ("0xgame", "Escape") in desktop.keys_sent
    assert 111 in killed
    assert any("cool-down" in b for _, b in desktop.notifications)


def test_submit_high_effort_longer_cooldown(tmp_path: Path, monkeypatch) -> None:
    desktop = RecordingDesktop()
    monkeypatch.setattr("playwait.service._spawn_self", lambda args: 1)
    monkeypatch.setattr("playwait.service.time.time", lambda: 50_000.0)
    thoughtful = (
        "Please redesign the cool-down so it scales with effort because a fixed "
        "timer feels wrong. Consider heuristics on length and code fences instead "
        "of an LLM call — implement that mapping carefully.\n\n"
        "```\nprint('example')\n```\n"
    )
    state = State(
        mode=Mode.INTERRUPTED,
        window_id="0xgame",
        awaiting_reply=["c1"],
        paused=True,
    )
    state = handle_submit(
        desktop,
        _cfg(tmp_path),
        state,
        conversation_id="c1",
        prompt=thoughtful,
    )
    assert state.mode == Mode.COOLDOWN
    assert state.cooldown_until is not None
    duration = state.cooldown_until - 50_000.0
    assert duration >= 40


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
    desktop = RecordingDesktop(active_id="0xgame")
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
    # Full interrupt activates game for Esc, then Cursor.
    assert "0xgame" in desktop.activated
    assert "0x200" in desktop.activated


def test_cooldown_expiry_pending_already_in_cursor_soft(tmp_path: Path, monkeypatch) -> None:
    desktop = RecordingDesktop(active_id="0x200")  # Cursor focused
    monkeypatch.setattr("playwait.service._spawn_self", lambda args: 42)
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
    # Soft path must not raise the game (no activate of 0xgame).
    assert "0xgame" not in desktop.activated
    assert desktop.keys_sent == [("0xgame", "Escape")]


def test_cooldown_left_game_without_pending_arms(tmp_path: Path) -> None:
    from playwait.service import on_cooldown_left_game

    desktop = RecordingDesktop(active_id="0x200")
    state = State(
        mode=Mode.COOLDOWN,
        window_id="0xgame",
        pending=False,
        cooldown_until=9_999_999.0,
    )
    state = on_cooldown_left_game(desktop, _cfg(tmp_path), state)
    assert state.mode == Mode.ARMED
    assert state.pending is False
    assert desktop.minimized == []


def test_permission_mcp_interrupts_and_skips_cooldown(tmp_path: Path, monkeypatch) -> None:
    from playwait.service import handle_permission, on_resume_focus

    desktop = RecordingDesktop(active_id="0xgame")
    monkeypatch.setattr("playwait.service._spawn_self", lambda args: 9)
    state = State(mode=Mode.ARMED, window_id="0xgame")
    state, out = handle_permission(
        desktop, _cfg(tmp_path), state, source="mcp", tool_name="browser_navigate"
    )
    assert out == {"permission": "ask"}
    assert state.mode == Mode.INTERRUPTED
    assert state.skip_cooldown is True
    assert state.awaiting_reply == []
    assert state.permission_gate_active is True

    state = on_resume_focus(desktop, _cfg(tmp_path), state)
    assert state.mode == Mode.ARMED
    assert state.skip_cooldown is False
    assert state.cooldown_until is None


def test_permission_done_stays_in_cursor(tmp_path: Path, monkeypatch) -> None:
    """After Allow, stay interrupted — do not bounce back to the game mid-agent."""
    from playwait.service import handle_permission, handle_permission_done

    desktop = RecordingDesktop(active_id="0xgame")
    monkeypatch.setattr("playwait.service._spawn_self", lambda args: 9)
    state = State(mode=Mode.ARMED, window_id="0xgame")
    state, _ = handle_permission(
        desktop, _cfg(tmp_path), state, source="mcp", tool_name="browser_navigate"
    )
    assert state.permission_gate_active is True
    # Simulate user still in Cursor after Allow; tool finished.
    desktop.active_id = "0x200"
    activated_before = list(desktop.activated)
    state = handle_permission_done(desktop, _cfg(tmp_path), state)
    assert state.mode == Mode.INTERRUPTED
    assert state.permission_gate_active is False
    assert state.skip_cooldown is True
    assert desktop.activated == activated_before


def test_permission_done_stays_if_awaiting_reply(tmp_path: Path, monkeypatch) -> None:
    from playwait.service import handle_permission_done

    desktop = RecordingDesktop(active_id="0x200")
    state = State(
        mode=Mode.INTERRUPTED,
        window_id="0xgame",
        awaiting_reply=["chat-a"],
        permission_gate_active=True,
        skip_cooldown=True,
    )
    state = handle_permission_done(desktop, _cfg(tmp_path), state)
    assert state.mode == Mode.INTERRUPTED
    assert state.awaiting_reply == ["chat-a"]
    assert state.permission_gate_active is False
    assert desktop.activated == []


def test_permission_shell_patterns_pass_harmless(tmp_path: Path) -> None:
    from playwait.service import handle_permission

    desktop = RecordingDesktop(active_id="0xgame")
    state = State(mode=Mode.ARMED, window_id="0xgame")
    state, out = handle_permission(
        desktop, _cfg(tmp_path), state, source="shell", command="ls -la"
    )
    assert out == {}
    assert state.mode == Mode.ARMED
    assert desktop.minimized == []


def test_permission_shell_patterns_catch_sudo(tmp_path: Path, monkeypatch) -> None:
    from playwait.service import handle_permission

    desktop = RecordingDesktop(active_id="0xgame")
    monkeypatch.setattr("playwait.service._spawn_self", lambda args: 3)
    state = State(mode=Mode.ARMED, window_id="0xgame")
    state, out = handle_permission(
        desktop, _cfg(tmp_path), state, source="shell", command="sudo apt update"
    )
    assert out == {"permission": "ask"}
    assert state.mode == Mode.INTERRUPTED
    assert state.skip_cooldown is True


def test_permission_bypasses_cooldown(tmp_path: Path, monkeypatch) -> None:
    from playwait.service import handle_permission

    desktop = RecordingDesktop(active_id="0xgame")
    monkeypatch.setattr("playwait.service._spawn_self", lambda args: 11)
    killed: list[int] = []
    monkeypatch.setattr("playwait.service._kill_pid", lambda pid: killed.append(pid))
    state = State(
        mode=Mode.COOLDOWN,
        window_id="0xgame",
        cooldown_until=9_999_999.0,
        cooldown_wait_pid=55,
    )
    state, out = handle_permission(
        desktop, _cfg(tmp_path), state, source="mcp", tool_name="search"
    )
    assert out == {"permission": "ask"}
    assert state.mode == Mode.INTERRUPTED
    assert 55 in killed
    assert state.skip_cooldown is True


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
    assert state.cooldown_until == 5_000.0 + 15
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
