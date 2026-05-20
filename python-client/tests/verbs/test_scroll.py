"""Unit tests for scroll + scroll_to verbs."""
from __future__ import annotations

from unittest.mock import MagicMock

from cursor_pointer.verbs import dispatch, VerbContext
from cursor_pointer.verbs.scroll import SCROLL_VERB, SCROLL_TO_VERB


def _ctx(boxes=None) -> VerbContext:
    return VerbContext(
        cp=MagicMock(),
        boxes=boxes or [],
        executor=MagicMock(),
        history=[],
        log=lambda _m: None,
    )


def test_scroll_parse_down_default():
    assert SCROLL_VERB.parse("scroll") == {"direction": "down", "amount": 6}


def test_scroll_parse_up():
    assert SCROLL_VERB.parse("scroll up") == {"direction": "up", "amount": 6}


def test_scroll_parse_numeric_amount():
    assert SCROLL_VERB.parse("scroll 12") == {"direction": "down", "amount": 12}


def test_scroll_parse_rejects_scroll_to():
    assert SCROLL_VERB.parse("scroll_to 5") is None


def test_scroll_to_parse_id():
    assert SCROLL_TO_VERB.parse("scroll_to 5") == {"id": 5}


def test_scroll_to_parse_rejects_scroll():
    assert SCROLL_TO_VERB.parse("scroll down") is None


def test_dispatch_scroll_to_routes_correctly():
    """Crucial: scroll_to 5 must hit SCROLL_TO_VERB, not SCROLL_VERB."""
    out = dispatch("scroll_to 5", _ctx(boxes=[]))
    assert "scroll_to" in (out.intent.raw_action or "")


def test_scroll_handle_calls_cp_scroll():
    cp = MagicMock()
    box = {"id": 1, "x": 100, "y": 100, "w": 50, "h": 50}
    ctx = _ctx(boxes=[box])
    ctx.cp = cp
    out = SCROLL_VERB.handle({"direction": "down", "amount": 6}, ctx)
    assert out.status == "executed_unverified"
    cp.scroll.assert_called_once()


def test_scroll_to_handle_no_ax_ref_returns_error():
    box = {"id": 5, "x": 0, "y": 0, "w": 10, "h": 10}  # no ax_ref
    ctx = _ctx(boxes=[box])
    out = SCROLL_TO_VERB.handle({"id": 5}, ctx)
    assert out.status == "exec_error"


def test_scroll_to_handle_missing_id_returns_error():
    ctx = _ctx(boxes=[])
    out = SCROLL_TO_VERB.handle({"id": 99}, ctx)
    assert out.status == "exec_error"
