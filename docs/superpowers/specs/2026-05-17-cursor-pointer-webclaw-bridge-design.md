# cursor-pointer ↔ WebClaw bridge — design

**Date:** 2026-05-17
**Author:** brainstorming session with @liuzhixiong
**Status:** approved → ready for implementation plans (one per repo)

## Problem

cursor-pointer's agent drives macOS apps via AX + cursor-pointer's HTTP API. Browser tasks (DOM, fetches, complex web UIs) work poorly because AX of browser content is partial. WebClaw already runs an Agent + automation-bridge **inside** Chrome with full DOM access, but cursor-pointer has no way to delegate to it.

## Goal

Let cursor-pointer's agent emit a `browser <command>` verb that gets executed by WebClaw inside Chrome, and receive the result back.

## Non-goals

- Native Messaging (would require a Chromium Native Messaging Host installer; YAGNI).
- WebSocket — WebClaw's `external-comm.js` already has WebSocket support, but polling HTTP is simpler and survives Service Worker restarts.
- Bidirectional streaming — one command → one result is enough.
- Authentication — both endpoints are localhost only; same trust model as the existing cursor-pointer API.

## Architecture

```
┌─────────────────────────────┐         ┌─────────────────────────────┐
│  cursor-pointer agent        │         │  WebClaw service worker      │
│  (Python: run_agent.py)      │         │  (Chrome extension JS)       │
│                              │         │                              │
│   verb: browser "click .x"   │         │  every 2s when enabled:       │
│        │                     │         │     ↓                        │
│        ▼                     │  GET    │   fetch /browser/next-command │
│   POST /browser/enqueue ─────┼─────────┤   ◇ command? → run via       │
│    cmd, id                   │         │     existing AGENT_TOOLS     │
│                              │         │     ↓                        │
│   POLL /browser/result/<id>  │         │   POST /browser/result        │
│    until done or timeout     ◀─────────┤    id, ok, output             │
└─────────────────────────────┘         └─────────────────────────────┘
                  │                                       │
                  └────── shared HTTP 127.0.0.1:39213 ────┘
                          (cursor-pointer is the server,
                           WebClaw is the polling client)
```

cursor-pointer hosts a single command queue keyed by UUID. Agent enqueues, then polls a result endpoint until done or timeout. WebClaw long-polls (or short-polls) the queue, executes locally, posts result.

## Wire protocol (locked)

### `POST /browser/enqueue`

Request:
```json
{ "command": "<freeform string>", "timeout_seconds": 30 }
```

Response:
```json
{ "id": "<uuid>", "expires_at": "<iso8601>" }
```

The agent gets back an ID and a deadline.

### `GET /browser/next-command`

Response:
```json
{ "id": "<uuid>", "command": "<string>" }
```

…or `{}` if queue empty. WebClaw polls this every 2s.

### `POST /browser/result`

Request:
```json
{ "id": "<uuid>", "ok": true, "output": "<freeform string>" }
```

If `ok: false`, `output` carries the error message. Response: `{ "ok": true }`.

### `GET /browser/result/<id>` (agent polls this)

Response when pending:
```json
{ "status": "pending" }
```

When done:
```json
{ "status": "done", "ok": true, "output": "<...>" }
```

When expired:
```json
{ "status": "expired" }
```

## Components

### cursor-pointer side (Python + Rust)

**Rust (`src-tauri/src/api.rs`):**
- In-memory queue: `BrowserQueue { pending: Mutex<HashMap<String, BrowserCommand>>, results: Mutex<HashMap<String, BrowserResult>> }`
- Routes:
  - `POST /browser/enqueue` → put on queue, return uuid
  - `GET /browser/next-command` → return + remove first pending
  - `POST /browser/result` → store result for id
  - `GET /browser/result/<id>` → return current status
- TTL: commands older than 60s get dropped. Results older than 60s get dropped.

**Python agent (`python-client/tools/run_agent.py`):**
- New verb `browser` in `execute()`:
  ```python
  if verb == "browser":
      cmd_text = <strip "browser " prefix>
      r = requests.post(f"{API}/browser/enqueue", json={"command": cmd_text, "timeout_seconds": 30}).json()
      cmd_id = r["id"]
      deadline = time.time() + 35
      while time.time() < deadline:
          st = requests.get(f"{API}/browser/result/{cmd_id}").json()
          if st["status"] == "done":
              history.append(f"browser → {st['output'][:120]!r}")
              return None if st.get("ok") else st.get("output", "browser failed")
          if st["status"] == "expired":
              return "browser command expired (no WebClaw client polling?)"
          time.sleep(0.5)
      return "browser timed out waiting for WebClaw"
  ```

### WebClaw side (Chrome extension)

**New module `src/core/remote-control.js`:**
- `enableRemoteControl(baseUrl)` / `disableRemoteControl()` — turn the poll loop on/off.
- Internal: `setInterval(2000, async () => { /* fetch next + execute + post result */ })`
- Uses existing `agent()` from `src/core/agent.js` to execute the command (or a thinner wrapper if `agent()` expects too much ceremony).

**Sidepanel UI (`src/sidepanel/...`):**
- A toggle "Remote control (cursor-pointer)" with the cursor-pointer base URL input. Persisted to `chrome.storage.local`.

**Service worker (`src/background/service-worker.js`):**
- On startup, read the remote-control flag from storage; if on, call `enableRemoteControl(savedUrl)`.

## Data flow

1. Agent's VLM emits `action: browser "summarize the visible article"`.
2. Agent's `execute()` enqueues to cursor-pointer's queue, gets `id=abc`.
3. Agent polls `/browser/result/abc` every 500ms.
4. Meanwhile WebClaw's poll loop GETs `/browser/next-command`, receives `{id:"abc", command:"summarize ..."}`.
5. WebClaw runs the command via its agent; produces a string output.
6. WebClaw POSTs `/browser/result` with `{id:"abc", ok:true, output:"..."}`.
7. Agent's next poll sees `status:"done"`, returns the output text into history.
8. Next agent step sees the browser result in history and continues.

## Concurrency

- Multiple agents could enqueue simultaneously. The queue is FIFO; WebClaw drains in order.
- WebClaw's poll handles one command at a time (await-then-post-then-poll-again), so no parallel agent runs in WebClaw's tab.
- TTL prevents zombie queue entries if WebClaw isn't running.

## Error handling

| Failure | Handling |
|---|---|
| WebClaw not running | command expires after 30s → agent returns "browser command expired (no WebClaw client polling?)" |
| WebClaw command itself fails | WebClaw POSTs `ok:false output:"<err>"`; agent returns that error string |
| Network blip during enqueue | wrapped in agent's existing `_retry` |
| Queue full | TTL evicts old; new always accepted (size cap optional, defer) |
| WebClaw crashes mid-command | command stays in `pending` map until TTL; agent times out and reports |

## Testing

### cursor-pointer side (pytest, mocked)
- `test_enqueue_returns_id`
- `test_next_command_returns_oldest_pending`
- `test_next_command_empty_when_queue_empty`
- `test_post_result_unlocks_status_done`
- `test_result_status_expired_after_ttl`
- `test_agent_verb_browser_round_trip` (mocked HTTP)

### WebClaw side (jest/vitest)
- `test_remote_control_polls_when_enabled`
- `test_remote_control_skips_post_when_no_command`
- `test_remote_control_posts_result_after_execution`
- `test_remote_control_disabled_stops_polling`

### E2E (manual)
- Enable remote control in WebClaw sidepanel pointing at `http://127.0.0.1:39213`.
- Run cursor-pointer agent with `browser "what is the page title?"`.
- Confirm WebClaw responds with the page title in agent history.

## Scope

| Side | Files | Approx LOC |
|---|---|---|
| cursor-pointer Rust (api.rs) | 1 | ~80 |
| cursor-pointer Python (run_agent.py + client) | 2 | ~60 |
| cursor-pointer tests | 1 | ~80 |
| WebClaw remote-control module | 1 new | ~120 |
| WebClaw sidepanel toggle UI | 1-2 mod | ~40 |
| WebClaw service worker hookup | 1 mod | ~15 |
| WebClaw tests | 1 new | ~80 |
| **Total** | **9-10** | **~475** |

## Roll-back

- cursor-pointer: revert the api.rs commit; agent's `browser` verb becomes a "no such endpoint" error string. Other verbs unaffected.
- WebClaw: toggle off in sidepanel; the poll loop stops. No code change needed.

## Open questions (deferred)

- Streaming output for long-running commands (e.g. progressive screenshot of a page render). Defer until we have a use case.
- Per-tab targeting (agent says "browser tab=3 ..."). Defer; assume active tab for now.
- WebClaw auth token to prevent malicious sites from polling cursor-pointer pretending to be WebClaw. localhost is the only attack surface and we already accept that for the rest of cursor-pointer; defer.

## Two implementation plans

This spec covers BOTH repos. We'll author two separate plans:

1. `docs/superpowers/plans/2026-05-17-bridge-cursor-pointer-side.md` (in this repo)
2. `docs/superpowers/plans/2026-05-17-bridge-webclaw-side.md` (in web-claw repo)

Implementation order: cursor-pointer side first (so the endpoints exist for WebClaw to test against), then WebClaw side.
