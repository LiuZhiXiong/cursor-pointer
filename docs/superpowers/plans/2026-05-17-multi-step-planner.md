# Multi-step Planner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the agent's worker VLM emit a `subgoal: …` line alongside each `action: …`, track that sub-goal across steps, surface it in history, and auto-warn the VLM when the same sub-goal has failed 3 steps in a row.

**Architecture:** Module-level state (`current_subgoal`, `consec_subgoal_fails`) in `run_agent.py`. A new pure parser `parse_action_with_subgoal`. A small main-loop change that updates state after each step and augments the prompt when stuck. SYSTEM_PROMPT additions teach the VLM the new output shape.

**Tech Stack:** Python 3.11 + pytest. No new dependencies. No Rust changes. Verify_done logic stays orthogonal.

**Spec:** [`docs/superpowers/specs/2026-05-17-multi-step-planner-design.md`](../specs/2026-05-17-multi-step-planner-design.md)

---

## File Structure

| File | Role | Change |
|---|---|---|
| `python-client/tools/run_agent.py` | agent core | add parser, state, main-loop accounting, prompt aug, SYSTEM_PROMPT lines |
| `python-client/tests/test_planner.py` | unit tests | NEW file, 9 tests |

---

## Task 1: `parse_action_with_subgoal` parser (TDD)

**Files:**
- Create: `python-client/tests/test_planner.py`
- Modify: `python-client/tools/run_agent.py`

- [ ] **Step 1: write the failing parser tests**

Create `python-client/tests/test_planner.py`:

```python
"""Tests for the multi-step planner additions to run_agent.py."""
from __future__ import annotations

from run_agent import parse_action_with_subgoal


def test_parse_action_with_subgoal_two_lines():
    raw = "subgoal: 切换到漫游 tab\naction: click 13"
    sg, act = parse_action_with_subgoal(raw)
    assert sg == "切换到漫游 tab"
    assert act == "click 13"


def test_parse_action_with_subgoal_missing_subgoal():
    raw = "click 5"
    sg, act = parse_action_with_subgoal(raw)
    assert sg == "(unspecified)"
    assert act == "click 5"


def test_parse_action_with_subgoal_missing_action_falls_back_to_first_nonblank():
    """If `action:` prefix is absent, take the first non-blank, non-subgoal line."""
    raw = "subgoal: open settings\nclick 5"
    sg, act = parse_action_with_subgoal(raw)
    assert sg == "open settings"
    assert act == "click 5"


def test_parse_action_with_subgoal_case_insensitive():
    raw = "SUBGOAL: do stuff\nAction: click 7"
    sg, act = parse_action_with_subgoal(raw)
    assert sg == "do stuff"
    assert act == "click 7"


def test_parse_action_with_subgoal_extra_lines_tolerated():
    raw = (
        "Some commentary I shouldn't have written.\n"
        "subgoal: switch tab\n"
        "more noise\n"
        "action: click 3\n"
        "(reasoning trailing the action — drop me)"
    )
    sg, act = parse_action_with_subgoal(raw)
    assert sg == "switch tab"
    assert act == "click 3"
```

- [ ] **Step 2: run tests, expect ImportError**

```bash
cd /Users/liuzhixiong/coding-project/cursor-pointer/python-client
/Users/liuzhixiong/coding-project/cursor-pointer/python-client/.venv/bin/pytest tests/test_planner.py -v
```

Expected: 5 FAIL with `ImportError: cannot import name 'parse_action_with_subgoal' from 'run_agent'`.

- [ ] **Step 3: implement `parse_action_with_subgoal` in `run_agent.py`**

Find the existing `REVIEW_PROMPT = ` block in `python-client/tools/run_agent.py` (added for verify_done; should be near the `SHELL_WHITELIST` block). Immediately ABOVE `REVIEW_PROMPT`, add:

```python
# ---------------------------------------------------------------------------
# Multi-step planner — sub-goal parsing (worker VLM emits two lines per step)
# ---------------------------------------------------------------------------


def parse_action_with_subgoal(raw: str) -> tuple[str, str]:
    """Parse the VLM's two-line output.

    Lines:
        subgoal: <free text>
        action:  <click 5 | scroll down | ...>

    Tolerates extra noise lines and missing prefixes — getting an action
    is more important than enforcing the format. Defaults sub-goal to
    "(unspecified)" when missing.
    """
    subgoal = "(unspecified)"
    action = ""
    # Track whether we already harvested the subgoal/action lines so we
    # don't overwrite them when later lines also happen to look like one.
    have_sub = False
    have_act = False

    lines = [ln.strip() for ln in (raw or "").splitlines() if ln.strip()]
    for ln in lines:
        lower = ln.lower()
        if not have_sub and lower.startswith("subgoal:"):
            subgoal = ln.split(":", 1)[1].strip() or "(unspecified)"
            have_sub = True
            continue
        if not have_act and lower.startswith("action:"):
            action = ln.split(":", 1)[1].strip()
            have_act = True
            continue

    # Fallback: no `action:` prefix found — take the first non-blank,
    # non-subgoal-prefixed line as the action.
    if not action:
        for ln in lines:
            if ln.lower().startswith("subgoal:"):
                continue
            action = ln.strip()
            break

    return subgoal, action
```

- [ ] **Step 4: run tests, expect 5 PASSED**

```bash
/Users/liuzhixiong/coding-project/cursor-pointer/python-client/.venv/bin/pytest tests/test_planner.py -v
```

Expected: 5 PASSED.

- [ ] **Step 5: regression — all earlier tests still pass**

```bash
/Users/liuzhixiong/coding-project/cursor-pointer/python-client/.venv/bin/pytest tests/ -v
```

Expected: 43 PASSED (38 prior + 5 new).

- [ ] **Step 6: commit**

```bash
cd /Users/liuzhixiong/coding-project/cursor-pointer
git add python-client/tools/run_agent.py python-client/tests/test_planner.py
git commit -m "feat(agent): add parse_action_with_subgoal — sub-goal parser (TDD)"
```

---

## Task 2: module-level state + counter helpers (TDD)

**Files:**
- Modify: `python-client/tests/test_planner.py` (append)
- Modify: `python-client/tools/run_agent.py` (add state + helper)

The main-loop integration in Task 3 needs the counter logic clean and testable. Encapsulate it in one helper.

- [ ] **Step 1: append failing tests**

Append to `python-client/tests/test_planner.py`:

```python
# ---------------------------------------------------------------------------
# subgoal failure-counter accounting
# ---------------------------------------------------------------------------

from run_agent import update_subgoal_failure_counter


def test_failure_counter_increments_on_fail():
    new_count = update_subgoal_failure_counter(
        prev_count=2,
        prev_subgoal="X",
        new_subgoal="X",
        step_failed=True,
    )
    assert new_count == 3


def test_failure_counter_resets_on_success():
    new_count = update_subgoal_failure_counter(
        prev_count=2,
        prev_subgoal="X",
        new_subgoal="X",
        step_failed=False,
    )
    assert new_count == 0


def test_failure_counter_resets_when_subgoal_changes():
    """Switching sub-goals wipes the counter, whether or not the step failed."""
    assert update_subgoal_failure_counter(
        prev_count=2, prev_subgoal="X", new_subgoal="Y", step_failed=True,
    ) == 0
    assert update_subgoal_failure_counter(
        prev_count=2, prev_subgoal="X", new_subgoal="Y", step_failed=False,
    ) == 0


def test_failure_counter_initial_state():
    """Empty prev_subgoal (first step) behaves like a sub-goal change."""
    assert update_subgoal_failure_counter(
        prev_count=0, prev_subgoal="", new_subgoal="X", step_failed=True,
    ) == 1
```

- [ ] **Step 2: run, expect ImportError**

```bash
/Users/liuzhixiong/coding-project/cursor-pointer/python-client/.venv/bin/pytest tests/test_planner.py -v
```

Expected: 4 new FAIL with `cannot import name 'update_subgoal_failure_counter'`.

- [ ] **Step 3: implement state + helper**

In `python-client/tools/run_agent.py`, find the module-level `history: list[str] = []` line (added for the verb-expansion work). Add IMMEDIATELY BELOW it:

```python
# Multi-step planner state — module-level so the main loop can update and
# helper functions can read. main() resets both at the top of each run.
current_subgoal: str = ""
consec_subgoal_fails: int = 0
```

Then, immediately ABOVE the `parse_action_with_subgoal` function (added in Task 1), add:

```python
def update_subgoal_failure_counter(
    prev_count: int,
    prev_subgoal: str,
    new_subgoal: str,
    step_failed: bool,
) -> int:
    """Return the new consecutive-failure count given last/this sub-goal."""
    if prev_subgoal != new_subgoal:
        return 1 if step_failed else 0
    if step_failed:
        return prev_count + 1
    return 0
```

- [ ] **Step 4: run tests, expect 9 PASSED**

```bash
/Users/liuzhixiong/coding-project/cursor-pointer/python-client/.venv/bin/pytest tests/test_planner.py -v
```

Expected: 9 PASSED (5 parser + 4 counter).

- [ ] **Step 5: regression**

```bash
/Users/liuzhixiong/coding-project/cursor-pointer/python-client/.venv/bin/pytest tests/ -v
```

Expected: 47 PASSED.

- [ ] **Step 6: commit**

```bash
cd /Users/liuzhixiong/coding-project/cursor-pointer
git add python-client/tools/run_agent.py python-client/tests/test_planner.py
git commit -m "feat(agent): add subgoal state + failure counter helper (TDD)"
```

---

## Task 3: prompt augmentation for stuck warning (TDD)

**Files:**
- Modify: `python-client/tests/test_planner.py` (append)
- Modify: `python-client/tools/run_agent.py` (add `build_stuck_warning`)

A 5-liner helper just so the main loop in Task 4 stays readable.

- [ ] **Step 1: append failing test**

```python
# ---------------------------------------------------------------------------
# stuck-warning prompt augmentation
# ---------------------------------------------------------------------------

from run_agent import build_stuck_warning


def test_stuck_warning_empty_under_threshold():
    assert build_stuck_warning(subgoal="X", consec_fails=0) == ""
    assert build_stuck_warning(subgoal="X", consec_fails=2) == ""


def test_stuck_warning_at_threshold():
    out = build_stuck_warning(subgoal="切换 tab", consec_fails=3)
    assert "切换 tab" in out
    assert "3" in out
    # must instruct the VLM to switch sub-goal or done
    assert "sub-goal" in out.lower() or "subgoal" in out.lower()


def test_stuck_warning_above_threshold():
    out = build_stuck_warning(subgoal="X", consec_fails=5)
    assert "5" in out
```

- [ ] **Step 2: run, expect ImportError**

- [ ] **Step 3: implement `build_stuck_warning`**

Add IMMEDIATELY BELOW `update_subgoal_failure_counter`:

```python
def build_stuck_warning(subgoal: str, consec_fails: int) -> str:
    """Return a non-empty warning to splice into the next-step prompt
    when the VLM is grinding on the same sub-goal."""
    if consec_fails < 3:
        return ""
    return (
        f"\n⚠ sub-goal {subgoal!r} 已连续 {consec_fails} 步失败。\n"
        f"必须换一个 sub-goal 描述，或考虑 done（如目标已完成或无法达成）。\n"
    )
```

- [ ] **Step 4: run, expect 12 PASSED**

```bash
/Users/liuzhixiong/coding-project/cursor-pointer/python-client/.venv/bin/pytest tests/test_planner.py -v
```

Expected: 12 PASSED (5+4+3).

- [ ] **Step 5: regression**

```bash
/Users/liuzhixiong/coding-project/cursor-pointer/python-client/.venv/bin/pytest tests/ -v
```

Expected: 50 PASSED.

- [ ] **Step 6: commit**

```bash
cd /Users/liuzhixiong/coding-project/cursor-pointer
git add python-client/tools/run_agent.py python-client/tests/test_planner.py
git commit -m "feat(agent): add build_stuck_warning helper (TDD)"
```

---

## Task 4: wire planner into main loop

**Files:**
- Modify: `python-client/tools/run_agent.py` (main loop integration)

This is the actual behavior change. No new tests — the helpers in Tasks 1-3 are already covered.

- [ ] **Step 1: ensure `main()` initializes new state**

In `python-client/tools/run_agent.py`, find the line `history.clear()` inside `main()` (added during the verb-expansion work). Add immediately AFTER it:

```python
    global current_subgoal, consec_subgoal_fails
    current_subgoal = ""
    consec_subgoal_fails = 0
```

- [ ] **Step 2: parse the VLM output into (subgoal, action)**

Find the existing line:
```python
        action = raw.strip().splitlines()[0].strip() if raw.strip() else ""
        # If MiniMax wrapped action in markdown / quotes, strip.
        action = action.strip("`*\" ").lstrip("➜→- ")
```

Replace those three lines (and the `_log(f"  MiniMax (...): {action!r}")` line that follows them) with:

```python
        subgoal, action_raw = parse_action_with_subgoal(raw)
        # Preserve the existing markdown / quote / arrow cleanup.
        action = action_raw.strip("`*\" ").lstrip("➜→- ")
        _log(f"  → subgoal: {subgoal!r}")
        _log(f"  MiniMax ({time.time()-t0:.1f}s): {action!r}")

        # Failure-counter accounting happens AFTER execute() returns.
        prev_subgoal_for_counter = current_subgoal
```

- [ ] **Step 3: update counter after each step**

Find the existing main-loop region right after `execute()` finishes and result is recorded into history. Currently looks something like:

```python
        result = execute(action, boxes)
        ...
        if result is None:
            history.append(f"step {step}: {action}")
        else:
            history.append(f"step {step}: FAILED {action} ({result})")
```

Replace both `history.append` calls with the new shape, and add counter accounting + the global rebinding. The block becomes:

```python
        result = execute(action, boxes)
        ...
        step_failed = result is not None
        consec_subgoal_fails = update_subgoal_failure_counter(
            prev_count=consec_subgoal_fails,
            prev_subgoal=prev_subgoal_for_counter,
            new_subgoal=subgoal,
            step_failed=step_failed,
        )
        current_subgoal = subgoal
        outcome = "ok" if not step_failed else f"fail: {result}"
        history.append(f"step {step}: [{subgoal}] {action} ({outcome})")
        if consec_subgoal_fails >= 3:
            _log(f"  ⚠ stuck: subgoal {subgoal!r} failed {consec_subgoal_fails} consecutive steps")
```

NOTE: search the actual current history.append patterns first; there may be multiple branches (CRASHED, FAILED, success). Apply the same `[subgoal]` prefix consistently to every history-append branch you find inside the main loop. Use the existing `result` / `step_failed` logic as the source-of-truth.

- [ ] **Step 4: splice the stuck warning into the next-step prompt**

Find the prompt-build section (around where the existing `banned_xy` warning is appended — search for `len(banned_xy)`). Add IMMEDIATELY BEFORE the existing final-line prompt rule (`"只输出一行动作:"` or similar — search for `只输出`):

```python
        prompt += build_stuck_warning(current_subgoal, consec_subgoal_fails)
```

This MUST come BEFORE the "请优先按标签..." rule line so the warning is sandwiched between the history block and the closing instructions.

ALSO: change the final-line instruction from `只输出一行动作:` to `按格式输出两行（subgoal: ... 然后 action: ...）:`. This signals to the VLM that two lines are required.

- [ ] **Step 5: update SYSTEM_PROMPT**

In `python-client/tools/run_agent.py`, find the `SYSTEM_PROMPT = textwrap.dedent("""\` block. Add this paragraph BEFORE the existing `给你一个目标，你每一步从下面挑一个动作输出，**只输出一行**：` paragraph, replacing that line with new format guidance. The new section reads:

```
    给你一个目标，你每一步必须输出两行：
        subgoal: <一句话描述你这一步想完成的子目标>
        action: <click 5 | scroll down | clipboard write "..." | done ...>

    sub-goal 可以跨步保持不变（推进同一目标），也可以每步换（切换思路）。
    若 prompt 提示 "sub-goal 连续 N 步失败"，必须换 sub-goal 描述，否则系统会判定卡死并退出。
```

- [ ] **Step 6: syntax-check + run regression suite**

```bash
/Users/liuzhixiong/coding-project/cursor-pointer/python-client/.venv/bin/python -c "import ast; ast.parse(open('/Users/liuzhixiong/coding-project/cursor-pointer/python-client/tools/run_agent.py').read())"
/Users/liuzhixiong/coding-project/cursor-pointer/python-client/.venv/bin/pytest python-client/tests/ -v
```

Expected: clean parse, 50 PASSED.

- [ ] **Step 7: commit**

```bash
cd /Users/liuzhixiong/coding-project/cursor-pointer
git add python-client/tools/run_agent.py
git commit -m "feat(agent): wire planner — sub-goal in prompt/history + stuck warning"
```

---

## Task 5: live E2E with multi-step task

**Files:** none modified. Pure verification.

Goal: confirm sub-goals show up in history and the stuck warning fires when MiniMax repeats failures.

- [ ] **Step 1: confirm baseline**

```bash
curl -s --max-time 2 http://127.0.0.1:39213/health
osascript -e 'tell application "NeteaseMusic" to activate' && sleep 1 && osascript -e 'tell application "NeteaseMusic" to activate'
```

- [ ] **Step 2: run a deliberately multi-step task**

```bash
cd /Users/liuzhixiong/coding-project/cursor-pointer/python-client
source /Users/liuzhixiong/coding-project/cursor-pointer/python-client/.venv/bin/activate
env -u CURSOR_POINTER_NO_OVERLAY python tools/run_agent.py \
  "在网易云左侧切换到「漫游」tab 然后把当前播放的歌名复制到剪贴板" \
  --max-steps 10 2>&1 | tee /tmp/run_planner_e2e.log
```

This task has TWO clear sub-goals: (a) switch to 漫游 tab, (b) copy song name. Expected behavior: each step's log shows `→ subgoal: ...` and history entries start with `[<subgoal>]`.

- [ ] **Step 3: confirm sub-goal markers in log**

```bash
grep -E "subgoal:|stuck:|\[.*\] " /tmp/run_planner_e2e.log | head -30
```

Expected: at least 2 distinct sub-goal strings (or 2 stable strings if the VLM stuck with one phrasing). Look for evolution like `→ subgoal: '切换到漫游 tab'` early, `→ subgoal: '复制歌名'` later.

- [ ] **Step 4: outcomes**

ACCEPTABLE:
- A) Both sub-goals appear in log AND verify_done returned `ok` → full multi-step success.
- B) Both sub-goals appear AND stuck warning fired at least once (means the detector works on real failures) → partial success but feature proven.
- C) Only one sub-goal text used the whole run (VLM didn't update it) but log still shows the field → format works, agent didn't need to abort.

UNACCEPTABLE:
- D) Log shows no `→ subgoal:` line at all → integration didn't fire.
- E) `(unspecified)` appears in EVERY entry → VLM ignored the new format; need prompt rework.
- F) Agent crashed before completing a step.

- [ ] **Step 5: archive evidence**

If outcome A/B/C:

```bash
cd /Users/liuzhixiong/coding-project/cursor-pointer
mkdir -p docs/superpowers/evidence
cp /tmp/run_planner_e2e.log docs/superpowers/evidence/2026-05-17-planner-e2e.log
git add docs/superpowers/evidence/2026-05-17-planner-e2e.log
git commit -m "evidence: planner e2e log — sub-goals tracked across multi-step task"
```

---

## Self-Review Notes

- **Spec coverage:** parse → Task 1. State + counter → Task 2. Stuck warning → Task 3. Main-loop integration + SYSTEM_PROMPT → Task 4. E2E → Task 5. Roll-back gate (env var) is deferred — re-add if Task 5 shows VLM destabilization.
- **Placeholder scan:** all steps have exact code or exact commands; no TBDs.
- **Type consistency:** `parse_action_with_subgoal -> tuple[str, str]` everywhere; `update_subgoal_failure_counter` returns int; `build_stuck_warning` returns str.
- **YAGNI ruthless:** no separate planner LLM call, no sub-goal verification, no `subgoal: ABORT` explicit syntax.
- **Roll-back:** every commit is atomic; reverting Task 4 alone leaves the helpers defined-but-unused and harmless.
