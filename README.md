# playwait

While you focus on a game (or another fullscreen task), **Cursor agents** run in the background. When a turn finishes (or a tool needs approval), playwait pauses the window, focuses Cursor, and chimes. After you answer every waiting chat, it sends you back. There is a cooldown time that gives time before being pulled off of your primary focus, scales depending on the size of your last contribution (default between 1-4 min)


**Supported:** Ubuntu 24.04, GNOME on **X11** (not Wayland). Esc pause (not process freeze).

## Quick start (recommended)

### 1. Clone and install

```bash
sudo apt install xdotool wmctrl libnotify-bin
# Sound: pw-play (PipeWire) or paplay

git clone https://github.com/jhoh10/playwait.git ~/src/playwait
cd ~/src/playwait
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
chmod +x hooks/on-stop.sh hooks/on-submit.sh hooks/on-permission-*.sh
```

Python 3.12+.

### 2. Run the setup skill in Cursor

Open this repo in Cursor and run the **playwait-setup** skill (`.cursor/skills/playwait-setup/`).

It walks you through hooks, timing preferences (cool-down + awaiting TTL), optional GNOME hotkeys, and a dry-run. Prefer this over hand-editing configs.

Then: focus your game → `playwait arm` (or your hotkey) → play. When done: `playwait disarm`.

---

## Daily use

1. Prefer **borderless windowed** (or a normal window) over exclusive fullscreen so minimize/focus works reliably.
2. Focus the game (or other task) window and **arm** it:

   ```bash
   "$HOME/src/playwait/.venv/bin/playwait" arm
   ```

   Confirm with `playwait status` — you want `"mode": "armed"` and a non-null `"window_id"`.
3. When an agent finishes: soft chime → pause → minimize → Cursor. Extra finished chats while you’re already interrupted stay tracked; you are not yanked again. Mid-run **tool approvals** (MCP always; Shell when the command matches risk patterns) also yank immediately — they **bypass** cool-down. After you Allow, playwait **stays in Cursor** so a burst of approvals (or the imminent turn-end) does not bounce you back to the game.
4. Reply in Cursor. After each send, if other chats still need you, you stay in Cursor. When the **last fresh** waiting chat is answered, playwait returns you to the window and starts a cool-down that scales with reply effort (**1–4 min** by default). Waiting chats with **no activity for 15 minutes** are dropped automatically. If you leave the game for Cursor during cool-down, cool-down is abandoned (and a deferred agent-ready interrupt, if any, soft-fires without stealing focus back through the game).
5. Done with Cursor but won’t reply to a waiting chat? Clear and return:

   ```bash
   "$HOME/src/playwait/.venv/bin/playwait" release
   ```

6. When done for the night:

   ```bash
   "$HOME/src/playwait/.venv/bin/playwait" disarm
   ```

```bash
playwait status   # awaiting_reply lists chats still needing a reply
echo "$HOME/src/playwait/.venv/bin/playwait"   # absolute path for shortcuts/hooks
```

## Cursor hooks (manual reference)

The setup skill writes these for you. If editing by hand, use **absolute** paths in `~/.cursor/hooks.json`:

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
    ],
    "beforeMCPExecution": [
      {
        "command": "/home/YOU/src/playwait/hooks/on-permission-mcp.sh"
      }
    ],
    "beforeShellExecution": [
      {
        "command": "/home/YOU/src/playwait/hooks/on-permission-shell.sh"
      }
    ],
    "afterMCPExecution": [
      {
        "command": "/home/YOU/src/playwait/hooks/on-permission-done.sh"
      }
    ],
    "afterShellExecution": [
      {
        "command": "/home/YOU/src/playwait/hooks/on-permission-done.sh"
      }
    ]
  }
}
```

Replace `/home/YOU/src/playwait` with your real checkout path.

- **`stop`** — agent turn ended → interrupt (and remember that chat).
- **`beforeSubmitPrompt`** — you hit send → clear that chat; return only when none remain.
- **`beforeMCPExecution`** — MCP tool about to run → auto-interrupt (no cool-down).
- **`beforeShellExecution`** — Shell about to run → interrupt when command matches risk patterns (or `ask-always` if configured).
- **`afterMCPExecution` / `afterShellExecution`** — after Allow (tool finished) → clear the permission gate; stay in Cursor (return on reply / `release`).

Dry-run while disarmed:

```bash
echo '{"status":"completed","conversation_id":"test"}' | playwait on-stop
echo '{"conversation_id":"test","prompt":"hi"}' | playwait on-submit
PLAYWAIT_PERMISSION_SOURCE=mcp echo '{"tool_name":"demo"}' | playwait on-permission
PLAYWAIT_PERMISSION_SOURCE=shell echo '{"command":"sudo true"}' | playwait on-permission
```

## GNOME arm / disarm hotkeys

**Settings → Keyboard → View and Customize Shortcuts → Custom Shortcuts**

| Name | Command |
|------|---------|
| playwait arm | `$HOME/src/playwait/.venv/bin/playwait arm` |
| playwait disarm | `$HOME/src/playwait/.venv/bin/playwait disarm` |
| playwait release | `$HOME/src/playwait/.venv/bin/playwait release` |

GNOME may not expand `$HOME` in shortcuts — paste the expanded absolute path instead. Suggested chords: **Super+Alt+A** (arm), **Super+Alt+D** (disarm), **Super+Alt+R** (release).

## Config (optional)

`~/.config/playwait/config.toml`:

```toml
pause_key = "Escape"
resume_key = "Escape"
# Effort-scaled cool-down after return (seconds). Default Play range: 1–4 min.
cooldown_min_seconds = 60
cooldown_max_seconds = 240
# Fallback when you focus the window manually (no scored reply):
cooldown_seconds = 60
# Drop waiting chats with no stop/submit activity this long (seconds):
awaiting_ttl_seconds = 900   # 15 minutes
# Debug-only flat cool-down while developing playwait (not for normal play):
# cooldown_min_seconds = 20
# cooldown_max_seconds = 20
# cooldown_seconds = 20
# Leave game during cool-down for this long → abandon cool-down:
# cooldown_abandon_seconds = 1.0
# Tool-permission auto-interrupt:
# mcp_permission_interrupt = true
# shell_permission_interrupt = "patterns"  # or "ask-always" or "off"
cursor_name = "Cursor"
cursor_class = "cursor"
# interrupt_lead_seconds = 1.0   # chime, then wait before window changes
# interrupt_step_seconds = 0.4
# return_lead_seconds = 0.35
# desktop_notifications = true  # optional banners; off by default (chime-only)
```

State and logs: `~/.local/state/playwait/`.

```bash
# Live debug (stop/submit, awaiting chats, return):
tail -f ~/.local/state/playwait/playwait.log
playwait status   # mode + awaiting_reply snapshot
```

## Window tips

- Prefer **borderless windowed** over exclusive fullscreen.
- Pause defaults to **Esc**. Process freeze (`SIGSTOP`) is not in this early release yet.
- If the armed window is **closed**, playwait auto-disarms on the next stop/submit/permission/return/watcher tick (notification: “Armed window closed — disarmed”). Re-arm after launching the game again.

## Notifications

Playwait’s primary interrupt signal is a **chime**. Desktop banners are **off by default** — GNOME often queues them behind Cursor’s Allow/Deny prompts, then flushes a pile (including onto the login screen after logout).

To enable banners:

```toml
desktop_notifications = true
```

When enabled, banners are transient, reuse one notification slot, and are explicitly closed after a few seconds so they are less likely to linger into GDM.

On GNOME, while a Cursor tool Allow/Deny prompt sits unacknowledged, other banners still often **queue**. Trust the chime and `~/.local/state/playwait/playwait.log` when that happens.

## Development

```bash
source .venv/bin/activate
pytest
```

## License

MIT — see [LICENSE](LICENSE).

## Out of scope (0.1.x)

Wayland, SIGSTOP pause mode, non-Cursor agents. Exact “Allow/Deny UI appeared” events (Cursor has no PermissionRequest hook — Shell patterns are approximate).
