# Signing & notarizing the CursorPointer .dmg

`scripts/build_signed_dmg.sh` produces a **signed, notarized, stapled,
universal (Intel + Apple Silicon)** `.dmg` ready to upload to Gumroad.
Before running it, you need four pieces of information from Apple.

## 1. Apple Developer account — $99/year

macOS refuses to launch unsigned downloaded apps with anything friendlier
than "this is damaged, move to trash." Avoiding that requires an
**Apple Developer Program** membership at
<https://developer.apple.com/programs/> — **$99 USD/year**. No free tier
produces a notarizable Developer ID certificate.

Once enrolled (can take 24-48h to activate), open Xcode → Settings →
Accounts → your Apple ID → Manage Certificates → `+` →
**Developer ID Application**. Xcode installs the cert into your login
keychain. Verify with:

```bash
security find-identity -v -p codesigning
```

You should see a line like
`Developer ID Application: Your Name (ABCDE12345)`.
That entire string (minus the leading `N)` index) is your
`APPLE_SIGNING_IDENTITY`.

## 2. App-specific password (NOT your iCloud password)

Notarization uses an app-specific password, not your normal login.

1. Go to <https://appleid.apple.com>
2. Sign in → **Sign-In and Security** → **App-Specific Passwords**
3. Click `+`, label it `cursorpointer-notarize`, copy the 16-char string
   (format: `abcd-efgh-ijkl-mnop`)

That string is `APPLE_PASSWORD`. If you ever lose it, just revoke and
re-issue — it's not your real password.

## 3. Team ID

<https://developer.apple.com/account> → **Membership details** → 10-char
alphanumeric **Team ID**. That's `APPLE_TEAM_ID`. (Same value as the
parenthesized code at the end of your signing identity.)

## 4. Run the build

```bash
export APPLE_ID="you@example.com"
export APPLE_PASSWORD="abcd-efgh-ijkl-mnop"
export APPLE_TEAM_ID="ABCDE12345"
export APPLE_SIGNING_IDENTITY="Developer ID Application: Your Name (ABCDE12345)"

./scripts/build_signed_dmg.sh --dry-run   # sanity check first
./scripts/build_signed_dmg.sh             # real build, ~10-20 min
```

Output lands at
`src-tauri/target/universal-apple-darwin/release/bundle/dmg/CursorPointer_<version>_universal.dmg`
and the script prints the SHA256.

## 5. Upload to Gumroad

1. Gumroad dashboard → **Products** → **New product** → **Digital product**
2. Upload the `.dmg`
3. In the description, paste the SHA256 from the script output so buyers
   can verify integrity
4. Publish

## Troubleshooting

- **Notarization rejected: "The signature does not include a secure
  timestamp."** Your build skipped `--timestamp` somewhere — re-run with
  a clean target dir: `rm -rf src-tauri/target/universal-apple-darwin`
  then retry. Tauri passes the timestamp flag by default; this usually
  means a cached unsigned artifact got picked up.
- **Notarization rejected: "hardened runtime missing."** Confirm
  `tauri.conf.json` `bundle.macOS.minimumSystemVersion` is `10.15`+.
  For per-binary detail, run `xcrun notarytool log <submission-id>
  --apple-id ... --password ... --team-id ...`.
