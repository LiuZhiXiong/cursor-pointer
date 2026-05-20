"""System-level verbs: app, clipboard, shell."""
from __future__ import annotations

import re
import shlex
import subprocess
from typing import Optional

from ..intent import Outcome
from .base import Verb, VerbContext, make_placeholder_intent


# Whitelist of safe read-only commands. Mirrors the SHELL_WHITELIST that
# lived in run_agent.py before migration.
SHELL_WHITELIST = frozenset({
    "ls", "cat", "echo", "pwd", "which",
    "head", "tail", "grep", "find", "file",
    "wc", "date", "hostname", "whoami",
})


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


# ---------- clipboard ----------

_CLIPBOARD_RE = re.compile(r"^\s*clipboard(?:\s+(\S+))?(?:\s+(.*))?$", re.IGNORECASE)
# Relaxed write payload regex — tolerates missing closing quote (MiniMax
# sometimes drops it).
_CLIPBOARD_WRITE_PAYLOAD_RE = re.compile(r'"([^"]*)"?', re.IGNORECASE)


def _parse_clipboard(s: str) -> Optional[dict]:
    m = _CLIPBOARD_RE.match(s)
    if not m:
        return None
    sub = (m.group(1) or "").strip().strip('"').lower()
    rest = (m.group(2) or "").strip()
    if sub == "read":
        return {"op": "read", "text": None}
    if sub == "write":
        pm = _CLIPBOARD_WRITE_PAYLOAD_RE.search(rest)
        return {"op": "write", "text": pm.group(1) if pm else ""}
    # Any other sub (or no sub) — let the handler emit the helpful error.
    return {"op": "_invalid", "text": sub}


def _handle_clipboard(args: dict, ctx: VerbContext) -> Outcome:
    op = args["op"]
    if op == "read":
        try:
            text = ctx.cp.clipboard_get()
        except Exception as e:
            return Outcome(
                status="exec_error",
                intent=make_placeholder_intent("clipboard read"),
                error=f"clipboard read failed: {e}",
            )
        ctx.history.append(f"clipboard read → {text[:80]!r}")
        return Outcome(
            status="executed_unverified",
            intent=make_placeholder_intent("clipboard read"),
            error=None,
        )
    if op == "write":
        text = args.get("text") or ""
        if not text:
            return Outcome(
                status="exec_error",
                intent=make_placeholder_intent("clipboard write"),
                error='clipboard write needs quoted text: clipboard write "..."',
            )
        try:
            ctx.cp.clipboard_set(text)
        except Exception as e:
            return Outcome(
                status="exec_error",
                intent=make_placeholder_intent(f'clipboard write "{text}"'),
                error=f"clipboard write failed: {e}",
            )
        return Outcome(
            status="executed_unverified",
            intent=make_placeholder_intent(f'clipboard write "{text}"'),
            error=None,
        )
    # _invalid (or anything else) — emit helpful error listing valid subs.
    sub = args.get("text") or ""
    return Outcome(
        status="exec_error",
        intent=make_placeholder_intent(f"clipboard {sub}"),
        error=f"clipboard needs 'read' or 'write \"...\"', got {sub!r}",
    )


CLIPBOARD_VERB = Verb(
    name="clipboard",
    parse=_parse_clipboard,
    handle=_handle_clipboard,
    grammar_hint='clipboard read / clipboard write "<text>"  # 剪贴板读写',
)


# ---------- shell ----------

_SHELL_RE = re.compile(r"^\s*shell\s+(.+)$", re.IGNORECASE)


def _parse_shell(s: str) -> Optional[dict]:
    m = _SHELL_RE.match(s)
    if not m:
        return None
    cmd = m.group(1).strip()
    if not cmd:
        return None
    return {"cmd": cmd}


def _handle_shell(args: dict, ctx: VerbContext) -> Outcome:
    raw = f"shell {args['cmd']}"
    placeholder = make_placeholder_intent(raw)
    try:
        argv = shlex.split(args["cmd"])
    except ValueError as e:
        return Outcome(status="exec_error", intent=placeholder,
                       error=f"shell could not parse {args['cmd']!r}: {e}")
    if not argv:
        return Outcome(status="exec_error", intent=placeholder,
                       error="shell needs a command")
    head = argv[0]
    if head not in SHELL_WHITELIST:
        return Outcome(
            status="exec_error", intent=placeholder,
            error=(f"shell command {head!r} not in whitelist "
                   f"{sorted(SHELL_WHITELIST)}"),
        )
    try:
        out = subprocess.run(
            argv, capture_output=True, text=True, timeout=8,
        )
    except subprocess.TimeoutExpired:
        return Outcome(status="exec_error", intent=placeholder,
                       error=f"shell {head!r} timed out (8s)")
    except FileNotFoundError:
        return Outcome(status="exec_error", intent=placeholder,
                       error=f"shell {head!r} not found on PATH")
    result_text = (out.stdout or "")[:200].rstrip()
    ctx.history.append(f"shell {head!r} → {result_text!r}")
    return Outcome(status="executed_unverified", intent=placeholder, error=None)


SHELL_VERB = Verb(
    name="shell",
    parse=_parse_shell,
    handle=_handle_shell,
    grammar_hint="shell <cmd>          # 仅限只读命令：ls/cat/echo/pwd/head/tail/grep/find/wc/date 等",
)
