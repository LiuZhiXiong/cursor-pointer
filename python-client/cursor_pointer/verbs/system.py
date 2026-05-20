"""System-level verbs: app, clipboard, shell."""
from __future__ import annotations

import re
import subprocess
from typing import Optional

from ..intent import Outcome
from .base import Verb, VerbContext, make_placeholder_intent


# ---------- app ----------

_APP_RE = re.compile(r"^\s*app(?:\s+(.+?))?\s*$", re.IGNORECASE)


def _parse_app(s: str) -> Optional[dict]:
    m = _APP_RE.match(s)
    if not m:
        return None
    raw = m.group(1)
    if raw is None:
        return {"name": ""}    # bare "app" → handler reports missing name
    name = raw.strip().strip('"').strip()
    return {"name": name}


def _handle_app(args: dict, ctx: VerbContext) -> Outcome:
    name = args["name"]
    raw = f"app {name}" if name else "app"
    placeholder = make_placeholder_intent(raw)
    if not name:
        return Outcome(status="exec_error", intent=placeholder,
                       error="app needs <name>")

    is_bundle = "." in name
    if is_bundle:
        script = f'tell application id "{name}" to activate'
    else:
        script = f'tell application "{name}" to activate'

    # Try 1 — osascript
    try:
        subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, timeout=5, check=True,
        )
        return Outcome(status="executed_unverified", intent=placeholder)
    except subprocess.TimeoutExpired:
        return Outcome(status="exec_error", intent=placeholder,
                       error=f"app activate {name!r} timed out (5s)")
    except subprocess.CalledProcessError as e_osa:
        osa_stderr = (e_osa.stderr or b"").decode(errors="replace")[:80].strip()
        # Try 2 — `open -a` (LaunchServices fuzzy-resolves)
        try:
            subprocess.run(
                ["open", "-a", name],
                capture_output=True, timeout=5, check=True,
            )
            return Outcome(status="executed_unverified", intent=placeholder)
        except subprocess.TimeoutExpired:
            return Outcome(status="exec_error", intent=placeholder,
                           error=f"app activate {name!r} timed out (5s)")
        except subprocess.CalledProcessError as e_open:
            open_stderr = (e_open.stderr or b"").decode(errors="replace")[:80].strip()
            return Outcome(
                status="exec_error", intent=placeholder,
                error=(f"app activate failed: osascript={osa_stderr!r} "
                       f"open={open_stderr!r}"),
            )


APP_VERB = Verb(
    name="app",
    parse=_parse_app,
    handle=_handle_app,
    grammar_hint="app <name>           # 启动或切换到应用（如 NeteaseMusic / Finder / Safari）",
)
