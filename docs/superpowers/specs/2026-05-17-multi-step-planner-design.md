# Multi-step planner — design

**Date:** 2026-05-17
**Author:** brainstorming session with @liuzhixiong
**Status:** approved → ready for implementation plan

## Problem

The agent has no concept of "what part of the goal am I working on right now." Today's loop just shows the worker VLM the original goal + step history + screen; the VLM picks one action; the agent runs it. For long tasks this lottery breaks down:

- The VLM forgets what it was trying to do two steps ago when the screen changes.
- It rotates through the same misguided action without realizing it's stuck on the same sub-objective.
- The verify_done reviewer can only judge the entire goal, not whether mid-task progress is happening.

The fix is NOT a pre-baked plan tree (overengineered, brittle when the screen reveals surprises). The fix is to make sub-goal state **first-class** — visible in every prompt and in history, with an explicit stuck-detector.

## Goal

Add a `subgoal` field that the worker VLM updates every step, and an auto-abort signal when the same sub-goal fails three steps in a row. The agent's loop stays one-step-at-a-time; we just thread sub-goal context through it.

## Non-goals

- Pre-planning the whole goal upfront (rejected — too brittle).
- A separate planner LLM call before each step (latency cost, no proven benefit).
- Sub-goal verification per step (verify_done already runs on `done`; adding mid-task verification doubles cost without solving today's pain point).
- Changing the verb set or action grammar.

## Decisions (locked during brainstorming)

| Decision | Choice |
|---|---|
| Planning strategy | Fully dynamic; sub-goal can change every step. |
| Output format | Two-line VLM response: `subgoal: …` then `action: …`. |
| Abort trigger | Same sub-goal 3 consecutive failed steps → next prompt forces re-pick. |
| Sub-goal verification | Out of scope — keep verify_done on whole goal. |

## Architecture

```
main loop (per step)
  ↓
build_prompt(goal, history, current_subgoal, banned_xy, consec_fails)
    if consec_fails ≥ 3:
        prompt += stuck-warning for current_subgoal
  ↓
raw = ask_minimax(annotated, prompt)
  ↓
subgoal, action = parse_action_with_subgoal(raw)
  ↓
update current_subgoal + consec_fails accounting
  ↓
result = execute(action, boxes)
  ↓
record history entry: f"step N: [{subgoal}] {action} ({outcome})"
  ↓
... existing verify_done / escalation / etc.
```

`current_subgoal`, `consec_fails`, and `last_subgoal_seen` live as module-level state alongside `history` (Task 6 of the verb-expansion plan already established that pattern).

## Components

### `parse_action_with_subgoal(raw: str) -> tuple[str, str]`

Pure parser, no I/O.

- Splits `raw` into lines, finds the first line starting with `subgoal:` (case-insensitive) and the first starting with `action:`.
- Returns `(subgoal_text, action_line)`.
- If `subgoal:` is missing → `subgoal = "(unspecified)"`. We do NOT reject — getting an `action` is more important than getting a sub-goal label.
- If `action:` is missing → fall back to using the first non-blank line that looks like an action. The existing `ACTION_RE` then runs against that string as before.

### Module state additions (in `run_agent.py`)

```python
current_subgoal: str = ""
consec_subgoal_fails: int = 0
```

Both reset at the top of `main()` alongside `history.clear()`.

### Main-loop accounting

After `parse_action_with_subgoal(raw)`:

```python
if subgoal != current_subgoal:
    current_subgoal = subgoal
    consec_subgoal_fails = 0
```

After `execute()` returns:

```python
if result is None:
    # action ran without error string; treat as success
    consec_subgoal_fails = 0
else:
    consec_subgoal_fails += 1
```

(`result is None` is the existing success convention — see today's `execute()`.)

### Prompt augmentation

In the existing prompt-build section (where banned_xy already gets appended), add:

```python
if consec_subgoal_fails >= 3:
    prompt += (
        f"\n⚠ sub-goal {current_subgoal!r} 已连续 {consec_subgoal_fails} 步失败。"
        f"\n必须换一个 sub-goal 描述，或考虑 done（如果目标已完成或确实无法达成）。\n"
    )
```

### History format change

From:
```
step N: click 5
```
To:
```
step N: [切换到漫游 tab] click 5 (ok)
```

The `[subgoal]` prefix and `(ok|fail|error)` suffix let the next step's VLM scan history and notice repetition.

### SYSTEM_PROMPT additions

Insert after the verb listing, before the rules:

```
每一步必须输出两行：
  subgoal: <一句话描述你这一步想完成的子目标>
  action: <click 5 | scroll down | clipboard write "..." | done ...>

sub-goal 可以跨步保持不变（说明在推进同一目标），也可以每步换（说明在切换思路）。
若 prompt 提示 "sub-goal 连续 N 步失败"，必须换 sub-goal 描述。
```

## Data flow

- VLM input: goal + augmented history (with `[subgoal]` + outcome) + maybe stuck-warning
- VLM output: 2 lines (`subgoal:` / `action:`)
- Agent state: `current_subgoal`, `consec_subgoal_fails`
- Verify_done input: unchanged (still operates on original goal + done_reason)

## Interaction with verify_done

When `action == "done"`, verify_done still runs on the **original goal**, not the current sub-goal. Sub-goal is a worker-VLM concept; the reviewer judges the whole task. This keeps the two systems orthogonal.

## Error handling

| Failure | Handling |
|---|---|
| VLM omits `subgoal:` | sub-goal becomes `"(unspecified)"`; agent proceeds |
| VLM omits `action:` | fall back to first non-blank line; existing ACTION_RE handles or returns parse error |
| VLM outputs garbage on both | existing `result is None or "could not parse"` path triggers; counts as a sub-goal failure |
| consec_fails reaches max_steps | existing max-steps termination still applies; agent stops |

## Testing

`python-client/tests/test_planner.py` (new file):

| Test | Asserts |
|---|---|
| `test_parse_action_with_subgoal_two_lines` | standard `subgoal:\naction:` parsed correctly |
| `test_parse_action_with_subgoal_missing_subgoal` | missing `subgoal:` → returns `"(unspecified)"` |
| `test_parse_action_with_subgoal_missing_action` | missing `action:` → falls back to first non-blank line |
| `test_parse_action_with_subgoal_case_insensitive` | `SUBGOAL:` and `Action:` parsed |
| `test_parse_action_with_subgoal_extra_lines` | extra commentary lines tolerated, subgoal+action extracted |
| `test_subgoal_failure_counter_increments_on_fail` | helper-level state-machine test |
| `test_subgoal_failure_counter_resets_on_success` | success path resets counter |
| `test_subgoal_failure_counter_resets_on_subgoal_change` | switching sub-goal resets counter |
| `test_prompt_augments_with_stuck_warning_at_threshold` | helper that builds the stuck warning emits the expected string at consec_fails ≥ 3 |

All 9 tests run offline (no MiniMax / cursor-pointer calls).

## Observability

- `_log("→ subgoal: ...")` each step so the run log shows sub-goal evolution
- `_log("⚠ stuck: subgoal X failed 3 consecutive steps")` when warning triggers
- History entries grep-able by `[<subgoal>]` for post-mortem analysis

## Scope

| Layer | LOC |
|---|---|
| `parse_action_with_subgoal` helper | ~25 |
| Module state additions | ~5 |
| Main-loop integration | ~30 |
| Prompt augmentation helper | ~15 |
| SYSTEM_PROMPT additions | ~8 |
| Tests | ~150 |
| **Total** | **~230** |

No new dependencies. No new HTTP endpoints. No Rust changes.

## Roll-back

If the sub-goal field destabilizes VLM output (e.g., MiniMax refuses to obey the format), gate the new code behind `CURSOR_POINTER_PLANNER=1` (default off) for a soak period, then default-on after a streak of clean runs. Same env-var pattern as the verify_done rollout (commit 87bdddb).

## Open questions (deferred)

- Should `consec_fails` count ONLY hard errors or also "AX state unchanged"? — Count both as fail. That's the same convention `result is None` uses in `execute()`.
- Should sub-goal text be passed to `verify_done` for richer context? — No. Keep verify_done orthogonal; if it ever needs sub-goal, expose via history (already present).
- Multi-step planner naming the abort signal — should we let VLM emit `subgoal: ABORT` explicitly? — No. The 3-fail counter is automatic; explicit ABORT adds a parser-state surface for marginal value.
