#!/bin/sh
# panel/install.sh : install carpatic-panel and carpatic-flyout (idempotent). DESTDIR and PREFIX are honoured so the packaging agent can reuse it.
#   sh panel/install.sh              -> /usr/local
#   DESTDIR=$pkgdir PREFIX=/usr sh panel/install.sh
set -e
HERE=$(cd "$(dirname "$0")" && pwd)
PREFIX=${PREFIX:-/usr/local}; D=${DESTDIR:-}
LIB=$D$PREFIX/lib/carpatic-panel; BIN=$D$PREFIX/bin
SHARE=$D$PREFIX/share/carpatic/panel/branding
mkdir -p "$LIB/carpatic_panel" "$BIN" "$SHARE"
for asset in "$HERE"/assets/branding/*.svg; do install -m 644 "$asset" "$SHARE/"; done
for f in "$HERE"/lib/carpatic_panel/*.py; do install -m 644 "$f" "$LIB/carpatic_panel/"; done
for b in carpatic-panel carpatic-flyout carpatic-overview carpatic-calendar; do install -m 755 "$HERE/bin/$b" "$BIN/$b"; done
# the scripts look for the library next to themselves, then in /usr/local/lib/carpatic-panel: rewrite for a non-default prefix
[ "$PREFIX" = /usr/local ] || sed -i "s#/usr/local/lib/carpatic-panel#$PREFIX/lib/carpatic-panel#" "$BIN/carpatic-panel" "$BIN/carpatic-flyout" "$BIN/carpatic-calendar"
echo "carpatic-panel installed in $D$PREFIX (run: carpatic-panel run, or set BAR=panel in the profile)"
