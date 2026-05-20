"""scroll + scroll_to verbs."""
from __future__ import annotations

import re
import time
from typing import Optional

from ..intent import Outcome
from .base import Verb, VerbContext, make_placeholder_intent


# ---------- scroll ----------

_SCROLL_RE = re.compile(
    r"^\s*scroll(?:\s+(up|down|\d+))?\s*$", re.IGNORECASE
)


def _parse_scroll(s: str) -> Optional[dict]:
    m = _SCROLL_RE.match(s)
    if not m:
        return None
    arg = m.group(1)
    if arg is None:
        return {"direction": "down", "amount": 6}
    arg_lower = arg.lower()
    if arg_lower == "up":
        return {"direction": "up", "amount": 6}
    if arg_lower == "down":
        return {"direction": "down", "amount": 6}
    if arg.isdigit():
        return {"direction": "down", "amount": int(arg)}
    return None


def _handle_scroll(args: dict, ctx: VerbContext) -> Outcome:
    raw = f"scroll {args['direction']} {args['amount']}"
    direction = args["direction"]
    amount = int(args["amount"])
    dy = -amount if direction == "down" else amount

    # Anchor cursor over the target app's content area before scrolling.
    boxes = ctx.boxes
    if boxes:
        xs = sorted(b["x"] + b["w"] // 2 for b in boxes)
        ys = sorted(b["y"] + b["h"] // 2 for b in boxes)
        ax, ay = xs[len(xs) // 2], ys[len(ys) // 2]
        ctx.cp.move(ax, ay)
        time.sleep(0.15)
        ctx.log(f"  → scroll anchor ({ax},{ay}) dy={dy}")
    ctx.cp.scroll(dy=dy)
    return Outcome(
        status="executed_unverified",
        intent=make_placeholder_intent(raw),
        error=None,
    )


SCROLL_VERB = Verb(
    name="scroll",
    parse=_parse_scroll,
    handle=_handle_scroll,
    grammar_hint="scroll <up|down|N>  # 滚动当前页面（默认半屏向下）— 探索视口外内容首选",
)


# ---------- scroll_to ----------

_SCROLL_TO_RE = re.compile(r"^\s*scroll_to\s+(\d+)\s*$", re.IGNORECASE)


def _parse_scroll_to(s: str) -> Optional[dict]:
    m = _SCROLL_TO_RE.match(s)
    if not m:
        return None
    return {"id": int(m.group(1))}


def _handle_scroll_to(args: dict, ctx: VerbContext) -> Outcome:
    eid = args["id"]
    raw = f"scroll_to {eid}"
    placeholder = make_placeholder_intent(raw)
    el = next((b for b in ctx.boxes if b.get("id") == eid), None)
    if el is None:
        return Outcome(status="exec_error", intent=placeholder,
                       error=f"no element with id {eid}")
    ax_ref = el.get("ax_ref")
    if ax_ref is None:
        return Outcome(status="exec_error", intent=placeholder,
                       error=f"#{eid} has no AX handle — can't scroll_to")
    try:
        from ApplicationServices import (  # type: ignore
            AXUIElementCopyActionNames,
            AXUIElementPerformAction,
        )
        err, actions = AXUIElementCopyActionNames(ax_ref, None)
        if err == 0 and actions and "AXScrollToVisible" in actions:
            AXUIElementPerformAction(ax_ref, "AXScrollToVisible")
            ctx.log(f"  → AXScrollToVisible '{el.get('label','')}' (#{eid})")
            return Outcome(status="executed_unverified",
                           intent=placeholder, error=None)
    except Exception as e:
        return Outcome(status="exec_error", intent=placeholder,
                       error=f"AXScrollToVisible crashed: {e}")
    return Outcome(status="exec_error", intent=placeholder,
                   error=f"#{eid} does not support AXScrollToVisible")


SCROLL_TO_VERB = Verb(
    name="scroll_to",
    parse=_parse_scroll_to,
    handle=_handle_scroll_to,
    grammar_hint="scroll_to <id>      # 把已编号元素精确滚入视口（仅当元素已在清单里）",
)
