# First-100-Users Funnel — cursor-pointer

**Status:** zero current users. $249 milestone is gated by distribution, not
product. This doc surfaces the funnel assumptions so we can falsify them
before pouring time into channels that won't return it.

---

## 1. Acquisition surface — where the first 100 actually come from

Ranked least-confident first, because that's the honest order.

1. **Twitter/X — least confident.** The launch storyboard treats Twitter as a
   primary channel, but the author account has effectively **zero followers
   in the AI-agent niche** today. A cold post lands at maybe 200–500
   impressions through hashtags alone. Tagging Anthropic / OpenAI dev
   accounts is the only realistic amplifier and that's a coin flip. Honest
   reach estimate: **5–20 click-throughs** unless something gets quote-tweeted
   by a known account.
2. **Show HN — medium confidence.** "Show HN: closed-loop computer control
   for AI agents on macOS" hits an audience that already cares about agent
   reliability. A front-page brush, even at rank 20, is **500–2000
   click-throughs**. Falls off the page in 6 hours though, so it's a
   one-shot. Title and the first comment matter more than the post body.
3. **Agent-builder Discord / Slack threads — highest confidence per visit,
   lowest reach.** Anthropic dev Discord, computer-use-tagged threads,
   browser-use community. Posting "I hit this exact problem and built a fix"
   in an existing thread converts at ~30%+ but each thread is **5–15 eyeballs**.
   We need 8–10 threads to get to 100 visits, which is a week of patient
   posting, not a launch event.

Channels deliberately deprioritized: LinkedIn (wrong audience), paid ads (no
LTV signal yet), blog SEO (months of lag), Product Hunt (skews B2B
non-technical, and we have no landing page).

**Top assumption to falsify in week 1:** that Show HN actually delivers the
500+ visits. If it flops, the funnel is starved at the top and channels 1
and 3 cannot make up the gap alone.

---

## 2. Landing moment — first 5 seconds on the README

What the user sees (lines 1–18 of `README.md`):

- H1 + one-line pitch: *"The bridge that lets your AI agent actually use
  your Mac."* — clear enough.
- Paragraph naming the specific pain: *"silent click failure, Electron, hours
  debugging."* — this lands for the right reader.
- Five bullets covering closed-loop verify, AXPress, permission surfacing,
  verb registry, 173 tests / MIT.

**What works:** the pain statement is concrete. A reader who has shipped a
computer-use agent recognizes "Electron app ignoring synthetic event" in <2
seconds.

**Gaps:**
- **No hero gif / video.** The 90s demo is storyboarded but not embedded.
  Right now the first 5 seconds is all text. A 10–15s looping gif of a
  `[STEP N] status=ok` banner would do more lifting than any sentence.
- **No social proof above the fold.** "173 tests, MIT" is buried in the
  5th bullet. Stars count (currently 0–single-digit) is the dominant signal
  GitHub itself shows; we can't fix that, but we can move "173 tests" up.
- **"Quick start" requires Rust toolchain + Node 18 + Xcode CLT.** That
  shows up at line 44, after the value prop. Fine — but it means
  click-to-running is not 60 seconds. See section 3.

---

## 3. First 60-second success — clone to first `status=ok` banner

The honest path:

1. `git clone` (5s)
2. `cd cursor-pointer && npm install` — **30–90s, leaks here on slow networks
   or missing Node**
3. `npm run dev` — opens Tauri shell, triggers Rust compile on first run.
   **First-run Rust compile is 2–5 minutes, not 60 seconds.** Funnel
   reality: the 60-second number is a lie unless we ship a prebuilt `.dmg`.
4. Floating panel appears → permission prompts fire for Accessibility +
   Screen Recording → **user has to leave the app, open System Settings,
   toggle two switches, return, relaunch**. Major leak.
5. `cd python-client && pip install -e ".[ocr]"` — another minute, plus
   tesseract / OCR deps may break on fresh machines.
6. `python tools/run_agent.py "open TextEdit and type hello"` — first
   `[STEP N] status=ok` banner. If we got here, conversion is high; user
   has invested 10+ minutes.

**True median time-to-first-banner: 8–15 minutes, not 60 seconds.** The
README's "see it work in 30 seconds" code block is aspirational, not
runnable as-is (it has `ax_press_fn=...` placeholders).

---

## 4. Drop-off points — three specific moments users quit

1. **Permission grant dance (step 4 above).** Hypothesis: 40%+ bounce
   because System Settings → Privacy → toggle two switches → restart app is
   four context switches. Smallest fix: a `npm run doctor` (or in-panel
   button) that opens the exact Privacy panes via `x-apple.systempreferences:`
   URLs and reports which permissions are missing. One screen, one click.
2. **`pip install -e ".[ocr]"` fails on fresh Python.** Hypothesis: OCR
   extras pull tesseract bindings that need Homebrew preinstall.
   Smallest fix: make `[ocr]` optional in the docs, lead with the
   no-OCR install, add a one-line "if OCR breaks, skip it — the agent
   still runs" note.
3. **First `run_agent.py` invocation needs an API key for the LLM.** The
   README doesn't mention this above the fold. Hypothesis: a user gets to
   step 6 and hits `ANTHROPIC_API_KEY not set` with no guidance. Smallest
   fix: a single line in Quick Start — "export ANTHROPIC_API_KEY=... before
   running the agent" — and a friendlier error in `run_agent.py` itself.

---

## 5. Retention hypothesis — why a second visit?

Honest answer: **we don't have one yet, and that's the problem.** Run
Journal (the memory/learning feature) was deprioritized, so there is no
"come back and see what your agent learned overnight" pull. The product
today is a *better primitive*, not a *growing asset*.

Second-visit candidates, ranked by plausibility:

- **They're building something with it.** Most realistic. A developer who
  got one demo working integrates cursor-pointer into their own agent;
  the second visit is to read API docs, file an issue, or check for a
  new release. This is the only retention we can credibly claim today.
- **Release cadence.** Shipping a tagged release every 2–3 weeks with a
  visible CHANGELOG gives Watch-ers a reason to re-engage. Cheap to do.
- **A killer recipe.** "Use cursor-pointer + Claude to auto-triage your
  inbox" or similar — one canned, copy-paste workflow that solves a real
  task. We don't have one. Building one is probably higher-leverage than
  any single feature.

Until Run Journal (or equivalent) lands, retention is "developer building
on top of us," which is narrow but legitimate.

---

## 6. First paying user math — how 100 free users become $249

The candidate mechanisms, with the load-bearing assumption made explicit:

- **Hypothesis A — sponsored development / GitHub Sponsors.** 100 users
  → ~3% become Sponsors at $5–$10/mo → ~$15–$30 MRR. Hitting $249 takes
  9–16 months at this rate. **Assumption: 3% sponsor-conversion on a
  free MIT tool, which is generous; the realistic median for solo MIT
  repos is closer to 0.5%.**
- **Hypothesis B — paid managed/hosted version.** Not credible at 100
  users. Hosting a Mac daemon for someone else is operationally
  ridiculous; this is a local-first product by construction.
  **Falsified before we start.**
- **Hypothesis C — paid notarized + signed `.dmg` + priority support,
  $49 one-shot.** 100 users → 5 buyers ($245). Closest to $249 in one
  hit. **Assumption: 5% of free users will pay $49 to skip the
  unsigned-dmg warning and get email support. Testable by adding a
  Gumroad link and seeing if anyone clicks.**
- **Hypothesis D — consulting / integration contracts.** One contract
  pays $249 trivially. **Assumption: a single inbound from the first
  100 users asks "can you help us wire this into our agent." Plausible
  but lumpy.**

**The bet:** Hypothesis C (signed `.dmg` + $49) is the cleanest experiment
because it has a binary success signal and doesn't depend on goodwill.
Ship a Gumroad link in the v0.2.0 release notes, see what happens in 30
days. If zero clicks at 100 users, the willingness-to-pay assumption is
falsified and we pivot to D.

---

## What we are NOT doing in the first 100

- No paid acquisition.
- No landing page beyond the README.
- No telemetry (we will not know first-run success rate; we accept this).
- No Run Journal / memory features pre-launch.
- No multi-OS (macOS only; Windows / Linux requests get a "noted, not now").
