---
name: playwait-setup
description: >-
  Guided interactive setup for playwait (Ubuntu/X11 Cursor hooks, venv install,
  GNOME arm/disarm hotkeys). Use when the user asks to install or set up
  playwait, wire Cursor stop/beforeSubmitPrompt hooks, configure arm hotkeys,
  or get playwait working for the first time.
---

# playwait setup

Walk the user through a **minimal** first-time setup. Detect what’s already done; only ask for missing decisions. Prefer doing work for them (edit files, run installs) over dumping the whole README.

## Goals

After this skill finishes, the user should have:

1. playwait installed in a venv (editable)
2. `~/.cursor/hooks.json` pointing at **absolute** `on-stop.sh` / `on-submit.sh`
3. Absolute-path GNOME custom shortcuts for arm/disarm (or clear skip)
4. A dry-run proof that hooks invoke playwait

Supported target: **Ubuntu + GNOME on X11**. If Wayland, stop and explain — playwait won’t work yet.

## Style

- Short questions; one decision at a time.
- Surface **only** the instruction they must do by hand (e.g. GNOME Settings keybinding UI, `sudo` password).
- Do not dump full README sections unless they ask.
- Use absolute paths everywhere (hooks + shortcuts).

## Progress checklist

Copy and update as you go:

```
playwait setup:
- [ ] Session is X11
- [ ] Checkout + venv install
- [ ] apt deps (xdotool, wmctrl, libnotify-bin)
- [ ] Cursor hooks.json wired
- [ ] GNOME arm/disarm shortcuts
- [ ] Dry-run on-stop / on-submit
```

---

## Step 0 — Find the repo

1. If the workspace is already a playwait checkout (`pyproject.toml` name `playwait`, `hooks/on-stop.sh` exists), use that path as `ROOT`.
2. Otherwise ask:
   - Clone fresh into `~/src/playwait`?
   - Or path to an existing checkout?
3. Resolve `ROOT` to an absolute path. Set:
   - `PW="$ROOT/.venv/bin/playwait"`
   - `STOP="$ROOT/hooks/on-stop.sh"`
   - `SUBMIT="$ROOT/hooks/on-submit.sh"`

---

## Step 1 — Session type (gate)

Run:

```bash
echo "${XDG_SESSION_TYPE:-unknown}"
```

- If `wayland`: stop. Tell them playwait needs GNOME on **X11** for now; switching sessions is out of scope of this skill unless they ask.
- If `x11`: continue.
- If unknown: ask them to confirm X11 before continuing.

---

## Step 2 — Install package (venv)

If `$PW` is missing or not executable:

```bash
cd "$ROOT"
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
chmod +x hooks/on-stop.sh hooks/on-submit.sh
```

Confirm:

```bash
"$PW" --help >/dev/null && echo OK
```

Ask only if clone vs existing checkout was unclear; don’t re-ask install path once `ROOT` is set.

---

## Step 3 — System deps

Check for `xdotool`, `wmctrl`, `notify-send`:

```bash
command -v xdotool; command -v wmctrl; command -v notify-send
```

If any missing, ask permission to run:

```bash
sudo apt install xdotool wmctrl libnotify-bin
```

Sound is optional (`pw-play` or `paplay`); mention only if both are missing.

---

## Step 4 — Cursor hooks (critical)

Read `~/.cursor/hooks.json` if it exists.

**Required hooks** (absolute paths):

```json
{
  "version": 1,
  "hooks": {
    "stop": [{ "command": "STOP_PATH" }],
    "beforeSubmitPrompt": [{ "command": "SUBMIT_PATH" }]
  }
}
```

Replace `STOP_PATH` / `SUBMIT_PATH` with `$STOP` / `$SUBMIT`.

Rules:

- Merge into existing hooks; do **not** wipe unrelated hooks.
- Both commands **must** be absolute and end in `playwait/hooks/on-stop.sh` and `…/on-submit.sh` (not a parent `productivity/hooks/` path).
- If a wrong path is present, fix it and tell the user what changed.
- After writing, show a one-line summary of the two commands.

If Cursor is already open, tell them hooks may need a **Cursor restart** (or new agent) to pick up `hooks.json` changes — one sentence only.

---

## Step 5 — GNOME arm / disarm shortcuts

Ask whether they want hotkeys now or later.

If yes:

1. Resolve absolute arm/disarm commands (expand `$HOME`; GNOME often won’t):

   ```bash
   echo "$PW arm"
   echo "$PW disarm"
   ```

2. Give **only** this hand-done UI recipe (don’t paste the whole README):

   - Settings → Keyboard → View and Customize Shortcuts → Custom Shortcuts
   - Add **playwait arm** → command from step 1 → suggest **Super+Alt+A**
   - Add **playwait disarm** → suggest **Super+Alt+D**

3. Ask them to confirm once both exist (or that they skipped).

Do not try to drive the GNOME Settings GUI unless they explicitly want automation and a reliable method is available.

---

## Step 6 — Dry-run proof

While **disarmed** (`"$PW" status` should show `"mode": "idle"` or no armed window):

```bash
echo '{"status":"completed","conversation_id":"setup-test"}' | "$PW" on-stop
echo '{"conversation_id":"setup-test","prompt":"hi"}' | "$PW" on-submit
```

Expect JSON `{"continue": true}` from on-submit and no crash. Point them at:

```bash
tail -n 20 ~/.local/state/playwait/playwait.log
```

If submit never appears in the log later during real use, the usual bug is a wrong `beforeSubmitPrompt` path in `hooks.json`.

---

## Step 7 — First real use (brief)

Tell them only this:

1. Focus the game / other task window → run arm (hotkey or `"$PW" arm`).
2. Check `"$PW" status` → `"mode": "armed"`, non-null `window_id`.
3. Prefer borderless/windowed over exclusive fullscreen.
4. When done: disarm.

Optional debug: `tail -f ~/.local/state/playwait/playwait.log`

---

## Failure cheat sheet

| Symptom | Likely cause |
|--------|----------------|
| Agent ends, game never pauses | `stop` hook path wrong / not executable / not X11 |
| Reply sent, never returns | `beforeSubmitPrompt` missing or wrong path |
| Stuck “still awaiting” | Extra `conversation_id` in state; check `playwait status` + log |
| Arm grabs wrong window | Focus the target window first, then arm |

## Out of scope for this skill

Wayland, SIGSTOP pause, mid-run Allow/Deny, publishing releases, changing cool-down heuristics.
