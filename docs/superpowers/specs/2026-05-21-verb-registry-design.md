# Verb Registry — design

**Date:** 2026-05-21
**Author:** brainstorming session with @liuzhixiong
**Status:** approved → ready for implementation plan

## Problem

`python-client/tools/run_agent.py:execute()` is a 311-line `if-elif` chain handling 16 verbs. Adding a new verb requires editing five places: the shared `ACTION_RE` regex, the if-elif branch, request shape, `SYSTEM_PROMPT` grammar string, and (sometimes) the Python client. Verb parsing is order-sensitive — `scroll_to` only matches before `scroll` because of regex alternation order in `ACTION_RE`. The system prompt's verb grammar block is a hand-maintained string that drifts from reality every time a verb is added or changed.

The closed-loop contract just shipped (`2026-05-21-closed-loop-action-contract-design.md`) leaves an inconsistency: `click` and `type` go through `ActionExecutor` and return `Outcome`, but the other 14 verbs still return `None | str` and get wrapped at the call site. Half-uniform.

The fix is a **verb registry**: every verb becomes a declarative object (name + parser + handler + grammar hint), `execute()` becomes a thin dispatcher over an ordered registry, and the system prompt's grammar section is generated from the same registry. Adding a verb becomes a single file change.

## Goal

Move all 16 verbs from `run_agent.py:execute()` into per-category modules under `python-client/cursor_pointer/verbs/`. Replace the if-elif chain with `dispatch(action_str, ctx) -> Outcome`. Auto-generate the system-prompt verb grammar block. All 14 legacy verbs return `Outcome` (via the existing `_wrap_legacy_return` shape), closing the loop on the prior contract work.

**Success criteria:**

1. Adding a new verb requires touching **exactly one new file** (the verb module) plus one line in `verbs/__init__.py` (registry tuple). No edits to `run_agent.py`, no edits to `SYSTEM_PROMPT` string.
2. All 100 existing tests pass unchanged (behavior is byte-identical from the planner's perspective).
3. Each verb has a unit test covering its `parse()` (positive + negative) and its `handle()` (mocked context).
4. Registry meta-test asserts no duplicate names/aliases and every verb produces a non-None Outcome for at least one input.

## Non-goals

- **Closed-loop verify for non-click/type verbs.** Verifying scroll / key / drag / etc. requires per-verb design (what does "verify a scroll" mean?) — explicitly out of scope. Those handlers stay legacy-bodied, wrapped to `Outcome(status="executed_unverified")` like today.
- **Splitting `run_agent.py` proper.** Perception, planner, and verifier stay where they are. Only the verb dispatch leaves the file.
- **Verb behavior changes.** Every verb's body is moved **verbatim**. No refactoring, no "while we're here" cleanup. Behavioral equivalence is the migration's only success bar.
- **Verb registry as plugin/extension API.** Verbs ship in-tree. No dynamic loading, no external verb packages.
- **Cross-session learning** (theme D). Future PR; registry makes it cheap but doesn't add it.
- **Python client `CursorPointer` changes.** Untouched.
- **Tauri / Rust changes.** Untouched.

## Decisions (locked during brainstorming)

| Decision | Choice |
|---|---|
| Verb file granularity | Grouped by category — 7 files for 16 verbs (click/dclick/rclick share `click.py`; etc.). |
| Verb identity | A frozen `Verb` dataclass: `name`, `aliases`, `grammar_hint`, `parse`, `handle`. |
| Dispatch | First-match-wins iteration over an ordered tuple. Longest-prefix verbs (`scroll_to` before `scroll`) registered first. |
| Parser scope | Each verb owns its own regex. The shared `ACTION_RE` is **deleted** at the end of migration. |
| Handler signature | `handle(args: dict, ctx: VerbContext) -> Outcome`. Always returns an Outcome — no exceptions cross the boundary except programmer errors. |
| `VerbContext` shape | `cp`, `boxes`, `executor`, `history`, `log`. Adds new fields as later verbs need them. |
| Backward compat | `execute(action_str, boxes)` keeps its `(str, list[dict]) -> None | str` signature so the surrounding planner code is untouched. Internally calls `dispatch()` and converts the Outcome via the existing `_wrap_legacy_return`-symmetric helper. |
| System prompt grammar | Auto-generated from `Verb.grammar_hint` strings, inserted into `SYSTEM_PROMPT` via f-string at module load. Hand-maintained verb-list lines are deleted. |
| Migration order | Verb-by-verb. Each verb's migration is one PR-sized commit: move body verbatim, register, replace old if-elif branch with `dispatch_one()`, verify behavior equivalence via existing tests + a new unit test. After all 16 verbs migrate, delete the if-elif chain and `ACTION_RE`. |
| Exception policy in `handle()` | Try/except inside each handler; bare `Exception` becomes `Outcome(status="exec_error", error=str(e))`. No bubbling. |
| Tests location | `python-client/tests/verbs/test_<name>.py` per verb. Plus `tests/test_registry.py` (meta) and `tests/test_dispatch.py` (ordering). |

## Architecture

```
                Planner (VLM, unchanged)
                          │
                          │ action_str = "click 5"
                          ▼
        ┌─────────────────────────────────────────┐
        │ run_agent.execute(action_str, boxes)    │ ~15 lines
        │   1. build VerbContext                  │
        │   2. outcome = dispatch(action_str, ctx)│
        │   3. return _outcome_to_legacy(outcome) │
        └─────────────────────────────────────────┘
                          │
                          ▼
        ┌─────────────────────────────────────────┐
        │ cursor_pointer.verbs.dispatch()         │
        │   for verb in REGISTRY:                 │
        │     args = verb.parse(action_str)       │
        │     if args is not None:                │
        │       return verb.handle(args, ctx)     │
        │   return Outcome(exec_error, "unknown") │
        └─────────────────────────────────────────┘
                          │
                          ▼
                 (concrete verb module's handle)
                          │
                          ▼
                       Outcome
```

### New files

```
python-client/cursor_pointer/verbs/
├── __init__.py     # REGISTRY tuple + dispatch() + build_grammar_section()
├── base.py         # Verb dataclass, VerbContext dataclass
├── click.py        # click, dclick, rclick (share helpers)
├── keyboard.py     # type, key
├── scroll.py       # scroll, scroll_to
├── mouse.py        # drag
├── system.py       # app, clipboard, shell, wait
├── browser.py      # browser
└── done.py         # done
```

### Files modified

- `python-client/cursor_pointer/__init__.py` — export `Verb`, `VerbContext`, `dispatch`, `REGISTRY` (lazy).
- `python-client/tools/run_agent.py` — `execute()` becomes thin dispatcher; `ACTION_RE` and the verb if-elif chain are deleted; `SYSTEM_PROMPT` switches its verb-grammar block to an f-string interpolating `build_grammar_section()`.

### Final shape of `execute()`

After migration, the function shrinks from 311 lines to roughly:

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
    return _legacy_return_from_outcome(outcome)
```

That's the whole function. The 14 verb bodies live in `verbs/<category>.py`; the planner's surrounding code (`_wrap_legacy_return`, main loop branching) does not change.

### Files untouched

- `src-tauri/*` — no Rust changes.
- `python-client/cursor_pointer/client.py` — the SDK surface is untouched.
- `python-client/cursor_pointer/executor.py`, `intent.py`, `anchors.py` — closed-loop work stays as-is; click/type verbs delegate to it.

## Data types

```python
# verbs/base.py

from dataclasses import dataclass, field
from typing import Callable, Optional

from ..intent import Outcome


@dataclass(frozen=True)
class Verb:
    name: str
    parse: Callable[[str], Optional[dict]]
    handle: Callable[[dict, "VerbContext"], Outcome]
    aliases: tuple[str, ...] = ()
    grammar_hint: str = ""


@dataclass
class VerbContext:
    cp: object                           # CursorPointer; loose-typed to avoid cycle
    boxes: list[dict]
    executor: object                     # ActionExecutor; same reason
    history: list[str]
    log: Callable[[str], None]
```

`VerbContext` is **mutable** so handlers can append to `history`. It's intentionally loose-typed (`object`) on `cp` and `executor` to avoid circular imports — handlers can `cast` or just use duck typing.

## Dispatch

```python
# verbs/__init__.py

from .base import Verb, VerbContext
from .done import DONE_VERB, WAIT_VERB
from .scroll import SCROLL_TO_VERB, SCROLL_VERB
from .mouse import DRAG_VERB
from .system import APP_VERB, CLIPBOARD_VERB, SHELL_VERB
from .browser import BROWSER_VERB
from .keyboard import TYPE_VERB, KEY_VERB
from .click import DCLICK_VERB, RCLICK_VERB, CLICK_VERB

REGISTRY: tuple[Verb, ...] = (
    # Order matters: longer prefixes / more-specific shapes first.
    DONE_VERB, WAIT_VERB,
    SCROLL_TO_VERB, SCROLL_VERB,
    DRAG_VERB, APP_VERB,
    CLIPBOARD_VERB, SHELL_VERB, BROWSER_VERB,
    TYPE_VERB, KEY_VERB,
    DCLICK_VERB, RCLICK_VERB, CLICK_VERB,
)


def dispatch(action_str: str, ctx: VerbContext) -> Outcome:
    for verb in REGISTRY:
        args = verb.parse(action_str)
        if args is not None:
            return verb.handle(args, ctx)
    from ..intent import ExpectSig, Intent, Outcome
    placeholder = Intent(
        kind="click", target=None, payload={}, expect=ExpectSig(),
        raw_action=action_str,
    )
    return Outcome(
        status="exec_error", intent=placeholder,
        error=f"unknown action: {action_str!r}",
    )


def build_grammar_section() -> str:
    """Used by SYSTEM_PROMPT to render the verb-grammar block."""
    return "\n".join(
        f"    {v.grammar_hint}" for v in REGISTRY if v.grammar_hint
    )
```

## Parser conventions

Each verb owns its parser. Conventions:

- Return `None` if the string isn't this verb (used as the dispatch signal — first non-None wins).
- Return a `dict` of typed args on match. Convention: ints parsed, strings stripped of quotes, defaults filled in.
- Regex pinned with `^` and case-insensitive `re.IGNORECASE`.

Examples (for the plan, not exhaustive):

```python
# verbs/click.py

_CLICK_RE = re.compile(r"^\s*click\s+(\d+)\s*$", re.IGNORECASE)

def _parse_click(s: str) -> Optional[dict]:
    m = _CLICK_RE.match(s)
    return {"id": int(m.group(1))} if m else None

CLICK_VERB = Verb(
    name="click",
    parse=_parse_click,
    handle=_handle_click,
    grammar_hint="click <id>          # 点击编号为 id 的元素",
)
```

```python
# verbs/scroll.py

_SCROLL_TO_RE = re.compile(r"^\s*scroll_to\s+(\d+)\s*$", re.IGNORECASE)
_SCROLL_RE = re.compile(r"^\s*scroll\s+(up|down|\d+)?\s*$", re.IGNORECASE)

def _parse_scroll_to(s: str) -> Optional[dict]:
    m = _SCROLL_TO_RE.match(s)
    return {"id": int(m.group(1))} if m else None

def _parse_scroll(s: str) -> Optional[dict]:
    m = _SCROLL_RE.match(s)
    if not m:
        return None
    arg = m.group(1)
    if arg is None:
        return {"direction": "down", "amount": 6}
    if arg.isdigit():
        return {"direction": "down", "amount": int(arg)}
    return {"direction": arg.lower(), "amount": 6}
```

Because `scroll_to` is registered before `scroll` AND its parser is anchored to `^scroll_to\b`, both correctness layers (registration order, parser specificity) protect against the longest-prefix bug.

## Handler conventions

Each handler:

```python
def _handle_<verb>(args: dict, ctx: VerbContext) -> Outcome:
    try:
        # ... body, moved verbatim from execute() ...
        return Outcome(status="executed_unverified", intent=_placeholder(...))
    except Exception as e:
        return Outcome(status="exec_error", intent=_placeholder(...), error=str(e))
```

Click and type handlers are special: they delegate to `ctx.executor.execute(intent)` and return the executor's Outcome directly (no wrapping). The legacy 14 verbs return placeholder-intent Outcomes (since they don't have a meaningful Intent).

A small helper `make_placeholder_intent(action_str)` is shared (in `verbs/base.py`) to avoid 14 copies of the placeholder construction. Click and type handlers don't use it — they build a real Intent via `build_click_intent` / `build_type_intent`.

## System prompt generation

Today `SYSTEM_PROMPT` in `run_agent.py:1233-` contains a hand-maintained block:

```
action 行的合法语法（任选一个）:

    click <id>          # 点击编号为 id 的元素
    dclick <id>         # 双击
    rclick <id>         # 右键
    scroll <up|down|N>  # 滚动当前页面
    ...
```

After this change, that block becomes:

```python
SYSTEM_PROMPT = textwrap.dedent(f"""...
    action 行的合法语法（任选一个）:

{build_grammar_section()}
    ...""")
```

Each verb's `grammar_hint` carries the existing description. The auto-generated block is byte-identical to the current hand-maintained one at first; afterwards, it stays in sync automatically.

## Migration plan (mechanical)

The migration is staged: while in flight, the if-elif chain coexists with `dispatch()`. Each step migrates ONE verb without disturbing the others.

For each verb V:

1. Create `verbs/<category>.py` (if not yet) and add the `V_VERB = Verb(...)` instance — move the existing handler body verbatim into `_handle_<v>(args, ctx)`.
2. Add `V_VERB` to the REGISTRY tuple in `verbs/__init__.py` (in the correct order slot).
3. In `run_agent.py:execute()`, replace V's if-branch body with:
   ```python
   if <verb V matched>:
       return _legacy_return_from_outcome(dispatch_one(V_VERB, action_str, ctx))
   ```
   (`dispatch_one` is a temporary helper used during migration — just calls `V_VERB.parse(action_str)` + `V_VERB.handle(args, ctx)`. Deleted at the end.)
4. Write `tests/verbs/test_<verb>.py` — parse positive/negative, handle behavior with mocked context.
5. Run regression: full test suite must pass.
6. Commit.

After all 16 verbs migrate (16 commits):

1. Replace the entire body of `execute()` with `dispatch()` + outcome → legacy-return conversion.
2. Delete the old if-elif chain.
3. Delete `ACTION_RE`.
4. Delete the temporary `dispatch_one` helper.
5. Switch `SYSTEM_PROMPT` to use `build_grammar_section()`.
6. Delete the hand-maintained grammar string.
7. Final regression — all tests pass.
8. Commit.

## Outcome → legacy return conversion

The planner-side already expects `None | str | "DONE"`. The converter:

```python
def _legacy_return_from_outcome(outcome: Outcome) -> Optional[str]:
    if outcome.status in ("ok", "executed_unverified"):
        # The done verb returns Outcome(status="ok") with intent.raw_action.startswith("done")
        # — convert to legacy "DONE" sentinel.
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

This preserves the exact strings the planner currently sees in `result is not None` branches, including the `mismatch_target:` prefix it already matches on.

## Testing

### Per-verb unit tests (16 files under `tests/verbs/`)

Each test file follows the same shape:

```python
def test_parse_matches_canonical_form(): ...
def test_parse_rejects_other_verbs(): ...
def test_parse_handles_whitespace_and_case(): ...
def test_handle_happy_path(): ...      # mocked VerbContext
def test_handle_error_path(): ...      # when applicable
```

### Registry meta-tests (`tests/test_registry.py`)

```python
def test_no_duplicate_names():
    names = [v.name for v in REGISTRY]
    assert len(names) == len(set(names))

def test_no_duplicate_aliases():
    all_names = set()
    for v in REGISTRY:
        for n in (v.name, *v.aliases):
            assert n not in all_names, f"duplicate verb name {n!r}"
            all_names.add(n)

def test_every_verb_has_grammar_hint():
    for v in REGISTRY:
        assert v.grammar_hint, f"verb {v.name!r} missing grammar_hint"

def test_build_grammar_section_nonempty():
    assert build_grammar_section().strip()
```

### Dispatch ordering test (`tests/test_dispatch.py`)

```python
def test_scroll_to_5_routes_to_scroll_to_not_scroll():
    ctx = _ctx()
    with patch.object(SCROLL_TO_VERB, "handle") as h_to, \
         patch.object(SCROLL_VERB, "handle") as h_scroll:
        h_to.return_value = _ok_outcome("scroll_to 5")
        dispatch("scroll_to 5", ctx)
        h_to.assert_called_once()
        h_scroll.assert_not_called()

def test_unknown_action_returns_exec_error():
    out = dispatch("totally not a verb", _ctx())
    assert out.status == "exec_error"
    assert "unknown action" in (out.error or "")
```

### Regression

All 100 existing tests pass without modification. Behavior is byte-identical from the planner's perspective; the test suite is the strongest evidence.

## Risks

1. **Behavior drift during verbatim migration.** Mitigation: existing 100 tests act as a behavioral fence. Any drift is caught by `test_planner.py` / `test_new_verbs.py` regression. Manual smoke after final commit.
2. **Grammar string drift between current SYSTEM_PROMPT and auto-generated block.** Mitigation: in the final commit, the FIRST grammar section produced by `build_grammar_section()` is diffed against the current hand-maintained string (one-time check during plan execution); any mismatch is reconciled by tweaking `grammar_hint` strings, NOT by changing prompt semantics.
3. **Click reach-around / icon-row logic lost.** The current `click` if-branch contains "icon-row reach-around" heuristics that were already removed when click migrated to the executor. The verbs/click.py for `click` is just `executor.execute(intent)`. dclick/rclick keep the legacy hover-then-click body (verbatim).
4. **Circular imports.** Mitigation: `verbs/base.py` imports only stdlib + `intent`. `verbs/__init__.py` does lazy imports if needed. `VerbContext` uses `object` typing on `cp` / `executor` to avoid pulling in `client` / `executor` at module load.

## What this unlocks (out of scope here, but worth noting)

- **Theme D (cross-session learning):** with structured Outcomes carrying `used_path` and a verb registry naming each action, success rate per (app, verb, used_path) is trivially recordable. The next PR can add a `verbs/middleware.py` that wraps every `handle()` with telemetry.
- **Per-verb closed-loop verify:** the executor's verify pattern can be ported per-verb (e.g., `scroll` checks ROI delta at viewport center). Each verb's `handle()` is the natural injection point.
- **External verb extensions:** if we ever want plugin verbs (e.g., third-party app integrations), the registry becomes the extension API. Out of scope for this PR.
