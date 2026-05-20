"""Unit tests for Intent / Outcome dataclasses."""
from __future__ import annotations

import pytest

from cursor_pointer.intent import (
    ExpectSig,
    Intent,
    Outcome,
    TargetSig,
)


def _make_target() -> TargetSig:
    return TargetSig(
        element_id=5,
        bbox=(100, 200, 80, 30),
        ax_path=("AXApplication:Mail", "AXButton:Send"),
        role="AXButton",
        ocr_text="Send",
        visual_hash="ab" * 8,
    )


def test_target_sig_frozen():
    t = _make_target()
    with pytest.raises(Exception):
        t.element_id = 7  # type: ignore[misc]


def test_expect_sig_defaults():
    e = ExpectSig()
    assert e.focus_changes is True
    assert e.ax_subtree_changes is False
    assert e.roi_pixel_delta_min == pytest.approx(0.02)
    assert e.typed_text_in_focus is None


def test_intent_carries_raw_action():
    i = Intent(
        kind="click",
        target=_make_target(),
        payload={},
        expect=ExpectSig(),
        raw_action="click 5",
    )
    assert i.kind == "click"
    assert i.raw_action == "click 5"
    assert i.target is not None
    assert i.target.element_id == 5


def test_outcome_default_fields():
    t = _make_target()
    i = Intent(kind="click", target=t, payload={}, expect=ExpectSig(), raw_action="click 5")
    o = Outcome(
        status="ok",
        intent=i,
        elapsed_ms=120,
        relocate_drift_px=3,
        used_path="ax_press",
        before_hash="aa" * 8,
        after_hash="bb" * 8,
        error=None,
    )
    assert o.status == "ok"
    assert o.used_path == "ax_press"
    assert o.error is None
