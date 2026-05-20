"""Tests for dispatch() — ordering + fallback behavior."""
from __future__ import annotations

from unittest.mock import MagicMock


def _ctx():
    from cursor_pointer.verbs import VerbContext
    return VerbContext(
        cp=MagicMock(),
        boxes=[],
        executor=MagicMock(),
        history=[],
        log=lambda _msg: None,
    )


def test_dispatch_empty_registry_returns_exec_error_unknown():
    from cursor_pointer.verbs import dispatch
    out = dispatch("anything goes here", _ctx())
    assert out.status == "exec_error"
    assert "unknown action" in (out.error or "")


def test_placeholder_intent_carries_raw_action():
    from cursor_pointer.verbs.base import make_placeholder_intent
    intent = make_placeholder_intent("scroll down")
    assert intent.raw_action == "scroll down"
    assert intent.target is None
