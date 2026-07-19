#!/bin/bash
# Download Tailwind CSS standalone CLI + daisyUI bundle, then build app.css.
# No npm/Node. Binary + daisyui.mjs land in .bin/ (gitignored).
# Usage: scripts/tailwind.sh [build|watch]   (default: build)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BIN="$ROOT/.bin"
TW="$BIN/tailwindcss"
IN="$ROOT/app/static/src/input.css"
OUT="$ROOT/app/static/css/app.css"
MODE="${1:-build}"

mkdir -p "$BIN" "$ROOT/app/static/css"

# ponytail: resolve OS/arch from uname; covers macOS + linux x64/arm64.
# Add windows/musl branches when a target actually needs them.
os="$(uname -s)"; arch="$(uname -m)"
case "$os-$arch" in
  Darwin-arm64)  tw_asset="tailwindcss-macos-arm64" ;;
  Darwin-x86_64) tw_asset="tailwindcss-macos-x64" ;;
  Linux-aarch64) tw_asset="tailwindcss-linux-arm64" ;;
  Linux-x86_64)  tw_asset="tailwindcss-linux-x64" ;;
  *) echo "Unsupported OS/arch: $os-$arch" >&2; exit 1 ;;
esac

if [ ! -x "$TW" ]; then
  echo "Downloading Tailwind standalone ($tw_asset)..." >&2
  curl -sLo "$TW" "https://github.com/tailwindlabs/tailwindcss/releases/latest/download/$tw_asset"
  chmod +x "$TW"
fi
if [ ! -f "$BIN/daisyui.mjs" ]; then
  echo "Downloading daisyUI bundle..." >&2
  curl -sLo "$BIN/daisyui.mjs" "https://github.com/saadeghi/daisyui/releases/latest/download/daisyui.mjs"
fi

if [ "$MODE" = "watch" ]; then
  exec "$TW" -i "$IN" -o "$OUT" --watch
else
  "$TW" -i "$IN" -o "$OUT" --minify
  echo "Built $OUT" >&2
fi
