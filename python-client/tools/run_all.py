"""Unified element detector — runs AX → OCR → visual in sequence, dedupes
overlapping bboxes, and posts a single combined list to the overlay.

Strategy:
  - **AX first** (highest priority). If the focused app exposes its UI, we
    get semantic labels for free.
  - **OCR next**. Anything OCR finds that doesn't already overlap an AX box
    becomes a new element (useful for text inside Electron apps that AX can't
    see).
  - **Visual last**. Pure shape detection catches icons/buttons that have no
    text — only added if they don't overlap an existing box.

The merged list is what the agent loop should iterate over.
"""

from __future__ import annotations

import sys
import time

import requests

# Reuse helpers from the per-source scripts
sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
from run_ocr import trigger_system_screenshot  # noqa: E402
from run_visual import detect_visual_elements   # noqa: E402

API = "http://127.0.0.1:39213"


def iou(a, b):
    ax, ay, aw, ah = a["x"], a["y"], a["w"], a["h"]
    bx, by, bw, bh = b["x"], b["y"], b["w"], b["h"]
    ix0 = max(ax, bx); iy0 = max(ay, by)
    ix1 = min(ax + aw, bx + bw); iy1 = min(ay + ah, by + bh)
    if ix1 <= ix0 or iy1 <= iy0:
        return 0.0
    inter = (ix1 - ix0) * (iy1 - iy0)
    return inter / (aw * ah + bw * bh - inter)


def overlap_ratio(a, b):
    """How much of the smaller box lies inside the bigger one."""
    ax, ay, aw, ah = a["x"], a["y"], a["w"], a["h"]
    bx, by, bw, bh = b["x"], b["y"], b["w"], b["h"]
    ix0 = max(ax, bx); iy0 = max(ay, by)
    ix1 = min(ax + aw, bx + bw); iy1 = min(ay + ah, by + bh)
    if ix1 <= ix0 or iy1 <= iy0:
        return 0.0
    inter = (ix1 - ix0) * (iy1 - iy0)
    smaller = min(aw * ah, bw * bh)
    return inter / smaller if smaller > 0 else 0.0


# Priority order — higher number = preferred kept bbox.
SRC_RANK = {"ax": 3, "ocr": 2, "visual": 1}


def merge_boxes(boxes: list[dict]) -> list[dict]:
    """Cluster boxes by spatial overlap, output one per cluster with combined
    labels. Priorities: AX bbox wins (most semantic), but OCR text is appended
    so we get human-readable labels."""
    boxes = sorted(boxes, key=lambda b: -(b["w"] * b["h"]))  # large first
    used = [False] * len(boxes)
    out: list[dict] = []
    for i, b in enumerate(boxes):
        if used[i]:
            continue
        cluster = [b]
        used[i] = True
        for j in range(i + 1, len(boxes)):
            if used[j]:
                continue
            # merge if IoU > 0.3 OR smaller is 80%+ inside the other
            if iou(b, boxes[j]) > 0.3 or overlap_ratio(b, boxes[j]) > 0.8:
                cluster.append(boxes[j])
                used[j] = True
        # pick representative bbox: highest-priority src, then smallest
        cluster.sort(key=lambda c: (-SRC_RANK.get(c.get("src", ""), 0), c["w"] * c["h"]))
        rep = cluster[0]
        # combine labels — show src tags so the agent knows which is which
        labels = []
        for c in cluster:
            labels.append(c["text"])
        # dedupe text fragments
        seen_txt = []
        for t in labels:
            if t not in seen_txt:
                seen_txt.append(t)
        merged = dict(rep)
        merged["text"] = " | ".join(seen_txt)[:120]
        merged["sources"] = [c.get("src", "?") for c in cluster]
        out.append(merged)
    return out


def collect_ax(target_pid: int | None = None) -> list[dict]:
    """Run AX detector inline. If ``target_pid`` is given, walk that app's
    tree directly instead of trusting ``frontmostApplication`` (which can
    drift after screenshot nudges)."""
    from ApplicationServices import (  # type: ignore
        AXIsProcessTrusted, AXUIElementCreateApplication,
    )
    from Cocoa import NSWorkspace  # type: ignore
    if not AXIsProcessTrusted():
        return []
    from run_ax import walk  # type: ignore

    if target_pid is None:
        front = NSWorkspace.sharedWorkspace().frontmostApplication()
        target_pid = front.processIdentifier()
        name = front.localizedName()
    else:
        name = next(
            (a.localizedName() for a in NSWorkspace.sharedWorkspace().runningApplications()
             if a.processIdentifier() == target_pid),
            "?",
        )
    print(f"   walking AX of: {name} (pid {target_pid})")

    items: list = []
    walk(AXUIElementCreateApplication(target_pid), items)
    boxes = []
    for it in items:
        boxes.append({
            "id": 0,  # assigned later
            "x": it["x"], "y": it["y"], "w": it["w"], "h": it["h"],
            "text": f"AX/{it['role'].removeprefix('AX')}: {it['label']}",
            "score": 1.0,
            "src": "ax",
        })
    return boxes


def collect_ocr(png_path) -> list[dict]:
    import numpy as np
    from PIL import Image
    from rapidocr_onnxruntime import RapidOCR  # type: ignore
    img = Image.open(png_path).convert("RGB")
    ocr = RapidOCR()
    result, _ = ocr(np.array(img))
    mons = requests.get(f"{API}/screen/monitors", timeout=3).json()
    scale = float(mons[0]["scale_factor"] or 2.0)
    mon_x = int(mons[0]["x"]); mon_y = int(mons[0]["y"])
    boxes = []
    for box, text, score in result or []:
        if not text or not text.strip() or (score or 0) < 0.3:
            continue
        xs = [pt[0] for pt in box]; ys = [pt[1] for pt in box]
        x0, y0 = int(min(xs) / scale + mon_x), int(min(ys) / scale + mon_y)
        x1, y1 = int(max(xs) / scale + mon_x), int(max(ys) / scale + mon_y)
        boxes.append({
            "id": 0,
            "x": x0, "y": y0, "w": x1 - x0, "h": y1 - y0,
            "text": f"OCR: {text.strip()[:60]}",
            "score": float(score or 0),
            "src": "ocr",
        })
    return boxes


def collect_visual(png_path) -> list[dict]:
    import cv2
    import numpy as np
    from PIL import Image
    img_pil = Image.open(png_path).convert("RGB")
    img = cv2.cvtColor(np.array(img_pil), cv2.COLOR_RGB2BGR)
    mons = requests.get(f"{API}/screen/monitors", timeout=3).json()
    scale = float(mons[0]["scale_factor"] or 2.0)
    mon_x = int(mons[0]["x"]); mon_y = int(mons[0]["y"])
    rects = detect_visual_elements(img, scale=scale)
    return [{
        "id": 0, "x": x + mon_x, "y": y + mon_y, "w": w, "h": h,
        "text": f"VIS:{w}x{h}", "score": 0.6, "src": "visual",
    } for (x, y, w, h) in rects]


def main() -> int:
    # Remember which app was foreground BEFORE we start (so we can walk its AX
    # tree even after screenshot nudges switch focus).
    from Cocoa import NSWorkspace  # type: ignore
    initial_front = NSWorkspace.sharedWorkspace().frontmostApplication()
    initial_pid = initial_front.processIdentifier()
    print(f"target app: {initial_front.localizedName()} (pid {initial_pid})")

    print("→ system screenshot")
    png_path = trigger_system_screenshot()

    t0 = time.time()
    print("→ AX tree")
    ax_boxes = collect_ax(target_pid=initial_pid)
    print(f"   ax: {len(ax_boxes)}  ({time.time()-t0:.2f}s)")

    t1 = time.time()
    print("→ OCR")
    ocr_boxes = collect_ocr(png_path)
    print(f"   ocr: {len(ocr_boxes)}  ({time.time()-t1:.2f}s)")

    t2 = time.time()
    print("→ visual (opencv)")
    vis_boxes = collect_visual(png_path)
    print(f"   visual: {len(vis_boxes)}  ({time.time()-t2:.2f}s)")

    # Cluster overlapping detections from all sources into one per element.
    all_boxes = ax_boxes + ocr_boxes + vis_boxes
    merged = merge_boxes(all_boxes)

    # Filter to truly actionable / informative elements.
    # Strategy:
    #   • Always keep clusters that have at least one AX node with an
    #     "interactive" role (Button / Link / TextField / etc.).
    #   • Keep OCR-only clusters if the text looks like a label, not noise.
    #   • Drop AX-only clusters where the role is just AXImage / AXStaticText
    #     with no clickable hint.
    #   • Drop pure-visual clusters that overlap nothing else (too noisy).
    INTERACTIVE_AX = {
        "Button", "Link", "TextField", "TextArea", "SearchField",
        "SecureTextField", "ComboBox", "PopUpButton", "CheckBox",
        "RadioButton", "Slider", "MenuItem", "MenuBarItem", "Tab",
        "DisclosureTriangle",
    }
    def is_actionable(b):
        text = b["text"]
        srcs = set(b.get("sources", [b.get("src", "?")]))
        # If AX gave us a hint with an interactive role → always keep
        if "ax" in srcs:
            for role in INTERACTIVE_AX:
                if f"AX/{role}:" in text:
                    return True
            # AX/Image with a real (non-placeholder) label looks clickable for
            # icon-only buttons in Electron apps — keep those too.
            if "AX/Image:" in text:
                # extract the label after "AX/Image:"
                seg = text.split("AX/Image:", 1)[1].split("|", 1)[0].strip()
                if seg and seg != "AXImage" and len(seg) < 40:
                    return True
            return False
        # OCR / visual only
        if "ocr" in srcs:
            # drop very long paragraphs (probably body text, not a button)
            ocr_part = ""
            for chunk in text.split("|"):
                if chunk.strip().startswith("OCR:"):
                    ocr_part = chunk.split("OCR:", 1)[1].strip()
                    break
            if len(ocr_part) > 30:
                return False
            # drop pure numeric or single-char "labels"
            if len(ocr_part) <= 1:
                return False
            return True
        # visual-only — skip (too much noise to be useful by itself)
        return False

    merged = [b for b in merged if is_actionable(b)]
    for i, b in enumerate(merged, start=1):
        b["id"] = i

    by_src = {"ax": 0, "ocr": 0, "visual": 0, "fused": 0}
    for b in merged:
        srcs = set(b.get("sources", [b.get("src", "?")]))
        if len(srcs) > 1:
            by_src["fused"] += 1
        else:
            by_src[next(iter(srcs))] = by_src.get(next(iter(srcs)), 0) + 1
    print(
        f"\nclusters: {len(merged)}  —  "
        f"ax-only={by_src['ax']}  ocr-only={by_src['ocr']}  "
        f"visual-only={by_src['visual']}  fused={by_src['fused']}"
    )

    requests.post(
        f"{API}/ocr/boxes", json={"boxes": merged, "enable": True}, timeout=5
    )
    print("posted → overlay")
    return 0


if __name__ == "__main__":
    sys.exit(main())
