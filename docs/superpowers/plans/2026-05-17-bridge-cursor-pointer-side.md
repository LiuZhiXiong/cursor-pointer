# cursor-pointer ↔ WebClaw bridge — cursor-pointer side plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add 4 HTTP endpoints (`POST /browser/enqueue`, `GET /browser/next-command`, `POST /browser/result`, `GET /browser/result/<id>`) plus an in-memory queue, plus an agent verb `browser <command>` that enqueues + polls for result.

**Architecture:** Mutex-protected `HashMap<String, …>` queue in `api.rs` with TTL eviction. Python agent `execute()` gains a new verb branch that talks to those endpoints via the existing `requests` session. No new dependencies.

**Tech Stack:** Rust (axum + tokio + uuid), Python 3.11 (requests).

**Spec:** [`docs/superpowers/specs/2026-05-17-cursor-pointer-webclaw-bridge-design.md`](../specs/2026-05-17-cursor-pointer-webclaw-bridge-design.md)

---

## Task 1: Rust browser queue + 4 endpoints

**Files:**
- Modify: `src-tauri/src/api.rs`
- Modify: `src-tauri/Cargo.toml` (add `uuid` crate)

- [ ] **Step 1: add `uuid` dependency**

In `src-tauri/Cargo.toml`, find the `[dependencies]` section and add (if not already present):

```toml
uuid = { version = "1", features = ["v4"] }
```

Then run:

```bash
cd /Users/liuzhixiong/coding-project/cursor-pointer/.claude/worktrees/<this-worktree>/src-tauri
cargo build 2>&1 | tail -5
```

Expected: build succeeds (uuid downloads + compiles).

- [ ] **Step 2: add browser queue state types**

In `src-tauri/src/api.rs`, find the existing `AppState` struct definition. Add new types ABOVE it:

```rust
#[derive(Clone, Serialize, Deserialize)]
pub struct BrowserCommand {
    pub id: String,
    pub command: String,
    pub enqueued_at: u64,
    pub expires_at: u64,
}

#[derive(Clone, Serialize, Deserialize)]
pub struct BrowserResult {
    pub id: String,
    pub ok: bool,
    pub output: String,
    pub posted_at: u64,
}

pub struct BrowserQueue {
    pub pending: Mutex<VecDeque<BrowserCommand>>,
    pub results: Mutex<HashMap<String, BrowserResult>>,
}

impl BrowserQueue {
    pub fn new() -> Self {
        Self {
            pending: Mutex::new(VecDeque::new()),
            results: Mutex::new(HashMap::new()),
        }
    }

    fn now() -> u64 {
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|d| d.as_secs())
            .unwrap_or(0)
    }

    pub fn enqueue(&self, command: String, timeout_seconds: u64) -> BrowserCommand {
        let now = Self::now();
        let cmd = BrowserCommand {
            id: uuid::Uuid::new_v4().to_string(),
            command,
            enqueued_at: now,
            expires_at: now + timeout_seconds,
        };
        // Evict stale entries first.
        let mut pending = self.pending.lock().unwrap();
        pending.retain(|c| c.expires_at > now);
        pending.push_back(cmd.clone());
        cmd
    }

    pub fn next(&self) -> Option<BrowserCommand> {
        let now = Self::now();
        let mut pending = self.pending.lock().unwrap();
        pending.retain(|c| c.expires_at > now);
        pending.pop_front()
    }

    pub fn store_result(&self, result: BrowserResult) {
        let mut results = self.results.lock().unwrap();
        // Evict results older than 60s.
        let cutoff = Self::now().saturating_sub(60);
        results.retain(|_, r| r.posted_at >= cutoff);
        results.insert(result.id.clone(), result);
    }

    pub fn status(&self, id: &str) -> serde_json::Value {
        let results = self.results.lock().unwrap();
        if let Some(r) = results.get(id) {
            return serde_json::json!({
                "status": "done",
                "ok": r.ok,
                "output": r.output,
            });
        }
        drop(results);
        let pending = self.pending.lock().unwrap();
        let now = Self::now();
        let in_pending = pending.iter().any(|c| c.id == id && c.expires_at > now);
        let expired = pending.iter().any(|c| c.id == id && c.expires_at <= now);
        if in_pending {
            serde_json::json!({ "status": "pending" })
        } else if expired {
            serde_json::json!({ "status": "expired" })
        } else {
            // ID we've never seen, or a long-finished result that already got evicted.
            serde_json::json!({ "status": "expired" })
        }
    }
}
```

Note: `VecDeque` and `HashMap` are already imported at the top of `api.rs` for the existing `FxQueue` — verify with `grep "use std::collections" src-tauri/src/api.rs`. If not present, add `use std::collections::{HashMap, VecDeque};` near the top.

- [ ] **Step 3: wire BrowserQueue into AppState**

Find the existing `AppState` struct (above the impl block, near the top of `api.rs`):

```rust
pub struct AppState {
    pub version: String,
    pub fx: Arc<FxQueue>,
    pub ocr: Arc<OcrState>,
    pub app: tauri::AppHandle,
}
```

Add a new field:

```rust
pub struct AppState {
    pub version: String,
    pub fx: Arc<FxQueue>,
    pub ocr: Arc<OcrState>,
    pub browser: Arc<BrowserQueue>,
    pub app: tauri::AppHandle,
}
```

Then find where `AppState` is constructed (search for `AppState {` — should be in `src-tauri/src/lib.rs`). Add `browser: Arc::new(api::BrowserQueue::new()),` to the struct literal. (You may also need to re-export `BrowserQueue` from `api.rs` — it's `pub` so as long as `lib.rs` uses `api::BrowserQueue`, it'll work.)

- [ ] **Step 4: add the 4 handler functions**

In `src-tauri/src/api.rs`, find a sensible spot (e.g. immediately before `// ----- clipboard` section that was added in the verb-expansion cycle). Add a new section:

```rust
// ----- browser bridge (poll-based ↔ WebClaw) -----

#[derive(Deserialize)]
struct EnqueueReq {
    command: String,
    #[serde(default = "default_timeout")]
    timeout_seconds: u64,
}

fn default_timeout() -> u64 { 30 }

async fn browser_enqueue(
    State(s): State<Arc<AppState>>,
    Json(b): Json<EnqueueReq>,
) -> Json<serde_json::Value> {
    let cmd = s.browser.enqueue(b.command, b.timeout_seconds);
    Json(serde_json::json!({
        "id": cmd.id,
        "expires_at": cmd.expires_at,
    }))
}

async fn browser_next_command(
    State(s): State<Arc<AppState>>,
) -> Json<serde_json::Value> {
    match s.browser.next() {
        Some(c) => Json(serde_json::json!({ "id": c.id, "command": c.command })),
        None => Json(serde_json::json!({})),
    }
}

#[derive(Deserialize)]
struct ResultReq {
    id: String,
    ok: bool,
    output: String,
}

async fn browser_result(
    State(s): State<Arc<AppState>>,
    Json(b): Json<ResultReq>,
) -> Json<serde_json::Value> {
    let now = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0);
    s.browser.store_result(BrowserResult {
        id: b.id,
        ok: b.ok,
        output: b.output,
        posted_at: now,
    });
    Json(serde_json::json!({ "ok": true }))
}

async fn browser_result_status(
    State(s): State<Arc<AppState>>,
    axum::extract::Path(id): axum::extract::Path<String>,
) -> Json<serde_json::Value> {
    Json(s.browser.status(&id))
}
```

- [ ] **Step 5: register routes**

Find the `.route("/clipboard/get", ...)` lines in `serve()`. Add IMMEDIATELY ABOVE them:

```rust
        .route("/browser/enqueue", post(browser_enqueue))
        .route("/browser/next-command", get(browser_next_command))
        .route("/browser/result", post(browser_result))
        .route("/browser/result/:id", get(browser_result_status))
```

- [ ] **Step 6: rebuild + reinstall .app**

```bash
pkill -f "CursorPointer.app/Contents/MacOS/cursor-pointer" 2>&1; sleep 1
cd /Users/liuzhixiong/coding-project/cursor-pointer/.claude/worktrees/<this-worktree>
npm run build 2>&1 | tail -3
rm -rf /Applications/CursorPointer.app
cp -R src-tauri/target/release/bundle/macos/CursorPointer.app /Applications/
open /Applications/CursorPointer.app
sleep 3
curl -s http://127.0.0.1:39213/health
```

Expected: build succeeds, /health returns ok.

NOTE: TCC permissions (Screen Recording, Accessibility, Input Monitoring) will be invalidated by the rebuild's new cdhash. That's a known cost — re-add per `docs/API.md` if needed.

- [ ] **Step 7: live round-trip test**

```bash
# enqueue
curl -s -X POST http://127.0.0.1:39213/browser/enqueue \
     -H "Content-Type: application/json" \
     -d '{"command":"test","timeout_seconds":30}'

# (capture the id from above)

# next-command should return the same
curl -s http://127.0.0.1:39213/browser/next-command

# next-command again should return {}
curl -s http://127.0.0.1:39213/browser/next-command

# post result
curl -s -X POST http://127.0.0.1:39213/browser/result \
     -H "Content-Type: application/json" \
     -d '{"id":"<the-id>","ok":true,"output":"hello"}'

# status should be done
curl -s http://127.0.0.1:39213/browser/result/<the-id>
```

Expected: enqueue returns `{"id":"...","expires_at":...}`. First next-command returns the command. Second is empty `{}`. Post result returns `{"ok":true}`. Status query returns `{"status":"done","ok":true,"output":"hello"}`.

- [ ] **Step 8: commit**

```bash
cd /Users/liuzhixiong/coding-project/cursor-pointer/.claude/worktrees/<this-worktree>
git add src-tauri/src/api.rs src-tauri/src/lib.rs src-tauri/Cargo.toml src-tauri/Cargo.lock
git commit -m "feat(api): add /browser/* endpoints + in-memory queue for WebClaw bridge"
```

---

## Task 2: Python client `browser` wrappers (TDD)

**Files:**
- Modify: `python-client/cursor_pointer/client.py`
- Modify: `python-client/tests/test_new_verbs.py` (append)

- [ ] **Step 1: append failing tests**

Append to `python-client/tests/test_new_verbs.py`:

```python
# ---------------------------------------------------------------------------
# CursorPointer client — browser bridge methods
# ---------------------------------------------------------------------------


def test_client_browser_enqueue_hits_correct_endpoint():
    from cursor_pointer import CursorPointer
    cp = CursorPointer()
    with patch.object(cp, "_post", return_value={"id": "abc", "expires_at": 123}) as p:
        result = cp.browser_enqueue("test cmd", timeout_seconds=30)
    p.assert_called_once_with("/browser/enqueue", {"command": "test cmd", "timeout_seconds": 30})
    assert result["id"] == "abc"


def test_client_browser_result_status_hits_correct_endpoint():
    from cursor_pointer import CursorPointer
    cp = CursorPointer()
    with patch.object(cp, "_get", return_value={"status": "done", "ok": True, "output": "x"}) as g:
        result = cp.browser_result_status("abc")
    g.assert_called_once_with("/browser/result/abc")
    assert result["status"] == "done"
```

- [ ] **Step 2: run, expect AttributeError**

```bash
cd /Users/liuzhixiong/coding-project/cursor-pointer/.claude/worktrees/<this-worktree>/python-client
/Users/liuzhixiong/coding-project/cursor-pointer/python-client/.venv/bin/pytest tests/test_new_verbs.py -v -k browser
```

Expected: 2 fail.

- [ ] **Step 3: add methods to `client.py`**

In `python-client/cursor_pointer/client.py`, find the existing `def clipboard_set(self, text: str) -> None:` method. Add directly BELOW it:

```python
    # ----- browser bridge -----

    def browser_enqueue(self, command: str, timeout_seconds: int = 30) -> dict:
        return self._post("/browser/enqueue",
                          {"command": command, "timeout_seconds": timeout_seconds})

    def browser_result_status(self, cmd_id: str) -> dict:
        return self._get(f"/browser/result/{cmd_id}")
```

- [ ] **Step 4: run, expect 2 PASSED + regression**

```bash
cd /Users/liuzhixiong/coding-project/cursor-pointer/.claude/worktrees/<this-worktree>/python-client
/Users/liuzhixiong/coding-project/cursor-pointer/python-client/.venv/bin/pytest tests/ -v
```

Expected: 57 PASSED (55 prior + 2 new).

- [ ] **Step 5: commit**

```bash
cd /Users/liuzhixiong/coding-project/cursor-pointer/.claude/worktrees/<this-worktree>
git add python-client/cursor_pointer/client.py python-client/tests/test_new_verbs.py
git commit -m "feat(client): add browser_enqueue / browser_result_status (TDD)"
```

---

## Task 3: agent `browser` verb (TDD)

**Files:**
- Modify: `python-client/tools/run_agent.py`
- Modify: `python-client/tests/test_new_verbs.py` (append)

- [ ] **Step 1: extend ACTION_RE**

In `python-client/tools/run_agent.py`, find:

```python
    r"(?P<verb>scroll_to|scroll|click|dclick|rclick|drag|app|clipboard|shell|type|key|done|wait)"
```

Add `browser` to the alternation (anywhere is fine; tail is fine):

```python
    r"(?P<verb>scroll_to|scroll|click|dclick|rclick|drag|app|clipboard|shell|browser|type|key|done|wait)"
```

- [ ] **Step 2: append failing tests**

```python
# ---------------------------------------------------------------------------
# browser verb (bridge to WebClaw)
# ---------------------------------------------------------------------------


def test_browser_verb_enqueues_polls_and_returns():
    """Happy path: enqueue → poll once → result is done → history gets the output."""
    mock_cp = MagicMock()
    mock_cp.browser_enqueue.return_value = {"id": "abc", "expires_at": 999}
    mock_cp.browser_result_status.return_value = {
        "status": "done", "ok": True, "output": "page title is X"
    }
    with patch("run_agent.CursorPointer", return_value=mock_cp), \
         patch("run_agent.time.sleep"), \
         patch("run_agent.history", []) as fake_hist:
        result = execute('browser "what is the page title?"', boxes=[])
    assert result is None
    mock_cp.browser_enqueue.assert_called_once()
    enq_args = mock_cp.browser_enqueue.call_args
    assert "what is the page title?" in enq_args.kwargs.get("command", "") or \
           "what is the page title?" in (enq_args.args[0] if enq_args.args else "")
    assert any("browser" in h and "page title is X" in h for h in fake_hist)


def test_browser_verb_expired_returns_error():
    mock_cp = MagicMock()
    mock_cp.browser_enqueue.return_value = {"id": "abc", "expires_at": 0}
    mock_cp.browser_result_status.return_value = {"status": "expired"}
    with patch("run_agent.CursorPointer", return_value=mock_cp), \
         patch("run_agent.time.sleep"):
        result = execute('browser "something"', boxes=[])
    assert result is not None
    assert "expired" in result.lower() or "webclaw" in result.lower()


def test_browser_verb_pending_then_done():
    """First poll returns pending, second returns done."""
    mock_cp = MagicMock()
    mock_cp.browser_enqueue.return_value = {"id": "abc", "expires_at": 999}
    mock_cp.browser_result_status.side_effect = [
        {"status": "pending"},
        {"status": "done", "ok": True, "output": "done payload"},
    ]
    with patch("run_agent.CursorPointer", return_value=mock_cp), \
         patch("run_agent.time.sleep"), \
         patch("run_agent.history", []):
        result = execute('browser "x"', boxes=[])
    assert result is None
    assert mock_cp.browser_result_status.call_count == 2


def test_browser_verb_failed_result_returns_error():
    """ok:false from WebClaw surfaces as a verb error string."""
    mock_cp = MagicMock()
    mock_cp.browser_enqueue.return_value = {"id": "abc", "expires_at": 999}
    mock_cp.browser_result_status.return_value = {
        "status": "done", "ok": False, "output": "DOM query failed"
    }
    with patch("run_agent.CursorPointer", return_value=mock_cp), \
         patch("run_agent.time.sleep"):
        result = execute('browser "bad selector"', boxes=[])
    assert result is not None
    assert "DOM query failed" in result
```

- [ ] **Step 3: run, expect 4 fail**

```bash
/Users/liuzhixiong/coding-project/cursor-pointer/python-client/.venv/bin/pytest tests/test_new_verbs.py -v -k browser
```

Expected: 2 prior `browser` tests pass, 4 new fail with `unknown verb 'browser'`.

- [ ] **Step 4: implement the `browser` verb branch**

In `python-client/tools/run_agent.py`, find the `if verb == "shell":` block. After its closing `return None`, add a new branch:

```python
    if verb == "browser":
        # Extract the quoted command. ACTION_RE's `arg` only catches digits/quoted
        # strings; we want everything after the literal "browser" token.
        idx = action_str.lower().find("browser")
        rest = action_str[idx + 7:].strip() if idx >= 0 else ""
        # Strip outer quotes if present
        m = re.search(r'"([^"]*)"?', rest)
        cmd_text = m.group(1) if m else rest.strip()
        if not cmd_text:
            return "browser needs a quoted command, e.g. browser \"what is the title?\""

        try:
            enq = cp.browser_enqueue(cmd_text, timeout_seconds=30)
        except Exception as e:
            return f"browser enqueue failed: {e}"
        cmd_id = enq.get("id")
        if not cmd_id:
            return f"browser enqueue returned no id: {enq!r}"

        deadline = time.time() + 35
        while time.time() < deadline:
            try:
                st = cp.browser_result_status(cmd_id)
            except Exception as e:
                return f"browser result poll failed: {e}"
            status = st.get("status")
            if status == "done":
                output = (st.get("output") or "")[:200]
                if not st.get("ok"):
                    return f"browser failed: {output}"
                history.append(f"browser {cmd_text[:40]!r} → {output!r}")
                return None
            if status == "expired":
                return ("browser command expired (no WebClaw client polling? "
                        "enable Remote Control in WebClaw sidepanel)")
            time.sleep(0.5)
        return "browser timed out waiting for WebClaw"
```

- [ ] **Step 5: run, expect 61 PASSED**

```bash
/Users/liuzhixiong/coding-project/cursor-pointer/python-client/.venv/bin/pytest tests/ -v
```

Expected: 61 PASSED (55 baseline + 2 client + 4 browser verb tests = 61).

- [ ] **Step 6: SYSTEM_PROMPT addition**

In `python-client/tools/run_agent.py`, find the SYSTEM_PROMPT verb listing. After the line:

```
        shell <cmd>          # 仅限只读命令...
```

Add:

```
        browser "<task>"     # 委托 WebClaw 在浏览器里执行（需 WebClaw 启用 Remote Control）
```

- [ ] **Step 7: commit**

```bash
cd /Users/liuzhixiong/coding-project/cursor-pointer/.claude/worktrees/<this-worktree>
git add python-client/tools/run_agent.py python-client/tests/test_new_verbs.py
git commit -m "feat(agent): add browser verb — delegate browser tasks to WebClaw (TDD)"
```

---

## Task 4: smoke matrix + docs

**Files:**
- Modify: `scripts/smoke_test_api.py`
- Modify: `docs/API.md`

- [ ] **Step 1: extend smoke test**

In `scripts/smoke_test_api.py`, add a new test function before the `# --- run all ---` block:

```python
def t_browser_enqueue_next_result_roundtrip() -> None:
    """Full bridge round-trip without WebClaw — we play both sides."""
    enq = post("/browser/enqueue",
               {"command": "smoke-test", "timeout_seconds": 10}).json()
    cmd_id = enq.get("id")
    nxt = get("/browser/next-command").json()
    pulled_id = nxt.get("id")
    post("/browser/result",
         {"id": cmd_id, "ok": True, "output": "smoke-test-output"})
    final = get(f"/browser/result/{cmd_id}").json()
    ok = (cmd_id == pulled_id and final.get("status") == "done"
          and final.get("output") == "smoke-test-output")
    record("/browser/* round-trip", PASS if ok else FAIL,
           f"enq_id={cmd_id} pulled={pulled_id} final={final.get('status')}",
           "enqueue → next → result → status")
```

Register in the `tests = [...]` list.

- [ ] **Step 2: docs/API.md update**

In `docs/API.md`, find a sensible spot (after the OCR section). Add:

```markdown
---

## Browser bridge (cursor-pointer ↔ WebClaw)

`POST /browser/enqueue` `{"command": "...", "timeout_seconds": 30}` → `{"id": "...", "expires_at": ...}`
`GET /browser/next-command` → `{"id": "...", "command": "..."}` or `{}`
`POST /browser/result` `{"id": "...", "ok": true, "output": "..."}` → `{"ok": true}`
`GET /browser/result/<id>` → `{"status": "pending" | "done" | "expired", ...}`

The agent's `browser "<task>"` verb enqueues, polls, returns the WebClaw
output into history. WebClaw must have Remote Control enabled in its
sidepanel; otherwise commands expire after their timeout_seconds.
```

- [ ] **Step 3: run smoke test live**

```bash
python3 /Users/liuzhixiong/coding-project/cursor-pointer/.claude/worktrees/<this-worktree>/scripts/smoke_test_api.py 2>&1 | tail -5
```

Expected: matrix is 23 pass · 0 fail · 1 skip (was 22; added the new round-trip).

- [ ] **Step 4: commit**

```bash
cd /Users/liuzhixiong/coding-project/cursor-pointer/.claude/worktrees/<this-worktree>
git add scripts/smoke_test_api.py docs/API.md
git commit -m "docs+test: /browser/* round-trip in smoke matrix + API docs"
```

---

## Self-Review Notes

- **Spec coverage:** 4 endpoints (Task 1), Python client wrappers (Task 2), agent verb (Task 3), smoke + docs (Task 4). WebClaw side is its own plan in the other repo.
- **No placeholders:** every step has exact code or exact commands.
- **Type consistency:** `BrowserCommand` / `BrowserResult` / `BrowserQueue` named identically Rust-side; `browser_enqueue` / `browser_result_status` named identically Python-side. The verb is `browser` everywhere.
- **TCC caveat:** Task 1 Step 6 rebuilds the .app → cdhash changes → permissions may need re-granting. Documented in spec / docs/API.md.
- **Rollback:** reverting Task 1's commit removes the endpoints; the agent's `browser` verb returns a graceful enqueue-failed error string after that.
