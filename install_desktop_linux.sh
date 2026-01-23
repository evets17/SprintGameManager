#!/usr/bin/env bash
set -euo pipefail

# Install .desktop file for Ubuntu/Linux desktop integration.
# Run this after build_exe_linux.sh

root="$(cd "$(dirname "$0")" && pwd)"

exe="$root/dist/SprintGameManager"
icon="$root/resources/icon.png"

if [ ! -f "$exe" ]; then
  echo "Error: $exe not found. Run build_exe_linux.sh first." >&2
  exit 1
fi

if [ ! -f "$icon" ]; then
  echo "Error: $icon not found." >&2
  exit 1
fi

desktop_dir="$HOME/.local/share/applications"
mkdir -p "$desktop_dir"

desktop_file="$desktop_dir/sprintgamemanager.desktop"

cat > "$desktop_file" << EOF
[Desktop Entry]
Name=SprintGameManager
Comment=Sprint Game Manager
Exec=$exe
Icon=$icon
Type=Application
Categories=Game;Utility;
Terminal=false
EOF

chmod +x "$desktop_file"

echo "Installed: $desktop_file"
echo "SprintGameManager should now appear in your application menu."
