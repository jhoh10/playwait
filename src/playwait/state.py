from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any


class Mode(StrEnum):
    IDLE = "idle"
    ARMED = "armed"
    INTERRUPTED = "interrupted"
    COOLDOWN = "cooldown"


@dataclass
class State:
    mode: Mode = Mode.IDLE
    window_id: str | None = None
    pid: int | None = None
    pending: bool = False
    cooldown_until: float | None = None
    resume_watch_pid: int | None = None
    cooldown_wait_pid: int | None = None
    paused: bool = False
    # Conversation IDs from Cursor stop hooks that still need a user reply.
    awaiting_reply: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["mode"] = self.mode.value
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> State:
        mode_raw = data.get("mode", "idle")
        try:
            mode = Mode(mode_raw)
        except ValueError:
            mode = Mode.IDLE
        awaiting = data.get("awaiting_reply", [])
        if not isinstance(awaiting, list):
            awaiting = []
        awaiting_ids = [str(x) for x in awaiting if x is not None and str(x)]
        return cls(
            mode=mode,
            window_id=_as_optional_str(data.get("window_id")),
            pid=_as_optional_int(data.get("pid")),
            pending=bool(data.get("pending", False)),
            cooldown_until=_as_optional_float(data.get("cooldown_until")),
            resume_watch_pid=_as_optional_int(data.get("resume_watch_pid")),
            cooldown_wait_pid=_as_optional_int(data.get("cooldown_wait_pid")),
            paused=bool(data.get("paused", False)),
            awaiting_reply=_unique_preserve(awaiting_ids),
        )

    def is_armed_target(self) -> bool:
        return self.mode != Mode.IDLE and self.window_id is not None

    def cooldown_active(self, now: float | None = None) -> bool:
        if self.mode != Mode.COOLDOWN or self.cooldown_until is None:
            return False
        return (now if now is not None else time.time()) < self.cooldown_until

    def cooldown_overdue(self, now: float | None = None) -> bool:
        if self.mode != Mode.COOLDOWN or self.cooldown_until is None:
            return False
        return (now if now is not None else time.time()) >= self.cooldown_until


def _as_optional_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _as_optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _unique_preserve(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def note_awaiting(state: State, conversation_id: str | None) -> None:
    if not conversation_id:
        return
    if conversation_id not in state.awaiting_reply:
        state.awaiting_reply.append(conversation_id)


def clear_awaiting(state: State, conversation_id: str | None) -> bool:
    """Remove a conversation from awaiting_reply. Returns True if it was present."""
    if not conversation_id:
        return False
    if conversation_id not in state.awaiting_reply:
        return False
    state.awaiting_reply = [c for c in state.awaiting_reply if c != conversation_id]
    return True


def default_state() -> State:
    return State()


def load_state(path: Path) -> State:
    if not path.is_file():
        return default_state()
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
        if not isinstance(data, dict):
            return default_state()
        return State.from_dict(data)
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return default_state()


def save_state(path: Path, state: State) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state.to_dict(), indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)
