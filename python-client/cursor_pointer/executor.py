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

    # -------- type pipeline --------

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

        # Verify — focused AX value should contain the typed text.
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


def _focus_signature(focus_obj) -> str:
    """Reduce a focused-AX dict to a stable equality key."""
    if focus_obj is None:
        return ""
    if isinstance(focus_obj, dict):
        return (
            f"{focus_obj.get('id','')}|"
            f"{focus_obj.get('role','')}|"
            f"{focus_obj.get('label','')}"
        )
    return repr(focus_obj)
