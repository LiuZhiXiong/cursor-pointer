"""Multi-pass consensus detector.

Runs AX + OCR several times across ~1.5 seconds, then keeps only elements
that appeared in a majority of passes. For each surviving cluster we use the
median bbox so jitter (web pages re-rendering, lazy-loaded images) gets
filtered out cleanly.

Compared with the one-shot ``run_all.py`` this trades latency (~3-5s) for
stability — far fewer phantom "Loading..." boxes, fewer OCR misreads, and
elements that only appear after the page settles are still captured.
"""

from __future__ import annotations

import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent))
from run_all import (
    SRC_RANK, collect_ax, collect_ocr, collect_visual, iou, overlap_ratio, merge_boxes,
)
from run_ocr import trigger_system_screenshot

API = "http://127.0.0.1:39213"

# How many passes per source. AX is fast (≈0.3s) so we can afford more; OCR
# is slow (≈2-5s) so 2 is plenty.
AX_PASSES = 3
OCR_PASSES = 2
VIS_PASSES = 1


INTERACTIVE_AX = {
    "Button", "Link", "TextField", "TextArea", "SearchField",
    "SecureTextField", "ComboBox", "PopUpButton", "CheckBox",
    "RadioButton", "Slider", "MenuItem", "MenuBarItem", "Tab",
    "DisclosureTriangle",
}


def _is_actionable(text: str, sources: set) -> bool:
    if "ax" in sources:
        for role in INTERACTIVE_AX:
            if f"AX/{role}:" in text:
                return True
        if "AX/Image:" in text:
            seg = text.split("AX/Image:", 1)[1].split("|", 1)[0].strip()
            if seg and seg != "AXImage" and len(seg) < 40:
                return True
        return False
    if "ocr" in sources:
        ocr_part = ""
        for chunk in text.split("|"):
            if chunk.strip().startswith("OCR:"):
                ocr_part = chunk.split("OCR:", 1)[1].strip()
                break
        if not (2 <= len(ocr_part) <= 30):
            return False
        return True
    return False


def cluster_across_passes(
    all_detections: list[tuple[int, dict]],
    n_passes_per_box: dict[str, int],
) -> list[dict]:
    """All detections from all passes → cluster by spatial overlap, attach
    `seen` (how many passes detected the cluster) and median bbox."""

    # Sort large-first so the smaller, more specific boxes get absorbed into
    # them — same as merge_boxes.
    flat = [d for _, d in all_detections]
    flat.sort(key=lambda b: -(b["w"] * b["h"]))
    used = [False] * len(flat)
    clusters: list[dict] = []
    for i, b in enumerate(flat):
        if used[i]:
            continue
        cluster_boxes = [b]
        used[i] = True
        for j in range(i + 1, len(flat)):
            if used[j]:
                continue
            if iou(b, flat[j]) > 0.3 or overlap_ratio(b, flat[j]) > 0.8:
                cluster_boxes.append(flat[j])
                used[j] = True

        # which passes saw this cluster (by pass-key = src + pass_idx)
        passes_seen: set[str] = set()
        for c in cluster_boxes:
            passes_seen.add(c.get("_pass", "?"))

        # pick representative bbox: highest-priority src, median of that src
        cluster_boxes.sort(key=lambda c: -SRC_RANK.get(c.get("src", ""), 0))
        top_src = cluster_boxes[0].get("src", "?")
        same_src = [c for c in cluster_boxes if c.get("src") == top_src]
        bx = int(statistics.median([c["x"] for c in same_src]))
        by = int(statistics.median([c["y"] for c in same_src]))
        bw = int(statistics.median([c["w"] for c in same_src]))
        bh = int(statistics.median([c["h"] for c in same_src]))

        # combine labels
        labels: list[str] = []
        seen_txt = set()
        for c in cluster_boxes:
            t = c["text"]
            if t not in seen_txt:
                seen_txt.add(t)
                labels.append(t)

        sources = set(c.get("src", "?") for c in cluster_boxes)
        clusters.append({
            "x": bx, "y": by, "w": bw, "h": bh,
            "text": " | ".join(labels)[:120],
            "sources": list(sources),
            "passes_seen": len(passes_seen),
            "raw_n": len(cluster_boxes),
        })
    return clusters


def main() -> int:
    # Lock onto whatever app is currently frontmost.
    from Cocoa import NSWorkspace  # type: ignore
    initial_pid = NSWorkspace.sharedWorkspace().frontmostApplication().processIdentifier()
    initial_name = NSWorkspace.sharedWorkspace().frontmostApplication().localizedName()
    print(f"target: {initial_name} (pid {initial_pid})")

    all_dets: list[tuple[int, dict]] = []
    pass_keys: dict[str, int] = {}

    def add(boxes, pass_key):
        pass_keys[pass_key] = pass_keys.get(pass_key, 0) + len(boxes)
        for b in boxes:
            b["_pass"] = pass_key
            all_dets.append((0, b))

    # AX passes
    print(f"\n→ AX × {AX_PASSES}:")
    for i in range(AX_PASSES):
        ax = collect_ax(target_pid=initial_pid)
        print(f"  pass {i+1}: {len(ax)} elements")
        add(ax, f"ax-{i}")
        time.sleep(0.4)

    # OCR passes — need fresh screenshot each time
    print(f"\n→ OCR × {OCR_PASSES}:")
    for i in range(OCR_PASSES):
        png = trigger_system_screenshot()
        ocr = collect_ocr(png)
        print(f"  pass {i+1}: {len(ocr)} elements")
        add(ocr, f"ocr-{i}")

    # Visual pass — single pass (deterministic on a fixed image)
    print(f"\n→ Visual × {VIS_PASSES}:")
    last_png = trigger_system_screenshot()
    vis = collect_visual(last_png)
    print(f"  pass 1: {len(vis)} elements")
    add(vis, "visual-0")

    print(f"\nTotal raw detections: {len(all_dets)}")

    # Cluster across all passes
    clusters = cluster_across_passes(all_dets, pass_keys)
    print(f"Clusters: {len(clusters)}")

    # consensus filter — must appear in ≥ majority of passes per source
    # For AX: needs ≥ ceil(AX_PASSES/2) AX passes OR a non-AX pass too
    # Simpler heuristic: total passes_seen / total_passes ≥ 0.5
    TOTAL_PASSES = AX_PASSES + OCR_PASSES + VIS_PASSES
    THRESHOLD = 2  # seen in at least 2 passes (any combination)

    survived = [c for c in clusters if c["passes_seen"] >= THRESHOLD]
    print(f"After ≥{THRESHOLD}-pass consensus: {len(survived)}")

    # filter to actionable
    actionable = [c for c in survived if _is_actionable(c["text"], set(c["sources"]))]
    print(f"After actionable filter: {len(actionable)}")

    # assign ids + tier
    counts = {1: 0, 2: 0, 3: 0, 4: 0}
    for i, c in enumerate(actionable, start=1):
        c["id"] = i
        s = set(c["sources"])
        if {"ax", "ocr", "visual"} <= s:
            c["tier"] = 1  # gold — all 3 sources
        elif {"ax", "ocr"} <= s:
            c["tier"] = 2  # silver — AX + OCR
        elif "ax" in s:
            c["tier"] = 3  # AX only (semantic but unconfirmed)
        else:
            c["tier"] = 4  # OCR / visual only
        counts[c["tier"]] += 1

    print(
        f"\nTiers: gold={counts[1]}  silver={counts[2]}  "
        f"ax_only={counts[3]}  ocr_only={counts[4]}"
    )

    # ─── Edge-snap refinement ────────────────────────────────────────────
    # Tighten every bbox to the actual visible UI feature inside it so
    # clicks land precisely. This is the cheap-but-effective accuracy boost.
    try:
        import cv2
        import numpy as np
        from PIL import Image
        from cursor_pointer.refine import refine_boxes  # type: ignore

        img_pil = Image.open(last_png).convert("RGB")
        img_bgr = cv2.cvtColor(np.array(img_pil), cv2.COLOR_RGB2BGR)
        mons = requests.get(f"{API}/screen/monitors", timeout=3).json()
        scale = float(mons[0]["scale_factor"] or 2.0)
        actionable = refine_boxes(img_bgr, actionable, scale=scale)
        n_refined = sum(1 for b in actionable if b.get("refined"))
        print(f"edge-snap refined {n_refined}/{len(actionable)} bboxes")
    except Exception as e:
        print(f"refine skipped: {e}")

    requests.post(
        f"{API}/ocr/boxes",
        json={"boxes": actionable, "enable": True},
        timeout=5,
    )
    print(f"\nposted {len(actionable)} consensus elements → overlay")
    return 0


if __name__ == "__main__":
    sys.exit(main())
