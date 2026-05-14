#!/usr/bin/env bash
set -euo pipefail

SCRIPT_PATH="$(readlink -f "$0")"
ROOT_DIR="$(cd "$(dirname "$SCRIPT_PATH")" && pwd)"

exec env -i \
  HOME="$HOME" \
  USER="${USER:-bakram}" \
  LOGNAME="${LOGNAME:-bakram}" \
  SHELL="${SHELL:-/bin/bash}" \
  PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin" \
  LANG="${LANG:-en_US.UTF-8}" \
  LC_ALL="${LC_ALL:-en_US.UTF-8}" \
  DISPLAY="${DISPLAY:-:0}" \
  WAYLAND_DISPLAY="${WAYLAND_DISPLAY:-wayland-0}" \
  XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}" \
  XDG_CURRENT_DESKTOP="${XDG_CURRENT_DESKTOP:-ubuntu:GNOME}" \
  XDG_SESSION_TYPE="${XDG_SESSION_TYPE:-wayland}" \
  DBUS_SESSION_BUS_ADDRESS="${DBUS_SESSION_BUS_ADDRESS:-}" \
  XAUTHORITY="${XAUTHORITY:-$HOME/.Xauthority}" \
  PYTHONUNBUFFERED=1 \
  /usr/bin/python3 "$ROOT_DIR/app.py"
