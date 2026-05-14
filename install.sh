#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
INSTALL_DIR="$HOME/.local/share/claude-linux"
DESKTOP_DIR="$HOME/.local/share/applications"
ICON_DIR="$HOME/.local/share/icons/hicolor/scalable/apps"
BIN_DIR="${HOME}/.local/bin"

mkdir -p "$INSTALL_DIR" "$DESKTOP_DIR" "$ICON_DIR" "$BIN_DIR"

cp "$ROOT_DIR/app.py" "$INSTALL_DIR/app.py"
cp "$ROOT_DIR/launch.sh" "$INSTALL_DIR/launch.sh"
cp "$ROOT_DIR/README.md" "$INSTALL_DIR/README.md"
cp "$ROOT_DIR/assets/claude-linux.svg" "$ICON_DIR/claude-linux.svg"
chmod +x "$INSTALL_DIR/app.py" "$INSTALL_DIR/launch.sh"

cat > "$DESKTOP_DIR/claude.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Claude Linux
Comment=Native Claude desktop client for Linux
Exec=$INSTALL_DIR/launch.sh
Icon=claude-linux
Terminal=false
Categories=Network;Chat;Office;
StartupWMClass=io.github.bakram.claudelinux
EOF

ln -sf "$INSTALL_DIR/launch.sh" "$BIN_DIR/claude-linux-desktop"

command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$DESKTOP_DIR" >/dev/null 2>&1 || true
command -v gtk-update-icon-cache >/dev/null 2>&1 && gtk-update-icon-cache -f -t "$HOME/.local/share/icons/hicolor" >/dev/null 2>&1 || true

echo "Installed Claude Linux to $INSTALL_DIR"
echo "Desktop entry: $DESKTOP_DIR/claude.desktop"
