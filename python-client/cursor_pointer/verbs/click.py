"""click + dclick + rclick verbs.

click goes through ActionExecutor for closed-loop verify.
dclick and rclick keep the legacy hover-then-click path (single-action
AX press doesn't apply to multi-clicks or right-clicks).
"""
from __future__ import annotations

import re
import time
from typing import Optional

from ..executor import build_click_intent
from ..intent import Outcome
from .base import Verb, VerbContext, make_placeholder_intent


_CLICK_RE = re.compile(r"^\s*click\s+(\d+)\s*$", re.IGNORECASE)
_DCLICK_RE = re.compile(r"^\s*dclick\s+(\d+)\s*$", re.IGNORECASE)
_RCLICK_RE = re.compile(r"^\s*rclick\s+(\d+)\s*$", re.IGNORECASE)


def _parse_click(s: str) -> Optional[dict]:
    m = _CLICK_RE.match(s)
    return {"id": int(m.group(1))} if m else None


def _parse_dclick(s: str) -> Optional[dict]:
    m = _DCLICK_RE.match(s)
    return {"id": int(m.group(1))} if m else None


def _parse_rclick(s: str) -> Optional[dict]:
    m = _RCLICK_RE.match(s)
    return {"id": int(m.group(1))} if m else None


def _hover_then_click(cp, x: int, y: int, *, count: int = 1,
                     button: str = "left", dwell: float = 0.25) -> None:
    """Move → dwell → click. Triggers hover state on Electron apps."""
    cp.move(x, y)
    time.sleep(dwell)
    cp.click(x, y, count=count, button=button)


def _handle_click(args: dict, ctx: VerbContext) -> Outcome:
    eid = args["id"]
    raw = f"click {eid}"
    el = next((b for b in ctx.boxes if b.get("id") == eid), None)
    if el is None:
        return Outcome(status="exec_error",
                       intent=make_placeholder_intent(raw),
                       error=f"no element with id {eid}")
    intent = build_click_intent(
        action_str=raw, element_id=eid,
        elements=ctx.boxes, screenshot_png=b"",
    )
    if intent is None:
        return Outcome(status="exec_error",
                       intent=make_placeholder_intent(raw),
                       error=f"no element with id {eid}")
    outcome = ctx.executor.execute(intent)
    ctx.log(f"  → click outcome: status={outcome.status} "
            f"used_path={outcome.used_path} "
            f"drift={outcome.relocate_drift_px} "
            f"ms={outcome.elapsed_ms}")
    return outcome


def _handle_dclick(args: dict, ctx: VerbContext) -> Outcome:
    eid = args["id"]
    raw = f"dclick {eid}"
    el = next((b for b in ctx.boxes if b.get("id") == eid), None)
    if el is None:
        return Outcome(status="exec_error",
                       intent=make_placeholder_intent(raw),
                       error=f"no element with id {eid}")
    cx = el["x"] + el["w"] // 2
    cy = el["y"] + el["h"] // 2
    _hover_then_click(ctx.cp, cx, cy, count=2)
    return Outcome(status="executed_unverified",
                   intent=make_placeholder_intent(raw), error=None)


def _handle_rclick(args: dict, ctx: VerbContext) -> Outcome:
    eid = args["id"]
    raw = f"rclick {eid}"
    el = next((b for b in ctx.boxes if b.get("id") == eid), None)
    if el is None:
        return Outcome(status="exec_error",
                       intent=make_placeholder_intent(raw),
                       error=f"no element with id {eid}")
    cx = el["x"] + el["w"] // 2
    cy = el["y"] + el["h"] // 2
    _hover_then_click(ctx.cp, cx, cy, button="right")
    return Outcome(status="executed_unverified",
                   intent=make_placeholder_intent(raw), error=None)


CLICK_VERB = Verb(
    name="click", parse=_parse_click, handle=_handle_click,
    grammar_hint="click <id>          # 点击编号为 id 的元素",
)
DCLICK_VERB = Verb(
    name="dclick", parse=_parse_dclick, handle=_handle_dclick,
    grammar_hint="dclick <id>         # 双击",
)
RCLICK_VERB = Verb(
    name="rclick", parse=_parse_rclick, handle=_handle_rclick,
    grammar_hint="rclick <id>         # 右键",
)
