# v0.2.0 — Your agent now knows when its clicks actually worked

Every click and keystroke through cursor-pointer now returns a structured outcome — so when your agent's plan is going sideways, you find out on step 3, not step 8.

```bash
python tools/run_agent.py "open a new TextEdit document and type closed loop"
# [STEP 3] click 5 → status=ok path=ax_press drift=0px (12ms)
```

[Download cursor-pointer-0.2.0.dmg](#assets) · or jump to [Build from source](#-try-it-in-30-seconds)

---

## 🎯 What's new

### 🆕 Closed-loop action contract
Every `click` / `type` returns one of: `ok`, `mismatch_target`, `verify_failed`, `exec_error`, `permission_denied`. Each outcome carries the path taken (`ax_press` or `pixel`) and pixel drift between perception and action. No more "I guess it worked."

### 🆕 AX-press path for Electron apps
If a button responds to accessibility actions, cursor-pointer uses that path — the only reliable way to click Slack, Discord, and other Electron apps that ignore synthetic mouse events.

### 🆕 Declarative verb registry
One file per verb in `python-client/cursor_pointer/verbs/`. The agent's prompt grammar is auto-generated from the registry, so you can't ship a verb the agent doesn't know how to call. Ships with 14 verbs: `click`, `dclick`, `rclick`, `type`, `key`, `drag`, `scroll`, `scroll_to`, `app`, `clipboard`, `shell`, `browser`, `wait`, `done`.

### 🔧 Per-step structured log
`tools/run_agent.py` now prints one line per step — glanceable during a run, greppable after.

### 🔧 `scripts/demo_recorder.py`
Tees the per-step banner as a JSONL event stream. Useful for OBS overlays, post-run analysis, or your own dashboard.

---

## 🚀 Try it in 30 seconds

```bash
# ~10s — clone
git clone https://github.com/LiuZhiXiong/cursor-pointer.git
cd cursor-pointer

# ~1 min — Tauri dev shell (grant Accessibility + Screen Recording on first launch)
npm install && npm run dev

# 5-10 min on first run — Rust compile + Python deps
cd python-client
pip install -e ".[ocr]"

# ~5s per agent step
python tools/run_agent.py "open a new TextEdit document and type closed loop"
```

Toggle Screen Recording off mid-run — the loop halts with a clear `permission_denied` instead of spinning on black frames.

---

<details>
<summary><b>Upgrade notes</b></summary>

- `ActionExecutor.execute()` now returns an `Outcome` dataclass. Direct `cp.click(x, y)` / `cp.type_text(...)` calls are unchanged.
- Custom verbs written against the old dispatcher need to move into `cursor_pointer/verbs/` — see `verbs/click.py` for the shape.
- No config file changes. No new env vars.

</details>

<details>
<summary><b>Breaking changes</b></summary>

One: `ActionExecutor.execute()` return type changed from `bool` to `Outcome`. If you only used the high-level agent loop or the `cp.*` helpers, you're unaffected.

</details>

<details>
<summary><b>Full commit list</b></summary>

See the compare view: [`v0.1.0...v0.2.0`](https://github.com/LiuZhiXiong/cursor-pointer/compare/v0.1.0...v0.2.0)

</details>

---

## What's next

Validating willingness to pay for a signed, notarized `.dmg` build. v0.3.0 direction depends on what that experiment surfaces — likely candidates are a Windows port spike or a hosted verify-loop telemetry endpoint, but nothing's committed yet.

If you'd pay for a signed build, [open an issue](https://github.com/LiuZhiXiong/cursor-pointer/issues/new) and say so — that's the highest-signal feedback I can get right now.

---

## Acknowledgements

Solo dev, MIT-licensed, macOS only (Apple Silicon + Intel universal). 173 tests passing. Built because I was tired of agents that lie about whether they clicked the button.

Questions or stuck on setup? [GitHub Discussions](https://github.com/LiuZhiXiong/cursor-pointer/discussions) is the fastest way to reach me.
