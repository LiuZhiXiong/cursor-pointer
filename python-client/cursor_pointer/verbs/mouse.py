"""drag verb."""
from __future__ import annotations

import re
import time
from typing import Optional

from ..intent import Outcome
from .base import Verb, VerbContext, make_placeholder_intent


_DRAG_RE = re.compile(r"^\s*drag\s+(\d+)\s+to\s+(\d+)\s*$", re.IGNORECASE)


def _parse_drag(s: str) -> Optional[dict]:
    m = _DRAG_RE.match(s)
    if not m:
        return None
    return {"from_id": int(m.group(1)), "to_id": int(m.group(2))}


def _handle_drag(args: dict, ctx: VerbContext) -> Outcome:
    f, t = args["from_id"], args["to_id"]
    raw = f"drag {f} to {t}"
    placeholder = make_placeholder_intent(raw)
    el_from = next((b for b in ctx.boxes if b["id"] == f), None)
    el_to = next((b for b in ctx.boxes if b["id"] == t), None)
    if not el_from or not el_to:
        return Outcome(status="exec_error", intent=placeholder,
                       error=f"drag: bad id(s) {f}/{t}")
    fx = el_from["x"] + el_from["w"] // 2
    fy = el_from["y"] + el_from["h"] // 2
    tx = el_to["x"] + el_to["w"] // 2
    ty = el_to["y"] + el_to["h"] // 2
    ctx.cp.move(fx, fy)
    time.sleep(0.2)
    ctx.cp.drag(from_xy=(fx, fy), to_xy=(tx, ty))
    return Outcome(status="executed_unverified", intent=placeholder, error=None)


DRAG_VERB = Verb(
    name="drag",
    parse=_parse_drag,
    handle=_handle_drag,
    grammar_hint="drag <id1> to <id2>  # 拖拽：从元素1拖到元素2",
)
