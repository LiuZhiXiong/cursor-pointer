#!/usr/bin/env bash
# Cross-repo E2E test for cursor-pointer ↔ WebClaw bridge.
# Prerequisites:
#   1. CursorPointer.app running (http://127.0.0.1:39213/health returns ok)
#   2. WebClaw extension loaded in Chrome from
#      /Users/liuzhixiong/coding-project/workspace-ai/web-claw/web-claw/
#      (the Vite-built output dir)
#   3. WebClaw sidepanel → Remote Control section → enable polling with
#      baseUrl=http://127.0.0.1:39213, click Save
set -euo pipefail

API="http://127.0.0.1:39213"

echo "=== 1. cursor-pointer reachable? ==="
curl -s --max-time 2 "$API/health"
echo

echo
echo "=== 2. enqueue a browser command ==="
ENQ=$(curl -s -X POST "$API/browser/enqueue" \
     -H "Content-Type: application/json" \
     -d '{"command":"what is the page title of the current tab? answer in one sentence","timeout_seconds":60}')
echo "$ENQ"
ID=$(echo "$ENQ" | sed -E 's/.*"id":"([^"]+)".*/\1/')
echo "id: $ID"
echo

echo "=== 3. poll for result (up to 30s) ==="
for i in $(seq 1 60); do
    STATUS=$(curl -s "$API/browser/result/$ID")
    STATE=$(echo "$STATUS" | sed -E 's/.*"status":"([^"]+)".*/\1/')
    case "$STATE" in
        done) echo "[t=$((i/2))s] ✓ $STATUS"; exit 0 ;;
        expired) echo "[t=$((i/2))s] ✗ expired — WebClaw not polling? $STATUS"; exit 2 ;;
        pending) ;;
        *) echo "[t=$((i/2))s] ? $STATUS" ;;
    esac
    sleep 0.5
done

echo "✗ timed out after 30s — did WebClaw drain the queue?"
exit 3
