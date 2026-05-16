# Goal-aware verification — design

**Date:** 2026-05-16
**Author:** brainstorming session with @liuzhixiong
**Status:** approved → ready for implementation plan

## Problem

The agent declares `done <reason>` based purely on the worker VLM's
judgment. Today's NeteaseMusic scroll test produced:

```
MiniMax: 'done 我看到了"你的宝藏有声书"板块，包含"听过的有声书"、
        "中国通史 纪录片"、"毛选中的顶级思维智慧"等内容。'
✓ done: ...
```

…but AX search of the post-`done` state confirms **zero matches** for
`宝藏`, `有声书`, `中国通史`, `毛选`, `纪录片`. The VLM hallucinated
a successful outcome.

This pattern is the most dangerous failure mode for a fully-autonomous
agent: it ships false success, and every layer built on top of `done`
(retry logic, replay, downstream chained tasks) inherits the lie.

## Goal

Stop accepting `done` solely on the worker VLM's word. Add a single
review pass that re-grounds against fresh screen state.

## Non-goals

- Verifying every intermediate step (only `done` for now — cheap, focused)
- Switching VLM providers (worker and reviewer both stay on MiniMax)
- Decomposing goals into sub-goals or assertions (deferred to future work)
- Goal-language parsing (the goal stays free-text Chinese)

## Approach (chosen: A)

| | A — same-model review | B — stronger reviewer | C — algorithmic + VLM |
|---|---|---|---|
| Latency | +1 MiniMax call | +1 stronger call | mostly fast |
| Token cost | +1× per `done` | +2-5× per `done` | 0× when claim matches |
| New deps | none | new API key | none |
| Catch rate | medium | high | medium-high |
| Complexity | minimal | low | high |

A wins on YAGNI. Today's bug is the obvious-hallucination class; even a
same-model reviewer with a fresh screenshot should catch it because the
hallucinated labels are testably absent. Upgrade to B or C if A's
catch rate proves insufficient after real-world use.

## Architecture

```
main loop
  ↓
execute(action, boxes)
  ↓ returns "DONE"
verify_done(goal, done_reason, target_pid, ask_minimax)
  ├── trigger_system_screenshot()
  ├── detect_elements(target_pid)        # fresh AX walk
  ├── annotate(png, boxes, scale)
  ├── prompt = REVIEW_PROMPT.format(...)
  ├── raw = ask_minimax(annotated, prompt)
  └── return parse_verdict(raw)          # ("ok"|"reject", why)
  ↓
verdict == "ok"  → return 0 (real done)
verdict == "reject" → push history, continue main loop
```

The verifier is **stateless**: it does not read or mutate any of the
agent's main-loop variables. Inputs: `goal`, `done_reason`, target pid,
and the bound `ask_minimax` callable. Output: a `(verdict, why)` tuple.

## Components

### `verify_done(goal, done_reason, target_pid, ask_minimax)`

Single function in `run_agent.py`. Side effects: triggers a screenshot
via `⌘⇧3` and writes the annotated `.review.png` to Desktop.

### `REVIEW_PROMPT` (module-level constant)

```
你是一个验收员。Agent 刚才报告任务完成，你要核实。

原始目标：{goal}
Agent 的完成理由：{done_reason}

当前屏幕（图）和可交互元素清单：
{elements}

判断：当前屏幕状态是否真正达成原始目标？

输出格式（严格两行）：
verdict: ok | reject
why: <一句话>
```

### `parse_verdict(raw: str) -> (str, str)`

- Default `verdict="reject"`, `why=raw[:120]` if parsing fails.
- Case-insensitive line scan for `verdict:` and `why:`.
- `verdict` normalized to `"ok"` if value starts with `ok`, else `"reject"`.

Rationale for default-reject: a hallucinating VLM producing garbage on
the review prompt should NOT be silently accepted as `ok`.

## Main-loop integration

In `run_agent.py:main`, replace the existing:

```python
if result == "DONE":
    _log(f"\n✓ done: {action}  (total {time.time()-total_t0:.1f}s)")
    return 0
```

with:

```python
if result == "DONE":
    done_reason = action.removeprefix("done").strip()
    verdict, why = verify_done(
        goal, done_reason, initial_pid, ask_minimax
    )
    _log(f"  → reviewer verdict={verdict} why='{why}'")
    if verdict == "ok":
        _log(f"\n✓ done verified: {action} ({why})  (total {time.time()-total_t0:.1f}s)")
        return 0
    history.append(f"step {step}: rejected hallucinated done ({why})")
    _log(f"  ⚠ done rejected — continuing main loop")
    continue
```

`history` already feeds the next-step prompt, so the worker VLM sees
the rejection and avoids repeating the same false claim.

## Data flow

- **Inputs to verifier:** goal (str), done_reason (str), pid (int)
- **Inputs to reviewer VLM:** annotated `.review.png` (PIL Image) + prompt
- **Outputs:** `("ok" | "reject", why: str)`

No persistent state. Each `done` triggers an independent review.

## Error handling

| Failure | Handling |
|---|---|
| screenshot times out | treat as `reject` + `why="screenshot failed"` — same as if VLM disagreed |
| AX walk returns 0 elements | continue with empty `{elements}` block — reviewer can still judge from image |
| ask_minimax raises | treat as `reject`, log the exception |
| parser can't find `verdict:` | default `reject` |

No partial states leak out — verifier always returns a valid tuple or
raises (and the caller catches with the existing per-step `try/except`).

## Testing

Three pytest cases in `python-client/tests/test_verify_done.py`:

1. **happy path** — patch `ask_minimax` to return
   ```
   verdict: ok
   why: 网易云左侧栏「漫游」已高亮
   ```
   Assert `verdict == "ok"`.

2. **rejection** — patch to return
   ```
   verdict: reject
   why: 当前仍在推荐页，左栏「漫游」未高亮
   ```
   Assert `verdict == "reject"` and `why` matches.

3. **garbage tolerance** — patch to return `"???"` or empty string;
   assert default `verdict == "reject"`.

Tests stub `trigger_system_screenshot`, `detect_elements`, `annotate`
with no-ops so they run without cursor-pointer or NM.

## Observability

- New log line per `done`: `→ reviewer verdict={verdict} why='{why}'`
- `.review.png` artifacts stay on Desktop alongside `.agent.png`
- Rejection events grep-able via `grep "rejected hallucinated done" /tmp/agent_*.log`

## Scope

- **In:** `run_agent.py` (~70 lines new code), one `REVIEW_PROMPT`
  constant, three pytest cases.
- **Out:** no changes to `run_som.py`, `run_ax.py`, cursor-pointer
  binary, or any other tooling. No new dependencies.

## Roll-back

The integration is a single block. If the reviewer turns out to be
overly strict and blocks legitimate `done`s, gate the call behind an
env var `CURSOR_POINTER_VERIFY=1` (default off during initial bake-in).
Promote to default-on after a real-world streak of correct verdicts.

## Open questions (deferred)

- Should `wait`, `key`, `type` also trigger review? — No for now. Only `done`.
- Cost of reviewer at scale (each `done` = +1 VLM call). — Acceptable
  given today's ≤ 10 step task lengths; revisit if tasks grow.
- Should `done_reason` be required (currently optional in ACTION_RE)?
  — Keep optional; reviewer can judge with just `goal + screen`.
