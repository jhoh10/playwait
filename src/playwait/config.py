from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path


def _xdg_config_home() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))


def _xdg_state_home() -> Path:
    return Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))


def _xdg_data_home() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))


@dataclass
class Config:
    pause_key: str = "Escape"
    resume_key: str = "Escape"
    cooldown_seconds: int = 120
    cursor_name: str = "Cursor"
    cursor_class: str = "cursor"
    poll_interval_seconds: float = 0.4
    # Soften yank-to-Cursor: chime first, then staged pause → minimize → focus.
    interrupt_lead_seconds: float = 0.55
    interrupt_step_seconds: float = 0.4
    return_lead_seconds: float = 0.35
    interrupt_sound: str = ""
    confirm_sound: str = ""
    state_dir: Path = field(default_factory=lambda: _xdg_state_home() / "playwait")
    config_path: Path = field(
        default_factory=lambda: _xdg_config_home() / "playwait" / "config.toml"
    )

    @property
    def state_path(self) -> Path:
        return self.state_dir / "state.json"

    @property
    def log_path(self) -> Path:
        return self.state_dir / "playwait.log"

    def resolve_sound(self, kind: str) -> Path | None:
        """Return a path to a sound file if one exists."""
        configured = self.interrupt_sound if kind == "interrupt" else self.confirm_sound
        if configured:
            p = Path(configured).expanduser()
            if p.is_file():
                return p
        # Packaged assets next to the installed package, then repo assets, then freedesktop.
        candidates: list[Path] = []
        pkg = Path(__file__).resolve().parent
        repo_root = pkg.parents[1] if len(pkg.parents) > 1 else pkg
        name = "interrupt.wav" if kind == "interrupt" else "confirm.wav"
        candidates.append(repo_root / "assets" / "sounds" / name)
        candidates.append(pkg / "assets" / "sounds" / name)
        share = _xdg_data_home() / "playwait" / "sounds" / name
        candidates.append(share)
        freedesktop = Path("/usr/share/sounds/freedesktop/stereo")
        candidates.append(
            freedesktop / ("message.oga" if kind == "interrupt" else "dialog-information.oga")
        )
        for c in candidates:
            if c.is_file():
                return c
        return None


def load_config(path: Path | None = None) -> Config:
    cfg = Config()
    config_path = path or cfg.config_path
    if not config_path.is_file():
        return cfg
    try:
        with config_path.open("rb") as f:
            data = tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError):
        return cfg
    for key in (
        "pause_key",
        "resume_key",
        "cursor_name",
        "cursor_class",
        "interrupt_sound",
        "confirm_sound",
    ):
        if key in data and isinstance(data[key], str):
            setattr(cfg, key, data[key])
    if "cooldown_seconds" in data and isinstance(data["cooldown_seconds"], int):
        cfg.cooldown_seconds = max(1, data["cooldown_seconds"])
    if "poll_interval_seconds" in data and isinstance(
        data["poll_interval_seconds"], (int, float)
    ):
        cfg.poll_interval_seconds = float(data["poll_interval_seconds"])
    for delay_key in (
        "interrupt_lead_seconds",
        "interrupt_step_seconds",
        "return_lead_seconds",
    ):
        if delay_key in data and isinstance(data[delay_key], (int, float)):
            setattr(cfg, delay_key, max(0.0, float(data[delay_key])))
    if "state_dir" in data and isinstance(data["state_dir"], str):
        cfg.state_dir = Path(data["state_dir"]).expanduser()
    return cfg
