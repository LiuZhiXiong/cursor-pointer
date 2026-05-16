"""Set-of-Mark (SoM) detector — produces 3 aligned artifacts so a vision LLM
can ground its decisions:

  1. <png>.som.png       annotated screenshot with numbered markers
  2. <png>.elements.json structured manifest: every id's role/label/bbox/
                         parent_id/children/source/tier
  3. <png>.tree.txt      indented element tree, human + LLM readable

The numbered markers on the image **correspond 1:1** to the `id` field in the
JSON manifest. Hand both to a VLM and it can reason about elements by id and
reference their semantic role / label / hierarchy.

Run:

    python tools/run_som.py                       # detect frontmost app
    python tools/run_som.py --post                # also post boxes to overlay
    python tools/run_som.py --out /tmp/myrun      # custom output prefix
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import requests

API = "http://127.0.0.1:39213"

sys.path.insert(0, str(Path(__file__).parent))
from run_ax import walk, CLICKABLE_ROLES  # type: ignore
from run_ocr import trigger_system_screenshot  # type: ignore

# Roles we treat as "leaf" actionable elements. Containers (Group, ScrollArea,
# WebArea, ...) appear in the tree as structural parents but don't get a
# numbered marker on the screenshot.
ACTIONABLE_ROLES = {r for r in CLICKABLE_ROLES} | {"AXStaticText"}


def _main_window_bbox(target_pid: int):
    """Return the target app's main window bbox in logical px, or None."""
    from ApplicationServices import (  # type: ignore
        AXUIElementCreateApplication,
        AXUIElementCopyAttributeValue,
        kAXMainWindowAttribute,
        kAXFocusedWindowAttribute,
        kAXPositionAttribute,
        kAXSizeAttribute,
    )
    app = AXUIElementCreateApplication(target_pid)
    for attr in (kAXMainWindowAttribute, kAXFocusedWindowAttribute):
        err, win = AXUIElementCopyAttributeValue(app, attr, None)
        if err == 0 and win is not None:
            err_p, pos = AXUIElementCopyAttributeValue(win, kAXPositionAttribute, None)
            err_s, size = AXUIElementCopyAttributeValue(win, kAXSizeAttribute, None)
            if err_p == 0 and err_s == 0:
                pr, sr = repr(pos), repr(size)
                def grab(s, label):
                    try:
                        return float(s.split(f"{label}:")[1].split()[0].rstrip("}").rstrip(","))
                    except Exception:
                        return None
                x = grab(pr, "x"); y = grab(pr, "y")
                w = grab(sr, "w") or grab(sr, "width")
                h = grab(sr, "h") or grab(sr, "height")
                if None not in (x, y, w, h):
                    return (int(x), int(y), int(w), int(h))
    return None


def collect(target_pid: int, clip_to_window: bool = True,
            n_passes: int = 1) -> list[dict]:
    """AX walk with parent links + post-process dedup + optional window clipping.

    Pass `n_passes >= 2` to run several AX walks 200ms apart and keep only
    elements that appear at the same bbox in a majority of passes. This
    filters out phantom/loading elements that show up briefly in animations.

    The clipping step is what kills 'messy boxes everywhere' — AX trees can
    leak phantom elements positioned at stale coordinates.
    """
    from ApplicationServices import AXUIElementCreateApplication, AXIsProcessTrusted  # type: ignore

    if not AXIsProcessTrusted():
        print("  ⚠ AX permission missing — collect will return nothing")
        return []

    try:
        win_bbox = _main_window_bbox(target_pid) if clip_to_window else None
    except Exception as e:
        print(f"  ⚠ couldn't read main window bbox ({e}) — no clipping")
        win_bbox = None
    if win_bbox:
        wx, wy, ww, wh = win_bbox
        print(f"  main window: ({wx},{wy}) {ww}x{wh}")

    if n_passes <= 1:
        raw: list[dict] = []
        try:
            walk(AXUIElementCreateApplication(target_pid), raw,
                 include_text=True, include_containers=True)
        except RecursionError:
            print("  ⚠ AX walk hit recursion limit — partial tree")
        except Exception as e:
            print(f"  ⚠ AX walk error ({e}) — partial tree")
    else:
        # Multi-pass: only keep elements appearing in >= ceil(N/2) passes at
        # the same role + bbox (5px tolerance). Use the LAST pass's tree
        # structure (parent_idx) so the final raw list has valid parent links.
        passes: list[list[dict]] = []
        for i in range(n_passes):
            items: list[dict] = []
            try:
                walk(AXUIElementCreateApplication(target_pid), items,
                     include_text=True, include_containers=True)
            except Exception as e:
                print(f"  ⚠ pass {i+1} error: {e}")
            passes.append(items)
            if i < n_passes - 1:
                time.sleep(0.25)
        # Build a "seen counter" keyed by role + bbox-bin
        counter: dict[tuple, int] = {}
        for items in passes:
            seen_this_pass = set()
            for it in items:
                key = (it["role"], it["x"] // 5, it["y"] // 5,
                       it["w"] // 5, it["h"] // 5)
                if key in seen_this_pass:
                    continue
                seen_this_pass.add(key)
                counter[key] = counter.get(key, 0) + 1
        threshold = (n_passes // 2) + 1
        stable_keys = {k for k, c in counter.items() if c >= threshold}
        # Use the last pass as canonical, but rewrite parent_idx so it points
        # into the new filtered list (keep the chain alive by climbing dropped
        # ancestors to the nearest survivor).
        canonical = passes[-1]
        survives = [
            (it["role"], it["x"] // 5, it["y"] // 5,
             it["w"] // 5, it["h"] // 5) in stable_keys
            for it in canonical
        ]
        old_to_new: dict[int, int] = {}
        raw = []
        for old_idx, (it, alive) in enumerate(zip(canonical, survives)):
            if alive:
                old_to_new[old_idx] = len(raw)
                raw.append(dict(it))
        for it in raw:
            p = it["parent_idx"]
            while p >= 0 and p not in old_to_new:
                p = canonical[p]["parent_idx"]
            it["parent_idx"] = old_to_new.get(p, -1)
        dropped = len(canonical) - len(raw)
        print(f"  multi-pass ({n_passes}): kept {len(raw)} stable, dropped {dropped} flickers")

    # ---- Pre-filter: noise rejection (lyrics, empty decorations, nested dupes) ----
    # Count sibling StaticTexts per parent — a parent with many StaticText
    # children is almost certainly a lyrics block / list-of-comments / etc.
    # None of those individual texts are click targets.
    sibling_static_count: dict[int, int] = {}
    for it in raw:
        if it["role"] == "AXStaticText":
            p = it["parent_idx"]
            sibling_static_count[p] = sibling_static_count.get(p, 0) + 1

    # ---- Column detection: a "text column" is ≥4 items at the same x±5,
    # similar w, similar h, distributed vertically. Catches lyrics where
    # each line is wrapped in its own AXGroup (so sibling-count fails).
    # We drop the entire column. Indices into raw[].
    #
    # Exemption: if EVERY item in the column has an AXImage neighbor on the
    # same row (within 40px to the left), it's a nav menu (icon + label)
    # and must be preserved. Lyrics columns lack that icon companion.
    text_like_roles = {"AXStaticText", "AXGroup"}
    column_drop: set[int] = set()
    # Build a quick spatial index of AXImages for the icon-neighbor check.
    images = [it for it in raw if it["role"] == "AXImage"]
    def _has_icon_neighbor(it: dict) -> bool:
        cy = it["y"] + it["h"] / 2
        for im in images:
            im_cy = im["y"] + im["h"] / 2
            if abs(im_cy - cy) > 8:
                continue
            # icon should be left of text, within 40px
            gap = it["x"] - (im["x"] + im["w"])
            if -4 <= gap <= 40:
                return True
        return False

    by_col: dict[tuple[int, int, int], list[int]] = {}
    for i, it in enumerate(raw):
        if it["role"] not in text_like_roles:
            continue
        # bin by (x // 6, w // 30, h // 5) — relaxed grouping
        key = (it["x"] // 6, it["w"] // 30, it["h"] // 5)
        by_col.setdefault(key, []).append(i)
    for _, idxs in by_col.items():
        if len(idxs) < 4:
            continue
        ys = sorted(raw[i]["y"] for i in idxs)
        # require true vertical distribution: y-span > 4 * row height
        span = ys[-1] - ys[0]
        h = max(1, raw[idxs[0]]["h"])
        if span < 4 * h:
            continue
        # Exempt icon-paired columns (nav menus)
        if all(_has_icon_neighbor(raw[i]) for i in idxs):
            continue
        column_drop.update(idxs)

    # filter: must be inside main window, not a giant container, not tiny,
    # not noisy (empty-label decoration, lyrics-style StaticText),
    # and not duplicating an already-seen bbox.
    seen_keys: set[tuple] = set()

    def _kept(it):
        if it["w"] > 1800 or it["h"] > 1500:
            return False
        if it["w"] < 6 or it["h"] < 6:
            return False
        if it["x"] < 0 or it["y"] < 0:
            return False
        if win_bbox:
            wx, wy, ww, wh = win_bbox
            cx = it["x"] + it["w"] / 2
            cy = it["y"] + it["h"] / 2
            # center must be inside the target window's bbox (+8px slack)
            if not (wx - 8 <= cx <= wx + ww + 8 and wy - 8 <= cy <= wy + wh + 8):
                return False

        role = it["role"]
        label = (it.get("label") or "").strip()

        # 1) Lyrics / long-list StaticText: parent with ≥4 StaticText siblings.
        #    None of those individual lines are click targets — they're
        #    rendered text inside a scroll container.
        if role == "AXStaticText":
            if sibling_static_count.get(it["parent_idx"], 0) >= 4:
                return False
            if len(label) <= 1:
                # ":", "-", " " etc. are decorative separators
                return False

        # 2) Empty-label decorations: AXImage / AXGroup with no semantic
        #    label AND role-name-only ("AXImage" / "AXGroup") — pure
        #    visual fluff that pollutes the marker list.
        if role in ("AXImage", "AXGroup"):
            if not label or label == role:
                return False

        # spatial dedup: round to 3px grid, drop if exact same role already seen
        key = (role, it["x"] // 3, it["y"] // 3, it["w"] // 3, it["h"] // 3)
        if key in seen_keys:
            return False
        seen_keys.add(key)
        return True

    keep_map: dict[int, int] = {}  # old idx → new idx
    keep: list[dict] = []
    for i, it in enumerate(raw):
        if i in column_drop:
            continue
        if not _kept(it):
            continue
        keep_map[i] = len(keep)
        keep.append(it)

    # 3) Nested-overlap pass: if A fully contains B and they share role,
    #    drop the larger outer A — the smaller is a more specific click
    #    target. Operates on keep[] before parent reindex.
    def _contains(a, b, slack=2):
        return (a["x"] - slack <= b["x"]
                and a["y"] - slack <= b["y"]
                and a["x"] + a["w"] + slack >= b["x"] + b["w"]
                and a["y"] + a["h"] + slack >= b["y"] + b["h"])

    drop_idx: set[int] = set()
    for i, a in enumerate(keep):
        if i in drop_idx:
            continue
        for j, b in enumerate(keep):
            if i == j or j in drop_idx:
                continue
            if a["role"] != b["role"]:
                continue
            if a["w"] * a["h"] > b["w"] * b["h"] * 1.05 and _contains(a, b):
                drop_idx.add(i)
                break
    if drop_idx:
        # Drop from keep AND from keep_map (raw_idx → keep_idx) so the
        # subsequent parent-reindex (which uses keep_map) stays consistent.
        # We need to rebuild keep_map with new positions.
        new_keep_map: dict[int, int] = {}
        new_keep: list[dict] = []
        old_to_new: dict[int, int] = {}
        for old_keep_idx, it in enumerate(keep):
            if old_keep_idx in drop_idx:
                continue
            new_idx = len(new_keep)
            new_keep.append(it)
            old_to_new[old_keep_idx] = new_idx
        # invert keep_map (raw → old_keep_idx) and rebuild with new indices
        for raw_idx, old_keep_idx in keep_map.items():
            if old_keep_idx in old_to_new:
                new_keep_map[raw_idx] = old_to_new[old_keep_idx]
        keep = new_keep
        keep_map = new_keep_map

    # For each kept element, climb up raw[parent_idx] until we find one that
    # also got kept (or hit the root). After this `parent_idx` points into keep.
    for it in keep:
        p = it["parent_idx"]
        while p >= 0 and p not in keep_map:
            p = raw[p]["parent_idx"]
        it["parent_idx"] = keep_map.get(p, -1)

    # assign stable ids starting from 1; tag clickable vs container
    for i, it in enumerate(keep, start=1):
        it["id"] = i
        it["parent_id"] = (keep[it["parent_idx"]]["id"]
                           if it["parent_idx"] >= 0 else None)
        it["clickable"] = it["role"] in ACTIONABLE_ROLES
    return keep


def build_tree(elements: list[dict]) -> list[dict]:
    """Group children under each parent. Returns list of root nodes."""
    by_id = {e["id"]: dict(e, children=[]) for e in elements}
    roots = []
    for e in elements:
        node = by_id[e["id"]]
        if e["parent_id"] and e["parent_id"] in by_id:
            by_id[e["parent_id"]]["children"].append(node)
        else:
            roots.append(node)
    return roots


def render_tree(roots: list[dict], depth: int = 0) -> str:
    """Indented text tree, one line per element."""
    lines: list[str] = []
    for node in roots:
        role = node["role"].removeprefix("AX")
        label = node["label"][:40].replace("\n", " ")
        bbox = f"({node['x']},{node['y']},{node['w']}x{node['h']})"
        lines.append(f"{'  ' * depth}#{node['id']:>3}  {role:14}  '{label}'  {bbox}")
        if node["children"]:
            lines.append(render_tree(node["children"], depth + 1))
    return "\n".join(line for line in lines if line)


def annotate(png_path: Path, elements: list[dict], scale: float,
             max_width: int = 1600) -> Path:
    """Draw numbered markers on the screenshot."""
    from PIL import Image, ImageDraw, ImageFont
    img = Image.open(png_path).convert("RGB")
    W, H = img.size
    if W > max_width:
        ratio = max_width / W
        img = img.resize((int(W * ratio), int(H * ratio)), Image.LANCZOS)
        scale = scale * ratio

    draw = ImageDraw.Draw(img, "RGBA")
    font = None
    for cand in ("/System/Library/Fonts/SFNS.ttf", "/System/Library/Fonts/Helvetica.ttc"):
        if os.path.exists(cand):
            try:
                font = ImageFont.truetype(cand, 14)
                break
            except Exception:
                pass
    if font is None:
        font = ImageFont.load_default()

    # Only draw markers for clickable leaves — containers stay invisible in
    # the image (they're tree-structure only).
    for e in elements:
        if not e.get("clickable", True):
            continue
        x = int(e["x"] * scale)
        y = int(e["y"] * scale)
        w = int(e["w"] * scale)
        h = int(e["h"] * scale)
        depth = min(e.get("depth", 0), 6)
        r = 236 - depth * 22
        b = 72 + depth * 30
        outline = (r, 72, b, 255)
        draw.rectangle([x, y, x + w, y + h], outline=outline, width=2)
        tag = str(e["id"])
        tw = max(20, 8 * len(tag) + 6)
        draw.rectangle([x, max(0, y - 16), x + tw, y], fill=outline)
        draw.text((x + 3, max(0, y - 16)), tag, fill="white", font=font)
    out = Path(str(png_path)[:-len(png_path.suffix)] + ".som.png")
    img.save(out, "PNG", optimize=True)
    return out


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--post", action="store_true",
                   help="also POST boxes to /ocr/boxes overlay")
    p.add_argument("--out", default=None,
                   help="output prefix (default: alongside the screenshot)")
    args = p.parse_args()

    from Cocoa import NSWorkspace  # type: ignore
    app = NSWorkspace.sharedWorkspace().frontmostApplication()
    pid = app.processIdentifier()
    print(f"target: {app.localizedName()} (pid {pid})")

    print("→ AX walk (with parent links)…")
    t0 = time.time()
    elements = collect(pid)
    print(f"  → {len(elements)} elements in {time.time()-t0:.2f}s")

    print("→ system screenshot…")
    png = trigger_system_screenshot()

    mons = requests.get(f"{API}/screen/monitors", timeout=3).json()
    scale = float(mons[0]["scale_factor"] or 2.0)

    print("→ annotate…")
    img_path = annotate(png, elements, scale=scale)
    print(f"  → {img_path}")

    # output prefix — either user-specified or alongside screenshot.
    # Avoid .with_suffix() because the screenshot filename "截屏2026-05-16 21.01.49.png"
    # has multiple dots and Path treats ".49" as the suffix.
    if args.out:
        prefix_str = args.out
    else:
        prefix_str = str(png)[:-len(png.suffix)]  # strip just ".png"
    prefix = Path(prefix_str)

    # JSON manifest — strip parent_idx (internal), keep parent_id (the public one)
    manifest = []
    for e in elements:
        manifest.append({
            "id": e["id"],
            "role": e["role"].removeprefix("AX"),
            "label": e["label"][:60],
            "bbox": [e["x"], e["y"], e["w"], e["h"]],
            "parent_id": e["parent_id"],
            "depth": e["depth"],
            "clickable": e["clickable"],
            "source": "ax",
        })
    json_path = Path(str(prefix) + ".elements.json")
    json_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    print(f"  → {json_path}")

    # tree text
    roots = build_tree(elements)
    tree_path = Path(str(prefix) + ".tree.txt")
    tree_path.write_text(render_tree(roots))
    print(f"  → {tree_path}")

    if args.post:
        # Only post clickable leaves to overlay (containers stay invisible)
        boxes = []
        for e in elements:
            if not e["clickable"]:
                continue
            tier = 1 if e["depth"] <= 2 else 3
            boxes.append({
                "id": e["id"],
                "x": e["x"], "y": e["y"], "w": e["w"], "h": e["h"],
                "text": f"AX/{e['role'].removeprefix('AX')}: {e['label']}",
                "tier": tier,
            })
        requests.post(f"{API}/ocr/boxes",
                      json={"boxes": boxes, "enable": True}, timeout=5)
        print(f"  → posted {len(boxes)} boxes to overlay")

    print(f"\n3 artifacts ready:")
    print(f"  • image:    {img_path}")
    print(f"  • manifest: {json_path}")
    print(f"  • tree:     {tree_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
