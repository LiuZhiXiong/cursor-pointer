from __future__ import annotations

from unittest.mock import MagicMock

from cursor_pointer.verbs import VerbContext
from cursor_pointer.verbs.click import CLICK_VERB, DCLICK_VERB, RCLICK_VERB


def _ctx(boxes=None, executor=None):
    return VerbContext(
        cp=MagicMock(), boxes=boxes or [],
        executor=executor or MagicMock(), history=[], log=lambda _m: None,
    )


def test_click_parse():
    assert CLICK_VERB.parse("click 5") == {"id": 5}


def test_click_parse_rejects_dclick():
    assert CLICK_VERB.parse("dclick 5") is None


def test_dclick_parse():
    assert DCLICK_VERB.parse("dclick 5") == {"id": 5}


def test_rclick_parse():
    assert RCLICK_VERB.parse("rclick 5") == {"id": 5}


def test_click_handle_missing_box_returns_error():
    out = CLICK_VERB.handle({"id": 99}, _ctx(boxes=[]))
    assert out.status == "exec_error" or out.status == "mismatch_target"


def test_click_handle_delegates_to_executor():
    exec_mock = MagicMock()
    fake_outcome = MagicMock(status="ok", used_path="ax_press",
                              relocate_drift_px=0, error=None, elapsed_ms=5,
                              intent=MagicMock(raw_action="click 5"))
    exec_mock.execute.return_value = fake_outcome
    box = {"id": 5, "x": 10, "y": 10, "w": 50, "h": 30,
           "role": "AXButton", "label": "Send", "ax_ref": "REF"}
    ctx = _ctx(boxes=[box], executor=exec_mock)
    out = CLICK_VERB.handle({"id": 5}, ctx)
    exec_mock.execute.assert_called_once()
    assert out is fake_outcome


def test_dclick_handle_calls_hover_then_click_count_2():
    box = {"id": 5, "x": 10, "y": 10, "w": 50, "h": 30,
           "role": "AXButton", "label": "Send", "ax_ref": "REF"}
    ctx = _ctx(boxes=[box])
    out = DCLICK_VERB.handle({"id": 5}, ctx)
    assert out.status == "executed_unverified"
    assert ctx.cp.move.called


def test_rclick_handle_uses_right_button():
    box = {"id": 5, "x": 10, "y": 10, "w": 50, "h": 30,
           "role": "AXButton", "label": "Send", "ax_ref": "REF"}
    ctx = _ctx(boxes=[box])
    out = RCLICK_VERB.handle({"id": 5}, ctx)
    assert out.status == "executed_unverified"
    _args, kwargs = ctx.cp.click.call_args
    assert kwargs.get("button") == "right"
