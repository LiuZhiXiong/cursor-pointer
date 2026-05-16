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
