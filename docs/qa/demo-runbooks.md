# Demo recording runbooks — human-driven scenarios

These three runbooks cover the 90s-demo scenarios that **cannot be
fully automated** because they depend on a human's timing or on
toggling system-level state (Privacy panel, manual dismissal of a
modal, Electron app-specific behavior).

For the automated half, see `scripts/qa_demo_smoke.py` (covers
SCENARIO 1: TextEdit happy path). All four must pass before the human
hits record on OBS.

> **Order of operations on demo day:**
> 1. `npm run dev` — daemon running.
> 2. `python scripts/qa_demo_smoke.py` — must exit 0.
> 3. Walk SCENARIO 2 below, in a throwaway terminal, once.
> 4. Walk SCENARIO 3 once.
> 5. Walk SCENARIO 4 once (LAST — it revokes the daemon's permission
>    and you have to re-grant before any further runs).
> 6. Only then start OBS and record the take.

Source of truth for the per-step banner format:
`python-client/tools/run_agent.py:1259-1275` (the `_summary = ...`
block). All banner-fragment expectations below quote that format.

---

## SCENARIO 2 — Electron app AXPress beat

**Storyboard ref:** docs/marketing/demo-storyboard.md → "SCENARIO 2:
Electron app AXPress beat" (timestamp 0:35–0:60 in the storyboard
table).

**Point of the beat:** demonstrate that cursor-pointer's AXPress
fallback drives a button in an Electron app where a raw synthetic
click would silently fail. The single load-bearing signal in the
banner is `path=ax_press`.

### Prereqs

| | |
|--|--|
| App installed | Slack desktop (preferred — common, recognizable) OR NeteaseMusic OR VS Code. Anything Electron-based with a clearly-labeled button. |
| App state | Logged in, at a screen with a stable button visible. Slack: the "New message" pencil icon top-right of any channel is reliable. |
| Daemon | Running (`npm run dev`). |
| Permissions | Accessibility + Screen Recording granted. |
| Pre-flight | You have run this scenario at least once in the last 24h and noted the AX path the daemon takes for this button (the daemon's path choice is stable across runs but can shift with app updates). |

### Steps

1. Bring the Electron app to foreground; make sure the target button
   is fully visible (not behind another window).
2. In a terminal:

       cd python-client
       python tools/run_agent.py "click the new message button in Slack"
       # adjust goal phrasing if you picked a different target

3. Watch stdout for the per-step banner.

### Expected banner line

The banner format is:

    [STEP N] click <id>   → status=ok path=ax_press drift=0px (NNms)

The **load-bearing fragments** that the storyboard text references:

- `status=ok`
- `path=ax_press`  ← the entire point of this beat
- `(NNms)` showing a sub-100ms execution time (proves it's AX, not pixel)

### PASS criteria

All of the following must hold:

- [ ] At least one `[STEP N] click ...` banner appears with both
      `status=ok` AND `path=ax_press`.
- [ ] The Electron app visibly responds (panel opens, focus moves,
      etc. — whatever the chosen button does).
- [ ] Agent eventually prints `✓ done verified` OR you can `Ctrl-C`
      cleanly right after the load-bearing banner (this beat does
      not require completion of the whole goal).

### FAIL criteria

Any one of these is a FAIL — fix before recording:

- Banner shows `path=cgevent` or `path=pixel` for the target button
  (means AXPress was not selected — wrong target, or AX tree changed
  in the app's last update).
- Banner shows `status=ok` but the app visually did nothing (means
  the daemon thinks it pressed but the app ignored the press — this
  is exactly the failure mode the product is supposed to detect, so
  if it appears in this beat the storyboard premise is wrong; switch
  targets).
- Banner shows `status=verify_failed` or `status=mismatch_target`.

### If it fails

1. Run `python tools/run_agent.py "<same goal>"` again — sometimes
   the first run cold-starts the AX tree and the second is the
   "real" one.
2. If still failing, pick a different Electron button. Suggested
   fallbacks in order of demo-friendliness:
   - VS Code: the "Source Control" icon in the left activity bar.
   - NeteaseMusic: the play/pause button in the player.
   - Slack: the "+" icon next to "Channels" in the sidebar.
3. If NO Electron app responds with `path=ax_press`, that is a
   product regression, not a recording issue. File an issue, do
   NOT record around it.

---

## SCENARIO 3 — `mismatch_target` on stale UI

**Storyboard ref:** docs/marketing/demo-storyboard.md → "SCENARIO 3:
mismatch_target on stale UI" (timestamp 0:60–0:78).

**Point of the beat:** show that when the UI changes between
*perception* and *action* (a modal dismissed, a button moved), the
daemon catches it and surfaces a structured `mismatch_target` status
rather than clicking the wrong region.

### Prereqs

| | |
|--|--|
| App | Any app with a modal/sheet that can be dismissed by clicking outside it or pressing Esc. Recommended: **System Settings** with any Help / About sheet open, or **TextEdit** with the open-file dialog. |
| Daemon | Running. |
| Permissions | Accessibility + Screen Recording granted. |
| Helper | A second hand on the keyboard is helpful — you need to press Esc with sub-second timing while the agent is mid-step. |
| Practice | You have rehearsed the timing at least twice — the modal must dismiss AFTER the agent has perceived it but BEFORE it executes the click. |

### Steps

1. Open the chosen app and trigger the modal. For TextEdit:

       File → Open... (the open-file sheet appears).

2. In a terminal, with the modal still visible, run:

       cd python-client
       python tools/run_agent.py "in the open dialog, click the Cancel button"

3. Watch the agent's stdout. When you see the planner pick the button
   (a "subgoal: ..." line or a `[STEP N]` banner starting), within
   about **0.5s** press `Esc` (or click outside the sheet) to
   dismiss the modal.
4. Continue watching stdout for the next step's banner.

### Expected banner line

After dismissal the next click-step should print:

    [STEP N] click <id>   → status=mismatch_target path=none — target signature did not match ...

The next line should be:

    ⚠ mismatch_target: ... — re-perception next step, no failure counted

(That second line is also from `run_agent.py:1281-1288`.)

### PASS criteria

- [ ] A `[STEP N] click ...` banner appears with
      `status=mismatch_target`.
- [ ] The follow-up `⚠ mismatch_target: ...` re-perception line
      appears.
- [ ] The agent does NOT crash and does NOT click a random region of
      the screen — it should either retry, replan, or eventually stop
      cleanly.

### FAIL criteria

- Banner shows `status=ok` even though the modal was dismissed
  (means the dismissal was too late — the click already executed
  before signature check; this is a **timing** failure, not a
  product failure — retry).
- Banner shows `status=verify_failed` instead of `mismatch_target`
  (means the signature check passed but post-action verify failed —
  also a different code path; retry with cleaner timing).
- Agent crashes or loops on the dismissed modal indefinitely.

### If it fails

1. Reset state, re-open the modal, run again. Timing is the most
   common reason — practice the Esc-key press until you can
   reliably hit the 0.3–0.8s window after the `[STEP` banner starts.
2. If 3 retries all show `status=ok`, your timing is consistently
   late. Switch to a slower goal so the agent's "perceive →
   execute" gap is wider: a goal that requires the agent to first
   scroll or focus another window before clicking gives you more
   slack.
3. If you NEVER see `status=mismatch_target` across many tries,
   that's a product regression in the signature-check path. File
   issue.

---

## SCENARIO 4 — `permission_denied` mid-run surfacing

**Storyboard ref:** docs/marketing/demo-storyboard.md → "SCENARIO 4:
permission_denied surfacing" (timestamp 0:78–0:85).

**Point of the beat:** show that revoking Screen Recording mid-run
causes the agent to **halt immediately with a structured error**,
NOT loop forever on black screenshots.

> **Run this LAST.** It revokes Screen Recording permission for the
> daemon, and you'll need to re-grant it (System Settings → Privacy
> → Screen Recording → toggle daemon back on) before any further
> recording or testing.

### Prereqs

| | |
|--|--|
| Daemon | Running. |
| Permissions | Accessibility + Screen Recording **currently granted** (you can't revoke what isn't granted). |
| System Settings | Pre-opened to Privacy & Security → Screen Recording, with the daemon row visible — you'll be toggling it during the run. |
| Goal | Any goal that takes the agent at least 5 steps so you have time to flip the toggle. "Open Mail and click the first unread message" is a reliable medium-length goal. |

### Steps

1. Position System Settings on your second monitor (or in a
   side-by-side window) so the toggle is one click away.
2. In a terminal, run:

       cd python-client
       python tools/run_agent.py "open Mail and click the first unread message"

3. After you see 2–3 `[STEP N]` banners scroll past (i.e. the agent
   has clearly been running successfully), switch to System
   Settings and toggle Screen Recording **off** for the daemon.
4. Watch the terminal for the halt line.

### Expected banner line

Exactly:

    !! permission denied — halting loop: permission_denied: screen_recording

(That string is emitted by `run_agent.py:1279`.) The agent process
should then exit with **code 2**.

### PASS criteria

- [ ] The `!! permission denied — halting loop: permission_denied:
      screen_recording` line appears within **2 steps** of you
      toggling the permission off.
- [ ] The agent process exits with code 2 (check with `echo $?`
      after the run).
- [ ] The terminal does NOT continue to print step banners after
      the halt line.

### FAIL criteria

- Agent prints step banners with `status=verify_failed` or similar
  but does NOT print the halt line (means the permission_denied
  error from the daemon is being swallowed or mis-classified —
  product bug).
- Agent prints the halt line but exits with code 0 or 1 (means the
  exit-code contract is broken).
- Agent loops indefinitely on what looks like black/empty
  screenshots (the original failure mode this feature exists to
  fix — product regression).

### If it fails

1. Confirm Screen Recording really did toggle off (sometimes macOS
   prompts for a daemon restart — if it does, the daemon may have
   already cached the previous decision; restart `npm run dev` and
   retry).
2. Check the daemon's terminal: it should be logging a
   `screen_recording_denied` or similar error. If it isn't, the
   error isn't even reaching the API surface.
3. If the halt line appears but rc is wrong, that's a one-line fix
   in `run_agent.py`. Ping engineer; do not record around it.

---

## Re-grant checklist (after SCENARIO 4)

After running scenario 4, **before doing anything else**:

1. System Settings → Privacy & Security → Screen Recording → toggle
   daemon **on**.
2. macOS may require you to quit and re-launch the daemon. Stop
   `npm run dev` (Ctrl-C) and restart it.
3. `python scripts/qa_demo_smoke.py --dry-run` — confirms perm is
   back.

Only then proceed to record.
