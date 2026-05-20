"""Unit tests for done + wait verbs."""
from __future__ import annotations

import time
from unittest.mock import MagicMock

from cursor_pointer.verbs import dispatch, VerbContext
from cursor_pointer.verbs.done import DONE_VERB, WAIT_VERB


def _ctx() -> VerbContext:
    return VerbContext(
        cp=MagicMock(),
        boxes=[],
        executor=MagicMock(),
        history=[],
        log=lambda _m: None,
    )


def test_done_parse_matches_keyword():
    assert DONE_VERB.parse("done") == {"reason": ""}
    assert DONE_VERB.parse("done finished the task") == {"reason": "finished the task"}


def test_done_parse_rejects_other_verbs():
    assert DONE_VERB.parse("click 5") is None
    assert DONE_VERB.parse("scroll down") is None


def test_done_handle_returns_ok_with_done_raw_action():
    out = DONE_VERB.handle({"reason": "task complete"}, _ctx())
    assert out.status == "ok"
    assert out.intent.raw_action.lower().startswith("done")


def test_done_dispatches_via_registry():
    out = dispatch("done all set", _ctx())
    assert out.status == "ok"


def test_wait_parse_default_1_5_seconds():
    assert WAIT_VERB.parse("wait") == {"seconds": 1.5}


def test_wait_parse_explicit_seconds():
    assert WAIT_VERB.parse("wait 3") == {"seconds": 3.0}
    assert WAIT_VERB.parse("wait 0") == {"seconds": 0.0}


def test_wait_parse_rejects_non_wait():
    assert WAIT_VERB.parse("done") is None
    assert WAIT_VERB.parse("waiter") is None


def test_wait_handle_sleeps(monkeypatch):
    captured = []
    monkeypatch.setattr(time, "sleep", lambda s: captured.append(s))
    out = WAIT_VERB.handle({"seconds": 0.5}, _ctx())
    assert captured == [0.5]
    assert out.status == "executed_unverified"
