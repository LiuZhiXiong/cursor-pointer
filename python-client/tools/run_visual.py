"""Vision-only UI element detector for apps where macOS AX is blind.

Many third-party apps (Electron, custom renderers like NeteaseMusic / QQ /
WeChat / etc.) don't expose their UI through the macOS Accessibility tree, so
``run_ax.py`` returns nothing useful. This script falls back to pure visual
analysis:

  1. Take a system screenshot (trustworthy regardless of TCC).
  2. Find candidate buttons/cards/icons via:
     - Canny edges + contour extraction (catches bordered controls)
     - MSER region detection (catches stable text/icon blobs)
  3. Filter contours by size (buttons are typically 16-400 logical px wide).
  4. Cluster overlapping detections, keep one per cluster.
  5. POST to /ocr/boxes so the overlay paints them.

Combine with run_ocr.py + run_ax.py for the most complete picture.
"""

from __future__ import annotations

import glob
import os
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import requests
from PIL import Image

API = "http://127.0.0.1:39213"


def trigger_system_screenshot() -> Path:
    """Fire Cmd+Shift+3 (with retry nudges) until a new file lands on Desktop."""
    import subprocess

    desk = Path.home() / "Desktop"
    patterns = ["截屏*.png", "Screen Shot*.png", "Screenshot*.png"]
    def listing():
        out = set()
        for p in patterns:
            out.update(glob.glob(str(desk / p)))
        return out

    # Don't nudge Safari (annoying for the user). Only Finder as fallback.
    for nudge in (None, "Finder"):
        if nudge:
            subprocess.run(
                ["osascript", "-e", f'tell application "{nudge}" to activate'],
                capture_output=True,
            )
            time.sleep(0.8)
        before = listing()
        requests.post(
            f"{API}/keyboard/key",
            json={"key": "3", "modifiers": ["cmd", "shift"]},
            timeout=2,
        )
        deadline = time.time() + 3.5
        while time.time() < deadline:
            new = listing() - before
            if new:
                return Path(max(new, key=os.path.getmtime))
            time.sleep(0.15)
    raise TimeoutError("system screenshot failed")


def detect_visual_elements(img_bgr, scale: float = 2.0) -> list[tuple[int, int, int, int]]:
    """Return [(x, y, w, h), ...] in *logical* pixels for candidate UI regions."""
    h_phys, w_phys = img_bgr.shape[:2]

    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)

    # ---- pass 1: Canny + dilate + contours -------------------------------
    blurred = cv2.GaussianBlur(gray, (3, 3), 0)
    edges = cv2.Canny(blurred, 30, 100)
    # dilate to close gaps so buttons render as one contour
    k = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    edges = cv2.dilate(edges, k, iterations=1)
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    raw = []  # [(x, y, w, h) in physical px]
    for c in contours:
        x, y, w, h = cv2.boundingRect(c)
        # Filter by physical pixel size: between 16 and 500 logical → 32-1000 physical (Retina)
        min_px = int(16 * scale)
        max_w = int(500 * scale)
        max_h = int(200 * scale)
        if not (min_px <= w <= max_w and min_px <= h <= max_h):
            continue
        ar = w / max(1, h)
        if ar < 0.2 or ar > 12:
            continue
        # Skip near-screen-edge giant boxes
        if w * h > 0.2 * w_phys * h_phys:
            continue
        raw.append((x, y, w, h))

    # ---- merge nested / nearly-coincident rectangles ---------------------
    def iou(a, b):
        ax, ay, aw, ah = a
        bx, by, bw, bh = b
        ix0 = max(ax, bx); iy0 = max(ay, by)
        ix1 = min(ax + aw, bx + bw); iy1 = min(ay + ah, by + bh)
        if ix1 <= ix0 or iy1 <= iy0:
            return 0.0
        inter = (ix1 - ix0) * (iy1 - iy0)
        return inter / (aw * ah + bw * bh - inter)

    merged: list[tuple[int, int, int, int]] = []
    raw.sort(key=lambda r: r[2] * r[3])  # small first
    for r in raw:
        # if a larger box overlaps a lot, prefer the smaller (more specific)
        replace_idx = -1
        skip = False
        for i, m in enumerate(merged):
            if iou(r, m) > 0.6:
                # keep whichever is smaller
                if r[2] * r[3] < m[2] * m[3]:
                    replace_idx = i
                else:
                    skip = True
                break
        if skip:
            continue
        if replace_idx >= 0:
            merged[replace_idx] = r
        else:
            merged.append(r)

    # ---- convert to logical pixels ---------------------------------------
    out = []
    for x, y, w, h in merged:
        out.append((int(x / scale), int(y / scale), int(w / scale), int(h / scale)))
    return out


def main() -> int:
    print("triggering screenshot…")
    png_path = trigger_system_screenshot()
    print(f"  → {png_path}")

    monitors = requests.get(f"{API}/screen/monitors", timeout=3).json()
    scale = float(monitors[0]["scale_factor"] or 2.0)
    mon_x = int(monitors[0]["x"])
    mon_y = int(monitors[0]["y"])

    img_pil = Image.open(png_path).convert("RGB")
    img = cv2.cvtColor(np.array(img_pil), cv2.COLOR_RGB2BGR)
    print(f"image: {img.shape[1]}x{img.shape[0]} px (physical); scale={scale}")

    t0 = time.time()
    rects = detect_visual_elements(img, scale=scale)
    print(f"  → {len(rects)} candidate UI regions in {time.time()-t0:.2f}s")

    boxes = []
    for i, (x, y, w, h) in enumerate(rects, start=1):
        boxes.append({
            "id": i,
            "x": x + mon_x,
            "y": y + mon_y,
            "w": w,
            "h": h,
            "text": f"Visual:{w}x{h}",
            "score": 0.6,
        })

    r = requests.post(
        f"{API}/ocr/boxes",
        json={"boxes": boxes, "enable": True},
        timeout=5,
    )
    print(f"posted {len(boxes)} regions → {r.status_code}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
