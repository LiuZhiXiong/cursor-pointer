# cursor-pointer ↔ WebClaw bridge E2E test

## What this verifies

`browser "<task>"` in cursor-pointer agent → WebClaw drains → executes via WebClaw's `agent.run()` → result lands back in cursor-pointer's history.

## Prerequisites

1. **cursor-pointer running**
   ```bash
   curl -s http://127.0.0.1:39213/health
   ```
   Must return `{"ok":true,...}`. If not, `open /Applications/CursorPointer.app`.

2. **WebClaw extension loaded in Chrome**
   - Open `chrome://extensions`
   - Toggle "Developer mode" (top right)
   - Click "Load unpacked"
   - Select `/Users/liuzhixiong/coding-project/workspace-ai/web-claw/web-claw/`
     (the Vite output directory, not the source dir)
   - If WebClaw is already loaded, click the Reload (⟳) button on its card

3. **Remote Control enabled in WebClaw sidepanel**
   - Click the WebClaw icon to open the sidepanel
   - Scroll to the "Remote Control (cursor-pointer)" section
   - Check "Enable polling"
   - Verify the URL is `http://127.0.0.1:39213`
   - Click **Save**
   - The status line should show `✓ enabled, polling`

## Running the test

```bash
bash /Users/liuzhixiong/coding-project/cursor-pointer/scripts/test_bridge_e2e.sh
```

Expected output:
```
=== 1. cursor-pointer reachable? ===
{"ok":true,...}

=== 2. enqueue a browser command ===
{"id":"<uuid>","expires_at":...}
id: <uuid>

=== 3. poll for result (up to 30s) ===
[t=2s] ? {"status":"pending"}
[t=4s] ✓ {"status":"done","ok":true,"output":"..."}
```

`output` is whatever WebClaw's `agent.run()` produced — typically a short
sentence describing the current tab's title or content.

## If the script reports `expired`

WebClaw isn't draining the queue. Check in the WebClaw sidepanel:
- Remote Control toggle is checked AND saved
- The status line shows `✓ enabled, polling`
- The URL exactly matches the cursor-pointer port

You can also tail Chrome's console for `[remote-control]` log lines.

## If the script times out

WebClaw enabled polling but `agent.run()` is slow or stuck. Open
Chrome's DevTools on the active tab and check the WebClaw side panel
for stuck operations. Click WebClaw → Stop Agent if available.

## Architecture recap

```
cursor-pointer agent
  → execute("browser \"...\"")
  → POST /browser/enqueue  (HTTP, localhost)

WebClaw service-worker
  → setInterval(2s) → GET /browser/next-command
  → agent.run({messages:[{role:"user",content:command}]})
  → POST /browser/result {id, ok, output}

cursor-pointer agent
  → GET /browser/result/<id>  (polled until done)
  → history.append(f"browser ... → ...")
```

Implementation:
- cursor-pointer commit: `dcf3ba5 feat(bridge): cursor-pointer side`
- web-claw branch: `feature/cursor-pointer-bridge` (commits 28c9dfd, 0f28823, c43c5d3, a095909)
