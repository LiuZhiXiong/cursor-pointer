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

        # 4. verify (Task 6)
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
