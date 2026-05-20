"""Unit tests for anchors module — pHash, permission detection."""
from __future__ import annotations

import io

import pytest
from PIL import Image

from cursor_pointer.anchors import (
    average_hash_hex,
    hamming_distance_hex,
    is_permission_denied_frame,
)


def _png_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_average_hash_same_image_zero_distance():
    img = Image.new("RGB", (200, 200), (128, 64, 200))
    h = average_hash_hex(_png_bytes(img))
    assert hamming_distance_hex(h, h) == 0
    assert len(h) == 16  # 64 bits = 16 hex chars


def test_average_hash_different_images_nonzero_distance():
    """Two visually distinct images should hash differently.

    Note: average-hash is degenerate on uniform colour (no per-pixel variance
    → all bits set), so we use a contrasting pattern in each image.
    """
    a = Image.new("RGB", (200, 200), (240, 240, 240))
    # Black L in top-left quadrant.
    for x in range(0, 100):
        for y in range(0, 100):
            a.putpixel((x, y), (0, 0, 0))
    b = Image.new("RGB", (200, 200), (240, 240, 240))
    # Black L in bottom-right quadrant.
    for x in range(100, 200):
        for y in range(100, 200):
            b.putpixel((x, y), (0, 0, 0))
    ha = average_hash_hex(_png_bytes(a))
    hb = average_hash_hex(_png_bytes(b))
    assert hamming_distance_hex(ha, hb) > 10


def test_average_hash_roi_only():
    """ROI hash should depend only on the cropped region."""
    img = Image.new("RGB", (400, 400), (200, 200, 200))
    # ROI #1: 100x100 region with a checker pattern (varied)
    for x in range(50, 150):
        for y in range(50, 150):
            img.putpixel((x, y), (0, 0, 0) if (x + y) % 16 < 8 else (255, 255, 255))
    # ROI #2: 100x100 region with a horizontal-stripe pattern (also varied)
    for x in range(200, 300):
        for y in range(200, 300):
            img.putpixel((x, y), (0, 0, 0) if (y // 4) % 2 == 0 else (255, 255, 255))
    h_checker = average_hash_hex(_png_bytes(img), bbox=(50, 50, 100, 100))
    h_stripes = average_hash_hex(_png_bytes(img), bbox=(200, 200, 100, 100))
    assert hamming_distance_hex(h_checker, h_stripes) > 5


def test_permission_denied_black_frame():
    black = Image.new("RGB", (1280, 800), (0, 0, 0))
    assert is_permission_denied_frame(_png_bytes(black)) is True


def test_permission_denied_normal_frame():
    normal = Image.new("RGB", (1280, 800), (180, 180, 180))
    assert is_permission_denied_frame(_png_bytes(normal)) is False


def test_permission_denied_zero_size():
    assert is_permission_denied_frame(b"") is True


# ---------------------------------------------------------------------------
# Multi-anchor target matching
# ---------------------------------------------------------------------------

from cursor_pointer.anchors import find_target_match
from cursor_pointer.intent import TargetSig


def _elem(eid: int, x: int, y: int, w: int = 80, h: int = 30,
          role: str = "AXButton", label: str = "Send") -> dict:
    return {
        "id": eid,
        "x": x, "y": y, "w": w, "h": h,
        "role": role,
        "label": label,
        "ax_ref": object(),
    }


def _sig(x: int, y: int, w: int = 80, h: int = 30,
         role: str = "AXButton", label: str = "Send",
         visual_hash: str = "0" * 16) -> TargetSig:
    return TargetSig(
        element_id=5,
        bbox=(x, y, w, h),
        ax_path=None,
        role=role,
        ocr_text=label,
        visual_hash=visual_hash,
    )


def test_find_target_match_exact_role_and_label():
    elements = [
        _elem(1, 0, 0, label="Cancel"),
        _elem(5, 100, 200),
        _elem(7, 300, 400, label="Other"),
    ]
    sig = _sig(100, 200)
    hit, drift = find_target_match(sig, elements, drift_radius_px=50)
    assert hit is not None
    assert hit["id"] == 5
    assert drift == 0


def test_find_target_match_drift_within_radius():
    elements = [_elem(5, 130, 230)]  # 30/30 → ~42px drift
    sig = _sig(100, 200)
    hit, drift = find_target_match(sig, elements, drift_radius_px=50)
    assert hit is not None
    assert hit["id"] == 5
    assert 30 <= drift <= 50


def test_find_target_match_drift_beyond_radius():
    elements = [_elem(5, 500, 500)]
    sig = _sig(100, 200)
    hit, drift = find_target_match(sig, elements, drift_radius_px=50)
    assert hit is None
    assert drift is None


def test_find_target_match_label_disambiguates_collision():
    elements = [
        _elem(1, 110, 210, label="WrongOne"),
        _elem(5, 120, 220, label="Send"),
    ]
    sig = _sig(100, 200, label="Send")
    hit, drift = find_target_match(sig, elements, drift_radius_px=50)
    assert hit is not None
    assert hit["id"] == 5


def test_find_target_match_no_role_no_label_fallback_to_bbox():
    elements = [_elem(5, 105, 205, role="?", label="?")]
    sig = _sig(100, 200, role=None, label=None)
    hit, _ = find_target_match(sig, elements, drift_radius_px=50)
    assert hit is not None
