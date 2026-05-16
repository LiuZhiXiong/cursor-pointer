"""Accessibility-tree based interactive element detector.

Walks the AX tree of the frontmost application, extracts every clickable /
interactive element (buttons, links, text fields, menu items, checkboxes, …)
with its screen bbox and label, and posts them to ``/ocr/boxes`` so the
overlay paints labelled rectangles on top of the real UI.

Requires Accessibility permission for the Python interpreter (you may need
to grant it the first time — System Settings → Privacy → Accessibility).

Run:
    python tools/run_ax.py
"""

from __future__ import annotations

import sys
import time
from typing import Any

import requests
from ApplicationServices import (  # type: ignore
    AXIsProcessTrusted,
    AXUIElementCopyAttributeValue,
    AXUIElementCreateApplication,
    AXUIElementCreateSystemWide,
    kAXChildrenAttribute,
    kAXFocusedApplicationAttribute,
    kAXPositionAttribute,
    kAXRoleAttribute,
    kAXSizeAttribute,
    kAXTitleAttribute,
    kAXDescriptionAttribute,
    kAXValueAttribute,
    kAXHelpAttribute,
)
from Cocoa import NSWorkspace  # type: ignore
from CoreFoundation import CFGetTypeID, CFStringGetTypeID  # type: ignore

API = "http://127.0.0.1:39213"

# Roles we consider "interactive" / clickable.
# Mac apps + Safari/Chrome webpages use a mix of these.
CLICKABLE_ROLES = {
    # Native macOS
    "AXButton",
    "AXMenuItem",
    "AXMenuBarItem",
    "AXLink",
    "AXCheckBox",
    "AXRadioButton",
    "AXPopUpButton",
    "AXTab",
    "AXTextField",
    "AXTextArea",
    "AXSearchField",
    "AXSecureTextField",
    "AXComboBox",
    "AXSlider",
    "AXDisclosureTriangle",
    "AXIncrementor",
    "AXOutline",
    "AXRow",
    "AXCell",
    # Web (Safari/Chrome expose DOM via AX)
    "AXLink",
    "AXButton",
    "AXTextLink",
    "AXListBox",
    "AXList",
    "AXListItem",
    "AXImage",
    "AXVideo",
    "AXAudio",
}

# Containers we recurse THROUGH but don't list as elements themselves.
CONTAINER_ROLES = {
    "AXWindow",
    "AXGroup",
    "AXSplitGroup",
    "AXTabGroup",
    "AXToolbar",
    "AXScrollArea",
    "AXWebArea",
    "AXApplication",
    "AXSheet",
    "AXDrawer",
    "AXStaticText",  # web text — useful as click target sometimes but very noisy
}


def _attr(elem, name) -> Any:
    err, val = AXUIElementCopyAttributeValue(elem, name, None)
    if err != 0:
        return None
    return val


def _str(v) -> str:
    if v is None:
        return ""
    if isinstance(v, str):
        return v
    try:
        s = str(v)
    except Exception:
        return ""
    # PyObjC's str() on opaque AXUIElement objects includes the pointer
    # address, which is non-deterministic across reads. That breaks every
    # AX-based caching/hashing scheme. Reject it.
    if s.startswith("<AXUIElement") or s.startswith("<AXValue"):
        return ""
    return s


def _point_size(elem):
    pos_v = _attr(elem, kAXPositionAttribute)
    size_v = _attr(elem, kAXSizeAttribute)
    if pos_v is None or size_v is None:
        return None
    # AXValue wrappers — extract via repr parsing as a last resort.
    pr = repr(pos_v)
    sr = repr(size_v)
    # repr looks like "<AXValue 0x... {value = x:N y:N type = kAXValueCGPointType}>"
    def grab(s, label):
        try:
            after = s.split(f"{label}:")[1]
            num = after.split()[0].rstrip("}").rstrip(",")
            return float(num)
        except Exception:
            return None

    x = grab(pr, "x")
    y = grab(pr, "y")
    w = grab(sr, "w") or grab(sr, "width")
    h = grab(sr, "h") or grab(sr, "height")
    if None in (x, y, w, h):
        return None
    return (int(x), int(y), int(w), int(h))


def walk(elem, out, depth=0, max_depth=80, monitor_origin=(0, 0),
         include_text=False, parent_idx=-1, include_containers=False):
    """Walk the AX tree.

    Each emitted dict has:
      - role, label, x, y, w, h, depth
      - parent_idx: the index into `out` of the nearest emitted ancestor (-1 if root)
    The caller can rebuild a tree from parent_idx without us doing a second pass.
    """
    if depth > max_depth:
        return
    role = _str(_attr(elem, kAXRoleAttribute))
    if not role:
        return

    emit = (
        role in CLICKABLE_ROLES
        or (include_text and role == "AXStaticText")
        or (include_containers and role in CONTAINER_ROLES)
    )
    my_idx = parent_idx
    if emit:
        ps = _point_size(elem)
        if ps is not None:
            x, y, w, h = ps
            if 2 <= w <= 3000 and 2 <= h <= 2000:
                label = (
                    _str(_attr(elem, kAXTitleAttribute))
                    or _str(_attr(elem, kAXDescriptionAttribute))
                    or _str(_attr(elem, kAXHelpAttribute))
                    or _str(_attr(elem, kAXValueAttribute))
                    or role
                )
                out.append({
                    "role": role,
                    "label": label[:60],
                    "x": x - monitor_origin[0],
                    "y": y - monitor_origin[1],
                    "w": w,
                    "h": h,
                    "depth": depth,
                    "parent_idx": parent_idx,
                    # Live AXUIElement handle — used by AXPress click path.
                    # PyObjC retains it through dict reference; cheap to keep.
                    "ax_ref": elem,
                })
                my_idx = len(out) - 1

    # ALWAYS recurse so we reach AXWebArea subtrees.
    kids = _attr(elem, kAXChildrenAttribute) or []
    for k in kids:
        walk(k, out, depth + 1, max_depth, monitor_origin,
             include_text, my_idx, include_containers)


def main() -> int:
    if not AXIsProcessTrusted():
        print(
            "✗ This Python interpreter lacks Accessibility permission.\n"
            "  System Settings → Privacy → Accessibility → add\n"
            f"  {sys.executable}\n"
            "  then retry."
        )
        return 1

    ws = NSWorkspace.sharedWorkspace()
    front = ws.frontmostApplication()
    pid = front.processIdentifier()
    name = front.localizedName()
    print(f"frontmost: {name} (pid {pid})")

    app_ax = AXUIElementCreateApplication(pid)
    items = []
    t0 = time.time()
    walk(app_ax, items)
    print(f"AX tree walked in {time.time()-t0:.2f}s → {len(items)} interactive elements")

    # dedupe overlapping items, keep the smallest at each spot (more specific)
    seen = {}
    for it in items:
        k = (it["x"] // 5, it["y"] // 5, it["w"] // 5, it["h"] // 5)
        if k not in seen or it["w"] * it["h"] < seen[k]["w"] * seen[k]["h"]:
            seen[k] = it
    items = list(seen.values())
    print(f"after dedupe: {len(items)}")

    # convert to overlay box format. AX positions are already in *logical*
    # screen coords (Cocoa points) so no scale conversion needed.
    boxes = []
    for i, it in enumerate(items, start=1):
        boxes.append({
            "id": i,
            "x": it["x"],
            "y": it["y"],
            "w": it["w"],
            "h": it["h"],
            "text": f"{it['role'].removeprefix('AX')}: {it['label']}",
            "score": 1.0,
        })

    # preview top 10
    for b in boxes[:10]:
        print(f"  #{b['id']:>3}  {b['text']!r:60}  bbox=({b['x']},{b['y']},{b['w']}x{b['h']})")

    r = requests.post(
        f"{API}/ocr/boxes",
        json={"boxes": boxes, "enable": True},
        timeout=5,
    )
    print(f"\nposted {len(boxes)} elements → {r.status_code}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
