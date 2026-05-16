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
