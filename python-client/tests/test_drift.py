"""End-to-end test of relocate behavior against drifted elements.

Synthetic — uses an in-memory ActionExecutor with mocked screenshot +
mocked detect_elements that return the target shifted by N pixels on the
second call. Verifies the Outcome reports the drift accurately and still
fires the action.
"""
from __future__ import annotations

import io
from unittest.mock import MagicMock

from PIL import Image

from cursor_pointer.executor import ActionExecutor, build_click_intent


def _png(w: int = 400, h: int = 400, color=(200, 200, 200)) -> bytes:
    img = Image.new("RGB", (w, h), color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _elem(x, y, eid=5):
    return {"id": eid, "x": x, "y": y, "w": 80, "h": 30,
            "role": "AXButton", "label": "Send", "ax_ref": "REF"}


def test_drift_within_threshold_recovers_and_succeeds():
    """Target moves 30px between perception and action — executor finds it."""
    initial_elems = [_elem(100, 200)]
    drifted_elems = [_elem(130, 220)]  # ~36px drift

    cp = MagicMock()
    screenshot_fn = MagicMock(return_value=_png())
    ax_press = MagicMock(return_value=True)
    focused_ax = MagicMock(side_effect=[
        {"id": "before"}, {"id": "after"},
    ])
    detect = MagicMock(return_value=drifted_elems)

    ex = ActionExecutor(cp=cp, screenshot_fn=screenshot_fn,
                        ax_press_fn=ax_press, focused_ax_fn=focused_ax,
                        detect_elements_fn=detect)

    intent = build_click_intent(
        action_str="click 5", element_id=5,
        elements=initial_elems, screenshot_png=_png(),
    )
    outcome = ex.execute(intent)
    assert outcome.status == "ok"
    assert outcome.relocate_drift_px is not None
    assert 25 <= outcome.relocate_drift_px <= 50


def test_drift_beyond_threshold_returns_mismatch_target():
    initial_elems = [_elem(100, 200)]
    drifted_elems = [_elem(500, 500)]  # way out of radius

    cp = MagicMock()
    screenshot_fn = MagicMock(return_value=_png())
    ax_press = MagicMock(return_value=False)
    focused_ax = MagicMock(return_value=None)
    detect = MagicMock(return_value=drifted_elems)

    ex = ActionExecutor(cp=cp, screenshot_fn=screenshot_fn,
                        ax_press_fn=ax_press, focused_ax_fn=focused_ax,
                        detect_elements_fn=detect)

    intent = build_click_intent(
        action_str="click 5", element_id=5,
        elements=initial_elems, screenshot_png=_png(),
    )
    outcome = ex.execute(intent)
    assert outcome.status == "mismatch_target"
    cp.click.assert_not_called()
    ax_press.assert_not_called()
