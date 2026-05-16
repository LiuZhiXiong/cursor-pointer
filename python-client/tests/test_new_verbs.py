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
