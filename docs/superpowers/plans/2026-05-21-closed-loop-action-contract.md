# Closed-Loop Action Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Introduce `Intent → ActionExecutor → Outcome` contract in the Python agent. Migrate `click` + `type` verbs to it. Replace the planner's None/string success check with structured Outcome branching for all 16 verbs.

**Architecture:** Three new Python modules (`intent.py`, `anchors.py`, `executor.py`) under `python-client/cursor_pointer/`. The executor relocates targets just-in-time, prefers AX-press over pixel clicks, and verifies the expected change happened before returning success. Other 14 verbs keep their legacy bodies but get wrapped to return a uniform `Outcome` so the planner is consistent. **No Rust changes** (see Deviation note below).

**Tech Stack:** Python 3, pyobjc (`ApplicationServices`), Pillow, requests, pytest.

---

## Deviation from spec — no Rust endpoint

The spec called for a new `POST /ax/press` Rust endpoint backed by `objc2-application-services`. **This plan drops that work** because the existing Python code at `python-client/tools/run_agent.py:233-253` already implements `ax_press_element(ax_ref) -> bool` directly via pyobjc's `ApplicationServices` module. Adding a Rust endpoint would duplicate the functionality with zero benefit — the only Python caller would route a pyobjc handle through HTTP and back to the same pyobjc API.

What changes: the executor's "structured-first" step calls `ax_press_element(el["ax_ref"])` directly instead of `cp.ax_press(path)`. No Cargo.toml changes, no `src-tauri/src/ax.rs`, no smoke-test updates.

Spec is otherwise honored as-is.

## File map

| File | Action | Responsibility |
|---|---|---|
| `python-client/cursor_pointer/intent.py` | **Create** | Immutable dataclasses: `TargetSig`, `ExpectSig`, `Intent`, `Outcome` |
| `python-client/cursor_pointer/anchors.py` | **Create** | pHash, AX-focused-element read, multi-anchor match, drift search, permission-denied (black-frame) detection |
| `python-client/cursor_pointer/executor.py` | **Create** | `ActionExecutor` class — relocate / structured-first / pixel-fallback / verify; `IntentBuilder` factory functions |
| `python-client/cursor_pointer/__init__.py` | **Modify** | Lazy-export new symbols |
| `python-client/tools/run_agent.py` | **Modify** | `click`/`type` branches in `execute()` now build Intent + call executor; legacy 14 branches wrapped to return `Outcome`; planner status branching |
| `python-client/tests/test_intent.py` | **Create** | Dataclass round-trip + frozen invariants |
| `python-client/tests/test_anchors.py` | **Create** | pHash, drift search, permission detection |
| `python-client/tests/test_executor.py` | **Create** | Executor unit tests with mocked client + AX |
| `python-client/tests/test_drift.py` | **Create** | Synthetic drift recovery |
| `python-client/tests/test_integration_textedit.py` | **Create** | Opt-in real TextEdit e2e (env `RUN_INTEGRATION=1`) |

`client.py` and `src-tauri/*` are **not** modified.

---

## Task 1: Define data types in `intent.py`

**Files:**
- Create: `python-client/cursor_pointer/intent.py`
- Test: `python-client/tests/test_intent.py`

- [ ] **Step 1: Write the failing test**

Create `python-client/tests/test_intent.py`:

```python
"""Unit tests for Intent / Outcome dataclasses."""
from __future__ import annotations

import pytest

from cursor_pointer.intent import (
    ExpectSig,
    Intent,
    Outcome,
    TargetSig,
)


def _make_target() -> TargetSig:
    return TargetSig(
        element_id=5,
        bbox=(100, 200, 80, 30),
        ax_path=("AXApplication:Mail", "AXButton:Send"),
        role="AXButton",
        ocr_text="Send",
        visual_hash="ab" * 16,
    )


def test_target_sig_frozen():
    t = _make_target()
    with pytest.raises(Exception):
        t.element_id = 7  # type: ignore[misc]


def test_expect_sig_defaults():
    e = ExpectSig()
    assert e.focus_changes is True
    assert e.ax_subtree_changes is False
    assert e.roi_pixel_delta_min == pytest.approx(0.02)
    assert e.typed_text_in_focus is None


def test_intent_carries_raw_action():
    i = Intent(
        kind="click",
        target=_make_target(),
        payload={},
        expect=ExpectSig(),
        raw_action="click 5",
    )
    assert i.kind == "click"
    assert i.raw_action == "click 5"
    assert i.target is not None
    assert i.target.element_id == 5


def test_outcome_default_fields():
    t = _make_target()
    i = Intent(kind="click", target=t, payload={}, expect=ExpectSig(), raw_action="click 5")
    o = Outcome(
        status="ok",
        intent=i,
        elapsed_ms=120,
        relocate_drift_px=3,
        used_path="ax_press",
        before_hash="aa" * 16,
        after_hash="bb" * 16,
        error=None,
    )
    assert o.status == "ok"
    assert o.used_path == "ax_press"
    assert o.error is None
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd python-client && python -m pytest tests/test_intent.py -v
```
Expected: `ModuleNotFoundError: No module named 'cursor_pointer.intent'`

- [ ] **Step 3: Write minimal implementation**

Create `python-client/cursor_pointer/intent.py`:

```python
"""Closed-loop action contract — immutable data types.

These types are used by the executor to convey:
  * Intent: what the agent wants to do, with multi-anchor target evidence
  * Outcome: what happened, structured so the planner can branch on it
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional


@dataclass(frozen=True)
class TargetSig:
    """Multi-anchor signature of an action's target element.

    Captured at perception time. The executor uses it to re-locate the
    element just-in-time (right before acting) and to verify it didn't
    silently move or disappear.
    """
    element_id: int
    bbox: tuple[int, int, int, int]            # (x, y, w, h) logical px
    ax_path: Optional[tuple[str, ...]] = None  # e.g. ("AXApp:Mail","AXButton:Send")
    role: Optional[str] = None
    ocr_text: Optional[str] = None
    visual_hash: str = ""                      # hex pHash of ROI


@dataclass(frozen=True)
class ExpectSig:
    """What the executor should treat as evidence the action worked.

    Any-of semantics: if ANY enabled condition is satisfied after the
    action, verification passes.
    """
    focus_changes: bool = True
    ax_subtree_changes: bool = False
    roi_pixel_delta_min: float = 0.02
    typed_text_in_focus: Optional[str] = None


@dataclass(frozen=True)
class Intent:
    kind: Literal["click", "type"]
    target: Optional[TargetSig]
    payload: dict = field(default_factory=dict)
    expect: ExpectSig = field(default_factory=ExpectSig)
    raw_action: str = ""


OutcomeStatus = Literal[
    "ok",
    "mismatch_target",
    "executed_unverified",
    "verify_failed",
    "exec_error",
]

UsedPath = Literal["ax_press", "pixel", "dom_click", "none"]


@dataclass(frozen=True)
class Outcome:
    status: OutcomeStatus
    intent: Intent
    elapsed_ms: int = 0
    relocate_drift_px: Optional[int] = None
    used_path: UsedPath = "none"
    before_hash: Optional[str] = None
    after_hash: Optional[str] = None
    error: Optional[str] = None
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd python-client && python -m pytest tests/test_intent.py -v
```
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add python-client/cursor_pointer/intent.py python-client/tests/test_intent.py
git commit -m "feat(agent): closed-loop action contract — Intent / Outcome types"
```

---

## Task 2: pHash + permission-denied detection in `anchors.py`

**Files:**
- Create: `python-client/cursor_pointer/anchors.py`
- Test: `python-client/tests/test_anchors.py`

- [ ] **Step 1: Write the failing test**

Create `python-client/tests/test_anchors.py`:

```python
"""Unit tests for anchors module — pHash, permission detection."""
from __future__ import annotations

import io

import pytest
from PIL import Image

from cursor_pointer.anchors import (
    average_hash_hex,
    hamming_distance_hex,
    is_permission_denied_frame,
)


def _png_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_average_hash_same_image_zero_distance():
    img = Image.new("RGB", (200, 200), (128, 64, 200))
    h = average_hash_hex(_png_bytes(img))
    assert hamming_distance_hex(h, h) == 0
    assert len(h) == 16  # 64 bits = 16 hex chars


def test_average_hash_different_images_nonzero_distance():
    a = Image.new("RGB", (200, 200), (10, 10, 10))
    b = Image.new("RGB", (200, 200), (240, 240, 240))
    ha = average_hash_hex(_png_bytes(a))
    hb = average_hash_hex(_png_bytes(b))
    # Pure black vs pure white: every bit should flip → distance 64.
    assert hamming_distance_hex(ha, hb) == 64


def test_average_hash_roi_only():
    """ROI hash should depend only on the cropped region."""
    img = Image.new("RGB", (400, 400), (200, 200, 200))
    # Draw a black rectangle in one corner.
    for x in range(50, 150):
        for y in range(50, 150):
            img.putpixel((x, y), (0, 0, 0))
    h_with_black = average_hash_hex(_png_bytes(img), bbox=(50, 50, 100, 100))
    h_empty_area = average_hash_hex(_png_bytes(img), bbox=(200, 200, 100, 100))
    assert hamming_distance_hex(h_with_black, h_empty_area) > 5


def test_permission_denied_black_frame():
    black = Image.new("RGB", (1280, 800), (0, 0, 0))
    assert is_permission_denied_frame(_png_bytes(black)) is True


def test_permission_denied_normal_frame():
    normal = Image.new("RGB", (1280, 800), (180, 180, 180))
    assert is_permission_denied_frame(_png_bytes(normal)) is False


def test_permission_denied_zero_size():
    assert is_permission_denied_frame(b"") is True
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd python-client && python -m pytest tests/test_anchors.py -v
```
Expected: `ModuleNotFoundError: No module named 'cursor_pointer.anchors'`

- [ ] **Step 3: Write minimal implementation**

Create `python-client/cursor_pointer/anchors.py`:

```python
"""Multi-anchor target matching + perception sanity checks.

Pure functions over screenshot bytes + element metadata. No I/O to the
cursor-pointer daemon; the executor wires those together.
"""
from __future__ import annotations

import io
from typing import Optional

from PIL import Image


# ---------------------------------------------------------------------------
# Perceptual hash (8x8 average hash)
# ---------------------------------------------------------------------------
#
# 64 bits = 16 hex chars. Good enough for "did this 100x40 button visually
# change after my click". Cheap to compute (~1ms per ROI). For a stricter
# perceptual hash we'd switch to pHash (DCT-based) — average hash is the
# right v1 trade-off.


def average_hash_hex(
    png_bytes: bytes,
    bbox: Optional[tuple[int, int, int, int]] = None,
) -> str:
    """Compute 8x8 average hash, returned as a 16-char lowercase hex string.

    If ``bbox`` is given, hash only that region (x, y, w, h in pixels).
    Empty / invalid input yields an all-zero hash.
    """
    if not png_bytes:
        return "0" * 16
    try:
        img = Image.open(io.BytesIO(png_bytes))
    except Exception:
        return "0" * 16
    if bbox is not None:
        x, y, w, h = bbox
        x = max(0, x); y = max(0, y)
        w = max(1, w); h = max(1, h)
        right = min(img.width, x + w)
        bottom = min(img.height, y + h)
        if right <= x or bottom <= y:
            return "0" * 16
        img = img.crop((x, y, right, bottom))
    img = img.convert("L").resize((8, 8), Image.BILINEAR)
    pixels = list(img.getdata())
    avg = sum(pixels) / 64.0
    bits = 0
    for i, p in enumerate(pixels):
        if p >= avg:
            bits |= 1 << i
    return f"{bits:016x}"


def hamming_distance_hex(a: str, b: str) -> int:
    """Bit-level Hamming distance between two 16-char hex hashes."""
    if len(a) != len(b):
        return max(len(a), len(b)) * 4
    return bin(int(a, 16) ^ int(b, 16)).count("1")


# ---------------------------------------------------------------------------
# Permission denied (black frame) detection
# ---------------------------------------------------------------------------

def is_permission_denied_frame(png_bytes: bytes) -> bool:
    """Detect Screen Recording permission revoked: empty bytes OR all-black.

    Heuristic over the FULL frame (a black frame's ROI is also black, so we
    can't localize). Threshold: mean < 2 AND stddev < 1 AND non-empty.
    """
    if not png_bytes:
        return True
    try:
        img = Image.open(io.BytesIO(png_bytes))
    except Exception:
        return True
    if img.width <= 0 or img.height <= 0:
        return True
    small = img.convert("L").resize((32, 32), Image.BILINEAR)
    pixels = list(small.getdata())
    n = len(pixels)
    mean = sum(pixels) / n
    var = sum((p - mean) ** 2 for p in pixels) / n
    stddev = var ** 0.5
    return mean < 2.0 and stddev < 1.0
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd python-client && python -m pytest tests/test_anchors.py -v
```
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add python-client/cursor_pointer/anchors.py python-client/tests/test_anchors.py
git commit -m "feat(agent): anchors — pHash + permission-denied detection"
```

---

## Task 3: Drift-aware target matching in `anchors.py`

**Files:**
- Modify: `python-client/cursor_pointer/anchors.py`
- Modify: `python-client/tests/test_anchors.py`

- [ ] **Step 1: Append failing test**

Append to `python-client/tests/test_anchors.py`:

```python
from cursor_pointer.anchors import find_target_match
from cursor_pointer.intent import TargetSig


def _elem(eid: int, x: int, y: int, w: int = 80, h: int = 30,
          role: str = "AXButton", label: str = "Send") -> dict:
    return {
        "id": eid,
        "x": x, "y": y, "w": w, "h": h,
        "role": role,
        "label": label,
        "ax_ref": object(),  # any non-None marker for ax availability
    }


def _sig(x: int, y: int, w: int = 80, h: int = 30,
         role: str = "AXButton", label: str = "Send",
         visual_hash: str = "0" * 16) -> TargetSig:
    return TargetSig(
        element_id=5,
        bbox=(x, y, w, h),
        ax_path=None,
        role=role,
        ocr_text=label,
        visual_hash=visual_hash,
    )


def test_find_target_match_exact_role_and_label():
    elements = [
        _elem(1, 0, 0, label="Cancel"),
        _elem(5, 100, 200),  # the target
        _elem(7, 300, 400, label="Other"),
    ]
    sig = _sig(100, 200)
    hit, drift = find_target_match(sig, elements, drift_radius_px=50)
    assert hit is not None
    assert hit["id"] == 5
    assert drift == 0


def test_find_target_match_drift_within_radius():
    elements = [_elem(5, 130, 230)]  # moved 30px right + 30px down
    sig = _sig(100, 200)
    hit, drift = find_target_match(sig, elements, drift_radius_px=50)
    assert hit is not None
    assert hit["id"] == 5
    # center moved 30,30 → euclidean ~ 42
    assert 30 <= drift <= 50


def test_find_target_match_drift_beyond_radius():
    elements = [_elem(5, 500, 500)]  # way off
    sig = _sig(100, 200)
    hit, drift = find_target_match(sig, elements, drift_radius_px=50)
    assert hit is None
    assert drift is None


def test_find_target_match_label_disambiguates_collision():
    # Two elements within drift radius — picker prefers exact label match.
    elements = [
        _elem(1, 110, 210, label="WrongOne"),
        _elem(5, 120, 220, label="Send"),
    ]
    sig = _sig(100, 200, label="Send")
    hit, drift = find_target_match(sig, elements, drift_radius_px=50)
    assert hit is not None
    assert hit["id"] == 5


def test_find_target_match_no_role_no_label_fallback_to_bbox():
    elements = [_elem(5, 105, 205, role="?", label="?")]
    sig = _sig(100, 200, role=None, label=None)
    hit, _ = find_target_match(sig, elements, drift_radius_px=50)
    assert hit is not None
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd python-client && python -m pytest tests/test_anchors.py -v
```
Expected: ImportError on `find_target_match`.

- [ ] **Step 3: Append implementation**

Append to `python-client/cursor_pointer/anchors.py`:

```python
# ---------------------------------------------------------------------------
# Multi-anchor target match
# ---------------------------------------------------------------------------
#
# Given the signature captured at perception time and the freshly-detected
# element list captured at action time, return the element that best matches
# along with the pixel drift (euclidean distance between old and new center).
#
# Match priority within the drift radius:
#   1. role + ocr_text exact equal
#   2. role exact equal AND label substring match
#   3. ocr_text exact equal alone
#   4. ax_path equal (if both sides have one)
#   5. closest geometric center
#
# Whichever yields the smallest drift wins.

import math


def find_target_match(
    sig: "TargetSig",  # noqa: F821  — forward ref for typing
    elements: list[dict],
    drift_radius_px: int = 50,
) -> tuple[Optional[dict], Optional[int]]:
    sx = sig.bbox[0] + sig.bbox[2] // 2
    sy = sig.bbox[1] + sig.bbox[3] // 2

    candidates: list[tuple[int, int, dict]] = []  # (priority, drift, elem)

    for el in elements:
        ex = el["x"] + el["w"] // 2
        ey = el["y"] + el["h"] // 2
        drift = int(math.hypot(ex - sx, ey - sy))
        if drift > drift_radius_px:
            continue

        priority = 99
        if sig.role and sig.ocr_text and \
                el.get("role") == sig.role and el.get("label") == sig.ocr_text:
            priority = 1
        elif sig.role and el.get("role") == sig.role and sig.ocr_text and \
                sig.ocr_text in (el.get("label") or ""):
            priority = 2
        elif sig.ocr_text and el.get("label") == sig.ocr_text:
            priority = 3
        elif sig.ax_path and tuple(el.get("ax_path") or ()) == sig.ax_path:
            priority = 4
        else:
            priority = 5
        candidates.append((priority, drift, el))

    if not candidates:
        return None, None

    candidates.sort(key=lambda t: (t[0], t[1]))
    _, drift, el = candidates[0]
    return el, drift
```

Also add the import at the top of the file (just below `from PIL import Image`):

```python
# Forward-import only used by type hints / runtime check in find_target_match.
# Avoid circular import at module-load by inlining below.
from cursor_pointer.intent import TargetSig  # noqa: E402,F401
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd python-client && python -m pytest tests/test_anchors.py -v
```
Expected: all (6 from Task 2 + 5 from Task 3) = 11 passed.

- [ ] **Step 5: Commit**

```bash
git add python-client/cursor_pointer/anchors.py python-client/tests/test_anchors.py
git commit -m "feat(agent): drift-aware multi-anchor target matching"
```

---

## Task 4: `ActionExecutor` skeleton + `__init__.py` export

**Files:**
- Create: `python-client/cursor_pointer/executor.py`
- Modify: `python-client/cursor_pointer/__init__.py`
- Test: `python-client/tests/test_executor.py`

- [ ] **Step 1: Write the failing test**

Create `python-client/tests/test_executor.py`:

```python
"""Unit tests for ActionExecutor — skeleton + construction.

Uses mocks for CursorPointer + screenshot source + AX press so tests can
run without the desktop daemon or pyobjc.
"""
from __future__ import annotations

import io
from unittest.mock import MagicMock

import pytest
from PIL import Image

from cursor_pointer.executor import ActionExecutor


def _png(w: int = 200, h: int = 200, color=(180, 180, 180)) -> bytes:
    img = Image.new("RGB", (w, h), color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_executor_constructs_with_dependencies():
    cp = MagicMock()
    screenshot_fn = MagicMock(return_value=_png())
    ax_press = MagicMock(return_value=False)
    focused_ax = MagicMock(return_value=None)

    ex = ActionExecutor(
        cp=cp,
        screenshot_fn=screenshot_fn,
        ax_press_fn=ax_press,
        focused_ax_fn=focused_ax,
    )
    assert ex is not None
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd python-client && python -m pytest tests/test_executor.py -v
```
Expected: `ModuleNotFoundError: No module named 'cursor_pointer.executor'`

- [ ] **Step 3: Write minimal implementation**

Create `python-client/cursor_pointer/executor.py`:

```python
"""Closed-loop action executor.

Each call to ``execute(intent)`` runs:
  1. relocate   — re-perceive, find the target by signature
  2. structured — try AX press first if available
  3. fallback   — pixel click otherwise
  4. verify     — confirm the expected change happened

All failure modes are returned as ``Outcome`` values; no exceptions cross
the executor boundary except for programmer errors.
"""
from __future__ import annotations

import time
from typing import Callable, Optional

from .intent import ExpectSig, Intent, Outcome, TargetSig


class ActionExecutor:
    def __init__(
        self,
        cp,                                       # CursorPointer
        screenshot_fn: Callable[[], bytes],
        ax_press_fn: Callable[[object], bool],
        focused_ax_fn: Callable[[], Optional[dict]],
        detect_elements_fn: Optional[Callable[[], list[dict]]] = None,
        drift_radius_px: int = 50,
        phash_distance_threshold: int = 8,
    ):
        self.cp = cp
        self.screenshot_fn = screenshot_fn
        self.ax_press_fn = ax_press_fn
        self.focused_ax_fn = focused_ax_fn
        self.detect_elements_fn = detect_elements_fn
        self.drift_radius_px = drift_radius_px
        self.phash_distance_threshold = phash_distance_threshold

    def execute(self, intent: Intent) -> Outcome:
        # Skeleton — full implementation lands in Tasks 5-8.
        return Outcome(
            status="executed_unverified",
            intent=intent,
            elapsed_ms=0,
            used_path="none",
        )
```

Modify `python-client/cursor_pointer/__init__.py` to lazy-export the new types. Replace the file contents with:

```python
"""CursorPointer Python client SDK."""
from .client import CursorPointer, CursorPointerError, Monitor

__all__ = [
    "CursorPointer",
    "CursorPointerError",
    "Monitor",
    # Agent helpers (require the `[ocr]` extra)
    "Annotation",
    "Element",
    "Session",
    "annotate",
    "click_element",
    # Closed-loop action contract
    "ActionExecutor",
    "ExpectSig",
    "Intent",
    "Outcome",
    "TargetSig",
]
__version__ = "0.1.0"


def __getattr__(name):
    # Lazy import — agent helpers depend on Pillow + RapidOCR, optional.
    if name in {"Annotation", "Element", "annotate", "click_element"}:
        from . import annotate as _a
        return getattr(_a, name)
    if name == "Session":
        from .session import Session
        return Session
    if name in {"ActionExecutor"}:
        from .executor import ActionExecutor
        return ActionExecutor
    if name in {"ExpectSig", "Intent", "Outcome", "TargetSig"}:
        from . import intent as _i
        return getattr(_i, name)
    raise AttributeError(name)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd python-client && python -m pytest tests/test_executor.py -v
```
Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add python-client/cursor_pointer/executor.py python-client/cursor_pointer/__init__.py python-client/tests/test_executor.py
git commit -m "feat(agent): ActionExecutor skeleton + public exports"
```

---

## Task 5: Executor — click relocate + structured-first + pixel fallback

**Files:**
- Modify: `python-client/cursor_pointer/executor.py`
- Modify: `python-client/tests/test_executor.py`

- [ ] **Step 1: Append failing tests**

Append to `python-client/tests/test_executor.py`:

```python
from cursor_pointer.intent import ExpectSig, Intent, TargetSig


def _make_intent(text_target: bool = False) -> Intent:
    target = TargetSig(
        element_id=5,
        bbox=(100, 200, 80, 30),
        ax_path=None,
        role="AXButton",
        ocr_text="Send",
        visual_hash="0" * 16,
    )
    return Intent(
        kind="click",
        target=target,
        payload={},
        expect=ExpectSig(focus_changes=True, roi_pixel_delta_min=0.02),
        raw_action="click 5",
    )


def _elem(eid=5, x=100, y=200, w=80, h=30, role="AXButton", label="Send",
          ax_ref="REF-OBJ"):
    return {"id": eid, "x": x, "y": y, "w": w, "h": h,
            "role": role, "label": label, "ax_ref": ax_ref}


def test_executor_relocate_mismatch_returns_early():
    cp = MagicMock()
    screenshot_fn = MagicMock(return_value=_png())
    ax_press = MagicMock(return_value=False)
    focused_ax = MagicMock(return_value=None)
    # No matching element in fresh detection.
    detect = MagicMock(return_value=[_elem(eid=99, x=500, y=500, label="Other")])

    ex = ActionExecutor(cp=cp, screenshot_fn=screenshot_fn,
                        ax_press_fn=ax_press, focused_ax_fn=focused_ax,
                        detect_elements_fn=detect)
    outcome = ex.execute(_make_intent())
    assert outcome.status == "mismatch_target"
    assert outcome.used_path == "none"
    cp.click.assert_not_called()
    ax_press.assert_not_called()


def test_executor_structured_first_skips_pixel():
    cp = MagicMock()
    screenshot_fn = MagicMock(return_value=_png())
    ax_press = MagicMock(return_value=True)  # AX press succeeds
    # focus changes before/after → verify ok
    focused_ax = MagicMock(side_effect=[
        {"id": "before"}, {"id": "after"},
    ])
    detect = MagicMock(return_value=[_elem()])

    ex = ActionExecutor(cp=cp, screenshot_fn=screenshot_fn,
                        ax_press_fn=ax_press, focused_ax_fn=focused_ax,
                        detect_elements_fn=detect)
    outcome = ex.execute(_make_intent())
    assert outcome.used_path == "ax_press"
    cp.click.assert_not_called()
    ax_press.assert_called_once()


def test_executor_pixel_fallback_when_no_ax_ref():
    cp = MagicMock()
    screenshot_fn = MagicMock(return_value=_png())
    ax_press = MagicMock(return_value=False)
    focused_ax = MagicMock(side_effect=[
        {"id": "before"}, {"id": "after"},
    ])
    detect = MagicMock(return_value=[_elem(ax_ref=None)])

    ex = ActionExecutor(cp=cp, screenshot_fn=screenshot_fn,
                        ax_press_fn=ax_press, focused_ax_fn=focused_ax,
                        detect_elements_fn=detect)
    outcome = ex.execute(_make_intent())
    assert outcome.used_path == "pixel"
    cp.click.assert_called_once()
    ax_press.assert_not_called()


def test_executor_pixel_fallback_when_ax_press_returns_false():
    cp = MagicMock()
    screenshot_fn = MagicMock(return_value=_png())
    ax_press = MagicMock(return_value=False)  # AX press unsupported
    focused_ax = MagicMock(side_effect=[
        {"id": "before"}, {"id": "after"},
    ])
    detect = MagicMock(return_value=[_elem()])

    ex = ActionExecutor(cp=cp, screenshot_fn=screenshot_fn,
                        ax_press_fn=ax_press, focused_ax_fn=focused_ax,
                        detect_elements_fn=detect)
    outcome = ex.execute(_make_intent())
    assert outcome.used_path == "pixel"
    cp.click.assert_called_once()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd python-client && python -m pytest tests/test_executor.py -v
```
Expected: 4 new tests fail (executor returns `executed_unverified` skeleton).

- [ ] **Step 3: Write implementation**

Replace the `execute` method in `python-client/cursor_pointer/executor.py` with the click pipeline. Replace the entire file body below the `__init__` definition with:

```python
    def execute(self, intent: Intent) -> Outcome:
        start = time.time()
        if intent.kind == "click":
            return self._execute_click(intent, start)
        if intent.kind == "type":
            return self._execute_type(intent, start)
        return Outcome(
            status="exec_error",
            intent=intent,
            elapsed_ms=int((time.time() - start) * 1000),
            error=f"unsupported intent.kind={intent.kind!r}",
        )

    # -------- click pipeline --------

    def _execute_click(self, intent: Intent, start: float) -> Outcome:
        from . import anchors

        target = intent.target
        if target is None:
            return Outcome(
                status="exec_error",
                intent=intent,
                elapsed_ms=int((time.time() - start) * 1000),
                error="click intent missing target",
            )

        # 1. relocate
        fresh = self.detect_elements_fn() if self.detect_elements_fn else []
        hit, drift = anchors.find_target_match(target, fresh, self.drift_radius_px)
        if hit is None:
            return Outcome(
                status="mismatch_target",
                intent=intent,
                elapsed_ms=int((time.time() - start) * 1000),
                relocate_drift_px=None,
                used_path="none",
                error="target signature did not match any current element",
            )

        before_focus = self.focused_ax_fn()
        before_shot = self.screenshot_fn()
        before_hash = anchors.average_hash_hex(
            before_shot, bbox=(hit["x"], hit["y"], hit["w"], hit["h"])
        )

        cx = hit["x"] + hit["w"] // 2
        cy = hit["y"] + hit["h"] // 2

        # 2. structured-first
        used_path = "none"
        if hit.get("ax_ref") is not None:
            if self.ax_press_fn(hit["ax_ref"]):
                used_path = "ax_press"

        # 3. pixel fallback
        if used_path == "none":
            try:
                self.cp.click(cx, cy)
                used_path = "pixel"
            except Exception as e:
                return Outcome(
                    status="exec_error",
                    intent=intent,
                    elapsed_ms=int((time.time() - start) * 1000),
                    relocate_drift_px=drift,
                    used_path="none",
                    error=f"pixel click failed: {e}",
                )

        # 4. verify (in next task — for now mark unverified)
        return self._verify_click(
            intent=intent,
            start=start,
            hit=hit,
            drift=drift,
            used_path=used_path,
            before_focus=before_focus,
            before_hash=before_hash,
        )

    def _verify_click(self, intent, start, hit, drift, used_path,
                      before_focus, before_hash):
        # Stub returning executed_unverified — Task 6 fills this in.
        return Outcome(
            status="executed_unverified",
            intent=intent,
            elapsed_ms=int((time.time() - start) * 1000),
            relocate_drift_px=drift,
            used_path=used_path,
            before_hash=before_hash,
            after_hash=None,
            error=None,
        )

    # -------- type pipeline (Task 7) --------

    def _execute_type(self, intent: Intent, start: float) -> Outcome:
        return Outcome(
            status="exec_error",
            intent=intent,
            elapsed_ms=int((time.time() - start) * 1000),
            error="type pipeline not yet implemented",
        )
```

Update the click-related tests to expect `executed_unverified` instead of `ok` for now (the verify step isn't implemented yet). In `test_executor_structured_first_skips_pixel`, `test_executor_pixel_fallback_when_no_ax_ref`, `test_executor_pixel_fallback_when_ax_press_returns_false`, change the assertion to also accept `executed_unverified`:

Add at the bottom of each of those three tests after the `used_path` assertion:

```python
    assert outcome.status in ("ok", "executed_unverified")
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd python-client && python -m pytest tests/test_executor.py -v
```
Expected: 5 passed (skeleton + 4 new).

- [ ] **Step 5: Commit**

```bash
git add python-client/cursor_pointer/executor.py python-client/tests/test_executor.py
git commit -m "feat(agent): executor click pipeline — relocate + structured + pixel"
```

---

## Task 6: Executor — click verify (focus change OR ROI delta)

**Files:**
- Modify: `python-client/cursor_pointer/executor.py`
- Modify: `python-client/tests/test_executor.py`

- [ ] **Step 1: Append failing tests**

Append to `python-client/tests/test_executor.py`:

```python
def test_executor_verify_ok_via_focus_change():
    cp = MagicMock()
    screenshot_fn = MagicMock(return_value=_png())
    ax_press = MagicMock(return_value=True)
    focused_ax = MagicMock(side_effect=[
        {"id": "before-elem"}, {"id": "after-elem"},
    ])
    detect = MagicMock(return_value=[_elem()])

    ex = ActionExecutor(cp=cp, screenshot_fn=screenshot_fn,
                        ax_press_fn=ax_press, focused_ax_fn=focused_ax,
                        detect_elements_fn=detect)
    outcome = ex.execute(_make_intent())
    assert outcome.status == "ok"
    assert outcome.used_path == "ax_press"


def test_executor_verify_ok_via_roi_delta():
    # Before screenshot is grey; after is the same grey + a black box at (100,200)
    grey = _png(color=(180, 180, 180))
    img = Image.new("RGB", (200, 200), (180, 180, 180))
    for x in range(100, 180):
        for y in range(200, 230):
            if x < img.width and y < img.height:
                img.putpixel((x, y), (0, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    diff = buf.getvalue()

    cp = MagicMock()
    screenshot_fn = MagicMock(side_effect=[grey, diff])
    ax_press = MagicMock(return_value=True)
    focused_ax = MagicMock(return_value={"id": "same"})  # focus did NOT change
    detect = MagicMock(return_value=[_elem()])

    ex = ActionExecutor(cp=cp, screenshot_fn=screenshot_fn,
                        ax_press_fn=ax_press, focused_ax_fn=focused_ax,
                        detect_elements_fn=detect)
    outcome = ex.execute(_make_intent())
    assert outcome.status == "ok"


def test_executor_verify_failed_neither_focus_nor_roi():
    same = _png()
    cp = MagicMock()
    screenshot_fn = MagicMock(side_effect=[same, same])
    ax_press = MagicMock(return_value=True)
    focused_ax = MagicMock(return_value={"id": "same"})
    detect = MagicMock(return_value=[_elem()])

    ex = ActionExecutor(cp=cp, screenshot_fn=screenshot_fn,
                        ax_press_fn=ax_press, focused_ax_fn=focused_ax,
                        detect_elements_fn=detect)
    outcome = ex.execute(_make_intent())
    assert outcome.status == "verify_failed"
```

Update the three earlier tests (Task 5) that asserted `outcome.status in ("ok","executed_unverified")` to now expect `outcome.status == "ok"` since verify is wired up:

```python
    # in test_executor_structured_first_skips_pixel:
    assert outcome.status == "ok"
    # in test_executor_pixel_fallback_when_no_ax_ref:
    assert outcome.status == "ok"
    # in test_executor_pixel_fallback_when_ax_press_returns_false:
    assert outcome.status == "ok"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd python-client && python -m pytest tests/test_executor.py -v
```
Expected: 3 new tests fail with `executed_unverified` instead of `ok` / `verify_failed`.

- [ ] **Step 3: Implement verify**

Replace `_verify_click` in `python-client/cursor_pointer/executor.py` with:

```python
    def _verify_click(self, intent, start, hit, drift, used_path,
                      before_focus, before_hash):
        from . import anchors

        # Small settle delay — let the UI react.
        time.sleep(0.05)

        after_focus = self.focused_ax_fn()
        after_shot = self.screenshot_fn()

        # Permission revoked mid-action surfaces here.
        if anchors.is_permission_denied_frame(after_shot):
            return Outcome(
                status="exec_error",
                intent=intent,
                elapsed_ms=int((time.time() - start) * 1000),
                relocate_drift_px=drift,
                used_path=used_path,
                before_hash=before_hash,
                after_hash=None,
                error="permission_denied: screen_recording",
            )

        after_hash = anchors.average_hash_hex(
            after_shot, bbox=(hit["x"], hit["y"], hit["w"], hit["h"])
        )

        focus_changed = _focus_signature(before_focus) != _focus_signature(after_focus)
        roi_distance = anchors.hamming_distance_hex(before_hash, after_hash)
        # roi_pixel_delta_min ~ fraction of bits flipped. 0.02 of 64 ≈ 1.3, so
        # a distance ≥ 2 satisfies the default threshold.
        roi_threshold_bits = max(1, int(intent.expect.roi_pixel_delta_min * 64))
        roi_changed = roi_distance >= roi_threshold_bits

        verified = False
        if intent.expect.focus_changes and focus_changed:
            verified = True
        if intent.expect.roi_pixel_delta_min > 0 and roi_changed:
            verified = True

        status = "ok" if verified else "verify_failed"
        return Outcome(
            status=status,
            intent=intent,
            elapsed_ms=int((time.time() - start) * 1000),
            relocate_drift_px=drift,
            used_path=used_path,
            before_hash=before_hash,
            after_hash=after_hash,
            error=None if verified else
                  f"no verifiable change (focus_changed={focus_changed}, "
                  f"roi_distance={roi_distance}/{roi_threshold_bits})",
        )


def _focus_signature(focus_obj) -> str:
    """Reduce a focused-AX dict to a stable equality key."""
    if focus_obj is None:
        return ""
    if isinstance(focus_obj, dict):
        return f"{focus_obj.get('id','')}|{focus_obj.get('role','')}|{focus_obj.get('label','')}"
    return repr(focus_obj)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd python-client && python -m pytest tests/test_executor.py -v
```
Expected: all click tests pass.

- [ ] **Step 5: Commit**

```bash
git add python-client/cursor_pointer/executor.py python-client/tests/test_executor.py
git commit -m "feat(agent): executor click verify — focus change OR ROI delta"
```

---

## Task 7: Executor — type pipeline (focus optional target + verify via AXValue)

**Files:**
- Modify: `python-client/cursor_pointer/executor.py`
- Modify: `python-client/tests/test_executor.py`

- [ ] **Step 1: Append failing tests**

Append to `python-client/tests/test_executor.py`:

```python
def _make_type_intent(text: str = "hello", with_target: bool = False) -> Intent:
    target = None
    if with_target:
        target = TargetSig(
            element_id=5, bbox=(100, 200, 80, 30),
            ax_path=None, role="AXTextField", ocr_text="Search",
            visual_hash="0" * 16,
        )
    return Intent(
        kind="type",
        target=target,
        payload={"text": text},
        expect=ExpectSig(focus_changes=False, roi_pixel_delta_min=0.0,
                         typed_text_in_focus=text),
        raw_action=f'type "{text}"',
    )


def test_executor_type_no_target_verifies_via_axvalue():
    cp = MagicMock()
    screenshot_fn = MagicMock(return_value=_png())
    ax_press = MagicMock(return_value=False)
    # After typing, focused AX has value ending with "hello"
    focused_ax = MagicMock(return_value={"value": "previous text hello"})

    ex = ActionExecutor(cp=cp, screenshot_fn=screenshot_fn,
                        ax_press_fn=ax_press, focused_ax_fn=focused_ax)
    outcome = ex.execute(_make_type_intent("hello"))
    assert outcome.status == "ok"
    cp.type_text.assert_called_once_with("hello")


def test_executor_type_verify_failed_when_axvalue_missing_text():
    cp = MagicMock()
    screenshot_fn = MagicMock(return_value=_png())
    ax_press = MagicMock(return_value=False)
    focused_ax = MagicMock(return_value={"value": "unrelated text"})

    ex = ActionExecutor(cp=cp, screenshot_fn=screenshot_fn,
                        ax_press_fn=ax_press, focused_ax_fn=focused_ax)
    outcome = ex.execute(_make_type_intent("hello"))
    assert outcome.status == "verify_failed"


def test_executor_type_with_target_focuses_then_types():
    cp = MagicMock()
    screenshot_fn = MagicMock(return_value=_png())
    ax_press = MagicMock(return_value=True)  # focus click via AX
    focused_ax = MagicMock(return_value={"value": "hello"})
    detect = MagicMock(return_value=[
        _elem(eid=5, role="AXTextField", label="Search")
    ])

    ex = ActionExecutor(cp=cp, screenshot_fn=screenshot_fn,
                        ax_press_fn=ax_press, focused_ax_fn=focused_ax,
                        detect_elements_fn=detect)
    outcome = ex.execute(_make_type_intent("hello", with_target=True))
    assert outcome.status == "ok"
    ax_press.assert_called_once()
    cp.type_text.assert_called_once_with("hello")
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd python-client && python -m pytest tests/test_executor.py -v
```
Expected: 3 new tests fail (`_execute_type` returns exec_error stub).

- [ ] **Step 3: Implement type pipeline**

Replace `_execute_type` in `python-client/cursor_pointer/executor.py` with:

```python
    def _execute_type(self, intent: Intent, start: float) -> Outcome:
        from . import anchors

        text = intent.payload.get("text", "")
        if not text:
            return Outcome(
                status="exec_error",
                intent=intent,
                elapsed_ms=int((time.time() - start) * 1000),
                error="type intent missing payload.text",
            )

        used_path = "none"

        # Optional: focus a target element first.
        if intent.target is not None:
            fresh = self.detect_elements_fn() if self.detect_elements_fn else []
            hit, _drift = anchors.find_target_match(
                intent.target, fresh, self.drift_radius_px
            )
            if hit is None:
                return Outcome(
                    status="mismatch_target",
                    intent=intent,
                    elapsed_ms=int((time.time() - start) * 1000),
                    used_path="none",
                    error="type target signature did not match any current element",
                )
            cx = hit["x"] + hit["w"] // 2
            cy = hit["y"] + hit["h"] // 2
            if hit.get("ax_ref") is not None and self.ax_press_fn(hit["ax_ref"]):
                used_path = "ax_press"
            else:
                try:
                    self.cp.click(cx, cy)
                    used_path = "pixel"
                except Exception as e:
                    return Outcome(
                        status="exec_error",
                        intent=intent,
                        elapsed_ms=int((time.time() - start) * 1000),
                        used_path="none",
                        error=f"focus click failed: {e}",
                    )
            time.sleep(0.05)

        # Type the text.
        try:
            self.cp.type_text(text)
        except Exception as e:
            return Outcome(
                status="exec_error",
                intent=intent,
                elapsed_ms=int((time.time() - start) * 1000),
                used_path=used_path,
                error=f"type_text failed: {e}",
            )

        # Verify — focused AX's value should end-with (or contain) the typed text.
        time.sleep(0.05)
        focused = self.focused_ax_fn() or {}
        value = focused.get("value") if isinstance(focused, dict) else None
        expected = intent.expect.typed_text_in_focus or text
        verified = bool(value and expected in value)
        status = "ok" if verified else "verify_failed"

        return Outcome(
            status=status,
            intent=intent,
            elapsed_ms=int((time.time() - start) * 1000),
            used_path=used_path,
            error=None if verified else
                  f"typed text {expected!r} not present in focused AXValue "
                  f"{(value or '')[:60]!r}",
        )
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd python-client && python -m pytest tests/test_executor.py -v
```
Expected: all executor tests pass.

- [ ] **Step 5: Commit**

```bash
git add python-client/cursor_pointer/executor.py python-client/tests/test_executor.py
git commit -m "feat(agent): executor type pipeline — focus optional + AXValue verify"
```

---

## Task 8: `IntentBuilder` helpers — build_click / build_type

**Files:**
- Modify: `python-client/cursor_pointer/executor.py`
- Modify: `python-client/tests/test_executor.py`

- [ ] **Step 1: Append failing tests**

Append to `python-client/tests/test_executor.py`:

```python
from cursor_pointer.executor import build_click_intent, build_type_intent


def test_build_click_intent_from_element_list():
    elements = [
        _elem(eid=5, x=100, y=200, role="AXButton", label="Send",
              ax_ref="REF"),
    ]
    shot = _png()
    intent = build_click_intent(
        action_str="click 5", element_id=5,
        elements=elements, screenshot_png=shot,
    )
    assert intent.kind == "click"
    assert intent.target is not None
    assert intent.target.element_id == 5
    assert intent.target.role == "AXButton"
    assert intent.target.ocr_text == "Send"
    assert len(intent.target.visual_hash) == 16


def test_build_click_intent_returns_none_when_id_missing():
    elements = [_elem(eid=7)]
    intent = build_click_intent(
        action_str="click 5", element_id=5,
        elements=elements, screenshot_png=_png(),
    )
    assert intent is None


def test_build_type_intent_with_target():
    elements = [_elem(eid=3, role="AXTextField", label="Search")]
    intent = build_type_intent(
        action_str='type 3 "hello"', text="hello",
        element_id=3, elements=elements, screenshot_png=_png(),
    )
    assert intent.kind == "type"
    assert intent.payload["text"] == "hello"
    assert intent.target is not None
    assert intent.target.role == "AXTextField"


def test_build_type_intent_without_target():
    intent = build_type_intent(
        action_str='type "hello"', text="hello",
        element_id=None, elements=[], screenshot_png=_png(),
    )
    assert intent.kind == "type"
    assert intent.target is None
    assert intent.payload["text"] == "hello"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd python-client && python -m pytest tests/test_executor.py -v
```
Expected: ImportError on `build_click_intent` / `build_type_intent`.

- [ ] **Step 3: Append implementation**

Append to `python-client/cursor_pointer/executor.py` (after the `ActionExecutor` class):

```python
# ---------------------------------------------------------------------------
# IntentBuilder helpers
# ---------------------------------------------------------------------------
#
# Translate the raw VLM-emitted action string + current element list +
# current screenshot into a structured Intent. Pure functions — no I/O.


def build_click_intent(
    action_str: str,
    element_id: int,
    elements: list[dict],
    screenshot_png: bytes,
) -> Optional[Intent]:
    from . import anchors

    el = next((b for b in elements if b.get("id") == element_id), None)
    if el is None:
        return None
    bbox = (int(el["x"]), int(el["y"]), int(el["w"]), int(el["h"]))
    target = TargetSig(
        element_id=element_id,
        bbox=bbox,
        ax_path=None,
        role=el.get("role"),
        ocr_text=el.get("label"),
        visual_hash=anchors.average_hash_hex(screenshot_png, bbox=bbox),
    )
    return Intent(
        kind="click",
        target=target,
        payload={},
        expect=ExpectSig(focus_changes=True, roi_pixel_delta_min=0.02),
        raw_action=action_str,
    )


def build_type_intent(
    action_str: str,
    text: str,
    element_id: Optional[int],
    elements: list[dict],
    screenshot_png: bytes,
) -> Intent:
    from . import anchors

    target = None
    if element_id is not None:
        el = next((b for b in elements if b.get("id") == element_id), None)
        if el is not None:
            bbox = (int(el["x"]), int(el["y"]), int(el["w"]), int(el["h"]))
            target = TargetSig(
                element_id=element_id,
                bbox=bbox,
                ax_path=None,
                role=el.get("role"),
                ocr_text=el.get("label"),
                visual_hash=anchors.average_hash_hex(screenshot_png, bbox=bbox),
            )
    return Intent(
        kind="type",
        target=target,
        payload={"text": text},
        expect=ExpectSig(
            focus_changes=False,
            roi_pixel_delta_min=0.0,
            typed_text_in_focus=text,
        ),
        raw_action=action_str,
    )
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd python-client && python -m pytest tests/test_executor.py -v
```
Expected: all tests pass (including 4 new).

- [ ] **Step 5: Commit**

```bash
git add python-client/cursor_pointer/executor.py python-client/tests/test_executor.py
git commit -m "feat(agent): IntentBuilder — build_click_intent / build_type_intent"
```

---

## Task 9: Wire executor into `run_agent.py` click branch

**Files:**
- Modify: `python-client/tools/run_agent.py:1157-1225`
- Test: existing tests must still pass; one new test for the integration shim.

This task threads the executor through the existing agent loop. Other 14 verb branches keep their bodies but get a return-value adapter (Task 11).

- [ ] **Step 1: Inspect current click branch**

Read `python-client/tools/run_agent.py:1157-1225`. The existing branch contains AX press fast-path + icon-row reach-around + hover-then-click fallback. We will **replace it** with executor delegation. The reach-around logic (`AXStaticText` + icon sibling) is preserved as a *signature builder hint* — pass the resolved icon target to the executor instead of the original text element.

- [ ] **Step 2: Write the failing test**

Create `python-client/tests/test_run_agent_click.py`:

```python
"""Test that the click verb in run_agent.execute() delegates to ActionExecutor."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


def test_click_delegates_to_executor_and_records_outcome():
    import run_agent

    # Stub the executor to return a structured Outcome
    fake_outcome = MagicMock(status="ok", used_path="ax_press",
                              relocate_drift_px=0, error=None)
    fake_executor = MagicMock()
    fake_executor.execute.return_value = fake_outcome

    boxes = [{"id": 5, "x": 100, "y": 200, "w": 80, "h": 30,
              "role": "AXButton", "label": "Send", "ax_ref": object()}]

    with patch.object(run_agent, "_get_executor", return_value=fake_executor), \
         patch.object(run_agent, "_current_screenshot", return_value=b"PNG"):
        result = run_agent.execute("click 5", boxes)

    assert result is None  # backward-compat: success still None
    fake_executor.execute.assert_called_once()
    intent = fake_executor.execute.call_args.args[0]
    assert intent.kind == "click"
    assert intent.target.element_id == 5


def test_click_returns_error_string_on_mismatch_target():
    import run_agent

    fake_outcome = MagicMock(status="mismatch_target", used_path="none",
                              relocate_drift_px=None,
                              error="target not found")
    fake_executor = MagicMock()
    fake_executor.execute.return_value = fake_outcome

    boxes = [{"id": 5, "x": 100, "y": 200, "w": 80, "h": 30,
              "role": "AXButton", "label": "Send", "ax_ref": object()}]

    with patch.object(run_agent, "_get_executor", return_value=fake_executor), \
         patch.object(run_agent, "_current_screenshot", return_value=b"PNG"):
        result = run_agent.execute("click 5", boxes)

    assert result is not None
    assert "mismatch_target" in result or "target not found" in result
```

- [ ] **Step 3: Run test to verify it fails**

```bash
cd python-client && python -m pytest tests/test_run_agent_click.py -v
```
Expected: fails — `_get_executor` and `_current_screenshot` don't exist yet.

- [ ] **Step 4: Add executor accessor + screenshot helper at top of `run_agent.py`**

Open `python-client/tools/run_agent.py`. Find the existing imports block (around line 30-50). After the existing imports, add:

```python
# ----- closed-loop action contract (Task 9 of action-contract plan) -----
from cursor_pointer.executor import (
    ActionExecutor as _ActionExecutor,
    build_click_intent as _build_click_intent,
    build_type_intent as _build_type_intent,
)


_EXECUTOR_SINGLETON: Optional[_ActionExecutor] = None


def _current_screenshot() -> bytes:
    """Take a PNG of the primary monitor via the daemon. Used by the executor
    for pHash + verify steps. Falls back to empty bytes on error so the
    permission-denied detector triggers cleanly."""
    try:
        return CursorPointer().screenshot()
    except Exception:
        return b""


def _focused_ax_dict() -> Optional[dict]:
    """Return {role, label, value, id} for the system-wide focused AX element,
    or None. Tolerant: any pyobjc failure returns None so verify falls through
    to ROI-based detection."""
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
        out = {}
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


def _get_executor() -> _ActionExecutor:
    global _EXECUTOR_SINGLETON
    if _EXECUTOR_SINGLETON is None:
        _EXECUTOR_SINGLETON = _ActionExecutor(
            cp=CursorPointer(),
            screenshot_fn=_current_screenshot,
            ax_press_fn=ax_press_element,
            focused_ax_fn=_focused_ax_dict,
            detect_elements_fn=lambda: detect_elements(_target_pid_for_executor())
                                       if _target_pid_for_executor() else [],
        )
    return _EXECUTOR_SINGLETON


_CURRENT_TARGET_PID: Optional[int] = None


def _target_pid_for_executor() -> Optional[int]:
    return _CURRENT_TARGET_PID


def _set_target_pid_for_executor(pid: Optional[int]) -> None:
    global _CURRENT_TARGET_PID
    _CURRENT_TARGET_PID = pid
```

In the main loop (search for the call to `detect_elements(target_pid)` — should be once per step), add immediately after a successful detect:

```python
_set_target_pid_for_executor(target_pid)
```

This makes the executor's just-in-time re-detect use the same target pid the planner is on.

- [ ] **Step 5: Replace the click branch in `execute()`**

In `python-client/tools/run_agent.py`, replace the entire block from line 1157 (`if verb in ("click", "dclick", "rclick"):`) through line 1225 (`return None` before `return f"unknown verb {verb!r}"`) with:

```python
    if verb in ("click", "dclick", "rclick"):
        try:
            eid = int(arg)
        except (TypeError, ValueError):
            return f"click needs element id, got {arg!r}"

        # Non-single-click verbs (dclick, rclick) keep the legacy hover-then-
        # click path — they don't benefit from AX-press verify (AXPress is
        # single-action only). Closed-loop coverage of multi-click verbs is a
        # follow-up.
        if verb != "click":
            el = next((b for b in boxes if b["id"] == eid), None)
            if not el:
                return f"no element with id {eid}"
            cx = el["x"] + el["w"] // 2
            cy = el["y"] + el["h"] // 2
            if verb == "dclick":
                hover_then_click(cp, cx, cy, count=2)
            else:
                hover_then_click(cp, cx, cy, button="right")
            return None

        # Single-click → closed-loop executor path.
        shot = _current_screenshot()
        intent = _build_click_intent(action_str, eid, boxes, shot)
        if intent is None:
            return f"no element with id {eid}"
        outcome = _get_executor().execute(intent)
        _log(f"  → click outcome: status={outcome.status} "
             f"used_path={outcome.used_path} "
             f"drift={outcome.relocate_drift_px} "
             f"ms={outcome.elapsed_ms}")

        if outcome.status == "ok":
            return None
        if outcome.status == "executed_unverified":
            # Action ran; planner should re-check before next step.
            history.append(f"click #{eid} executed (unverified)")
            return None
        # mismatch_target / verify_failed / exec_error → structured error.
        return f"{outcome.status}: {outcome.error or 'no detail'}"
```

- [ ] **Step 6: Run tests to verify they pass**

```bash
cd python-client && python -m pytest tests/test_run_agent_click.py tests/test_planner.py tests/test_verify_done.py tests/test_new_verbs.py -v
```
Expected: all pass. If `test_new_verbs.py` has any click-specific assertion that breaks (e.g. asserting a raw `cp.click(...)` call), update the assertion to instead verify the executor was invoked.

- [ ] **Step 7: Commit**

```bash
git add python-client/tools/run_agent.py python-client/tests/test_run_agent_click.py
git commit -m "feat(agent): wire click verb to ActionExecutor (closed loop)"
```

---

## Task 10: Wire executor into `run_agent.py` type branch

**Files:**
- Modify: `python-client/tools/run_agent.py:1133-1147`
- Test: new tests under `tests/test_run_agent_type.py`

- [ ] **Step 1: Write the failing test**

Create `python-client/tests/test_run_agent_type.py`:

```python
"""Test that the type verb in run_agent.execute() delegates to ActionExecutor."""
from __future__ import annotations

from unittest.mock import MagicMock, patch


def test_type_no_target_delegates_to_executor():
    import run_agent
    fake_outcome = MagicMock(status="ok", used_path="none",
                              relocate_drift_px=None, error=None)
    fake_executor = MagicMock()
    fake_executor.execute.return_value = fake_outcome

    with patch.object(run_agent, "_get_executor", return_value=fake_executor), \
         patch.object(run_agent, "_current_screenshot", return_value=b"PNG"):
        result = run_agent.execute('type "hello"', boxes=[])

    assert result is None
    intent = fake_executor.execute.call_args.args[0]
    assert intent.kind == "type"
    assert intent.target is None
    assert intent.payload["text"] == "hello"


def test_type_verify_failed_returns_structured_error():
    import run_agent
    fake_outcome = MagicMock(status="verify_failed", used_path="none",
                              relocate_drift_px=None, error="value not present")
    fake_executor = MagicMock()
    fake_executor.execute.return_value = fake_outcome

    with patch.object(run_agent, "_get_executor", return_value=fake_executor), \
         patch.object(run_agent, "_current_screenshot", return_value=b"PNG"):
        result = run_agent.execute('type "hello"', boxes=[])

    assert result is not None
    assert "verify_failed" in result
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd python-client && python -m pytest tests/test_run_agent_type.py -v
```
Expected: fails (current `type` calls `cp.type_text` directly, doesn't use executor).

- [ ] **Step 3: Replace the type branch**

In `python-client/tools/run_agent.py`, replace the block at lines 1133-1147 (the `if verb == "type":` branch) with:

```python
    if verb == "type":
        # arg via regex is only set when text was fully quoted. For
        # missing-quote / non-ASCII / multiline content, grab everything after
        # the literal "type" token.
        text = arg.strip('"') if arg else ""
        if not text:
            lower = action_str.lower()
            idx = lower.find("type")
            if idx >= 0:
                rest = action_str[idx + 4:].strip()
                text = rest.strip('"\'').strip()
        if not text:
            return "type without text"

        # No element id in current type grammar — always target=None.
        shot = _current_screenshot()
        intent = _build_type_intent(
            action_str=action_str, text=text, element_id=None,
            elements=boxes, screenshot_png=shot,
        )
        outcome = _get_executor().execute(intent)
        _log(f"  → type outcome: status={outcome.status} ms={outcome.elapsed_ms}")

        if outcome.status == "ok":
            return None
        if outcome.status == "executed_unverified":
            history.append(f"type {text[:20]!r} executed (unverified)")
            return None
        return f"{outcome.status}: {outcome.error or 'no detail'}"
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd python-client && python -m pytest tests/test_run_agent_type.py tests/test_planner.py tests/test_new_verbs.py -v
```
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add python-client/tools/run_agent.py python-client/tests/test_run_agent_type.py
git commit -m "feat(agent): wire type verb to ActionExecutor (closed loop)"
```

---

## Task 11: Legacy verbs — uniform `Outcome` adapter at planner boundary

**Files:**
- Modify: `python-client/tools/run_agent.py` — the call site of `execute()` in the main loop
- Test: `python-client/tests/test_outcome_adapter.py`

Goal: the *planner-side* code that consumes `execute()`'s return value now branches on a uniform `Outcome` object instead of the legacy `None | str`. Inside `execute()`, the 14 legacy verbs still return `None | str`; an **adapter** wraps the call to convert.

- [ ] **Step 1: Write the failing test**

Create `python-client/tests/test_outcome_adapter.py`:

```python
"""Test the outcome adapter that wraps legacy execute() returns."""
from __future__ import annotations


def test_adapter_none_becomes_executed_unverified():
    from run_agent import _wrap_legacy_return
    out = _wrap_legacy_return(None, action_str="scroll down")
    assert out.status == "executed_unverified"
    assert out.error is None
    assert out.intent.raw_action == "scroll down"


def test_adapter_done_sentinel_becomes_ok():
    from run_agent import _wrap_legacy_return
    out = _wrap_legacy_return("DONE", action_str="done complete")
    assert out.status == "ok"


def test_adapter_error_string_becomes_exec_error():
    from run_agent import _wrap_legacy_return
    out = _wrap_legacy_return("could not parse action: 'wat'",
                              action_str="wat")
    assert out.status == "exec_error"
    assert "could not parse" in (out.error or "")
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd python-client && python -m pytest tests/test_outcome_adapter.py -v
```
Expected: `_wrap_legacy_return` not defined.

- [ ] **Step 3: Implement adapter**

In `python-client/tools/run_agent.py`, add near the other helper definitions (right after `_get_executor`):

```python
from cursor_pointer.intent import (
    ExpectSig as _ExpectSig,
    Intent as _Intent,
    Outcome as _Outcome,
)


def _wrap_legacy_return(result, action_str: str) -> _Outcome:
    """Convert the legacy `execute()` return value (None | str) into the
    uniform Outcome shape. Used by the planner-side caller to remove the
    None/string branching."""
    placeholder_intent = _Intent(
        kind="click",  # placeholder; legacy verbs don't always have a real kind
        target=None,
        payload={},
        expect=_ExpectSig(),
        raw_action=action_str,
    )
    if result is None:
        return _Outcome(
            status="executed_unverified",
            intent=placeholder_intent,
            error=None,
        )
    if result == "DONE":
        return _Outcome(
            status="ok",
            intent=placeholder_intent,
            error=None,
        )
    return _Outcome(
        status="exec_error",
        intent=placeholder_intent,
        error=result,
    )
```

Find the main loop in `run_agent.py` (around line 1430-1500). Locate the call site of `result = execute(...)` and the subsequent `if result is not None:` check. Replace the post-execute block with the Outcome-aware version. Specifically: after the line `result = execute(action, boxes)`, insert:

```python
        outcome = _wrap_legacy_return(result, action_str=action)
        # Planner-side reactions per Outcome.status.
        if outcome.status == "mismatch_target":
            _log("  → outcome: mismatch_target — forcing re-perception next step")
            # Force the next iteration to re-detect by clearing local cache.
            # (boxes/elements get rebuilt every step already, so this is a
            #  hint for stuck-detector accounting only.)
            consec_action_fails = 0  # NOT a planner failure
        elif outcome.status == "verify_failed":
            consec_action_fails += 1
        elif outcome.status == "exec_error":
            if outcome.error and "permission_denied" in outcome.error:
                _log(f"!! permission denied — halting loop: {outcome.error}")
                break
            consec_action_fails += 1
        # ok / executed_unverified — keep existing flow.
```

(The existing `if result is not None:` block stays for now where it handles error history append etc.; the new block adds the structured reactions on top.)

For the closed-loop verbs (click/type), the path inside `execute()` already returns `None` for `executed_unverified` and a structured-error string for the failure cases, so the adapter sees the right shape.

- [ ] **Step 4: Run test to verify it passes**

```bash
cd python-client && python -m pytest tests/test_outcome_adapter.py tests/test_planner.py tests/test_verify_done.py tests/test_new_verbs.py tests/test_run_agent_click.py tests/test_run_agent_type.py -v
```
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add python-client/tools/run_agent.py python-client/tests/test_outcome_adapter.py
git commit -m "feat(agent): planner reads structured Outcome for all verbs"
```

---

## Task 12: Drift recovery integration test (synthetic)

**Files:**
- Create: `python-client/tests/test_drift.py`

- [ ] **Step 1: Write the test**

Create `python-client/tests/test_drift.py`:

```python
"""End-to-end test of relocate behavior against drifted elements.

Synthetic — uses an in-memory ActionExecutor with mocked screenshot +
mocked detect_elements that return the target shifted by N pixels on the
second call. Verifies the Outcome reports the drift accurately and still
fires the action.
"""
from __future__ import annotations

import io
from unittest.mock import MagicMock

from PIL import Image

from cursor_pointer.executor import ActionExecutor, build_click_intent


def _png(w: int = 400, h: int = 400, color=(200, 200, 200)) -> bytes:
    img = Image.new("RGB", (w, h), color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _elem(x, y, eid=5):
    return {"id": eid, "x": x, "y": y, "w": 80, "h": 30,
            "role": "AXButton", "label": "Send", "ax_ref": "REF"}


def test_drift_within_threshold_recovers_and_succeeds():
    """Target moves 30px between perception and action — executor finds it."""
    initial_elems = [_elem(100, 200)]
    drifted_elems = [_elem(130, 220)]  # 30px right, 20px down → ~36px drift

    cp = MagicMock()
    screenshot_fn = MagicMock(return_value=_png())
    ax_press = MagicMock(return_value=True)
    focused_ax = MagicMock(side_effect=[
        {"id": "before"}, {"id": "after"},
    ])
    # First detect call (in IntentBuilder is via initial_elems passed in);
    # the executor's just-in-time re-detect returns drifted_elems.
    detect = MagicMock(return_value=drifted_elems)

    ex = ActionExecutor(cp=cp, screenshot_fn=screenshot_fn,
                        ax_press_fn=ax_press, focused_ax_fn=focused_ax,
                        detect_elements_fn=detect)

    intent = build_click_intent(
        action_str="click 5", element_id=5,
        elements=initial_elems, screenshot_png=_png(),
    )
    outcome = ex.execute(intent)
    assert outcome.status == "ok"
    assert outcome.relocate_drift_px is not None
    assert 25 <= outcome.relocate_drift_px <= 45


def test_drift_beyond_threshold_returns_mismatch_target():
    initial_elems = [_elem(100, 200)]
    drifted_elems = [_elem(500, 500)]  # way out of radius

    cp = MagicMock()
    screenshot_fn = MagicMock(return_value=_png())
    ax_press = MagicMock(return_value=False)
    focused_ax = MagicMock(return_value=None)
    detect = MagicMock(return_value=drifted_elems)

    ex = ActionExecutor(cp=cp, screenshot_fn=screenshot_fn,
                        ax_press_fn=ax_press, focused_ax_fn=focused_ax,
                        detect_elements_fn=detect)

    intent = build_click_intent(
        action_str="click 5", element_id=5,
        elements=initial_elems, screenshot_png=_png(),
    )
    outcome = ex.execute(intent)
    assert outcome.status == "mismatch_target"
    cp.click.assert_not_called()
    ax_press.assert_not_called()
```

- [ ] **Step 2: Run test to verify it passes**

```bash
cd python-client && python -m pytest tests/test_drift.py -v
```
Expected: 2 passed (all behavior already implemented in earlier tasks).

- [ ] **Step 3: Commit**

```bash
git add python-client/tests/test_drift.py
git commit -m "test(agent): synthetic drift recovery + mismatch detection"
```

---

## Task 13: TextEdit live integration test (opt-in)

**Files:**
- Create: `python-client/tests/test_integration_textedit.py`

This test only runs when `RUN_INTEGRATION=1` is set. It boots TextEdit via AppleScript, drives the agent through one click + one type, and asserts the closed-loop Outcomes report `ok` with the AX-press path used for menu clicks.

- [ ] **Step 1: Write the test**

Create `python-client/tests/test_integration_textedit.py`:

```python
"""Live integration test: real cursor-pointer daemon + real TextEdit.app.

Gated by env var. Run with:

    cd python-client
    RUN_INTEGRATION=1 python -m pytest tests/test_integration_textedit.py -v -s

Prereqs:
  * cursor-pointer daemon running on default port (npm run dev)
  * Accessibility + Screen Recording permissions granted
  * TextEdit available at /System/Applications/TextEdit.app
"""
from __future__ import annotations

import os
import subprocess
import time

import pytest


pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_INTEGRATION") != "1",
    reason="set RUN_INTEGRATION=1 to run live TextEdit integration test",
)


def _osascript(script: str) -> None:
    subprocess.run(["osascript", "-e", script], check=False, capture_output=True)


@pytest.fixture
def textedit():
    _osascript('tell application "TextEdit" to activate')
    _osascript('tell application "TextEdit" to make new document')
    time.sleep(1.5)
    yield
    _osascript(
        'tell application "TextEdit" to close every document saving no'
    )
    _osascript('tell application "TextEdit" to quit')


def test_type_into_textedit_verifies_via_axvalue(textedit):
    from cursor_pointer import CursorPointer
    from cursor_pointer.executor import ActionExecutor, build_type_intent
    import run_agent

    cp = CursorPointer()
    ex = ActionExecutor(
        cp=cp,
        screenshot_fn=run_agent._current_screenshot,
        ax_press_fn=run_agent.ax_press_element,
        focused_ax_fn=run_agent._focused_ax_dict,
    )
    intent = build_type_intent(
        action_str='type "closed loop"',
        text="closed loop",
        element_id=None,
        elements=[],
        screenshot_png=run_agent._current_screenshot(),
    )
    outcome = ex.execute(intent)
    assert outcome.status == "ok", (
        f"type verify failed: {outcome.error} "
        f"(used_path={outcome.used_path})"
    )
```

- [ ] **Step 2: Verify the test is skipped by default**

```bash
cd python-client && python -m pytest tests/test_integration_textedit.py -v
```
Expected: 1 skipped (env var not set).

- [ ] **Step 3: Verify the test passes when daemon is running** (manual — perform before merging)

```bash
# Terminal 1: start the daemon
cd cursor-pointer && npm run dev

# Terminal 2 (after daemon is up + permissions granted):
cd python-client && RUN_INTEGRATION=1 python -m pytest tests/test_integration_textedit.py -v -s
```
Expected: 1 passed. If it fails, the failure message will identify which stage broke (relocate / structured / verify) — debug from there.

- [ ] **Step 4: Commit**

```bash
git add python-client/tests/test_integration_textedit.py
git commit -m "test(agent): opt-in TextEdit live integration for type verify"
```

---

## Final regression pass

After Task 13:

- [ ] **Run full test suite**

```bash
cd python-client && python -m pytest -v
```
Expected: all non-integration tests pass. Integration test skipped unless `RUN_INTEGRATION=1`.

- [ ] **Manual smoke** (with daemon running, optional)

```bash
cd python-client && python tools/run_agent.py "open TextEdit and type 'hello'"
```
Expected: agent executes; logs show `→ click outcome: status=ok used_path=ax_press` and `→ type outcome: status=ok` for the relevant steps. No silent black-screen loops.

- [ ] **Final commit (only if any fixes were needed)**

```bash
git add -p   # review and stage
git commit -m "fix(agent): regression cleanup for closed-loop contract"
```

---

## Self-review (already done — issues fixed inline)

1. **Spec coverage check:**
   - Intent / Outcome / TargetSig / ExpectSig dataclasses → Task 1 ✓
   - anchors.py (pHash + match + permission) → Tasks 2, 3 ✓
   - ActionExecutor + relocate + structured-first + pixel + verify → Tasks 4-7 ✓
   - IntentBuilder → Task 8 ✓
   - Wire click verb → Task 9 ✓
   - Wire type verb → Task 10 ✓
   - Legacy verbs → uniform Outcome at planner → Task 11 ✓
   - Drift test → Task 12 ✓
   - TextEdit integration → Task 13 ✓
   - Permission revocation surfacing → covered in Tasks 2 + 6 (executor verify checks `is_permission_denied_frame`) ✓
   - Rust `/ax/press` endpoint → **deliberately dropped** (deviation documented at top)

2. **Placeholder scan:** No "TBD" / "implement later" / "handle edge cases" / "similar to Task N" survived.

3. **Type consistency:** `ActionExecutor`, `build_click_intent`, `build_type_intent`, `_wrap_legacy_return`, `_get_executor`, `_current_screenshot`, `_focused_ax_dict` all match across tasks.

4. **Ambiguity:** Planner-side reaction to `mismatch_target` is "don't increment failure counter" — this is the intentional behavior the spec describes. Planner-side reaction to `executed_unverified` is currently "continue" without forcing re-screenshot; spec calls for "screenshot before next action" — the existing main loop already screenshots every step, so this is satisfied implicitly.
