from __future__ import annotations

import logging
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

log = logging.getLogger("playwait")

# Stable id so successive playwait banners replace each other instead of stacking
# in GNOME's notification queue (often stuck behind Cursor tool-approval prompts).
_NOTIFY_REPLACE_ID = "871001"
_NOTIFY_EXPIRE_MS = "4000"


class Desktop(Protocol):
    def active_window_id(self) -> str | None: ...
    def window_pid(self, window_id: str) -> int | None: ...
    def send_key(self, window_id: str, key: str, *, activate: bool = True) -> bool: ...
    def minimize(self, window_id: str) -> bool: ...
    def activate(self, window_id: str) -> bool: ...
    def find_cursor_window(self, name: str, wm_class: str) -> str | None: ...
    def focus_cursor(self, name: str, wm_class: str) -> bool: ...
    def cursor_window_ids(self, name: str, wm_class: str) -> list[str]: ...
    def notify(self, title: str, body: str) -> None: ...
    def play_sound(self, path: Path | None, *, wait: bool = False) -> None: ...


def notify_argv(title: str, body: str) -> list[str]:
    """Build notify-send argv: transient, short-lived, single replace slot."""
    return [
        "notify-send",
        "--app-name=playwait",
        "--urgency=low",
        "--expire-time=" + _NOTIFY_EXPIRE_MS,
        "--transient",
        "--replace-id=" + _NOTIFY_REPLACE_ID,
        title,
        body,
    ]


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

    def send_key(self, window_id: str, key: str, *, activate: bool = True) -> bool:
        if self.fail_keys:
            return False
        if activate:
            self.activated.append(window_id)
            self.active_id = window_id
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

    def cursor_window_ids(self, name: str, wm_class: str) -> list[str]:
        return [self.cursor_id] if self.cursor_id else []

    def focus_cursor(self, name: str, wm_class: str) -> bool:
        if not self.cursor_id:
            return False
        return self.activate(self.cursor_id)

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

    def send_key(self, window_id: str, key: str, *, activate: bool = True) -> bool:
        if not shutil.which("xdotool"):
            log.warning("xdotool not found; cannot send key")
            return False
        # Some games need focus first; permission/soft paths may skip to avoid
        # stealing the Cursor window when the user is already working there.
        if activate:
            # Avoid --sync: it can hang for seconds on unresponsive game windows.
            _run(["xdotool", "windowactivate", window_id], timeout=1.5)
        proc = _run(["xdotool", "key", "--window", window_id, key], timeout=2.0)
        ok = bool(proc and proc.returncode == 0)
        if not ok:
            log.warning("send_key failed for %s key=%s", window_id, key)
        return ok

    def minimize(self, window_id: str) -> bool:
        if shutil.which("xdotool"):
            # No --sync: Proton/fullscreen games often never acknowledge sync.
            proc = _run(["xdotool", "windowminimize", window_id], timeout=2.0)
            if proc and proc.returncode == 0:
                return True
        if shutil.which("wmctrl"):
            hex_id = _to_hex_window_id(window_id)
            proc = _run(["wmctrl", "-i", "-r", hex_id, "-b", "add,hidden"], timeout=2.0)
            if proc and proc.returncode == 0:
                return True
            proc = _run(["wmctrl", "-i", "-r", hex_id, "-b", "add,shaded"], timeout=2.0)
            if proc and proc.returncode == 0:
                return True
        log.warning("minimize failed for %s", window_id)
        return False

    def activate(self, window_id: str) -> bool:
        """Raise a window. Prefer wmctrl — more reliable vs Proton/fullscreen games."""
        hex_id = _to_hex_window_id(window_id)
        target = _normalize_wmctrl_id(window_id)

        if shutil.which("wmctrl"):
            proc = _run(["wmctrl", "-i", "-a", hex_id], timeout=1.5)
            if proc and proc.returncode == 0 and _window_ids_equal(
                self.active_window_id(), target
            ):
                return True
            # wmctrl sometimes succeeds asynchronously; accept rc=0 as soft success
            # only after also trying xdotool below if focus did not move.

        if shutil.which("xdotool"):
            # Never use --sync: stale ids hang and block the yank sequence.
            _run(["xdotool", "windowactivate", window_id], timeout=1.5)
            _run(["xdotool", "windowfocus", "--sync", window_id], timeout=1.5)
            if _window_ids_equal(self.active_window_id(), target):
                return True

        if shutil.which("wmctrl"):
            proc = _run(["wmctrl", "-i", "-a", hex_id], timeout=1.5)
            if proc and proc.returncode == 0:
                # Brief settle; fullscreen games may lag.
                import time as _time

                _time.sleep(0.15)
                if _window_ids_equal(self.active_window_id(), target):
                    return True
                # Last resort: claim success if wmctrl accepted the request.
                log.info("activate: wmctrl accepted %s (active=%s)", target, self.active_window_id())
                return True

        log.warning("activate failed for %s", window_id)
        return False

    def cursor_window_ids(self, name: str, wm_class: str) -> list[str]:
        """Candidate Cursor windows, best-first (real app class, then visible)."""
        ordered: list[str] = []

        def add(ids: list[str]) -> None:
            for wid in ids:
                n = _normalize_wmctrl_id(wid) if wid else ""
                if n and n not in ordered:
                    ordered.append(n)

        # 1) wmctrl class cursor.Cursor — the real IDE window ("Cursor Agents").
        if shutil.which("wmctrl"):
            proc = _run(["wmctrl", "-lx"], timeout=2.0)
            if proc and proc.returncode == 0:
                class_hits: list[str] = []
                name_hits: list[str] = []
                for line in proc.stdout.splitlines():
                    lower = line.lower()
                    parts = line.split(None, 4)
                    if not parts:
                        continue
                    wid = parts[0]
                    if len(parts) >= 3 and "cursor.cursor" in parts[2].lower():
                        class_hits.append(wid)
                    elif name.lower() in lower or (wm_class and wm_class.lower() in lower):
                        name_hits.append(wid)
                add(class_hits)
                add(name_hits)

        # 2) Visible xdotool matches.
        if shutil.which("xdotool"):
            for needle in (name, wm_class):
                if not needle:
                    continue
                for kind in ("--name", "--class"):
                    proc = _run(
                        ["xdotool", "search", "--onlyvisible", kind, needle],
                        timeout=2.0,
                    )
                    if proc and proc.returncode == 0:
                        add(
                            [
                                line.strip()
                                for line in proc.stdout.splitlines()
                                if line.strip()
                            ]
                        )

        # 3) Any xdotool match (may include stale helper windows — last resort).
        if shutil.which("xdotool"):
            for needle in (name, wm_class):
                if not needle:
                    continue
                for kind in ("--name", "--class"):
                    proc = _run(["xdotool", "search", kind, needle], timeout=2.0)
                    if proc and proc.returncode == 0:
                        add(
                            [
                                line.strip()
                                for line in proc.stdout.splitlines()
                                if line.strip()
                            ]
                        )
        return ordered

    def find_cursor_window(self, name: str, wm_class: str) -> str | None:
        ids = self.cursor_window_ids(name, wm_class)
        if not ids:
            log.warning("could not find Cursor window (name=%s class=%s)", name, wm_class)
            return None
        return ids[0]

    def focus_cursor(self, name: str, wm_class: str) -> bool:
        ids = self.cursor_window_ids(name, wm_class)
        if not ids:
            log.warning("could not find Cursor window (name=%s class=%s)", name, wm_class)
            return False
        for wid in ids:
            log.info("focus_cursor: trying %s", wid)
            if self.activate(wid):
                log.info("focus_cursor: activated %s", wid)
                return True
        log.warning("focus_cursor: all candidates failed (%s)", ids)
        return False

    def notify(self, title: str, body: str) -> None:
        if not shutil.which("notify-send"):
            return
        _run(notify_argv(title, body))

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


def _normalize_wmctrl_id(window_id: str) -> str:
    """wmctrl prints hex (0x…); xdotool uses decimal — normalize to decimal string."""
    wid = window_id.strip()
    if wid.lower().startswith("0x"):
        try:
            return str(int(wid, 16))
        except ValueError:
            return wid
    return wid


def _window_ids_equal(a: str | None, b: str | None) -> bool:
    if not a or not b:
        return False
    try:
        return int(str(a), 0) == int(str(b), 0)
    except ValueError:
        return str(a) == str(b)


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
