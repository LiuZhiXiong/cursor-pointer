# Operation Verb Expansion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add four new agent verbs — `drag`, `app`, `clipboard read|write`, `shell <whitelisted-cmd>` — plus the two cursor-pointer HTTP endpoints (`/clipboard/get`, `/clipboard/set`) that `clipboard` requires.

**Architecture:** Pure additions. `drag` composes existing mouse primitives via the already-implemented `cp.drag()` Python helper. `app` and `shell` are local Python subprocess calls. `clipboard` requires net-new Rust handlers that shell out to `pbcopy`/`pbpaste`. Each verb follows the existing `execute()` dispatcher pattern in `run_agent.py`. `shell` is gated by a hardcoded whitelist of read-only commands.

**Tech Stack:** Rust (axum + tokio) + Python (subprocess, regex, pytest). No new dependencies on either side.

**Spec:** [`docs/superpowers/specs/2026-05-17-operation-verb-expansion-design.md`](../specs/2026-05-17-operation-verb-expansion-design.md)

---

## File Structure

| File | Role | Change |
|---|---|---|
| `src-tauri/src/input.rs` | macOS input primitives | add `clipboard_get` + `clipboard_set` |
| `src-tauri/src/api.rs` | HTTP routes & handlers | add `clipboard_get` + `clipboard_set` handlers + route registrations |
| `python-client/cursor_pointer/client.py` | typed HTTP client | add `clipboard_get` + `clipboard_set` methods |
| `python-client/tools/run_agent.py` | agent action loop | extend `ACTION_RE`, add 4 verb branches in `execute()`, add `SHELL_WHITELIST` + `_parse_drag` helper, update `SYSTEM_PROMPT` |
| `python-client/tests/test_new_verbs.py` | unit tests for new verbs | create with 8 tests |
| `scripts/smoke_test_api.py` | end-to-end API matrix | add 2 clipboard endpoint cases (matrix grows 21 → 23) |

---

## Task 1: cursor-pointer Rust — clipboard endpoints

**Files:**
- Modify: `src-tauri/src/input.rs` (add `clipboard_get` / `clipboard_set`)
- Modify: `src-tauri/src/api.rs` (handlers + route registrations)

This is a Rust-only task. We can't TDD this against pytest, so verify via a live cursor-pointer rebuild and `curl` round-trip.

- [ ] **Step 1: add input helpers to `input.rs`**

Find the bottom of `src-tauri/src/input.rs` (after `pub fn key_toggle` or `pub fn key_press`). Append:

```rust
pub fn clipboard_get() -> Result<String> {
    let out = std::process::Command::new("/usr/bin/pbpaste")
        .output()
        .map_err(|e| InputError::Op(format!("pbpaste spawn: {}", e)))?;
    if !out.status.success() {
        return Err(InputError::Op(format!(
            "pbpaste exited {}: {}",
            out.status,
            String::from_utf8_lossy(&out.stderr).trim()
        )));
    }
    Ok(String::from_utf8_lossy(&out.stdout).to_string())
}

pub fn clipboard_set(text: &str) -> Result<()> {
    use std::io::Write;
    let mut child = std::process::Command::new("/usr/bin/pbcopy")
        .stdin(std::process::Stdio::piped())
        .spawn()
        .map_err(|e| InputError::Op(format!("pbcopy spawn: {}", e)))?;
    child
        .stdin
        .as_mut()
        .ok_or_else(|| InputError::Op("pbcopy stdin missing".into()))?
        .write_all(text.as_bytes())
        .map_err(|e| InputError::Op(format!("pbcopy write: {}", e)))?;
    let status = child
        .wait()
        .map_err(|e| InputError::Op(format!("pbcopy wait: {}", e)))?;
    if !status.success() {
        return Err(InputError::Op(format!("pbcopy exited {}", status)));
    }
    Ok(())
}
```

- [ ] **Step 2: add handler + request struct to `api.rs`**

Find `async fn screencapture_native` in `src-tauri/src/api.rs` (it's near the bottom of the file, around line 520). Add a new section just before it:

```rust
// ----- clipboard ---------------------------------------------------------

#[derive(Deserialize)]
struct ClipboardSetReq {
    text: String,
}

async fn clipboard_get() -> ApiResult<serde_json::Value> {
    let text = run_blocking_input(input::clipboard_get).await?;
    Ok(Json(serde_json::json!({ "text": text })))
}

async fn clipboard_set(Json(b): Json<ClipboardSetReq>) -> ApiResult<serde_json::Value> {
    let text = b.text.clone();
    run_blocking_input(move || input::clipboard_set(&text)).await?;
    Ok(Json(serde_json::json!({ "ok": true })))
}
```

- [ ] **Step 3: register routes**

In `src-tauri/src/api.rs`, find the `.route("/ocr/run", post(ocr_run))` line in the `serve()` function (around line 576). Add two new routes immediately above it:

```rust
        .route("/clipboard/get", get(clipboard_get))
        .route("/clipboard/set", post(clipboard_set))
```

- [ ] **Step 4: rebuild cursor-pointer**

Stop any running cursor-pointer first:

```bash
pkill -f "CursorPointer.app/Contents/MacOS/cursor-pointer" 2>&1; sleep 1
pkill -f "target/debug/cursor-pointer" 2>&1; sleep 1
```

Then rebuild + reinstall the release `.app` so existing Screen Recording / Accessibility grants stay valid:

```bash
cd /Users/liuzhixiong/coding-project/cursor-pointer
npm run build 2>&1 | tail -3
```

Expected output ends with: `Finished 2 bundles at: ... CursorPointer.app ... CursorPointer_0.1.0_aarch64.dmg`.

Reinstall:

```bash
rm -rf /Applications/CursorPointer.app
cp -R src-tauri/target/release/bundle/macos/CursorPointer.app /Applications/
open /Applications/CursorPointer.app
sleep 3
curl -s http://127.0.0.1:39213/health
```

Expected: `{"ok":true,...}`.

Note: macOS TCC binds permissions to cdhash, so the new build may invalidate
the Screen Recording / Accessibility grants — that's fine for this task
because clipboard endpoints don't need either of those permissions, only
the AX/Screen Recording grants from the previous feature work. If unit
tests later complain, fix per the recipe in `docs/API.md` ("Permissions").

- [ ] **Step 5: live round-trip test**

```bash
# Write
curl -s -X POST http://127.0.0.1:39213/clipboard/set \
     -H "Content-Type: application/json" \
     -d '{"text":"cursor-pointer-smoke-test"}'

# Read it back
curl -s http://127.0.0.1:39213/clipboard/get
```

Expected:
- POST returns `{"ok":true}`
- GET returns `{"text":"cursor-pointer-smoke-test"}`

If POST or GET returns 500, inspect `Console.app` for the `cursor-pointer` process or re-run `npm run build` and check for compilation errors above.

- [ ] **Step 6: commit**

```bash
cd /Users/liuzhixiong/coding-project/cursor-pointer
git add src-tauri/src/input.rs src-tauri/src/api.rs
git commit -m "feat(api): add /clipboard/get and /clipboard/set endpoints"
```

---

## Task 2: Python client — `clipboard_get` / `clipboard_set`

**Files:**
- Modify: `python-client/cursor_pointer/client.py` (add two methods)
- Test: `python-client/tests/test_new_verbs.py` (create; first 2 tests)

- [ ] **Step 1: create the failing tests**

Create `python-client/tests/test_new_verbs.py`:

```python
"""Tests for the new agent verbs and their client-level helpers."""
from __future__ import annotations

from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# CursorPointer client — clipboard methods
# ---------------------------------------------------------------------------

def test_client_clipboard_get_hits_correct_endpoint():
    from cursor_pointer import CursorPointer
    cp = CursorPointer()
    with patch.object(cp, "_get", return_value={"text": "hello"}) as g:
        result = cp.clipboard_get()
    g.assert_called_once_with("/clipboard/get")
    assert result == "hello"


def test_client_clipboard_set_hits_correct_endpoint():
    from cursor_pointer import CursorPointer
    cp = CursorPointer()
    with patch.object(cp, "_post", return_value={"ok": True}) as p:
        cp.clipboard_set("test value")
    p.assert_called_once_with("/clipboard/set", {"text": "test value"})
```

- [ ] **Step 2: run tests, expect AttributeError on `clipboard_get`**

```bash
cd /Users/liuzhixiong/coding-project/cursor-pointer/python-client
/Users/liuzhixiong/coding-project/cursor-pointer/python-client/.venv/bin/pytest tests/test_new_verbs.py -v
```

Expected: 2 FAILED with `AttributeError: 'CursorPointer' object has no attribute 'clipboard_get'`.

- [ ] **Step 3: add methods to `client.py`**

In `python-client/cursor_pointer/client.py`, find the `def scroll(` method. Add two new methods directly above `def scroll(`:

```python
    def clipboard_get(self) -> str:
        return self._get("/clipboard/get")["text"]

    def clipboard_set(self, text: str) -> None:
        self._post("/clipboard/set", {"text": text})

```

- [ ] **Step 4: run tests, expect 2 PASSED**

```bash
cd /Users/liuzhixiong/coding-project/cursor-pointer/python-client
/Users/liuzhixiong/coding-project/cursor-pointer/python-client/.venv/bin/pytest tests/test_new_verbs.py -v
```

Expected: 2 PASSED.

- [ ] **Step 5: commit**

```bash
cd /Users/liuzhixiong/coding-project/cursor-pointer
git add python-client/cursor_pointer/client.py python-client/tests/test_new_verbs.py
git commit -m "feat(client): add clipboard_get / clipboard_set wrappers (TDD)"
```

---

## Task 3: Agent — extend `ACTION_RE` regex

**Files:**
- Modify: `python-client/tools/run_agent.py` (extend `ACTION_RE` only)
- Test: `python-client/tests/test_new_verbs.py` (append)

- [ ] **Step 1: append failing parser tests**

Append to `python-client/tests/test_new_verbs.py`:

```python
# ---------------------------------------------------------------------------
# ACTION_RE — recognize the new verbs
# ---------------------------------------------------------------------------

from run_agent import ACTION_RE


def test_action_re_recognizes_drag():
    m = ACTION_RE.search("drag 5 to 9")
    assert m is not None
    assert m["verb"].lower() == "drag"


def test_action_re_recognizes_app():
    m = ACTION_RE.search("app NeteaseMusic")
    assert m is not None
    assert m["verb"].lower() == "app"


def test_action_re_recognizes_clipboard_read():
    m = ACTION_RE.search("clipboard read")
    assert m is not None
    assert m["verb"].lower() == "clipboard"
    assert m["arg"] == "read"


def test_action_re_recognizes_clipboard_write():
    m = ACTION_RE.search('clipboard write "hello"')
    assert m is not None
    assert m["verb"].lower() == "clipboard"


def test_action_re_recognizes_shell():
    m = ACTION_RE.search("shell ls -la")
    assert m is not None
    assert m["verb"].lower() == "shell"


def test_action_re_still_recognizes_existing_click():
    """Don't break existing verbs."""
    m = ACTION_RE.search("click 7")
    assert m["verb"].lower() == "click"
    assert m["arg"] == "7"
```

- [ ] **Step 2: run tests, expect failures**

```bash
cd /Users/liuzhixiong/coding-project/cursor-pointer/python-client
/Users/liuzhixiong/coding-project/cursor-pointer/python-client/.venv/bin/pytest tests/test_new_verbs.py -v
```

Expected: 2 prior tests pass (clipboard client), 6 new fail because the verbs aren't in the regex yet.

- [ ] **Step 3: update `ACTION_RE`**

In `python-client/tools/run_agent.py`, find the existing `ACTION_RE = re.compile(` block (around line 771). The current verb alternation is:

```python
    r"(?P<verb>scroll_to|scroll|click|dclick|rclick|type|key|done|wait)"
```

Replace with:

```python
    r"(?P<verb>scroll_to|scroll|click|dclick|rclick|drag|app|clipboard|shell|type|key|done|wait)"
```

And the existing arg alternation is:

```python
    r"(?P<arg>up|down|left|right|\d+|\".+?\")?"
```

Replace with:

```python
    r"(?P<arg>up|down|left|right|read|write|\d+|\".+?\")?"
```

(`read|write` lets ACTION_RE capture clipboard sub-commands as the arg group.)

- [ ] **Step 4: run tests, expect 8 PASSED**

```bash
cd /Users/liuzhixiong/coding-project/cursor-pointer/python-client
/Users/liuzhixiong/coding-project/cursor-pointer/python-client/.venv/bin/pytest tests/test_new_verbs.py -v
```

Expected: 8 PASSED (2 client + 6 parser).

- [ ] **Step 5: regression — existing verify_done tests still pass**

```bash
/Users/liuzhixiong/coding-project/cursor-pointer/python-client/.venv/bin/pytest tests/ -v
```

Expected: 17 PASSED (9 existing + 8 new). If any of the original 9 verify_done tests fails, the regex change broke them — revert and reconsider.

- [ ] **Step 6: commit**

```bash
cd /Users/liuzhixiong/coding-project/cursor-pointer
git add python-client/tools/run_agent.py python-client/tests/test_new_verbs.py
git commit -m "feat(agent): extend ACTION_RE for drag/app/clipboard/shell verbs"
```

---

## Task 4: Agent — `drag` verb

**Files:**
- Modify: `python-client/tools/run_agent.py` (add `_parse_drag` helper + drag branch in `execute()`)
- Test: `python-client/tests/test_new_verbs.py` (append)

- [ ] **Step 1: append failing tests**

Append to `python-client/tests/test_new_verbs.py`:

```python
# ---------------------------------------------------------------------------
# drag verb
# ---------------------------------------------------------------------------

from run_agent import _parse_drag, execute


def test_parse_drag_basic():
    assert _parse_drag("drag 5 to 9") == (5, 9)


def test_parse_drag_extra_words():
    assert _parse_drag("drag 5 to 9 quickly") == (5, 9)


def test_parse_drag_missing_to():
    assert _parse_drag("drag 5 9") == (None, None)


def test_drag_invokes_cp_drag():
    boxes = [
        {"id": 5, "x": 10, "y": 20, "w": 30, "h": 40, "role": "Cell",
         "label": "src", "parent_label": "", "parent_bbox": None,
         "ax_ref": None, "parent_ax_ref": None},
        {"id": 9, "x": 100, "y": 200, "w": 30, "h": 40, "role": "Cell",
         "label": "dst", "parent_label": "", "parent_bbox": None,
         "ax_ref": None, "parent_ax_ref": None},
    ]
    mock_cp = MagicMock()
    with patch("run_agent.CursorPointer", return_value=mock_cp), \
         patch("run_agent.time.sleep"):
        result = execute("drag 5 to 9", boxes)
    assert result is None
    # cp.drag should be called with the center points of the two boxes.
    mock_cp.drag.assert_called_once_with(
        from_xy=(25, 40),  # 10 + 30//2, 20 + 40//2
        to_xy=(115, 220),   # 100 + 30//2, 200 + 40//2
    )


def test_drag_with_bad_ids_returns_error():
    boxes = [
        {"id": 5, "x": 10, "y": 20, "w": 30, "h": 40, "role": "Cell",
         "label": "src", "parent_label": "", "parent_bbox": None,
         "ax_ref": None, "parent_ax_ref": None},
    ]
    mock_cp = MagicMock()
    with patch("run_agent.CursorPointer", return_value=mock_cp):
        result = execute("drag 5 to 99", boxes)
    assert result is not None
    assert "bad id" in result.lower() or "99" in result
```

- [ ] **Step 2: import CursorPointer at module level**

The existing `execute()` does `from cursor_pointer import CursorPointer` inside the function. Tests need to patch `run_agent.CursorPointer`, so hoist that import.

In `python-client/tools/run_agent.py`, find this block near the top (after `import requests`):

```python
import requests
```

Add (preserving the existing top-level pattern):

```python
from cursor_pointer import CursorPointer  # noqa: E402
```

Then in `execute()`, locate the line `from cursor_pointer import CursorPointer` and remove it (it'll now be a module-level import). The body of `execute()` should still start with `cp = CursorPointer()`.

- [ ] **Step 3: add `_parse_drag` helper**

Insert above `def execute(` (which is at line 780):

```python
def _parse_drag(action_str: str) -> tuple[int | None, int | None]:
    """Parse 'drag <from_id> to <to_id>'. Returns (None, None) on mismatch."""
    m = re.search(r"drag\s+(\d+)\s+to\s+(\d+)", action_str, re.IGNORECASE)
    if not m:
        return None, None
    return int(m.group(1)), int(m.group(2))
```

- [ ] **Step 4: add drag verb branch in `execute()`**

In `execute()`, after the existing `if verb == "scroll_to":` block (search for `if verb == "scroll_to":` and find its closing `return` or end of block), add:

```python
    if verb == "drag":
        f, t = _parse_drag(action_str)
        if f is None:
            return f"drag needs 'from to' ids, got {action_str!r}"
        el_from = next((b for b in boxes if b["id"] == f), None)
        el_to = next((b for b in boxes if b["id"] == t), None)
        if not el_from or not el_to:
            return f"drag: bad id(s) {f}/{t}"
        fx = el_from["x"] + el_from["w"] // 2
        fy = el_from["y"] + el_from["h"] // 2
        tx = el_to["x"] + el_to["w"] // 2
        ty = el_to["y"] + el_to["h"] // 2
        cp.move(fx, fy)
        time.sleep(0.2)
        cp.drag(from_xy=(fx, fy), to_xy=(tx, ty))
        return None
```

- [ ] **Step 5: run tests, expect 13 PASSED**

```bash
cd /Users/liuzhixiong/coding-project/cursor-pointer/python-client
/Users/liuzhixiong/coding-project/cursor-pointer/python-client/.venv/bin/pytest tests/ -v
```

Expected: 13 PASSED (9 verify_done + 8 prior new + 5 new drag = 22). If only some pass: read the failure carefully and either fix the implementation OR the test (the test value `(25, 40)` is computed from the box centers — if the box dimensions in the test differ from those in the assertion, the test is wrong).

Actually: count is **22** PASSED, not 13. Adjust this expectation as the suite grows.

- [ ] **Step 6: commit**

```bash
cd /Users/liuzhixiong/coding-project/cursor-pointer
git add python-client/tools/run_agent.py python-client/tests/test_new_verbs.py
git commit -m "feat(agent): add drag verb (TDD)"
```

---

## Task 5: Agent — `app` verb

**Files:**
- Modify: `python-client/tools/run_agent.py` (add app branch in `execute()`)
- Test: `python-client/tests/test_new_verbs.py` (append)

- [ ] **Step 1: append failing tests**

```python
# ---------------------------------------------------------------------------
# app verb
# ---------------------------------------------------------------------------

import subprocess as _subprocess  # alias so patches don't break drag tests


def test_app_invokes_osascript_with_name():
    mock_cp = MagicMock()
    with patch("run_agent.CursorPointer", return_value=mock_cp), \
         patch("run_agent.subprocess.run") as mock_run:
        # Successful CompletedProcess sentinel
        mock_run.return_value = MagicMock(returncode=0, stderr=b"")
        result = execute("app NeteaseMusic", boxes=[])
    assert result is None
    # First positional arg to subprocess.run should be the osascript command list
    args, kwargs = mock_run.call_args
    cmd = args[0]
    assert cmd[0] == "osascript"
    assert any("NeteaseMusic" in s for s in cmd)


def test_app_without_name_returns_error():
    mock_cp = MagicMock()
    with patch("run_agent.CursorPointer", return_value=mock_cp):
        result = execute("app", boxes=[])
    assert result is not None
    assert "needs" in result.lower() or "name" in result.lower()


def test_app_osascript_failure_returns_error():
    mock_cp = MagicMock()
    with patch("run_agent.CursorPointer", return_value=mock_cp), \
         patch("run_agent.subprocess.run") as mock_run:
        mock_run.side_effect = _subprocess.CalledProcessError(
            1, "osascript", stderr=b"application not found"
        )
        result = execute("app NoSuchApp", boxes=[])
    assert result is not None
    assert "failed" in result.lower() or "not found" in result.lower()
```

- [ ] **Step 2: run tests, expect failures**

```bash
cd /Users/liuzhixiong/coding-project/cursor-pointer/python-client
/Users/liuzhixiong/coding-project/cursor-pointer/python-client/.venv/bin/pytest tests/test_new_verbs.py -v
```

Expected: 3 new tests FAIL with "unknown verb 'app'".

- [ ] **Step 3: add app verb branch**

In `execute()`, after the `drag` block, add:

```python
    if verb == "app":
        # arg only captures quoted/digit/up-down-read-write — so for the
        # free-text app name, grab everything after the literal "app" token.
        name = ""
        if arg:
            name = arg.strip('"').strip()
        if not name:
            idx = action_str.lower().find("app")
            if idx >= 0:
                rest = action_str[idx + 3:].strip()
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
            stderr = (e.stderr or b"").decode(errors="replace")[:80]
            return f"app activate failed: {stderr.strip()}"
        except subprocess.TimeoutExpired:
            return f"app activate {name!r} timed out (5s)"
```

- [ ] **Step 4: run tests, expect 3 PASSED for app + all earlier still PASS**

```bash
cd /Users/liuzhixiong/coding-project/cursor-pointer/python-client
/Users/liuzhixiong/coding-project/cursor-pointer/python-client/.venv/bin/pytest tests/ -v
```

Expected: 25 PASSED (22 prior + 3 new app tests).

- [ ] **Step 5: commit**

```bash
cd /Users/liuzhixiong/coding-project/cursor-pointer
git add python-client/tools/run_agent.py python-client/tests/test_new_verbs.py
git commit -m "feat(agent): add app verb (osascript activate, TDD)"
```

---

## Task 6: Agent — `clipboard` verb

**Files:**
- Modify: `python-client/tools/run_agent.py` (add clipboard branch in `execute()`)
- Test: `python-client/tests/test_new_verbs.py` (append)

- [ ] **Step 1: append failing tests**

```python
# ---------------------------------------------------------------------------
# clipboard verb (read | write)
# ---------------------------------------------------------------------------


def test_clipboard_read_appends_to_history():
    """clipboard read should call cp.clipboard_get and inject into history."""
    mock_cp = MagicMock()
    mock_cp.clipboard_get.return_value = "已复制的文本"
    with patch("run_agent.CursorPointer", return_value=mock_cp), \
         patch("run_agent.history", []) as fake_hist:
        result = execute("clipboard read", boxes=[])
    assert result is None
    mock_cp.clipboard_get.assert_called_once()
    assert any("clipboard read" in h for h in fake_hist)
    assert any("已复制的文本" in h for h in fake_hist)


def test_clipboard_write_extracts_quoted_text():
    mock_cp = MagicMock()
    with patch("run_agent.CursorPointer", return_value=mock_cp):
        result = execute('clipboard write "hello world"', boxes=[])
    assert result is None
    mock_cp.clipboard_set.assert_called_once_with("hello world")


def test_clipboard_write_without_quotes_returns_error():
    mock_cp = MagicMock()
    with patch("run_agent.CursorPointer", return_value=mock_cp):
        result = execute("clipboard write hello", boxes=[])
    assert result is not None
    assert "quoted" in result.lower() or "needs" in result.lower()


def test_clipboard_bad_subcommand_returns_error():
    mock_cp = MagicMock()
    with patch("run_agent.CursorPointer", return_value=mock_cp):
        result = execute("clipboard reverse", boxes=[])
    assert result is not None
    assert "read" in result.lower()  # message lists valid subs
```

**Note on `history`:** The agent module owns a module-level `history`
list shared across the loop. The tests patch it as an empty list.
Implementation MUST use `run_agent.history` (not a local variable)
for these tests to work — see Step 3.

- [ ] **Step 2: run tests, expect failures**

```bash
cd /Users/liuzhixiong/coding-project/cursor-pointer/python-client
/Users/liuzhixiong/coding-project/cursor-pointer/python-client/.venv/bin/pytest tests/test_new_verbs.py -v
```

Expected: 4 new clipboard tests FAIL.

- [ ] **Step 3: verify `history` location**

Run:

```bash
grep -n "^history\|history = \[\]\|^    history = " python-client/tools/run_agent.py | head -5
```

If `history` is currently a LOCAL variable inside `main()`, you must hoist it to module level for the verb to access it (and for the tests to patch it). Add this near the top of `run_agent.py` (after other module-level state but before `def main`):

```python
# Module-level history so verb handlers in execute() can append to the
# same list that main() reads. Reset at the top of main().
history: list[str] = []
```

Then in `main()`, replace `history: list[str] = []` (or `history = []`) with `history.clear()`. If `main()` initialized `history` as `[]`, that pattern is now `history.clear()` to keep the same identity across calls.

If `history` is already module-level, skip this step.

- [ ] **Step 4: add clipboard verb branch**

In `execute()`, after the `app` block, add:

```python
    if verb == "clipboard":
        sub = ""
        if arg:
            sub = arg.strip('"').lower()
        if sub == "read":
            try:
                text = cp.clipboard_get()
            except Exception as e:
                return f"clipboard read failed: {e}"
            history.append(f"clipboard read → {text[:80]!r}")
            return None
        if sub == "write":
            m = re.search(r'write\s+"([^"]*)"', action_str, re.IGNORECASE)
            if not m or not m.group(1):
                return "clipboard write needs quoted text: clipboard write \"...\""
            try:
                cp.clipboard_set(m.group(1))
            except Exception as e:
                return f"clipboard write failed: {e}"
            return None
        return f"clipboard needs 'read' or 'write \"...\"', got {sub!r}"
```

- [ ] **Step 5: run tests, expect 29 PASSED**

```bash
cd /Users/liuzhixiong/coding-project/cursor-pointer/python-client
/Users/liuzhixiong/coding-project/cursor-pointer/python-client/.venv/bin/pytest tests/ -v
```

Expected: 29 PASSED (25 prior + 4 new clipboard).

- [ ] **Step 6: commit**

```bash
cd /Users/liuzhixiong/coding-project/cursor-pointer
git add python-client/tools/run_agent.py python-client/tests/test_new_verbs.py
git commit -m "feat(agent): add clipboard read/write verbs (TDD)"
```

---

## Task 7: Agent — `shell` verb with whitelist

**Files:**
- Modify: `python-client/tools/run_agent.py` (add `SHELL_WHITELIST` + shell branch in `execute()`)
- Test: `python-client/tests/test_new_verbs.py` (append)

- [ ] **Step 1: append failing tests**

```python
# ---------------------------------------------------------------------------
# shell verb (whitelisted)
# ---------------------------------------------------------------------------


def test_shell_whitelist_allows_ls():
    mock_cp = MagicMock()
    fake_completed = MagicMock(stdout="file1\nfile2\n", stderr="", returncode=0)
    with patch("run_agent.CursorPointer", return_value=mock_cp), \
         patch("run_agent.subprocess.run", return_value=fake_completed) as mock_run, \
         patch("run_agent.history", []) as fake_hist:
        result = execute("shell ls /tmp", boxes=[])
    assert result is None
    mock_run.assert_called_once()
    assert any("shell" in h and "ls" in h for h in fake_hist)


def test_shell_blocks_non_whitelisted_command():
    mock_cp = MagicMock()
    with patch("run_agent.CursorPointer", return_value=mock_cp), \
         patch("run_agent.subprocess.run") as mock_run:
        result = execute("shell rm -rf /", boxes=[])
    assert result is not None
    assert "whitelist" in result.lower() or "rm" in result
    mock_run.assert_not_called()


def test_shell_truncates_long_stdout():
    mock_cp = MagicMock()
    huge = "x" * 5000
    fake_completed = MagicMock(stdout=huge, stderr="", returncode=0)
    with patch("run_agent.CursorPointer", return_value=mock_cp), \
         patch("run_agent.subprocess.run", return_value=fake_completed), \
         patch("run_agent.history", []) as fake_hist:
        execute("shell cat /etc/hosts", boxes=[])
    # the truncated output in history should be <= some safe cap
    last = fake_hist[-1]
    assert len(last) < 500, f"history line too long: {len(last)}"


def test_shell_timeout_returns_error():
    mock_cp = MagicMock()
    with patch("run_agent.CursorPointer", return_value=mock_cp), \
         patch("run_agent.subprocess.run",
               side_effect=_subprocess.TimeoutExpired(cmd="cat", timeout=8)):
        result = execute("shell cat /dev/zero", boxes=[])
    assert result is not None
    assert "timed out" in result.lower() or "timeout" in result.lower()
```

- [ ] **Step 2: run tests, expect failures**

```bash
cd /Users/liuzhixiong/coding-project/cursor-pointer/python-client
/Users/liuzhixiong/coding-project/cursor-pointer/python-client/.venv/bin/pytest tests/test_new_verbs.py -v
```

Expected: 4 new shell tests FAIL.

- [ ] **Step 3: add `SHELL_WHITELIST` constant**

In `python-client/tools/run_agent.py`, find the existing `REVIEW_PROMPT = ` block (around line 670). Just above it, add:

```python
# ---------------------------------------------------------------------------
# Shell verb safety — only these commands are allowed. Read-only by design.
# ---------------------------------------------------------------------------

SHELL_WHITELIST = frozenset({
    "ls", "cat", "echo", "pwd", "which",
    "head", "tail", "grep", "find", "file",
    "wc", "date", "hostname", "whoami",
})
```

- [ ] **Step 4: add shell verb branch**

In `execute()`, after the `clipboard` block, add:

```python
    if verb == "shell":
        idx = action_str.lower().find("shell")
        cmd = action_str[idx + 5:].strip() if idx >= 0 else ""
        if not cmd:
            return "shell needs a command"
        head = cmd.split()[0]
        if head not in SHELL_WHITELIST:
            return (f"shell command {head!r} not in whitelist "
                    f"{sorted(SHELL_WHITELIST)}")
        try:
            out = subprocess.run(
                cmd, shell=True, capture_output=True,
                text=True, timeout=8,
            )
        except subprocess.TimeoutExpired:
            return f"shell {head!r} timed out (8s)"
        result_text = (out.stdout or "")[:200].rstrip()
        history.append(f"shell {head!r} → {result_text!r}")
        return None
```

- [ ] **Step 5: run tests, expect 33 PASSED**

```bash
cd /Users/liuzhixiong/coding-project/cursor-pointer/python-client
/Users/liuzhixiong/coding-project/cursor-pointer/python-client/.venv/bin/pytest tests/ -v
```

Expected: 33 PASSED (29 prior + 4 new shell).

- [ ] **Step 6: commit**

```bash
cd /Users/liuzhixiong/coding-project/cursor-pointer
git add python-client/tools/run_agent.py python-client/tests/test_new_verbs.py
git commit -m "feat(agent): add shell verb with read-only whitelist (TDD)"
```

---

## Task 8: SYSTEM_PROMPT update + smoke matrix grows

**Files:**
- Modify: `python-client/tools/run_agent.py` (extend SYSTEM_PROMPT)
- Modify: `scripts/smoke_test_api.py` (add clipboard tests)

- [ ] **Step 1: extend SYSTEM_PROMPT**

In `python-client/tools/run_agent.py`, find the `SYSTEM_PROMPT = textwrap.dedent("""\` block (around line 906). The verb listing inside currently ends with `done <短结论>`. Insert these lines immediately after the existing `scroll_to <id>` line and before `type "<text>"`:

```
        drag <id1> to <id2>  # 拖拽：从元素1拖到元素2
        app <name>           # 启动或切换到应用（如 NeteaseMusic / Finder / Safari）
        clipboard read       # 读当前剪贴板，结果会出现在历史里
        clipboard write "<text>"  # 写入剪贴板
        shell <cmd>          # 仅限只读命令：ls/cat/echo/pwd/head/tail/grep/find/wc/date 等
```

Then in the same SYSTEM_PROMPT, find the rule bullet list at the bottom (starts with `重要规则：`). Append one new bullet:

```
      • 跨 app 复制粘贴的标准做法：`clipboard write "<text>"` → `app <name>` → `click <input_id>` → `key cmd+v`。
```

- [ ] **Step 2: add clipboard cases to smoke test**

In `scripts/smoke_test_api.py`, find `def t_ocr_get` near the bottom of the test-function definitions. Add two new test functions directly above the `# --- run all ---` comment block (around line 245):

```python
def t_clipboard_set_get_roundtrip() -> None:
    """POST /clipboard/set then GET /clipboard/get round-trips the same text."""
    token = "cursor-pointer-smoke-test-token"
    r1 = post("/clipboard/set", {"text": token})
    g = get("/clipboard/get").json()
    ok = r1.status_code == 200 and g.get("text") == token
    record("/clipboard/set + /clipboard/get", PASS if ok else FAIL,
           f"set={r1.status_code} get={g.get('text')!r}",
           "round-trip via pbcopy/pbpaste")
```

Then find the `tests = [` list further down (around line 280). Add `t_clipboard_set_get_roundtrip` to that list, anywhere before the existing `t_ocr_get`.

- [ ] **Step 3: run smoke test against live cursor-pointer**

```bash
cd /Users/liuzhixiong/coding-project/cursor-pointer
curl -s http://127.0.0.1:39213/health
python3 scripts/smoke_test_api.py
```

Expected: matrix shows 22 pass · 0 fail · 1 skip (was 21/0/1; we added one round-trip case).
If `curl health` fails first, restart `CursorPointer.app` (Task 1's build).

- [ ] **Step 4: run unit tests one more time**

```bash
cd /Users/liuzhixiong/coding-project/cursor-pointer/python-client
/Users/liuzhixiong/coding-project/cursor-pointer/python-client/.venv/bin/pytest tests/ -v
```

Expected: 33 PASSED.

- [ ] **Step 5: commit**

```bash
cd /Users/liuzhixiong/coding-project/cursor-pointer
git add python-client/tools/run_agent.py scripts/smoke_test_api.py
git commit -m "docs(agent): SYSTEM_PROMPT covers new verbs + smoke test 22/22"
```

---

## Task 9: E2E live verification

**Files:** none modified — this is a behavioral test.

The four verbs together should enable a realistic cross-app task. We'll
run a single end-to-end goal that exercises `app` + `clipboard read` +
`shell` (drag is left out because there's no reliable drag target on
this machine).

Goal: "Read the current macOS hostname and write it to the clipboard."

This requires the agent to:
1. `shell hostname` → injects hostname into history
2. `clipboard write "<hostname>"` → writes to pasteboard
3. `done` → verifier confirms

- [ ] **Step 1: ensure cursor-pointer is running**

```bash
curl -s --max-time 2 http://127.0.0.1:39213/health
```

If non-200, restart the .app per Task 1.

- [ ] **Step 2: run the agent**

```bash
cd /Users/liuzhixiong/coding-project/cursor-pointer/python-client
source .venv/bin/activate
env -u CURSOR_POINTER_NO_OVERLAY python tools/run_agent.py \
  "读取本机 hostname，然后把它写入系统剪贴板" \
  --max-steps 6 2>&1 | tee /tmp/run_verb_e2e.log
```

This will take 1-3 minutes.

- [ ] **Step 3: confirm new verbs fired**

```bash
grep -E "shell|clipboard|verdict" /tmp/run_verb_e2e.log
```

Expected: at least one `shell 'hostname'` invocation AND at least one
`cp.clipboard_set` (visible as the agent issuing `clipboard write "..."`).
If only one of the two fires, the agent succeeded via an alternative
path — still acceptable.

- [ ] **Step 4: ground-truth — pbpaste shows the hostname**

```bash
pbpaste
hostname
```

Expected: `pbpaste` output matches `hostname` output (exactly or with
the trailing `.local` either present or stripped — both are valid forms
the agent might pick).

Acceptable outcomes:
- A) `pbpaste` matches `hostname` (full E2E success)
- B) The log shows `shell 'hostname'` AND `clipboard write` fired, but
  pbpaste content differs (the agent did the verbs but typed something
  else into clipboard — still proves the verbs work)
- C) Verifier rejected the `done` and agent ran out of steps. Acceptable
  — the verbs fired correctly; only goal-completion failed.

Unacceptable:
- D) `unknown verb 'shell'` or `unknown verb 'clipboard'` in the log →
  ACTION_RE didn't get the change → revisit Task 3.

- [ ] **Step 5: archive evidence (optional)**

```bash
cd /Users/liuzhixiong/coding-project/cursor-pointer
mkdir -p docs/superpowers/evidence
cp /tmp/run_verb_e2e.log docs/superpowers/evidence/2026-05-17-verb-expansion-e2e.log
git add docs/superpowers/evidence/2026-05-17-verb-expansion-e2e.log
git commit -m "evidence: e2e log confirming new verbs fire end-to-end"
```

---

## Self-Review Notes

- **Spec coverage:**
  - Rust endpoints `/clipboard/{get,set}` → Task 1
  - Python client wrappers → Task 2
  - ACTION_RE → Task 3
  - drag verb → Task 4
  - app verb → Task 5
  - clipboard verb → Task 6
  - shell verb + whitelist → Task 7
  - SYSTEM_PROMPT + smoke matrix → Task 8
  - E2E behavior → Task 9
- **Placeholder scan:** no TBDs. Every step has either exact code, an exact command, or an explicit decision tree (e.g., Task 6 Step 3 contingent on `history` already being module-level).
- **Type consistency:**
  - `_parse_drag` returns `tuple[int | None, int | None]` everywhere.
  - `cp.drag(from_xy, to_xy)` matches the signature in `python-client/cursor_pointer/client.py:119`.
  - `SHELL_WHITELIST` is a frozenset everywhere; `head in SHELL_WHITELIST` works.
- **Rollback path:** each verb is one branch in `execute()`. Reverting one commit removes one verb cleanly.
- **Live state caveat:** Task 1 rebuilds cursor-pointer; macOS TCC may pin permissions to the new cdhash. If the existing AX / Screen Recording grants get invalidated, recover per `docs/API.md` ("Permissions") before Task 9.
