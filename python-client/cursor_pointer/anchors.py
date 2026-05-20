"""Multi-anchor target matching + perception sanity checks.

Pure functions over screenshot bytes + element metadata. No I/O to the
cursor-pointer daemon; the executor wires those together.
"""
from __future__ import annotations

import io
from typing import Optional

import math

from PIL import Image

from cursor_pointer.intent import TargetSig


# ---------------------------------------------------------------------------
# Perceptual hash (8x8 average hash)
# ---------------------------------------------------------------------------
#
# 64 bits = 16 hex chars. Good enough for "did this 100x40 button visually
# change after my click". Cheap to compute (~1ms per ROI). For a stricter
# perceptual hash we'd switch to pHash (DCT-based) — average hash is the
# right v1 trade-off.


def average_hash_hex(
    png_bytes: bytes,
    bbox: Optional[tuple[int, int, int, int]] = None,
) -> str:
    """Compute 8x8 average hash, returned as a 16-char lowercase hex string.

    If ``bbox`` is given, hash only that region (x, y, w, h in pixels).
    Empty / invalid input yields an all-zero hash.
    """
    if not png_bytes:
        return "0" * 16
    try:
        img = Image.open(io.BytesIO(png_bytes))
    except Exception:
        return "0" * 16
    if bbox is not None:
        x, y, w, h = bbox
        x = max(0, x); y = max(0, y)
        w = max(1, w); h = max(1, h)
        right = min(img.width, x + w)
        bottom = min(img.height, y + h)
        if right <= x or bottom <= y:
            return "0" * 16
        img = img.crop((x, y, right, bottom))
    img = img.convert("L").resize((8, 8), Image.BILINEAR)
    pixels = list(img.getdata())
    avg = sum(pixels) / 64.0
    bits = 0
    for i, p in enumerate(pixels):
        if p >= avg:
            bits |= 1 << i
    return f"{bits:016x}"


def hamming_distance_hex(a: str, b: str) -> int:
    """Bit-level Hamming distance between two 16-char hex hashes."""
    if len(a) != len(b):
        return max(len(a), len(b)) * 4
    return bin(int(a, 16) ^ int(b, 16)).count("1")


# ---------------------------------------------------------------------------
# Permission denied (black frame) detection
# ---------------------------------------------------------------------------

def is_permission_denied_frame(png_bytes: bytes) -> bool:
    """Detect Screen Recording permission revoked: empty bytes OR all-black.

    Heuristic over the FULL frame (a black frame's ROI is also black, so we
    can't localize). Threshold: mean < 2 AND stddev < 1 AND non-empty.
    """
    if not png_bytes:
        return True
    try:
        img = Image.open(io.BytesIO(png_bytes))
    except Exception:
        return True
    if img.width <= 0 or img.height <= 0:
        return True
    small = img.convert("L").resize((32, 32), Image.BILINEAR)
    pixels = list(small.getdata())
    n = len(pixels)
    mean = sum(pixels) / n
    var = sum((p - mean) ** 2 for p in pixels) / n
    stddev = var ** 0.5
    return mean < 2.0 and stddev < 1.0


# ---------------------------------------------------------------------------
# Multi-anchor target match
# ---------------------------------------------------------------------------
#
# Given the signature captured at perception time and the freshly-detected
# element list captured at action time, return the element that best matches
# along with the pixel drift (euclidean distance between old and new center).
#
# Match priority within the drift radius:
#   1. role + ocr_text exact equal
#   2. role exact equal AND ocr_text substring of label
#   3. ocr_text exact equal alone
#   4. ax_path equal (if both sides have one)
#   5. closest geometric center


def find_target_match(
    sig: TargetSig,
    elements: list[dict],
    drift_radius_px: int = 50,
) -> tuple[Optional[dict], Optional[int]]:
    sx = sig.bbox[0] + sig.bbox[2] // 2
    sy = sig.bbox[1] + sig.bbox[3] // 2

    candidates: list[tuple[int, int, dict]] = []

    for el in elements:
        ex = el["x"] + el["w"] // 2
        ey = el["y"] + el["h"] // 2
        drift = int(math.hypot(ex - sx, ey - sy))
        if drift > drift_radius_px:
            continue

        priority = 99
        if sig.role and sig.ocr_text and \
                el.get("role") == sig.role and el.get("label") == sig.ocr_text:
            priority = 1
        elif sig.role and el.get("role") == sig.role and sig.ocr_text and \
                sig.ocr_text in (el.get("label") or ""):
            priority = 2
        elif sig.ocr_text and el.get("label") == sig.ocr_text:
            priority = 3
        elif sig.ax_path and tuple(el.get("ax_path") or ()) == sig.ax_path:
            priority = 4
        else:
            priority = 5
        candidates.append((priority, drift, el))

    if not candidates:
        return None, None

    candidates.sort(key=lambda t: (t[0], t[1]))
    _, drift, el = candidates[0]
    return el, drift
