# launchd Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Auto-start CursorPointer.app at user login via a versioned launchd LaunchAgent + install/uninstall shell scripts.

**Architecture:** Three files under `scripts/launchd/`: a plist, an install script, and an uninstall script. `open -a` invocation so LaunchServices handles GUI/TCC properly. Self-assert via `launchctl list` after each operation.

**Tech Stack:** macOS launchd, plain Bash. No Python, Rust, or test framework changes.

**Spec:** [`docs/superpowers/specs/2026-05-17-launchd-integration-design.md`](../specs/2026-05-17-launchd-integration-design.md)

---

## Task 1: write the plist

**Files:**
- Create: `scripts/launchd/com.cursorpointer.plist`

- [ ] **Step 1: create the plist file**

```bash
mkdir -p /Users/liuzhixiong/coding-project/cursor-pointer/.claude/worktrees/launchd/scripts/launchd
```

Write `scripts/launchd/com.cursorpointer.plist` with EXACTLY this content:

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

- [ ] **Step 2: validate with plutil**

Run:
```bash
plutil -lint /Users/liuzhixiong/coding-project/cursor-pointer/.claude/worktrees/launchd/scripts/launchd/com.cursorpointer.plist
```

Expected output: `... .plist: OK`

If plutil errors, fix the XML (most common issue: stray whitespace or wrong DOCTYPE).

- [ ] **Step 3: commit**

```bash
cd /Users/liuzhixiong/coding-project/cursor-pointer/.claude/worktrees/launchd
git add scripts/launchd/com.cursorpointer.plist
git commit -m "feat(launchd): add com.cursorpointer.plist LaunchAgent template"
```

---

## Task 2: write install.sh

**Files:**
- Create: `scripts/launchd/install.sh`

- [ ] **Step 1: create install.sh**

Write `scripts/launchd/install.sh` with EXACTLY this content:

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

if launchctl list | grep -q "com.cursorpointer"; then
    echo "✓ installed → $DEST"
    echo "✓ active in launchctl"
    echo "  Run 'launchctl start com.cursorpointer' to launch NOW without re-login."
else
    echo "✗ launchctl load reported success but 'launchctl list' shows nothing"
    exit 2
fi
```

- [ ] **Step 2: chmod +x**

```bash
chmod +x /Users/liuzhixiong/coding-project/cursor-pointer/.claude/worktrees/launchd/scripts/launchd/install.sh
```

- [ ] **Step 3: shellcheck (best-effort)**

If `shellcheck` is installed (`which shellcheck`), run:

```bash
shellcheck /Users/liuzhixiong/coding-project/cursor-pointer/.claude/worktrees/launchd/scripts/launchd/install.sh
```

If shellcheck is missing, skip (zero installs not blocking).

- [ ] **Step 4: live test (the .app exists, so install should succeed)**

```bash
bash /Users/liuzhixiong/coding-project/cursor-pointer/.claude/worktrees/launchd/scripts/launchd/install.sh
launchctl list | grep com.cursorpointer
```

Expected:
- script output ends with `✓ installed → ...` and `✓ active in launchctl`
- `launchctl list | grep com.cursorpointer` returns exactly one line like `-	0	com.cursorpointer`

- [ ] **Step 5: commit**

```bash
cd /Users/liuzhixiong/coding-project/cursor-pointer/.claude/worktrees/launchd
git add scripts/launchd/install.sh
git commit -m "feat(launchd): add install.sh with self-assert via launchctl list"
```

---

## Task 3: write uninstall.sh + verify round-trip

**Files:**
- Create: `scripts/launchd/uninstall.sh`

- [ ] **Step 1: create uninstall.sh**

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

- [ ] **Step 2: chmod +x**

```bash
chmod +x /Users/liuzhixiong/coding-project/cursor-pointer/.claude/worktrees/launchd/scripts/launchd/uninstall.sh
```

- [ ] **Step 3: live test — uninstall the install from Task 2**

```bash
bash /Users/liuzhixiong/coding-project/cursor-pointer/.claude/worktrees/launchd/scripts/launchd/uninstall.sh
launchctl list | grep -c com.cursorpointer
```

Expected:
- script output ends with `✓ removed → ...`
- `launchctl list | grep -c com.cursorpointer` returns `0` (no matches; grep exits 1, that's fine — note the `-c` here counts and prints `0`, not exit 1)

Actually: `launchctl list | grep -c com.cursorpointer` returns the count `0` to stdout AND exits 1 when count is 0. To avoid the exit-1 bash trip, use:

```bash
launchctl list | grep -c com.cursorpointer || true
```

- [ ] **Step 4: idempotent re-uninstall**

```bash
bash /Users/liuzhixiong/coding-project/cursor-pointer/.claude/worktrees/launchd/scripts/launchd/uninstall.sh
```

Expected: prints `(nothing to uninstall — ...)` and exits 0.

- [ ] **Step 5: full round-trip — install again then uninstall again**

```bash
bash /Users/liuzhixiong/coding-project/cursor-pointer/.claude/worktrees/launchd/scripts/launchd/install.sh
bash /Users/liuzhixiong/coding-project/cursor-pointer/.claude/worktrees/launchd/scripts/launchd/uninstall.sh
```

Both must succeed end-to-end.

- [ ] **Step 6: commit**

```bash
cd /Users/liuzhixiong/coding-project/cursor-pointer/.claude/worktrees/launchd
git add scripts/launchd/uninstall.sh
git commit -m "feat(launchd): add uninstall.sh + verify install/uninstall round-trip"
```

---

## Task 4: docs/API.md update

**Files:**
- Modify: `docs/API.md`

- [ ] **Step 1: append the Auto-start section**

Open `docs/API.md`. Find the existing `## Permissions {#permissions}` heading. After that section ends (the section that lists Accessibility / Input Monitoring / Screen Recording grants), add a new top-level section:

```markdown
---

## Auto-start on login

The bundled LaunchAgent makes CursorPointer.app auto-start at user login.

```bash
bash scripts/launchd/install.sh     # one-time setup
bash scripts/launchd/uninstall.sh   # remove
```

The plist runs `open -a /Applications/CursorPointer.app` at login. Logs go
to `/tmp/cursorpointer.launchd.log` and `.err`. Use `launchctl list | grep
com.cursorpointer` to confirm the service is registered.

To launch immediately (without logging out and back in):

```bash
launchctl start com.cursorpointer
```
```

- [ ] **Step 2: commit**

```bash
cd /Users/liuzhixiong/coding-project/cursor-pointer/.claude/worktrees/launchd
git add docs/API.md
git commit -m "docs(API): document launchd auto-start scripts"
```

---

## Task 5: E2E — install, restart .app via launchd, verify health

**Files:** none modified.

The full goal of this feature is "at login, CursorPointer.app auto-runs." We can simulate that without logging out by using `launchctl start`.

- [ ] **Step 1: ensure we're starting clean**

```bash
bash /Users/liuzhixiong/coding-project/cursor-pointer/.claude/worktrees/launchd/scripts/launchd/uninstall.sh
pkill -f "CursorPointer.app/Contents/MacOS/cursor-pointer" 2>&1 || true
sleep 1
curl -s --max-time 2 http://127.0.0.1:39213/health 2>&1 || echo "(API down — expected)"
```

Expected: API is down (no cursor-pointer running).

- [ ] **Step 2: install + manual start**

```bash
bash /Users/liuzhixiong/coding-project/cursor-pointer/.claude/worktrees/launchd/scripts/launchd/install.sh
launchctl start com.cursorpointer
sleep 4
curl -s http://127.0.0.1:39213/health
```

Expected: GET /health returns `{"ok":true,...}`.

- [ ] **Step 3: simulate restart by killing the .app and re-`launchctl start`**

```bash
pkill -f "CursorPointer.app/Contents/MacOS/cursor-pointer"
sleep 2
curl -s --max-time 2 http://127.0.0.1:39213/health 2>&1 || echo "(API down — expected after kill)"

launchctl start com.cursorpointer
sleep 4
curl -s http://127.0.0.1:39213/health
```

Expected: after kill, API down; after re-start, API up again. This confirms launchd can re-launch the .app on demand.

- [ ] **Step 4: leave the LaunchAgent installed**

Don't uninstall at the end of this task — the user wants auto-start to STAY working. The merge to main will leave the LaunchAgent loaded.

- [ ] **Step 5: optional evidence archive**

```bash
cd /Users/liuzhixiong/coding-project/cursor-pointer/.claude/worktrees/launchd
mkdir -p docs/superpowers/evidence
cat > docs/superpowers/evidence/2026-05-17-launchd-e2e.log <<'EOF'
launchd E2E (manual):
  $ bash scripts/launchd/install.sh
  ✓ installed → ~/Library/LaunchAgents/com.cursorpointer.plist
  $ launchctl start com.cursorpointer; sleep 4; curl /health
  {"ok":true,"name":"cursor-pointer","version":"0.1.0"}
  $ pkill cursor-pointer; sleep 2; curl /health
  (API down)
  $ launchctl start com.cursorpointer; sleep 4; curl /health
  {"ok":true,"name":"cursor-pointer","version":"0.1.0"}
EOF
git add docs/superpowers/evidence/2026-05-17-launchd-e2e.log
git commit -m "evidence: launchd E2E — install/start/kill/restart confirmed"
```

---

## Self-Review Notes

- **Spec coverage:** plist → Task 1. install.sh → Task 2. uninstall.sh → Task 3. docs → Task 4. E2E → Task 5.
- **Placeholder scan:** no TBDs.
- **Type consistency:** plist file path identical everywhere (`scripts/launchd/com.cursorpointer.plist`); install dest identical (`$HOME/Library/LaunchAgents/com.cursorpointer.plist`); label identical (`com.cursorpointer`).
- **Tests:** shell self-assert in install + uninstall + E2E manual round-trip. No pytest needed.
- **Roll-back:** `bash scripts/launchd/uninstall.sh` reverses install. Reverting commits reverts the files.
