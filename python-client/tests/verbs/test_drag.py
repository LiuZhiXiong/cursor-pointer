from __future__ import annotations

from unittest.mock import MagicMock

from cursor_pointer.verbs import VerbContext
from cursor_pointer.verbs.mouse import DRAG_VERB


def _ctx(boxes=None) -> VerbContext:
    return VerbContext(cp=MagicMock(), boxes=boxes or [],
                       executor=MagicMock(), history=[], log=lambda _m: None)


def test_drag_parse_canonical():
    assert DRAG_VERB.parse("drag 1 to 2") == {"from_id": 1, "to_id": 2}


def test_drag_parse_rejects_missing_to():
    assert DRAG_VERB.parse("drag 1 2") is None


def test_drag_parse_rejects_other_verb():
    assert DRAG_VERB.parse("click 5") is None


def test_drag_handle_missing_ids_returns_error():
    ctx = _ctx(boxes=[])
    out = DRAG_VERB.handle({"from_id": 1, "to_id": 2}, ctx)
    assert out.status == "exec_error"


def test_drag_handle_calls_cp_drag():
    cp = MagicMock()
    boxes = [
        {"id": 1, "x": 0, "y": 0, "w": 10, "h": 10},
        {"id": 2, "x": 100, "y": 100, "w": 10, "h": 10},
    ]
    ctx = _ctx(boxes=boxes)
    ctx.cp = cp
    out = DRAG_VERB.handle({"from_id": 1, "to_id": 2}, ctx)
    assert out.status == "executed_unverified"
    cp.drag.assert_called_once()
