#!/usr/bin/env sh
set -eu

WORKER_RUNTIME="${WORKER_RUNTIME:-python3.12}"
WORKER_ARCHITECTURE="${WORKER_ARCHITECTURE:-x86_64}"
BUILD_DIR="${BUILD_DIR:-build/tailwag-worker}"
DIST_DIR="${DIST_DIR:-dist}"
ZIP_NAME="${ZIP_NAME:-tailwag-memory-worker.zip}"
ZIP_PATH="${DIST_DIR}/${ZIP_NAME}"
PROJECT_DIR="$(pwd)"

case "$WORKER_RUNTIME" in
  python3.10|python3.11|python3.12) ;;
  *) printf "%s\n" "WORKER_RUNTIME must be python3.10, python3.11, or python3.12" >&2; exit 2 ;;
esac
case "$WORKER_ARCHITECTURE" in
  x86_64) DOCKER_PLATFORM="linux/amd64" ;;
  arm64) DOCKER_PLATFORM="linux/arm64" ;;
  *) printf "%s\n" "WORKER_ARCHITECTURE must be x86_64 or arm64" >&2; exit 2 ;;
esac
case "$BUILD_DIR" in /*) printf "%s\n" "BUILD_DIR must be relative to the repository" >&2; exit 2 ;; esac
case "$DIST_DIR" in /*) printf "%s\n" "DIST_DIR must be relative to the repository" >&2; exit 2 ;; esac

if ! command -v docker >/dev/null 2>&1; then
  printf "%s\n" "docker is required to build a Lambda-compatible worker zip" >&2
  exit 127
fi

if ! command -v zip >/dev/null 2>&1; then
  printf "%s\n" "zip is required to create the worker archive" >&2
  exit 127
fi
mkdir -p "$DIST_DIR"
rm -rf "$BUILD_DIR"
rm -f "$ZIP_PATH"

export BUILD_DIR ZIP_PATH

docker run --rm \
  --platform "$DOCKER_PLATFORM" \
  --user "$(id -u):$(id -g)" \
  --entrypoint /bin/sh \
  -v "$PROJECT_DIR:/var/task" \
  -w /var/task \
  -e BUILD_DIR \
  -e ZIP_PATH \
  "public.ecr.aws/lambda/python:${WORKER_RUNTIME#python}" \
  -c 'mkdir -p "$BUILD_DIR" && python -m pip install ".[aws]" --target "$BUILD_DIR"'

(
  cd "$BUILD_DIR"
  zip -qr "$PROJECT_DIR/$ZIP_PATH" .

)
printf "%s\n" "$ZIP_PATH"
