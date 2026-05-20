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
        # Full implementation lands in Tasks 5-7.
        return Outcome(
            status="executed_unverified",
            intent=intent,
            elapsed_ms=0,
            used_path="none",
        )
