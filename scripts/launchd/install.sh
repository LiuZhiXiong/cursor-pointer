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
