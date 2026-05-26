# Gumroad listing — cursor-pointer signed .dmg ($49)

Paste-ready blocks for the Gumroad creator dashboard. Each section maps to a Gumroad field.

---

## 1. Product name

*(Gumroad field: "Name", ≤ 60 chars)*

```
cursor-pointer for Mac — signed .dmg (skip the build)
```

(54 chars)

---

## 2. Summary / short description

*(Gumroad field: "Summary", ≤ 300 chars — shows up in search and on the checkout page)*

```
A notarized, ready-to-run macOS build of cursor-pointer — the closed-loop bridge that lets your AI agent actually use your Mac and know when its clicks worked. Drag to /Applications and go. No Rust toolchain, no 15-minute cold build, no Gatekeeper "unidentified developer" dance.
```

(290 chars)

---

## 3. Full description

*(Gumroad field: "Description", rich text. Paste as-is — Gumroad accepts basic Markdown.)*

```markdown
**Your AI agent thinks it clicked Submit. Did it actually work?** cursor-pointer is the macOS daemon + Python SDK that gives every click and keystroke a structured outcome, so your agent stops guessing. This listing is the ready-to-run, signed-and-notarized **v0.2.0** build.

### Who this is for

You're a developer building AI agents that need to use a Mac. You've already read the README. You believe the closed-loop verify story is worth trying. But you do **not** want to:

- install the Rust toolchain
- wait 10–15 minutes for a cold `cargo build`
- right-click → Open and answer "yes I really want to run this unsigned thing"
- explain to your teammate's Mac why Gatekeeper is yelling

If 15 minutes of your time is worth more than $49, this is the shortcut.

### What you get

- **`CursorPointer_0.2.0_universal.dmg`** — signed with an Apple Developer ID and notarized by Apple. Runs on macOS 12+, Apple Silicon and Intel.
- Drag to `/Applications`, double-click, grant Accessibility + Screen Recording, done.
- Same binary as the open-source build — same closed-loop verify, same AXPress path for Electron apps (Slack, Discord, etc.), same declarative verb registry, same 173 tests passing.
- Free upgrades to every future v0.x release for the lifetime of the v0 series — re-download from your Gumroad library.

### What this is NOT

- **Not a license.** cursor-pointer is MIT-licensed and free. The source is on GitHub. If you want to build it yourself, you can — and I'll cheer you on. You're paying for a prebuilt binary, not for permission to use the software.
- **Not a support contract.** I'll answer "the .dmg won't open" emails because that's me failing to ship a working binary. I won't write your agent for you.
- **Not a subscription.** One-time $49. No auto-renewal, no seat tracking.

### Why I'm charging for an MIT thing

Honest answer: I'm a solo developer trying to find out if there's a willingness-to-pay signal for cursor-pointer before I sink another six months into it. The MIT code is and will stay free. Charging for the convenience build is the cleanest experiment I could design — it tests "do people value this enough to pay for a shortcut?" without locking anyone out of the actual software. The first $249 of revenue earns back my Claude Max subscription, which is what's funding the development time in the first place. After that I'll know whether to keep building, change direction, or open up paid features.

If that framing feels wrong to you, the GitHub build path is one `git clone` away and I won't be offended. If it feels fair, thank you — you're directly buying my next month of work on this.

### Refund policy

7 days, no questions asked. Email me from the address you bought with and I'll refund. I'd rather you have your $49 back than feel stuck with software that didn't fit.

### Free build path

Source, build instructions, and the same binary you'd produce yourself:
https://github.com/LiuZhiXiong/cursor-pointer

— Zhixiong (the solo dev). Reply to your purchase email to reach me directly.
```

---

## 4. Price

*(Gumroad field: "Price")*

```
$49.00 USD — one-time
```

---

## 5. Pay-what-you-want toggle

*(Gumroad field: "Pay what you want")*

```
OFF
```

**Why:** the whole point of this listing is a willingness-to-pay experiment with a clean price signal. PWYW muddies the data — a $5 sale and a $49 sale tell me very different things about whether $49 is the right number, and PWYW collapses that signal into noise. Single fixed price, see who bites.

---

## 6. Quantity limit

*(Gumroad field: "Maximum number of purchases")*

```
(leave blank — unlimited)
```

**Why we're NOT limiting:** artificial scarcity is dishonest for a digital good. The marginal cost of a 50th sale is the same as the 1st (zero). Saying "only 100 available" would be a manipulation tactic, not a fact about the product. If we ever genuinely cap it (e.g., to keep support load manageable while solo), we'll say *why* in the listing, not invent a fake-scarcity number.

---

## 7. Tags suggestion

*(Gumroad field: "Tags", 3–5 tags)*

```
macos
developer-tools
ai-agents
automation
python
```

---

## 8. Thumbnail spec

*(Gumroad field: "Cover" / product image. No design produced — describe the goal for a designer or Figma hack.)*

**Dimensions:** 1280 × 720 (Gumroad's recommended cover ratio).

**What it should communicate in under 2 seconds of scrolling:**

1. **This is a Mac app.** Include the cursor-pointer `.icns` icon (or a clean .dmg/Finder mockup) prominently in the upper-left or center-left. Mac users recognize the disk-image visual instantly.
2. **The closed-loop value prop.** Right side: a single line of monospaced terminal text in a light-on-dark code block:
   ```
   [STEP 3] click 5  → status=ok path=ax_press
   ```
   This is the actual signature of the product. Anyone who's debugged a silently-failing agent will read that line and understand.
3. **One headline, ≤ 7 words**, top or bottom band:
   *"Your agent knows when clicks worked."*
4. **Price/format hint in small text** (optional): `signed .dmg · macOS 12+ · $49`

**Avoid:** stock photos of robots, generic "AI" gradients, hands-on-keyboard imagery. The thumbnail should look like a developer tool, not a SaaS landing page.

**Color direction:** dark background (matches the terminal aesthetic and the cursor-pointer overlay panel), one accent color for the status line (green `ok` is fine — it's the truth).

---

## 9. Refund policy text

*(Gumroad field: dedicated "Refund policy", ≤ 500 chars)*

```
7-day refund, no questions asked. If anything's broken, doesn't run on your Mac, or just isn't what you expected — reply to your purchase email within 7 days and I'll refund in full. I'm a solo developer and I'd rather you have your money back than feel stuck. The software is MIT-licensed and the source stays on GitHub regardless of refund status, so you lose nothing by trying it.
```

(427 chars)

---

## Post-purchase email draft

*(Gumroad field: "Content" / "Email after purchase". This is what Gumroad sends the buyer immediately after payment. ~200 words.)*

**Subject:** Your cursor-pointer .dmg is ready

**Body:**

```
Thanks for buying cursor-pointer. Download link below — let's get you to a verified click in under 2 minutes.

→ Download: CursorPointer_0.2.0_universal.dmg
   [Gumroad-provided download URL]
   SHA-256: (paste the dmg checksum here at upload time)

Install in 4 steps:

1. Double-click the .dmg, drag CursorPointer.app to /Applications.
2. First launch: right-click CursorPointer.app → Open. Confirm in the dialog. (macOS does this once per app even when signed; after that it opens like any other app.)
3. macOS will prompt for Accessibility and Screen Recording — System Settings → Privacy & Security. Toggle both ON for CursorPointer, then quit and relaunch the app.
4. Run it. The floating control panel appears. The HTTP API is live at http://127.0.0.1:39213. From here, the README's Python quickstart works as-is:
   https://github.com/LiuZhiXiong/cursor-pointer#python-sdk

Future v0.x releases are free upgrades — you'll get an email with a new download link whenever I ship one. Your Gumroad library always has the latest.

If anything's broken, reply to this email — I'm the solo dev and I'll see it. Refund policy is 7 days, no questions.

— Zhixiong
github.com/LiuZhiXiong/cursor-pointer
```

(~210 words)

---

## Notes for the operator (not part of the listing)

- The .dmg filename in the email assumes `0.2.0` and the universal build. If you ship Apple-Silicon-only first, change to `_aarch64.dmg` and note the architecture in the listing.
- Add the actual SHA-256 to the email at the moment you upload — Gumroad keeps the binary, but the checksum lets buyers verify they got what you uploaded.
- "Free upgrades for the v0 series" is a promise. If you bump to v1.0 and want a paid upgrade, communicate that clearly in advance via the Gumroad mass-email feature, ideally one full minor version before the cutover.
- Gumroad takes ~10% + payment fees. Net per sale at $49 is roughly $42–$43 depending on payment method. First $249 earned back = ~6 sales, not 5. Adjust the "willingness-to-pay" narrative target accordingly.
