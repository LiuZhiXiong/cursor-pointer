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
    mock_cp.drag.assert_called_once_with(
        from_xy=(25, 40),
        to_xy=(115, 220),
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


# ---------------------------------------------------------------------------
# app verb
# ---------------------------------------------------------------------------

import subprocess as _subprocess  # alias so patches don't break drag tests


def test_app_invokes_osascript_with_name():
    mock_cp = MagicMock()
    with patch("run_agent.CursorPointer", return_value=mock_cp), \
         patch("run_agent.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stderr=b"")
        result = execute("app NeteaseMusic", boxes=[])
    assert result is None
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
    assert "read" in result.lower()  # message should list valid subs


def test_clipboard_write_accepts_missing_close_quote():
    """Real-world: MiniMax sometimes drops the closing quote.
    The regex was relaxed to `"([^"]*)"?` to accept that — this test
    pins the behavior so it doesn't regress."""
    mock_cp = MagicMock()
    with patch("run_agent.CursorPointer", return_value=mock_cp):
        result = execute('clipboard write "hostname-no-close-quote', boxes=[])
    assert result is None
    mock_cp.clipboard_set.assert_called_once_with("hostname-no-close-quote")


# ---------------------------------------------------------------------------
# shell verb (whitelisted, read-only)
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


# ---------------------------------------------------------------------------
# app verb — bundle-id + fallback
# ---------------------------------------------------------------------------


def test_app_bundle_id_uses_application_id_syntax():
    """Names containing a dot are treated as bundle IDs."""
    mock_cp = MagicMock()
    with patch("run_agent.CursorPointer", return_value=mock_cp), \
         patch("run_agent.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stderr=b"")
        result = execute("app com.netease.163music", boxes=[])
    assert result is None
    # The osascript command should use `tell application id "..."` (bundle form)
    cmd = mock_run.call_args.args[0]
    assert cmd[0] == "osascript"
    full_script = " ".join(cmd)
    assert 'application id "com.netease.163music"' in full_script


def test_app_osascript_failure_falls_back_to_open_a():
    """If osascript fails, retry via `open -a`."""
    mock_cp = MagicMock()
    call_count = {"n": 0}

    def fake_run(cmd, **kw):
        call_count["n"] += 1
        if cmd[0] == "osascript":
            raise _subprocess.CalledProcessError(
                1, "osascript", stderr=b"app not found"
            )
        if cmd[0] == "open":
            return MagicMock(returncode=0, stderr=b"")
        raise AssertionError(f"unexpected cmd: {cmd}")

    with patch("run_agent.CursorPointer", return_value=mock_cp), \
         patch("run_agent.subprocess.run", side_effect=fake_run):
        result = execute("app SomeWeirdApp", boxes=[])
    assert result is None
    assert call_count["n"] == 2  # osascript then open


def test_shell_blocks_command_injection_via_semicolon():
    """Critical safety regression: `shell grep; rm -rf /` must NOT execute
    the rm. The whitelist sees `grep` (allowed), but shell=True would
    happily run the `; rm` half. Switching to shell=False+shlex prevents this."""
    mock_cp = MagicMock()
    executed_cmds = []

    def record_run(cmd, **kw):
        executed_cmds.append(cmd)
        # Simulate subprocess running successfully
        return MagicMock(stdout="", stderr="", returncode=0)

    with patch("run_agent.CursorPointer", return_value=mock_cp), \
         patch("run_agent.subprocess.run", side_effect=record_run), \
         patch("run_agent.history", []):
        result = execute("shell grep; rm -rf /", boxes=[])
    # Implementation freedom: either it errors out (semicolon is a literal
    # arg that grep won't like) or runs grep with literal args that include
    # the semicolon. EITHER WAY, `rm` must NEVER appear as an executable.
    for cmd in executed_cmds:
        if isinstance(cmd, list):
            assert cmd[0] != "rm", f"rm executed: {cmd}"
            # No element of the argv should be a shell metachar interpreted as separator
        elif isinstance(cmd, str):
            # If anyone ever switches BACK to shell=True, this assertion catches it.
            assert "rm" not in cmd or "shell=True" not in str(kw), \
                f"raw shell exec with rm: {cmd}"


def test_shell_uses_argv_list_not_shell_string():
    """The implementation should pass argv as a LIST to subprocess.run,
    with shell=False (default). This is what prevents the injection."""
    mock_cp = MagicMock()
    with patch("run_agent.CursorPointer", return_value=mock_cp), \
         patch("run_agent.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout="", stderr="", returncode=0)
        execute("shell ls /tmp", boxes=[])
    args, kwargs = mock_run.call_args
    cmd_arg = args[0]
    assert isinstance(cmd_arg, list), f"expected list argv, got {type(cmd_arg).__name__}: {cmd_arg!r}"
    assert cmd_arg[0] == "ls"
    assert "/tmp" in cmd_arg
    assert kwargs.get("shell", False) is False


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


# ---------------------------------------------------------------------------
# browser verb (bridge to WebClaw)
# ---------------------------------------------------------------------------


def test_browser_verb_enqueues_polls_and_returns():
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
    full_args_str = str(enq_args)
    assert "what is the page title?" in full_args_str
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
