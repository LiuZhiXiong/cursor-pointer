"""OCR-based Set-of-Mark annotation for the cursor-pointer agent loop.

Take a screenshot → detect text regions via RapidOCR → draw numbered boxes →
return both the annotated image and the element list, addressable by element
id. Coordinates are stored in *logical* screen pixels so that any subsequent
``CursorPointer.click(...)`` lands precisely on the element.

This is the SoM (Set-of-Mark) pattern used by Anthropic Computer Use and
similar agents — feed the annotated image + element list to any multimodal
model, have it pick "element #N", then click it.
"""

from __future__ import annotations

import dataclasses
import io
import json
import os
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

from PIL import Image, ImageDraw, ImageFont

from .client import CursorPointer, Monitor


@dataclass
class Element:
    id: int
    bbox: tuple[int, int, int, int]      # (x0, y0, x1, y1) in *logical* screen px
    text: str
    score: float
    source: str = "ocr"
    # bbox in raw screenshot pixels (handy for re-OCR or debugging)
    bbox_px: tuple[int, int, int, int] = (0, 0, 0, 0)

    @property
    def center(self) -> tuple[int, int]:
        x0, y0, x1, y1 = self.bbox
        return ((x0 + x1) // 2, (y0 + y1) // 2)

    @property
    def width(self) -> int:
        return self.bbox[2] - self.bbox[0]

    @property
    def height(self) -> int:
        return self.bbox[3] - self.bbox[1]

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "bbox": list(self.bbox),
            "bbox_px": list(self.bbox_px),
            "center": list(self.center),
            "text": self.text,
            "score": self.score,
            "source": self.source,
        }


@dataclass
class Annotation:
    id: str
    monitor: Monitor
    elements: list[Element]
    image_path: Path          # annotated PNG on disk (boxes + numbers)
    raw_path: Path            # clean PNG of the original screenshot
    timestamp: float = field(default_factory=time.time)

    def by_id(self, element_id: int) -> Element:
        for e in self.elements:
            if e.id == element_id:
                return e
        raise KeyError(f"no element #{element_id} in annotation {self.id}")

    def find(self, text: str, *, exact: bool = False) -> Optional[Element]:
        """Return the first element whose text matches (case-insensitive)."""
        needle = text.lower().strip()
        for e in self.elements:
            t = e.text.lower().strip()
            if (t == needle) if exact else (needle in t):
                return e
        return None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "timestamp": self.timestamp,
            "monitor": dataclasses.asdict(self.monitor),
            "image_path": str(self.image_path),
            "raw_path": str(self.raw_path),
            "elements": [e.to_dict() for e in self.elements],
        }

    def save_json(self, path: Optional[Path] = None) -> Path:
        path = path or self.image_path.with_suffix(".json")
        path.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2))
        return path


# ---------------------------------------------------------------------------
# OCR backend
# ---------------------------------------------------------------------------

_ocr_singleton = None


def _get_ocr():
    """Lazy-load RapidOCR — heavy import (onnxruntime)."""
    global _ocr_singleton
    if _ocr_singleton is None:
        from rapidocr_onnxruntime import RapidOCR  # type: ignore
        _ocr_singleton = RapidOCR()
    return _ocr_singleton


def _run_ocr(image: Image.Image) -> list[tuple[tuple[int, int, int, int], str, float]]:
    """Return [(bbox_px=(x0,y0,x1,y1), text, score), ...] in screenshot pixel space."""
    import numpy as np
    arr = np.array(image.convert("RGB"))
    ocr = _get_ocr()
    result, _ = ocr(arr)
    out = []
    for box, text, score in result or []:
        xs = [pt[0] for pt in box]
        ys = [pt[1] for pt in box]
        x0, y0, x1, y1 = int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys))
        out.append(((x0, y0, x1, y1), text, float(score)))
    return out


# ---------------------------------------------------------------------------
# Annotation rendering
# ---------------------------------------------------------------------------

def _label_font(size: int) -> ImageFont.ImageFont:
    for cand in (
        "/System/Library/Fonts/SFNS.ttf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
    ):
        if os.path.exists(cand):
            try:
                return ImageFont.truetype(cand, size)
            except Exception:
                continue
    return ImageFont.load_default()


def _draw_annotations(
    image: Image.Image,
    elements: list[Element],
    *,
    scale: float,
) -> Image.Image:
    """Overlay numbered boxes on the screenshot (in screenshot-pixel space)."""
    canvas = image.copy()
    draw = ImageDraw.Draw(canvas, "RGBA")
    font_size = max(14, int(18 * scale))
    font = _label_font(font_size)
    palette = [
        (236, 72, 153),    # pink
        (59, 130, 246),    # blue
        (16, 185, 129),    # green
        (245, 158, 11),    # amber
        (139, 92, 246),    # purple
        (239, 68, 68),     # red
    ]
    for e in elements:
        color = palette[e.id % len(palette)]
        x0, y0, x1, y1 = e.bbox_px
        draw.rectangle([x0, y0, x1, y1], outline=color + (255,), width=max(2, int(2 * scale)))
        # Number tag at top-left
        tag = str(e.id)
        tw = font.getbbox(tag)[2] - font.getbbox(tag)[0] + int(10 * scale)
        th = font.getbbox(tag)[3] - font.getbbox(tag)[1] + int(8 * scale)
        bx0 = x0
        by0 = max(0, y0 - th)
        draw.rectangle([bx0, by0, bx0 + tw, by0 + th], fill=color + (235,))
        draw.text(
            (bx0 + int(5 * scale), by0 + int(2 * scale)),
            tag,
            fill=(255, 255, 255, 255),
            font=font,
        )
    return canvas


# ---------------------------------------------------------------------------
# Public entrypoint
# ---------------------------------------------------------------------------

def annotate(
    client: CursorPointer,
    *,
    monitor: int = 0,
    min_score: float = 0.45,
    save_dir: Optional[Path] = None,
) -> Annotation:
    """Screenshot → OCR → annotated image + element list."""
    monitors = client.monitors()
    mon = next(m for m in monitors if m.index == monitor)
    scale = mon.scale_factor or 1.0

    png = client.screenshot(monitor=monitor)
    raw_img = Image.open(io.BytesIO(png)).convert("RGB")
    boxes = _run_ocr(raw_img)

    elements: list[Element] = []
    for i, (bbox_px, text, score) in enumerate(boxes, start=1):
        if score < min_score:
            continue
        if not text.strip():
            continue
        # Convert screenshot pixels → logical screen pixels
        x0, y0, x1, y1 = bbox_px
        logical = (
            int(mon.x + x0 / scale),
            int(mon.y + y0 / scale),
            int(mon.x + x1 / scale),
            int(mon.y + y1 / scale),
        )
        elements.append(
            Element(
                id=i,
                bbox=logical,
                bbox_px=bbox_px,
                text=text,
                score=score,
            )
        )

    annotated = _draw_annotations(raw_img, elements, scale=scale)
    aid = uuid.uuid4().hex[:10]
    save_dir = Path(save_dir or "/tmp/cursor-pointer-annotations")
    save_dir.mkdir(parents=True, exist_ok=True)
    img_path = save_dir / f"{aid}.png"
    raw_path = save_dir / f"{aid}.raw.png"
    annotated.save(img_path, "PNG", optimize=True)
    raw_img.save(raw_path, "PNG", optimize=True)

    ann = Annotation(
        id=aid,
        monitor=mon,
        elements=elements,
        image_path=img_path,
        raw_path=raw_path,
    )
    ann.save_json()
    return ann


def click_element(
    client: CursorPointer,
    annotation: Annotation,
    element_id: int,
    *,
    button: str = "left",
    count: int = 1,
) -> tuple[int, int]:
    """Click the centre of an annotated element. Returns the (x, y) clicked."""
    el = annotation.by_id(element_id)
    cx, cy = el.center
    client.click(cx, cy, button=button, count=count)
    return cx, cy
