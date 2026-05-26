"""Full autonomous agent — MiniMax VLM as the brain, cursor-pointer as hands.

Loop:
  1. Detect interactive elements (consensus or single AX pass).
  2. Annotate the screenshot with numbered boxes.
  3. Ask MiniMax: "Given the goal, which numbered element do you click next?
     Or are we done?"
  4. Parse the answer → execute (click / type / wait / done).
  5. Repeat.

Run with a goal:

    python tools/run_agent.py "在网易云音乐里换一首歌"
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import textwrap
import time
from pathlib import Path
from typing import Optional

import requests
from cursor_pointer import CursorPointer  # noqa: E402
from cursor_pointer.executor import (  # noqa: E402
    ActionExecutor as _ActionExecutor,
    build_click_intent as _build_click_intent,
    build_type_intent as _build_type_intent,
)
from cursor_pointer.intent import (  # noqa: E402
    ExpectSig as _ExpectSig,
    Intent as _Intent,
    Outcome as _Outcome,
)

# Eager-imported alias so tests can patch `run_agent.trigger_system_screenshot`
# without having to dig into run_ocr. Production code already does this lazy
# import in several places; we just hoist a module-level reference.
try:
    sys.path.insert(0, str(Path(__file__).parent))
    from run_ocr import trigger_system_screenshot  # type: ignore  # noqa: E402
except Exception:
    trigger_system_screenshot = None  # type: ignore

API = "http://127.0.0.1:39213"
TRACE = os.environ.get("CURSOR_POINTER_TRACE") == "1"
LOG_FILE: Optional[Path] = None

# Module-level so verb handlers in execute() can append to the same list
# that main() reads. main() must call history.clear() at the top of each run.
history: list[str] = []

# Multi-step planner state — module-level so the main loop can update and
# helper functions can read. main() resets both at the top of each run.
current_subgoal: str = ""
consec_subgoal_fails: int = 0

# Action-text-based stuck detector (a stronger signal than subgoal-text
# because the VLM tends to rephrase subgoals while reusing the same action).
last_action: str = ""
consec_action_fails: int = 0


def _trace_req(method: str, url: str, note: str = "") -> None:
    if TRACE:
        path = url.replace(API, "")
        print(f"  [cp] {method:4} {path}  {note}")


def _log(msg: str) -> None:
    """Print + persist to LOG_FILE."""
    print(msg, flush=True)
    if LOG_FILE:
        try:
            with open(LOG_FILE, "a") as f:
                f.write(msg + "\n")
        except Exception:
            pass


def _retry(fn, *, tries: int = 3, delay: float = 0.6, label: str = "op"):
    """Call fn() up to `tries` times, sleeping `delay` between attempts.

    Logs each failure with the exception message but doesn't crash until the
    last attempt fails — at which point the original exception bubbles up.
    """
    last_exc = None
    for attempt in range(1, tries + 1):
        try:
            return fn()
        except Exception as e:
            last_exc = e
            _log(f"  ⚠ {label} attempt {attempt}/{tries} failed: {e}")
            if attempt < tries:
                time.sleep(delay)
    raise last_exc  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Closed-loop action contract glue
# ---------------------------------------------------------------------------
#
# Provides the ActionExecutor with screenshot, focused-AX, and just-in-time
# element-detection callbacks. The executor lives behind a module-level
# accessor so tests can monkeypatch it cleanly.

_EXECUTOR_SINGLETON: Optional[_ActionExecutor] = None
_CURRENT_TARGET_PID: Optional[int] = None


def _current_screenshot() -> bytes:
    """PNG of the primary monitor. Empty bytes on failure so the executor's
    permission-denied detector triggers cleanly."""
    try:
        return CursorPointer().screenshot()
    except Exception:
        return b""


def _focused_ax_dict() -> Optional[dict]:
    """Return {role,label,value,id} for the system-wide focused AX element."""
    try:
        from ApplicationServices import (  # type: ignore
            AXUIElementCreateSystemWide,
            AXUIElementCopyAttributeValue,
        )
        sysw = AXUIElementCreateSystemWide()
        err, focused = AXUIElementCopyAttributeValue(
            sysw, "AXFocusedUIElement", None
        )
        if err != 0 or focused is None:
            return None
        out: dict = {}
        for key in ("AXRole", "AXTitle", "AXValue"):
            try:
                e, v = AXUIElementCopyAttributeValue(focused, key, None)
                if e == 0:
                    out[key] = v
            except Exception:
                pass
        return {
            "role": out.get("AXRole"),
            "label": out.get("AXTitle"),
            "value": out.get("AXValue"),
            "id": f"{out.get('AXRole')}|{out.get('AXTitle')}|{id(focused)}",
        }
    except Exception:
        return None


def _set_target_pid_for_executor(pid: Optional[int]) -> None:
    global _CURRENT_TARGET_PID
    _CURRENT_TARGET_PID = pid


def _detect_for_executor() -> list[dict]:
    """Just-in-time element detection for the executor's relocate step."""
    if _CURRENT_TARGET_PID is None:
        return []
    try:
        return detect_elements(_CURRENT_TARGET_PID)
    except Exception:
        return []


def _get_executor() -> _ActionExecutor:
    global _EXECUTOR_SINGLETON
    if _EXECUTOR_SINGLETON is None:
        _EXECUTOR_SINGLETON = _ActionExecutor(
            cp=CursorPointer(),
            screenshot_fn=_current_screenshot,
            ax_press_fn=ax_press_element,
            focused_ax_fn=_focused_ax_dict,
            detect_elements_fn=_detect_for_executor,
        )
    return _EXECUTOR_SINGLETON


def _wrap_legacy_return(result, action_str: str) -> _Outcome:
    """Convert the legacy execute() return value (None | str) into the uniform
    Outcome shape so the planner-side reads one type."""
    placeholder = _Intent(
        kind="click", target=None, payload={}, expect=_ExpectSig(),
        raw_action=action_str,
    )
    if result is None:
        return _Outcome(status="executed_unverified", intent=placeholder)
    if result == "DONE":
        return _Outcome(status="ok", intent=placeholder)
    return _Outcome(status="exec_error", intent=placeholder, error=result)


def _legacy_return_from_outcome(outcome: _Outcome) -> Optional[str]:
    """Reverse of _wrap_legacy_return — converts an Outcome back into the
    None | str | 'DONE' shape the planner-side main loop expects.

    Preserves exact string prefixes the planner pattern-matches on
    (e.g. ``mismatch_target:``).
    """
    if outcome.status in ("ok", "executed_unverified"):
        if outcome.intent.raw_action.lower().startswith("done"):
            return "DONE"
        return None
    if outcome.status == "mismatch_target":
        return f"mismatch_target: {outcome.error or 'target moved'}"
    if outcome.status == "verify_failed":
        return f"verify_failed: {outcome.error or 'no detail'}"
    if outcome.status == "exec_error":
        return outcome.error or "exec_error"
    return outcome.error or f"unknown status: {outcome.status}"


def preflight() -> Optional[str]:
    """Verify everything we need before the loop starts. Returns None on
    success, or a human-readable error string."""
    # 1) cursor-pointer API
    try:
        r = requests.get(f"{API}/screen/monitors", timeout=3)
        if r.status_code != 200:
            return f"cursor-pointer API returned {r.status_code}"
    except Exception as e:
        return f"cursor-pointer not reachable at {API}: {e} — is the app running?"

    # 2) MiniMax mmx CLI on PATH
    mmx_check = subprocess.run(
        ["which", "mmx"], capture_output=True, text=True, timeout=5,
    )
    if mmx_check.returncode != 0:
        return "`mmx` CLI not found on PATH — install minimax-mmx or set up VLM provider"

    # 3) AX trust
    try:
        from ApplicationServices import AXIsProcessTrusted  # type: ignore
        if not AXIsProcessTrusted():
            return ("Accessibility permission missing for this Python interpreter — "
                    "System Settings → Privacy → Accessibility → add "
                    + sys.executable)
    except Exception as e:
        return f"could not check AX trust: {e}"

    # 4) PyObjC NSWorkspace
    try:
        from Cocoa import NSWorkspace  # type: ignore  # noqa
    except Exception as e:
        return f"NSWorkspace import failed: {e}"

    return None


# ---------------------------------------------------------------------------
# Stability + click-quality helpers (algorithms for robust grounding)
# ---------------------------------------------------------------------------

def _ax_view_signature(target_pid: int) -> str:
    """Semantic fingerprint of the current application state — md5 of
    every actionable element's (role, label, bbox). Invariant to screenshot
    preview thumbnails, cursor halo, vinyl record animations, etc.

    If two signatures differ, the application's logical state changed.
    Pure AX read, ~150ms.
    """
    import hashlib
    sys.path.insert(0, str(Path(__file__).parent))
    from run_ax import walk
    from ApplicationServices import AXUIElementCreateApplication  # type: ignore
    items: list = []
    try:
        walk(AXUIElementCreateApplication(target_pid), items,
             include_text=True, include_containers=True)
    except Exception:
        pass
    # Hash every element so a sidebar-tab switch (which changes CONTENT area
    # cards) is reflected. Include bbox so even same-label elements at
    # different positions register as state change.
    parts = [
        f"{it['role']}/{it['label'][:30]}/{it['x']},{it['y']}"
        for it in items
    ]
    return hashlib.md5("|".join(parts).encode()).hexdigest()


def _xcap_screen_bytes(size: tuple = (48, 27)) -> Optional[bytes]:
    """Cheap grayscale bytes of current screen via xcap (~80ms).

    Returns raw 8-bit grayscale bytes at the given size, or None on failure.
    """
    import base64, io
    try:
        from PIL import Image
        r = requests.get(f"{API}/screen/screenshot?monitor=0", timeout=4).json()
        data = r["image"].split(",")[1]
        img = Image.open(io.BytesIO(base64.b64decode(data))).convert("L").resize(size)
        return img.tobytes()
    except Exception:
        return None


def _xcap_screen_signature() -> Optional[str]:
    """Legacy hash sig used by ban-region logic — coarse but exact."""
    import hashlib
    raw = _xcap_screen_bytes(size=(96, 54))
    return hashlib.md5(raw).hexdigest() if raw else None


def _frames_similar(a: Optional[bytes], b: Optional[bytes],
                    threshold: float = 0.985) -> bool:
    """Two frames are 'similar' if ≥98.5% of pixels are within 8 grayscale
    levels of each other. Tolerant to a small spinning vinyl record / clock
    ticking / cursor halo, but catches real page changes (huge diff regions).
    """
    if a is None or b is None or len(a) != len(b):
        return False
    same = sum(1 for x, y in zip(a, b) if abs(x - y) < 8)
    return (same / len(a)) >= threshold


def wait_for_stable(max_wait: float = 1.5, poll: float = 0.3,
                    needed_matches: int = 2) -> bool:
    """Poll screen until `needed_matches` consecutive frames are similar
    (not necessarily identical — tolerates micro-animations like a spinning
    cursor or vinyl record).
    """
    deadline = time.time() + max_wait
    last = None
    matches = 0
    while time.time() < deadline:
        cur = _xcap_screen_bytes()
        if _frames_similar(cur, last):
            matches += 1
            if matches >= needed_matches:
                return True
        else:
            matches = 0
        last = cur
        time.sleep(poll)
    return False


def hover_then_click(cp, x: int, y: int, *, count: int = 1,
                     button: str = "left", dwell: float = 0.25) -> None:
    """Move cursor → dwell to trigger hover state → click.

    Many Electron / web apps reveal the actual click target on hover
    (highlight, tooltip, expanded row). Click without hover often hits a
    transparent layer that does nothing.
    """
    cp.move(x, y)
    time.sleep(dwell)
    cp.click(x, y, count=count, button=button)


def ax_press_element(ax_ref) -> bool:
    """Perform AXPress on a live AXUIElement; True on success.

    Many Electron apps (NeteaseMusic / Slack / Discord …) ignore synthetic
    mouse clicks on sidebar / nav items but respond reliably to AXPress
    because the action goes through the app's own AX handler instead of OS
    event delivery.
    """
    if ax_ref is None:
        return False
    try:
        from ApplicationServices import (  # type: ignore
            AXUIElementCopyActionNames,
            AXUIElementPerformAction,
        )
        err, actions = AXUIElementCopyActionNames(ax_ref, None)
        if err != 0 or not actions or "AXPress" not in actions:
            return False
        return AXUIElementPerformAction(ax_ref, "AXPress") == 0
    except Exception:
        return False


def click_escalation_ax(cp, el: dict, target_pid: int,
                        before_ax_sig: str,
                        reactivate_bundle: Optional[str] = None) -> tuple[bool, str]:
    """AX-semantic escalation: verify via AX state hash, not pixels.

    Strategies (safe — no keyboard shortcuts that could yank focus to
    Spotlight / OS shortcuts):
      1) hover longer + reclick
      2) parent container center
      3) horizontally-expanded sidebar-row click (widens StaticText bbox)

    `reactivate_bundle` is called between strategies so focus stays on the
    target app even if a side-effect popped a different window forward.
    """
    cx, cy = el["x"] + el["w"] // 2, el["y"] + el["h"] // 2

    def _reactivate():
        if reactivate_bundle:
            subprocess.run(
                ["osascript", "-e",
                 f'tell application id "{reactivate_bundle}" to activate'],
                capture_output=True,
            )
            time.sleep(0.2)

    def _check_changed() -> bool:
        return _ax_view_signature(target_pid) != before_ax_sig

    # 1) hover longer + reclick
    _reactivate()
    cp.move(cx, cy)
    time.sleep(0.45)
    cp.click(cx, cy)
    time.sleep(0.8)
    if _check_changed():
        return True, "hover_reclick"

    # 2) parent container center
    parent_bbox = el.get("parent_bbox")
    if parent_bbox:
        _reactivate()
        px = parent_bbox[0] + parent_bbox[2] // 2
        py = parent_bbox[1] + parent_bbox[3] // 2
        cp.move(px, py)
        time.sleep(0.3)
        cp.click(px, py)
        time.sleep(0.8)
        if _check_changed():
            return True, f"parent_click({parent_bbox})"

    # 3) horizontally-expanded click — for sidebar StaticText items where
    # the real clickable region is the full ROW (icon + text). Sweep slightly
    # to the LEFT (where the icon usually sits) since the text is on the right.
    if el.get("role") in ("StaticText", "Image") and el["w"] < 80:
        _reactivate()
        # Click 30px left of the text center → typically lands on the icon-row
        ex = max(el["x"] - 30, cx - 40)
        ey = cy
        cp.move(ex, ey)
        time.sleep(0.3)
        cp.click(ex, ey)
        time.sleep(0.8)
        if _check_changed():
            return True, f"row_left_expand({ex},{ey})"

    return False, "all_strategies_exhausted"


def click_escalation_fuzzy(cp, el: dict, all_boxes: list[dict],
                           before_bytes: bytes) -> tuple[bool, str]:
    """Escalation chain with ⌘⇧3 verification + fuzzy compare.

    Catches the real failure mode: hover halo / vinyl spin don't fool us
    into thinking a strategy worked when only ambient pixels changed.
    """
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).parent))
    from run_ocr import trigger_system_screenshot  # type: ignore

    cx, cy = el["x"] + el["w"] // 2, el["y"] + el["h"] // 2

    def _check_changed() -> bool:
        try:
            png = trigger_system_screenshot()
            return not _frames_similar(_screen_bytes_from_png(png), before_bytes)
        except Exception:
            return False

    # 1) hover longer + reclick
    cp.move(cx, cy)
    time.sleep(0.45)
    cp.click(cx, cy)
    time.sleep(0.9)
    if _check_changed():
        return True, "hover_reclick"

    # 2) parent container center
    parent_bbox = el.get("parent_bbox")
    if parent_bbox:
        px = parent_bbox[0] + parent_bbox[2] // 2
        py = parent_bbox[1] + parent_bbox[3] // 2
        cp.move(px, py)
        time.sleep(0.3)
        cp.click(px, py)
        time.sleep(0.9)
        if _check_changed():
            return True, f"parent_click({parent_bbox})"

    # 3) keyboard
    cp.move(cx, cy)
    time.sleep(0.2)
    cp.click(cx, cy)
    time.sleep(0.3)
    try:
        cp.key("space")
    except Exception:
        pass
    time.sleep(0.9)
    if _check_changed():
        return True, "kbd_space"

    return False, "all_strategies_exhausted"


def click_escalation_syssh(cp, el: dict, all_boxes: list[dict],
                           before_sig: str) -> tuple[bool, str]:
    """Same as click_escalation but uses ⌘⇧3 system screenshot for verification.

    On macOS 26 xcap can only see cursor-pointer's own overlay, so we MUST use
    the system screenshot to know whether the underlying app actually changed.
    Slower (~1.2s per check) but ground-truth.
    """
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).parent))
    from run_ocr import trigger_system_screenshot  # type: ignore

    cx, cy = el["x"] + el["w"] // 2, el["y"] + el["h"] // 2

    def _check_changed() -> bool:
        try:
            png = trigger_system_screenshot()
            return _screen_signature(png) != before_sig
        except Exception:
            return False

    # Strategy 1: hover longer + reclick
    cp.move(cx, cy)
    time.sleep(0.4)
    cp.click(cx, cy)
    time.sleep(0.9)
    if _check_changed():
        return True, "hover_reclick"

    # Strategy 2: parent container center
    parent_bbox = el.get("parent_bbox")
    if parent_bbox:
        px = parent_bbox[0] + parent_bbox[2] // 2
        py = parent_bbox[1] + parent_bbox[3] // 2
        cp.move(px, py)
        time.sleep(0.3)
        cp.click(px, py)
        time.sleep(0.9)
        if _check_changed():
            return True, f"parent_click({parent_bbox})"

    # Strategy 3: keyboard — focus then activate
    cp.move(cx, cy)
    time.sleep(0.2)
    cp.click(cx, cy)
    time.sleep(0.3)
    try:
        cp.key("space")
    except Exception:
        pass
    time.sleep(0.9)
    if _check_changed():
        return True, "kbd_space"

    return False, "all_strategies_exhausted"


def click_escalation(cp, el: dict, all_boxes: list[dict],
                     before_sig: str) -> tuple[bool, str]:
    """If a normal click didn't move the page, try harder:

      1) Hover 400ms + re-click (sometimes one hover isn't enough)
      2) Click the parent container's center (catches Electron 'click the row,
         not the icon')
      3) Keyboard activation: focus then space

    Uses fuzzy frame comparison so a small spinning indicator doesn't fool us
    into thinking a strategy succeeded.

    Returns (success, strategy_used).
    """
    cx, cy = el["x"] + el["w"] // 2, el["y"] + el["h"] // 2
    before = _xcap_screen_bytes()

    def _check_changed() -> bool:
        after = _xcap_screen_bytes()
        return not _frames_similar(before, after)

    # Strategy 1: hover longer + reclick
    cp.move(cx, cy)
    time.sleep(0.4)
    cp.click(cx, cy)
    time.sleep(0.8)
    if _check_changed():
        return True, "hover_reclick"

    # Strategy 2: parent container center
    parent_bbox = el.get("parent_bbox")
    if parent_bbox:
        px = parent_bbox[0] + parent_bbox[2] // 2
        py = parent_bbox[1] + parent_bbox[3] // 2
        cp.move(px, py)
        time.sleep(0.25)
        cp.click(px, py)
        time.sleep(0.8)
        if _check_changed():
            return True, f"parent_click({parent_bbox})"

    # Strategy 3: keyboard — focus then activate
    cp.move(cx, cy)
    time.sleep(0.2)
    cp.click(cx, cy)
    time.sleep(0.3)
    try:
        cp.key("space")
    except Exception:
        pass
    time.sleep(0.7)
    if _check_changed():
        return True, "kbd_space"

    return False, "all_strategies_exhausted"


# ---------------------------------------------------------------------------
# Element detection (lean — single AX pass, fast)
# ---------------------------------------------------------------------------

def _UNUSED_row_merge(items: list[dict]) -> list[dict]:
    """Pair small icons (≤30px) with same-row text labels into wider click rows.

    A small AXImage at (x=200, y=297, w=20, h=21) plus an AXStaticText at
    (x=240, y=295, w=30, h=18) saying "精选" → one combined row element with
    bbox spanning both. This is what makes sidebar tab-switching actually work
    on Electron apps where the icon alone isn't the click target.
    """
    icons = [it for it in items if it["role"] in {"AXImage", "AXButton"}
             and it["w"] <= 30 and it["h"] <= 30]
    texts = [it for it in items if it["role"] == "AXStaticText"]
    if not icons or not texts:
        return items

    merged_ids: set[int] = set()
    used_text: set[int] = set()
    new_rows: list[dict] = []
    for ic_idx, ic in enumerate(icons):
        icx_center_y = ic["y"] + ic["h"] / 2
        # find the closest text to the right, same horizontal band
        best = None
        best_dx = 1e9
        for t_idx, t in enumerate(texts):
            if t_idx in used_text:
                continue
            t_center_y = t["y"] + t["h"] / 2
            if abs(t_center_y - icx_center_y) > max(ic["h"], t["h"]) * 0.9:
                continue
            dx = t["x"] - (ic["x"] + ic["w"])
            if dx < -4 or dx > 120:
                continue
            if dx < best_dx:
                best_dx = dx
                best = (t_idx, t)
        if best is None:
            continue
        t_idx, t = best
        used_text.add(t_idx)
        merged_ids.add(id(ic))
        merged_ids.add(id(t))
        x0 = min(ic["x"], t["x"]) - 4
        y0 = min(ic["y"], t["y"]) - 2
        x1 = max(ic["x"] + ic["w"], t["x"] + t["w"]) + 4
        y1 = max(ic["y"] + ic["h"], t["y"] + t["h"]) + 2
        new_rows.append({
            "role": "AXRow",
            "label": f"{t['label'][:30]} ({ic['label'][:20]})",
            "x": x0, "y": y0, "w": x1 - x0, "h": y1 - y0,
        })

    # Keep originals that didn't merge + add new rows
    kept = [it for it in items if id(it) not in merged_ids]
    return kept + new_rows


def detect_elements(target_pid: int) -> list[dict]:
    """Use SoM collector — clipped to target window, dedup'd, with parent_id.

    Returns clickable leaves only. Each box carries `parent_label` so the LLM
    can disambiguate icon-only Images by their wrapping Group label.
    """
    sys.path.insert(0, str(Path(__file__).parent))
    from run_som import collect

    # 3 passes over ~500ms = phantom/animation filter
    elements = collect(target_pid, clip_to_window=True, n_passes=3)

    by_id = {e["id"]: e for e in elements}
    boxes: list[dict] = []
    for e in elements:
        if not e["clickable"]:
            continue
        parent = by_id.get(e["parent_id"]) if e["parent_id"] else None
        parent_label = ""
        parent_bbox = None
        if parent:
            if parent["label"] and parent["label"] != "AXGroup":
                parent_label = parent["label"][:30]
            # Only carry parent bbox if it's bigger — for escalation strategy
            if parent["w"] > e["w"] or parent["h"] > e["h"]:
                parent_bbox = (parent["x"], parent["y"], parent["w"], parent["h"])
        boxes.append({
            "id": e["id"],
            "x": e["x"], "y": e["y"], "w": e["w"], "h": e["h"],
            "role": e["role"].removeprefix("AX"),
            "label": e["label"][:40],
            "parent_id": e.get("parent_id"),
            "parent_label": parent_label,
            "parent_bbox": parent_bbox,
            # Live AXUIElement for AXPress fast-path; also keep parent's
            # ref so escalation can try AXPress on the container.
            "ax_ref": e.get("ax_ref"),
            "parent_ax_ref": parent.get("ax_ref") if parent else None,
        })

    role_priority = {"Button": 0, "Tab": 0, "Link": 1,
                     "TextField": 2, "SearchField": 2,
                     "RadioButton": 3, "CheckBox": 3,
                     "MenuItem": 4, "MenuBarItem": 5,
                     "StaticText": 6, "Image": 7}

    def _rank(b):
        return (role_priority.get(b["role"], 4), b["w"] * b["h"])
    boxes.sort(key=_rank)
    return boxes


# ---------------------------------------------------------------------------
# Annotation rendering (for the VLM prompt)
# ---------------------------------------------------------------------------

def annotate(png_path: Path, boxes: list[dict], scale: float) -> Path:
    from PIL import Image, ImageDraw, ImageFont
    img = Image.open(png_path).convert("RGB")
    W0, H0 = img.size
    target_w = 1280
    if W0 > target_w:
        ratio = target_w / W0
        img = img.resize((int(W0 * ratio), int(H0 * ratio)), Image.LANCZOS)
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
    for b in boxes:
        x = int(b["x"] * scale); y = int(b["y"] * scale)
        w = int(b["w"] * scale); h = int(b["h"] * scale)
        draw.rectangle([x, y, x + w, y + h], outline=(236, 72, 153, 255), width=2)
        tag = str(b["id"])
        tw = max(20, 8 * len(tag) + 6)
        draw.rectangle([x, max(0, y - 16), x + tw, y], fill=(236, 72, 153, 235))
        draw.text((x + 3, max(0, y - 16)), tag, fill="white", font=font)
    out = png_path.with_suffix(".agent.png")
    img.save(out, "PNG", optimize=True)
    return out


# ---------------------------------------------------------------------------
# MiniMax call
# ---------------------------------------------------------------------------

def _screen_signature(png_path: Path) -> str:
    """Cheap signature of a screenshot — used to detect 'click did nothing'."""
    import hashlib
    from PIL import Image
    img = Image.open(png_path).convert("L").resize((96, 54))
    return hashlib.md5(img.tobytes()).hexdigest()


def _screen_bytes_from_png(png_path: Path, size: tuple = (48, 27)) -> bytes:
    """Coarse grayscale bytes from a saved PNG — for fuzzy frame compare."""
    from PIL import Image
    return Image.open(png_path).convert("L").resize(size).tobytes()


def ask_minimax(image_path: Path, prompt: str) -> str:
    cmd = [
        "mmx", "vision", "describe",
        "--image", str(image_path),
        "--prompt", prompt,
        "--output", "json", "--quiet",
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
    except subprocess.TimeoutExpired:
        raise RuntimeError("mmx timed out after 90s")
    if r.returncode != 0:
        raise RuntimeError(f"mmx failed (code {r.returncode}): {r.stderr.strip()[:200]}")
    try:
        data = json.loads(r.stdout)
        for k in ("reply", "text", "content", "description", "answer", "response"):
            if isinstance(data.get(k), str):
                return data[k]
        if isinstance(data.get("choices"), list) and data["choices"]:
            msg = data["choices"][0].get("message", {})
            if isinstance(msg.get("content"), str):
                return msg["content"]
        return json.dumps(data)
    except json.JSONDecodeError:
        return r.stdout


# ---------------------------------------------------------------------------
# Multi-step planner — sub-goal parsing (worker VLM emits two lines per step)
# ---------------------------------------------------------------------------


def update_subgoal_failure_counter(
    prev_count: int,
    prev_subgoal: str,
    new_subgoal: str,
    step_failed: bool,
) -> int:
    """Return the new consecutive-failure count given last/this sub-goal.

    Rules:
      • Empty prev_subgoal (first step) treats new_subgoal as continuation —
        a failure starts the count at 1.
      • Real sub-goal change (non-empty prev_subgoal differs from new_subgoal)
        always resets to 0, regardless of step_failed.
      • Same sub-goal: increment on fail, reset on success.
    """
    if prev_subgoal and prev_subgoal != new_subgoal:
        return 0
    if step_failed:
        return prev_count + 1
    return 0


def update_action_failure_counter(
    prev_count: int,
    prev_action: str,
    new_action: str,
    step_failed: bool,
) -> int:
    """Same shape as update_subgoal_failure_counter but keyed on the literal
    action text. Catches loops where the VLM rephrases sub-goal but emits
    the same click."""
    if prev_action and prev_action != new_action:
        return 1 if step_failed else 0
    if step_failed:
        return prev_count + 1
    return 0


def build_action_stuck_warning(action: str, consec_fails: int) -> str:
    """Warning emitted when the SAME action text fails 3+ times in a row."""
    if consec_fails < 3:
        return ""
    return (
        f"\n⚠ action {action!r} 已连续 {consec_fails} 步失败（同一动作）。\n"
        f"必须换不同的 action（不同 id 或不同 verb），或考虑 done。\n"
    )


def build_stuck_warning(subgoal: str, consec_fails: int) -> str:
    """Return a non-empty warning to splice into the next-step prompt
    when the VLM is grinding on the same sub-goal."""
    if consec_fails < 3:
        return ""
    return (
        f"\n⚠ sub-goal {subgoal!r} 已连续 {consec_fails} 步失败。\n"
        f"必须换一个 sub-goal 描述，或考虑 done（如目标已完成或无法达成）。\n"
    )


def parse_action_with_subgoal(raw: str) -> tuple[str, str]:
    """Parse the VLM's two-line output.

    Lines:
        subgoal: <free text>
        action:  <click 5 | scroll down | ...>

    Tolerates extra noise lines and missing prefixes — getting an action
    is more important than enforcing the format. Defaults sub-goal to
    "(unspecified)" when missing.
    """
    subgoal = "(unspecified)"
    action = ""
    have_sub = False
    have_act = False

    lines = [ln.strip() for ln in (raw or "").splitlines() if ln.strip()]
    for ln in lines:
        lower = ln.lower()
        if not have_sub and lower.startswith("subgoal:"):
            subgoal = ln.split(":", 1)[1].strip() or "(unspecified)"
            have_sub = True
            continue
        if not have_act and lower.startswith("action:"):
            action = ln.split(":", 1)[1].strip()
            have_act = True
            continue

    if not action:
        for ln in lines:
            if ln.lower().startswith("subgoal:"):
                continue
            action = ln.strip()
            break

    return subgoal, action


# ---------------------------------------------------------------------------
# Goal-aware verification (review the worker VLM's `done` claim)
# ---------------------------------------------------------------------------

REVIEW_PROMPT = """你是一个验收员。Agent 刚才报告任务完成，你要核实。

原始目标：{goal}
Agent 的完成理由：{done_reason}

当前屏幕（图）和可交互元素清单：
{elements}

判断：当前屏幕状态是否真正达成原始目标？

输出格式（严格两行）：
verdict: ok | reject
why: <一句话>
"""


def parse_verdict(raw: str) -> tuple[str, str]:
    """Parse the reviewer VLM's two-line response.

    Default-to-reject on any ambiguity — fail-safe against hallucinated
    `verdict: ok` lines from a confused reviewer.
    """
    verdict = "reject"
    why = (raw or "").strip()[:120]
    for line in (raw or "").splitlines():
        stripped = line.strip()
        lower = stripped.lower()
        if lower.startswith("verdict:"):
            value = stripped.split(":", 1)[1].strip().lower()
            if value.startswith("ok"):
                verdict = "ok"
            elif value.startswith("reject"):
                verdict = "reject"
        elif lower.startswith("why:"):
            why = stripped.split(":", 1)[1].strip()[:200]
    return verdict, why


def verify_done(goal: str, done_reason: str, target_pid: int,
                ask_minimax) -> tuple[str, str]:
    """Re-ground a `done` claim against fresh screen state.

    Returns ("ok", why) only if the reviewer VLM confirms the goal is
    truly achieved. Any failure (screenshot timeout, mmx crash, garbage
    output) returns ("reject", why) — fail-safe.
    """
    try:
        if trigger_system_screenshot is None:
            raise RuntimeError("trigger_system_screenshot unavailable")
        png = trigger_system_screenshot()
    except Exception as e:
        return "reject", f"screenshot failed: {e}"

    try:
        boxes = detect_elements(target_pid)
    except Exception as e:
        return "reject", f"element detection failed: {e}"

    try:
        mons = requests.get(f"{API}/screen/monitors", timeout=3).json()
        scale = float(mons[0]["scale_factor"] or 2.0)
    except Exception:
        scale = 2.0

    try:
        annotated = annotate(png, boxes, scale=scale)
    except Exception as e:
        return "reject", f"annotation failed: {e}"

    elem_lines = []
    for b in boxes[:60]:
        parent_part = f"  ⊂ {b['parent_label']}" if b.get("parent_label") else ""
        elem_lines.append(
            f"  #{b['id']:>3}  {b['role']:14}  '{b['label']}'  ({b['w']}x{b['h']}){parent_part}"
        )
    elements_block = "\n".join(elem_lines) if elem_lines else "(none)"

    prompt = REVIEW_PROMPT.format(
        goal=goal,
        done_reason=done_reason or "(未提供)",
        elements=elements_block,
    )

    try:
        raw = ask_minimax(annotated, prompt)
    except Exception as e:
        return "reject", f"reviewer exception: {e}"

    return parse_verdict(raw)


# ---------------------------------------------------------------------------
# Action parsing / execution
# ---------------------------------------------------------------------------

def execute(action_str: str, boxes: list[dict]) -> Optional[str]:
    """Parse and run one action. Return None on success, error msg on failure.

    All verb dispatch goes through the cursor_pointer.verbs registry.
    """
    from cursor_pointer.verbs import dispatch as _dispatch, VerbContext as _VerbContext
    ctx = _VerbContext(
        cp=CursorPointer(),
        boxes=boxes,
        executor=_get_executor(),
        history=history,
        log=_log,
    )
    outcome = _dispatch(action_str, ctx)
    return _legacy_return_from_outcome(outcome)


# ---------------------------------------------------------------------------
# Goal loop
# ---------------------------------------------------------------------------

from cursor_pointer.verbs import build_grammar_section as _build_grammar

SYSTEM_PROMPT = textwrap.dedent(f"""\
    你是一个能操作 macOS 桌面的自动化 agent。你看到的图片是当前屏幕，
    粉色编号方框是你可以交互的元素（按钮/链接/输入框等）。

    给你一个目标，你每一步必须输出两行：
        subgoal: <一句话描述你这一步想完成的子目标>
        action: <click 5 | scroll down | clipboard write "..." | done ...>

    sub-goal 可以跨步保持不变（推进同一目标），也可以每步换（切换思路）。
    若 prompt 提示 "sub-goal 连续 N 步失败"，必须换 sub-goal 描述。

    action 行的合法语法（任选一个）:

{_build_grammar()}

    重要规则：
      • 严格两行：第一行 subgoal: ...，第二行 action: ...，没有多余行、没有 markdown。
      • 优先 click 真·按钮（圆形 / 实心彩色 / 明显图标），少点装饰文字。
      • 看不清楚就 wait 1。
      • 找不到目标元素时用 `scroll down` 探索；元素清单里已有但部分被截则用 `scroll_to`。
      • 网易云/Electron 类 app 会把视口外元素从清单里删掉，所以靠 `scroll down` 翻页比 `scroll_to` 更通用。
      • 跨 app 复制粘贴的标准做法：`clipboard write "<text>"` → `app <name>` → `click <input_id>` → `key cmd+v`。
      • 任务里出现 URL / 域名 / "搜索" / "网页" / "浏览器" / "打开 https://" 这类信号时，**必须**用 `browser "<task>"` 把整个任务委托给浏览器代理，不要自己 click 浏览器界面。
""")


def main() -> int:
    if len(sys.argv) < 2:
        print('usage: run_agent.py "<目标>" [--max-steps N]')
        return 2
    goal = sys.argv[1]
    max_steps = 5
    if "--max-steps" in sys.argv:
        max_steps = int(sys.argv[sys.argv.index("--max-steps") + 1])

    # Open run log so we can inspect failures after the fact.
    global LOG_FILE
    ts = time.strftime("%Y%m%d_%H%M%S")
    LOG_FILE = Path(f"/tmp/agent_{ts}.log")
    LOG_FILE.write_text(f"goal: {goal}\nstarted: {ts}\n\n")

    # Preflight — fail fast with a clear message
    err = preflight()
    if err:
        _log(f"✗ preflight failed: {err}")
        return 3
    _log("✓ preflight ok (cursor-pointer + mmx + AX permission)")

    from Cocoa import NSWorkspace  # type: ignore
    initial_app = NSWorkspace.sharedWorkspace().frontmostApplication()
    initial_pid = initial_app.processIdentifier()
    bundle_id = initial_app.bundleIdentifier()
    _log(f"agent target app: {initial_app.localizedName()} (pid {initial_pid}, bundle {bundle_id})")
    _log(f"goal: {goal!r}")
    _log(f"log file: {LOG_FILE}\n")

    if not bundle_id:
        _log("✗ target app has no bundle id (probably system process). Aborting.")
        return 4

    sys.path.insert(0, str(Path(__file__).parent))
    from run_ocr import trigger_system_screenshot  # type: ignore

    history.clear()
    global current_subgoal, consec_subgoal_fails, last_action, consec_action_fails
    current_subgoal = ""
    consec_subgoal_fails = 0
    last_action = ""
    consec_action_fails = 0
    last_click_xy: Optional[tuple[int, int]] = None
    total_t0 = time.time()
    # Banned points: list of (cx, cy) we clicked but didn't move state. ids are
    # unstable across passes, so we ban by screen coordinate (with tolerance).
    banned_xy: list[tuple[int, int]] = []
    for step in range(1, max_steps + 1):
        step_t0 = time.time()
        _log(f"\n── step {step}/{max_steps} ──")

        # bring target to front for AX + screenshot
        subprocess.run(
            ["osascript", "-e", f'tell application id "{bundle_id}" to activate'],
            capture_output=True,
        )
        time.sleep(0.6)

        # Wait until the page stops animating/loading before reading elements
        stable = wait_for_stable(max_wait=1.5)
        if not stable:
            _log("  (page still animating after 1.5s — proceeding anyway)")

        # 1. detect
        try:
            boxes = detect_elements(initial_pid)
        except Exception as e:
            _log(f"  ✗ detect_elements failed: {e}")
            time.sleep(1.0)
            continue
        _log(f"  AX: {len(boxes)} clickable leaves")

        # Push to overlay so the user sees the SAME numbered markers that
        # MiniMax is reasoning about. Non-fatal if it fails.
        overlay_boxes = [
            {k: v for k, v in b.items() if k not in ("ax_ref", "parent_ax_ref")}
            | {"text": f"{b['role']}: {b['label']}", "tier": 3}
            for b in boxes
        ]
        try:
            requests.post(f"{API}/ocr/boxes",
                          json={"boxes": overlay_boxes, "enable": True},
                          timeout=2)
        except Exception as e:
            _log(f"  ⚠ overlay post failed (non-fatal): {e}")
        if not boxes:
            _log("  (target app not exposing UI; waiting and retrying)")
            time.sleep(1.5)
            continue

        # 2. screenshot + annotate — both wrapped in retry
        _trace_req("POST", f"{API}/keyboard/key", "(⌘⇧3 — system screenshot)")
        try:
            png = _retry(trigger_system_screenshot, tries=3, delay=0.8,
                         label="trigger_system_screenshot")
        except Exception as e:
            _log(f"  ✗ screenshot failed: {e}")
            continue
        _trace_req("GET", f"{API}/screen/monitors")
        try:
            mons = _retry(
                lambda: requests.get(f"{API}/screen/monitors", timeout=3).json(),
                tries=2, label="get monitors",
            )
            scale = float(mons[0]["scale_factor"] or 2.0)
        except Exception:
            scale = 2.0  # safe fallback for Retina
        try:
            annotated = annotate(png, boxes, scale=scale)
        except Exception as e:
            _log(f"  ✗ annotate failed: {e}")
            continue

        # 3. ask MiniMax — include element semantics so it picks by label, not vibes.
        # Drop boxes whose center is within 20px of a banned point.
        def _is_banned(b):
            cx = b["x"] + b["w"] // 2
            cy = b["y"] + b["h"] // 2
            for bx, by in banned_xy:
                if abs(cx - bx) < 20 and abs(cy - by) < 20:
                    return True
            return False
        visible_boxes = [b for b in boxes if not _is_banned(b)]

        elem_lines = []
        for b in visible_boxes[:80]:
            parent_part = f"  ⊂ {b['parent_label']}" if b.get('parent_label') else ""
            elem_lines.append(
                f"  #{b['id']:>3}  {b['role']:14}  '{b['label']}'  ({b['w']}x{b['h']}){parent_part}"
            )
        elem_section = "\n".join(elem_lines)

        prompt = (
            SYSTEM_PROMPT
            + f"\n\n目标: {goal}\n\n"
            + "屏幕上的可交互元素清单（粉色编号在图里对应）:\n"
            + elem_section
            + "\n\n"
        )
        if history:
            prompt += "已执行的动作:\n" + "\n".join(f"  {h}" for h in history) + "\n\n"
        if banned_xy:
            prompt += f"⚠ 已经点过 {len(banned_xy)} 个位置都没用，换个明显不同的位置\n"
            prompt += "  → 改选更宽的行（role=Row）或换屏幕另一侧的元素\n\n"
        prompt += build_stuck_warning(current_subgoal, consec_subgoal_fails)
        prompt += build_action_stuck_warning(last_action, consec_action_fails)
        prompt += (
            "请优先按标签语义匹配目标（如 精选 / 推荐 / play / search 等），"
            "再用图里的位置确认。如果目标是切换 tab，优先选宽行（w>80）"
            "或带文字标签的 Row 元素，**不要选 icon-only 的 Image**。"
            "按格式输出两行（subgoal: ... 然后 action: ...）:"
        )
        t0 = time.time()
        try:
            raw = _retry(lambda: ask_minimax(annotated, prompt),
                         tries=2, delay=1.5, label="ask_minimax")
        except Exception as e:
            _log(f"  ✗ MiniMax failed after retries: {e} — skipping step")
            continue
        subgoal, action_raw = parse_action_with_subgoal(raw)
        action = action_raw.strip("`*\" ").lstrip("➜→- ")
        _log(f"  → subgoal: {subgoal!r}")
        _log(f"  MiniMax ({time.time()-t0:.1f}s): {action!r}")
        prev_subgoal_for_counter = current_subgoal
        prev_action_for_counter = last_action

        # AX semantic signature is rock-solid — invariant to all UI
        # animations / screenshot preview thumbnails / cursor halo.
        before_ax_sig = _ax_view_signature(initial_pid)
        try:
            before_sig = _screen_signature(png)  # legacy ban map
        except Exception:
            before_sig = ""

        # 4. execute — never let an exception kill the whole loop
        try:
            result = execute(action, boxes)
        except Exception as e:
            _log(f"  ✗ execute crashed: {e}")
            history.append(f"step {step}: [{subgoal}] CRASHED {action} ({e})")
            consec_subgoal_fails = update_subgoal_failure_counter(
                prev_count=consec_subgoal_fails,
                prev_subgoal=prev_subgoal_for_counter,
                new_subgoal=subgoal,
                step_failed=True,
            )
            consec_action_fails = update_action_failure_counter(
                prev_count=consec_action_fails,
                prev_action=prev_action_for_counter,
                new_action=action,
                step_failed=True,
            )
            current_subgoal = subgoal
            last_action = action
            time.sleep(1.0)
            continue

        # 4b. Structured-Outcome reactions (closed-loop action contract).
        outcome = _wrap_legacy_return(result, action_str=action)

        # One-line readable banner so demos / users see what the agent decided
        # and how it landed without parsing verb-specific logs.
        _summary = (
            f"[STEP {step}] {action!s:<40s} → status={outcome.status}"
        )
        if outcome.used_path and outcome.used_path != "none":
            _summary += f" path={outcome.used_path}"
        if outcome.relocate_drift_px is not None:
            _summary += f" drift={outcome.relocate_drift_px}px"
        if outcome.elapsed_ms:
            _summary += f" ({outcome.elapsed_ms}ms)"
        if outcome.error and outcome.status != "ok":
            _summary += f"  — {outcome.error[:60]}"
        _log(_summary)

        if outcome.status == "exec_error" and outcome.error and \
                "permission_denied" in outcome.error:
            _log(f"!! permission denied — halting loop: {outcome.error}")
            return 2
        if isinstance(result, str) and result.startswith("mismatch_target:"):
            # World moved between perception and action; this is not a planner
            # failure — force re-perception by skipping the fail-counter bump.
            _log(f"  ⚠ {result} — re-perception next step, no failure counted")
            history.append(f"step {step}: [{subgoal}] mismatch_target {action}")
            current_subgoal = subgoal
            last_action = action
            continue
        if result == "DONE":
            if os.environ.get("CURSOR_POINTER_VERIFY", "1") == "0":
                _log(f"\n✓ done: {action}  (verifier disabled)  "
                     f"(total {time.time()-total_t0:.1f}s)")
                return 0
            done_reason = action[len("done"):].strip().lstrip(":：") if action.lower().startswith("done") else ""
            _log(f"  → reviewing done claim: '{done_reason}'")
            try:
                verdict, why = verify_done(
                    goal=goal,
                    done_reason=done_reason,
                    target_pid=initial_pid,
                    ask_minimax=ask_minimax,
                )
            except Exception as e:
                verdict, why = "reject", f"verifier crashed: {e}"
            _log(f"  → reviewer verdict={verdict} why='{why}'")
            if verdict == "ok":
                _log(f"\n✓ done verified: {action}  ({why})  "
                     f"(total {time.time()-total_t0:.1f}s)")
                return 0
            history.append(
                f"step {step}: [{subgoal}] rejected hallucinated done ({why})"
            )
            # Reject still counts as a same-subgoal failure so the stuck
            # detector eventually pushes the VLM off a wrong sub-goal.
            consec_subgoal_fails = update_subgoal_failure_counter(
                prev_count=consec_subgoal_fails,
                prev_subgoal=prev_subgoal_for_counter,
                new_subgoal=subgoal,
                step_failed=True,
            )
            consec_action_fails = update_action_failure_counter(
                prev_count=consec_action_fails,
                prev_action=prev_action_for_counter,
                new_action=action,
                step_failed=True,
            )
            current_subgoal = subgoal
            last_action = action
            _log(f"  ⚠ done rejected — continuing main loop")
            continue
        if result is not None:
            _log(f"  ✗ {result}")
            history.append(f"step {step}: [{subgoal}] FAILED {action} ({result})")
            consec_subgoal_fails = update_subgoal_failure_counter(
                prev_count=consec_subgoal_fails,
                prev_subgoal=prev_subgoal_for_counter,
                new_subgoal=subgoal,
                step_failed=True,
            )
            consec_action_fails = update_action_failure_counter(
                prev_count=consec_action_fails,
                prev_action=prev_action_for_counter,
                new_action=action,
                step_failed=True,
            )
            current_subgoal = subgoal
            last_action = action
            if consec_subgoal_fails >= 3:
                _log(f"  ⚠ stuck: subgoal {subgoal!r} failed {consec_subgoal_fails} consecutive steps")
            # If MiniMax wrote unparseable garbage, treat as a "wait 1" and move on
            # rather than burning a step indefinitely.
            if "could not parse" in result or "unknown verb" in result:
                _log(f"  → falling back to wait 1 to recover")
                time.sleep(1.0)
        else:
            history.append(f"step {step}: [{subgoal}] {action} (ok)")
            consec_subgoal_fails = update_subgoal_failure_counter(
                prev_count=consec_subgoal_fails,
                prev_subgoal=prev_subgoal_for_counter,
                new_subgoal=subgoal,
                step_failed=False,
            )
            consec_action_fails = update_action_failure_counter(
                prev_count=consec_action_fails,
                prev_action=prev_action_for_counter,
                new_action=action,
                step_failed=False,
            )
            current_subgoal = subgoal
            last_action = action

        # Post-click verification — AX-only, no screenshot needed.
        if action.startswith(("click", "dclick", "rclick")) and result is None:
            time.sleep(1.0)
            _m = re.search(r"^\s*[dr]?click\s+(\d+)", action, re.IGNORECASE)
            eid = int(_m.group(1)) if _m else None
            el = next((b for b in boxes if b["id"] == eid), None) if eid else None
            if el:
                cx = el["x"] + el["w"] // 2
                cy = el["y"] + el["h"] // 2
                last_click_xy = (cx, cy)
                after_ax_sig = _ax_view_signature(initial_pid)
                if after_ax_sig == before_ax_sig:
                    _log(f"  ⚠ AX state unchanged → escalating…")
                    from cursor_pointer import CursorPointer
                    cp_esc = CursorPointer()
                    success, strat = click_escalation_ax(
                        cp_esc, el, initial_pid,
                        before_ax_sig=before_ax_sig,
                        reactivate_bundle=bundle_id,
                    )
                    if success:
                        _log(f"  ✓ escalation succeeded via {strat}")
                    else:
                        banned_xy.append((cx, cy))
                        _log(f"  ✗ escalation exhausted → banning ({cx},{cy})")
                else:
                    _log(f"  ✓ AX state changed after click (real action)")
        else:
            time.sleep(1.4)

        _log(f"  step took {time.time()-step_t0:.1f}s")

        if len(banned_xy) >= 4:
            _log("\n⚠ too many failed click regions — giving up to avoid infinite loop")
            return 1

    _log(f"\n⚠ stopped after {max_steps} steps  (total {time.time()-total_t0:.1f}s)")
    return 1


if __name__ == "__main__":
    sys.exit(main())
