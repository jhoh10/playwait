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
    # Last activity (unix time) per awaiting conversation_id.
    awaiting_activity: dict[str, float] = field(default_factory=dict)
    # Peak reply-effort score (0..1) across submits during this interrupt.
    peak_effort: float = 0.0
    # When True, resume from interrupt goes straight to armed (no cool-down).
    # Used for tool-permission interrupts so the next approval can yank immediately.
    skip_cooldown: bool = False
    # Set when a permission-gate interrupt is active; after-tool hooks may auto-return.
    permission_gate_active: bool = False

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
        awaiting_ids = _unique_preserve(awaiting_ids)

        activity_raw = data.get("awaiting_activity", {})
        activity: dict[str, float] = {}
        if isinstance(activity_raw, dict):
            for key, val in activity_raw.items():
                try:
                    activity[str(key)] = float(val)
                except (TypeError, ValueError):
                    continue
        # Backfill missing timestamps so old state files still prune eventually.
        now = time.time()
        for cid in awaiting_ids:
            if cid not in activity:
                activity[cid] = now
        activity = {k: v for k, v in activity.items() if k in set(awaiting_ids)}

        peak = data.get("peak_effort", 0.0)
        try:
            peak_f = float(peak)
        except (TypeError, ValueError):
            peak_f = 0.0
        peak_f = max(0.0, min(1.0, peak_f))
        return cls(
            mode=mode,
            window_id=_as_optional_str(data.get("window_id")),
            pid=_as_optional_int(data.get("pid")),
            pending=bool(data.get("pending", False)),
            cooldown_until=_as_optional_float(data.get("cooldown_until")),
            resume_watch_pid=_as_optional_int(data.get("resume_watch_pid")),
            cooldown_wait_pid=_as_optional_int(data.get("cooldown_wait_pid")),
            paused=bool(data.get("paused", False)),
            awaiting_reply=awaiting_ids,
            awaiting_activity=activity,
            peak_effort=peak_f,
            skip_cooldown=bool(data.get("skip_cooldown", False)),
            permission_gate_active=bool(data.get("permission_gate_active", False)),
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


def note_awaiting(
    state: State,
    conversation_id: str | None,
    *,
    now: float | None = None,
) -> None:
    if not conversation_id:
        return
    ts = time.time() if now is None else now
    if conversation_id not in state.awaiting_reply:
        state.awaiting_reply.append(conversation_id)
    state.awaiting_activity[conversation_id] = ts


def clear_awaiting(state: State, conversation_id: str | None) -> bool:
    """Remove a conversation from awaiting_reply. Returns True if it was present."""
    if not conversation_id:
        return False
    if conversation_id not in state.awaiting_reply:
        return False
    state.awaiting_reply = [c for c in state.awaiting_reply if c != conversation_id]
    state.awaiting_activity.pop(conversation_id, None)
    return True


def clear_all_awaiting(state: State) -> list[str]:
    """Clear every awaiting conversation. Returns the ids that were cleared."""
    cleared = list(state.awaiting_reply)
    state.awaiting_reply = []
    state.awaiting_activity = {}
    return cleared


def prune_stale_awaiting(
    state: State,
    *,
    ttl_seconds: int,
    now: float | None = None,
) -> list[str]:
    """Drop awaiting chats with no activity within ttl_seconds. Returns dropped ids."""
    if ttl_seconds <= 0:
        return []
    ts = time.time() if now is None else now
    keep: list[str] = []
    dropped: list[str] = []
    for cid in state.awaiting_reply:
        last = state.awaiting_activity.get(cid, ts)
        if ts - last >= ttl_seconds:
            dropped.append(cid)
        else:
            keep.append(cid)
    if not dropped:
        return []
    state.awaiting_reply = keep
    state.awaiting_activity = {
        cid: state.awaiting_activity[cid]
        for cid in keep
        if cid in state.awaiting_activity
    }
    return dropped


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
