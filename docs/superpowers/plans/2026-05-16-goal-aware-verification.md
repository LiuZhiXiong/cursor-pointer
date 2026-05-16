# Goal-Aware Verification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a reviewer pass to the agent so `done` claims are re-grounded against a fresh screenshot + AX state — kills the VLM-hallucinated success class of failures.

**Architecture:** One new module-level function `verify_done(goal, done_reason, target_pid, ask_minimax)` in `python-client/tools/run_agent.py` that re-screenshots, re-walks AX, builds a reviewer prompt, calls `ask_minimax`, and parses the verdict. Integrated into the main loop at the existing `result == "DONE"` branch. Pure addition, no refactoring of unrelated code.

**Tech Stack:** Python 3.13, existing MiniMax CLI (`mmx`), existing PyObjC + PIL stack, pytest (new dependency, only for tests).

**Spec:** [`docs/superpowers/specs/2026-05-16-goal-aware-verification-design.md`](../specs/2026-05-16-goal-aware-verification-design.md)

---

## Task 1: bootstrap test infrastructure

**Files:**
- Create: `python-client/tests/__init__.py` (empty)
- Create: `python-client/tests/conftest.py`
- Create: `python-client/pyproject.toml`
- Modify: `python-client/.venv` (install pytest)

This is a one-time setup because `python-client/` has no tests yet. We
add a minimal `pyproject.toml` so `pytest` discovers `tests/` and so
`tools/run_agent.py` can be imported as a module via the path-insert
pattern already used inside the file.

- [ ] **Step 1: install pytest into the existing venv**

Run:
```bash
/Users/liuzhixiong/coding-project/cursor-pointer/python-client/.venv/bin/pip install pytest
```

Expected: `Successfully installed pytest-<ver>` + transitive deps.

- [ ] **Step 2: create `python-client/pyproject.toml`**

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
python_files = ["test_*.py"]
python_classes = ["Test*"]
python_functions = ["test_*"]
addopts = "-ra -q"
```

- [ ] **Step 3: create empty `python-client/tests/__init__.py`**

```python
```

(One blank line, no content. Makes `tests/` a package so conftest
fixtures are picked up.)

- [ ] **Step 4: create `python-client/tests/conftest.py`**

```python
"""Shared test fixtures.

`tools/` is a sibling of `tests/` — adopt the same path-insert pattern
the production code uses so test files can `from tools.run_agent import …`.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Make `tools/` importable as a package root.
ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))
```

- [ ] **Step 5: smoke-test that pytest finds the tests dir**

Run:
```bash
cd /Users/liuzhixiong/coding-project/cursor-pointer/python-client
.venv/bin/pytest --collect-only
```

Expected: `no tests ran in <time>` (zero tests collected, exit code 5
is acceptable). Important — no errors about missing `tools` import.

- [ ] **Step 6: commit**

```bash
cd /Users/liuzhixiong/coding-project/cursor-pointer
git add python-client/pyproject.toml python-client/tests/__init__.py python-client/tests/conftest.py
git commit -m "test: bootstrap pytest infrastructure for python-client"
```

---

## Task 2: define `REVIEW_PROMPT` constant + `parse_verdict` (TDD)

**Files:**
- Create: `python-client/tests/test_verify_done.py`
- Modify: `python-client/tools/run_agent.py` (add `REVIEW_PROMPT` and `parse_verdict`)

The parser is pure logic — no I/O, no MiniMax, no screen capture. TDD
this part first; verifier function builds on top of it in Task 3.

- [ ] **Step 1: write the failing parser tests**

Create `python-client/tests/test_verify_done.py`:

```python
"""Tests for verify_done helper logic in run_agent.py."""
from __future__ import annotations

from run_agent import parse_verdict


def test_parse_verdict_ok():
    raw = """verdict: ok
why: 网易云左侧栏「漫游」已高亮"""
    verdict, why = parse_verdict(raw)
    assert verdict == "ok"
    assert "漫游" in why


def test_parse_verdict_reject():
    raw = """verdict: reject
why: 当前仍在推荐页，左栏「漫游」未高亮"""
    verdict, why = parse_verdict(raw)
    assert verdict == "reject"
    assert "推荐" in why


def test_parse_verdict_garbage_defaults_reject():
    """If the reviewer output is unparseable, default to reject (fail-safe)."""
    for raw in ["", "???", "ok cool", "yes"]:
        verdict, _ = parse_verdict(raw)
        assert verdict == "reject", f"garbage {raw!r} should be reject"


def test_parse_verdict_case_insensitive():
    raw = """VERDICT: OK
WHY: looks good"""
    verdict, _ = parse_verdict(raw)
    assert verdict == "ok"


def test_parse_verdict_extra_whitespace():
    raw = "  verdict:   ok  \n  why:   yep  "
    verdict, why = parse_verdict(raw)
    assert verdict == "ok"
    assert why == "yep"
```

- [ ] **Step 2: run the tests — expect ImportError / NameError**

Run:
```bash
cd /Users/liuzhixiong/coding-project/cursor-pointer/python-client
.venv/bin/pytest tests/test_verify_done.py -v
```

Expected: ImportError on `from run_agent import parse_verdict` because
`parse_verdict` doesn't exist yet.

- [ ] **Step 3: implement `REVIEW_PROMPT` and `parse_verdict` in `run_agent.py`**

Find the existing `ACTION_RE = re.compile(...)` block in
`python-client/tools/run_agent.py` (around line 667). Insert these two
items **immediately above** it so they're module-level and importable
without triggering side effects:

```python
# ---------------------------------------------------------------------------
# Goal-aware verification (review the worker VLM's `done` claim)
# ---------------------------------------------------------------------------

REVIEW_PROMPT = """你是一个验收员。Agent 刚才报告任务完成，你要核实。

原始目标：{goal}
Agent 的完成理由：{done_reason}

当前屏幕（图）和可交互元素清单：
{elements}

判断：当前屏幕状态是否真正达成原始目标？

输出格式（严格两行）：
verdict: ok | reject
why: <一句话>
"""


def parse_verdict(raw: str) -> tuple[str, str]:
    """Parse the reviewer VLM's two-line response.

    Default-to-reject on any ambiguity — fail-safe against hallucinated
    `verdict: ok` lines from a confused reviewer.
    """
    verdict = "reject"
    why = (raw or "").strip()[:120]
    for line in (raw or "").splitlines():
        stripped = line.strip()
        lower = stripped.lower()
        if lower.startswith("verdict:"):
            value = stripped.split(":", 1)[1].strip().lower()
            if value.startswith("ok"):
                verdict = "ok"
            elif value.startswith("reject"):
                verdict = "reject"
        elif lower.startswith("why:"):
            why = stripped.split(":", 1)[1].strip()[:200]
    return verdict, why
```

- [ ] **Step 4: run the parser tests — expect all green**

Run:
```bash
cd /Users/liuzhixiong/coding-project/cursor-pointer/python-client
.venv/bin/pytest tests/test_verify_done.py -v
```

Expected:
```
test_parse_verdict_ok PASSED
test_parse_verdict_reject PASSED
test_parse_verdict_garbage_defaults_reject PASSED
test_parse_verdict_case_insensitive PASSED
test_parse_verdict_extra_whitespace PASSED
```

- [ ] **Step 5: commit**

```bash
cd /Users/liuzhixiong/coding-project/cursor-pointer
git add python-client/tools/run_agent.py python-client/tests/test_verify_done.py
git commit -m "feat(agent): add REVIEW_PROMPT + parse_verdict (TDD)"
```

---

## Task 3: implement `verify_done` (TDD)

**Files:**
- Modify: `python-client/tests/test_verify_done.py` (append new tests)
- Modify: `python-client/tools/run_agent.py` (add `verify_done` function)

`verify_done` orchestrates: fresh screenshot → fresh AX walk →
annotate → reviewer call → parse. Stub all I/O in tests so they run
fast and offline.

- [ ] **Step 1: append failing verifier tests**

Append to `python-client/tests/test_verify_done.py`:

```python
# -----------------------------------------------------------------------
# verify_done — orchestration tests (all I/O stubbed)
# -----------------------------------------------------------------------

from pathlib import Path
from unittest.mock import patch


def _stub_pipeline():
    """Patch the four I/O dependencies of verify_done.

    Returns the patchers (already started). Caller must stop them.
    """
    p_shot = patch("run_agent.trigger_system_screenshot",
                   return_value=Path("/tmp/fake_shot.png"))
    p_detect = patch("run_agent.detect_elements", return_value=[
        {"id": 1, "x": 100, "y": 200, "w": 30, "h": 20,
         "role": "StaticText", "label": "漫游",
         "parent_label": "", "parent_bbox": None,
         "ax_ref": None, "parent_ax_ref": None},
    ])
    p_monitors = patch("run_agent.requests.get")
    p_annotate = patch("run_agent.annotate",
                       return_value=Path("/tmp/fake_shot.review.png"))
    for p in (p_shot, p_detect, p_monitors, p_annotate):
        p.start()
    # Make the GET /screen/monitors call return a sane scale.
    p_monitors_started = p_monitors  # alias
    p_monitors_started.return_value.json.return_value = [{"scale_factor": 2.0}]
    return [p_shot, p_detect, p_monitors, p_annotate]


def _stop_patchers(patchers):
    for p in patchers:
        p.stop()


def test_verify_done_ok():
    from run_agent import verify_done
    patchers = _stub_pipeline()
    try:
        def fake_minimax(_img, _prompt):
            return "verdict: ok\nwhy: 漫游 tab 已激活"
        verdict, why = verify_done(
            goal="切到漫游 tab",
            done_reason="已经切到漫游",
            target_pid=1234,
            ask_minimax=fake_minimax,
        )
        assert verdict == "ok"
        assert "漫游" in why
    finally:
        _stop_patchers(patchers)


def test_verify_done_reject_when_reviewer_says_no():
    from run_agent import verify_done
    patchers = _stub_pipeline()
    try:
        def fake_minimax(_img, _prompt):
            return "verdict: reject\nwhy: 仍在推荐页"
        verdict, why = verify_done(
            goal="切到漫游 tab",
            done_reason="看到漫游",
            target_pid=1234,
            ask_minimax=fake_minimax,
        )
        assert verdict == "reject"
        assert "推荐" in why
    finally:
        _stop_patchers(patchers)


def test_verify_done_reject_on_minimax_exception():
    """If ask_minimax raises, treat as reject (fail-safe)."""
    from run_agent import verify_done
    patchers = _stub_pipeline()
    try:
        def boom(_img, _prompt):
            raise RuntimeError("mmx exploded")
        verdict, why = verify_done(
            goal="x",
            done_reason="x",
            target_pid=1234,
            ask_minimax=boom,
        )
        assert verdict == "reject"
        assert "mmx" in why or "exception" in why.lower()
    finally:
        _stop_patchers(patchers)


def test_verify_done_prompt_includes_goal_and_reason(monkeypatch):
    """Verify the goal and done_reason are interpolated into the prompt
    the reviewer sees — that's the whole grounding mechanism."""
    from run_agent import verify_done
    patchers = _stub_pipeline()
    captured = {}
    try:
        def capture(_img, prompt):
            captured["prompt"] = prompt
            return "verdict: ok\nwhy: ok"
        verify_done(
            goal="切到「漫游」tab",
            done_reason="左栏漫游已高亮",
            target_pid=1234,
            ask_minimax=capture,
        )
        assert "切到「漫游」tab" in captured["prompt"]
        assert "左栏漫游已高亮" in captured["prompt"]
    finally:
        _stop_patchers(patchers)
```

- [ ] **Step 2: run new tests — expect ImportError**

Run:
```bash
cd /Users/liuzhixiong/coding-project/cursor-pointer/python-client
.venv/bin/pytest tests/test_verify_done.py -v
```

Expected: previous 5 still pass; 4 new fail with `cannot import name 'verify_done'`.

- [ ] **Step 3: implement `verify_done` in `run_agent.py`**

Insert this **immediately below** `parse_verdict` (so it can call into
the already-imported helpers `trigger_system_screenshot`,
`detect_elements`, `annotate`):

```python
def verify_done(goal: str, done_reason: str, target_pid: int,
                ask_minimax) -> tuple[str, str]:
    """Re-ground a `done` claim against fresh screen state.

    Returns ("ok", why) only if the reviewer VLM confirms the goal is
    truly achieved. Any failure (screenshot timeout, mmx crash, garbage
    output) returns ("reject", why) — fail-safe.
    """
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).parent))
    from run_ocr import trigger_system_screenshot as _trigger  # type: ignore

    try:
        png = _trigger()
    except Exception as e:
        return "reject", f"screenshot failed: {e}"

    try:
        boxes = detect_elements(target_pid)
    except Exception as e:
        return "reject", f"element detection failed: {e}"

    try:
        mons = requests.get(f"{API}/screen/monitors", timeout=3).json()
        scale = float(mons[0]["scale_factor"] or 2.0)
    except Exception:
        scale = 2.0

    try:
        annotated = annotate(png, boxes, scale=scale)
    except Exception as e:
        return "reject", f"annotation failed: {e}"

    # Element summary for the reviewer — same shape the worker sees.
    elem_lines = []
    for b in boxes[:60]:
        parent_part = f"  ⊂ {b['parent_label']}" if b.get("parent_label") else ""
        elem_lines.append(
            f"  #{b['id']:>3}  {b['role']:14}  '{b['label']}'  ({b['w']}x{b['h']}){parent_part}"
        )
    elements_block = "\n".join(elem_lines) if elem_lines else "(none)"

    prompt = REVIEW_PROMPT.format(
        goal=goal,
        done_reason=done_reason or "(未提供)",
        elements=elements_block,
    )

    try:
        raw = ask_minimax(annotated, prompt)
    except Exception as e:
        return "reject", f"reviewer exception: {e}"

    return parse_verdict(raw)
```

Note: `trigger_system_screenshot` is imported lazily inside the function
to mirror the existing pattern at `run_agent.py:309`/`372`/`909` and
avoid cyclic-import worries during test stubbing. Tests stub
`run_agent.trigger_system_screenshot` — make that import work by also
adding a module-level alias at the top of `run_agent.py`:

In `run_agent.py`, find the existing block of imports near the top
(after `import requests`). Add:

```python
# Eager-imported alias so tests can patch `run_agent.trigger_system_screenshot`
# without having to dig into run_ocr.
try:
    sys.path.insert(0, str(Path(__file__).parent))
    from run_ocr import trigger_system_screenshot  # type: ignore  # noqa: E402
except Exception:
    trigger_system_screenshot = None  # type: ignore
```

…and adjust `verify_done` to use the alias if present:

```python
def verify_done(goal: str, done_reason: str, target_pid: int,
                ask_minimax) -> tuple[str, str]:
    try:
        if trigger_system_screenshot is None:
            raise RuntimeError("trigger_system_screenshot unavailable")
        png = trigger_system_screenshot()
    except Exception as e:
        return "reject", f"screenshot failed: {e}"
    # (rest unchanged — drop the local import)
```

- [ ] **Step 4: run all tests — expect 9 green**

Run:
```bash
cd /Users/liuzhixiong/coding-project/cursor-pointer/python-client
.venv/bin/pytest tests/test_verify_done.py -v
```

Expected: 9 passed.

- [ ] **Step 5: commit**

```bash
cd /Users/liuzhixiong/coding-project/cursor-pointer
git add python-client/tools/run_agent.py python-client/tests/test_verify_done.py
git commit -m "feat(agent): implement verify_done — VLM re-grounding"
```

---

## Task 4: wire `verify_done` into main loop

**Files:**
- Modify: `python-client/tools/run_agent.py:1048-1050` (the `if result == "DONE":` block)

This is the actual behavior change. Until this step, `verify_done`
exists but is never called.

- [ ] **Step 1: locate the existing DONE block**

In `python-client/tools/run_agent.py`, currently lines 1048-1050:

```python
        if result == "DONE":
            _log(f"\n✓ done: {action}  (total {time.time()-total_t0:.1f}s)")
            return 0
```

- [ ] **Step 2: replace with verified-DONE block**

Replace those three lines with:

```python
        if result == "DONE":
            done_reason = action[len("done"):].strip().lstrip(":：") if action.lower().startswith("done") else ""
            _log(f"  → reviewing done claim: '{done_reason}'")
            try:
                verdict, why = verify_done(
                    goal=goal,
                    done_reason=done_reason,
                    target_pid=initial_pid,
                    ask_minimax=ask_minimax,
                )
            except Exception as e:
                verdict, why = "reject", f"verifier crashed: {e}"
            _log(f"  → reviewer verdict={verdict} why='{why}'")
            if verdict == "ok":
                _log(f"\n✓ done verified: {action}  ({why})  "
                     f"(total {time.time()-total_t0:.1f}s)")
                return 0
            history.append(
                f"step {step}: rejected hallucinated done ({why})"
            )
            _log(f"  ⚠ done rejected — continuing main loop")
            continue
```

- [ ] **Step 3: syntax-check the file**

Run:
```bash
/Users/liuzhixiong/coding-project/cursor-pointer/python-client/.venv/bin/python -c "import ast; ast.parse(open('/Users/liuzhixiong/coding-project/cursor-pointer/python-client/tools/run_agent.py').read())"
```

Expected: no output (clean parse). Any output means syntax error.

- [ ] **Step 4: re-run all unit tests — still green**

Run:
```bash
cd /Users/liuzhixiong/coding-project/cursor-pointer/python-client
.venv/bin/pytest tests/test_verify_done.py -v
```

Expected: 9 passed.

- [ ] **Step 5: commit**

```bash
cd /Users/liuzhixiong/coding-project/cursor-pointer
git add python-client/tools/run_agent.py
git commit -m "feat(agent): wire verify_done into main loop — block hallucinated done"
```

---

## Task 5: end-to-end live test (NeteaseMusic)

**Files:**
- (No files modified — this validates the real binary path against the
  same NM target that surfaced the original bug.)

This is the verification-before-completion gate per
`superpowers:verification-before-completion`: prove the new code
actually catches a hallucinated `done` in production.

- [ ] **Step 1: prepare NM state**

NM should be in a state where the goal "切换到漫游 tab" is NOT yet
satisfied (e.g., on 推荐 page). If unsure, run:

```bash
osascript -e 'tell application "NeteaseMusic" to activate'
```

then visually confirm in the agent overlay or screenshot that NM is
not already on 漫游.

- [ ] **Step 2: re-run the original scroll task that hallucinated**

```bash
cd /Users/liuzhixiong/coding-project/cursor-pointer/python-client
source .venv/bin/activate
env -u CURSOR_POINTER_NO_OVERLAY python tools/run_agent.py \
  "向下滚动网易云首页，直到看到「热歌榜」或「主播电台」这类下方板块" \
  --max-steps 6 2>&1 | tee /tmp/full_run_verify.log
```

- [ ] **Step 3: look for the new log marker**

Check the log:

```bash
grep -E "reviewer verdict|rejected hallucinated" /tmp/full_run_verify.log
```

Expected: at least one `→ reviewer verdict=...` line. If the worker
hallucinated (as it did before), expect a `verdict=reject` followed
by `⚠ done rejected — continuing main loop`.

- [ ] **Step 4: end-state ground truth**

Run the same AX-label search that exposed the original bug:

```bash
cd /Users/liuzhixiong/coding-project/cursor-pointer/python-client
.venv/bin/python -c "
import sys
sys.path.insert(0, 'tools')
from run_som import collect
from Cocoa import NSWorkspace
nm = next(a for a in NSWorkspace.sharedWorkspace().runningApplications()
          if a.bundleIdentifier() == 'com.netease.163music')
els = collect(nm.processIdentifier(), n_passes=1)
for needle in ['热歌榜', '主播', '电台', '榜']:
    matches = [e for e in els if needle in (e.get('label') or '')]
    print(f'{needle!r}: {len(matches)} match')
"
```

Expected (both acceptable outcomes):
- Agent ran out of steps with verdict=reject events logged (bug prevented), OR
- Agent reached a state where ≥1 of `热歌榜 / 主播 / 电台 / 榜` actually appears in AX, and the reviewer said `verdict=ok`.

What MUST NOT happen: log shows `✓ done verified` but the AX search returns 0 matches for the claimed keywords. That would mean the verifier rubber-stamped a hallucination.

- [ ] **Step 5: commit the new test artifact (optional)**

If the log is illustrative, save it:

```bash
mkdir -p docs/superpowers/evidence
cp /tmp/full_run_verify.log docs/superpowers/evidence/2026-05-16-verify-done-e2e.log
git add docs/superpowers/evidence/2026-05-16-verify-done-e2e.log
git commit -m "evidence: e2e log proving verify_done catches scroll-test hallucination"
```

If the log shows nothing interesting (e.g., agent legit completed without
triggering review-reject), skip this commit.

---

## Self-Review Notes

- **Spec coverage:** every section in the spec maps to a task:
  - Architecture / `verify_done` body → Task 3
  - `REVIEW_PROMPT` + `parse_verdict` → Task 2
  - Main-loop integration → Task 4
  - Three pytest cases (happy, reject, garbage) → Task 2 + Task 3 (we have 9 covering the same surface area, exceeding the spec's three)
  - E2E live verification → Task 5
- **Placeholder scan:** no TBDs. Every step has either exact code or an exact command.
- **Type consistency:** `verify_done` signature is `(goal: str, done_reason: str, target_pid: int, ask_minimax) -> tuple[str, str]` everywhere. `parse_verdict` returns `(str, str)` everywhere.
- **Rollback path:** if Task 4 misbehaves in prod, revert that single commit; the previous commit leaves `verify_done` defined-but-uncalled and harmless.
