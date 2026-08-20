#!/usr/bin/env bash
# Build an ad-hoc signed Local AI.app (menu bar gateway manager).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APP_DIR="$ROOT/apps/LocalAIApp"
DIST="$ROOT/dist/Local AI.app"
CONTENTS="$DIST/Contents"
MACOS="$CONTENTS/MacOS"
RESOURCES="$CONTENTS/Resources"

cd "$APP_DIR"
swift build -c release --package-path "$APP_DIR" --scratch-path "$APP_DIR/.build"
BIN="$(swift build -c release --package-path "$APP_DIR" --scratch-path "$APP_DIR/.build" --show-bin-path)/LocalAI"

rm -rf "$DIST"
mkdir -p "$MACOS" "$RESOURCES"
cp "$BIN" "$MACOS/LocalAI"
cp "$APP_DIR/Support/Info.plist" "$CONTENTS/Info.plist"
printf 'APPL????' > "$CONTENTS/PkgInfo"

ICON_SRC="$(mktemp -t localai-icon).png"
python3 - "$ICON_SRC" <<'PY'
import struct, zlib, sys
path = sys.argv[1]
w = h = 1024
def chunk(tag, data):
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
bg, accent, mark = (246, 245, 242), (74, 95, 193), (62, 123, 82)
rows = []
for y in range(h):
    row = bytearray([0])
    for x in range(w):
        if 430 <= x < 594 and 430 <= y < 594:
            row.extend(accent)
        elif 586 <= x < 650 and 586 <= y < 650:
            row.extend(mark)
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

codesign --force --deep --sign - "$DIST"
echo "Built $DIST"
echo "Open with: open \"$DIST\""
