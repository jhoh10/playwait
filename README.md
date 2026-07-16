# playwait

Pause and minimize an armed game when a **Cursor agent finishes a turn**, raise Cursor, play a peaceful sound, then auto-resume when you return to the game. After resume, a **~2 minute cool-down** blocks another yank; if an agent finishes during cool-down, you get **one deferred yank** when it ends.

## Requirements (Ubuntu 24.04 / GNOME X11)

```bash
sudo apt install xdotool wmctrl libnotify-bin
# PipeWire sound player (usually present):
# pw-play  — or paplay from pulseaudio-utils
```

Python 3.12+.

## Install

```bash
cd /path/to/playwait
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
```

Put `playwait` on your PATH (venv `bin`, or `pip install --user -e .`).

## Daily use

1. Focus Skyrim (prefer **borderless windowed** under Proton).
2. Run **arm** (bind a GNOME custom shortcut):

   ```bash
   playwait arm
   ```

3. When a Cursor agent turn ends, playwait: Esc → minimize game → focus Cursor → soft sound.
4. Alt-tab / click back into the game → auto unpause (Esc again) → 2 minutes protected play.
5. When done for the night:

   ```bash
   playwait disarm
   ```

```bash
playwait status   # JSON state
```

## Cursor `stop` hook

Merge into `~/.cursor/hooks.json` (create if missing):

```json
{
  "version": 1,
  "hooks": {
    "stop": [
      {
        "command": "/absolute/path/to/playwait/hooks/on-stop.sh"
      }
    ]
  }
}
```

Make the wrapper executable:

```bash
chmod +x hooks/on-stop.sh
```

Dry-run while disarmed (should no-op):

```bash
echo '{"status":"completed"}' | playwait on-stop
```

## GNOME arm / disarm hotkeys

Settings → Keyboard → Custom Shortcuts:

| Name | Command |
|------|---------|
| playwait arm | `/path/to/.venv/bin/playwait arm` |
| playwait disarm | `/path/to/.venv/bin/playwait disarm` |

## Config (optional)

`~/.config/playwait/config.toml`:

```toml
pause_key = "Escape"
resume_key = "Escape"
cooldown_seconds = 120
cursor_name = "Cursor"
cursor_class = "cursor"
# interrupt_sound = "/path/to/soft.wav"
# confirm_sound = "/path/to/soft.wav"
```

State/logs: `~/.local/state/playwait/`.

## Proton / Skyrim tips

- Use **borderless windowed** so minimize/focus work reliably.
- v1 pauses with **Esc** (in-game menu). If Proton swallows the key, a later `pause_mode = sigstop` (Steam reaper tree, as in [SDH-PauseGames](https://github.com/popsUlfr/SDH-PauseGames)) is the proven fallback — not implemented yet.
- Exclusive fullscreen may fight window tools.

## Smoke checklist

- [ ] `pytest`
- [ ] `echo '{"status":"completed"}' | playwait on-stop` while disarmed → no yank
- [ ] Arm Skyrim → finish a Cursor turn → pause + minimize + Cursor + sound
- [ ] Refocus Skyrim → resumes; within 2 minutes another agent finish does not yank; after ~2m one deferred yank if pending

## Development

```bash
pytest
```

## Out of scope (v1)

Mid-run Allow/Deny detection, Wayland adapters, SIGSTOP pause mode, Claude Code hooks.
