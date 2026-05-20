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
    assert outcome.status == "ok"


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
    assert outcome.status == "ok"


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
    assert outcome.status == "ok"


def test_executor_verify_ok_via_focus_change():
    cp = MagicMock()
    screenshot_fn = MagicMock(return_value=_png())
    ax_press = MagicMock(return_value=True)
    focused_ax = MagicMock(side_effect=[
        {"id": "before-elem"}, {"id": "after-elem"},
    ])
    detect = MagicMock(return_value=[_elem()])

    ex = ActionExecutor(cp=cp, screenshot_fn=screenshot_fn,
                        ax_press_fn=ax_press, focused_ax_fn=focused_ax,
                        detect_elements_fn=detect)
    outcome = ex.execute(_make_intent())
    assert outcome.status == "ok"
    assert outcome.used_path == "ax_press"


def test_executor_verify_ok_via_roi_delta():
    """ROI changed (focus stays same)."""
    grey = _png(w=400, h=400, color=(180, 180, 180))
    img = Image.new("RGB", (400, 400), (180, 180, 180))
    # Add a black checker into the bbox (100,200,80,30).
    for x in range(100, 180):
        for y in range(200, 230):
            if (x + y) % 4 < 2:
                img.putpixel((x, y), (0, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    diff = buf.getvalue()

    cp = MagicMock()
    screenshot_fn = MagicMock(side_effect=[grey, diff])
    ax_press = MagicMock(return_value=True)
    focused_ax = MagicMock(return_value={"id": "same"})  # focus did NOT change
    detect = MagicMock(return_value=[_elem()])

    ex = ActionExecutor(cp=cp, screenshot_fn=screenshot_fn,
                        ax_press_fn=ax_press, focused_ax_fn=focused_ax,
                        detect_elements_fn=detect)
    outcome = ex.execute(_make_intent())
    assert outcome.status == "ok", f"got {outcome.status}: {outcome.error}"


def test_executor_verify_failed_neither_focus_nor_roi():
    same = _png()
    cp = MagicMock()
    screenshot_fn = MagicMock(side_effect=[same, same])
    ax_press = MagicMock(return_value=True)
    focused_ax = MagicMock(return_value={"id": "same"})
    detect = MagicMock(return_value=[_elem()])

    ex = ActionExecutor(cp=cp, screenshot_fn=screenshot_fn,
                        ax_press_fn=ax_press, focused_ax_fn=focused_ax,
                        detect_elements_fn=detect)
    outcome = ex.execute(_make_intent())
    assert outcome.status == "verify_failed"


def _make_type_intent(text: str = "hello", with_target: bool = False) -> Intent:
    target = None
    if with_target:
        target = TargetSig(
            element_id=5, bbox=(100, 200, 80, 30),
            ax_path=None, role="AXTextField", ocr_text="Search",
            visual_hash="0" * 16,
        )
    return Intent(
        kind="type",
        target=target,
        payload={"text": text},
        expect=ExpectSig(focus_changes=False, roi_pixel_delta_min=0.0,
                         typed_text_in_focus=text),
        raw_action=f'type "{text}"',
    )


def test_executor_type_no_target_verifies_via_axvalue():
    cp = MagicMock()
    screenshot_fn = MagicMock(return_value=_png())
    ax_press = MagicMock(return_value=False)
    focused_ax = MagicMock(return_value={"value": "previous text hello"})

    ex = ActionExecutor(cp=cp, screenshot_fn=screenshot_fn,
                        ax_press_fn=ax_press, focused_ax_fn=focused_ax)
    outcome = ex.execute(_make_type_intent("hello"))
    assert outcome.status == "ok"
    cp.type_text.assert_called_once_with("hello")


def test_executor_type_verify_failed_when_axvalue_missing_text():
    cp = MagicMock()
    screenshot_fn = MagicMock(return_value=_png())
    ax_press = MagicMock(return_value=False)
    focused_ax = MagicMock(return_value={"value": "unrelated text"})

    ex = ActionExecutor(cp=cp, screenshot_fn=screenshot_fn,
                        ax_press_fn=ax_press, focused_ax_fn=focused_ax)
    outcome = ex.execute(_make_type_intent("hello"))
    assert outcome.status == "verify_failed"


def test_executor_type_with_target_focuses_then_types():
    cp = MagicMock()
    screenshot_fn = MagicMock(return_value=_png())
    ax_press = MagicMock(return_value=True)
    focused_ax = MagicMock(return_value={"value": "hello"})
    detect = MagicMock(return_value=[
        _elem(eid=5, role="AXTextField", label="Search")
    ])

    ex = ActionExecutor(cp=cp, screenshot_fn=screenshot_fn,
                        ax_press_fn=ax_press, focused_ax_fn=focused_ax,
                        detect_elements_fn=detect)
    outcome = ex.execute(_make_type_intent("hello", with_target=True))
    assert outcome.status == "ok"
    ax_press.assert_called_once()
    cp.type_text.assert_called_once_with("hello")


from cursor_pointer.executor import build_click_intent, build_type_intent


def test_build_click_intent_from_element_list():
    elements = [
        _elem(eid=5, x=100, y=200, role="AXButton", label="Send",
              ax_ref="REF"),
    ]
    shot = _png()
    intent = build_click_intent(
        action_str="click 5", element_id=5,
        elements=elements, screenshot_png=shot,
    )
    assert intent is not None
    assert intent.kind == "click"
    assert intent.target is not None
    assert intent.target.element_id == 5
    assert intent.target.role == "AXButton"
    assert intent.target.ocr_text == "Send"
    assert len(intent.target.visual_hash) == 16


def test_build_click_intent_returns_none_when_id_missing():
    elements = [_elem(eid=7)]
    intent = build_click_intent(
        action_str="click 5", element_id=5,
        elements=elements, screenshot_png=_png(),
    )
    assert intent is None


def test_build_type_intent_with_target():
    elements = [_elem(eid=3, role="AXTextField", label="Search")]
    intent = build_type_intent(
        action_str='type 3 "hello"', text="hello",
        element_id=3, elements=elements, screenshot_png=_png(),
    )
    assert intent.kind == "type"
    assert intent.payload["text"] == "hello"
    assert intent.target is not None
    assert intent.target.role == "AXTextField"


def test_build_type_intent_without_target():
    intent = build_type_intent(
        action_str='type "hello"', text="hello",
        element_id=None, elements=[], screenshot_png=_png(),
    )
    assert intent.kind == "type"
    assert intent.target is None
    assert intent.payload["text"] == "hello"


def test_executor_permission_denied_surfaces_via_verify():
    """Black-frame after action → exec_error permission_denied."""
    normal = _png()
    black = _png(color=(0, 0, 0))
    cp = MagicMock()
    screenshot_fn = MagicMock(side_effect=[normal, black])
    ax_press = MagicMock(return_value=True)
    focused_ax = MagicMock(return_value={"id": "x"})
    detect = MagicMock(return_value=[_elem()])

    ex = ActionExecutor(cp=cp, screenshot_fn=screenshot_fn,
                        ax_press_fn=ax_press, focused_ax_fn=focused_ax,
                        detect_elements_fn=detect)
    outcome = ex.execute(_make_intent())
    assert outcome.status == "exec_error"
    assert "permission_denied" in (outcome.error or "")
