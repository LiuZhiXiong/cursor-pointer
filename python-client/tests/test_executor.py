"""Unit tests for ActionExecutor — skeleton + construction.

Uses mocks for CursorPointer + screenshot source + AX press so tests can
run without the desktop daemon or pyobjc.
"""
from __future__ import annotations

import io
from unittest.mock import MagicMock

import pytest
from PIL import Image

from cursor_pointer.executor import ActionExecutor


def _png(w: int = 200, h: int = 200, color=(180, 180, 180)) -> bytes:
    img = Image.new("RGB", (w, h), color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_executor_constructs_with_dependencies():
    cp = MagicMock()
    screenshot_fn = MagicMock(return_value=_png())
    ax_press = MagicMock(return_value=False)
    focused_ax = MagicMock(return_value=None)

    ex = ActionExecutor(
        cp=cp,
        screenshot_fn=screenshot_fn,
        ax_press_fn=ax_press,
        focused_ax_fn=focused_ax,
    )
    assert ex is not None


from cursor_pointer.intent import ExpectSig, Intent, TargetSig


def _make_intent() -> Intent:
    target = TargetSig(
        element_id=5,
        bbox=(100, 200, 80, 30),
        ax_path=None,
        role="AXButton",
        ocr_text="Send",
        visual_hash="0" * 16,
    )
    return Intent(
        kind="click",
        target=target,
        payload={},
        expect=ExpectSig(focus_changes=True, roi_pixel_delta_min=0.02),
        raw_action="click 5",
    )


def _elem(eid=5, x=100, y=200, w=80, h=30, role="AXButton", label="Send",
          ax_ref="REF-OBJ"):
    return {"id": eid, "x": x, "y": y, "w": w, "h": h,
            "role": role, "label": label, "ax_ref": ax_ref}


def test_executor_relocate_mismatch_returns_early():
    cp = MagicMock()
    screenshot_fn = MagicMock(return_value=_png())
    ax_press = MagicMock(return_value=False)
    focused_ax = MagicMock(return_value=None)
    detect = MagicMock(return_value=[_elem(eid=99, x=500, y=500, label="Other")])

    ex = ActionExecutor(cp=cp, screenshot_fn=screenshot_fn,
                        ax_press_fn=ax_press, focused_ax_fn=focused_ax,
                        detect_elements_fn=detect)
    outcome = ex.execute(_make_intent())
    assert outcome.status == "mismatch_target"
    assert outcome.used_path == "none"
    cp.click.assert_not_called()
    ax_press.assert_not_called()


def test_executor_structured_first_skips_pixel():
    cp = MagicMock()
    screenshot_fn = MagicMock(return_value=_png())
    ax_press = MagicMock(return_value=True)
    focused_ax = MagicMock(side_effect=[
        {"id": "before"}, {"id": "after"},
    ])
    detect = MagicMock(return_value=[_elem()])

    ex = ActionExecutor(cp=cp, screenshot_fn=screenshot_fn,
                        ax_press_fn=ax_press, focused_ax_fn=focused_ax,
                        detect_elements_fn=detect)
    outcome = ex.execute(_make_intent())
    assert outcome.used_path == "ax_press"
    cp.click.assert_not_called()
    ax_press.assert_called_once()
    assert outcome.status in ("ok", "executed_unverified")


def test_executor_pixel_fallback_when_no_ax_ref():
    cp = MagicMock()
    screenshot_fn = MagicMock(return_value=_png())
    ax_press = MagicMock(return_value=False)
    focused_ax = MagicMock(side_effect=[
        {"id": "before"}, {"id": "after"},
    ])
    detect = MagicMock(return_value=[_elem(ax_ref=None)])

    ex = ActionExecutor(cp=cp, screenshot_fn=screenshot_fn,
                        ax_press_fn=ax_press, focused_ax_fn=focused_ax,
                        detect_elements_fn=detect)
    outcome = ex.execute(_make_intent())
    assert outcome.used_path == "pixel"
    cp.click.assert_called_once()
    ax_press.assert_not_called()
    assert outcome.status in ("ok", "executed_unverified")


def test_executor_pixel_fallback_when_ax_press_returns_false():
    cp = MagicMock()
    screenshot_fn = MagicMock(return_value=_png())
    ax_press = MagicMock(return_value=False)
    focused_ax = MagicMock(side_effect=[
        {"id": "before"}, {"id": "after"},
    ])
    detect = MagicMock(return_value=[_elem()])

    ex = ActionExecutor(cp=cp, screenshot_fn=screenshot_fn,
                        ax_press_fn=ax_press, focused_ax_fn=focused_ax,
                        detect_elements_fn=detect)
    outcome = ex.execute(_make_intent())
    assert outcome.used_path == "pixel"
    cp.click.assert_called_once()
    assert outcome.status in ("ok", "executed_unverified")
