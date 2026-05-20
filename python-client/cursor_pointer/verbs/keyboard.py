"""type + key verbs.

`type` delegates to ActionExecutor (closed-loop verify via AXValue).
`key` is legacy-bodied (no closed-loop verify yet).
"""
from __future__ import annotations

import re
from typing import Optional

from ..executor import build_type_intent
from ..intent import Outcome
from .base import Verb, VerbContext, make_placeholder_intent


# ---------- type ----------

_TYPE_QUOTED_RE = re.compile(r'^\s*type\s+"([^"]*)"\s*$', re.IGNORECASE)
_TYPE_UNQUOTED_RE = re.compile(r"^\s*type\s+(\S.*\S|\S)\s*$", re.IGNORECASE)


def _parse_type(s: str) -> Optional[dict]:
    m = _TYPE_QUOTED_RE.match(s)
    if m:
        return {"text": m.group(1)}
    m = _TYPE_UNQUOTED_RE.match(s)
    if m:
        text = m.group(1).strip().strip('"\'').strip()
        if text:
            return {"text": text}
    return None


def _handle_type(args: dict, ctx: VerbContext) -> Outcome:
    text = args["text"]
    intent = build_type_intent(
        action_str=f'type "{text}"', text=text, element_id=None,
        elements=ctx.boxes, screenshot_png=b"",
    )
    outcome = ctx.executor.execute(intent)
    ctx.log(f"  → type outcome: status={outcome.status} ms={outcome.elapsed_ms}")
    return outcome


TYPE_VERB = Verb(
    name="type",
    parse=_parse_type,
    handle=_handle_type,
    grammar_hint='type "<text>"       # 在当前焦点处输入文字',
)


# ---------- key ----------

_KEY_RE = re.compile(r"^\s*key(?:\s+(\S+))?\s*$", re.IGNORECASE)


def _parse_key(s: str) -> Optional[dict]:
    m = _KEY_RE.match(s)
    if not m:
        return None
    raw = m.group(1)
    if raw is None:
        return {"key": "enter", "modifiers": []}
    raw = raw.strip().strip('"')
    if "+" in raw:
        parts = raw.split("+")
        return {"key": parts[-1], "modifiers": parts[:-1]}
    return {"key": raw, "modifiers": []}


def _handle_key(args: dict, ctx: VerbContext) -> Outcome:
    key = args["key"]
    modifiers = args.get("modifiers") or []
    raw = "key " + ("+".join([*modifiers, key]) if modifiers else key)
    ctx.cp.key(key, modifiers=modifiers)
    return Outcome(
        status="executed_unverified",
        intent=make_placeholder_intent(raw),
        error=None,
    )


KEY_VERB = Verb(
    name="key",
    parse=_parse_key,
    handle=_handle_key,
    grammar_hint="key <name>          # 按一个键（如 enter / escape / space / cmd+a）",
)
