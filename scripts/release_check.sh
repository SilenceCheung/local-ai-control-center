#!/usr/bin/env bash
# Production gate for the direct Developer ID distribution channel.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APP="${1:-$ROOT/dist/Local AI.app}"
INFO="$APP/Contents/Info.plist"
PRIVACY="$APP/Contents/Resources/PrivacyInfo.xcprivacy"
ENTITLEMENTS="$(mktemp -t localai-entitlements).plist"
trap 'rm -f "$ENTITLEMENTS"' EXIT

fail() {
  echo "release-check: $*" >&2
  exit 1
}

[[ -d "$APP" ]] || fail "missing app bundle: $APP"
[[ -f "$INFO" ]] || fail "missing Info.plist"
[[ -f "$PRIVACY" ]] || fail "missing PrivacyInfo.xcprivacy"
[[ -x "$APP/Contents/MacOS/LocalAI" ]] || fail "missing executable"

plutil -lint "$INFO" >/dev/null
plutil -lint "$PRIVACY" >/dev/null

[[ "$(/usr/libexec/PlistBuddy -c 'Print :CFBundleIdentifier' "$INFO")" == "com.localai.controlcenter.app" ]] \
  || fail "unexpected bundle identifier"
/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' "$INFO" >/dev/null \
  || fail "missing marketing version"
/usr/libexec/PlistBuddy -c 'Print :CFBundleVersion' "$INFO" >/dev/null \
  || fail "missing build number"
/usr/libexec/PlistBuddy -c 'Print :NSHumanReadableCopyright' "$INFO" >/dev/null \
  || fail "missing copyright"

codesign --verify --deep --strict --verbose=2 "$APP"
SIGNATURE="$(codesign -dvvv "$APP" 2>&1)"
grep -q '^Authority=Developer ID Application:' <<<"$SIGNATURE" \
  || fail "bundle is not signed with Developer ID Application"
grep -q 'flags=.*runtime' <<<"$SIGNATURE" \
  || fail "Hardened Runtime is not enabled"

codesign -d --entitlements :- "$APP" >"$ENTITLEMENTS" 2>/dev/null || true
if plutil -extract com.apple.security.app-sandbox raw "$ENTITLEMENTS" >/dev/null 2>&1; then
  [[ "$(plutil -extract com.apple.security.app-sandbox raw "$ENTITLEMENTS")" != "true" ]] \
    || fail "direct channel must not use the App Sandbox entitlement"
fi

xcrun stapler validate "$APP" >/dev/null \
  || fail "notarization ticket is missing or invalid"

if spctl --status 2>&1 | grep -qi 'assessments disabled'; then
  fail "Gatekeeper assessment is disabled; validate on a Mac with assessments enabled"
fi
spctl --assess --type execute --verbose=4 "$APP"

echo "release-check: PASS — Developer ID, Hardened Runtime, notarization, privacy manifest, and Gatekeeper verified."
