"""OmniParser integration — Microsoft's icon-aware UI element detector.

OmniParser (https://huggingface.co/microsoft/OmniParser-v2.0) is purpose-built
for parsing arbitrary GUI screenshots into a list of interactive elements with
**icon semantics** ("play_button", "search_icon", "menu_dots", …). It is the
right tool when AX is blind (Electron apps, custom-renderer apps) and OCR can
only find text labels — OmniParser identifies *pictorial* buttons too.

The model has two components:

  1. **Icon detection** — YOLOv8 trained on UI screenshots, ~50MB.
     Outputs: list of (bbox, confidence) for visual UI elements.
  2. **Icon captioning** — Florence-2-base finetuned, ~270MB.
     Outputs: short label for each detected icon ("play button").

This script handles both. The model files are loaded lazily so cursor-pointer
keeps working even when OmniParser isn't installed yet.

First-time setup (one-off, ~300MB download):

    pip install ultralytics transformers
    huggingface-cli download microsoft/OmniParser-v2.0 \\
        --local-dir ~/.cache/omniparser

Then:

    python tools/run_omniparser.py

Output flows through ``/ocr/boxes`` like every other detector, so the overlay
draws and the agent loop sees the new elements with `icon` source.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import requests

os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

_YOLO_MODEL = None

API = "http://127.0.0.1:39213"
MODEL_DIR = Path(os.environ.get(
    "OMNIPARSER_DIR",
    str(Path.home() / ".cache" / "omniparser"),
))
DETECTION_WEIGHTS = MODEL_DIR / "icon_detect" / "model.pt"
# OmniParser-v2.0 ships the captioner as `icon_caption/`; older docs say
# `icon_caption_florence`. Prefer whichever exists.
CAPTION_MODEL = (MODEL_DIR / "icon_caption_florence"
                 if (MODEL_DIR / "icon_caption_florence").exists()
                 else MODEL_DIR / "icon_caption")


def have_models() -> bool:
    return DETECTION_WEIGHTS.exists() and CAPTION_MODEL.exists()


def detect_icons(image_path: Path, max_icon_size: int = 160) -> list[dict]:
    """Return [{bbox: [x,y,w,h] physical, score: float}, ...]

    `max_icon_size` filters out large detections (album covers, banner images)
    that aren't real interactive icons — caps captioning latency dramatically.
    Pass 0 to disable the filter.
    """
    try:
        from ultralytics import YOLO  # type: ignore
    except ImportError as e:
        raise RuntimeError(
            "Install `ultralytics` (pip install ultralytics) to use OmniParser detection"
        ) from e

    global _YOLO_MODEL
    if _YOLO_MODEL is None:
        _YOLO_MODEL = YOLO(str(DETECTION_WEIGHTS))
    model = _YOLO_MODEL
    results = model(str(image_path), conf=0.25, iou=0.4, verbose=False)
    items: list[dict] = []
    for r in results:
        boxes = r.boxes
        if boxes is None:
            continue
        for box in boxes:
            xyxy = box.xyxy[0].tolist()
            x0, y0, x1, y1 = map(int, xyxy)
            w, h = x1 - x0, y1 - y0
            if max_icon_size and (w > max_icon_size or h > max_icon_size):
                continue
            items.append({
                "bbox_px": (x0, y0, w, h),
                "score": float(box.conf[0]),
            })
    return items


_CAPTION_CACHE: dict = {}  # process-level cache so we don't reload Florence on every step


def _get_caption_model():
    if "model" in _CAPTION_CACHE:
        return _CAPTION_CACHE["processor"], _CAPTION_CACHE["model"]
    try:
        from transformers import AutoModelForCausalLM, AutoProcessor  # type: ignore
    except ImportError:
        return None, None
    processor = AutoProcessor.from_pretrained("microsoft/Florence-2-base-ft",
                                              trust_remote_code=True)
    model = AutoModelForCausalLM.from_pretrained(
        str(CAPTION_MODEL),
        trust_remote_code=True,
        attn_implementation="eager",
    )
    _CAPTION_CACHE["processor"] = processor
    _CAPTION_CACHE["model"] = model
    return processor, model


def caption_icons(image_path: Path, items: list[dict]) -> list[dict]:
    """Add `label` to each item via Florence-2 caption model.

    Model + processor are cached at module level so subsequent calls within
    the same process are fast (~1.5s per icon vs ~7s for cold load).
    """
    from PIL import Image
    import torch  # type: ignore

    processor, model = _get_caption_model()
    if processor is None or model is None:
        for it in items:
            it["label"] = "icon"
        return items

    img = Image.open(image_path).convert("RGB")
    for it in items:
        x, y, w, h = it["bbox_px"]
        crop = img.crop((x, y, x + w, y + h))
        inputs = processor(text="<CAPTION>", images=crop, return_tensors="pt")
        with torch.no_grad():
            out = model.generate(**inputs, max_new_tokens=20)
        it["label"] = processor.batch_decode(out, skip_special_tokens=True)[0]
    return items


def main() -> int:
    if not have_models():
        print(
            "✗ OmniParser models not found at",
            MODEL_DIR,
            "\n  download with:",
            "\n    pip install ultralytics transformers huggingface_hub",
            "\n    huggingface-cli download microsoft/OmniParser-v2.0 \\",
            "\n        --local-dir ~/.cache/omniparser",
            "\n",
            "\n  or set OMNIPARSER_DIR=<your path>",
        )
        return 1

    # Reuse our screenshot trigger
    sys.path.insert(0, str(Path(__file__).parent))
    from run_ocr import trigger_system_screenshot  # type: ignore

    print("→ system screenshot")
    png = trigger_system_screenshot()
    print(f"  → {png}")

    print("→ OmniParser icon detection")
    t0 = time.time()
    items = detect_icons(png)
    print(f"  → {len(items)} icons in {time.time()-t0:.2f}s")

    print("→ Florence-2 captioning")
    t0 = time.time()
    items = caption_icons(png, items)
    print(f"  → {time.time()-t0:.2f}s")

    # Convert to overlay box format. OmniParser bboxes are in *physical* px.
    mons = requests.get(f"{API}/screen/monitors", timeout=3).json()
    scale = float(mons[0]["scale_factor"] or 2.0)
    mon_x = int(mons[0]["x"])
    mon_y = int(mons[0]["y"])

    boxes = []
    for i, it in enumerate(items, start=1):
        x, y, w, h = it["bbox_px"]
        boxes.append({
            "id": i,
            "x": int(x / scale + mon_x),
            "y": int(y / scale + mon_y),
            "w": int(w / scale),
            "h": int(h / scale),
            "text": f"OMNI: {it.get('label','icon')}",
            "score": float(it.get("score", 0.5)),
            "tier": 2,  # icon detection earns silver tier (no AX confirmation)
        })

    requests.post(f"{API}/ocr/boxes", json={"boxes": boxes, "enable": True}, timeout=5)
    print(f"posted {len(boxes)} icon elements → overlay")
    return 0


if __name__ == "__main__":
    sys.exit(main())
