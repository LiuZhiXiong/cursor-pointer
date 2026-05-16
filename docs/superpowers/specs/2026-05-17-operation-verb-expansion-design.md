# Operation verb expansion — design

**Date:** 2026-05-17
**Author:** brainstorming session with @liuzhixiong
**Status:** approved → ready for implementation plan

## Problem

The agent's current verb set is `click | dclick | rclick | scroll | scroll_to | type | key | done | wait`. That's enough to drive a single-window task, but real automation needs four more capabilities the VLM cannot synthesize from existing primitives:

| Missing | Why we need it |
|---|---|
| `drag` | playlists, settings sliders, file rearranging — none reachable by click |
| `app` | switching to or launching a different application by name |
| `clipboard` | cross-app copy-paste; the only sane way to ferry text between apps |
| `shell` | read-only system inspection (`ls`, `cat`, `pwd`, …) that the AX tree can't answer |

## Goal

Add the four verbs to `run_agent.py`, plus the two cursor-pointer HTTP endpoints that `clipboard` depends on. Each verb should follow the same shape as today's existing verbs (parsed by `ACTION_RE`, dispatched by `execute()`, tested in `tests/`).

## Non-goals

- A hotkey/system-shortcut verb — `key cmd+space` already triggers Spotlight; `key cmd+tab` already cycles apps. Aliasing those would be cosmetic, not capability.
- Image/HTML clipboard support — text only.
- Drag with intermediate waypoints, modifier keys, or velocity control.
- A `shell` blocklist or per-call confirmation — a strict whitelist is simpler and tighter.

## Decisions (locked during brainstorming)

| Decision | Choice |
|---|---|
| Scope of this spec | 4 verbs: drag / app / clipboard / shell |
| Hotkey verb | dropped — covered by existing `key` |
| Clipboard format | plain text only |
| Shell safety policy | hard whitelist of read-only commands |

## Architecture

```
agent verb           → cursor-pointer HTTP        → macOS primitive
─────────────────────  ─────────────────────────   ────────────────────
drag from to         → mouse_down + move + up      enigo CGEvent
app <name>           → (none)                      osascript activate
clipboard read       → GET /clipboard/get          pbpaste / NSPasteboard
clipboard write "X"  → POST /clipboard/set         pbcopy / NSPasteboard
shell <cmd>          → (none)                      subprocess.run (whitelisted)
```

`drag` and `shell` and `app` need no new cursor-pointer endpoint — they compose existing ones (`drag`) or call into Python's `subprocess` (`app`, `shell`). Only `clipboard` requires net-new Rust handlers because Python can't directly read macOS's pasteboard without PyObjC, and the agent should treat cursor-pointer as the platform façade.

## Components

### Rust side — `src-tauri/src/`

**New input helpers (`input.rs`):**

```rust
pub fn clipboard_get() -> Result<String> {
    // Shell out to pbpaste — zero new deps, available on every Mac.
    let out = std::process::Command::new("/usr/bin/pbpaste").output()
        .map_err(|e| InputError::Op(e.to_string()))?;
    Ok(String::from_utf8_lossy(&out.stdout).to_string())
}

pub fn clipboard_set(text: &str) -> Result<()> {
    let mut child = std::process::Command::new("/usr/bin/pbcopy")
        .stdin(std::process::Stdio::piped())
        .spawn()
        .map_err(|e| InputError::Op(e.to_string()))?;
    use std::io::Write;
    child.stdin.as_mut().unwrap().write_all(text.as_bytes())
        .map_err(|e| InputError::Op(e.to_string()))?;
    child.wait().map_err(|e| InputError::Op(e.to_string()))?;
    Ok(())
}
```

`pbcopy` and `pbpaste` are macOS builtins. No new crate dependency.

**New HTTP handlers (`api.rs`):**

```rust
async fn clipboard_get() -> ApiResult<serde_json::Value> {
    let text = run_blocking_input(input::clipboard_get).await?;
    Ok(Json(serde_json::json!({ "text": text })))
}

#[derive(Deserialize)]
struct ClipboardReq { text: String }

async fn clipboard_set(Json(b): Json<ClipboardReq>) -> ApiResult<serde_json::Value> {
    let text = b.text.clone();
    run_blocking_input(move || input::clipboard_set(&text)).await?;
    Ok(Json(serde_json::json!({ "ok": true })))
}
```

**Routes:**

```rust
.route("/clipboard/get", get(clipboard_get))
.route("/clipboard/set", post(clipboard_set))
```

### Python client — `cursor_pointer/client.py`

Two thin wrappers:

```python
def clipboard_get(self) -> str:
    return self._get("/clipboard/get")["text"]

def clipboard_set(self, text: str) -> None:
    self._post("/clipboard/set", {"text": text})
```

### Agent — `python-client/tools/run_agent.py`

**ACTION_RE update:**

```python
ACTION_RE = re.compile(
    r"(?ix)"
    r"(?:^|\b)"
    r"(?P<verb>scroll_to|scroll|click|dclick|rclick|drag|app|clipboard|shell|type|key|done|wait)"
    r"\b\s*"
    r"(?P<arg>up|down|left|right|read|write|\d+|\".+?\")?",
)
```

The arg group adds `read|write` for clipboard's two sub-commands.

**New verb handlers in `execute()`:**

```python
SHELL_WHITELIST = {
    "ls", "cat", "echo", "pwd", "which",
    "head", "tail", "grep", "find", "file",
    "wc", "date", "hostname", "whoami",
}


def _parse_drag(action_str: str) -> tuple[int | None, int | None]:
    """Parse 'drag <from_id> to <to_id>'. Returns (from, to) or (None, None)."""
    m = re.search(r"drag\s+(\d+)\s+to\s+(\d+)", action_str, re.IGNORECASE)
    if not m:
        return None, None
    return int(m.group(1)), int(m.group(2))


def _shell_first_token(action_str: str) -> tuple[str, str]:
    """Strip the leading `shell` token, return (head, full_cmd)."""
    after = action_str[action_str.lower().find("shell") + 5:].strip()
    head = after.split()[0] if after else ""
    return head, after


if verb == "drag":
    f, t = _parse_drag(action_str)
    if f is None:
        return f"drag needs 'from to' ids, got {action_str!r}"
    el_from = next((b for b in boxes if b["id"] == f), None)
    el_to = next((b for b in boxes if b["id"] == t), None)
    if not el_from or not el_to:
        return f"drag: bad id(s) {f}/{t}"
    fx, fy = el_from["x"] + el_from["w"] // 2, el_from["y"] + el_from["h"] // 2
    tx, ty = el_to["x"] + el_to["w"] // 2, el_to["y"] + el_to["h"] // 2
    # cp.drag handles move→down→move→up internally; we only add a small
    # dwell before each phase so Electron apps have time to register the
    # press (some app drag handlers debounce sub-frame mouse_down events).
    cp.move(fx, fy)
    time.sleep(0.2)
    cp.drag(from_xy=(fx, fy), to_xy=(tx, ty))
    return None

if verb == "app":
    name = (arg or "").strip('"')
    if not name:
        # `app` takes a free-text name; ACTION_RE's arg only catches quoted/digit
        rest = action_str[action_str.lower().find("app") + 3:].strip()
        name = rest.strip('"\' ')
    if not name:
        return "app needs <name>"
    try:
        subprocess.run(
            ["osascript", "-e", f'tell application "{name}" to activate'],
            capture_output=True, timeout=5, check=True,
        )
        return None
    except subprocess.CalledProcessError as e:
        return f"app activate failed: {e.stderr.decode()[:80]}"

if verb == "clipboard":
    sub = (arg or "").lower().strip('"')
    if sub == "read":
        text = cp.clipboard_get()
        history.append(f"clipboard read → {text[:80]!r}")
        return None
    if sub == "write":
        # extract quoted text after "write"
        m = re.search(r'write\s+"([^"]*)"', action_str, re.IGNORECASE)
        text = m.group(1) if m else ""
        if not text:
            return "clipboard write needs quoted text"
        cp.clipboard_set(text)
        return None
    return f"clipboard needs 'read' or 'write \"...\"', got {sub!r}"

if verb == "shell":
    head, cmd = _shell_first_token(action_str)
    if head not in SHELL_WHITELIST:
        return f"shell command {head!r} not in whitelist {sorted(SHELL_WHITELIST)}"
    try:
        out = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=8,
        )
        result = out.stdout[:200]
        history.append(f"shell {head!r} → {result!r}")
        return None
    except subprocess.TimeoutExpired:
        return f"shell {head!r} timed out (8s)"
```

Note: `history` and `cp` are already in scope inside `execute()`. We treat clipboard-read and shell as side-effect-bearing verbs whose result lands in `history` so the next-step prompt sees what the agent learned.

### SYSTEM_PROMPT — additions

```
        drag <id1> to <id2>  # 拖拽：从元素1拖到元素2
        app <name>           # 启动或切换到应用（如 NeteaseMusic / Finder / Safari）
        clipboard read       # 读当前剪贴板，结果会出现在历史里
        clipboard write "<text>"  # 写入剪贴板
        shell <cmd>          # 仅限只读命令：ls/cat/echo/pwd/head/tail/grep/find/wc/date 等
```

Plus a hint:

> 跨 app 复制粘贴：`clipboard write "xxx"` → `app <target>` → `click <target_input>` → `key cmd+v`。

## Testing

### Python unit tests (extend `tests/test_verify_done.py` or new file)

| Test | What it asserts |
|---|---|
| `test_parse_drag_basic` | `_parse_drag("drag 5 to 9")` → `(5, 9)` |
| `test_parse_drag_extra_words` | `_parse_drag("drag 5 to 9 quickly")` still returns `(5, 9)` |
| `test_parse_drag_missing_to` | `_parse_drag("drag 5 9")` returns `(None, None)` |
| `test_shell_whitelist_accepts` | `execute("shell ls -la", boxes=[])` calls subprocess; returns None |
| `test_shell_whitelist_rejects` | `execute("shell rm /", boxes=[])` returns error string starting with "shell command" |
| `test_clipboard_read_dispatches` | mock `cp.clipboard_get` → `execute("clipboard read", …)` appends to history |
| `test_clipboard_write_extracts_quoted` | `execute('clipboard write "hello"', …)` calls `cp.clipboard_set("hello")` |
| `test_app_activate_calls_osascript` | patch `subprocess.run` → verb invokes osascript with the right script |

### Rust-side smoke test (extend `scripts/smoke_test_api.py`)

Add two endpoints to the matrix:
- `GET /clipboard/get` → 200, returns `{"text": "..."}`
- `POST /clipboard/set` with `{"text": "smoke-test-token"}` → 200, then GET round-trips the same string

Target: matrix becomes 23/23 pass.

## Error handling

| Failure | Handling |
|---|---|
| `drag` with one bad id | execute returns `"drag: bad id(s) X/Y"` — surfaces as failed step, agent tries again |
| `app <name>` for non-existent app | osascript exits non-zero → return error string with stderr snippet |
| `clipboard set` with empty quoted text | return `"clipboard write needs quoted text"` rather than wipe clipboard |
| `shell <cmd>` not in whitelist | return error listing the whitelist — the VLM learns its options |
| `shell` command times out | return timeout error; do not block the agent step indefinitely |
| `pbcopy/pbpaste` exit non-zero | propagated as `InputError::Op` from Rust → 500 to Python → caught by `_retry` |

## Observability

- Each new verb logs through the existing `_log()` channel with a `→` prefix matching today's `→ AXPress …` / `→ scroll anchor …` style.
- `shell` and `clipboard read` results go into `history` so the next-step prompt sees what the agent learned. This is the whole point of read verbs: feed the worker context for the next decision.

## Scope estimate

| Layer | Approx LOC |
|---|---|
| Rust (`input.rs` + `api.rs`) | ~40 |
| Python client (`client.py`) | ~10 |
| Agent (`run_agent.py`) | ~90 |
| SYSTEM_PROMPT additions | ~6 |
| Tests | ~120 |
| Total | ~270 |

No new Python or Rust dependencies.

## Roll-back

Each verb is independent. If `shell` proves too dangerous, removing the
single `if verb == "shell":` branch (and the SHELL_WHITELIST constant)
disables it without affecting the other three. The clipboard endpoints
are pure additions — leaving them in but unused is harmless.

## Open questions (deferred)

- Should `shell` runs go through cursor-pointer's HTTP API for parity with mouse/keyboard? — No. Local subprocess is simpler and we already accept that the agent runs arbitrary Python. Adding HTTP-shell would expand cursor-pointer's attack surface for zero benefit.
- Should `app <name>` support bundle ID fallback for apps whose display name doesn't match? — Defer. `osascript activate` accepts both bundle IDs and display names; if VLM picks the wrong identifier we'll iterate after seeing real failures.
- Should `clipboard` track a per-step diff so the agent notices clipboard contents changing? — Defer. Not needed for the listed cross-app paste workflows.
