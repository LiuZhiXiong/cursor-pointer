"""Bbox edge-snap refinement.

Many of our detected bounding boxes are loose:

  • OCR boxes typically include padding around the text glyph.
  • AX/Image boxes can be for the entire icon container, not just the icon.
  • Visual contours may bleed into the surrounding area.

This module takes a raw screenshot + a candidate bbox and tightens the bbox
to the actual visible feature inside it. The result is a much more precise
click target (better hit-rate on small icons / dense UI).

Approach:
  1. Expand the candidate bbox by a few px so the actual edge is interior.
  2. Convert the crop to grayscale, Canny edge.
  3. Find connected components.
  4. Pick the component closest to the bbox centroid (skips noise on edges).
  5. Return the tight bounding rect of that component.

Falls back to the original bbox if anything looks off.
"""

from __future__ import annotations

from typing import Tuple

import cv2  # type: ignore
import numpy as np

Bbox = Tuple[int, int, int, int]   # x, y, w, h


def refine_bbox(
    img_bgr: np.ndarray,
    bbox: Bbox,
    *,
    scale: float = 2.0,
    padding_px: int = 6,
    min_component_area_ratio: float = 0.05,
) -> Bbox:
    """Tighten a logical-pixel bbox by snapping it to the strongest visual
    component inside an expanded crop.

    Args:
        img_bgr: full physical-pixel screenshot (BGR, opencv convention).
        bbox: (x, y, w, h) in *logical* screen pixels.
        scale: physical/logical ratio (2.0 on Retina).
        padding_px: expand the crop by this many logical px on each side.
        min_component_area_ratio: ignore components smaller than this share
            of the original bbox — pure noise.
    """
    x, y, w, h = bbox
    if w < 4 or h < 4:
        return bbox

    H, W = img_bgr.shape[:2]
    # Convert to physical-pixel rect
    px0 = max(0, int((x - padding_px) * scale))
    py0 = max(0, int((y - padding_px) * scale))
    px1 = min(W, int((x + w + padding_px) * scale))
    py1 = min(H, int((y + h + padding_px) * scale))
    if px1 - px0 < 6 or py1 - py0 < 6:
        return bbox

    crop = img_bgr[py0:py1, px0:px1]
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    # Light blur to merge nearby strokes (letters of a label, parts of an icon)
    blur = cv2.GaussianBlur(gray, (3, 3), 0)
    edges = cv2.Canny(blur, 30, 110)
    # Dilate so a multi-stroke icon (▶ + circle, letter glyphs) merges
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    edges = cv2.dilate(edges, kernel, iterations=1)

    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return bbox

    # Score each contour: prefer (a) large area, (b) close to original centre
    crop_h, crop_w = crop.shape[:2]
    orig_phys_w = w * scale
    orig_phys_h = h * scale
    cx_target = crop_w / 2.0
    cy_target = crop_h / 2.0

    best = None
    best_score = -1.0
    for c in contours:
        bx, by, bw, bh = cv2.boundingRect(c)
        # Filter near-edge slivers (just the crop frame)
        if bw < 4 or bh < 4:
            continue
        if bw * bh < min_component_area_ratio * orig_phys_w * orig_phys_h:
            continue
        if bw >= crop_w - 2 and bh >= crop_h - 2:
            # whole-crop blob = noise
            continue
        cx = bx + bw / 2.0
        cy = by + bh / 2.0
        dist = ((cx - cx_target) ** 2 + (cy - cy_target) ** 2) ** 0.5
        # Score: larger area + closer to centre is better. Normalise distance.
        area_score = (bw * bh) / (crop_w * crop_h)
        center_score = 1.0 - min(dist / max(crop_w, crop_h), 1.0)
        score = 0.55 * area_score + 0.45 * center_score
        if score > best_score:
            best_score = score
            best = (bx, by, bw, bh)

    if best is None:
        return bbox

    bx, by, bw, bh = best
    # Convert physical → logical, restore screen offset
    new_x = int(px0 / scale + bx / scale)
    new_y = int(py0 / scale + by / scale)
    new_w = max(2, int(bw / scale))
    new_h = max(2, int(bh / scale))
    return (new_x, new_y, new_w, new_h)


def refine_boxes(
    img_bgr: np.ndarray,
    boxes: list[dict],
    *,
    scale: float = 2.0,
) -> list[dict]:
    """Apply edge-snap to a whole list of overlay-format box dicts.

    Each dict needs keys: x, y, w, h. Adds:
      - original_bbox: pre-refinement (for debugging)
      - refined: bool (whether the bbox actually changed)
    """
    out: list[dict] = []
    for b in boxes:
        orig = (b["x"], b["y"], b["w"], b["h"])
        try:
            new = refine_bbox(img_bgr, orig, scale=scale)
        except Exception:
            new = orig
        nb = dict(b)
        nb["original_bbox"] = list(orig)
        if new != orig:
            nb["x"], nb["y"], nb["w"], nb["h"] = new
            nb["refined"] = True
        else:
            nb["refined"] = False
        out.append(nb)
    return out
