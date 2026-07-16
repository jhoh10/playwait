# playwait

Pause and minimize an armed game when a **Cursor agent finishes a turn**, raise Cursor, play a peaceful sound, then **return you to the game when you’ve answered every chat that was waiting**. After resume, a **~2 minute cool-down** blocks another yank; if an agent finishes during cool-down, you get **one deferred yank** when it ends.

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
2. **Arm** the game so playwait knows which window to yank.

   Arming means: “the window that is focused right now is the game.” Focus Skyrim first, then run:

   ```bash
   playwait arm
   ```

   You should get a quiet desktop notification (and soft confirm sound) that the window was armed. Check anytime with:

   ```bash
   playwait status
   ```

   You want `"mode": "armed"` and a non-null `"window_id"`.

   Doing this from the terminal every time is awkward in fullscreen, so bind **arm** (and **disarm**) as GNOME custom shortcuts once:

   1. Open **Settings → Keyboard → View and Customize Shortcuts → Custom Shortcuts**.
   2. Click **+** / **Add Shortcut**.
   3. Name it e.g. `playwait arm`.
   4. For **Command**, use the **absolute path** to the installed CLI (not bare `playwait`, unless that is already on PATH for GUI apps — often it is not). After a venv install, that looks like:

      ```text
      /home/jon/projects/productivity/playwait/.venv/bin/playwait arm
      ```

      Adjust the path if your checkout or venv lives elsewhere.
   5. Assign a hotkey you will not hit by accident while playing (or that you only use when starting a play+agent session).
   6. Repeat for `playwait disarm` with the same binary path and `disarm` instead of `arm`.

   Then each session: focus Skyrim → press your arm hotkey → leave Cursor agents running in the background.

3. When a Cursor agent turn ends, playwait: Esc → minimize game → focus Cursor → soft sound. If **another** chat also finishes while you’re already interrupted, you stay in Cursor; playwait remembers both chats still need a reply.
4. Reply in Cursor. After each send, if other chats still need you, you stay put (notify: “N chats still need a reply”). When the **last** waiting chat gets a reply, playwait raises the game, unpauses, and starts the ~2 minute cool-down. You can still alt-tab back manually anytime.
5. When done for the night, **disarm** (hotkey or terminal) so later agent finishes do not touch your desktop:

   ```bash
   playwait disarm
   ```

```bash
playwait status   # JSON state — look at awaiting_reply for open chats
```

## Cursor hooks

You need **two** hooks. Merge into `~/.cursor/hooks.json` (create if missing), using **absolute** paths:

```json
{
  "version": 1,
  "hooks": {
    "stop": [
      {
        "command": "/absolute/path/to/playwait/hooks/on-stop.sh"
      }
    ],
    "beforeSubmitPrompt": [
      {
        "command": "/absolute/path/to/playwait/hooks/on-submit.sh"
      }
    ]
  }
}
```

Make the wrappers executable:

```bash
chmod +x hooks/on-stop.sh hooks/on-submit.sh
```

- **`stop`** — agent turn ended → yank (and remember that chat’s `conversation_id`).
- **`beforeSubmitPrompt`** — you hit send → clear that chat; return to game only when `awaiting_reply` is empty.

Dry-run while disarmed (should no-op):

```bash
echo '{"status":"completed","conversation_id":"test"}' | playwait on-stop
echo '{"conversation_id":"test","prompt":"hi"}' | playwait on-submit
```

## GNOME arm / disarm hotkeys

See **Daily use**, step 2, for the full walkthrough. Summary:

| Name | Command |
|------|---------|
| playwait arm | `/path/to/playwait/.venv/bin/playwait arm` |
| playwait disarm | `/path/to/playwait/.venv/bin/playwait disarm` |

Use absolute paths so the shortcuts work when GNOME does not inherit your shell PATH.

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
- [ ] Reply in that chat → auto return to game + cool-down
- [ ] Two chats finish → reply to one → stay in Cursor; reply to second → return to game
- [ ] Within cool-down another agent finish does not yank; after ~2m one deferred yank if pending

## Development

```bash
pytest
```

## Out of scope (v1)

Mid-run Allow/Deny detection, Wayland adapters, SIGSTOP pause mode, Claude Code hooks.
