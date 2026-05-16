# launchd integration — design

**Date:** 2026-05-17
**Author:** brainstorming session with @liuzhixiong
**Status:** approved → ready for implementation plan

## Problem

cursor-pointer has to be started manually every login. The .app sits at `/Applications/CursorPointer.app` but doesn't auto-launch. Restoring the agent after every reboot is friction.

## Goal

A minimal launchd LaunchAgent that auto-starts CursorPointer.app at login, with simple install/uninstall scripts in the repo.

## Non-goals

- Crash-restart (KeepAlive) — YAGNI; we can add later if .app proves unstable.
- Health checks (`curl /health` from launchd) — same.
- Full one-shot installer (build + permissions + venv) — separate concern, deferred.
- Supervising the Python agent — agent runs on-demand; we only auto-start the server.

## Architecture

```
~/Library/LaunchAgents/com.cursorpointer.plist  ← user LaunchAgent slot
    │
    └── ProgramArguments: ["/usr/bin/open", "-a", "/Applications/CursorPointer.app"]
        RunAtLoad: true
```

Uses `open -a` (not direct binary exec) so LaunchServices handles GUI session attachment and TCC attribution properly. Direct exec from launchd inherits a restricted env and is a known source of TCC mis-attribution.

## Components

### `scripts/launchd/com.cursorpointer.plist` (new file)

Source of truth, version-controlled.

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.cursorpointer</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/open</string>
        <string>-a</string>
        <string>/Applications/CursorPointer.app</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/tmp/cursorpointer.launchd.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/cursorpointer.launchd.err</string>
</dict>
</plist>
```

### `scripts/launchd/install.sh` (new file)

```bash
#!/usr/bin/env bash
set -euo pipefail

SRC="$(cd "$(dirname "$0")" && pwd)/com.cursorpointer.plist"
DEST="$HOME/Library/LaunchAgents/com.cursorpointer.plist"

if [ ! -d "/Applications/CursorPointer.app" ]; then
    echo "✗ /Applications/CursorPointer.app not found."
    echo "  Run 'npm run build' from the repo root, then copy the produced"
    echo "  CursorPointer.app to /Applications, then re-run this script."
    exit 1
fi

plutil -lint "$SRC" >/dev/null

mkdir -p "$HOME/Library/LaunchAgents"
cp "$SRC" "$DEST"
launchctl unload "$DEST" 2>/dev/null || true
launchctl load -w "$DEST"

# Self-assert
if launchctl list | grep -q "com.cursorpointer"; then
    echo "✓ installed → $DEST"
    echo "✓ active in launchctl"
    echo "  Run 'launchctl start com.cursorpointer' to launch NOW without re-login."
else
    echo "✗ launchctl load reported success but 'launchctl list' shows nothing"
    exit 2
fi
```

### `scripts/launchd/uninstall.sh` (new file)

```bash
#!/usr/bin/env bash
set -euo pipefail
DEST="$HOME/Library/LaunchAgents/com.cursorpointer.plist"

if [ ! -f "$DEST" ]; then
    echo "(nothing to uninstall — $DEST not present)"
    exit 0
fi

launchctl unload "$DEST" 2>/dev/null || true
rm -f "$DEST"

if launchctl list | grep -q "com.cursorpointer"; then
    echo "✗ uninstall failed — entry still in launchctl list"
    exit 1
fi

echo "✓ removed → $DEST"
```

### `docs/API.md` — new section

After the "Permissions" section, add:

```markdown
## Auto-start on login

```bash
bash scripts/launchd/install.sh     # one-time setup
bash scripts/launchd/uninstall.sh   # remove
```

The LaunchAgent runs `open -a CursorPointer.app` at login. Logs go to
`/tmp/cursorpointer.launchd.{log,err}`.
```

## Data flow

- User runs `install.sh` once.
- Script copies plist to `~/Library/LaunchAgents/`, calls `launchctl load -w`.
- macOS launchd at next login auto-launches CursorPointer.app.
- CursorPointer.app starts the HTTP API on port 39213 as before.
- On unload (uninstall.sh) the plist is removed; no orphan processes (the .app keeps running until quit, but won't restart on next login).

## Error handling

| Failure | Handling |
|---|---|
| `/Applications/CursorPointer.app` missing | install.sh refuses, prints build instructions, exit 1 |
| plist malformed | `plutil -lint` catches before copy, exit non-zero |
| `launchctl load` succeeds but service not listed | self-assert detects, exit 2 |
| uninstall on a never-installed system | uninstall.sh prints `(nothing to uninstall…)` and exit 0 (idempotent) |

## Testing

Shell-level smoke testable; no need for pytest. The install + uninstall scripts each have a self-assert step (`launchctl list | grep -q com.cursorpointer`). Manual verification:

1. `bash scripts/launchd/install.sh` → expect ✓ install lines.
2. `launchctl list | grep com.cursorpointer` → expect exactly one match.
3. `bash scripts/launchd/uninstall.sh` → expect ✓ removed line.
4. `launchctl list | grep com.cursorpointer` → expect no match (grep exits 1, that's fine).

For full E2E: after install, `launchctl start com.cursorpointer` + `curl /health` should return ok within a few seconds.

## Observability

- launchd logs to `/tmp/cursorpointer.launchd.log` and `.err`.
- `launchctl list` shows current registration + PID + exit code.

## Scope

| File | LOC |
|---|---|
| `com.cursorpointer.plist` | 22 |
| `install.sh` | 25 |
| `uninstall.sh` | 12 |
| `docs/API.md` addition | 10 |
| **Total** | **~69** |

No dependencies. No Python. No Rust. No tests (shell self-assert is enough).

## Roll-back

`uninstall.sh` reverses the install completely. Manually: `launchctl unload ~/Library/LaunchAgents/com.cursorpointer.plist && rm ~/Library/LaunchAgents/com.cursorpointer.plist`.

## Open questions (deferred)

- KeepAlive / crash restart — defer until we see real-world .app crashes.
- One-shot installer that also builds + grants permissions — separate Cycle.
- Should agent.py also be launchd-managed? — No; agent runs on-demand against the always-on .app.
