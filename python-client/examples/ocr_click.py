"""OCR-driven click: screenshot → RapidOCR → click the matched text.

Usage:
    python examples/ocr_click.py "Submit"

Install deps:
    pip install -e ".[ocr]"

The CursorPointer app must be running and the host must have granted
Accessibility + Screen Recording permissions.
"""

from __future__ import annotations

import io
import sys
from typing import Optional

import numpy as np
from PIL import Image
from rapidocr_onnxruntime import RapidOCR

from cursor_pointer import CursorPointer


def find_text(ocr_result, target: str) -> Optional[tuple[int, int]]:
    """Return the screen-space center of the first matched OCR box.

    rapidocr returns [(box, text, score), ...] where box is 4 points (x,y).
    """
    target_lc = target.lower()
    for box, text, _score in ocr_result or []:
        if target_lc in (text or "").lower():
            xs = [pt[0] for pt in box]
            ys = [pt[1] for pt in box]
            cx = int(sum(xs) / len(xs))
            cy = int(sum(ys) / len(ys))
            return cx, cy
    return None


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: ocr_click.py <text-to-click>")
        return 2
    target = sys.argv[1]

    cp = CursorPointer()
    cp.health()  # raises if daemon is offline

    monitor = cp.monitors()[0]
    print(f"Capturing monitor {monitor.index}: {monitor.width}x{monitor.height}")

    png = cp.screenshot(monitor=monitor.index)
    img = Image.open(io.BytesIO(png)).convert("RGB")
    arr = np.array(img)

    ocr = RapidOCR()
    result, _elapse = ocr(arr)
    print(f"OCR boxes: {len(result or [])}")

    hit = find_text(result, target)
    if not hit:
        print(f"No OCR match for {target!r}")
        return 1

    # Image space is the raw monitor pixel space. The screenshot may be on
    # a Retina display where image pixels are scale_factor × screen points.
    img_x, img_y = hit
    scale = monitor.scale_factor or 1.0
    screen_x = int(monitor.x + img_x / scale)
    screen_y = int(monitor.y + img_y / scale)

    print(f"Match at image=({img_x},{img_y}) → screen=({screen_x},{screen_y})")
    cp.click(screen_x, screen_y)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
