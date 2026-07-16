from __future__ import annotations

import logging
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

log = logging.getLogger("playwait")


class Desktop(Protocol):
    def active_window_id(self) -> str | None: ...
    def window_pid(self, window_id: str) -> int | None: ...
    def send_key(self, window_id: str, key: str) -> bool: ...
    def minimize(self, window_id: str) -> bool: ...
    def activate(self, window_id: str) -> bool: ...
    def find_cursor_window(self, name: str, wm_class: str) -> str | None: ...
    def notify(self, title: str, body: str) -> None: ...
    def play_sound(self, path: Path | None, *, wait: bool = False) -> None: ...


@dataclass
class RecordingDesktop:
    """In-memory desktop for tests."""

    active_id: str | None = "0x100"
    pid_by_window: dict[str, int] = field(default_factory=lambda: {"0x100": 4242})
    cursor_id: str | None = "0x200"
    keys_sent: list[tuple[str, str]] = field(default_factory=list)
    minimized: list[str] = field(default_factory=list)
    activated: list[str] = field(default_factory=list)
    notifications: list[tuple[str, str]] = field(default_factory=list)
    sounds: list[str] = field(default_factory=list)
    fail_keys: bool = False
    fail_minimize: bool = False
    fail_activate: bool = False

    def active_window_id(self) -> str | None:
        return self.active_id

    def window_pid(self, window_id: str) -> int | None:
        if window_id in self.pid_by_window:
            return self.pid_by_window[window_id]
        return 4242 if window_id else None

    def send_key(self, window_id: str, key: str) -> bool:
        if self.fail_keys:
            return False
        self.keys_sent.append((window_id, key))
        return True

    def minimize(self, window_id: str) -> bool:
        if self.fail_minimize:
            return False
        self.minimized.append(window_id)
        return True

    def activate(self, window_id: str) -> bool:
        if self.fail_activate:
            return False
        self.activated.append(window_id)
        self.active_id = window_id
        return True

    def find_cursor_window(self, name: str, wm_class: str) -> str | None:
        return self.cursor_id

    def notify(self, title: str, body: str) -> None:
        self.notifications.append((title, body))

    def play_sound(self, path: Path | None, *, wait: bool = False) -> None:
        self.sounds.append(str(path) if path else "")


def _run(argv: list[str], timeout: float = 5.0) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            argv,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        log.warning("command failed %s: %s", argv, exc)
        return None


@dataclass
class X11Desktop:
    """X11 desktop actions via xdotool / wmctrl / notify-send / pw-play."""

    def active_window_id(self) -> str | None:
        if not shutil.which("xdotool"):
            log.warning("xdotool not found")
            return None
        proc = _run(["xdotool", "getactivewindow"])
        if not proc or proc.returncode != 0:
            return None
        wid = proc.stdout.strip()
        return wid or None

    def window_pid(self, window_id: str) -> int | None:
        if not shutil.which("xdotool"):
            return None
        proc = _run(["xdotool", "getwindowpid", window_id])
        if not proc or proc.returncode != 0:
            return None
        try:
            return int(proc.stdout.strip())
        except ValueError:
            return None

    def send_key(self, window_id: str, key: str) -> bool:
        if not shutil.which("xdotool"):
            log.warning("xdotool not found; cannot send key")
            return False
        # Focus then key — some games need the window active first.
        _run(["xdotool", "windowactivate", "--sync", window_id])
        proc = _run(["xdotool", "key", "--window", window_id, key])
        ok = bool(proc and proc.returncode == 0)
        if not ok:
            log.warning("send_key failed for %s key=%s", window_id, key)
        return ok

    def minimize(self, window_id: str) -> bool:
        if shutil.which("xdotool"):
            proc = _run(["xdotool", "windowminimize", "--sync", window_id])
            if proc and proc.returncode == 0:
                return True
        if shutil.which("wmctrl"):
            # wmctrl wants hex id with 0x prefix sometimes; xdotool ids are decimal.
            hex_id = _to_hex_window_id(window_id)
            proc = _run(["wmctrl", "-i", "-r", hex_id, "-b", "add,hidden"])
            if proc and proc.returncode == 0:
                return True
        log.warning("minimize failed for %s", window_id)
        return False

    def activate(self, window_id: str) -> bool:
        if shutil.which("xdotool"):
            proc = _run(["xdotool", "windowactivate", "--sync", window_id])
            if proc and proc.returncode == 0:
                return True
        if shutil.which("wmctrl"):
            hex_id = _to_hex_window_id(window_id)
            proc = _run(["wmctrl", "-i", "-a", hex_id])
            if proc and proc.returncode == 0:
                return True
        log.warning("activate failed for %s", window_id)
        return False

    def find_cursor_window(self, name: str, wm_class: str) -> str | None:
        if shutil.which("xdotool"):
            for needle in (name, wm_class):
                if not needle:
                    continue
                proc = _run(["xdotool", "search", "--name", needle])
                if proc and proc.returncode == 0:
                    ids = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
                    if ids:
                        return ids[-1]
                proc = _run(["xdotool", "search", "--class", needle])
                if proc and proc.returncode == 0:
                    ids = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
                    if ids:
                        return ids[-1]
        if shutil.which("wmctrl"):
            proc = _run(["wmctrl", "-lx"])
            if proc and proc.returncode == 0:
                matches: list[str] = []
                for line in proc.stdout.splitlines():
                    lower = line.lower()
                    if name.lower() in lower or wm_class.lower() in lower:
                        parts = line.split(None, 1)
                        if parts:
                            matches.append(parts[0])
                if matches:
                    return matches[-1]
        log.warning("could not find Cursor window (name=%s class=%s)", name, wm_class)
        return None

    def notify(self, title: str, body: str) -> None:
        if not shutil.which("notify-send"):
            return
        _run(["notify-send", "--app-name=playwait", title, body])

    def play_sound(self, path: Path | None, *, wait: bool = False) -> None:
        if path is None or not path.is_file():
            return
        for player in ("pw-play", "paplay", "aplay"):
            if not shutil.which(player):
                continue
            try:
                if wait:
                    proc = _run([player, str(path)], timeout=10.0)
                    if proc and proc.returncode == 0:
                        return
                else:
                    # Fire-and-forget so window staging can overlap the chime.
                    subprocess.Popen(  # noqa: S603
                        [player, str(path)],
                        stdin=subprocess.DEVNULL,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        start_new_session=True,
                    )
                    return
            except OSError as exc:
                log.warning("sound player %s failed: %s", player, exc)
        log.warning("could not play sound %s", path)


def _to_hex_window_id(window_id: str) -> str:
    if window_id.startswith("0x") or window_id.startswith("0X"):
        return window_id
    try:
        return hex(int(window_id))
    except ValueError:
        return window_id


def pause_key_argv(window_id: str, key: str) -> list[str]:
    """Documented argv shape for tests / debugging."""
    return ["xdotool", "key", "--window", window_id, key]
