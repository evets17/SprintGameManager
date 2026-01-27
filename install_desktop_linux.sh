#!/usr/bin/env bash
set -euo pipefail

# Install .desktop file for Ubuntu/Linux desktop integration.
# Run this after build_exe_linux.sh
#
# Usage:
#   ./install_desktop_linux.sh          # User install (~/.local)
#   sudo ./install_desktop_linux.sh -s  # System-wide install (/usr)

root="$(cd "$(dirname "$0")" && pwd)"

exe="$root/dist/SprintGameManager"
icon_src="$root/resources/icon.png"

if [ ! -f "$exe" ]; then
  echo "Error: $exe not found. Run build_exe_linux.sh first." >&2
  exit 1
fi

if [ ! -f "$icon_src" ]; then
  echo "Error: $icon_src not found." >&2
  exit 1
fi

# Parse arguments
system_install=false
while getopts "s" opt; do
  case $opt in
    s) system_install=true ;;
    *) echo "Usage: $0 [-s]" >&2; exit 1 ;;
  esac
done

if [ "$system_install" = true ]; then
  # System-wide installation (requires root)
  if [ "$EUID" -ne 0 ]; then
    echo "Error: System-wide install requires root. Use: sudo $0 -s" >&2
    exit 1
  fi
  
  bin_dir="/usr/local/bin"
  icon_dir="/usr/share/icons/hicolor/256x256/apps"
  desktop_dir="/usr/share/applications"
  
  mkdir -p "$bin_dir" "$icon_dir" "$desktop_dir"
  
  # Copy executable and icon
  cp "$exe" "$bin_dir/sprintgamemanager"
  chmod +x "$bin_dir/sprintgamemanager"
  cp "$icon_src" "$icon_dir/sprintgamemanager.png"
  
  exe_path="$bin_dir/sprintgamemanager"
  icon_ref="sprintgamemanager"  # Use icon name for system icons
else
  # User installation
  desktop_dir="$HOME/.local/share/applications"
  mkdir -p "$desktop_dir"
  
  exe_path="$exe"
  icon_ref="$icon_src"
fi

desktop_file="$desktop_dir/sprintgamemanager.desktop"

cat > "$desktop_file" << EOF
[Desktop Entry]
Name=Sprint Game Manager
Comment=Manage Intellivision Sprint Console games
GenericName=Game Asset Manager
Exec=$exe_path %F
Icon=$icon_ref
Type=Application
Categories=Game;Utility;FileTools;
Terminal=false
Keywords=intellivision;sprint;rom;game;manager;
StartupWMClass=SprintGameManager
EOF

chmod +x "$desktop_file"

if [ "$system_install" = true ]; then
  # Update icon cache for system install
  if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -f /usr/share/icons/hicolor/ 2>/dev/null || true
  fi
  echo "System-wide install complete:"
  echo "  Executable: $bin_dir/sprintgamemanager"
  echo "  Icon: $icon_dir/sprintgamemanager.png"
  echo "  Desktop: $desktop_file"
else
  echo "User install complete:"
  echo "  Desktop: $desktop_file"
fi

echo "SprintGameManager should now appear in your application menu."
