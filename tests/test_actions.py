from __future__ import annotations

from playwait.actions import notify_argv, pause_key_argv
from playwait.actions import RecordingDesktop
from playwait.config import Config
from pathlib import Path


def test_pause_key_argv() -> None:
    assert pause_key_argv("12345", "Escape") == [
        "xdotool",
        "key",
        "--window",
        "12345",
        "Escape",
    ]


def test_notify_argv_is_transient_and_replacing() -> None:
    argv = notify_argv("playwait", "hello")
    assert argv[0] == "notify-send"
    assert "--transient" in argv
    assert "--urgency=low" in argv
    assert "--hint=int:transient:1" in argv
    assert any(a.startswith("--replace-id=") for a in argv)
    assert any(a.startswith("--expire-time=") for a in argv)
    assert argv[-2:] == ["playwait", "hello"]
    assert "-p" not in argv
    assert "-p" in notify_argv("playwait", "hello", print_id=True)


def test_close_notification_argv() -> None:
    from playwait.actions import close_notification_argv

    argv = close_notification_argv(42)
    assert argv[0] == "gdbus"
    assert any("CloseNotification" in a for a in argv)
    assert "uint32:42" in argv


def test_recording_desktop_minimize_activate() -> None:
    d = RecordingDesktop()
    assert d.minimize("0x1")
    assert d.minimized == ["0x1"]
    assert d.activate("0x2")
    assert d.activated == ["0x2"]
    assert d.active_id == "0x2"


def test_sound_and_notify_failures_do_not_raise(tmp_path: Path) -> None:
    d = RecordingDesktop()
    d.notify("t", "b")
    d.play_sound(None)
    d.play_sound(tmp_path / "missing.wav")
    assert d.notifications == [("t", "b")]
    assert d.sounds == ["", str(tmp_path / "missing.wav")]


def test_send_key_records() -> None:
    d = RecordingDesktop()
    assert d.send_key("0x1", "Escape")
    assert d.keys_sent == [("0x1", "Escape")]
    d.fail_keys = True
    assert d.send_key("0x1", "Escape") is False
