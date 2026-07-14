#!/usr/bin/env sh
set -eu

PYTHON_BIN="${PYTHON_BIN:-python3}"
BUILD_DIR="${BUILD_DIR:-build/tailwag-worker}"
DIST_DIR="${DIST_DIR:-dist}"
ZIP_NAME="${ZIP_NAME:-tailwag-memory-worker.zip}"
ZIP_PATH="${DIST_DIR}/${ZIP_NAME}"

rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR" "$DIST_DIR"

"$PYTHON_BIN" -m pip install ".[aws]" --target "$BUILD_DIR"

(
  cd "$BUILD_DIR"
  zip -qr "../../${ZIP_PATH}" .
)

printf '%s\n' "$ZIP_PATH"
