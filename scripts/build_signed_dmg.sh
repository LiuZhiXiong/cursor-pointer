#!/usr/bin/env bash
#
# build_signed_dmg.sh — build a signed + notarized + stapled universal macOS .dmg
# for CursorPointer, ready to upload to Gumroad.
#
# Required environment variables:
#   APPLE_ID                — your Apple Developer account email
#   APPLE_PASSWORD          — an APP-SPECIFIC password generated at
#                             https://appleid.apple.com → Sign-In and Security →
#                             App-Specific Passwords. This is NOT your normal
#                             iCloud / Apple ID password. Notarization will
#                             reject the iCloud password.
#   APPLE_TEAM_ID           — 10-character Team ID, visible at
#                             https://developer.apple.com/account → Membership
#   APPLE_SIGNING_IDENTITY  — full identity string as printed by:
#                             `security find-identity -v -p codesigning`
#                             e.g. "Developer ID Application: Jane Doe (ABCDE12345)"
#
# Usage:
#   ./scripts/build_signed_dmg.sh             # real build (signs + notarizes)
#   ./scripts/build_signed_dmg.sh --dry-run   # print the plan, touch nothing
#
# Output:
#   - signed + stapled .dmg path printed at the end
#   - SHA256 of the .dmg (paste alongside the Gumroad upload)
#   - full log at scripts/.last_build.log

set -euo pipefail

# ---------- argument parsing ----------
DRY_RUN=0
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    -h|--help)
      sed -n '2,30p' "$0"
      exit 0
      ;;
    *)
      echo "Unknown argument: $arg" >&2
      exit 2
      ;;
  esac
done

# ---------- locate repo paths ----------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
TAURI_DIR="$REPO_ROOT/src-tauri"
TAURI_CONF="$TAURI_DIR/tauri.conf.json"
TAURI_CONF_BACKUP="$TAURI_DIR/tauri.conf.json.bak.$$"
LOG_FILE="$SCRIPT_DIR/.last_build.log"

# Tee everything to the log file from this point onward.
# In dry-run we still log so the user can inspect the plan.
exec > >(tee "$LOG_FILE") 2>&1

echo "==> build_signed_dmg.sh starting at $(date -u +%FT%TZ)"
echo "    repo:    $REPO_ROOT"
echo "    dry-run: $DRY_RUN"

# ---------- env var validation ----------
MISSING=0
check_var() {
  local name="$1"
  local example="$2"
  if [ -z "${!name:-}" ]; then
    if [ "$DRY_RUN" -eq 1 ]; then
      echo "    (dry-run) $name not set — would use example: $example"
      # shellcheck disable=SC2140
      printf -v "$name" '%s' "$example"
      export "$name"
    else
      echo "ERROR: required env var $name is not set." >&2
      MISSING=1
    fi
  else
    echo "    $name: set"
  fi
}

echo "==> Checking required environment variables"
check_var APPLE_ID                "you@example.com"
check_var APPLE_PASSWORD          "abcd-efgh-ijkl-mnop"
check_var APPLE_TEAM_ID           "ABCDE12345"
check_var APPLE_SIGNING_IDENTITY  "Developer ID Application: Example Name (ABCDE12345)"

if [ "$MISSING" -ne 0 ]; then
  echo "" >&2
  echo "One or more required env vars are missing. See header of this script" >&2
  echo "or scripts/README_signing.md for how to obtain them." >&2
  exit 1
fi

# ---------- cleanup trap ----------
# Restore the original tauri.conf.json no matter how we exit. If we crashed
# mid-build, also delete any half-signed .dmg/.app to avoid confusing the next
# run (a stale unsigned artifact looks identical to a signed one in Finder).
cleanup() {
  local exit_code=$?
  if [ -f "$TAURI_CONF_BACKUP" ]; then
    echo "==> Restoring original $TAURI_CONF"
    mv -f "$TAURI_CONF_BACKUP" "$TAURI_CONF"
  fi
  if [ "$exit_code" -ne 0 ] && [ "$DRY_RUN" -eq 0 ]; then
    echo "==> Build failed (exit $exit_code). Cleaning half-signed artifacts." >&2
    local bundle_dir="$TAURI_DIR/target/universal-apple-darwin/release/bundle"
    if [ -d "$bundle_dir" ]; then
      find "$bundle_dir" -maxdepth 3 -type f \( -name "*.dmg" -o -name "*.app.zip" \) -print -delete || true
    fi
  fi
  exit "$exit_code"
}
trap cleanup EXIT

run() {
  # Print the command, then run it — unless dry-run, in which case just print.
  echo "    \$ $*"
  if [ "$DRY_RUN" -eq 0 ]; then
    "$@"
  fi
}

# ---------- Step 1: inject signingIdentity into a tempfile copy ----------
echo "==> Step 1: inject signingIdentity into tauri.conf.json"
if [ ! -f "$TAURI_CONF" ]; then
  echo "ERROR: $TAURI_CONF not found" >&2
  exit 1
fi

# Inject "signingIdentity" into bundle.macOS. We use python (always available
# on macOS) rather than sed to keep the JSON valid no matter how the file is
# currently formatted. Backup file is only created when we are about to mutate.
if [ "$DRY_RUN" -eq 0 ]; then
  cp "$TAURI_CONF" "$TAURI_CONF_BACKUP"
  python3 - "$TAURI_CONF" "$APPLE_SIGNING_IDENTITY" <<'PY'
import json, sys
path, identity = sys.argv[1], sys.argv[2]
with open(path) as f:
    conf = json.load(f)
bundle = conf.setdefault("bundle", {})
macos  = bundle.setdefault("macOS", {})
macos["signingIdentity"] = identity
with open(path, "w") as f:
    json.dump(conf, f, indent=2)
    f.write("\n")
PY
  echo "    injected signingIdentity into $TAURI_CONF (original backed up)"
else
  echo "    (dry-run) would inject signingIdentity=\"$APPLE_SIGNING_IDENTITY\" into $TAURI_CONF"
fi

# ---------- Step 2: tauri build ----------
echo "==> Step 2: build universal binary"
cd "$REPO_ROOT"
run npx tauri build --target universal-apple-darwin

# ---------- locate produced .dmg ----------
BUNDLE_DIR="$TAURI_DIR/target/universal-apple-darwin/release/bundle"
DMG_PATH=""
if [ "$DRY_RUN" -eq 0 ]; then
  # Pick the most-recent .dmg under the bundle dir.
  DMG_PATH="$(find "$BUNDLE_DIR/dmg" -maxdepth 1 -type f -name '*.dmg' -print0 2>/dev/null \
              | xargs -0 ls -t 2>/dev/null | head -n 1 || true)"
  if [ -z "$DMG_PATH" ] || [ ! -f "$DMG_PATH" ]; then
    echo "ERROR: no .dmg produced under $BUNDLE_DIR/dmg" >&2
    exit 1
  fi
  echo "    produced: $DMG_PATH"
else
  DMG_PATH="$BUNDLE_DIR/dmg/CursorPointer_0.1.0_universal.dmg"
  echo "    (dry-run) expected output: $DMG_PATH"
fi

# ---------- Step 3: notarize ----------
echo "==> Step 3: notarize via xcrun notarytool (this can take 5-15 min)"
run xcrun notarytool submit "$DMG_PATH" \
  --apple-id    "$APPLE_ID" \
  --password    "$APPLE_PASSWORD" \
  --team-id     "$APPLE_TEAM_ID" \
  --wait

# ---------- Step 4: staple ----------
echo "==> Step 4: staple notarization ticket onto the .dmg"
run xcrun stapler staple "$DMG_PATH"

# ---------- Step 5: verify ----------
echo "==> Step 5: verify Gatekeeper acceptance"
run spctl --assess --type execute --verbose "$DMG_PATH" || {
  # spctl returns non-zero on rejection; surface a clearer message.
  echo "ERROR: spctl rejected the signed .dmg. See log above for details." >&2
  exit 1
}

# ---------- Step 6: report ----------
echo "==> Step 6: done"
if [ "$DRY_RUN" -eq 0 ]; then
  SHA256="$(shasum -a 256 "$DMG_PATH" | awk '{print $1}')"
  echo ""
  echo "    Signed + notarized DMG ready for Gumroad upload:"
  echo "    path:   $DMG_PATH"
  echo "    sha256: $SHA256"
  echo ""
  echo "    Log: $LOG_FILE"
else
  echo ""
  echo "    (dry-run) would print the final .dmg path and SHA256 here."
  echo "    Re-run without --dry-run once your Apple Developer ID env vars are set."
fi
