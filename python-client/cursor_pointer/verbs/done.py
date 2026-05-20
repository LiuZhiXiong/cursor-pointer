"""done + wait — task termination and pause."""
from __future__ import annotations

import re
import time
from typing import Optional

from ..intent import Outcome
from .base import Verb, VerbContext, make_placeholder_intent


# ---------- done ----------

_DONE_RE = re.compile(r"^\s*done\b\s*(.*)$", re.IGNORECASE)


def _parse_done(s: str) -> Optional[dict]:
    m = _DONE_RE.match(s)
    if not m:
        return None
    return {"reason": m.group(1).strip()}


def _handle_done(args: dict, ctx: VerbContext) -> Outcome:
    raw = "done " + args["reason"] if args.get("reason") else "done"
    return Outcome(
        status="ok",
        intent=make_placeholder_intent(raw),
        error=None,
    )


DONE_VERB = Verb(
    name="done",
    parse=_parse_done,
    handle=_handle_done,
    grammar_hint="done <短结论>        # 任务完成或放弃",
)


# ---------- wait ----------

_WAIT_RE = re.compile(r"^\s*wait\s*(\d+(?:\.\d+)?)?\s*$", re.IGNORECASE)


def _parse_wait(s: str) -> Optional[dict]:
    m = _WAIT_RE.match(s)
    if not m:
        return None
    raw = m.group(1)
    seconds = float(raw) if raw is not None else 1.5
    return {"seconds": seconds}


def _handle_wait(args: dict, ctx: VerbContext) -> Outcome:
    time.sleep(float(args.get("seconds", 1.5)))
    return Outcome(
        status="executed_unverified",
        intent=make_placeholder_intent(f"wait {args.get('seconds', 1.5)}"),
        error=None,
    )


WAIT_VERB = Verb(
    name="wait",
    parse=_parse_wait,
    handle=_handle_wait,
    grammar_hint="wait <seconds>      # 等几秒",
)
