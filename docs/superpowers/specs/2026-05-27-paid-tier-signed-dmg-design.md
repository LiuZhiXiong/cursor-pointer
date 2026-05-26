# Paid Tier — Signed `.dmg` ($49) — design

**Date:** 2026-05-27
**Author:** PM (with @liuzhixiong)
**Status:** approved → ready for execution once Apple credentials arrive

## Problem

Free users hit 10–15 minutes of friction before their first run: clone,
install Rust, `cargo build --release`, grant Accessibility + Screen
Recording, bypass Gatekeeper on an unsigned binary. Funnel doc
(Hypothesis C) assumes ≥5% would pay $49 to skip that. We have no
evidence. This spec is the cheapest experiment that produces a clean
yes/no signal in 30 days.

## Goal

Ship a $49 paid tier on Gumroad delivering a signed, notarized `.dmg`
plus a one-paragraph install guide. Track purchases for 30 days → decide
kill/continue.

**Success criteria:**

1. Listing live on Gumroad within 1 working day of credentials + signed
   `.dmg` in hand.
2. Link present in v0.2.0 release notes and `README.md` install section.
3. After 30 days: **≥3 purchases = signal (continue); 1–2 = re-think;
   0 = kill, pivot to Hypothesis D.**
4. Refund rate <40% (else the product, not WTP, is the problem).

## Non-goals

- **License key / receipt enforcement.** Software is MIT. Paid artifact
  is convenience, not licensing. Anyone can rebuild from source.
- **Multiple tiers.** One SKU, one price.
- **Subscription billing.** Gumroad handles checkout, tax, refunds.
- **A pricing page on a website.** Gumroad page *is* the page.
- **Auto-update.** Static `.dmg`. New release → new asset, manually.
- **Universal binary.** ARM64 only. Intel users get pointed at source.
- **Support SLA.** README points to GitHub Issues, same as free users.

## Decisions (locked)

| Decision | Choice | Rationale |
|---|---|---|
| Price | **$49 one-time** | Matches Hypothesis C. One-time avoids subscription overhead and "is this still maintained" decay. Re-purchase on major version if we want repeat revenue later. |
| Artifact | Signed + notarized `.dmg`, ARM64 only | Notarization required or Gatekeeper still warns — defeats the purpose. |
| Auto-update | None | Buyers get a Gumroad email when we replace the asset. |
| Storefront | Gumroad | Lowest-ceremony; handles tax, EU VAT, refunds. |
| Asset hosting | Gumroad CDN, uploaded manually | No S3, no Cloudflare. |
| Refund policy | **7 days, no questions** (Gumroad default) | Don't fight refunds at this scale. |
| License enforcement | **None.** Software remains MIT. | Stated explicitly to kill bikeshedding. |
| Release cadence | New `.dmg` uploaded manually each tagged release | Automation not worth building until ≥3 buyers exist. |
| Build pipeline | `scripts/build_signed_dmg.sh` (Engineer, parallel) | Takes `APPLE_ID`, `APPLE_PASSWORD`, `APPLE_TEAM_ID` env vars; emits `dist/cursor-pointer-<version>-arm64.dmg`. |

## Architecture

```
  release tag (git)
        │
        ▼
  scripts/build_signed_dmg.sh        ← Engineer's parallel work
   (APPLE_ID, APPLE_PASSWORD,
    APPLE_TEAM_ID env vars)
        │
        ▼
  dist/cursor-pointer-<ver>-arm64.dmg
        │
        ▼ (manual upload, drag-and-drop)
   Gumroad product page
        ├─ checkout (Gumroad)
        ├─ refund handling (Gumroad)
        └─ download link emailed to buyer
```

No changes to `src-tauri/`, `python-client/`, agent runtime, or CI. The
only artifacts this spec produces are the Gumroad listing and the
README/release-notes link.

### Gumroad listing — day-1 contents (the contract)

1. **`.dmg` file** (uploaded as Gumroad asset).
2. **Install instructions, one paragraph:**
   > Download `cursor-pointer.dmg`, double-click, drag to
   > `/Applications`. On first launch, grant Accessibility and Screen
   > Recording permissions in System Settings → Privacy & Security.
3. **"What you're paying for" honesty section** (defended verbatim):
   > cursor-pointer is MIT open-source software. You can build it
   > yourself for free from github.com/<org>/cursor-pointer — about 15
   > minutes plus a Rust toolchain. You're paying $49 for the
   > convenience of a signed, notarized binary that installs in 30
   > seconds without Gatekeeper warnings. No extra features, no
   > private support, no SLA. The software is the same.
4. **Refund policy**, one line: 7-day refund, no questions, via Gumroad.
5. **Support link**: "Bug reports → github.com/<org>/cursor-pointer/issues."

If it doesn't fit on one Gumroad scroll, it doesn't ship. No screenshot
gallery, no testimonials, no roadmap.

## Risks

1. **Apple notarization friction.** First runs fail on entitlements /
   hardened-runtime config. **Mitigation:** We do not list until one
   successful end-to-end notarized build exists locally.
2. **Refund abuse.** Buyer refunds, keeps `.dmg`. **Mitigation:** None.
   MIT — they could have grabbed source for free anyway. Refund rate
   is a quality signal, not a fraud vector.
3. **"Why charge for MIT software" backlash.** Likely on HN/Reddit.
   **Mitigation:** Honesty section pre-empts it. "Software is free;
   the build is $49." Don't argue beyond that.
4. **`.dmg` goes stale between releases.** **Mitigation:** Gumroad
   emails buyers on asset update. We commit to replacing the asset on
   every tagged release for the experiment window. Automate post-30d
   only if experiment continues.
5. **<3 purchases ≠ falsification if no one saw it.** **Mitigation:**
   Link must appear in (a) v0.2.0 release notes, (b) `README.md`
   install section, (c) one HN/Reddit launch post. If reach is the
   bottleneck, that's a different failure mode — we do not move
   goalposts mid-experiment.

## Lines I will defend

- "Let's also add a $99 Pro tier." No. One SKU. See non-goals.
- "Let's add a license key just in case." No. MIT. See decisions.
- "Can we A/B test $39 vs $49?" No. The experiment is "does anyone
  pay," not "what's the optimal price." Optimization needs a
  denominator we don't have yet.
- "Wait until we have a website." No. Gumroad page is the page.

## Kill criteria (re-stated)

30 days after listing goes live:

- **0 purchases** → delist. Hypothesis C falsified. Pivot to D
  (consulting outreach).
- **1–2 purchases** → ambiguous. Keep listed another 30 days unchanged;
  if still <3 cumulative at day 60, delist.
- **≥3 purchases** → signal confirmed. Continue. Next spec covers
  release automation (risk #4) and possibly a second SKU.

The experiment is the spec. The product is incidental.
