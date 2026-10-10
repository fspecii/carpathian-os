#!/bin/sh
# Installs the Carpathian theme picker (carpatic-theme-picker, carpatic-look). Run as root after configurator/ is installed. Idempotent.
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
PREFIX=${PREFIX:-/usr/local}
LIB=$PREFIX/lib/carpatic-themepicker
[ "$(id -u)" = 0 ] || { echo "carpatic theme picker install: run as root (doas sh themepicker/install.sh)" >&2; exit 1; }
if command -v apk >/dev/null 2>&1 && [ "${SKIP_PACKAGES:-0}" != 1 ]; then
  pk=$(grep -v '^#' "$HERE/packages.txt" | grep -v '^$' | tr '\n' ' ')
  # shellcheck disable=SC2086
  apk add --no-cache $pk >/dev/null || { echo "carpatic theme picker install: could not install packages; check the network" >&2; exit 1; }
fi
mkdir -p "$PREFIX/bin" "$LIB" "$PREFIX/share/applications"
for f in carpatic-theme-picker carpatic-theme-picker-ui carpatic-look; do install -m 755 "$HERE/bin/$f" "$PREFIX/bin/$f"; done
for f in "$HERE"/lib/*.py; do install -m 644 "$f" "$LIB/$(basename "$f")"; done
install -m 644 "$HERE/share/applications/carpatic-theme-picker.desktop" "$PREFIX/share/applications/"
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$PREFIX/share/applications" 2>/dev/null || true
echo "Carpathian theme picker installed. Press Super+Ctrl+Shift+Space, or run: carpatic-theme-picker"
