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
