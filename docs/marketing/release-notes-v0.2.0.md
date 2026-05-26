# v0.2.0 — Your agent now knows when its clicks actually worked

The headline change: every action your agent takes through cursor-pointer now returns a **structured outcome** instead of a silent "I guess it worked." If a click missed, the target moved, or macOS revoked a permission mid-run, your agent finds out in the same step — not five steps later when the whole plan has gone sideways.

If you've spent an afternoon debugging "the agent insists it clicked Submit but the form is empty," this release is for you.

## What's new

### Closed-loop action contract

Every `click` and `type` now reports one of:

- `ok` — verified change on screen after the action
- `mismatch_target` — the element under the cursor at action time didn't match what your agent perceived (stale modal, UI shifted)
- `verify_failed` — the action executed but the expected change didn't happen
- `exec_error` — the OS rejected the action (permission, dead window, etc.)
- `permission_denied` — Accessibility or Screen Recording revoked; the loop halts cleanly with exit code 2 instead of looping on black frames

Each outcome also carries the **path taken** (`ax_press` or `pixel`) and **pixel drift** between perception and action. If a button responds to accessibility actions, cursor-pointer uses that path — which is the only reliable way to click many Electron apps (Slack, Discord, NeteaseMusic) that ignore synthetic mouse events.

### Declarative verb registry

Adding a new action used to mean editing the dispatcher, the prompt grammar, and the tests in three places. Now each verb is one file in `python-client/cursor_pointer/verbs/`. The agent's prompt grammar is auto-generated from the registry, so you can't ship a verb the agent doesn't know how to call (or vice versa).

Ships with: `click`, `dclick`, `rclick`, `type`, `key`, `drag`, `scroll`, `scroll_to`, `app`, `clipboard`, `shell`, `browser`, `wait`, `done`.

### Per-step structured log

`tools/run_agent.py` now prints one line per step:

```
[STEP 3] click 5  → status=ok path=ax_press drift=0px (12ms)
[STEP 4] click 7  → status=mismatch_target path=none — target signature did not match
```

Glanceable during a run, greppable after.

### `scripts/demo_recorder.py`

Wraps the agent and tees the per-step banner as a JSONL event stream — useful for OBS overlays, post-run analysis, or piping into your own dashboard. The agent itself is unchanged; the recorder parses existing stdout.

```bash
python scripts/demo_recorder.py --jsonl /tmp/run.jsonl "open TextEdit and type hello"
```

## Try it

```bash
git clone https://github.com/LiuZhiXiong/cursor-pointer.git
cd cursor-pointer
npm install && npm run dev          # grant Accessibility + Screen Recording

cd python-client
pip install -e ".[ocr]"
python tools/run_agent.py "open a new TextEdit document and type closed loop"
```

You'll see one `[STEP N]` line per action with `status=`, `path=`, and `drift=`. Toggle Screen Recording off mid-run and the loop halts with a clear `permission_denied` instead of spinning.

## Upgrade notes

- The Python SDK's `ActionExecutor.execute()` now returns an `Outcome` dataclass. Existing direct `cp.click(x, y)` / `cp.type_text(...)` calls are unchanged.
- If you wrote custom verbs against the old dispatcher, move them into `cursor_pointer/verbs/` — see `verbs/click.py` for the shape.

## Stats

173 tests, MIT-licensed, single-author. macOS only (Apple Silicon + Intel via universal build).

Full diff: `v0.1.0...v0.2.0`
Repo: https://github.com/LiuZhiXiong/cursor-pointer
