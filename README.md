# playwait

Personal Linux helper: while you play a single-player game (e.g. Skyrim on Proton), **Cursor agents** can run in the background. When an agent turn finishes, playwait pauses the game, minimizes it, focuses Cursor, and plays a soft chime. After you answer **every** chat that was waiting, it sends you back to the game. A short cool-down then avoids frantic back-and-forth.

**Supported environment (v0.1):** Ubuntu 24.04, GNOME on **X11** (not Wayland). Esc-based in-game pause (not process freeze).

## Requirements

```bash
sudo apt install xdotool wmctrl libnotify-bin
# Sound: pw-play (PipeWire) or paplay
```

Python 3.12+.

## Install

```bash
git clone <this-repo> ~/src/playwait
cd ~/src/playwait
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
chmod +x hooks/on-stop.sh hooks/on-submit.sh
```

Use the venv binary by absolute path in shortcuts and hooks (GNOME/Cursor often lack your shell `PATH`):

```bash
echo "$HOME/src/playwait/.venv/bin/playwait"
```

## Daily use

1. Run the game in **borderless windowed** mode if using Proton.
2. Focus the game and **arm** it (see hotkeys below):

   ```bash
   "$HOME/src/playwait/.venv/bin/playwait" arm
   ```

   Confirm with `playwait status` — you want `"mode": "armed"` and a non-null `"window_id"`.
3. When an agent finishes: soft chime → pause → minimize → Cursor. Extra finished chats while you’re already interrupted stay tracked; you are not yanked again.
4. Reply in Cursor. After each send, if other chats still need you, you stay in Cursor. When the **last** waiting chat is answered, playwait returns you to the game and starts a cool-down that scales with how much thought your replies took (**30s–3 min**, local heuristics — short “yes” → short cool-down; longer/code-heavy replies → longer).
5. When done for the night:

   ```bash
   "$HOME/src/playwait/.venv/bin/playwait" disarm
   ```

```bash
playwait status   # awaiting_reply lists chats still needing a reply
```

## Cursor hooks

Create or edit `~/.cursor/hooks.json` with **absolute** paths (adjust if your clone is elsewhere):

```json
{
  "version": 1,
  "hooks": {
    "stop": [
      {
        "command": "/home/YOU/src/playwait/hooks/on-stop.sh"
      }
    ],
    "beforeSubmitPrompt": [
      {
        "command": "/home/YOU/src/playwait/hooks/on-submit.sh"
      }
    ]
  }
}
```

Replace `/home/YOU/src/playwait` with your real checkout path (e.g. output of `pwd` inside the repo).

- **`stop`** — agent turn ended → interrupt (and remember that chat).
- **`beforeSubmitPrompt`** — you hit send → clear that chat; return to game only when none remain.

Dry-run while disarmed:

```bash
echo '{"status":"completed","conversation_id":"test"}' | playwait on-stop
echo '{"conversation_id":"test","prompt":"hi"}' | playwait on-submit
```

## GNOME arm / disarm hotkeys

**Settings → Keyboard → View and Customize Shortcuts → Custom Shortcuts**

| Name | Command |
|------|---------|
| playwait arm | `$HOME/src/playwait/.venv/bin/playwait arm` |
| playwait disarm | `$HOME/src/playwait/.venv/bin/playwait disarm` |

GNOME may not expand `$HOME` in shortcuts — paste the expanded absolute path instead. Suggested chords: **Super+Alt+A** (arm), **Super+Alt+D** (disarm).

## Config (optional)

`~/.config/playwait/config.toml`:

```toml
pause_key = "Escape"
resume_key = "Escape"
# Effort-scaled cool-down after return-to-game (seconds):
cooldown_min_seconds = 30
cooldown_max_seconds = 180
# Fallback when you focus the game manually (no scored reply):
cooldown_seconds = 30
cursor_name = "Cursor"
cursor_class = "cursor"
# interrupt_lead_seconds = 1.0   # chime, then wait before window changes
# interrupt_step_seconds = 0.4
# return_lead_seconds = 0.35
```

State and logs: `~/.local/state/playwait/`.

```bash
# Live debug (stop/submit, awaiting chats, return-to-game):
tail -f ~/.local/state/playwait/playwait.log
playwait status   # mode + awaiting_reply snapshot
```

## Proton / Skyrim tips

- Prefer **borderless windowed** over exclusive fullscreen.
- Pause uses **Esc** (in-game menu). Process freeze (`SIGSTOP`) is a known Proton approach elsewhere; not in v0.1 yet.

## Development

```bash
source .venv/bin/activate
pytest
```

## License

MIT — see [LICENSE](LICENSE).

## Out of scope (v0.1)

Mid-run Allow/Deny detection, Wayland, SIGSTOP pause mode, non-Cursor agents.
