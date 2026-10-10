#!/bin/sh
# Installs the Carpatic geek tools (carpatic router, menu, shortcut sheet, dev environments, web apps, hooks, theme packs, dotfiles).
# Run as root after desktop/ and configurator/ are installed. Idempotent.  Options: CAPTURE=1 also installs ffmpeg, satty, redshift.
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
PREFIX=${PREFIX:-/usr/local}
LIB=$PREFIX/lib/carpatic-geek
SHARE=$PREFIX/share/carpatic/geek
[ "$(id -u)" = 0 ] || { echo "carpatic geek install: run as root (doas sh geek/install.sh)" >&2; exit 1; }

if command -v apk >/dev/null 2>&1 && [ "${SKIP_PACKAGES:-0}" != 1 ]; then
  pk=$(grep -v '^#' "$HERE/packages.txt" | grep -v '^$' | tr '\n' ' ')
  [ "${CAPTURE:-0}" = 1 ] && pk="$pk $(grep -v '^#' "$HERE/packages-capture.txt" | grep -v '^$' | tr '\n' ' ')"
  # shellcheck disable=SC2086
  apk add --no-cache $pk >/dev/null || { echo "carpatic geek install: could not install packages; check the network" >&2; exit 1; }
fi

mkdir -p "$PREFIX/bin" "$LIB" "$SHARE"
for f in "$HERE"/bin/*; do [ -f "$f" ] && install -m 755 "$f" "$PREFIX/bin/$(basename "$f")"; done
for f in "$HERE"/lib/*; do [ -f "$f" ] && install -m 644 "$f" "$LIB/$(basename "$f")"; done
cp -a "$HERE"/share/. "$SHARE"/
[ -f "$HERE/../docs/USER-GUIDE-geek.md" ] && install -m 644 "$HERE/../docs/USER-GUIDE-geek.md" "$SHARE/USER-GUIDE-geek.md"
mkdir -p "$PREFIX/share/applications" "$PREFIX/share/man/man1"
install -m 644 "$HERE/share/applications/"*.desktop "$PREFIX/share/applications/"
install -m 644 "$HERE/share/man/carpatic.1" "$PREFIX/share/man/man1/carpatic.1"
# completions: where bash, zsh and fish look
install -D -m 644 "$HERE/share/completions/carpatic.bash" /usr/share/bash-completion/completions/carpatic
install -D -m 644 "$HERE/share/completions/_carpatic" /usr/share/zsh/site-functions/_carpatic
install -D -m 644 "$HERE/share/completions/carpatic.fish" /usr/share/fish/vendor_completions.d/carpatic.fish
# clipboard watcher (needs the X11 and XFixes headers only while building)
if command -v apk >/dev/null 2>&1 && ! [ -x "$PREFIX/bin/carpatic-clipwatch" ] && [ "${SKIP_PACKAGES:-0}" != 1 ]; then
  apk add --no-cache --virtual .carpatic-geek-build build-base libx11-dev libxfixes-dev >/dev/null
  cc -O2 -o "$PREFIX/bin/carpatic-clipwatch" "$HERE/src/clipwatch.c" -lX11 -lXfixes && echo "built carpatic-clipwatch"
  apk del .carpatic-geek-build >/dev/null
elif ! [ -x "$PREFIX/bin/carpatic-clipwatch" ] && command -v cc >/dev/null 2>&1; then
  cc -O2 -o "$PREFIX/bin/carpatic-clipwatch" "$HERE/src/clipwatch.c" -lX11 -lXfixes || echo "note: carpatic-clipwatch not built; clipboard history falls back to polling"
fi
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$PREFIX/share/applications" 2>/dev/null || true
[ -f "$HERE/share/VERSION" ] && install -D -m 644 "$HERE/share/VERSION" "$PREFIX/share/carpatic/VERSION"
echo "Carpatic geek tools installed. Try: carpatic --help"
