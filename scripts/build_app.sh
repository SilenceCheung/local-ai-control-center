#!/usr/bin/env bash
# Build Local AI.app — Hardened Runtime. Ad-hoc unless a Developer ID identity exists.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APP_DIR="$ROOT/apps/LocalAIApp"
DIST="$ROOT/dist/Local AI.app"
CONTENTS="$DIST/Contents"
MACOS="$CONTENTS/MacOS"
RESOURCES="$CONTENTS/Resources"
ENT="$APP_DIR/Support/LocalAI.entitlements"
RELEASE_BUILD="${RELEASE_BUILD:-0}"

SIGN_ID="-"
if IDENTITY_LINE="$(security find-identity -v -p codesigning 2>/dev/null | grep 'Developer ID Application' | head -1)"; then
  SIGN_ID="$(echo "$IDENTITY_LINE" | sed -E 's/.*"([^"]+)".*/\1/')"
fi

if [[ "$RELEASE_BUILD" == "1" && "$SIGN_ID" == "-" ]]; then
  echo "RELEASE_BUILD=1 requires a Developer ID Application identity; refusing an ad-hoc release." >&2
  exit 6
fi

cd "$APP_DIR"
swift build -c release --package-path "$APP_DIR" --scratch-path "$APP_DIR/.build"
BIN="$(swift build -c release --package-path "$APP_DIR" --scratch-path "$APP_DIR/.build" --show-bin-path)/LocalAI"

rm -rf "$DIST"
mkdir -p "$MACOS" "$RESOURCES"
cp "$BIN" "$MACOS/LocalAI"
cp "$APP_DIR/Support/Info.plist" "$CONTENTS/Info.plist"
cp "$APP_DIR/Support/PrivacyInfo.xcprivacy" "$RESOURCES/PrivacyInfo.xcprivacy"
cp -R "$APP_DIR/Support/en.lproj" "$RESOURCES/"
cp -R "$APP_DIR/Support/zh-Hans.lproj" "$RESOURCES/"
printf 'APPL????' > "$CONTENTS/PkgInfo"

ICON_SRC="$(mktemp -t localai-icon).png"
python3 - "$ICON_SRC" <<'PY'
import struct, zlib, sys, math
path = sys.argv[1]
w = h = 1024
def chunk(tag, data):
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
# Quiet paper field, single ink mark, small status pip. No neon, no stacked rectangles.
bg = (242, 240, 236)
ink = (58, 64, 78)
pip = (62, 118, 86)
def inside_round_rect(x, y, x0, y0, x1, y1, r):
    if x0 + r <= x < x1 - r and y0 <= y < y1: return True
    if x0 <= x < x1 and y0 + r <= y < y1 - r: return True
    corners = ((x0+r, y0+r), (x1-r, y0+r), (x0+r, y1-r), (x1-r, y1-r))
    for cx, cy in corners:
        if (x-cx)**2 + (y-cy)**2 <= r*r: return True
    return False
rows = []
for y in range(h):
    row = bytearray([0])
    for x in range(w):
        if inside_round_rect(x, y, 352, 352, 672, 672, 72):
            row.extend(ink)
        elif (x-700)**2 + (y-700)**2 <= 36*36:
            row.extend(pip)
        else:
            row.extend(bg)
    rows.append(bytes(row))
png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
png += chunk(b"IDAT", zlib.compress(b"".join(rows), 9)) + chunk(b"IEND", b"")
open(path, "wb").write(png)
PY

WORK="$(mktemp -d)"
ICONSET="$WORK/AppIcon.iconset"
mkdir -p "$ICONSET"
sips -s format png -z 16 16 "$ICON_SRC" --out "$ICONSET/icon_16x16.png" >/dev/null
sips -s format png -z 32 32 "$ICON_SRC" --out "$ICONSET/icon_16x16@2x.png" >/dev/null
sips -s format png -z 32 32 "$ICON_SRC" --out "$ICONSET/icon_32x32.png" >/dev/null
sips -s format png -z 64 64 "$ICON_SRC" --out "$ICONSET/icon_32x32@2x.png" >/dev/null
sips -s format png -z 128 128 "$ICON_SRC" --out "$ICONSET/icon_128x128.png" >/dev/null
sips -s format png -z 256 256 "$ICON_SRC" --out "$ICONSET/icon_128x128@2x.png" >/dev/null
sips -s format png -z 256 256 "$ICON_SRC" --out "$ICONSET/icon_256x256.png" >/dev/null
sips -s format png -z 512 512 "$ICON_SRC" --out "$ICONSET/icon_256x256@2x.png" >/dev/null
sips -s format png -z 512 512 "$ICON_SRC" --out "$ICONSET/icon_512x512.png" >/dev/null
cp "$ICON_SRC" "$ICONSET/icon_512x512@2x.png"
iconutil -c icns "$ICONSET" -o "$RESOURCES/AppIcon.icns"
rm -rf "$WORK" "$ICON_SRC"
if [[ -d /Applications/Xcode.app ]] && [[ -d "$APP_DIR/Support/AppIcon.icon" ]]; then
  echo "Icon Composer asset found; compile it in Xcode to replace the single-layer icns (Tahoe appearances)."
else
  echo "App icon is a single-layer icns. Tahoe layered appearances need Icon Composer + Xcode; not required for Developer ID distribution."
fi

codesign --force --deep --options runtime --entitlements "$ENT" --sign "$SIGN_ID" "$DIST"
codesign --verify --verbose=2 "$DIST" || true

if [[ "$SIGN_ID" != "-" ]]; then
  if bash "$ROOT/scripts/notarize.sh" "$DIST"; then
    echo "Notarized and stapled."
  else
    echo "Developer ID signed, not notarized. Run: bash scripts/notarize.sh"
    echo "Needs notarytool keychain profile ${NOTARY_PROFILE:-local-ai-notary}."
    if [[ "$RELEASE_BUILD" == "1" ]]; then
      echo "Release build failed because notarization did not complete." >&2
      exit 7
    fi
  fi
else
  echo "Signed ad-hoc with Hardened Runtime. Notarization skipped (no Developer ID Application identity)."
  echo "Production command after installing Developer ID and the notary profile: RELEASE_BUILD=1 bash scripts/build_app.sh"
fi

if [[ "$RELEASE_BUILD" == "1" ]]; then
  bash "$ROOT/scripts/release_check.sh" "$DIST"
fi

echo "Built $DIST"
echo "Open with: open \"$DIST\""
