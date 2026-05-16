"""One-shot OCR runner — fires the system screenshot, OCRs it, POSTs each
detected text element as a bounding box to ``/ocr/boxes`` so the overlay
can paint them on screen.

Triggered by clicking the "OCR 标注" button in the control panel (which calls
``POST /ocr/run`` on the API; that endpoint launches this script).

Run manually:
    python tools/run_ocr.py
"""

from __future__ import annotations

import glob
import os
import re
import sys
import time
from pathlib import Path

import requests
from PIL import Image
import numpy as np
from rapidocr_onnxruntime import RapidOCR

API = "http://127.0.0.1:39213"


def _list_screenshots():
    desk = Path.home() / "Desktop"
    patterns = ["截屏*.png", "Screen Shot*.png", "Screenshot*.png"]
    out = set()
    for p in patterns:
        out.update(glob.glob(str(desk / p)))
    return out


def trigger_system_screenshot() -> Path:
    """Fire Cmd+Shift+3 until a new file appears. Some apps (Finder, certain
    games, Spaces transitions) silently swallow the global shortcut, so we
    retry up to 3 times — each retry pokes a different known-good app to
    frontmost first to make sure the keystroke reaches WindowServer."""
    import subprocess

    # Don't nudge Safari (it disrupts the user's frontmost flow). Only fall
    # back to Finder if the active app silently swallows the shortcut.
    nudges = [None, "Finder"]
    for nudge in nudges:
        if nudge:
            subprocess.run(
                ["osascript", "-e", f'tell application "{nudge}" to activate'],
                capture_output=True,
            )
            time.sleep(0.8)
        before = _list_screenshots()
        requests.post(
            f"{API}/keyboard/key",
            json={"key": "3", "modifiers": ["cmd", "shift"]},
            timeout=2,
        )
        deadline = time.time() + 3.5
        while time.time() < deadline:
            after = _list_screenshots()
            new = after - before
            if new:
                return Path(max(new, key=os.path.getmtime))
            time.sleep(0.15)
    raise TimeoutError("No new screenshot appeared on Desktop after 3 attempts")


def main() -> int:
    print("triggering system screenshot…")
    png_path = trigger_system_screenshot()
    print(f"  → {png_path}")

    img = Image.open(png_path).convert("RGB")
    # Retina: physical pixels = 2 × logical
    monitors = requests.get(f"{API}/screen/monitors", timeout=3).json()
    scale = monitors[0]["scale_factor"] or 2.0
    mon_x = monitors[0]["x"]
    mon_y = monitors[0]["y"]

    print("running OCR…")
    ocr = RapidOCR()
    t0 = time.time()
    result, _ = ocr(np.array(img))
    print(f"  → {len(result or [])} elements in {time.time() - t0:.2f}s")

    boxes = []
    for i, (box, text, score) in enumerate(result or [], start=1):
        if not text or not text.strip():
            continue
        if (score or 0) < 0.3:
            continue
        xs = [pt[0] for pt in box]
        ys = [pt[1] for pt in box]
        x0_px, y0_px = int(min(xs)), int(min(ys))
        x1_px, y1_px = int(max(xs)), int(max(ys))
        # physical → logical
        x0 = int(mon_x + x0_px / scale)
        y0 = int(mon_y + y0_px / scale)
        x1 = int(mon_x + x1_px / scale)
        y1 = int(mon_y + y1_px / scale)
        boxes.append({
            "id": i,
            "x": x0,
            "y": y0,
            "w": x1 - x0,
            "h": y1 - y0,
            "text": text.strip()[:80],
            "score": float(score or 0.0),
        })

    print(f"posting {len(boxes)} boxes to overlay…")
    r = requests.post(
        f"{API}/ocr/boxes",
        json={"boxes": boxes, "enable": True},
        timeout=5,
    )
    print(f"  → {r.status_code}: {r.text}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
