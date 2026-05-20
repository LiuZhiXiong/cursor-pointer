"""browser verb — delegate web tasks to WebClaw via /browser/* bridge."""
from __future__ import annotations

import re
import time
from typing import Optional

from ..intent import Outcome
from .base import Verb, VerbContext, make_placeholder_intent


_BROWSER_RE = re.compile(r'^\s*browser\s+"([^"]+)"\s*$', re.IGNORECASE)


def _parse_browser(s: str) -> Optional[dict]:
    m = _BROWSER_RE.match(s)
    if not m:
        return None
    cmd_text = m.group(1).strip()
    if not cmd_text:
        return None
    return {"command": cmd_text}


def _handle_browser(args: dict, ctx: VerbContext) -> Outcome:
    cmd_text = args["command"]
    raw = f'browser "{cmd_text}"'
    placeholder = make_placeholder_intent(raw)

    try:
        # 90s queue timeout — browser tasks routinely take 30-60s.
        enq = ctx.cp.browser_enqueue(cmd_text, timeout_seconds=90)
    except Exception as e:
        return Outcome(status="exec_error", intent=placeholder,
                       error=f"browser enqueue failed: {e}")
    cmd_id = enq.get("id")
    if not cmd_id:
        return Outcome(status="exec_error", intent=placeholder,
                       error=f"browser enqueue returned no id: {enq!r}")

    deadline = time.time() + 60
    while time.time() < deadline:
        try:
            st = ctx.cp.browser_result_status(cmd_id)
        except Exception as e:
            return Outcome(status="exec_error", intent=placeholder,
                           error=f"browser result poll failed: {e}")
        status = st.get("status")
        if status == "done":
            output = (st.get("output") or "")[:200]
            if not st.get("ok"):
                return Outcome(status="exec_error", intent=placeholder,
                               error=f"browser failed: {output}")
            ctx.history.append(
                f"browser {cmd_text[:40]!r} → {output!r}"
            )
            return Outcome(status="executed_unverified",
                           intent=placeholder, error=None)
        if status == "expired":
            return Outcome(
                status="exec_error", intent=placeholder,
                error=("browser command expired (no WebClaw client polling? "
                       "enable Remote Control in WebClaw sidepanel)"),
            )
        time.sleep(0.5)
    return Outcome(status="exec_error", intent=placeholder,
                   error="browser timed out waiting for WebClaw")


BROWSER_VERB = Verb(
    name="browser",
    parse=_parse_browser,
    handle=_handle_browser,
    grammar_hint='browser "<task>"     # 委托 WebClaw 在浏览器里执行（需 WebClaw 启用 Remote Control）',
)
