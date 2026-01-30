#!/usr/bin/env bash
set -euo pipefail

# Build script for Unix (single-file) that reuses existing build version (does NOT update it).
# Usage: ./build_exe_unix.sh

root="$(cd "$(dirname "${0}")" && pwd)"
cd "$root"

build_py="$root/src/sgm/_build.py"
if [ ! -f "$build_py" ]; then
  echo "Missing $build_py. Please build Windows or mac first to generate the version file." >&2
  exit 1
fi

# Extract BUILD value from the build file
BUILD=$(sed -n "s/^BUILD = '\\(.*\\)'$/\1/p" "$build_py" || true)
if [ -z "$BUILD" ]; then
  echo "Failed to read BUILD from $build_py" >&2
  exit 1
fi

# Prefer venv python if available
if [ -x "$root/.venv/bin/python" ]; then
  python="$root/.venv/bin/python"
else
  if command -v python3 >/dev/null 2>&1; then
    python="$(command -v python3)"
  else
    python="$(command -v python)"
  fi
fi

echo "Using python: $python"

# Ensure PyInstaller is available
if ! "$python" -m pip show pyinstaller >/dev/null 2>&1; then
  echo "PyInstaller not found in environment; installing..."
  "$python" -m pip install --upgrade pyinstaller
fi

# Clean prior outputs
rm -rf "$root/dist" "$root/build"

# Icon handling (optional). Try common Linux icon file types.
icon_file=""
for candidate in "$root/resources/icon.png" "$root/resources/icon.ico" "$root/resources/icon.icns"; do
  if [ -f "$candidate" ]; then
    icon_file="$candidate"
    echo "Using icon: $icon_file"
    break
  fi
done
if [ -z "$icon_file" ]; then
  echo "Warning: no icon found in resources; building without icon"
fi

# PyInstaller add-data separator on POSIX is ':'
addData="resources:resources"

NAME="SprintGameManager-${BUILD}"

echo "Building single-file binary named: $NAME"

PYI_ARGS=(--noconfirm --clean --onefile --name "$NAME" --paths "src" --add-data "$addData" "main.py")
if [ -n "$icon_file" ]; then
  PYI_ARGS+=(--icon "$icon_file")
fi

"$python" -m PyInstaller "${PYI_ARGS[@]}"

echo "Built: $root/dist/$NAME"
