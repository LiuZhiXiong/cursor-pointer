from __future__ import annotations

from unittest.mock import MagicMock

from cursor_pointer.verbs import VerbContext
from cursor_pointer.verbs.system import CLIPBOARD_VERB


def _ctx():
    return VerbContext(cp=MagicMock(), boxes=[], executor=MagicMock(),
                       history=[], log=lambda _m: None)


def test_clipboard_parse_read():
    assert CLIPBOARD_VERB.parse("clipboard read") == {"op": "read", "text": None}


def test_clipboard_parse_write():
    assert CLIPBOARD_VERB.parse('clipboard write "hello"') == \
        {"op": "write", "text": "hello"}


def test_clipboard_parse_rejects_others():
    assert CLIPBOARD_VERB.parse("click 5") is None


def test_clipboard_handle_read():
    ctx = _ctx()
    ctx.cp.clipboard_get.return_value = "abc"
    out = CLIPBOARD_VERB.handle({"op": "read", "text": None}, ctx)
    assert out.status == "executed_unverified"
    assert any("clipboard read" in h for h in ctx.history)


def test_clipboard_handle_write_calls_set():
    ctx = _ctx()
    out = CLIPBOARD_VERB.handle({"op": "write", "text": "hello"}, ctx)
    ctx.cp.clipboard_set.assert_called_once_with("hello")
    assert out.status == "executed_unverified"
