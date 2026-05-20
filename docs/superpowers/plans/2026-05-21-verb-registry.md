# Verb Registry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate the 14-verb if-elif chain in `python-client/tools/run_agent.py:execute()` into a declarative verb registry under `python-client/cursor_pointer/verbs/`. Adding a verb becomes one new file + one line in REGISTRY. The system-prompt verb grammar block is auto-generated.

**Architecture:** Each verb is a `Verb(name, aliases, grammar_hint, parse, handle)` instance. `dispatch(action_str, ctx)` iterates an ordered REGISTRY, first non-None `parse()` wins. Handlers always return `Outcome` (the type introduced in the closed-loop work). `execute()` becomes a thin dispatcher; the legacy if-elif chain is deleted after all verbs migrate.

**Tech Stack:** Python 3, pytest, dataclasses, regex.

---

## Pre-migration baseline

Before starting Task 1: confirm 100 tests + 1 skipped pass.

```bash
cd /Users/liuzhixiong/coding-project/cursor-pointer/python-client
python -m pytest -q
```

Expected: `102 passed, 1 skipped`.

## Migration order (locked)

Verbs migrate in this order — simplest first, complex last:

| # | Task | Verbs | File |
|---|---|---|---|
| 1 | Foundation | — | `verbs/base.py`, `verbs/__init__.py`, tests |
| 2 | Trivial pair | `done`, `wait` | `verbs/done.py` |
| 3 | Scroll pair | `scroll_to`, `scroll` | `verbs/scroll.py` |
| 4 | Drag | `drag` | `verbs/mouse.py` |
| 5 | App | `app` | `verbs/system.py` |
| 6 | Clipboard | `clipboard` | `verbs/system.py` (extend) |
| 7 | Shell | `shell` | `verbs/system.py` (extend) |
| 8 | Browser | `browser` | `verbs/browser.py` |
| 9 | Keyboard pair | `type`, `key` | `verbs/keyboard.py` |
| 10 | Click family | `click`, `dclick`, `rclick` | `verbs/click.py` |
| 11 | Finalizer | — | delete `ACTION_RE`, replace `execute()` body, switch `SYSTEM_PROMPT` to f-string |

## Coexistence strategy

During Tasks 2-10, `execute()` keeps its if-elif chain AND `dispatch()` runs first. Each migrated verb is added to REGISTRY → `dispatch()` returns a non-`exec_error` Outcome → `execute()` short-circuits and converts to legacy return. Un-migrated verbs still fall through to the legacy if-elif. At Task 11 the if-elif is deleted.

The top of `execute()` after Task 1:

```python
def execute(action_str: str, boxes: list[dict]) -> Optional[str]:
    from cursor_pointer.verbs import dispatch, VerbContext
    ctx = VerbContext(
        cp=CursorPointer(),
        boxes=boxes,
        executor=_get_executor(),
        history=history,
        log=_log,
    )
    outcome = dispatch(action_str, ctx)
    if outcome.status != "exec_error" or "unknown action" not in (outcome.error or ""):
        # Verb was migrated → short-circuit.
        return _legacy_return_from_outcome(outcome)
    # Fall through to legacy if-elif for un-migrated verbs.
    cp = CursorPointer()
    m = ACTION_RE.search(action_str)
    ...
```

`_legacy_return_from_outcome` is added in Task 1.

---

## Task 1: Foundation — base types, registry shell, dispatch glue

**Files:**
- Create: `python-client/cursor_pointer/verbs/__init__.py`
- Create: `python-client/cursor_pointer/verbs/base.py`
- Create: `python-client/tests/verbs/__init__.py` (empty)
- Create: `python-client/tests/test_registry.py`
- Create: `python-client/tests/test_dispatch.py`
- Modify: `python-client/tools/run_agent.py` — add `_legacy_return_from_outcome` + top-of-`execute()` dispatch short-circuit

- [ ] **Step 1: Create empty test package directory**

```bash
mkdir -p /Users/liuzhixiong/coding-project/cursor-pointer/python-client/tests/verbs
touch /Users/liuzhixiong/coding-project/cursor-pointer/python-client/tests/verbs/__init__.py
```

- [ ] **Step 2: Write failing foundation tests**

Create `python-client/tests/test_registry.py`:

```python
"""Meta tests for the verb registry."""
from __future__ import annotations


def test_registry_imports():
    from cursor_pointer.verbs import REGISTRY, dispatch, VerbContext  # noqa: F401
    from cursor_pointer.verbs.base import Verb, make_placeholder_intent  # noqa: F401


def test_registry_is_tuple():
    from cursor_pointer.verbs import REGISTRY
    assert isinstance(REGISTRY, tuple)


def test_no_duplicate_names():
    from cursor_pointer.verbs import REGISTRY
    names = [v.name for v in REGISTRY]
    assert len(names) == len(set(names))


def test_no_duplicate_aliases():
    from cursor_pointer.verbs import REGISTRY
    seen: set[str] = set()
    for v in REGISTRY:
        for n in (v.name, *v.aliases):
            assert n not in seen, f"duplicate verb name {n!r}"
            seen.add(n)


def test_build_grammar_section_returns_string():
    from cursor_pointer.verbs import build_grammar_section
    section = build_grammar_section()
    assert isinstance(section, str)
```

Create `python-client/tests/test_dispatch.py`:

```python
"""Tests for dispatch() — ordering + fallback behavior."""
from __future__ import annotations

from unittest.mock import MagicMock


def _ctx():
    from cursor_pointer.verbs import VerbContext
    return VerbContext(
        cp=MagicMock(),
        boxes=[],
        executor=MagicMock(),
        history=[],
        log=lambda _msg: None,
    )


def test_dispatch_empty_registry_returns_exec_error_unknown():
    from cursor_pointer.verbs import dispatch
    out = dispatch("anything goes here", _ctx())
    assert out.status == "exec_error"
    assert "unknown action" in (out.error or "")


def test_placeholder_intent_carries_raw_action():
    from cursor_pointer.verbs.base import make_placeholder_intent
    intent = make_placeholder_intent("scroll down")
    assert intent.raw_action == "scroll down"
    assert intent.target is None
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
cd /Users/liuzhixiong/coding-project/cursor-pointer/python-client
python -m pytest tests/test_registry.py tests/test_dispatch.py -v
```

Expected: ImportError on `cursor_pointer.verbs`.

- [ ] **Step 4: Implement `verbs/base.py`**

Create `python-client/cursor_pointer/verbs/base.py`:

```python
"""Verb registry — shared base types.

Each verb is a frozen Verb dataclass: name + parse + handle + grammar hint.
Handlers receive a VerbContext giving them access to the cursor-pointer
client, the current element list, the ActionExecutor, the shared history
list, and a log function.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

from ..intent import ExpectSig, Intent, Outcome


@dataclass(frozen=True)
class Verb:
    name: str
    parse: Callable[[str], Optional[dict]]
    handle: Callable[[dict, "VerbContext"], Outcome]
    aliases: tuple[str, ...] = ()
    grammar_hint: str = ""


@dataclass
class VerbContext:
    cp: object                          # CursorPointer — loose-typed to avoid cycle
    boxes: list[dict]
    executor: object                    # ActionExecutor — same reason
    history: list[str]
    log: Callable[[str], None]


def make_placeholder_intent(action_str: str) -> Intent:
    """Used by legacy-bodied verbs that don't build a real Intent."""
    return Intent(
        kind="click",                   # placeholder kind; legacy verbs ignore
        target=None,
        payload={},
        expect=ExpectSig(),
        raw_action=action_str,
    )
```

- [ ] **Step 5: Implement `verbs/__init__.py`**

Create `python-client/cursor_pointer/verbs/__init__.py`:

```python
"""Verb registry — declarative dispatch.

REGISTRY is the source of truth for which verbs the agent understands.
dispatch(action_str, ctx) iterates it; first non-None parse() wins.
build_grammar_section() renders the verb-list block for SYSTEM_PROMPT.
"""
from __future__ import annotations

from ..intent import Outcome
from .base import Verb, VerbContext, make_placeholder_intent


# Verbs are added here one at a time as the migration progresses.
# Order matters: longer-prefix / more-specific verbs go FIRST so the
# first-match-wins dispatch can't be tricked by a shorter prefix.
REGISTRY: tuple[Verb, ...] = ()


def dispatch(action_str: str, ctx: VerbContext) -> Outcome:
    for verb in REGISTRY:
        args = verb.parse(action_str)
        if args is not None:
            return verb.handle(args, ctx)
    return Outcome(
        status="exec_error",
        intent=make_placeholder_intent(action_str),
        error=f"unknown action: {action_str!r}",
    )


def build_grammar_section() -> str:
    """Render the verb-grammar block for SYSTEM_PROMPT. One line per verb."""
    return "\n".join(
        f"    {v.grammar_hint}" for v in REGISTRY if v.grammar_hint
    )
```

- [ ] **Step 6: Add `_legacy_return_from_outcome` helper to `run_agent.py`**

In `python-client/tools/run_agent.py`, find the existing `_wrap_legacy_return` helper (around line 150). Right after it, add:

```python
def _legacy_return_from_outcome(outcome: _Outcome) -> Optional[str]:
    """Reverse of _wrap_legacy_return — converts an Outcome back into the
    None | str | 'DONE' shape the planner-side main loop expects.

    Preserves exact string prefixes the planner pattern-matches on
    (e.g. ``mismatch_target:``).
    """
    if outcome.status in ("ok", "executed_unverified"):
        if outcome.intent.raw_action.lower().startswith("done"):
            return "DONE"
        return None
    if outcome.status == "mismatch_target":
        return f"mismatch_target: {outcome.error or 'target moved'}"
    if outcome.status == "verify_failed":
        return f"verify_failed: {outcome.error or 'no detail'}"
    if outcome.status == "exec_error":
        return outcome.error or "exec_error"
    return outcome.error or f"unknown status: {outcome.status}"
```

- [ ] **Step 7: Add dispatch short-circuit at top of `execute()`**

In `python-client/tools/run_agent.py`, find the start of `execute()` (around line 1019). Replace:

```python
def execute(action_str: str, boxes: list[dict]) -> Optional[str]:
    """Parse and run one action. Return None on success, error msg on failure."""
    cp = CursorPointer()

    m = ACTION_RE.search(action_str)
```

with:

```python
def execute(action_str: str, boxes: list[dict]) -> Optional[str]:
    """Parse and run one action. Return None on success, error msg on failure."""
    # New-style: try the verb registry first. Verbs already migrated will
    # route through dispatch() and short-circuit here. Un-migrated verbs
    # fall through to the legacy if-elif chain below until Task 11.
    from cursor_pointer.verbs import dispatch as _dispatch, VerbContext as _VerbContext
    _ctx = _VerbContext(
        cp=CursorPointer(),
        boxes=boxes,
        executor=_get_executor(),
        history=history,
        log=_log,
    )
    _outcome = _dispatch(action_str, _ctx)
    _is_unknown = (
        _outcome.status == "exec_error"
        and "unknown action" in (_outcome.error or "")
    )
    if not _is_unknown:
        return _legacy_return_from_outcome(_outcome)

    cp = CursorPointer()

    m = ACTION_RE.search(action_str)
```

The legacy if-elif chain below is untouched.

- [ ] **Step 8: Run all tests to verify foundation works**

```bash
cd /Users/liuzhixiong/coding-project/cursor-pointer/python-client
python -m pytest -q
```

Expected: `108 passed, 1 skipped` (102 baseline + 6 new foundation tests).

- [ ] **Step 9: Commit**

```bash
cd /Users/liuzhixiong/coding-project/cursor-pointer
git add python-client/cursor_pointer/verbs/__init__.py \
        python-client/cursor_pointer/verbs/base.py \
        python-client/tests/verbs/__init__.py \
        python-client/tests/test_registry.py \
        python-client/tests/test_dispatch.py \
        python-client/tools/run_agent.py
git commit -m "feat(agent): verb registry foundation — base types + dispatch shell"
```

---

## Task 2: Migrate `done` + `wait`

**Files:**
- Create: `python-client/cursor_pointer/verbs/done.py`
- Modify: `python-client/cursor_pointer/verbs/__init__.py` — register
- Modify: `python-client/tools/run_agent.py` — delete old branches (lines 1029-1033)
- Test: `python-client/tests/verbs/test_done.py`

- [ ] **Step 1: Write failing test**

Create `python-client/tests/verbs/test_done.py`:

```python
"""Unit tests for done + wait verbs."""
from __future__ import annotations

import time
from unittest.mock import MagicMock

from cursor_pointer.verbs import dispatch, VerbContext
from cursor_pointer.verbs.done import DONE_VERB, WAIT_VERB


def _ctx() -> VerbContext:
    return VerbContext(
        cp=MagicMock(),
        boxes=[],
        executor=MagicMock(),
        history=[],
        log=lambda _m: None,
    )


def test_done_parse_matches_keyword():
    assert DONE_VERB.parse("done") == {"reason": ""}
    assert DONE_VERB.parse("done finished the task") == {"reason": "finished the task"}


def test_done_parse_rejects_other_verbs():
    assert DONE_VERB.parse("click 5") is None
    assert DONE_VERB.parse("scroll down") is None


def test_done_handle_returns_ok_with_done_raw_action():
    out = DONE_VERB.handle({"reason": "task complete"}, _ctx())
    assert out.status == "ok"
    assert out.intent.raw_action.lower().startswith("done")


def test_done_dispatches_via_registry():
    out = dispatch("done all set", _ctx())
    assert out.status == "ok"


def test_wait_parse_default_1_5_seconds():
    assert WAIT_VERB.parse("wait") == {"seconds": 1.5}


def test_wait_parse_explicit_seconds():
    assert WAIT_VERB.parse("wait 3") == {"seconds": 3.0}
    assert WAIT_VERB.parse("wait 0") == {"seconds": 0.0}


def test_wait_parse_rejects_non_wait():
    assert WAIT_VERB.parse("done") is None
    assert WAIT_VERB.parse("waiter") is None


def test_wait_handle_sleeps(monkeypatch):
    captured = []
    monkeypatch.setattr(time, "sleep", lambda s: captured.append(s))
    out = WAIT_VERB.handle({"seconds": 0.5}, _ctx())
    assert captured == [0.5]
    assert out.status == "executed_unverified"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/verbs/test_done.py -v
```

Expected: `ModuleNotFoundError: cursor_pointer.verbs.done`.

- [ ] **Step 3: Implement `verbs/done.py`**

Create `python-client/cursor_pointer/verbs/done.py`:

```python
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
    raw = "done " + args.get("reason", "") if args.get("reason") else "done"
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
```

- [ ] **Step 4: Register in REGISTRY**

In `python-client/cursor_pointer/verbs/__init__.py`, replace:

```python
REGISTRY: tuple[Verb, ...] = ()
```

with:

```python
from .done import DONE_VERB, WAIT_VERB

REGISTRY: tuple[Verb, ...] = (
    DONE_VERB,
    WAIT_VERB,
)
```

- [ ] **Step 5: Delete legacy if-elif branches in `run_agent.py`**

In `python-client/tools/run_agent.py`, delete lines 1029-1033 (the `if verb == "done":` and `if verb == "wait":` branches). Specifically, delete:

```python
    if verb == "done":
        return "DONE"
    if verb == "wait":
        time.sleep(float(arg) if arg and arg.isdigit() else 1.5)
        return None
```

- [ ] **Step 6: Run all tests + verify behavior unchanged**

```bash
python -m pytest -q
```

Expected: `116 passed, 1 skipped` (108 from Task 1 + 8 new).

- [ ] **Step 7: Commit**

```bash
git add python-client/cursor_pointer/verbs/done.py \
        python-client/cursor_pointer/verbs/__init__.py \
        python-client/tests/verbs/test_done.py \
        python-client/tools/run_agent.py
git commit -m "feat(agent): migrate done + wait verbs to registry"
```

---

## Task 3: Migrate `scroll_to` + `scroll`

**Files:**
- Create: `python-client/cursor_pointer/verbs/scroll.py`
- Modify: `python-client/cursor_pointer/verbs/__init__.py`
- Modify: `python-client/tools/run_agent.py` — delete lines 1034-1090
- Test: `python-client/tests/verbs/test_scroll.py`

These two need to live behind a single category file. **`scroll_to` MUST come before `scroll` in REGISTRY** so `scroll_to 5` doesn't match the `scroll` regex first.

- [ ] **Step 1: Write failing test**

Create `python-client/tests/verbs/test_scroll.py`:

```python
"""Unit tests for scroll + scroll_to verbs."""
from __future__ import annotations

from unittest.mock import MagicMock

from cursor_pointer.verbs import dispatch, VerbContext
from cursor_pointer.verbs.scroll import SCROLL_VERB, SCROLL_TO_VERB


def _ctx(boxes=None) -> VerbContext:
    return VerbContext(
        cp=MagicMock(),
        boxes=boxes or [],
        executor=MagicMock(),
        history=[],
        log=lambda _m: None,
    )


def test_scroll_parse_down_default():
    assert SCROLL_VERB.parse("scroll") == {"direction": "down", "amount": 6}


def test_scroll_parse_up():
    assert SCROLL_VERB.parse("scroll up") == {"direction": "up", "amount": 6}


def test_scroll_parse_numeric_amount():
    assert SCROLL_VERB.parse("scroll 12") == {"direction": "down", "amount": 12}


def test_scroll_parse_rejects_scroll_to():
    assert SCROLL_VERB.parse("scroll_to 5") is None


def test_scroll_to_parse_id():
    assert SCROLL_TO_VERB.parse("scroll_to 5") == {"id": 5}


def test_scroll_to_parse_rejects_scroll():
    assert SCROLL_TO_VERB.parse("scroll down") is None


def test_dispatch_scroll_to_routes_correctly():
    """Crucial: scroll_to_5 must hit SCROLL_TO_VERB, not SCROLL_VERB."""
    out = dispatch("scroll_to 5", _ctx(boxes=[]))
    # boxes empty → handler returns exec_error from missing element. But
    # critically the OUTCOME must come from scroll_to handler, not scroll.
    # We verify by checking raw_action.
    assert "scroll_to" in (out.intent.raw_action or "")


def test_scroll_handle_calls_cp_scroll():
    cp = MagicMock()
    box = {"id": 1, "x": 100, "y": 100, "w": 50, "h": 50}
    ctx = _ctx(boxes=[box])
    ctx.cp = cp
    out = SCROLL_VERB.handle({"direction": "down", "amount": 6}, ctx)
    assert out.status == "executed_unverified"
    cp.scroll.assert_called_once()


def test_scroll_to_handle_no_ax_ref_returns_error():
    box = {"id": 5, "x": 0, "y": 0, "w": 10, "h": 10}  # no ax_ref
    ctx = _ctx(boxes=[box])
    out = SCROLL_TO_VERB.handle({"id": 5}, ctx)
    assert out.status == "exec_error"


def test_scroll_to_handle_missing_id_returns_error():
    ctx = _ctx(boxes=[])
    out = SCROLL_TO_VERB.handle({"id": 99}, ctx)
    assert out.status == "exec_error"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/verbs/test_scroll.py -v
```

Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement `verbs/scroll.py`**

Read `python-client/tools/run_agent.py:1034-1090` for the verbatim source. Create `python-client/cursor_pointer/verbs/scroll.py`:

```python
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
```

- [ ] **Step 4: Register in REGISTRY**

In `python-client/cursor_pointer/verbs/__init__.py`:

```python
from .done import DONE_VERB, WAIT_VERB
from .scroll import SCROLL_TO_VERB, SCROLL_VERB

REGISTRY: tuple[Verb, ...] = (
    DONE_VERB,
    WAIT_VERB,
    SCROLL_TO_VERB,    # MUST come before SCROLL_VERB
    SCROLL_VERB,
)
```

- [ ] **Step 5: Delete legacy if-elif branches in `run_agent.py`**

Delete lines 1034-1090 — the `if verb == "scroll":` and `if verb == "scroll_to":` blocks.

- [ ] **Step 6: Run all tests**

```bash
python -m pytest -q
```

Expected: `126 passed, 1 skipped` (116 + 10 new).

- [ ] **Step 7: Commit**

```bash
git add python-client/cursor_pointer/verbs/scroll.py \
        python-client/cursor_pointer/verbs/__init__.py \
        python-client/tests/verbs/test_scroll.py \
        python-client/tools/run_agent.py
git commit -m "feat(agent): migrate scroll + scroll_to verbs to registry"
```

---

## Task 4: Migrate `drag`

**Files:**
- Create: `python-client/cursor_pointer/verbs/mouse.py`
- Modify: `verbs/__init__.py`, `run_agent.py` (delete lines 1091-1106)
- Test: `tests/verbs/test_drag.py`

- [ ] **Step 1: Write failing test**

Create `python-client/tests/verbs/test_drag.py`:

```python
from __future__ import annotations

from unittest.mock import MagicMock

from cursor_pointer.verbs import VerbContext
from cursor_pointer.verbs.mouse import DRAG_VERB


def _ctx(boxes=None) -> VerbContext:
    return VerbContext(cp=MagicMock(), boxes=boxes or [],
                       executor=MagicMock(), history=[], log=lambda _m: None)


def test_drag_parse_canonical():
    assert DRAG_VERB.parse("drag 1 to 2") == {"from_id": 1, "to_id": 2}


def test_drag_parse_rejects_missing_to():
    assert DRAG_VERB.parse("drag 1 2") is None


def test_drag_parse_rejects_other_verb():
    assert DRAG_VERB.parse("click 5") is None


def test_drag_handle_missing_ids_returns_error():
    ctx = _ctx(boxes=[])
    out = DRAG_VERB.handle({"from_id": 1, "to_id": 2}, ctx)
    assert out.status == "exec_error"


def test_drag_handle_calls_cp_drag():
    cp = MagicMock()
    boxes = [
        {"id": 1, "x": 0, "y": 0, "w": 10, "h": 10},
        {"id": 2, "x": 100, "y": 100, "w": 10, "h": 10},
    ]
    ctx = _ctx(boxes=boxes)
    ctx.cp = cp
    out = DRAG_VERB.handle({"from_id": 1, "to_id": 2}, ctx)
    assert out.status == "executed_unverified"
    cp.drag.assert_called_once()
```

- [ ] **Step 2: Run test to verify fail**

```bash
python -m pytest tests/verbs/test_drag.py -v
```

Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement `verbs/mouse.py`**

Reference source: `python-client/tools/run_agent.py:1091-1106`. Create `python-client/cursor_pointer/verbs/mouse.py`:

```python
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
```

- [ ] **Step 4: Register**

In `python-client/cursor_pointer/verbs/__init__.py`:

```python
from .done import DONE_VERB, WAIT_VERB
from .scroll import SCROLL_TO_VERB, SCROLL_VERB
from .mouse import DRAG_VERB

REGISTRY: tuple[Verb, ...] = (
    DONE_VERB, WAIT_VERB,
    SCROLL_TO_VERB, SCROLL_VERB,
    DRAG_VERB,
)
```

- [ ] **Step 5: Delete legacy branch**

Delete lines 1091-1106 from `run_agent.py` (the `if verb == "drag":` block).

- [ ] **Step 6: Run all tests**

```bash
python -m pytest -q
```

Expected: `131 passed, 1 skipped` (126 + 5).

- [ ] **Step 7: Commit**

```bash
git add python-client/cursor_pointer/verbs/mouse.py \
        python-client/cursor_pointer/verbs/__init__.py \
        python-client/tests/verbs/test_drag.py \
        python-client/tools/run_agent.py
git commit -m "feat(agent): migrate drag verb to registry"
```

---

## Task 5: Migrate `app`

**Files:**
- Create: `python-client/cursor_pointer/verbs/system.py`
- Modify: `verbs/__init__.py`, `run_agent.py` (delete lines 1107-1149)
- Test: `tests/verbs/test_app.py`

- [ ] **Step 1: Write failing test**

Create `python-client/tests/verbs/test_app.py`:

```python
from __future__ import annotations

from unittest.mock import MagicMock, patch

from cursor_pointer.verbs import VerbContext
from cursor_pointer.verbs.system import APP_VERB


def _ctx():
    return VerbContext(cp=MagicMock(), boxes=[], executor=MagicMock(),
                       history=[], log=lambda _m: None)


def test_app_parse_simple_name():
    assert APP_VERB.parse("app Finder") == {"name": "Finder"}


def test_app_parse_quoted_name():
    assert APP_VERB.parse('app "Google Chrome"') == {"name": "Google Chrome"}


def test_app_parse_bundle_id():
    assert APP_VERB.parse("app com.apple.finder") == {"name": "com.apple.finder"}


def test_app_parse_rejects_other():
    assert APP_VERB.parse("click 5") is None


def test_app_parse_rejects_empty():
    assert APP_VERB.parse("app") is None


def test_app_handle_osascript_success():
    with patch("subprocess.run") as run:
        run.return_value = MagicMock(stdout=b"", stderr=b"")
        out = APP_VERB.handle({"name": "Finder"}, _ctx())
    assert out.status == "executed_unverified"


def test_app_handle_osascript_fail_open_fallback_success():
    import subprocess
    err = subprocess.CalledProcessError(1, "osascript")
    err.stderr = b"some error"
    with patch("subprocess.run") as run:
        run.side_effect = [err, MagicMock(stdout=b"", stderr=b"")]
        out = APP_VERB.handle({"name": "Foo"}, _ctx())
    assert out.status == "executed_unverified"
```

- [ ] **Step 2: Run test to verify fail**

```bash
python -m pytest tests/verbs/test_app.py -v
```

Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement `verbs/system.py` (just `app` for now)**

Reference source: `python-client/tools/run_agent.py:1107-1149`. Create `python-client/cursor_pointer/verbs/system.py`:

```python
"""System-level verbs: app, clipboard, shell."""
from __future__ import annotations

import re
import subprocess
from typing import Optional

from ..intent import Outcome
from .base import Verb, VerbContext, make_placeholder_intent


# ---------- app ----------

_APP_RE = re.compile(r"^\s*app\s+(.+?)\s*$", re.IGNORECASE)


def _parse_app(s: str) -> Optional[dict]:
    m = _APP_RE.match(s)
    if not m:
        return None
    name = m.group(1).strip().strip('"').strip()
    if not name:
        return None
    return {"name": name}


def _handle_app(args: dict, ctx: VerbContext) -> Outcome:
    name = args["name"]
    raw = f"app {name}"
    placeholder = make_placeholder_intent(raw)

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
```

- [ ] **Step 4: Register**

In `verbs/__init__.py`:

```python
from .done import DONE_VERB, WAIT_VERB
from .scroll import SCROLL_TO_VERB, SCROLL_VERB
from .mouse import DRAG_VERB
from .system import APP_VERB

REGISTRY: tuple[Verb, ...] = (
    DONE_VERB, WAIT_VERB,
    SCROLL_TO_VERB, SCROLL_VERB,
    DRAG_VERB, APP_VERB,
)
```

- [ ] **Step 5: Delete legacy branch (lines 1107-1149)**

Delete the `if verb == "app":` block from `run_agent.py`.

- [ ] **Step 6: Run all tests**

```bash
python -m pytest -q
```

Expected: `138 passed, 1 skipped` (131 + 7).

- [ ] **Step 7: Commit**

```bash
git add python-client/cursor_pointer/verbs/system.py \
        python-client/cursor_pointer/verbs/__init__.py \
        python-client/tests/verbs/test_app.py \
        python-client/tools/run_agent.py
git commit -m "feat(agent): migrate app verb to registry"
```

---

## Task 6: Migrate `clipboard`

**Files:**
- Modify: `python-client/cursor_pointer/verbs/system.py` (extend)
- Modify: `verbs/__init__.py`, `run_agent.py` (delete lines 1150-1170)
- Test: `tests/verbs/test_clipboard.py`

- [ ] **Step 1: Write failing test**

Create `python-client/tests/verbs/test_clipboard.py`:

```python
from __future__ import annotations

from unittest.mock import MagicMock

from cursor_pointer.verbs import VerbContext
from cursor_pointer.verbs.system import CLIPBOARD_VERB


def _ctx():
    return VerbContext(cp=MagicMock(), boxes=[], executor=MagicMock(),
                       history=[], log=lambda _m: None)


def test_clipboard_parse_read():
    assert CLIPBOARD_VERB.parse("clipboard read") == {"op": "read", "text": None}


def test_clipboard_parse_write():
    assert CLIPBOARD_VERB.parse('clipboard write "hello"') == \
        {"op": "write", "text": "hello"}


def test_clipboard_parse_rejects_others():
    assert CLIPBOARD_VERB.parse("click 5") is None
    assert CLIPBOARD_VERB.parse("clipboard") is None


def test_clipboard_handle_read():
    ctx = _ctx()
    ctx.cp.clipboard_get.return_value = "abc"
    out = CLIPBOARD_VERB.handle({"op": "read", "text": None}, ctx)
    assert out.status == "executed_unverified"
    assert any("clipboard read" in h for h in ctx.history)


def test_clipboard_handle_write_calls_set():
    ctx = _ctx()
    out = CLIPBOARD_VERB.handle({"op": "write", "text": "hello"}, ctx)
    ctx.cp.clipboard_set.assert_called_once_with("hello")
    assert out.status == "executed_unverified"
```

- [ ] **Step 2: Run test to verify fail**

```bash
python -m pytest tests/verbs/test_clipboard.py -v
```

Expected: ImportError on `CLIPBOARD_VERB`.

- [ ] **Step 3: Extend `verbs/system.py`**

Append to `python-client/cursor_pointer/verbs/system.py`:

```python
# ---------- clipboard ----------

_CLIPBOARD_READ_RE = re.compile(r"^\s*clipboard\s+read\s*$", re.IGNORECASE)
_CLIPBOARD_WRITE_RE = re.compile(
    r'^\s*clipboard\s+write\s+"([^"]*)"\s*$', re.IGNORECASE
)


def _parse_clipboard(s: str) -> Optional[dict]:
    m = _CLIPBOARD_READ_RE.match(s)
    if m:
        return {"op": "read", "text": None}
    m = _CLIPBOARD_WRITE_RE.match(s)
    if m:
        return {"op": "write", "text": m.group(1)}
    return None


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
    # write
    text = args.get("text") or ""
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


CLIPBOARD_VERB = Verb(
    name="clipboard",
    parse=_parse_clipboard,
    handle=_handle_clipboard,
    grammar_hint='clipboard read / clipboard write "<text>"  # 剪贴板读写',
)
```

- [ ] **Step 4: Register**

In `verbs/__init__.py`:

```python
from .system import APP_VERB, CLIPBOARD_VERB

REGISTRY: tuple[Verb, ...] = (
    DONE_VERB, WAIT_VERB,
    SCROLL_TO_VERB, SCROLL_VERB,
    DRAG_VERB, APP_VERB,
    CLIPBOARD_VERB,
)
```

- [ ] **Step 5: Delete legacy branch (lines 1150-1170)**

Delete the `if verb == "clipboard":` block from `run_agent.py`.

- [ ] **Step 6: Run all tests**

```bash
python -m pytest -q
```

Expected: `144 passed, 1 skipped` (138 + 6).

- [ ] **Step 7: Commit**

```bash
git add python-client/cursor_pointer/verbs/system.py \
        python-client/cursor_pointer/verbs/__init__.py \
        python-client/tests/verbs/test_clipboard.py \
        python-client/tools/run_agent.py
git commit -m "feat(agent): migrate clipboard verb to registry"
```

---

## Task 7: Migrate `shell`

**Files:**
- Modify: `python-client/cursor_pointer/verbs/system.py` (extend)
- Modify: `verbs/__init__.py`, `run_agent.py` (delete lines 1171-1198)
- Test: `tests/verbs/test_shell.py`

`shell` uses a `SHELL_WHITELIST` defined at `run_agent.py:795`. The whitelist needs to move alongside the verb.

- [ ] **Step 1: Read the existing whitelist**

Find the `SHELL_WHITELIST = frozenset({...})` block in `run_agent.py` (line 795 onward, ~10-30 entries). It will be moved verbatim into `verbs/system.py`.

- [ ] **Step 2: Write failing test**

Create `python-client/tests/verbs/test_shell.py`:

```python
from __future__ import annotations

from unittest.mock import MagicMock, patch

from cursor_pointer.verbs import VerbContext
from cursor_pointer.verbs.system import SHELL_VERB, SHELL_WHITELIST


def _ctx():
    return VerbContext(cp=MagicMock(), boxes=[], executor=MagicMock(),
                       history=[], log=lambda _m: None)


def test_shell_parse_simple():
    assert SHELL_VERB.parse("shell ls -la") == {"cmd": "ls -la"}


def test_shell_parse_rejects_empty():
    assert SHELL_VERB.parse("shell") is None


def test_shell_parse_rejects_other():
    assert SHELL_VERB.parse("click 5") is None


def test_shell_handle_whitelisted_command():
    with patch("subprocess.run") as run:
        run.return_value = MagicMock(stdout="hi", stderr="")
        ctx = _ctx()
        out = SHELL_VERB.handle({"cmd": "echo hi"}, ctx)
    assert out.status == "executed_unverified"
    assert any("shell" in h for h in ctx.history)


def test_shell_handle_rejects_non_whitelisted():
    out = SHELL_VERB.handle({"cmd": "rm -rf /"}, _ctx())
    assert out.status == "exec_error"
    assert "whitelist" in (out.error or "")


def test_shell_whitelist_contains_safe_readonly_commands():
    assert "ls" in SHELL_WHITELIST
    assert "echo" in SHELL_WHITELIST
```

- [ ] **Step 3: Run test to verify fail**

```bash
python -m pytest tests/verbs/test_shell.py -v
```

Expected: ImportError on `SHELL_VERB` / `SHELL_WHITELIST`.

- [ ] **Step 4: Extend `verbs/system.py`**

First, **read `python-client/tools/run_agent.py:795` to copy the exact whitelist contents**, then append to `python-client/cursor_pointer/verbs/system.py`:

```python
# ---------- shell ----------

import shlex


# Whitelist of safe read-only commands. Mirrors the SHELL_WHITELIST in
# run_agent.py at migration time — keep this in sync if the agent verb set
# grows.
SHELL_WHITELIST = frozenset({
    # COPY VERBATIM from run_agent.py:795 — read that file first.
})


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
```

**Important:** After pasting, replace the empty SHELL_WHITELIST body with the verbatim contents from `run_agent.py:795`.

- [ ] **Step 5: Register**

In `verbs/__init__.py`:

```python
from .system import APP_VERB, CLIPBOARD_VERB, SHELL_VERB

REGISTRY: tuple[Verb, ...] = (
    DONE_VERB, WAIT_VERB,
    SCROLL_TO_VERB, SCROLL_VERB,
    DRAG_VERB, APP_VERB,
    CLIPBOARD_VERB, SHELL_VERB,
)
```

- [ ] **Step 6: Delete legacy branch (lines 1171-1198)**

Delete the `if verb == "shell":` block from `run_agent.py`. Leave the `SHELL_WHITELIST` definition in `run_agent.py:795` in place for now — Task 11 (finalizer) deletes it after confirming no other code references it.

- [ ] **Step 7: Run all tests**

```bash
python -m pytest -q
```

Expected: `150 passed, 1 skipped` (144 + 6).

- [ ] **Step 8: Commit**

```bash
git add python-client/cursor_pointer/verbs/system.py \
        python-client/cursor_pointer/verbs/__init__.py \
        python-client/tests/verbs/test_shell.py \
        python-client/tools/run_agent.py
git commit -m "feat(agent): migrate shell verb to registry (whitelist copied)"
```

---

## Task 8: Migrate `browser`

**Files:**
- Create: `python-client/cursor_pointer/verbs/browser.py`
- Modify: `verbs/__init__.py`, `run_agent.py` (delete lines 1199-1236)
- Test: `tests/verbs/test_browser_verb.py` (suffix `_verb` to not collide with playwright `browser`)

- [ ] **Step 1: Write failing test**

Create `python-client/tests/verbs/test_browser_verb.py`:

```python
from __future__ import annotations

from unittest.mock import MagicMock

from cursor_pointer.verbs import VerbContext
from cursor_pointer.verbs.browser import BROWSER_VERB


def _ctx():
    return VerbContext(cp=MagicMock(), boxes=[], executor=MagicMock(),
                       history=[], log=lambda _m: None)


def test_browser_parse_quoted_task():
    assert BROWSER_VERB.parse('browser "search for X"') == \
        {"command": "search for X"}


def test_browser_parse_rejects_unquoted():
    assert BROWSER_VERB.parse("browser hello") is None


def test_browser_parse_rejects_empty():
    assert BROWSER_VERB.parse('browser ""') is None


def test_browser_handle_enqueue_failure():
    ctx = _ctx()
    ctx.cp.browser_enqueue.side_effect = Exception("net down")
    out = BROWSER_VERB.handle({"command": "open google"}, ctx)
    assert out.status == "exec_error"
    assert "browser enqueue failed" in (out.error or "")


def test_browser_handle_success_polls_until_done():
    ctx = _ctx()
    ctx.cp.browser_enqueue.return_value = {"id": "abc123"}
    ctx.cp.browser_result_status.side_effect = [
        {"status": "pending"},
        {"status": "done", "ok": True, "output": "result text"},
    ]
    out = BROWSER_VERB.handle({"command": "open google"}, ctx)
    assert out.status == "executed_unverified"
    assert any("browser" in h for h in ctx.history)


def test_browser_handle_expired():
    ctx = _ctx()
    ctx.cp.browser_enqueue.return_value = {"id": "abc"}
    ctx.cp.browser_result_status.return_value = {"status": "expired"}
    out = BROWSER_VERB.handle({"command": "x"}, ctx)
    assert out.status == "exec_error"
    assert "expired" in (out.error or "").lower()
```

- [ ] **Step 2: Run test to verify fail**

```bash
python -m pytest tests/verbs/test_browser_verb.py -v
```

Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement `verbs/browser.py`**

Reference source: `python-client/tools/run_agent.py:1199-1236`. Create `python-client/cursor_pointer/verbs/browser.py`:

```python
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
```

- [ ] **Step 4: Register**

In `verbs/__init__.py`:

```python
from .browser import BROWSER_VERB

REGISTRY: tuple[Verb, ...] = (
    DONE_VERB, WAIT_VERB,
    SCROLL_TO_VERB, SCROLL_VERB,
    DRAG_VERB, APP_VERB,
    CLIPBOARD_VERB, SHELL_VERB, BROWSER_VERB,
)
```

- [ ] **Step 5: Delete legacy branch (lines 1199-1236)**

Delete the `if verb == "browser":` block from `run_agent.py`.

- [ ] **Step 6: Run all tests**

```bash
python -m pytest -q
```

Expected: `155 passed, 1 skipped` (150 + 5).

- [ ] **Step 7: Commit**

```bash
git add python-client/cursor_pointer/verbs/browser.py \
        python-client/cursor_pointer/verbs/__init__.py \
        python-client/tests/verbs/test_browser_verb.py \
        python-client/tools/run_agent.py
git commit -m "feat(agent): migrate browser verb to registry"
```

---

## Task 9: Migrate `type` + `key`

**Files:**
- Create: `python-client/cursor_pointer/verbs/keyboard.py`
- Modify: `verbs/__init__.py`, `run_agent.py` (delete lines 1237-1275)
- Test: `tests/verbs/test_keyboard.py`

`type` is currently the executor-driven path. Its verb handler is a thin wrapper that calls `build_type_intent` + `ctx.executor.execute(intent)`. `key` is legacy-bodied.

- [ ] **Step 1: Write failing test**

Create `python-client/tests/verbs/test_keyboard.py`:

```python
from __future__ import annotations

from unittest.mock import MagicMock

from cursor_pointer.verbs import VerbContext
from cursor_pointer.verbs.keyboard import KEY_VERB, TYPE_VERB


def _ctx(executor=None):
    return VerbContext(
        cp=MagicMock(), boxes=[],
        executor=executor or MagicMock(), history=[], log=lambda _m: None,
    )


def test_type_parse_quoted():
    assert TYPE_VERB.parse('type "hello world"') == {"text": "hello world"}


def test_type_parse_unquoted():
    assert TYPE_VERB.parse("type hello") == {"text": "hello"}


def test_type_parse_rejects_empty():
    assert TYPE_VERB.parse("type") is None


def test_type_handle_delegates_to_executor():
    exec_mock = MagicMock()
    fake_outcome = MagicMock(status="ok", used_path="none",
                              relocate_drift_px=None, error=None,
                              elapsed_ms=5,
                              intent=MagicMock(raw_action='type "hi"'))
    exec_mock.execute.return_value = fake_outcome
    ctx = _ctx(executor=exec_mock)
    out = TYPE_VERB.handle({"text": "hi"}, ctx)
    exec_mock.execute.assert_called_once()
    intent_arg = exec_mock.execute.call_args.args[0]
    assert intent_arg.kind == "type"
    assert intent_arg.payload["text"] == "hi"
    assert out is fake_outcome


def test_key_parse_simple():
    assert KEY_VERB.parse("key enter") == {"key": "enter", "modifiers": []}


def test_key_parse_combo():
    assert KEY_VERB.parse("key cmd+a") == \
        {"key": "a", "modifiers": ["cmd"]}


def test_key_parse_default_enter():
    assert KEY_VERB.parse("key") == {"key": "enter", "modifiers": []}


def test_key_handle_calls_cp_key():
    ctx = _ctx()
    out = KEY_VERB.handle({"key": "a", "modifiers": ["cmd"]}, ctx)
    ctx.cp.key.assert_called_once_with("a", modifiers=["cmd"])
    assert out.status == "executed_unverified"
```

- [ ] **Step 2: Run test to verify fail**

```bash
python -m pytest tests/verbs/test_keyboard.py -v
```

Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement `verbs/keyboard.py`**

Create `python-client/cursor_pointer/verbs/keyboard.py`:

```python
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
    # Need the current screenshot for IntentBuilder. The executor will take
    # its own anyway; this one is just for the visual hash of the (absent)
    # target. We can pass empty bytes since there's no target.
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
```

- [ ] **Step 4: Register**

In `verbs/__init__.py`:

```python
from .keyboard import KEY_VERB, TYPE_VERB

REGISTRY: tuple[Verb, ...] = (
    DONE_VERB, WAIT_VERB,
    SCROLL_TO_VERB, SCROLL_VERB,
    DRAG_VERB, APP_VERB,
    CLIPBOARD_VERB, SHELL_VERB, BROWSER_VERB,
    TYPE_VERB, KEY_VERB,
)
```

- [ ] **Step 5: Delete legacy branches (lines 1237-1275)**

Delete the `if verb == "type":` and `if verb == "key":` blocks from `run_agent.py`.

- [ ] **Step 6: Run all tests**

```bash
python -m pytest -q
```

Expected: `164 passed, 1 skipped` (155 + 9).

- [ ] **Step 7: Commit**

```bash
git add python-client/cursor_pointer/verbs/keyboard.py \
        python-client/cursor_pointer/verbs/__init__.py \
        python-client/tests/verbs/test_keyboard.py \
        python-client/tools/run_agent.py
git commit -m "feat(agent): migrate type + key verbs to registry"
```

---

## Task 10: Migrate `click` + `dclick` + `rclick`

**Files:**
- Create: `python-client/cursor_pointer/verbs/click.py`
- Modify: `verbs/__init__.py`, `run_agent.py` (delete the `if verb in ("click", "dclick", "rclick"):` block)
- Test: `tests/verbs/test_click_verb.py`

`click` delegates to ActionExecutor. `dclick`/`rclick` keep legacy hover-then-click bodies.

- [ ] **Step 1: Write failing test**

Create `python-client/tests/verbs/test_click_verb.py`:

```python
from __future__ import annotations

from unittest.mock import MagicMock, patch

from cursor_pointer.verbs import VerbContext
from cursor_pointer.verbs.click import CLICK_VERB, DCLICK_VERB, RCLICK_VERB


def _ctx(boxes=None, executor=None):
    return VerbContext(
        cp=MagicMock(), boxes=boxes or [],
        executor=executor or MagicMock(), history=[], log=lambda _m: None,
    )


def test_click_parse():
    assert CLICK_VERB.parse("click 5") == {"id": 5}


def test_click_parse_rejects_dclick():
    assert CLICK_VERB.parse("dclick 5") is None


def test_dclick_parse():
    assert DCLICK_VERB.parse("dclick 5") == {"id": 5}


def test_rclick_parse():
    assert RCLICK_VERB.parse("rclick 5") == {"id": 5}


def test_click_handle_missing_box_returns_error():
    out = CLICK_VERB.handle({"id": 99}, _ctx(boxes=[]))
    assert out.status == "exec_error" or out.status == "mismatch_target"


def test_click_handle_delegates_to_executor():
    exec_mock = MagicMock()
    fake_outcome = MagicMock(status="ok", used_path="ax_press",
                              relocate_drift_px=0, error=None, elapsed_ms=5,
                              intent=MagicMock(raw_action="click 5"))
    exec_mock.execute.return_value = fake_outcome
    box = {"id": 5, "x": 10, "y": 10, "w": 50, "h": 30,
           "role": "AXButton", "label": "Send", "ax_ref": "REF"}
    ctx = _ctx(boxes=[box], executor=exec_mock)
    out = CLICK_VERB.handle({"id": 5}, ctx)
    exec_mock.execute.assert_called_once()
    assert out is fake_outcome


def test_dclick_handle_calls_hover_then_click_count_2():
    box = {"id": 5, "x": 10, "y": 10, "w": 50, "h": 30,
           "role": "AXButton", "label": "Send", "ax_ref": "REF"}
    ctx = _ctx(boxes=[box])
    out = DCLICK_VERB.handle({"id": 5}, ctx)
    assert out.status == "executed_unverified"
    # The legacy body uses hover_then_click which moves then clicks; the
    # mocked cp records both.
    assert ctx.cp.move.called


def test_rclick_handle_uses_right_button():
    box = {"id": 5, "x": 10, "y": 10, "w": 50, "h": 30,
           "role": "AXButton", "label": "Send", "ax_ref": "REF"}
    ctx = _ctx(boxes=[box])
    out = RCLICK_VERB.handle({"id": 5}, ctx)
    assert out.status == "executed_unverified"
    # The click call uses button="right"
    args, kwargs = ctx.cp.click.call_args
    assert kwargs.get("button") == "right"
```

- [ ] **Step 2: Run test to verify fail**

```bash
python -m pytest tests/verbs/test_click_verb.py -v
```

Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement `verbs/click.py`**

Create `python-client/cursor_pointer/verbs/click.py`:

```python
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
    # The executor builds its own visual hash via screenshot; we pass empty
    # bytes here so build_click_intent skips the upfront pHash. The
    # executor's relocate step takes a fresh shot anyway.
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
```

- [ ] **Step 4: Register**

In `verbs/__init__.py`:

```python
from .click import CLICK_VERB, DCLICK_VERB, RCLICK_VERB

REGISTRY: tuple[Verb, ...] = (
    DONE_VERB, WAIT_VERB,
    SCROLL_TO_VERB, SCROLL_VERB,
    DRAG_VERB, APP_VERB,
    CLIPBOARD_VERB, SHELL_VERB, BROWSER_VERB,
    TYPE_VERB, KEY_VERB,
    DCLICK_VERB, RCLICK_VERB, CLICK_VERB,
)
```

- [ ] **Step 5: Delete legacy branches**

Delete the `if verb in ("click", "dclick", "rclick"):` block from `run_agent.py` (the entire block — formerly lines 1276 onward, now smaller since other verbs are gone).

- [ ] **Step 6: Run all tests**

```bash
python -m pytest -q
```

Expected: `173 passed, 1 skipped` (164 + 9).

- [ ] **Step 7: Commit**

```bash
git add python-client/cursor_pointer/verbs/click.py \
        python-client/cursor_pointer/verbs/__init__.py \
        python-client/tests/verbs/test_click_verb.py \
        python-client/tools/run_agent.py
git commit -m "feat(agent): migrate click + dclick + rclick verbs to registry"
```

---

## Task 11: Finalize — delete `ACTION_RE`, simplify `execute()`, auto-generate prompt grammar

After Task 10 all 14 verbs route through `dispatch()`. The if-elif chain in `execute()` is unreachable (every input either matches a registered verb or gets `exec_error: unknown action`). Time to clean up.

**Files:**
- Modify: `python-client/tools/run_agent.py` — delete `ACTION_RE`, the if-elif chain, `SHELL_WHITELIST` (if no remaining refs), and switch `SYSTEM_PROMPT` to f-string with `build_grammar_section()`
- Modify: `python-client/cursor_pointer/__init__.py` — export `Verb`, `VerbContext`, `dispatch`, `REGISTRY`

- [ ] **Step 1: Verify no remaining ACTION_RE references**

```bash
grep -n ACTION_RE /Users/liuzhixiong/coding-project/cursor-pointer/python-client/tools/run_agent.py
```

Note all usages. Expected: definition at line 1002, plus the main-loop reference at line 1659 (or thereabouts). The main-loop reference parses the action string a second time to extract the element id for post-click verification. After this task we'll replace it with a small inline regex.

- [ ] **Step 2: Replace `execute()` with a thin dispatcher**

In `python-client/tools/run_agent.py`, find the current (post-Task-10) `execute()`. It should now look like:

```python
def execute(action_str: str, boxes: list[dict]) -> Optional[str]:
    """Parse and run one action. Return None on success, error msg on failure."""
    from cursor_pointer.verbs import dispatch as _dispatch, VerbContext as _VerbContext
    _ctx = _VerbContext(
        cp=CursorPointer(),
        boxes=boxes,
        executor=_get_executor(),
        history=history,
        log=_log,
    )
    _outcome = _dispatch(action_str, _ctx)
    _is_unknown = (
        _outcome.status == "exec_error"
        and "unknown action" in (_outcome.error or "")
    )
    if not _is_unknown:
        return _legacy_return_from_outcome(_outcome)

    cp = CursorPointer()

    m = ACTION_RE.search(action_str)
    # ... legacy fallthrough — but now empty since all verbs migrated
    return f"unknown verb {m['verb'] if m else action_str!r}"
```

Replace it with:

```python
def execute(action_str: str, boxes: list[dict]) -> Optional[str]:
    """Parse and run one action. Return None on success, error msg on failure."""
    from cursor_pointer.verbs import dispatch as _dispatch, VerbContext as _VerbContext
    ctx = _VerbContext(
        cp=CursorPointer(),
        boxes=boxes,
        executor=_get_executor(),
        history=history,
        log=_log,
    )
    outcome = _dispatch(action_str, ctx)
    return _legacy_return_from_outcome(outcome)
```

(Make sure to also remove the empty `cp = CursorPointer()`, `m = ACTION_RE.search(...)`, and unknown-verb fallthrough that's left over.)

- [ ] **Step 3: Replace the second `ACTION_RE.search` in the main loop**

At `run_agent.py:1659` (or wherever the post-click verification logic lives), find:

```python
        if action.startswith(("click", "dclick", "rclick")) and result is None:
            time.sleep(1.0)
            m = ACTION_RE.search(action)
            eid = int(m["arg"]) if (m and m["arg"] and m["arg"].isdigit()) else None
```

Replace `m = ACTION_RE.search(action)` with an inline targeted regex:

```python
        if action.startswith(("click", "dclick", "rclick")) and result is None:
            time.sleep(1.0)
            import re as _re
            _m = _re.search(r"^\s*[dr]?click\s+(\d+)", action, _re.IGNORECASE)
            eid = int(_m.group(1)) if _m else None
```

(Use a different variable name `_m` to make the replacement obvious; existing `m` may still be in scope from earlier in the function — verify with surrounding code.)

- [ ] **Step 4: Delete `ACTION_RE` definition**

In `python-client/tools/run_agent.py`, find the `ACTION_RE = re.compile(...)` block (around line 1002, ~5-10 lines). Delete it entirely.

- [ ] **Step 5: Delete the `SHELL_WHITELIST` in `run_agent.py`**

Find the `SHELL_WHITELIST = frozenset({...})` block in `run_agent.py:795`. Verify nothing else in `run_agent.py` references it:

```bash
grep -n SHELL_WHITELIST /Users/liuzhixiong/coding-project/cursor-pointer/python-client/tools/run_agent.py
```

Expected: only the definition. Delete it.

- [ ] **Step 6: Switch `SYSTEM_PROMPT` to f-string with `build_grammar_section()`**

Find `SYSTEM_PROMPT = textwrap.dedent("""\` at `run_agent.py:1321`. The block currently contains a hand-maintained list:

```
    action 行的合法语法（任选一个）:

        click <id>          # 点击编号为 id 的元素
        dclick <id>         # 双击
        ...
        done <短结论>        # 任务完成或放弃
```

First, **diff-check** the auto-generated section against the current hand-maintained one:

```bash
python -c "from cursor_pointer.verbs import build_grammar_section; print(build_grammar_section())"
```

Compare the output line-by-line to lines 1334-1348 of the current `SYSTEM_PROMPT`. Adjust each verb's `grammar_hint` in its module if needed so the output matches the current prompt **byte-for-byte** (this is a one-time reconciliation — fix grammar_hint strings, NOT prompt semantics).

Once they match, replace the prompt's block. Change:

```python
SYSTEM_PROMPT = textwrap.dedent("""\
    ...
    action 行的合法语法（任选一个）:

        click <id>          # 点击编号为 id 的元素
        dclick <id>         # 双击
        ...
        done <短结论>        # 任务完成或放弃

    重要规则：
    ...
""")
```

to:

```python
from cursor_pointer.verbs import build_grammar_section as _build_grammar

SYSTEM_PROMPT = textwrap.dedent(f"""\
    ...
    action 行的合法语法（任选一个）:

{_build_grammar()}

    重要规则：
    ...
""")
```

Keep the `重要规则` and rest of the prompt body unchanged.

- [ ] **Step 7: Export from `cursor_pointer/__init__.py`**

In `python-client/cursor_pointer/__init__.py`, add lazy exports for the registry symbols. Find the existing `__getattr__`:

```python
def __getattr__(name):
    # Lazy import — agent helpers depend on Pillow + RapidOCR, optional.
    if name in {"Annotation", "Element", "annotate", "click_element"}:
        from . import annotate as _a
        return getattr(_a, name)
    if name == "Session":
        from .session import Session
        return Session
    if name == "ActionExecutor":
        from .executor import ActionExecutor
        return ActionExecutor
    if name in {"ExpectSig", "Intent", "Outcome", "TargetSig"}:
        from . import intent as _i
        return getattr(_i, name)
    raise AttributeError(name)
```

Add a verbs-registry branch before `raise AttributeError`:

```python
    if name in {"REGISTRY", "dispatch", "build_grammar_section",
                "Verb", "VerbContext"}:
        from . import verbs as _v
        return getattr(_v, name)
```

Also append the new names to `__all__`:

```python
__all__ = [
    "CursorPointer",
    "CursorPointerError",
    "Monitor",
    "Annotation", "Element", "Session", "annotate", "click_element",
    "ActionExecutor", "ExpectSig", "Intent", "Outcome", "TargetSig",
    # Verb registry
    "REGISTRY", "dispatch", "build_grammar_section", "Verb", "VerbContext",
]
```

- [ ] **Step 8: Run all tests**

```bash
cd /Users/liuzhixiong/coding-project/cursor-pointer/python-client
python -m pytest -q
```

Expected: `173 passed, 1 skipped`. **No regressions.**

- [ ] **Step 9: Smoke check — verify auto-generated prompt is intact**

```bash
python -c "from tools.run_agent import SYSTEM_PROMPT; print(SYSTEM_PROMPT)"
```

Expected: the same SYSTEM_PROMPT content as before the change, with the verb list section now auto-generated. Spot-check that each verb's grammar line is present.

- [ ] **Step 10: Verify line count reduction in `run_agent.py`**

```bash
wc -l /Users/liuzhixiong/coding-project/cursor-pointer/python-client/tools/run_agent.py
```

Expected: `run_agent.py` shrinks by roughly 300 lines (from ~1700 to ~1400) — the 14 verb branches + ACTION_RE + SHELL_WHITELIST + grammar-string lines are gone.

- [ ] **Step 11: Commit**

```bash
cd /Users/liuzhixiong/coding-project/cursor-pointer
git add python-client/tools/run_agent.py \
        python-client/cursor_pointer/__init__.py
git commit -m "feat(agent): finalize verb registry — delete legacy dispatch, auto-generate prompt grammar"
```

---

## Final regression pass

After Task 11:

- [ ] **Run full test suite**

```bash
cd /Users/liuzhixiong/coding-project/cursor-pointer/python-client
python -m pytest -v
```

Expected: `173 passed, 1 skipped`. All verb tests + all foundation tests + all closed-loop tests + planner regression + new_verbs regression.

- [ ] **Optional manual smoke** (with daemon running):

```bash
cd /Users/liuzhixiong/coding-project/cursor-pointer/python-client
python tools/run_agent.py "open TextEdit and type hello"
```

Expected: agent executes; verb dispatch logs visible. Behavior identical to pre-migration.

---

## Self-review

1. **Spec coverage:**
   - Foundation (base.py + dispatch + grammar gen) → Task 1 ✓
   - All 14 verbs migrated → Tasks 2-10 ✓
   - ACTION_RE deleted → Task 11 step 4 ✓
   - SHELL_WHITELIST moved + old deleted → Task 7 step 4, Task 11 step 5 ✓
   - SYSTEM_PROMPT auto-generated → Task 11 step 6 ✓
   - `execute()` becomes thin dispatcher → Task 11 step 2 ✓
   - Public exports → Task 11 step 7 ✓
   - Meta tests (no dup names/aliases) → Task 1 step 2 ✓
   - Dispatch-ordering test (scroll_to before scroll) → Task 3 ✓

2. **Placeholder scan:** No TBD / "implement later" / vague phrasings. The only deferred work is "copy SHELL_WHITELIST contents verbatim from run_agent.py:795" — engineer must read that line, but the location is exact.

3. **Type consistency:** `Verb`, `VerbContext`, `make_placeholder_intent`, `_legacy_return_from_outcome`, `build_grammar_section` are named identically across all tasks. Handler signatures `(args: dict, ctx: VerbContext) -> Outcome` are uniform. Verb instance names follow the convention `<NAME>_VERB`.

4. **Ambiguity:** The coexistence strategy (dispatch runs first, falls back to legacy if-elif) is explicitly described before Task 2. Each task says exactly which lines to delete from `run_agent.py`. Task 11's `ACTION_RE` second-use replacement is explicit (different variable name `_m`).
