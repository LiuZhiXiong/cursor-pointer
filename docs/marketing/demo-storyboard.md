# cursor-pointer — 90-second demo storyboard

**Audience:** AI agent developers shipping computer-use features who keep
losing days debugging "the click that silently failed."

**One-sentence pitch in the video:** *"Your agent thinks it clicked. Now it
knows whether it actually worked."*

**Target asset chain:** 90s screencap → Twitter/X launch post → GitHub
README hero gif (10-15s trimmed loop).

---

## Storyboard (90s)

| Time   | Visual                                                    | Audio / Caption                                                                                                  |
| ------ | --------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------- |
| 0:00–0:08  | Black screen, large text appears:<br>**"Your agent thinks it clicked.<br>Did it?"** | (silent) — let the question land                                                                                 |
| 0:08–0:25  | Split: LEFT pyautogui clicking "Submit" in an Electron app; RIGHT empty for now. Click visible, nothing happens. Cursor moves to next step anyway. | Subtitle: *"Most computer-use SDKs send a synthetic click and assume it worked. Electron apps often ignore those clicks. Your agent doesn't notice."* |
| 0:25–0:35  | Title card: **cursor-pointer** with subtitle *"The bridge that lets your AI actually use your Mac."* | 1-bar musical sting                                                                                              |
| 0:35–0:60  | Same scenario via cursor-pointer. RIGHT-side terminal overlay (driven by `demo_recorder.py` JSONL) shows the per-step banner as the agent runs:<br>`[STEP 3] click 5  → status=ok path=ax_press drift=0px (12ms)` | Subtitle: *"cursor-pointer's closed-loop action contract reports a STRUCTURED outcome per action. The click is verified against the focused element, not assumed."* |
| 0:60–0:78  | Trigger the unhappy path on purpose: hover over a stale modal, click the gone button. Overlay shows:<br>`[STEP 4] click 7  → status=mismatch_target path=none — target signature did not match`<br>The agent re-perceives and retries. | Subtitle: *"When the UI moves between perception and action, the agent sees it. No more 'walked 5 steps in the wrong direction.'"* |
| 0:78–0:85  | User goes to **System Settings → Privacy** and toggles Screen Recording off mid-run. Overlay surfaces:<br>`!! permission denied — halting loop: permission_denied: screen_recording` | Subtitle: *"Permission revocation surfaces immediately instead of looping on black screenshots."*                |
| 0:85–0:90  | End card: logo + `github.com/LiuZhiXiong/cursor-pointer` + small text "MIT-licensed, 173 tests, free to try." | (silent)                                                                                                          |

**Total runtime budget:** 90 seconds. If a section runs long, trim
0:08–0:25 first (the "what's broken today" framing) — most viewers
already know the pain.

---

## Recording checklist (pre-flight)

| ✅ before hitting record                                              | command / setting |
| -------------------------------------------------------------------- | ----------------- |
| cursor-pointer daemon running                                         | `npm run dev` |
| Accessibility + Screen Recording permissions granted for cursor-pointer | System Settings → Privacy |
| Demo target app open and at the right state                           | TextEdit New Document; Slack (or another Electron app for the "AXPress works where pixel fails" beat) |
| `demo_recorder.py` ready to stream JSONL                              | `python scripts/demo_recorder.py --jsonl /tmp/demo.jsonl "..."` |
| OBS scene: 2/3 screen capture + 1/3 terminal overlay                  | wire OBS Text Source to `tail -f /tmp/demo.jsonl` via `jq` formatter |
| Microphone OFF (we're using captions, no voiceover)                   | OBS audio mixer |
| Screen-recording test pass on Mac of choice                           | record 5s + replay to verify framerate |
| No notifications during recording                                     | Do Not Disturb ON, Slack quit, browsers without tabs that ping |
| Verify the 3 chosen demo paths work BEFORE recording                  | run each scenario once end-to-end; abort if any fails (QA gate) |

---

## QA pre-flight scenarios (must pass before recording)

Each scenario produces a known terminal banner that the storyboard
references. If the actual banner doesn't match, edit the storyboard, do
NOT fake the recording.

```
SCENARIO 1: TextEdit happy path
  $ python tools/run_agent.py "open a new TextEdit document and type closed loop"
  EXPECT in stdout:
    [STEP N] click <id>  → status=ok path=ax_press ...
    [STEP N+1] type "closed loop"  → status=ok path=none ...
    ✓ done verified

SCENARIO 2: Electron app AXPress beat
  Target: a button in an Electron app where synthetic clicks fail (Slack
  sidebar, NeteaseMusic player buttons, etc.). Pre-pick the button by
  running the agent once and noting which AX path responds.
  EXPECT:
    [STEP N] click <id>  → status=ok path=ax_press ...
  (specifically the path=ax_press fragment is the point of this beat)

SCENARIO 3: mismatch_target on stale UI
  Setup: open a dialog. Start the agent on a goal that targets a button
  inside the dialog. Manually dismiss the dialog ~1s before the agent
  would click.
  EXPECT:
    [STEP N] click <id>  → status=mismatch_target path=none — target signature did not match ...

SCENARIO 4: permission_denied surfacing
  Setup: start the agent on any goal. Mid-run, open System Settings →
  Privacy → Screen Recording, untoggle cursor-pointer.
  EXPECT:
    !! permission denied — halting loop: permission_denied: screen_recording
  Agent exits with code 2, NOT loops on a black frame.
```

---

## Twitter/X launch post (280-char draft)

```
Built a thing: cursor-pointer is a macOS daemon + Python SDK that gives
AI agents structured feedback on whether their clicks actually worked.

  • AXPress for Electron apps that ignore synthetic clicks
  • Per-action verify, no more silent failures
  • Permission revocation surfaces immediately

MIT • 173 tests • [link]
```

Char count target ≤ 280 for vanilla X; if Bluesky/LinkedIn cross-post,
the same copy works.

---

## Landing page outline (no design, copy structure)

Section headers + 1-2 sentence body each. Designer / static-site
generator can wrap this.

```
HERO
  H1: The bridge that lets your AI agent actually use your Mac.
  Sub: Computer-use SDKs treat the desktop as a black box. cursor-pointer
       gives every click and keystroke a STRUCTURED outcome so your agent
       (and you) know whether it worked.
  CTA: View on GitHub  →  github.com/LiuZhiXiong/cursor-pointer

WHY IT EXISTS
  Three short bullets, each a real failure mode the product solves:
    1. Synthetic clicks silently ignored by Electron apps
    2. Agents walking 5 steps in the wrong direction after a stale modal
    3. Permission revocation looped on black screenshots

HOW IT WORKS (3-panel diagram, can be ascii in v0)
  Agent → cursor-pointer → macOS → cursor-pointer → Agent (with outcome)

PROOF
  Live code snippet (the README's "30-second example")
  + the 90-second demo video embedded

WHO IT'S FOR
  "AI agent developers building computer-use features on macOS who are
   tired of debugging silent failures."

GETTING STARTED
  git clone + npm run dev + pip install + first run

PRICING / LICENSE
  MIT license. Free. (Add paid tier later when there's evidence.)

CREDITS
  Built solo, Tauri + axum + enigo + xcap. Powered by Claude.
```

---

## Distribution sequence (ranked by ROI)

1. **README** updated first (already shipped — `6781451`). This is the
   primary inbound surface from anyone googling the repo.
2. **GitHub release** with the 90s video embedded in the release notes.
   Tag a `v0.2.0` (or appropriate) so the release page has visible
   activity.
3. **Twitter/X post** linking to the GitHub release. Tag relevant AI-dev
   accounts (judiciously — no spray).
4. **HN Show post** ("Show HN: cursor-pointer — closed-loop computer
   control for AI agents") timed for a US-morning peak.
5. **Anthropic / OpenAI / agent-builder Discord channels** — answer
   existing "anyone built reliable Mac click verification?" threads with
   "I built this, would love feedback."

Defer until after first 50 GitHub stars:
   - LinkedIn / longer-form blog posts
   - Paid promotion
   - Custom landing page beyond the README

---

## Success criteria for the demo + launch

| Metric                                | 7-day target | How to measure |
| ------------------------------------- | ------------ | -------------- |
| GitHub stars                          | +25          | repo dashboard |
| Twitter post impressions              | 5k+          | post analytics |
| GitHub clones (unique)                | 30+          | Insights → Traffic |
| `npm run dev` first-run completed     | (unknowable without telemetry — skip) | — |
| Inbound issue / PR from non-author    | 1+           | GitHub notifications |
| One inbound "can I pay for X feature" inquiry | 1     | DM / issue thread |

If 7 days pass with <5 stars and zero engagement, the storyboard / pitch
needs revision before doing a second push.
