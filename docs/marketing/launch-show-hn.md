**Title:** Show HN: Cursor-pointer – closed-loop computer control for AI agents on macOS

**Body:**

I kept losing afternoons to the same bug: my agent would "click Submit" in a Slack-like Electron app, the synthetic mouse event would be silently ignored, and the agent would happily continue the next five steps as if the form had been submitted. Or a modal would dismiss itself between perceive-and-act, the click would land on whatever was underneath, and I'd be reading screenshots trying to figure out where the plan went off the rails.

Cursor-pointer is what I built to stop having that afternoon. It's a macOS daemon (Rust/Tauri) plus a Python SDK that gives every action a **structured outcome** — not "click sent" but "click verified against the focused element, took the ax_press path, 0px drift, 12ms."

What's actually different from rolling your own with pyautogui + a screenshot loop:

1. **AXPress first, pixel fallback.** Many Electron apps ignore synthetic CGEvents. cursor-pointer tries the accessibility action first (which Electron does respect) and falls back to a pixel click only if AX isn't available. The outcome tells you which path ran.
2. **Per-action verification.** After each click/type, it re-perceives and checks the expected change happened. Failure modes are explicit: `ok`, `mismatch_target`, `verify_failed`, `exec_error`, `permission_denied`.
3. **Permission revocation surfaces immediately.** Toggle Screen Recording off mid-run and the agent exits with code 2 instead of looping on black frames forever.

Minimal use:

```python
from cursor_pointer import CursorPointer
from cursor_pointer.executor import ActionExecutor, build_click_intent

cp = CursorPointer()
ex = ActionExecutor(cp=cp, screenshot_fn=lambda: cp.screenshot(),
                    ax_press_fn=..., focused_ax_fn=...)

intent = build_click_intent("click 5", element_id=5,
                            elements=detect(), screenshot_png=cp.screenshot())
outcome = ex.execute(intent)
print(outcome.status, outcome.used_path)
# → ok ax_press
# → mismatch_target none
```

Or run the bundled agent end-to-end:

```bash
python tools/run_agent.py "open a new TextEdit document and type closed loop"
```

macOS only right now (CGEvent + xcap + accessibility APIs). 173 tests. MIT.

Repo: https://github.com/LiuZhiXiong/cursor-pointer

Would love feedback from anyone building computer-use agents — especially on the verb registry shape and whether the outcome taxonomy maps to failure modes you've actually hit.
