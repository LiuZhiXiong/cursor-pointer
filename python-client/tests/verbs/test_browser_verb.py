from __future__ import annotations

from unittest.mock import MagicMock

from cursor_pointer.verbs import VerbContext
from cursor_pointer.verbs.browser import BROWSER_VERB


def _ctx():
    return VerbContext(cp=MagicMock(), boxes=[], executor=MagicMock(),
                       history=[], log=lambda _m: None)


def test_browser_parse_quoted_task():
    assert BROWSER_VERB.parse('browser "search for X"') == \
        {"command": "search for X"}


def test_browser_parse_rejects_unquoted():
    assert BROWSER_VERB.parse("browser hello") is None


def test_browser_parse_rejects_empty():
    assert BROWSER_VERB.parse('browser ""') is None


def test_browser_handle_enqueue_failure():
    ctx = _ctx()
    ctx.cp.browser_enqueue.side_effect = Exception("net down")
    out = BROWSER_VERB.handle({"command": "open google"}, ctx)
    assert out.status == "exec_error"
    assert "browser enqueue failed" in (out.error or "")


def test_browser_handle_success_polls_until_done():
    ctx = _ctx()
    ctx.cp.browser_enqueue.return_value = {"id": "abc123"}
    ctx.cp.browser_result_status.side_effect = [
        {"status": "pending"},
        {"status": "done", "ok": True, "output": "result text"},
    ]
    out = BROWSER_VERB.handle({"command": "open google"}, ctx)
    assert out.status == "executed_unverified"
    assert any("browser" in h for h in ctx.history)


def test_browser_handle_expired():
    ctx = _ctx()
    ctx.cp.browser_enqueue.return_value = {"id": "abc"}
    ctx.cp.browser_result_status.return_value = {"status": "expired"}
    out = BROWSER_VERB.handle({"command": "x"}, ctx)
    assert out.status == "exec_error"
    assert "expired" in (out.error or "").lower()
