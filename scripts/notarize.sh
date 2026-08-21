#!/usr/bin/env bash
# Notarize an already-signed Local AI.app (Developer ID + notarytool profile).
# Does not add App Sandbox. Safe to run after scripts/build_app.sh.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APP="${1:-$ROOT/dist/Local AI.app}"
PROFILE="${NOTARY_PROFILE:-local-ai-notary}"
ZIP="$ROOT/dist/LocalAI.zip"

if [[ ! -d "$APP" ]]; then
  echo "Missing app: $APP" >&2
  echo "Build first: bash scripts/build_app.sh" >&2
  exit 1
fi

if ! security find-identity -v -p codesigning 2>/dev/null | grep -q 'Developer ID Application'; then
  echo "No Developer ID Application identity in the keychain. Signed ad-hoc builds cannot be notarized." >&2
  exit 2
fi

if ! command -v xcrun >/dev/null; then
  echo "xcrun not found; install Xcode or Command Line Tools with notarytool." >&2
  exit 3
fi

if ! xcrun notarytool history --keychain-profile "$PROFILE" >/dev/null 2>&1; then
  echo "notarytool profile '$PROFILE' is missing." >&2
  echo "Create it once: xcrun notarytool store-credentials $PROFILE --apple-id <id> --team-id <team> --password <app-specific-password>" >&2
  exit 4
fi

echo "Submitting $APP for notarization (profile $PROFILE)…"
rm -f "$ZIP"
ditto -c -k --keepParent "$APP" "$ZIP"
xcrun notarytool submit "$ZIP" --keychain-profile "$PROFILE" --wait
if xcrun stapler staple "$APP"; then
  echo "Stapled notarization ticket onto $APP"
else
  echo "Notarization succeeded or is pending, but stapler failed. Gatekeeper may still need a network check on first launch." >&2
  exit 5
fi
echo "Notarized: $APP"
