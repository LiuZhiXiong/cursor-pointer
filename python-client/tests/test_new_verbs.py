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
